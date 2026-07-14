# MarketCell 实施路线图 v0.3

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
- `PlanDrivenLocalCoordinator` 和 `plan_execution.v1` 运行审计
- `CellGraphDefinition`、命名 Organ 子图和 `cell_graph_validation.v1`
- ExecutionPlan v2：node_id 与 cell_id 分离，节点显式引用 binding_id
- Graph Validator：组合依赖、Organ、环、可达性和 Registry 兼容性
- ExecutionPlan Validator：运行依赖、环、可达性、root 和 binding 一致性
- plan / trace / CellResult 一致性校验
- 成功和失败 AnalysisRun 的运行审计
- GitHub Actions Python / Rust CI

## 3. 当前阶段：Foundation Hardening

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

### P0.4 Input Reference / Resolver（下一步）

目标：为大数据输入和远程执行建立引用边界。

- 区分 input snapshot、input reference 和 feature snapshot
- ExecutionPlan 只保存引用和键
- 本地 resolver 参考实现
- 数据版本、来源和哈希进入运行审计
- 避免跨服务复制整段历史 K 线

### P0.5 Runtime Summary Store

目标：让 placement 使用跨运行历史，而不是单次摘要。

- 按 Cell、公式、实现、服务和 runtime 存储
- 支持时间窗口、样本量和最近状态
- 保留 P50 / P95 / P99、失败率和重试率
- placement 读取明确窗口快照
- 历史过期和实现版本切换规则

### P0.6 Performance Baseline

目标：CI 同时守住正确性和性能回归。

- 建立固定输入基准
- 记录总运行时间和 Cell P95
- 设置宽松、可解释的首版阈值
- 区分功能测试和 benchmark
- Rust 热点迁移必须由 profile 证据驱动

## 4. Foundation 退出标准

以下条件全部满足后，才进入大规模 Cell 扩展：

- 非法 DAG 在执行前被拒绝。（已完成）
- 本地执行由 plan 驱动，Registry 不再隐式决定拓扑。（已完成）
- 至少一个多级 aggregator 图可以稳定运行和回放。（已完成）
- 关闭或更换 executor 时，trace 仍能准确表达实际位置。
- placement 能消费跨运行历史窗口。
- 失败、超时、重试和降级拥有明确审计结构。
- 固定样例具备性能基线。

## 5. 后续阶段

### v0.3 Cell 能力扩展

- SupportResistanceCell
- BreakoutCell
- LiquidityCell
- VolumePriceAnomalyCell
- FundingOpenInterestCell
- 每个新 Cell 必须有验证数据、误判记录和公式版本

### v0.4 多周期和多 Organ

- MultiHorizonRequest
- HorizonDecisionCell
- 多周期冲突检测
- Organ 组合和共享 Cell
- 短线 / 中线 / 长线分层报告

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
- Executor Router
- Python / Rust remote executor
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
