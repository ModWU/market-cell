# MarketCell 数据源质量监控 v0.1

## 1. 目标

K 线数据进入分析前，必须先回答：

- 数据是否能用？
- 是否有缺口、重复、乱序或非法 OHLCV？
- 是否已经陈旧？
- 是否有异常成交量或异常振幅？
- 主数据源和参考数据源是否明显偏离？

这些问题不能交给单个 Cell 临时判断。它们属于数据层的质量门。

## 2. 当前代码落点

```text
packages/python/src/market_cell/data/
├── quality.py      # 单批 K 线基础合法性检查
├── monitoring.py   # SourceQualityMonitor，生成结构化质量问题
└── sources.py      # 数据源协议和主备路由
```

当前新增：

- `DataQualityIssue`：稳定问题码、等级、消息和元数据。
- `SourceQualityReport`：单源质量报告。
- `SourceComparisonReport`：跨源比较报告。
- `SourceQualityMonitor`：统一检测入口。
- `FileSystemDataQualityStore`：把质量问题持久化为 JSONL 时间序列。
- `SourceHealthSummary`：按 provider / symbol / horizon 聚合质量问题，输出健康评分。
- `SourceHealthTrendPoint`：按小时或天生成健康评分趋势点。
- `ProviderReliabilitySummary`：按 provider 聚合趋势点，输出基础可靠性排名输入。
- `ProviderSelectionPolicy`：读取 provider 可靠性摘要和源画像，输出主源/备源/禁用源建议。

## 3. 问题码

当前问题码：

| Code | 含义 | 默认等级 |
|---|---|---|
| `invalid_ohlcv` | 空数据、重复时间戳、乱序、非法价格或成交量 | critical |
| `invalid_timestamp` | 时间戳无法解析 | critical |
| `time_gap` | 相邻 K 线间隔超过预期 | warning |
| `stale_data` | 最新 K 线距离当前时间过久 | warning |
| `volume_spike` | 最新成交量显著高于历史均值 | warning |
| `range_spike` | 最新振幅显著高于历史均值 | warning |
| `cross_source_no_overlap` | 两个源没有可比较的重叠 K 线 | warning |
| `cross_source_close_deviation` | 主源和参考源收盘价偏差超过阈值 | warning |

`critical` 会让 `SourceQualityReport.is_usable = false`。`warning` 默认不拒绝数据，但应该进入报告、日志或监控面板。

## 4. 使用方式

```python
from market_cell.data import SourceQualityMonitor

monitor = SourceQualityMonitor(stale_after_ms=3_600_000)
report = monitor.inspect_batch(batch, now="2026-07-09T05:30:00Z")
```

跨源比较：

```python
comparison = monitor.compare_sources(primary_batch, reference_batch)
```

保存质量问题：

```python
from market_cell.data import FileSystemDataQualityStore

store = FileSystemDataQualityStore()
store.save_source_report(report)
store.save_comparison_report(comparison)
```

查询历史问题：

```python
records = store.list_records(source_provider="kaiko", symbol="BTC/USD", code="time_gap")
```

生成健康摘要：

```python
summaries = store.summarize(source_provider="kaiko", symbol="BTC/USD")
```

生成健康趋势和 provider 可靠性摘要：

```python
trends = store.health_trends(source_provider="kaiko", symbol="BTC/USD", window="day")
providers = store.provider_reliability(window="day")
```

## 5. 架构边界

- SourceQualityMonitor 不访问网络。
- SourceQualityMonitor 不保存数据。
- SourceQualityMonitor 不生成交易结论。
- FileSystemDataQualityStore 只保存结构化质量问题，不改变数据源返回值。
- Router 可以用基础合法性检查做主备降级。
- 后续监控服务可以持久化 `DataQualityIssue`，但不能改变 Cell 输出协议。

## 6. 存储布局

默认 JSONL 路径：

```text
.market_cell_cache/data_quality/
provider=<source_provider>/
symbol=<symbol>/
horizon=<horizon>/
date=<YYYY-MM-DD>/
issues.jsonl
```

每行是一个 `DataQualityRecord`：

```text
record_id
kind
observed_at
issue
context
```

`kind` 当前支持：

- `source_quality`
- `source_comparison`

## 7. 健康评分

`SourceHealthSummary` 当前按已记录问题扣分：

```text
critical: -20
warning:  -5
info:     -1
```

等级：

| Score | Grade |
|---|---|
| `>= 95` | `excellent` |
| `>= 85` | `good` |
| `>= 70` | `degraded` |
| `< 70` | `poor` |

当前评分只代表“已记录质量问题的负担”，不是完整 SLA 可用率。后续接入数据源正常心跳、请求成功率、延迟分布后，才能升级为更完整的 provider reliability score。

## 8. 健康趋势和可靠性摘要

`SourceHealthTrendPoint` 支持按 `hour` 或 `day` 聚合：

```text
source_provider
symbol
horizon
window
window_start
record_count
health_score
health_grade
severity_counts
issue_counts
dominant_issue_codes
```

`ProviderReliabilitySummary` 聚合多个趋势点：

```text
source_provider
trend_point_count
record_count
average_health_score
latest_health_score
worst_health_score
health_grade
affected_symbols
affected_horizons
severity_counts
issue_counts
first_window_start
last_window_start
```

当前 provider 排名依据：

```text
average_health_score desc
latest_health_score desc
worst_health_score desc
record_count asc
source_provider asc
```

这能用于早期主备源选择，但不能替代真实 SLA、延迟分布和请求成功率。

`ProviderSelectionPolicy` 在这个基础上进一步加入：

- 源等级：专业数据商、交易所直连、开发源。
- 最近健康分：最近质量下滑的数据源不能继续做主源。
- API key 可用性：专业数据商密钥未配置时不能被推荐为可用源。
- 业务偏好：允许显式偏好、禁用和优先级调整。

## 9. 后续增强

- 把 JSONL 质量记录升级为 Parquet，支持更快查询和聚合。
- 在 Rust 热路径生成实时 `DataQualityWarning`。
- 建立跨源价差的动态阈值，而不是固定百分比。
- 增加交易所维护、停盘、低流动性时段的例外规则。
- 在报告中标注数据质量对结论可信度的影响。
- 增加告警阈值、心跳成功率和延迟分布，并纳入 provider selection score。
