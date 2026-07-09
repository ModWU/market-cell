# MarketCell 外部架构研究 v0.1

## 1. 调研目的

MarketCell 不是普通指标工具，它需要长期演进成复杂市场分析系统。

因此需要吸收成熟系统的优点：

- 量化回测系统如何组织数据、策略、结果
- 自动交易系统如何处理事件、订单、风控
- 市场监控系统如何识别异常和操纵风险
- AI / 知识图谱系统如何组织外部事件和因子关系

## 2. 调研对象

| 系统 / 方向 | 类型 | 重点观察 |
|---|---|---|
| QuantConnect LEAN | 多资产量化引擎 | 数据、算法、交易、结果处理模块拆分 |
| NautilusTrader | 专业交易平台 | 消息总线、数据引擎、风控引擎、执行引擎 |
| Freqtrade | 加密交易机器人 | 策略生命周期、交易循环、交易所抽象 |
| Hummingbot | 加密做市和交易系统 | Connector、策略、订单状态跟踪 |
| Backtrader | 回测框架 | Cerebro、Data Feed、Strategy、Analyzer |
| vn.py | 事件驱动交易框架 | EventEngine、Gateway、App 模块 |
| Microsoft Qlib | AI 量化研究平台 | 数据、特征、模型、回测、Recorder |
| FINRA / 监管市场监控 | 市场操纵风险 | Spoofing、Layering、Wash Trading、Momentum Ignition |
| 金融知识图谱 / 因果图 | 外部因素分析 | 事件、实体、关系、时间维度 |

## 3. 成熟系统的共同架构规律

### 3.1 数据和策略解耦

成熟系统通常不会让策略直接依赖原始数据源。

常见结构：

```text
Data Source
→ Normalizer
→ Data Feed / Feature Store
→ Strategy / Analyzer
```

MarketCell 应吸收：

```text
Data Collector
→ Data Normalizer
→ Feature Layer
→ Cell Layer
```

### 3.2 事件驱动

交易系统普遍使用事件驱动。

事件可能包括：

- 新 K 线
- 新成交
- 新闻事件
- 风险事件
- Cell 完成事件
- 报告生成事件

MarketCell 前期可以先同步执行，但架构上要预留：

```text
EventBus
AnalysisTask
CellExecutionEvent
RiskEvent
ReportEvent
```

### 3.3 回测、模拟、实盘尽量共用语义

成熟系统会努力让 backtest / paper / live 共用相似模型。

MarketCell 前期虽然不做交易，但也应该让：

```text
实时分析
历史回放
批量扫描
```

使用同一套 CellResult 和 AnalysisReport。

### 3.4 结果可记录

Qlib、Backtrader 等研究系统非常重视结果记录和分析器。

MarketCell 应吸收：

- 每次分析保存 input snapshot
- 保存 CellResult
- 保存 formula_version
- 保存 report_id
- 后续能 replay

### 3.5 风控和执行分离

NautilusTrader、LEAN、Hummingbot 这类系统都强调执行链路独立。

MarketCell 后期自动交易必须是：

```text
AnalysisReport
→ Signal Adapter
→ Risk Guard
→ Order Manager
→ Exchange Adapter
```

DecisionCell 不能直接下单。

### 3.6 Connector / Gateway 模式

交易所、数据源、新闻源都应该通过 Adapter / Connector 接入。

MarketCell 后期需要：

```text
ExchangeDataConnector
NewsConnector
OnChainConnector
MacroDataConnector
SocialConnector
```

这样 Cell 不需要知道数据来自哪里。

## 4. 对 MarketCell 最有价值的吸收点

## 4.1 从 QuantConnect LEAN 吸收

LEAN 的优点是模块边界清楚：数据、算法执行、交易处理、结果处理分离。

MarketCell 可吸收：

- Data Feed 和 Cell Runtime 分离
- AnalysisResult 和 ReportHandler 分离
- 后期可以增加独立 ResultHandler

对应改进：

```text
AnalysisEngine 不直接负责保存报告
后期新增 ReportService / ReportStore
```

参考：

- https://github.com/QuantConnect/Lean
- https://www.quantconnect.com/docs/v2/writing-algorithms/key-concepts/algorithm-engine

## 4.2 从 NautilusTrader 吸收

NautilusTrader 的核心价值是现代交易系统架构：MessageBus、DataEngine、RiskEngine、ExecutionEngine、Cache。

MarketCell 可吸收：

- MessageBus 思想
- DataEngine / CellRuntime 分离
- RiskEngine 思想用于 ManipulationRisk 和 VolatilityRisk
- Cache 用于共享分析上下文

对应改进：

```text
新增 EventBus 概念
新增 AnalysisContext
新增 RiskEvent
```

参考：

- https://nautilustrader.io/docs/latest/concepts/architecture/

## 4.3 从 Freqtrade 吸收

Freqtrade 的优点是策略生命周期简单清晰，适合个人项目学习：

```text
获取数据
计算指标
生成入场/出场判断
执行交易管理
```

MarketCell 可吸收：

- 先做简单同步流程
- 先让策略/Cell 容易写
- 不要太早复杂服务化

参考：

- https://www.freqtrade.io/en/stable/bot-basics/

## 4.4 从 Hummingbot 吸收

Hummingbot 的重点是连接器和订单生命周期。

MarketCell 现在不做订单，但后期做自动交易时必须吸收：

- Connector 抽象
- 交易所状态同步
- 订单状态跟踪
- WebSocket 优先、REST 兜底

当前只需要在架构中保留：

```text
Trading Gateway
Exchange Adapter
Order State Tracker
```

参考：

- https://hummingbot.org/blog/hummingbot-architecture---part-1/

## 4.5 从 Backtrader 吸收

Backtrader 的 Cerebro 思想很适合 MarketCell：

```text
Data Feed
Strategy
Broker
Analyzer
Observer
```

MarketCell 可吸收：

- Analyzer 概念
- Observer 概念
- 报告和执行分离
- 回测后的分析器体系

对应改进：

```text
Cell 是分析单元
ReportAnalyzer 是报告分析单元
Observer 用于监控运行状态
```

参考：

- https://www.backtrader.com/docu/concepts/
- https://www.backtrader.com/docu/cerebro/

## 4.6 从 vn.py 吸收

vn.py 的事件引擎和 Gateway/App 拆分很适合交易系统长期扩展。

MarketCell 可吸收：

- EventEngine 思路
- Gateway 模式
- App 插件化

后期可以设计：

```text
market_cell/apps/
market_cell/connectors/
market_cell/event_bus/
```

参考：

- https://github.com/vnpy/vnpy

## 4.7 从 Qlib 吸收

Qlib 的价值在于研究工作流：

```text
数据
特征
模型
回测
记录器
```

MarketCell 可吸收：

- Recorder 思想
- Feature Store
- Experiment / Run 概念
- 评估结果沉淀

对应改进：

```text
AnalysisRun
ReportStore
EvaluationStore
```

参考：

- https://github.com/microsoft/qlib
- https://qlib.readthedocs.io/en/latest/

## 4.8 从市场监管吸收

FINRA 等监管机构关注的操纵模式包括：

- Spoofing
- Layering
- Momentum Ignition
- Wash Trading
- Pump and Dump

MarketCell 应吸收：

- 操纵风险必须拆成多个子 Cell
- 输出风险，不输出定罪式结论
- 证据要能解释异常行为模式

参考：

- https://www.finra.org/rules-guidance/guidance/reports/2025-finra-annual-regulatory-oversight-report/manipulative-trading
- https://www.chainalysis.com/blog/crypto-market-manipulation-wash-trading-pump-and-dump-2025/

## 4.9 从知识图谱和因果图吸收

MarketCell 特殊性在于它不是只分析 K 线，还要分析世界因素。

因此需要吸收：

- Entity：国家、公司、资产、资源、交易所、项目方
- Event：战争、制裁、ETF、政策、黑客攻击
- Relation：影响、依赖、冲突、传导
- Time：事件发生时间、影响衰减
- Confidence：关系可信度

对应改进：

```text
FactorGraph 不只是树
每条边需要 direction / weight / confidence / decay
```

参考：

- https://arxiv.org/html/2504.20058v1
- https://arxiv.org/html/2312.17375v2

## 5. 对当前文档体系的改进结论

这轮调研后，MarketCell 文档体系需要新增或强化：

| 改进点 | 需要进入的文档 |
|---|---|
| EventBus / MessageBus | `system_architecture.md`, `backend_architecture.md` |
| ReportStore / Replay | `system_architecture.md`, `roadmap.md` |
| Data Connector | `backend_architecture.md`, 后期 `data_source_strategy.md` |
| Feature Store | `system_architecture.md`, 后期 `data_source_strategy.md` |
| AnalysisRun / Recorder | `evaluation_strategy.md`, `backend_architecture.md` |
| FactorGraph 边属性 | 后期 `factor_graph_design.md` |
| Manipulation Risk 子 Cell | `cell_dictionary.md`, `risk_and_governance.md` |
| Trading Gateway 严格隔离 | `risk_and_governance.md`, `backend_architecture.md` |

## 6. 当前应该立即吸收的设计

不要立刻实现复杂服务，但文档和代码方向要预留：

```text
AnalysisRun
ReportStore
EventBus
DataConnector
FeatureStore
ReplayRunner
Observer
```

这些是后面系统变复杂时的骨架。

## 7. 当前不应该立刻做的事

- 不要现在做微服务。
- 不要现在做自动交易。
- 不要现在做复杂消息队列。
- 不要现在做完整知识图谱数据库。
- 不要现在把所有计算搬到 Rust。

当前应该继续做：

```text
Cell 协议稳定
数据契约稳定
报告结构稳定
验证策略稳定
```
