# ADR-0004: 固定输入性能基线与 CI 回归阈值

- 状态：Accepted
- 日期：2026-07-16
- 决策范围：端到端性能测量、CI 守护与热点迁移证据

## 背景

功能测试只能证明结果正确，不能发现一次改动把本地分析从毫秒级退化到百毫秒或秒级。另一方面，共享 CI runner 的机器、负载和调度存在波动，直接使用紧贴开发机实测值的阈值会产生不稳定告警。

性能变化还必须与公式、输入或结果变化分开报告，避免把业务输出漂移误判成纯性能回归。

## 决策

### 1. 使用版本化固定输入基线

`benchmarks/default_analysis.json` 遵守 `performance_baseline.v1`，固定：

```text
benchmark_id
input_file / input_hash
warmup_runs / measured_runs
expected_node_count
expected decision / formula versions
total P95 threshold / node P95 threshold
reference measurement / threshold rationale
```

输入哈希、公式版本或稳定决策字段变化属于 correctness failure，必须与性能阈值失败分开输出。

### 2. 测量 warm-process 端到端路径

基准先 warm up，再对同一个 Engine 执行 20 次完整分析。总耗时从 `AnalysisEngine.run` 外层测量；节点耗时读取正常 runtime event 中的 executor trace duration，不创建第二套计时协议。

输出 `performance_benchmark_result.v1`，包含总耗时和每个 node 的 sample count、平均值、P50、P95、P99、最大值、最慢节点以及运行环境。

### 3. 首版阈值只拦截数量级退化

2026-07-16 本地 warm-process 参考测量约为：

```text
total P95 < 5ms
slowest node P95 < 0.1ms
```

共享 CI 首版阈值设为：

```text
total P95 <= 100ms
each node P95 <= 10ms
```

阈值故意远宽于参考值，只捕获数量级回归，不充当生产 SLA。后续只能根据持续 CI 样本收紧，不能凭主观感受修改。

### 4. 功能测试与 benchmark 独立运行

`make test` 运行 Python / Rust 功能测试；`make benchmark` 运行性能基线。CI 使用两个独立步骤，结果可以明确区分：

- exit 2：正确性或基线身份漂移。
- exit 3：纯性能阈值回归。
- exit 1：基准配置或执行自身失败。

### 5. Benchmark 不是 Rust 迁移证明

基准只负责定位持续变慢的 node。迁移 Python 逻辑到 Rust 前，仍必须有 profile 证明热点位于具体公式或数据处理路径，并证明跨语言边界收益高于序列化和维护成本。

## 结果

正向结果：

- 固定样例同时守住结果身份和性能数量级。
- 总运行时与 Cell/node 尾延迟使用同一份结构化结果。
- 共享 CI 波动不会轻易造成假阳性。
- 性能回归、结果漂移和基准执行错误拥有不同退出码。
- 最慢 node 为后续 profile 提供稳定入口。

约束和代价：

- 当前基准只覆盖默认 BTC/USD 小样例和 Python 本地执行。
- 宽松阈值不能发现小幅退化，需要积累 CI 历史后再建立趋势告警。
- warm-process 基准不包含 Python 启动、安装、网络数据源或远程 worker 成本。

## 放弃的方案

把 benchmark 混入 unittest：性能抖动会让功能测试不稳定，也无法区分失败类型。

使用开发机实测值作为紧阈值：共享 CI 环境会频繁误报。

只测单个函数：无法覆盖 planning、resolver、coordinator、executor 和聚合的端到端退化。

看到某个 Cell 慢就直接迁移 Rust：没有 profile 证据时可能只是把成本转移到 FFI、序列化或部署边界。
