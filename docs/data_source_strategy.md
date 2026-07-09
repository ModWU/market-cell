# MarketCell 数据源策略 v0.1

## 1. 目标

MarketCell 是一个长期市场分析系统，K 线数据源必须按高稳定性、高可追踪性、高性能设计。

免费交易所 REST API 可以用于开发、回补和交叉校验，但不能作为唯一生产主源。

## 2. 分层数据源策略

推荐采用三层：

```text
Professional Data Provider  专业数据商，主历史源和标准化源
Exchange Direct             交易所官方 REST/WebSocket，实时源和校验源
Local Cache / Replay         本地缓存、回放、测试和断网降级
```

### 2.1 专业数据商

适合：

- 历史回测
- 多交易所标准化
- 大批量 OHLCV / trades / order book 数据
- SLA 和长期数据一致性要求

候选：

- Kaiko：适合机构级加密市场历史、OHLCV、订单簿和跨交易所数据。
- CoinAPI：适合 OHLCV、trades、quotes、order book，以及大规模 flat files。
- Databento：更适合传统金融市场、期货、股票、期权等高质量历史和实时数据。

### 2.2 交易所官方直连

适合：

- 实时行情
- 最近 K 线回补
- 主数据源校验
- 特定交易所策略分析

候选：

- Binance Spot/Futures：流动性强，公开 K 线 REST 和 WebSocket 完整，但区域可用性和规则变化需要监控。
- Coinbase Exchange：适合美国合规交易所视角。
- Kraken / OKX：适合多交易所交叉验证。

### 2.3 本地缓存和回放

必须保留：

- JSON/CSV 样例输入
- Parquet 历史缓存
- DuckDB 查询层
- AnalysisRun input_snapshot

原因：

- 外部 API 可能限流、维护、断网或返回异常。
- 回测和复盘必须可重复。
- CI 不能依赖外部行情 API。

## 3. 当前代码落点

当前新增：

```text
packages/python/src/market_cell/data/
├── sources.py      # CandleSource 协议、CandleQuery、CandleBatch、MarketDataRouter
├── cache.py        # CandleCache 协议和文件缓存实现
├── storage.py      # Parquet/DuckDB 存储适配基础
├── quality.py      # K 线质量检查
├── monitoring.py   # 数据源质量监控和跨源比较
├── provider_selection.py # 基于健康趋势和业务偏好的主备源选择策略
├── router_plan.py  # 把主备源选择计划映射成可审计路由顺序
└── binance.py      # Binance Spot Kline 开发/备份适配器
```

当前原则：

- Cell 不直接访问网络。
- Engine 不绑定具体数据商。
- Data Source 返回 `CandleBatch`，必须带 source profile。
- Router 支持主备降级。
- Router 会检查 K 线质量，拒绝空数据、重复时间戳、乱序和非法 OHLCV。
- `CachedCandleSource` 可包装任意数据源，减少重复外部请求。
- `ParquetCandleStore` 和 `DuckDBCandleSource` 为本地历史缓存和研究查询提供可选扩展。
- `SourceQualityMonitor` 可生成缺口、陈旧、异常量价和跨源偏差的结构化质量报告。
- `FileSystemDataQualityStore` 可把质量问题写入 JSONL，形成数据源健康时间序列。
- `SourceHealthSummary` 可按 provider / symbol / horizon 聚合问题，输出基础健康评分。
- `SourceHealthTrendPoint` 和 `ProviderReliabilitySummary` 可形成按时间窗口的健康趋势和 provider 排名输入。
- `ProviderSelectionPolicy` 可根据源等级、健康趋势、业务偏好、实时/历史能力和 API key 可用性输出 primary / backups / disabled 计划。
- `RouterPlanBuilder` 可把 `ProviderSelectionPlan` 映射到实际 `CandleSource` 实例，记录缺失 provider、禁用 provider 和未进入计划的 source。
- `RouterPlan.to_run_metadata()` 可把选择计划和实际路由计划写入 `AnalysisRun.metadata`，为报告复盘保留数据源审计链。
- 测试只使用本地文件和假源，不依赖外部 API。

## 4. 生产建议

如果目标是高稳定性和专业化，建议：

```text
主历史源：Kaiko 或 CoinAPI flat files/API
主实时源：交易所官方 WebSocket 或专业数据商 streaming
备份源：第二家专业数据商 + 交易所 REST
本地层：Parquet + DuckDB
监控层：延迟、缺口、重复、跨源价差、异常成交量
```

对加密资产：

- 不要只看单一交易所 K 线。
- 至少保留 `exchange`、`symbol`、`interval`、`source_provider`、`fetched_at`。
- 后期需要区分 spot、perpetual futures、index price、mark price。

对传统资产：

- 优先使用专业数据商。
- 交易所或券商 API 只适合补充，不适合做统一历史研究主源。

## 5. 后续实现顺序

1. Runtime Architecture：把 Rust 动态热路径、Python 静态冷路径和存储交接写清楚。
2. Realtime / Batch Contracts：用 Protobuf 描述实时事件，用 Parquet schema 描述历史 K 线。
3. Feature Layer：把 K 线转成稳定特征快照。
4. Parquet/DuckDB Cache Hardening：补齐去重、upsert、批量压缩和查询窗口。
5. Professional Provider Adapter：优先接 CoinAPI 或 Kaiko。
6. Replay Source Audit：回放时展示数据源计划变化。
7. Realtime Stream Worker：独立于分析内核处理 WebSocket。

## 6. 官方资料入口

- Binance Spot market data endpoints: https://developers.binance.com/docs/binance-spot-api-docs/rest-api/market-data-endpoints
- Binance WebSocket streams: https://developers.binance.com/docs/binance-spot-api-docs/web-socket-streams
- CoinAPI OHLCV REST API: https://docs.coinapi.io/market-data/rest-api/ohlcv
- CoinAPI flat files: https://docs.coinapi.io/market-data/flat-files
- Kaiko docs: https://docs.kaiko.com/
- Databento docs: https://docs.databento.com/
