# MarketCell Feature Layer 设计 v0.1

## 1. 目标

Feature Layer 负责把原始 K 线转换成可复用、可测试、可版本化的市场特征。

它不是 Cell，也不输出方向结论。它只回答：

```text
这批 K 线可以提取出哪些稳定的量价事实？
```

## 2. 当前实现

当前代码位置：

```text
packages/python/src/market_cell/features/
├── __init__.py
└── market.py
```

核心对象：

```text
FeatureSnapshot
```

当前版本：

```text
market_features_v0.1
```

## 3. 当前特征

`FeatureSnapshot` 当前包含：

- `candle_count`
- `first_close`
- `last_close`
- `close_change_pct`
- `latest_close_change`
- `previous_average_volume`
- `latest_volume_ratio`
- `average_range_pct`
- `latest_range_pct`
- `latest_wick_ratio`
- `total_move_pct`
- `path_distance_pct`
- `trend_efficiency`

这些特征被以下 Cell 复用：

- `TrendCell`
- `VolumeCell`
- `VolatilityCell`
- `MarketRegimeCell`
- `ManipulationRiskCell`

## 4. 架构边界

Feature Layer 可以：

- 计算可复用的量价特征
- 对特征公式版本化
- 被多个 Cell 复用
- 被未来 Rust 性能模块替代热点计算

Feature Layer 不可以：

- 输出交易建议
- 直接访问外部数据源
- 直接保存报告
- 私自绕过 `AnalysisRequest`

## 5. 性能演进

当前阶段每个 Cell 调用 `build_feature_snapshot`。这保持简单和可读。

数据源层已经有 `CandleCache`，负责减少外部行情请求。Feature Layer 后续会增加 `FeatureCache`，负责减少同一批 K 线在多个 Cell 中重复计算。

当 Cell 数量增多或性能压测显示重复计算明显时，下一步升级为：

```text
AnalysisEngine
→ FeatureRuntime / FeatureCache
→ CellRuntime
→ Cell
```

更后期可把高频特征迁到 Rust：

```text
crates/realtime_core
```

但迁移前必须保持 Python 版本作为可读、可测试的参考实现。
