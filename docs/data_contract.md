# MarketCell 数据契约 v0.3

## 1. 契约目标

数据契约保证不同模块对输入输出的理解一致。

MarketCell 后期会有很多 Cell，如果数据结构不稳定，系统会很快变乱。

## 2. AnalysisRequest

一次分析任务的输入。

```json
{
  "target": "BTC/USD",
  "horizon": "1h",
  "candles": [],
  "events": [],
  "context": {}
}
```

字段：

| 字段 | 类型 | 说明 |
|---|---|---|
| `target` | string | 分析目标，例如 BTC/USD |
| `horizon` | string | 分析周期，例如 1h |
| `candles` | array | K 线数据 |
| `events` | array | 外部事件 |
| `context` | object | 额外上下文 |

## 3. Candle

```json
{
  "timestamp": "2026-07-09T00:00:00Z",
  "open": 108000,
  "high": 108500,
  "low": 107500,
  "close": 108200,
  "volume": 1240
}
```

校验规则：

- `timestamp` 不能为空
- `timestamp` 在一次请求中不能重复
- `open/high/low/close` 必须大于 0
- `open/high/low/close/volume` 必须是有效数字
- `high >= open`
- `high >= close`
- `low <= open`
- `low <= close`
- `high >= low`
- `volume >= 0`

## 4. MarketEvent

```json
{
  "title": "大型机构继续增加 BTC ETF 风险敞口",
  "category": "institution",
  "sentiment": 0.55,
  "impact": 70,
  "freshness": 85
}
```

字段：

| 字段 | 范围 | 说明 |
|---|---|---|
| `sentiment` | -1 到 1 | 负面到正面 |
| `impact` | 0 到 100 | 影响力 |
| `freshness` | 0 到 100 | 新鲜度 |

校验规则：

- `title` 不能为空
- `category` 不能为空
- `sentiment` 必须在 -1 到 1 之间
- `impact` 必须在 0 到 100 之间
- `freshness` 必须在 0 到 100 之间

## 5. CellResult

```json
{
  "cell_id": "technical.trend",
  "direction": "bullish",
  "strength": 30,
  "confidence": 60,
  "volatility_risk": 10,
  "manipulation_risk": 0,
  "urgency": 20,
  "score": 18,
  "explanation": "...",
  "risk_level": "medium",
  "action_posture": "wait_for_confirmation",
  "evidence": [],
  "metadata": {
    "risk_breakdown": {
      "volatility_risk": "medium",
      "manipulation_risk": "medium"
    }
  }
}
```

方向枚举：

```text
bullish
bearish
neutral
conflict
```

风险等级枚举：

```text
low
medium
high
extreme
```

行动姿态枚举：

```text
observe
wait_for_confirmation
cautious_follow
reduce_exposure
avoid_chasing
```

## 6. Evidence

```json
{
  "source": "candles.close",
  "summary": "首尾收盘价上涨 3.14%",
  "weight": 1.0,
  "freshness": 100,
  "reliability": 70
}
```

## 7. AnalysisReport

```json
{
  "target": "BTC/USD",
  "horizon": "1h",
  "decision": {},
  "summary": "...",
  "run_id": "abc123",
  "report_id": "abc123",
  "schema_version": "analysis_report.v1",
  "engine_version": "0.1.0",
  "formula_versions": {
    "technical.trend": "trend_close_change_v0.1",
    "root.decision": "decision_weighted_score_v0.2"
  },
  "created_at": "2026-07-09T00:00:01+00:00",
  "disclaimer": "MarketCell 只提供结构化分析和风险提示，不构成投资建议。"
}
```

`AnalysisReport` 面向使用者，必须能直接说明这份报告遵守哪个 schema、由哪个引擎版本生成、使用了哪些公式版本。

## 8. AnalysisRun

一次可复盘的分析运行。

```json
{
  "run_id": "abc123",
  "target": "BTC/USD",
  "horizon": "1h",
  "engine_version": "0.1.0",
  "input_hash": "...",
  "input_snapshot": {},
  "formula_versions": {},
  "cell_manifests": [],
  "status": "succeeded",
  "schema_version": "analysis_run.v1",
  "started_at": "2026-07-09T00:00:00+00:00",
  "finished_at": "2026-07-09T00:00:01+00:00",
  "report_id": "abc123",
  "metadata": {
    "data_sources": {
      "provider_selection_plan": {},
      "router_plan": {}
    }
  }
}
```

`AnalysisRun` 关注“这次分析如何产生”，`AnalysisReport` 关注“这次分析输出什么”。

`AnalysisRun.metadata` 是运行审计扩展区。当前已经稳定预留：

```text
metadata.data_sources.provider_selection_plan
metadata.data_sources.router_plan
metadata.cell_graph_definition
metadata.cell_graph_validation
metadata.cell_execution_plan
metadata.execution_plan_validation
metadata.plan_execution
metadata.cell_runtime_traces
metadata.cell_runtime_summaries
```

规则：

- `AnalysisRun` 必须带 `schema_version = analysis_run.v1`。
- 数据源选择和实际路由计划只进入 `AnalysisRun.metadata`，不进入 `AnalysisReport.decision`。
- metadata 可以继续扩展，但已经命名的领域必须保持结构稳定。
- 回放时应该优先读取 `input_snapshot`、`formula_versions` 和 `metadata`，不要依赖临时日志。
- 回放必须单独比较 Graph identity、version 和内容哈希与结果漂移，不能用“结果碰巧相同”掩盖拓扑升级或未升版本的内容变更。

## 9. CellGraphDefinition

版本化 Cell 组合图：

```json
{
  "graph_id": "market.default_analysis",
  "graph_version": "0.1.0",
  "name": "Default Market Analysis",
  "root_node_id": "cell:root.decision",
  "nodes": [
    {
      "node_id": "cell:technical.trend",
      "cell_id": "technical.trend",
      "execution_role": "leaf",
      "dependencies": [],
      "metadata": {}
    }
  ],
  "organs": [
    {
      "organ_id": "organ.technical_structure",
      "organ_version": "0.1.0",
      "name": "Technical Structure",
      "node_ids": ["cell:technical.trend"],
      "output_node_ids": ["cell:technical.trend"],
      "description": "",
      "metadata": {}
    }
  ],
  "description": "",
  "schema_version": "cell_graph_definition.v1",
  "metadata": {}
}
```

Graph 只描述 node、dependency、root 和 Organ，不保存 formula implementation、service、runtime 或 endpoint。Organ 必须包含输出节点的依赖闭包；不同 Organ 可以共享 node_id。Graph snapshot 进入 `AnalysisRun.metadata.cell_graph_definition`。

## 10. CellGraphValidation

非法组合图使用结构化校验结果：

```json
{
  "error_type": "cell_graph_validation",
  "graph_id": "market.default_analysis",
  "graph_version": "0.1.0",
  "issues": [
    {
      "code": "missing_cell_implementation",
      "message": "node cell:missing references unregistered Cell missing.cell",
      "node_id": "cell:missing",
      "dependency_id": null,
      "cell_id": "missing.cell",
      "organ_id": null
    }
  ],
  "schema_version": "cell_graph_validation.v1"
}
```

它进入 failed `AnalysisRun.metadata.cell_graph_validation`。Graph validation 覆盖 root、依赖、环、可达性、Organ 输出和依赖闭包，以及 Graph 节点能否由当前 Registry 解析；失败必须发生在 ExecutionPlan 生成和任何 Cell 执行之前。

## 11. CellExecutionPlan

一次分析的 Cell 执行计划。

```json
{
  "plan_id": "plan123",
  "target": "BTC/USD",
  "horizon": "1h",
  "root_node_id": "cell:root.decision",
  "nodes": [],
  "service_bindings": [],
  "schema_version": "cell_execution_plan.v2",
  "created_at": "2026-07-10T00:00:00+00:00",
  "metadata": {}
}
```

`CellExecutionPlan` 关注“本次分析如何执行 Cell DAG”，不是 Cell 输出本身。

v2 执行身份规则：

- `node_id` 在一次计划内唯一。
- `cell_id` 表示能力，同一个 Cell 可以出现在多个节点。
- 每个节点通过 `binding_id` 显式引用服务 binding。
- implementation_id、service_id 和 runtime 只在 binding 中维护，节点不复制第二份。
- dependency 始终引用 `node_id`，不能引用 `cell_id`。
- `binding_id` 由 implementation 和逻辑 service 稳定生成。

当前单服务本地执行也必须能生成计划：

```text
service_id = python-local
runtime = python_local
endpoint = null
```

未来多服务集群可以替换 service binding 和 executor，但不能改变 `CellResult` 输出契约。

## 12. PlanExecution

一次已校验计划的协调执行审计：

```json
{
  "schema_version": "plan_execution.v1",
  "coordinator": "plan_driven_local_coordinator_v0.1",
  "plan_id": "plan123",
  "root_node_id": "cell:root.decision",
  "status": "succeeded",
  "execution_order": [
    "cell:technical.trend",
    "cell:root.decision"
  ],
  "completed_node_ids": [
    "cell:technical.trend",
    "cell:root.decision"
  ],
  "failed_node_id": null,
  "error": null
}
```

`PlanExecution` 关注“计划实际按什么节点顺序推进，以及停在哪里”。结果按 node_id 管理；相同 cell_id 的多个节点必须独立出现。失败时 `execution_order` 保留所有已尝试节点，`completed_node_ids` 只保留成功节点，`failed_node_id` 指向失败执行身份。它进入 `AnalysisRun.metadata.plan_execution`，不复制 CellResult 和 runtime trace。

## 13. CellRuntimeTrace

单个 Cell 节点的实际执行记录。

```json
{
  "trace_id": "trace123",
  "span_id": "span123",
  "run_id": "run123",
  "plan_id": "plan123",
  "node_id": "cell:technical.trend",
  "cell_id": "technical.trend",
  "implementation_id": "python-local:technical.trend:trend_close_change_v0.1",
  "service_id": "python-local",
  "runtime": "python_local",
  "formula_version": "trend_close_change_v0.1",
  "status": "succeeded",
  "started_at": "2026-07-10T00:00:00+00:00",
  "finished_at": "2026-07-10T00:00:00+00:00",
  "duration_ms": 1.23,
  "retry_count": 0,
  "error": null,
  "parent_span_id": null,
  "metadata": {
    "executor": "local_python_executor_v0.1",
    "planned_binding": true,
    "planned_service_id": "python-local"
  }
}
```

`CellRuntimeTrace` 关注“实际如何执行”，用于性能分析、失败定位和多服务复盘。`service_id / runtime / implementation_id` 必须来自实际 executor，计划信息只进入 trace metadata。成功 trace 必须与 `CellExecutionPlan` 完全一致；ExecutionPlan 是强制运行边界。它进入 `AnalysisRun.metadata.cell_runtime_traces`，不进入 `AnalysisReport`。

## 14. CellRuntimeSummary

一次运行内按 Cell、公式版本、实现、服务和运行时聚合后的性能摘要。

```json
{
  "cell_id": "technical.trend",
  "formula_version": "trend_close_change_v0.1",
  "implementation_id": "python-local:technical.trend:trend_close_change_v0.1",
  "service_id": "python-local",
  "runtime": "python_local",
  "trace_count": 2,
  "succeeded_count": 2,
  "failed_count": 0,
  "skipped_count": 0,
  "average_duration_ms": 1.5,
  "max_duration_ms": 2.0,
  "min_duration_ms": 1.0,
  "p95_duration_ms": 2.0,
  "error_count": 0,
  "retry_count": 0,
  "schema_version": "cell_runtime_summary.v1"
}
```

`CellRuntimeSummary` 关注“这一组 Cell 执行表现如何”，用于性能回归、服务容量规划、热点 Cell 识别和未来 placement policy。它进入 `AnalysisRun.metadata.cell_runtime_summaries`，不进入 `AnalysisReport`。

它不替代 `CellRuntimeTrace`：trace 是逐次证据，summary 是稳定聚合口径。未来多服务集群中，Rust worker、Python worker 或外部服务只要上报同一类 trace，就可以生成一致的 summary。

## 15. ServiceCapabilityCatalog

服务能力目录描述当前有哪些 Cell 实现可供 planner 选择：

```json
{
  "catalog_id": "catalog123",
  "bindings": [],
  "schema_version": "service_capability_catalog.v2",
  "generated_at": "2026-07-13T00:00:00+00:00",
  "metadata": {}
}
```

目录规则：

- `binding_id` 在一个目录内必须唯一；同一实现可以由多个逻辑服务承载。
- 跨语言统一按 `binding:{service_id}:{implementation_id}` 生成 binding_id。
- 候选实现必须同时匹配 `cell_id` 和 `formula_version`。
- 一个 `cell_id` 可以出现多个 service binding。
- 一个 `service_id` 可以承载多个 `cell_id`。
- catalog 只描述能力和当前绑定，不保存市场输入或 CellResult。

## 16. CellPlacementDecision

planner 为每个 Cell 选择实现时生成放置决策：

```json
{
  "cell_id": "technical.trend",
  "formula_version": "trend_close_change_v0.1",
  "selected_binding_id": "binding:rust-hot:rust-hot:technical.trend:trend_close_change_v0.1",
  "selected_implementation_id": "rust-hot:technical.trend:trend_close_change_v0.1",
  "selected_service_id": "rust-hot",
  "policy": "runtime_aware_priority_v0.1",
  "candidate_count": 2,
  "reason_codes": ["selected_by_runtime_latency"],
  "candidate_evaluations": [],
  "schema_version": "cell_placement_decision.v2"
}
```

放置策略先保证公式兼容；有足够历史样本时避开高失败率实现；其余候选按显式优先级和 P95 延迟确定性排序。决策进入 `CellExecutionPlan.metadata.placement_decisions`，用于解释“为什么本次由这个服务执行”。

## 17. ExecutionPlanValidation

非法计划使用结构化校验结果：

```json
{
  "error_type": "execution_plan_validation",
  "plan_id": "plan123",
  "issues": [
    {
      "code": "missing_dependency",
      "message": "node cell:root depends on missing node cell:missing",
      "node_id": "cell:root",
      "binding_id": null,
      "dependency_id": "cell:missing"
    }
  ],
  "schema_version": "execution_plan_validation.v1"
}
```

它进入 failed `AnalysisRun.metadata.execution_plan_validation`。不同语言 planner 必须使用相同 issue code，且 planning failure 发生在任何 Cell 执行之前。

## 18. 版本策略

当前已经在 `AnalysisReport` 中加入：

```text
schema_version
engine_version
formula_versions
```

当前已经在 `AnalysisRun` 中加入：

```text
schema_version
engine_version
input_hash
input_snapshot
formula_versions
metadata
```

CellGraphDefinition v1 固定：

```text
graph_id
graph_version
root_node_id
nodes
organs
organ_id / organ_version
node_ids / output_node_ids
```

CellGraphValidation v1 固定：

```text
graph_id
graph_version
issues.code
node_id / dependency_id / cell_id / organ_id
```

当前已经在 `CellRuntimeTrace` 中加入：

```text
schema_version
trace_id
span_id
plan_id
service_id
duration_ms
status
```

当前已经在 `CellRuntimeSummary` 中加入：

```text
schema_version
cell_id
formula_version
implementation_id
service_id
runtime
trace_count
p95_duration_ms
failed_count
retry_count
```

当前已经在 `ServiceCapabilityCatalog` 和 `CellPlacementDecision` 中加入：

```text
schema_version
catalog_id
implementation_id
service_id
formula_version
policy
reason_codes
candidate_evaluations
```

ExecutionPlan v2 新增：

```text
binding_id
node_id / cell_id 身份分离
topological_levels
execution_plan_validation
```

PlanExecution v1 固定：

```text
coordinator
plan_id
root_node_id
status
execution_order
completed_node_ids
failed_node_id
error
```

跨语言 schema 保存在：

```text
contracts/json_schema/
```

后续字段变更必须同步更新：

- Python 模型
- JSON Schema
- 文档示例
- 契约测试
