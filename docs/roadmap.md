# MarketCell 路线图 v0.1

## v0.1 已完成

- 项目骨架
- Python 分析内核
- Rust 高性能模块预留
- JSON 输入输出
- 第一批 Cell
- 基础测试

## v0.2 当前阶段

- 产品设计文档
- 系统架构文档
- 后端设计文档
- 后端架构文档
- Cell 协议
- 数据契约
- 风险治理文档
- AnalysisRun 运行记录
- FileSystemReportStore
- CLI 报告保存和回放
- 多语言 workspace 布局：`packages/python`、`crates`、`contracts`
- JSON Schema 契约
- DecisionPolicy 策略层和风险分层
- GitHub Actions CI，自动运行 Python 和 Rust 测试
- Data Source 协议、K 线主备路由和 Binance 开发适配器
- Feature Layer 初版：统一量价基础特征
- CandleCache 协议和文件缓存实现
- 运行时冷热路径文档：Rust 动态数据，Python 静态分析
- Protobuf 实时行情事件契约
- Parquet K 线批量存储契约
- Rust market_data_core 行情原语和质量函数
- ReplayRunner：基于 input_snapshot 重新执行并比较结果漂移
- Parquet/DuckDB 存储适配基础：CandleRow、分区路径、可选读写适配器
- SourceQualityMonitor：K 线缺口、陈旧、异常量价和跨源偏差监控
- FileSystemDataQualityStore：质量问题 JSONL 持久化

## v0.3 Cell 扩展

目标：增强分析能力。

- SupportResistanceCell
- BreakoutCell
- LiquidityCell
- VolumePriceAnomalyCell
- FundingOpenInterestCell

同时补齐轻量骨架：

- EventBus 使用场景扩展
- ReportAnalyzer 接口草案
- Parquet / DuckDB 去重、upsert 和查询窗口增强
- 数据源健康评分趋势和 Provider 可靠性排名

## v0.4 多周期分析

目标：开始回答短线、中线、长线问题。

- MultiHorizonRequest
- HorizonDecisionCell
- 多周期冲突检测
- 短线 / 中线 / 长线报告结构

## v0.5 数据接入

目标：从样例数据走向真实数据。

- CSV / JSON 本地行情导入
- 交易所 K 线拉取
- Parquet 保存历史数据
- DuckDB 查询历史数据

## v0.6 报告保存和回放

目标：让系统可以复盘。

- 保存 AnalysisReport
- 保存输入快照
- 回放历史分析
- 对比后续真实走势

## v0.7 AI 解释层

目标：AI 不直接做交易决策，而是解释结构化报告。

- AI 总结报告
- AI 解释冲突
- AI 生成复盘
- AI 帮助发现缺失因子

## v0.8 服务化后端

目标：给未来界面和自动交易前置系统提供 API。

- FastAPI
- AnalysisTask
- Report API
- Cell API

## v1.0 自动交易前置系统

目标：只接收分析结果，不污染分析内核。

- Trading Gateway
- Risk Guard
- Order Manager
- Position Manager
- Exchange Adapter

## 暂不做

- 高频交易
- 真实下单
- 复杂微服务
- 用户系统
- 权限系统
- 收费系统
