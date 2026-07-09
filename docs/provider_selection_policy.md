# MarketCell 数据源选择策略 v0.1

## 1. 目标

`ProviderSelectionPolicy` 用来把多个行情数据源整理成稳定的主源、备源和禁用源建议。

它解决的是“应该优先信任谁”的问题，不解决“如何拉取数据”的问题。

核心目标：

- 专业数据商优先于免费开发源。
- 健康趋势差的数据源不能继续做主源。
- 业务偏好、密钥配置和实时/历史能力必须显式可控。
- 输出结果必须可解释，能说明为什么某个源是 primary、backup 或 disabled。

## 2. 架构位置

```text
SourceProfile                 数据源静态能力
ProviderReliabilitySummary    数据源历史健康趋势
ProviderSelectionPreference   业务侧选择偏好
        ↓
ProviderSelectionPolicy
        ↓
ProviderSelectionPlan         primary / backups / disabled
        ↓
RouterPlanBuilder            映射到实际 CandleSource 实例
        ↓
RouterPlan                   可审计路由顺序
        ↓
AnalysisRun.metadata         持久化选择和路由审计
```

当前策略位于：

```text
packages/python/src/market_cell/data/provider_selection.py
packages/python/src/market_cell/data/router_plan.py
```

它属于 Data Layer 的策略层，不属于 Cell Layer，也不属于 Rust 实时热路径。

## 3. 输入

### 3.1 SourceProfile

表示数据源静态画像：

```text
provider
tier
description
supports_realtime
supports_history
requires_api_key
```

当前 tier 分为：

- `professional`：Kaiko、CoinAPI、Databento 这类专业数据商。
- `exchange_direct`：Binance、Coinbase、OKX 等交易所直连。
- `development`：本地 JSON、样例数据、开发回放源。

### 3.2 ProviderReliabilitySummary

表示数据源历史健康趋势，来自 `FileSystemDataQualityStore` 聚合：

```text
average_health_score
latest_health_score
worst_health_score
affected_symbols
affected_horizons
issue_counts
severity_counts
```

### 3.3 ProviderSelectionPreference

表示本次选择的业务偏好：

```text
preferred_providers
disabled_providers
available_api_key_providers
provider_priorities
min_health_score
required_history
required_realtime
```

`available_api_key_providers = None` 表示不检查密钥可用性。

`available_api_key_providers = []` 表示当前没有任何数据商密钥可用，需要禁用所有 `requires_api_key = true` 的源。

## 4. 评分规则

当前选择分数由四部分组成：

```text
selection_score =
  health
+ tier
+ business_priority
+ preferred
+ disabled_penalty
```

健康分不是只看平均值，而是组合：

```text
health =
  average_health_score * 0.50
+ latest_health_score  * 0.35
+ worst_health_score   * 0.15
```

这样可以避免一个长期平均分还不错、但最近已经明显劣化的数据源继续被选成主源。

默认 tier 加分：

| Tier | Bonus |
|---|---:|
| `professional` | 12 |
| `exchange_direct` | 6 |
| `development` | 0 |

这体现了当前系统的数据源原则：

```text
专业数据商优先作为生产历史主源
交易所直连优先作为实时源和校验源
本地源优先作为测试、回放和断网降级源
```

## 5. 禁用条件

数据源满足任意条件时会进入 `disabled`：

- provider 被显式加入 `disabled_providers`
- 本次需要历史数据，但 source 不支持历史
- 本次需要实时数据，但 source 不支持实时
- source 需要 API key，但当前 preference 没有声明该 key 可用
- 组合健康分低于 `min_health_score`
- 最近健康分低于 `min_health_score`

禁用源仍会出现在 `ProviderSelectionPlan.disabled`，并保留 `reason_codes`，方便审计。

## 6. 输出

`ProviderSelectionPlan` 输出：

```text
primary      推荐主源，可能为空
backups      推荐备源列表
disabled     不应该使用的源列表
candidates   最终排序后的全部候选
```

每个 `ProviderSelectionCandidate` 都包含：

```text
provider
tier
role
selection_score
health_score
business_priority
score_components
reason_codes
profile
reliability
```

`score_components` 用来解释分数来源，`reason_codes` 用来解释角色和禁用原因。

`RouterPlanBuilder` 在 `ProviderSelectionPlan` 之后运行，它输出：

```text
entries            已经映射到实际 CandleSource 的主备顺序
disabled           被策略禁用的 provider
missing_providers  策略选中但当前没有 source 实例的 provider
ignored_providers  传入了 source 实例但没有进入 selection plan 的 provider
```

`RouterPlan.to_router()` 会显式生成 `MarketDataRouter`。如果没有任何可路由 source，会抛出错误，而不是静默回退到未经过策略选择的 source。

`RouterPlan.to_run_metadata()` 会输出可直接传给 `AnalysisEngine.run(..., metadata=...)` 的审计信息：

```text
data_sources.provider_selection_plan
data_sources.router_plan
```

保存报告时，这些信息会进入 `AnalysisRun.metadata`，不会进入 `AnalysisReport` 主体，也不会改变 Cell 输出结构。

## 7. 使用示例

```python
from market_cell.data import ProviderSelectionPolicy, ProviderSelectionPreference

preference = ProviderSelectionPreference(
    preferred_providers=["kaiko"],
    available_api_key_providers=["kaiko"],
    required_history=True,
    min_health_score=70,
)

plan = ProviderSelectionPolicy().select(
    profiles=source_profiles,
    reliabilities=provider_reliability_summaries,
    preference=preference,
)
```

构建可执行路由计划：

```python
from market_cell.data import RouterPlanBuilder

router_plan = RouterPlanBuilder().build(available_sources, plan)
router = router_plan.to_router()
```

如果 source 实例和 profile 来自同一批对象，也可以一步完成：

```python
router_plan = RouterPlanBuilder().build_from_sources(
    sources=available_sources,
    reliabilities=provider_reliability_summaries,
    preference=preference,
)
```

保存到运行记录：

```python
from market_cell.engine import AnalysisEngine

report = AnalysisEngine(report_store=store).run(
    request,
    metadata=router_plan.to_run_metadata(),
)
```

## 8. 边界

当前策略只负责生成选择计划。

`RouterPlanBuilder` 只负责把选择计划映射到实际 source 实例。

它们都不会：

- 直接修改 `MarketDataRouter`
- 自动发起网络请求
- 自动切换正在运行的数据源
- 影响 Cell 输出协议
- 替代实时热路径里的连接状态和延迟监控
- 把数据源审计信息混入 `AnalysisReport` 决策字段

`ProviderSelectionPolicy` 不能持有 source 实例，`RouterPlanBuilder` 不能重新计算健康分，`MarketDataRouter` 不能理解业务优先级。三者分开，才能保证策略、配置和运行时行为都可测试。

## 9. 后续增强

- 引入请求成功率、延迟分布和心跳状态。
- 区分历史数据源选择和实时数据源选择。
- 加入 symbol / horizon / venue 级别的可靠性评分。
- 在回放比较中展示数据源计划变化，但不把数据源变化误判成 Cell 公式漂移。
- 将 Rust 热路径产出的实时质量 warning 汇入同一套 reliability 聚合。
