# ADR-0003: 跨运行 Runtime Summary Store 与窗口快照

- 状态：Accepted
- 日期：2026-07-16
- 决策范围：运行遥测、placement 历史和性能审计

## 背景

`CellRuntimeSummary v1` 只聚合一次 AnalysisRun。直接把多个 summary 列表交给 placement 存在三个问题：没有明确时间边界、无法从已聚合 P95 正确重算跨运行分位数、也无法判断最近状态和实现版本切换。

placement 必须使用可复盘的历史输入，同时运行历史不能进入 `CellResult` 或 `AnalysisReport`。

## 决策

### 1. Store 保存逐次 trace，不保存不可逆聚合

`RuntimeSummaryStore` 以 `(run_id, span_id)` 作为幂等写入身份，保存 `CellRuntimeTrace v1`。文件系统参考实现按以下维度分区：

```text
cell_id
formula_version
implementation_id
service_id
runtime
finished_at date
```

保留逐次 duration、status 和 retry_count，才能在任意窗口内重新计算 P50、P95、P99、失败率和重试率。

### 2. Placement 只读取显式窗口快照

Store 查询产生 `runtime_summary_snapshot.v1`：

```text
window_started_at / window_ended_at
trace_count / run_count
p50_duration_ms / p95_duration_ms / p99_duration_ms
failure_rate / retry_rate
latest_status / latest_finished_at
```

Planner 把完整 Snapshot 保存到 ExecutionPlan metadata，并把同一 Snapshot 传给所有候选的 placement policy。禁止使用无时间边界的隐式“全历史”。

### 3. 历史按精确版本隔离

聚合键必须同时匹配 Cell、formula_version、implementation_id、service_id 和 runtime。窗口外 trace 自动过期；公式版本或实现身份变化后，新候选从 `no_history` 开始，不继承旧实现的健康状态。

### 4. 成功和失败运行都写历史

Coordinator 返回的成功 trace 和失败 trace 都会进入 Store。写入结果使用 `runtime_summary_write.v1` 审计 attempted、stored 和 duplicate 数量。

历史写入失败不会把一次已经完成的分析改成失败，也不会覆盖原始 Cell 异常；错误必须进入 AnalysisRun metadata。已显式配置的 Store 如果无法读取窗口快照，则 planning 不继续使用不明来源的历史。

### 5. 当前实现保持简单

首版提供进程内 Store 和文件系统 Store。文件系统查询可以扫描分区文件；索引、压缩、并发写优化和远程时序数据库适配留给真实规模证据驱动的后续实现。

## 结果

正向结果：

- placement 的每次历史输入都有 snapshot_id 和明确窗口。
- 分位数来自原始样本，而不是错误聚合多个 P95。
- 小样本、失败率、重试率和最近状态可以统一审计。
- 公式和实现升级不会继承陈旧健康度。
- 本地、Python service、Rust service 和外部 service 可以共享相同历史契约。

约束和代价：

- 文件系统参考实现不适合无限规模或高并发 worker。
- 保存逐次 trace 比只保存 summary 占用更多空间，需要后续 retention 和 compaction 策略。
- Store 读取失败会阻止依赖该历史的 planning，需要运维监控其可用性。

## 放弃的方案

合并多个单次 P95：统计上不能得到真实跨运行 P95。

只保留最近一次 summary：无法形成稳定样本量，也无法计算失败和重试窗口。

按 cell_id 聚合所有版本：新公式或新实现会继承旧版本状态，导致错误 placement。

读取无限全历史：历史永不过期，近期退化会被长期样本稀释，也无法复盘一次 placement 的实际输入边界。
