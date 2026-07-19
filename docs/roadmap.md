# MarketCell 实施路线图 v1.2

## 1. 文档职责

本文是仓库唯一的实施顺序来源。

`product_design.md` 负责产品方向，`system_architecture.md` 负责系统边界，专项文档负责具体设计；它们不再维护独立版本清单。

## 2. 已完成基线

### 2.1 分析闭环

- AnalysisRequest 输入和校验
- Cell Manifest、Registry 和第一批参考 Cell
- DecisionPolicy、风险分层和 AnalysisReport
- AnalysisRun、报告保存和 ReplayRunner
- 分析结构、Cell 输出和风险解释守护测试

### 2.2 数据地基

- CandleSource、主备路由、缓存和 Binance 开发适配器
- 数据质量监控、质量记录、健康趋势和 provider 可靠性摘要
- ProviderSelectionPolicy 和 RouterPlanBuilder
- Parquet / DuckDB 可选存储适配基础
- Protobuf 实时行情契约和 Parquet K 线契约

### 2.3 多语言地基

- `packages/python`、`crates`、`contracts` workspace 边界
- Rust `market_data_core` 行情原语
- Rust `realtime_core` 动态数据模块预留
- Python 静态分析与 Rust 动态热点职责划分

### 2.4 Cell Execution Fabric 地基

- `CellExecutionPlan`、`CellServiceBinding` 和资源提示契约
- `CellRuntimeTrace`、`CellRuntimeSummary` 契约和本地采集
- `ServiceCapabilityCatalog` 和 `CellPlacementDecision`
- `RuntimeAwarePlacementPolicy`
- `CellExecutor` 和严格的 `LocalCellExecutor`
- `ExecutorRouter`、确定性 service/runtime 路由和路由失败审计
- `PlanDrivenLocalCoordinator` 和 `plan_execution.v1` 运行审计
- `CellGraphDefinition`、命名 Organ 子图和 `cell_graph_validation.v1`
- ExecutionPlan v2：node_id 与 cell_id 分离，节点显式引用 binding_id
- ExecutionPlan v3：计划保存 payload-free input references，节点显式引用输入身份
- ExecutionPlan v4：节点显式保存已校验 fallback binding 顺序
- ExecutionPlan v5：节点声明 required_input_kinds 并只绑定所需输入引用
- InputSnapshot / InputReference / InputResolutionRecord 跨语言契约
- `CellInputBundle` 类型化组合、精确基数校验和 trace 输入身份审计
- `data_provenance.v1`、`order_book_snapshot.v1`、`funding_open_interest_snapshot.v1` 和对应跨语言身份向量
- AnalysisRun v2 全量多输入持久化与 AnalysisRun v1 兼容回放
- LocalInputResolver 完整性校验、幂等注册和运行内单次解析缓存
- FeatureSnapshot 独立 schema、公式版本和 source input hash
- Runtime Summary Store、显式时间窗口快照和跨运行 placement 历史
- 固定输入 Performance Baseline、独立 benchmark 入口和 CI 回归阈值
- Graph Validator：组合依赖、Organ、环、可达性和 Registry 兼容性
- ExecutionPlan Validator：运行依赖、环、可达性、root、binding 和 input reference 一致性
- plan / trace / CellResult 一致性校验
- 成功和失败 AnalysisRun 的运行审计
- `FailureControlledExecutor`、`execution_control_record.v1` 和稳定 attempt / idempotency identity
- GitHub Actions Python / Rust CI

## 3. 当前阶段：Foundation Hardening（已完成）

当前不以新增 Cell 数量为目标，而是让大量 Cell 和未来多服务运行时建立在可验证地基上。

### P0.1 ExecutionPlan Validator（已完成）

目标：所有执行计划在运行前拒绝结构错误。

- node_id 唯一；cell_id 允许在不同节点重复
- root_node_id 合法性
- dependency 存在性
- DAG 环检测
- 不可达节点检测
- node、binding、formula_version 一致性
- 稳定的拓扑层级输出
- planning failure 在任何 Cell 执行前写入 failed AnalysisRun

### P0.2 Plan-Driven Local Coordinator（已完成）

目标：本地执行顺序真正由 ExecutionPlan 驱动。

- 按拓扑层执行节点
- 同层节点保留并行能力，但第一版可以顺序执行
- 聚合节点从依赖结果读取 child_results
- Registry 只提供实现，不再决定运行顺序
- 执行事件和 trace 绑定 node_id
- 同一 cell_id 的多个 node_id 独立执行并按节点保存结果
- 成功和失败运行保存确定性 execution_order、completed_node_ids 和 failed_node_id
- 禁止无 ExecutionPlan 的第二执行路径

### P0.3 Cell Graph Definition（已完成）

目标：把 Cell 组合关系从 Registry 列表中拆出。

- 定义版本化 `CellGraphDefinition`
- 支持 leaf、aggregator、root 多层结构
- Organ 以 organ_id + organ_version 表达版本化命名子图
- 多个 Organ 可共享 Cell
- Graph Definition 生成 ExecutionPlan，但不包含服务位置
- Registry 只注册实现，不再保存 leaf / root 拓扑角色
- Graph、Plan Validator 共享确定性拓扑算法
- Graph snapshot 和结构化校验失败进入 AnalysisRun

### P0.4 Input Reference / Resolver（已完成）

目标：为大数据输入和远程执行建立引用边界。

- 区分 input snapshot、input reference 和 feature snapshot
- ExecutionPlan 只保存引用和键
- 本地 resolver 参考实现
- 数据版本、来源和哈希进入运行审计
- 避免跨服务复制整段历史 K 线
- 同一 reference 在一次 run 内最多实际解析一次
- 同一 AnalysisRequest 在一次 run 内最多物化一次
- target / horizon 与计划不一致的引用在任何 Cell 启动前被拒绝
- 成功和失败 AnalysisRun 保存输入来源、版本、哈希、大小与解析状态

### P0.5 Runtime Summary Store（已完成）

目标：让 placement 使用跨运行历史，而不是单次摘要。

- 按 Cell、公式、实现、服务和 runtime 存储
- 支持时间窗口、样本量和最近状态
- 保留 P50 / P95 / P99、失败率和重试率
- placement 读取明确窗口快照
- 历史过期和实现版本切换规则

### P0.6 Performance Baseline（已完成）

目标：CI 同时守住正确性和性能回归。

- 建立固定输入基准
- 记录总运行时间和 Cell P95
- 设置宽松、可解释的首版阈值
- 区分功能测试和 benchmark
- Rust 热点迁移必须由 profile 证据驱动

### P0.7 Executor Router（已完成）

目标：让一次 ExecutionPlan 可以在不改变 DAG 语义的前提下派发到不同 executor，并准确记录实际执行位置。

- 精确 `service_id` 路由优先，`runtime` 路由作为显式通用适配器
- 不做隐式 fallback；降级必须由后续失败控制策略显式决定
- 缺失路由和 dispatch 异常生成失败 trace，实际服务字段保持为空，计划 binding 保存在 metadata
- delegate trace 同时校验 run、trace、plan、node、implementation、service 和 runtime
- `AnalysisEngine` 可注入 `ServiceCapabilityCatalog`，生成本地与服务 binding 混合计划

### P0.8 Failure Control Semantics（已完成）

目标：让远程或不稳定 executor 的每次尝试都能确定性分类、限制和复盘。

- ADR-0005 定义 attempt identity、幂等键和失败分类
- 区分 routing、dispatch、execution、timeout、backpressure、canceled 和 contract failure
- 超时预算取 node 与 binding 显式资源提示中的更严格值，不能由 transport 私自放宽
- 只对明确可重试失败重试，并保存每次 attempt 和最终 retry_count
- fallback 必须生成显式决策和审计，不能隐藏在 Router 内
- stateful binding 只有声明 `idempotent_execution` capability 才能在歧义失败后 retry / fallback
- 取消和背压在 Cell 启动前或安全边界生效
- `execution_control_record.v1` 保存每次 attempt、retry、fallback 和最终失败分类
- 跨语言 `execution_identity_v1` 固定幂等键和 attempt identity 算法

### P0.9 Typed Multi-Input Composition（已完成）

目标：在 LiquidityCell 之前建立可声明、可验证、可回放的多输入边界。

- Cell Manifest 显式声明 `required_input_kinds`，且 analysis_request 始终必需
- v1 每种 input kind 恰好一份快照；多 venue / 多窗口留给未来 slot/cardinality 协议
- Planner 只给节点绑定所需 InputReference，缺失或同类型歧义在 planning 阶段失败
- ExecutionPlan Validator 检查声明类型与实际引用精确一致
- Coordinator 组合 `cell_input_bundle.v1`，Executor 优先调用 `analyze_inputs`
- 普通 Cell 通过默认适配继续使用 `analyze(request, child_results)`
- 订单簿、数据血缘、排序、spread、sequence 和完整性校验形成正式契约
- AnalysisRun v2 保存全部 InputSnapshot，ReplayRunner 重建多输入并兼容 v1
- trace 保存 bundle schema、input kinds 和 snapshot ids，不复制 payload

## 4. Foundation 退出标准

以下条件全部满足后，才进入大规模 Cell 扩展：

- 非法 DAG 在执行前被拒绝。（已完成）
- 本地执行由 plan 驱动，Registry 不再隐式决定拓扑。（已完成）
- 至少一个多级 aggregator 图可以稳定运行和回放。（已完成）
- ExecutionPlan 不携带 K 线 payload，Input Resolver 可校验并审计输入。（已完成）
- 关闭或更换 executor 时，trace 仍能准确表达实际位置。（已完成）
- placement 能消费跨运行历史窗口。（已完成）
- 失败、超时、重试和降级拥有明确审计结构。（已完成）
- 多输入节点只能获得声明的数据，并能完整保存、篡改检测和稳定回放。（已完成）
- 固定样例具备性能基线。（已完成）

Foundation 退出标准、v0.3 首批 Cell 能力和多周期请求/决策闭环已经完成；下一项进入 Organ 组合和共享 Cell。

## 5. 后续阶段

### v0.3 Cell 能力扩展（已完成首批基线）

- SupportResistanceCell（已完成，experimental）
- BreakoutCell（已完成，experimental）
- LiquidityCell（已完成，experimental；消费正式 OrderBookSnapshot，只在显式 liquidity graph 中启用）
- VolumePriceAnomalyCell（已完成，experimental；稳健量价基线并作为 ManipulationRiskCell 的显式依赖）
- FundingOpenInterestCell（已完成，experimental；消费正式资金费率/OI/mark-price 时间序列，只在显式 derivatives graph 中启用）
- 每个新 Cell 必须有验证数据、误判记录和公式版本

### v0.4 多周期和多 Organ

- MultiHorizonRequest（已完成；同 target/as-of、2–8 周期、时间对齐、稳定身份、同 Graph/公式预检和独立子回放）
- HorizonDecisionCell（已完成，experimental；结构方向、分层权威、风险覆盖和稳定 decision identity）
- 多周期冲突检测（已完成；层内、short vs higher、medium vs long、lower vs long 和 broad）
- Organ 组合和共享 Cell（下一项）
- 短线 / 中线 / 长线分层报告（已完成；固定名义时长边界和 band decisions）

### v0.5 专业数据接入

- 专业历史数据商 adapter
- 交易所实时和历史数据闭环
- 数据源 SLA、心跳和延迟分布
- Parquet 去重、upsert 和查询窗口增强
- Replay Source Audit

### v0.6 评估平台

- 真实走势标签
- Cell 命中率、校准和风险事件评估
- 公式版本对比
- Shadow Run
- ReportAnalyzer

### v0.7 AI 解释层

- AI 只消费结构化 AnalysisReport
- 冲突解释和复盘总结
- 引用 Evidence，不重写决策事实
- AI 输出独立版本和审计

### v0.8 服务化后端

- FastAPI Gateway
- AnalysisTask
- Python / Rust remote executor 接入现有 Executor Router
- 集群调度和远程传输适配
- Report、Run 和 Cell API
- 服务发现、超时、重试和背压

### v1.0 自动交易前置系统

- Trading Gateway
- Risk Guard
- Order Manager
- Position Manager
- Exchange Adapter

Trading Layer 只消费稳定分析结果，不进入 Cell Execution Fabric。

## 6. 暂不做

- 高频交易策略
- 真实下单
- 复杂微服务拆分
- 多租户、权限和收费系统
- 没有 profile 证据的 Rust 重写
- 没有回放证据的 AI 决策替换
