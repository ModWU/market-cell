# MarketCell 稳定性设计 v0.6

## 1. 目标

地基阶段需要同时稳定六件事：

- 分析结构稳定
- Cell 输出稳定
- 风险解释稳定
- 执行语义稳定
- 输入身份和解析稳定
- 运行审计稳定

前三项保证产品结果可信，后两项保证大量 Cell 和多服务运行后仍能定位、复盘和扩展。

## 2. 分析结构稳定

当前结构：

```text
AnalysisRequest
→ validate_request
→ CellGraphDefinition
→ Graph Validator
→ CellExecutionPlanner
→ CellExecutionPlan
→ Plan Validator
→ CellExecutionCoordinator
→ CellExecutor
→ node_id -> CellResult
→ DecisionPolicy / DecisionCell
→ AnalysisReport
→ ReportStore / ReplayRunner
```

稳定要求：

- Engine 负责编排，不实现具体公式。
- Registry 只提供本地能力实现，不承担节点角色或运行顺序。
- Graph 定义组合，Planner 选择实现和服务，Coordinator 负责运行图语义，Executor 负责单节点真实执行。
- AnalysisReport 不包含服务、重试或队列信息。
- 新数据源必须经过标准数据契约进入分析。

当前 Graph、Registry、ExecutionPlan 和 Coordinator 已经分层。默认图与自定义多级图使用同一校验、规划和执行路径。

## 3. Cell 输出稳定

所有 Cell 必须输出标准 `CellResult`：

```text
cell_id
target
horizon
direction
strength
confidence
volatility_risk
manipulation_risk
urgency
score
explanation
risk_level
action_posture
evidence
children
metadata
```

稳定要求：

- 方向只能是 `bullish / bearish / neutral / conflict`。
- 风险值统一为 0 到 100。
- `cell_id / target / horizon` 必须与 invocation 匹配。
- 关键消费字段不能只藏在 metadata。
- 公式版本通过 Manifest 和 AnalysisRun 保存。
- Executor 和 Coordinator 双重校验结果契约。

## 4. 风险解释稳定

MarketCell 长期保持方向和风险分离：

```text
方向偏多
但风险中等或偏高
```

结构化风险输出包括：

- `risk_level`
- `action_posture`
- `risk_breakdown`
- `risk_notes`

稳定要求：

- 不使用“确定操纵”“必涨必跌”等越界表达。
- 新风险维度必须进入结构化 breakdown。
- UI、AI 和 Trading Gateway 先读结构化字段，再读 explanation。
- AI 解释不能修改 CellResult 的事实和版本。

## 5. 执行语义稳定

计划和真实执行必须一致：

```text
plan.node.node_id                = trace.node_id
plan.node.binding_id             = binding.binding_id
binding.implementation_id        = trace.implementation_id
binding.service_id               = trace.service_id
binding.runtime                  = trace.runtime
plan.node.input_reference_ids    ⊆ plan.input_references.reference_id
reference.content_hash           = resolved_snapshot.content_hash
reference.payload_size_bytes     = resolved_snapshot.payload_size_bytes
```

稳定要求：

- LocalCellExecutor 不得执行远程 binding。
- trace 中的服务信息来自实际 executor，不来自计划复制。
- ExecutionPlan 是强制边界，不允许无计划的第二执行路径。
- 失败、超时、重试和降级必须区分。
- 未来远程执行需要 run_id、plan_id、trace_id 和 parent_span_id 传播。
- 非法 DAG 必须在任何 Cell 执行前失败。
- 非法 Graph、Organ 或未注册 Cell 必须在生成 ExecutionPlan 前失败。
- `node_id` 是执行身份，`cell_id` 可以在不同节点重复。
- 节点必须通过 `binding_id` 显式绑定 implementation 和 service。
- 执行顺序来自 validator 输出的稳定拓扑层，不来自 Registry 或 plan.nodes 排列。
- 聚合结果必须严格按 node.dependencies 顺序输入。
- root 结果只能按 root_node_id 读取。
- ExecutionPlan 不能携带 InputSnapshot payload。
- 同一 run 内每个 reference_id 最多进行一次实际解析。
- 同一 run 内已解析 AnalysisRequest 最多物化一次，不能按 Cell 数重复反序列化大输入。
- 默认内存 InputSnapshotStore 必须是 run-scoped，避免长生命周期 Engine 无界持有历史 payload。
- Resolver 必须校验来源、数据版本、hash、size、target 和 horizon，URI 可读不等于完整性通过。
- Plan Validator 必须在执行前拒绝 target 或 horizon 与计划不一致的 InputReference。
- 相同逻辑快照重复注册必须幂等，created_at 不得改变 snapshot identity。

## 6. 运行审计稳定

`AnalysisRun` 负责保存：

- input snapshot 和 input hash
- input snapshot audit、input references 和 resolution records
- formula versions 和 manifests
- cell graph snapshot 和 graph validation
- provider / router audit
- execution plan 和 placement decisions
- plan execution order、completed nodes 和 failed node
- runtime traces 和 summaries
- 成功或失败状态

稳定要求：

- 成功和失败 run 都可持久化。
- 失败持久化错误不能覆盖原始 Cell 异常。
- Runtime summary 聚合维度必须包含实现和服务。
- 回放优先使用快照和版本，不依赖临时日志。
- metadata 已命名领域不能随意换结构。

## 7. 性能稳定

功能正确不等于系统可扩展。进入大规模 Cell 前需要：

- 固定输入 benchmark。
- 总运行时间和 Cell 尾延迟基线。
- 跨运行 summary 时间窗口。
- 样本量不足时不做激进 placement。
- 性能退化与结果变化分开报警。

性能阈值应由测量建立，不凭主观数字设定。

## 8. 当前守护测试

- `test_stability.py`：分析结构、Cell 输出和风险解释。
- `test_contracts.py`：跨语言 JSON 契约。
- `test_cell_graph.py`：默认图、多级聚合、共享 Organ、重复 Cell 和 Graph 失败审计。
- `test_executor.py`：binding、执行、trace、结果和失败 run。
- `test_coordinator.py`：拓扑顺序、多级聚合、重复 Cell、失败局部状态和节点事件。
- `test_inputs.py`：确定性输入身份、Resolver 完整性、幂等注册、运行内缓存、失败审计和计划无 payload。
- `test_execution_plan.py`：计划、trace 和 summary 持久化。
- `test_execution_placement.py`：多服务候选和运行时感知 placement。
- `test_replay.py`：输入快照重跑、公式漂移和 Graph 身份 / 版本 / 内容漂移。
- `test_run_store.py`：报告与运行记录。
- `test_decision_policy.py`：方向和风险分层。
- `test_registry_validation.py`：输入边界。

统一运行：

```bash
make test
```

## 9. 地基稳定性缺口

当前仍需补齐：

1. 远程 Executor 的幂等、超时、重试、背压和取消语义。

顺序以 `roadmap.md` 为准。
