# MarketCell 稳定性设计 v1.2

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
MultiHorizonRequest
→ validate target/as-of/order/freshness
→ preflight Graph content hash + formula versions
→ ordered child AnalysisRequest runs
→ MultiHorizonAnalysis(aggregation_status=not_computed)

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
- 多周期比较前必须证明 child 使用同一 Graph 内容和公式集合；MultiHorizonAnalysis 永不输出总体方向，只有版本化 HorizonDecisionCell 可以生成独立决策。

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
trace binding                    ∈ node.binding_id + node.fallback_binding_ids
binding.implementation_id        = trace.implementation_id
binding.service_id               = trace.service_id
binding.runtime                  = trace.runtime
plan.node.input_reference_ids    ⊆ plan.input_references.reference_id
plan.node.required_input_kinds   = referenced input kinds（顺序和基数一致）
reference.content_hash           = resolved_snapshot.content_hash
reference.payload_size_bytes     = resolved_snapshot.payload_size_bytes
```

上述服务身份等式适用于已经成功派发给 executor 的节点。若在 routing 或 dispatch 边界失败，trace 的实际 implementation、service 和 runtime 必须保持为空，并在 metadata 中保留 planned binding，不能伪造为已经在计划服务执行。

稳定要求：

- LocalCellExecutor 不得执行远程 binding。
- ExecutorRouter 先匹配精确 service，再匹配 runtime，且不得隐式 fallback。
- trace 中的服务信息来自实际 executor，不来自计划复制。
- Router 必须校验 delegate trace 的 run_id、trace_id、plan_id、node 和 binding 身份。
- FailureControlledExecutor 只能使用 ExecutionPlan v5 已列出的 fallback binding。
- 同一节点所有 retry / fallback attempt 必须共享 idempotency_key，并使用唯一 attempt_id。
- Coordinator 必须校验 control record 的 run/plan/node、binding 顺序、attempt identity 和 trace span。
- 只有 dispatch 和 timeout 默认重试；routing、dispatch、timeout、backpressure 才允许进入 fallback。
- 普通 execution failure、contract failure 和 canceled 默认立即终止。
- stateful binding 未声明 `idempotent_execution` 时，dispatch / timeout 后不得 retry 或 fallback。
- timeout 结果必须被拒收；同步本地实现不得声称已强制终止仍在运行的 Python 代码。
- backpressure 和预取消必须在 Cell 启动前生效。
- canceled trace 必须保留审计，但不能进入 placement 健康窗口。
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
- 每个节点只能获得 required_input_kinds 声明的输入，且 analysis_request 始终恰好一份。
- CellInputBundle 的 node、scope、引用身份和快照身份必须在公式启动前一致。
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
- execution control records、attempts、retry 和 fallback
- 成功或失败状态

稳定要求：

- 成功和失败 run 都可持久化。
- 失败持久化错误不能覆盖原始 Cell 异常。
- Runtime summary 聚合维度必须包含实现和服务。
- 回放优先使用快照和版本，不依赖临时日志；`replay_comparison.v1` 同时递归比较完整决策树、漂移路径和 canonical hash，不能只比较根节点摘要。
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
- `test_executor_router.py`：service/runtime 路由优先级、混合 binding、路由/dispatch 失败审计和 delegate trace 漂移。
- `test_execution_control.py`：幂等 identity、retry 顺序、timeout 拒收、backpressure、cancellation、fallback 和控制记录持久化。
- `test_coordinator.py`：拓扑顺序、多级聚合、重复 Cell、失败局部状态和节点事件。
- `test_inputs.py`：确定性输入身份、Resolver 完整性、幂等注册、运行内缓存、失败审计和计划无 payload。
- `test_execution_plan.py`：计划、trace 和 summary 持久化。
- `test_execution_placement.py`：多服务候选和运行时感知 placement。
- `test_replay.py`：输入快照重跑、公式漂移和 Graph 身份 / 版本 / 内容漂移。
- `test_funding_open_interest.py`：衍生品输入单位、线性合约边界、价格调整后的 OI 暴露、cadence/quality 失败关闭、显式 Graph 和多输入稳定回放。
- `test_multi_horizon.py`：稳定请求身份、as-of 新鲜度、短到长顺序、等价周期拒绝、同 Graph/公式预检、fail-fast 边界和 child 独立回放。
- `test_horizon_decision.py`：分层边界、结构方向、冲突分类、风险覆盖、稳定身份、输出不变量和应用层 Registry 边界。
- `test_run_store.py`：报告与运行记录。
- `test_decision_policy.py`：方向和风险分层。
- `test_registry_validation.py`：输入边界。

统一运行：

```bash
make test
```

## 9. 地基稳定性缺口

当前仍需补齐：

1. 生产远程 Executor 的 transport adapter、跨进程幂等结果存储和强制 deadline/cancellation。
2. MultiHorizonAnalysis / HorizonDecision 的父级运行持久化、历史走势标签和概率校准；在完成前 HorizonDecisionCell 保持 experimental，不能直接驱动交易。

顺序以 `roadmap.md` 为准。
