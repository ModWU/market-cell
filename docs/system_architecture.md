# MarketCell 系统架构文档 v0.2

## 1. 架构目标

MarketCell 的架构目标是构建一个可解释、可扩展、可回放的市场分析后台系统。

第一阶段只做后台分析闭环，不做界面，不做自动交易。

架构必须支持未来扩展到：

- 多资产
- 多周期
- 多数据源
- 因子图
- AI 解释
- 实时分析
- 自动交易前置系统

## 2. 总体架构图

```mermaid
flowchart TD
    User["用户 / 调用方"] --> CLI["CLI / API 输入层"]
    CLI --> Parser["Request Parser"]
    Parser --> Validator["Input Validator"]
    Validator --> Runtime["Analysis Runtime"]

    Runtime --> Registry["Cell Registry"]
    Runtime --> Planner["Analysis Planner"]
    Runtime --> Executor["Cell Executor"]

    Registry --> Cells["Cell Library"]
    Planner --> Graph["Factor Graph"]
    Executor --> Scoring["Scoring Engine"]

    Cells --> Technical["Technical Cells"]
    Cells --> Risk["Risk Cells"]
    Cells --> External["External Event Cells"]
    Cells --> Macro["Macro / Resource Cells"]
    Cells --> Crypto["Crypto Cells"]

    Scoring --> Decision["Decision Cell"]
    Decision --> Report["Structured Report"]
    Report --> Storage["Report Store / Replay"]
    Report --> AI["AI Explainer"]
    Report --> UI["Future Visualization"]

    Realtime["Rust Realtime Core"] -. later .-> Runtime
    Trading["Future Trading Gateway"] -. later .-> Report
```

当前已经实现：

- 多语言 workspace 初版：`packages/python`、`crates`、`contracts`
- CLI 输入层
- Request Parser
- Input Validator
- Cell Registry
- 固定 Cell 执行器
- Scoring Engine 初版
- DecisionCell
- DecisionPolicy 策略层
- EventBus
- AnalysisRun / Recorder 初版
- FileSystemReportStore
- ReplayRunner
- JSON Report v1
- JSON Schema 契约
- Protobuf 行情事件契约
- Parquet K 线批量存储契约
- Rust market_data_core 行情原语
- Rust realtime_core 预留

未来实现：

- Analysis Planner
- Factor Graph
- Data Connector / Feature Store
- AI Explainer
- Visualization
- Trading Gateway

## 2.1 外部成熟系统吸收点

MarketCell 吸收成熟交易和量化系统的架构经验，但不照搬。

| 来源 | 值得吸收 | MarketCell 中的落点 |
|---|---|---|
| QuantConnect LEAN | 数据、算法、交易、结果处理分离 | Data Layer、Cell Runtime、Report Store 分离 |
| NautilusTrader | MessageBus、DataEngine、RiskEngine、ExecutionEngine | EventBus、Risk Cell、未来 Trading Gateway |
| Freqtrade | 简单清晰的策略生命周期 | 当前阶段保持同步 CLI 和简单 Engine |
| Hummingbot | Connector 和订单状态跟踪 | 后期 Exchange Adapter、Order State Tracker |
| Backtrader | Data Feed、Strategy、Analyzer、Observer | Data Connector、Cell、ReportAnalyzer、Observer |
| vn.py | EventEngine、Gateway、App 插件化 | 后期 EventBus、Connector、App 模块 |
| Qlib | Recorder、Feature Store、研究工作流 | AnalysisRun、Feature Store、EvaluationStore |
| 市场监管 | Spoofing、Layering、Wash Trading 等异常模式 | Manipulation Risk Cell 族 |

核心结论：

```text
MarketCell 不能只是 Cell 列表。
它需要逐步演进为 Data + Event + Cell + Report + Replay 的分析系统。
```

## 3. 分层架构

```mermaid
flowchart TB
    L1["Interface Layer<br/>CLI / Future API / Future UI"]
    L2["Application Layer<br/>AnalysisEngine / Runtime / Planner"]
    L3["Domain Layer<br/>Cell / CellResult / Evidence / Scoring"]
    L4["Data Layer<br/>Candles / Events / Context / Feature Store"]
    L5["Infrastructure Layer<br/>Storage / Cache / Rust Core / External Connectors"]

    L1 --> L2
    L2 --> L3
    L3 --> L4
    L2 --> L5
    L5 --> L4
```

### 3.1 Interface Layer

负责接收输入和输出结果。

当前：

- CLI
- JSON 输入
- JSON 输出

后期：

- FastAPI
- WebSocket
- 可视化界面
- 自动交易系统调用入口

### 3.2 Application Layer

负责任务编排。

当前：

- AnalysisEngine
- 固定 Cell 列表执行
- DecisionCell 聚合

后期：

- AnalysisPlanner
- 多周期任务拆分
- 任务并发执行
- 回放任务
- 定时任务

### 3.3 Domain Layer

系统的核心领域模型。

包括：

- Cell
- CellManifest
- AnalysisRequest
- CellResult
- Evidence
- AnalysisReport
- Scoring

这一层必须稳定。后面无论接什么数据源，都不能破坏核心协议。

### 3.4 Data Layer

负责市场数据和外部事件数据。

当前：

- Candle
- MarketEvent
- context

后期：

- OrderBookSnapshot
- TradeTick
- FundingRate
- OpenInterest
- OnChainFlow
- MacroEvent
- NewsArticle

### 3.5 Infrastructure Layer

负责外部系统和性能模块。

后期包括：

- DuckDB
- Parquet
- PostgreSQL
- Redis
- 交易所 API
- 新闻 API
- 链上数据 API
- Rust realtime_core

## 4. 运行流程

```mermaid
sequenceDiagram
    participant U as User
    participant CLI as CLI
    participant P as Parser
    participant V as Validator
    participant E as AnalysisEngine
    participant C as CellRegistry
    participant X as CellExecutor
    participant D as DecisionCell
    participant R as Report

    U->>CLI: market-cell analyze input.json
    CLI->>P: 读取 JSON
    P->>V: 构建 AnalysisRequest
    V->>V: 校验 K 线和上下文
    V->>E: 传入合法请求
    E->>C: 获取已注册 Cell
    E->>X: 执行叶子 Cell
    X-->>E: 返回多个 CellResult
    E->>D: 聚合子节点结果
    D-->>E: 返回根节点 CellResult
    E->>R: 生成 AnalysisReport
    R-->>CLI: 输出 JSON
    CLI-->>U: 分析结果
```

## 5. 核心领域模型

```mermaid
classDiagram
    class AnalysisRequest {
        target
        horizon
        candles
        events
        context
    }

    class Candle {
        timestamp
        open
        high
        low
        close
        volume
    }

    class MarketEvent {
        title
        category
        sentiment
        impact
        freshness
    }

    class MarketCell {
        cell_id
        name
        category
        manifest()
        analyze()
    }

    class CellManifest {
        cell_id
        name
        category
        description
        inputs
        outputs
        formula_version
        risk_dimensions
        status
    }

    class CellResult {
        direction
        strength
        confidence
        volatility_risk
        manipulation_risk
        urgency
        score
        explanation
    }

    class Evidence {
        source
        summary
        weight
        freshness
        reliability
    }

    class AnalysisReport {
        target
        horizon
        decision
        summary
        disclaimer
    }

    AnalysisRequest "1" --> "*" Candle
    AnalysisRequest "1" --> "*" MarketEvent
    MarketCell "1" --> "1" CellManifest
    MarketCell "1" --> "1" CellResult
    CellResult "1" --> "*" Evidence
    CellResult "1" --> "*" CellResult
    AnalysisReport "1" --> "1" CellResult
```

## 6. Cell 系统架构

Cell 是 MarketCell 的最小分析单元。

每个 Cell 都必须遵守统一协议：

```text
analyze(request, child_results) -> CellResult
```

### 6.1 Cell 分类

```mermaid
mindmap
  root((MarketCell))
    Technical
      TrendCell
      VolumeCell
      VolatilityCell
      MarketRegimeCell
      SupportResistanceCell
    Risk
      ManipulationRiskCell
      LiquidityFragilityCell
      PumpDumpCell
      ExchangeDivergenceCell
    External
      NewsEventCell
      SocialSentimentCell
      PolicyEventCell
    Macro
      DollarLiquidityCell
      InterestRateCell
      OilCell
      GoldCell
    Crypto
      OnChainFlowCell
      StablecoinFlowCell
      FundingOpenInterestCell
      ExchangeBalanceCell
    Decision
      DecisionCell
      HorizonDecisionCell
      StrategyModeCell
```

### 6.2 Cell 生命周期

```mermaid
stateDiagram-v2
    [*] --> Draft
    Draft --> Experimental: 有实现和样例
    Experimental --> Validated: 有测试和回测证据
    Validated --> Deprecated: 被更好公式替代
    Deprecated --> [*]
    Experimental --> Deprecated: 误判过多
```

生命周期含义：

- Draft：只有想法或草稿
- Experimental：可以运行，但还没充分验证
- Validated：经过测试、样例、回放验证
- Deprecated：保留兼容，但不推荐继续使用

## 7. 因子图和分析树

MarketCell 长期不能只用固定树。

现实市场是网状影响关系：

```mermaid
flowchart LR
    War["战争风险"] --> Oil["石油"]
    Oil --> Inflation["通胀"]
    Inflation --> Rate["利率预期"]
    Rate --> USD["美元流动性"]
    USD --> BTC["BTC/USD"]

    War --> RiskAppetite["全球风险偏好"]
    RiskAppetite --> BTC

    War --> Gold["黄金"]
    Gold --> BTC

    Regulation["监管政策"] --> CryptoLiquidity["加密流动性"]
    CryptoLiquidity --> BTC

    Stablecoin["稳定币流入"] --> CryptoLiquidity
    ETF["ETF / 机构资金"] --> BTC
```

底层应该保存为 Factor Graph。

一次分析任务再从图里抽取 Analysis Tree：

```mermaid
flowchart TD
    Root["DecisionCell<br/>BTC/USD 1h"] --> T["TrendCell"]
    Root --> V["VolumeCell"]
    Root --> R["MarketRegimeCell"]
    Root --> N["NewsEventCell"]
    Root --> M["ManipulationRiskCell"]

    M --> VP["VolumePriceAnomalyCell"]
    M --> LIQ["LiquidityFragilityCell"]
    M --> WICK["LongWickPattern"]
```

这就是：

```text
Factor Graph 负责表达世界关系
Analysis Tree 负责一次任务怎么执行
```

## 8. 数据流

```mermaid
flowchart LR
    Raw["Raw Data<br/>交易所 / 新闻 / 链上 / 宏观"] --> Normalize["Normalize<br/>标准化"]
    Normalize --> Validate["Validate<br/>校验"]
    Validate --> Feature["Feature Engine<br/>特征计算"]
    Feature --> Request["AnalysisRequest"]
    Request --> Cells["Cell Execution"]
    Cells --> Results["CellResults"]
    Results --> Decision["DecisionCell"]
    Decision --> Report["AnalysisReport"]
    Report --> Store["Report Store"]
    Store --> Replay["Replay / Review"]
```

当前 v0.2 从 AnalysisRequest 开始。

真实数据接入后，前面会增加：

- collector
- normalizer
- feature engine
- storage

## 9. 评分和聚合模型

第一版评分必须可解释。

方向值：

```text
bullish = 1
bearish = -1
neutral = 0
conflict = 0
```

子节点分数：

```text
score = direction_value * strength * confidence / 100
```

父节点聚合：

```text
weighted_score = Σ child.score * child.weight
final_score = weighted_score / Σ child.weight
```

风险单独聚合：

```text
volatility_risk = max(child.volatility_risk)
manipulation_risk = max(child.manipulation_risk)
urgency = max(direction_strength, volatility_risk, manipulation_risk)
```

重要原则：

```text
方向不等于风险
信号不等于仓位
分析不等于下单
```

## 10. 操纵风险子系统

操纵风险是 MarketCell 的核心差异之一。

```mermaid
flowchart TD
    M["ManipulationRiskCell"] --> VPA["VolumePriceAnomalyCell<br/>量价异常"]
    M --> PDC["PumpDumpCell<br/>拉盘出货"]
    M --> LFC["LiquidityFragilityCell<br/>流动性脆弱"]
    M --> EDC["ExchangeDivergenceCell<br/>交易所偏离"]
    M --> FOI["FundingOpenInterestCell<br/>资金费率和持仓"]
    M --> SHM["SocialHypeMismatchCell<br/>热度和资金不匹配"]
    M --> WHALE["WhaleConcentrationCell<br/>大户集中"]

    VPA --> MR["Manipulation Risk Score"]
    PDC --> MR
    LFC --> MR
    EDC --> MR
    FOI --> MR
    SHM --> MR
    WHALE --> MR
```

输出原则：

- 输出“操纵风险”
- 不输出“确定操纵”
- 每个风险必须有证据
- 风险判断必须保留置信度

## 11. Python 和 Rust 边界

```mermaid
flowchart LR
    Python["Python Analysis Brain"] --> Domain["Domain Models / Cell Runtime"]
    Python --> AI["AI Explainer"]
    Python --> Research["Research / Backtest / Reports"]

    Rust["Rust Realtime Core"] --> Stream["Realtime Market Stream"]
    Rust --> OrderBook["OrderBook Analysis"]
    Rust --> HotPath["Hot Path Computation"]
    Rust --> RiskGuard["Future Risk Guard"]

    Rust -. FFI / Service / File / Queue .-> Python
    Python -. Config / Task .-> Rust
```

当前策略：

- Python 实现分析系统主体
- Python 负责静态分析、研究、回放和报告解释
- Rust 负责动态数据、实时聚合和性能热点
- Rust 先以 `market_data_core` 稳定行情原语，再演进实时 worker
- 不急着跨语言调用

未来 Rust 适合迁移：

- 订单簿计算
- 高频波动检测
- 实时数据流
- 大规模指标热点
- 自动交易风控核心

更详细的冷热路径边界见 `runtime_architecture.md`。

## 12. 存储架构规划

```mermaid
flowchart TD
    Collectors["Data Collectors"] --> Parquet["Parquet<br/>历史行情和特征"]
    Collectors --> DuckDB["DuckDB<br/>本地研究查询"]
    Runtime["Analysis Runtime"] --> Reports["Report Store<br/>JSON / PostgreSQL"]
    Runtime --> Cache["Redis<br/>实时状态缓存"]
    Reports --> Replay["Replay Engine"]
    DuckDB --> Feature["Feature Engine"]
    Parquet --> Feature
    Feature --> Runtime
```

阶段选择：

- v0.2：不接数据库，只用 JSON
- v0.5：Parquet + DuckDB
- v0.8：PostgreSQL 保存任务和报告
- v1.0：Redis 支持实时状态

## 13. 后期服务化架构

```mermaid
flowchart TD
    Client["CLI / Web UI / Trading System"] --> API["FastAPI Gateway"]
    API --> Task["Analysis Task Service"]
    Task --> Planner["Analysis Planner"]
    Planner --> Runtime["Cell Runtime"]
    Runtime --> Store["Report Store"]
    Runtime --> Data["Market Data Service"]
    Runtime --> AI["AI Explanation Service"]
    Runtime --> RustCore["Rust Realtime Service"]
    Store --> Client
```

服务化后，CLI 只是其中一个客户端。

## 14. 目录结构规划

当前结构：

```text
market-cell/
├── contracts/
│   └── json_schema/
├── docs/
├── examples/
├── packages/
│   └── python/
│       ├── src/market_cell/
│       │   ├── cells/
│       │   ├── policies/
│       │   ├── reports/
│       │   ├── cli.py
│       │   ├── engine.py
│       │   ├── models.py
│       │   ├── registry.py
│       │   ├── scoring.py
│       │   └── validation.py
│       └── tests/
└── crates/
    ├── market_data_core/
    └── realtime_core/
```

Python 包内部后期结构：

```text
packages/python/src/market_cell/
├── api/
├── app/
├── cells/
├── data/
├── features/
├── graph/
├── runtime/
├── replay/
├── reports/
├── storage/
└── ai/
```

## 15. 架构演进路线

### v0.2 当前目标

- 完整产品文档
- 完整系统架构文档
- Cell Manifest
- 输入校验
- Cell Registry
- MarketRegimeCell

### v0.3 Cell 扩展

- SupportResistanceCell
- BreakoutCell
- LiquidityCell
- FundingOpenInterestCell

### v0.4 多周期分析

- MultiHorizonRequest
- HorizonDecisionCell
- 多周期冲突判断

### v0.5 数据接入

- 交易所 K 线
- 本地缓存
- Parquet / DuckDB

### v0.6 回放系统

- 保存每次分析
- 回放历史输入
- 对比后续真实走势

### v0.7 AI 解释层

- AI 解释报告
- AI 总结冲突
- AI 生成复盘

### v1.0 自动交易前置

- Trading Gateway
- Risk Guard
- Position Manager
- Order Manager
- Exchange Adapter

## 16. 关键架构原则

1. 分析和交易分离
2. 方向和风险分离
3. 证据和结论绑定
4. Cell 可以独立测试
5. 公式必须版本化
6. 输入必须先校验
7. 报告必须可回放
8. Rust 只负责高性能边界，不抢 Python 的研究效率
9. AI 负责解释和辅助，不直接替代规则系统
10. 系统先稳定，再复杂
