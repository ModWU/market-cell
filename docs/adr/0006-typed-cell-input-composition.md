# ADR-0006: 类型化 Cell 多输入组合

- 状态：Accepted
- 日期：2026-07-18
- 决策范围：Cell 输入声明、ExecutionPlan 输入绑定、运行时组合、订单簿契约和多输入回放

## 背景

早期 Cell 统一消费 `AnalysisRequest`，适合 K 线、事件和少量用户上下文。LiquidityCell、FundingOpenInterestCell 等能力需要订单簿、资金费率和持仓快照；如果继续把这些数据塞进 `AnalysisRequest.context`，系统会失去字段类型、数据版本、来源身份、完整性校验和独立回放能力。

ADR-0002 已经区分 `InputSnapshot`、`InputReference` 和 Resolver，但原计划仍把同一个 analysis request 引用分配给所有节点，Coordinator 也只物化 `AnalysisRequest`。因此“数据可寻址”还没有闭合为“Cell 能精确声明和消费多种数据”。

## 决策

### 1. Cell 显式声明所需输入类型

`CellManifest.required_input_kinds` 是 Cell 能力契约的一部分。`analysis_request` 始终必需，用于统一 target、horizon 和基础分析上下文；需要盘口的 Cell 再声明 `order_book_snapshot`，需要衍生品定位序列的 Cell 再声明 `funding_open_interest_snapshot`。

v1 使用简单而严格的基数规则：每种 required input kind 恰好对应一个 InputSnapshot。多个交易所、多个窗口或同类型多 slot 不能靠重复 kind 猜测语义，必须在未来协议中显式引入 slot/cardinality 后再支持。

### 2. ExecutionPlan v5 保存声明并精确绑定引用

Planner 按 Manifest 顺序为每个节点选择引用：

```text
CellManifest.required_input_kinds
+ plan.input_references
→ node.required_input_kinds
+ node.input_reference_ids
```

缺失类型、重复声明、同类型多份快照或不支持的类型都在 planning 阶段失败。Plan Validator 再独立检查节点声明与实际引用类型精确一致，防止持久化计划被篡改或由其他语言错误生成。

### 3. Coordinator 负责组合，Cell 不负责取数

节点输入经过以下受控状态迁移：

```text
declared
→ planned
→ resolved and integrity-checked
→ composed as cell_input_bundle.v1
→ executed
```

任一步失败都会在 Cell 公式启动前停止该节点。Coordinator 继续按 reference_id 做运行内缓存，并把解析后的快照与原引用组合成 `ResolvedCellInput`，最终创建 `CellInputBundle`。Bundle 保证：

- node_id 与计划节点一致；
- required kinds 唯一且包含 analysis_request；
- 每种类型恰好一个已解析输入，顺序与声明一致；
- 所有输入 target / horizon 与 AnalysisRequest 一致；
- 引用身份、内容哈希、来源、版本和大小与快照一致。

Cell、Executor 和 Router 不自行访问存储。`CellExecutionContext` 携带 bundle，trace 记录 bundle schema、input kinds 和 snapshot ids，但不复制 payload。

### 4. 保留请求式 API，增加类型化入口

`MarketCell.analyze_inputs(bundle, child_results)` 是计划执行入口。基类默认把它转发到现有 `analyze(request, child_results)`，所以只需要 AnalysisRequest 的 Cell 不必重写。

需要额外输入的 Cell 重写 `analyze_inputs`，并通过 `require_one(input_kind)` 获取版本化快照。旧 `analyze` 方法继续保留为兼容边界；它不能成为绕过计划输入声明的第二执行路径。

### 5. 订单簿使用独立版本化领域契约

首批正式多输入类型为：

```text
data_provenance.v1
order_book_snapshot.v1
funding_open_interest_snapshot.v1
```

`OrderBookSnapshot` 校验正数且有限的价格/数量、bid 降序、ask 升序、价格唯一和正 spread。`FundingOpenInterestSnapshot` 明确 settled / predicted funding 语义、funding interval、采样间隔、OI quote-notional 币种和 linear contract type，并要求资金费率、持仓和 mark price 使用严格升序且唯一的同步时间点；仅接受 perpetual future 血缘，最新点必须匹配 provenance event time。同步 mark price 允许 Cell 先把 quote notional 换算为 base-equivalent exposure，隔离价格重估造成的假 OI 增长。`DataProvenance` 保存 provider、venue、market type、事件时间、抓取时间、sequence、源事件身份和质量标记。两个领域对象的 `from_input_snapshot` 都会复核 payload 与 InputSnapshot envelope 的 target、data version 和 source。

### 6. AnalysisRun v2 保存全部输入并支持旧回放

`AnalysisRun.input_snapshots[]` 保存本次运行使用的完整 InputSnapshot，包括所有额外输入。为兼容既有消费者，`input_snapshot` 和 `input_hash` 继续指向主 analysis request payload 与其内容哈希；metadata 同时保留单数主审计和复数 `input_snapshot_audits`。

ReplayRunner 对 v2 重建全部 InputSnapshot，把非 analysis-request 快照重新传给 Engine；读取旧 `analysis_run.v1` 时继续从 `input_snapshot` 回放。Resolver 在重放时再次执行身份和内容完整性校验。

## 结果

正向结果：

- LiquidityCell、FundingOpenInterestCell 等能力不需要污染无类型 context。
- 每个节点只解析、传输和审计自己声明的数据。
- 计划、运行时、trace 和回放共享同一输入身份链。
- Python、Rust 和远程 worker 可以用固定向量验证相同订单簿哈希与 snapshot/reference identity。
- 普通 Cell 保持现有实现方式，迁移成本受控。

约束和代价：

- v1 不支持同一种 input kind 的多份并列输入。
- 完整多输入回放会增大 AnalysisRun；生产大载荷后续应由持久 Snapshot Store 提供内容寻址归档，但不能只留下临时 URI。
- 新 input kind 必须同时增加领域模型、JSON Schema、Resolver 枚举、契约向量和篡改测试。
- 远程 Executor 必须传递同一 bundle envelope，不能退化成任意字典。

## 放弃的方案

把订单簿放进 `AnalysisRequest.context`：缺少类型、版本和血缘，无法证明回放使用的是同一盘口。

让 Cell 按需读取交易所或数据库：数据访问、缓存和完整性策略会散落到公式实现中，无法统一审计。

把所有引用分配给所有节点：扩大权限、解析和传输面，也无法从计划判断 Cell 的真实数据依赖。

允许重复 input kind 并由 Cell 猜顺序：同类型多输入没有稳定语义，跨语言实现会产生歧义。
