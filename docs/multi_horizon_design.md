# MarketCell 多周期请求设计 v0.1

## 1. 文档职责

本文定义 `MultiHorizonRequest` 的输入、校验、执行和失败边界。它只解决“如何把同一标的的多个周期安全地送入现有单周期分析闭环”，不在 source analysis 内定义跨周期方向、冲突评分或策略结论；这些由独立 HorizonDecisionCell 和 `horizon_decision.v1` 承担。

## 2. 状态、行为、规则、迁移与边界

状态：

```text
declared
validated
preflighted
executing
succeeded / failed
```

行为：

- 声明同一 target、同一 `as_of_ms` 下的 2–8 个完整 AnalysisRequest。
- 按调用方声明的短到长顺序运行单周期 AnalysisEngine。
- 保存每个子运行自己的 AnalysisReport、AnalysisRun、InputSnapshot、ExecutionPlan 和回放证据。
- 全部成功后返回 `multi_horizon_analysis.v1`。

规则：

- target 必须完全一致，horizon 必须唯一且按有效时长严格递增。
- `60m` 与 `1h` 这类等价周期不能重复声明。
- horizon 使用无前导零的正整数加 `s/m/h/d/w/M`；`M` 在排序和陈旧判断中采用固定 30 天规范月，不代表日历月运算。
- 每个子请求先通过现有 `validate_request`。
- K 线时间必须可解析、严格升序；最新时间不能晚于 `as_of_ms`，也不能落后超过自身一个周期。
- 所有子周期必须在执行前证明 Graph id、version、canonical content hash 和公式版本集合完全一致。
- v1 使用 sequential + fail-fast。失败后的已完成子报告不会回滚，因为它们是真实发生且可审计的运行；但不会返回伪装成完整批次的成功结果。

状态迁移：

```text
MultiHorizonRequest
→ request validation
→ engine / Graph / formula preflight
→ horizon[0] AnalysisEngine.run
→ horizon[1] AnalysisEngine.run
→ ...
→ MultiHorizonAnalysis(aggregation_status=not_computed)
```

边界：

- MultiHorizonRequest 是应用层批次包络，不是新的 Cell input kind。
- 每个子运行继续使用 `analysis_request` InputSnapshot、现有 ExecutionPlan v5 和 AnalysisRun v2。
- MultiHorizonAnalysis 只有有序子报告，没有根级 direction、score、risk_level 或 action_posture。
- AI、CLI 或调用方不能把简单多数票冒充 HorizonDecisionCell。

## 3. MultiHorizonRequest v1

```text
target
as_of_ms
requests[2..8]: AnalysisRequest
schema_version = multi_horizon_request.v1
metadata
```

保留完整 AnalysisRequest 而不是创建一套缩减版 K 线结构，有三个原因：

1. 单周期请求继续是唯一事实来源，事件、context 和未来字段不需要在多周期协议重复定义。
2. 每个子请求可以独立生成原有 InputSnapshot 身份并单独回放。
3. envelope target 与 child target 的重复是有意的不变量校验，防止批次拼接时混入其他资产。

`request_hash` 只覆盖 target、as_of、规范化后的 requests 和 schema version；metadata 不影响分析身份。`request_id` 为：

```text
multi-horizon-request:<request_hash 前 24 位>
```

固定身份向量位于 `contracts/test_vectors/multi_horizon_request_v1.json`。

## 4. 时间对齐

`as_of_ms` 是显式分析截止时间，不能读取当前墙钟。每个 horizon 的最新 K 线允许：

```text
latest_timestamp <= as_of_ms
as_of_ms - latest_timestamp <= horizon_duration
```

这样既允许 provider 使用已闭合 K 线结束时间，也允许时间戳表示当前周期开始边界，同时拒绝未来数据和明显陈旧数据。v1 不验证不同周期 OHLC 是否能逐根精确聚合，因为 provider 的 session、缺口处理和日历边界可能不同；跨周期价格一致性应由后续数据质量层使用明确市场日历处理。

## 5. 执行预检

MultiHorizonAnalyzer 在任何 Cell 启动前为全部 horizon 创建 AnalysisEngine，并比较：

```text
graph_id
graph_version
stable_json_hash(graph.to_dict())
graph 内全部 Cell 的 formula_version
```

只比较 graph id/version 不够：未升版本却修改拓扑仍会被 content hash 拒绝。只在运行后比较公式也不够：会产生可以提前避免的部分执行。因此 Graph 和公式一致性属于 batch preflight。

## 6. 子运行审计和回放

每个 AnalysisRun.metadata 写入：

```text
multi_horizon.schema_version
multi_horizon.batch_id
multi_horizon.request_id / request_hash
multi_horizon.target / as_of_ms
multi_horizon.horizon_order
multi_horizon.horizon_index / horizon_count
multi_horizon.execution_mode = sequential
multi_horizon.failure_mode = fail_fast
multi_horizon.aggregation_status = not_computed
multi_horizon.request_metadata
```

使用 `--save` 时，每个子报告和运行照常进入 FileSystemReportStore，可以由现有 ReplayRunner 独立重放。v1 暂不把批次包络保存为新的 AnalysisRun 类型；HorizonDecision 已有稳定身份，但父级状态机、失败恢复和持久化协议仍需单独设计，不能直接复用单 horizon AnalysisRun。

## 7. 失败语义

`multi_horizon_execution_error.v1` 区分：

```text
engine_factory_failure
graph_mismatch
formula_version_mismatch
analysis_failure
report_scope_mismatch
report_formula_mismatch
```

错误保存 batch id、完整 request id/hash、as-of、完整 horizon order、completed horizons 和 failed horizon。Graph/公式预检失败时 completed horizons 必须为空；执行失败时已完成边界必须准确，不能把部分结果返回成 succeeded MultiHorizonAnalysis。

## 8. 当前非目标

- MultiHorizonAnalyzer 本身不计算跨周期总体 direction；该职责由独立 HorizonDecisionCell 承担。
- MultiHorizonAnalysis 不内嵌短线、中线、长线分组权重或聚合结果。
- MultiHorizonAnalyzer 不进行多数票或简单平均。
- 不支持不同周期使用不同 Graph 或公式版本。
- 不并行执行；后续并行化必须保持稳定结果顺序和同样的失败审计。
- 不替代专业市场日历、跨周期 OHLC 聚合校验和数据源 SLA。

HorizonDecisionCell 已通过 `horizon_structure_alignment_v0.1` 消费完整、有序且同身份的子决策；详细分层、冲突和风险边界见 `horizon_decision_design.md`。MultiHorizonAnalysis 仍永久保持未聚合。
