# MarketCell Cell 公式与验证记录

## 1. 文档职责

本文记录新增 Cell 的公式边界、机器可读验证数据和已知误判风险。它不把 `experimental` Cell 宣称为已经通过历史回测；进入 `validated` 仍需满足 `cell_protocol.md` 和 `evaluation_strategy.md` 的完整门槛。

机器可读样例位于：

```text
validation/cells/<cell_name>_vN.json
```

每个样例至少区分正常方向、边界输入和已知误判防护，并由单元测试直接消费，避免文档样例与真实公式漂移。

## 2. SupportResistanceCell

### 2.1 身份和状态

```text
cell_id          technical.support_resistance
formula_version  support_resistance_cluster_rejection_v0.1
status           experimental
validation_data  validation/cells/support_resistance_v0.1.json
```

状态输入是历史 K 线和最新一根 K 线。行为是识别局部支撑/压力区并判断最新价格对该区域的响应。输出边界仍是标准 `CellResult`；Cell 不读取外部行情、不确认长期趋势，也不执行交易动作。

### 2.2 公式规则

1. 至少需要 6 根 K 线；最后一根只用于验证当前响应，不参与历史价位拟合。
2. 只使用最新 48 根历史 K 线，避免无限窗口让过时价位长期支配结果；历史低点和高点分别做确定性的密集聚类。
3. 聚类容差为 `clamp(历史平均振幅 × 0.35, 0.25%, 1.5%)`。
4. 一个价位至少有 2 个历史触点才算确认。
5. 只有最新 K 线测试已确认价位并明显收回时，才输出 bullish 或 bearish。
6. 同一根 K 线同时触及支撑和压力时输出 `conflict`，不从宽幅震荡中强行选择方向。
7. 单次收盘越过价位只输出 `conflict`，状态记为 `*_broken_unconfirmed`；有效突破由后续 BreakoutCell 独立确认。

主要状态迁移：

```text
insufficient_history
→ unconfirmed_levels / inside_range
→ testing_support / testing_resistance
→ support_rejection / resistance_rejection
→ support_broken_unconfirmed / resistance_broken_unconfirmed
```

### 2.3 固定验证样例

| case_id | 类型 | 预期 |
|---|---|---|
| `repeated_support_with_bullish_rejection` | 正常方向 | 重复支撑被测试并收回，bullish |
| `repeated_resistance_with_bearish_rejection` | 正常方向 | 重复压力被测试并回落，bearish |
| `insufficient_history_stays_neutral` | 边界 | 历史不足，neutral |
| `wide_candle_touching_both_zones_is_conflict` | 边界 | 同时触及两侧区域，conflict |
| `isolated_deep_wick_is_not_support` | 误判防护 | 孤立深影线不成为支撑，记录结构破坏 |

### 2.4 已知误判和限制

- 直接使用窗口最低点会把孤立深影线误当支撑。当前公式要求重复触点，并以验证样例固定这一防护。
- 单一周期的小样本只能说明局部价格结构，不能证明长期支撑或压力。
- 新闻跳空、流动性骤降、错误复权或异常数据可能让历史价位快速失效。
- 当前没有历史回放命中率、突破后续走势标签和跨周期一致性数据，因此状态保持 `experimental`。

## 3. BreakoutCell

### 3.1 身份、依赖和边界

```text
cell_id          technical.breakout
formula_version  breakout_structure_volume_confirmation_v0.1
status           experimental
dependency       technical.support_resistance
validation_data  validation/cells/breakout_v0.1.json
```

BreakoutCell 是默认图中的 aggregator，只消费同一 target、同一 horizon、公式版本为 `support_resistance_cluster_rejection_v0.1` 的一个 SupportResistanceCell 结果。它不重新拟合价位，而是复核 `support_broken_unconfirmed` 或 `resistance_broken_unconfirmed` 是否能转移为已确认突破。未知上游状态或公式版本漂移会直接失败，不能静默降级为 neutral。

### 3.2 确认规则

候选突破必须同时满足：

1. 最新收盘已经越过 SupportResistanceCell 给出的容差阈值。
2. 前一根收盘仍在阈值内，证明这是本根 K 线的新鲜越界，而不是重复报告延续走势。
3. 向上突破收在本根振幅上方 30% 区域且实体向上；向下突破收在下方 30% 区域且实体向下。
4. 最新成交量至少为历史基线的 `1.2` 倍；基线最多使用最近 20 根历史 K 线。

三个确认条件全部通过才输出 bullish 或 bearish。任何条件缺失都输出 `conflict` 并列出 `failed_confirmations`，没有候选结构时保持 neutral。

```text
no_breakout_candidate / insufficient_structure
→ upside/downside candidate
→ breakout_not_fresh
  / breakout_unconfirmed_candle
  / breakout_unconfirmed_volume
  / breakout_unconfirmed_multiple
→ upside_breakout_confirmed / downside_breakout_confirmed
```

### 3.3 固定验证样例

| case_id | 类型 | 预期 |
|---|---|---|
| `fresh_upside_breakout_with_volume` | 正常方向 | 新鲜向上越界且放量，bullish |
| `fresh_downside_breakout_with_volume` | 正常方向 | 新鲜向下越界且放量，bearish |
| `upside_break_without_volume_is_not_confirmed` | 误判防护 | 弱量穿越只记 conflict |
| `continued_move_after_prior_break_is_not_fresh` | 误判防护 | 已越界后的延续不重复确认 |
| `insufficient_structure_stays_neutral` | 边界 | 支撑压力历史不足，neutral |

### 3.4 已知误判和限制

- 放量与强收盘只能提高可信度，不能保证后续不会快速回落或形成假突破。
- 当前不评估突破后的回踩质量、盘口流动性和多周期一致性。
- 成交量基线在极端低流动性或数据缺口场景下仍可能失真。
- 当前没有历史标签证明突破后续走势，因此状态保持 `experimental`。

## 4. LiquidityCell

### 4.1 身份、输入和图边界

```text
cell_id          microstructure.liquidity
formula_version  order_book_depth_spread_imbalance_v0.1
status           experimental
required_inputs  analysis_request + order_book_snapshot
validation_data  validation/cells/liquidity_v0.1.json
graph             market.liquidity_analysis@0.2.0
```

LiquidityCell 只通过 `CellInputBundle` 消费正式 `order_book_snapshot.v1`，不从 `AnalysisRequest.context` 读取私有盘口字段。Registry 注册该能力，但默认 `market.default_analysis` 图不包含它；调用方只有显式选择 `liquidity_analysis_graph()` 并提供订单簿快照时才会执行。缺少订单簿会在 planning 阶段失败，而不是在 Cell 内静默降级。

### 4.2 公式规则

1. 以最佳买卖价中点为基准，只统计上下各 `100bps` 内的档位。
2. 每档深度使用 `price × quantity` 得到 quote notional；双侧失衡为 `(bid_depth - ask_depth) / (bid_depth + ask_depth)`。
3. 每侧至少需要 3 个近端有效档位；少于 3 档时状态为 `insufficient_depth`，方向保持 neutral。
4. 深度失衡达到 `±0.18` 才形成候选方向；正值为 bid-heavy，负值为 ask-heavy。
5. 点差 `≤5bps` 为 tight，`≤15bps` 为 normal，`15–30bps` 为 elevated，`≥30bps` 为 fragile。fragile 点差优先触发 `conflict`，不让名义深度失衡产生强方向。
6. 任一侧最大档位占该侧近端深度 `≥0.72` 时触发 `concentrated_depth`。孤立挂单墙只说明集中风险，不确认支撑、方向或操纵。
7. 显式 `quality_flags`、负 event/fetch 延迟或超过 `1000ms` 的抓取延迟触发 `degraded_input`，方向降级为 neutral。
8. freshness 只由 `event_time_ms` 与 `fetched_at_ms` 的确定性差值计算，不读取当前墙钟时间，保证历史回放稳定。
9. 流动性脆弱性只映射到 `volatility_risk`；`manipulation_risk` 固定为 0。单一快照不能证明 spoofing、layering 或市场操纵。
10. 单快照 confidence 最高为 88，不能把瞬时盘口表述为长期流动性结论。

主要状态：

```text
insufficient_depth
degraded_input
fragile_wide_spread
concentrated_depth
bid_heavy
ask_heavy
balanced
```

### 4.3 固定验证样例

| case_id | 类型 | 预期 |
|---|---|---|
| `tight_balanced_book_stays_neutral` | 边界 | 紧点差、双侧均衡，neutral |
| `distributed_bid_depth_is_bullish` | 正常方向 | 分布式买方深度占优，bullish |
| `distributed_ask_depth_is_bearish` | 正常方向 | 分布式卖方深度占优，bearish |
| `wide_spread_blocks_bid_imbalance` | 误判防护 | 宽点差覆盖买方失衡，conflict |
| `dominant_single_bid_wall_is_not_direction` | 误判防护 | 单墙集中不确认为方向，conflict |
| `insufficient_near_depth_stays_neutral` | 边界 | 双侧近端档位不足，neutral |
| `quality_flag_degrades_direction` | 误判防护 | sequence gap 降级为 neutral |
| `far_bid_wall_outside_window_is_ignored` | 误判防护 | 100bps 外远端大墙不影响近端方向 |
| `delayed_fetch_degrades_direction` | 边界 | event/fetch 延迟过高，neutral |

### 4.4 已知误判和限制

- 订单簿挂单可以在成交前撤销；单快照不能识别 spoofing、layering 或真实成交意图。
- quote notional 只在同一标的、同一 venue 的近端双侧做相对比较，不能直接用于跨资产绝对流动性排名。
- 当前 v1 每种 input kind 只允许一份快照，因此尚未做多 venue 聚合、时间序列持续性和撤单/成交事件确认。
- 没有历史标签、冲击成本回测和成交后滑点评估，因此状态保持 `experimental`。

## 5. VolumePriceAnomalyCell 与 ManipulationRiskCell

### 5.1 身份、依赖和职责拆分

```text
cell_id          risk.volume_price_anomaly
formula_version  robust_volume_price_anomaly_v0.2
status           experimental
validation_data  validation/cells/volume_price_anomaly_v0.2.json

consumer         risk.manipulation
consumer_formula shape_anomaly_manipulation_risk_v0.3
default_graph    market.default_analysis@0.4.0
```

`VolumeCell@volume_direction_confirmation_v0.2` 只判断量能是否支持价格方向，`manipulation_risk` 固定为 0。VolumePriceAnomalyCell 独立识别统计异常；ManipulationRiskCell 是 aggregator，必须消费同一 target、同一 horizon、精确公式版本的一份异常结果，再组合最新 K 线的大振幅和长影线。根决策继续直接消费 VolumeCell 和 ManipulationRiskCell，但不直接消费内部异常叶子，因此不会重复计分。

### 5.2 稳健量价公式

1. 最新一根 K 线只用于检测，不进入基线；至少需要 8 根历史 K 线，最多使用最近 48 根。
2. 成交量基线使用历史中位数。相对 MAD 为 `median(abs(volume / median_volume - 1))`，robust scale 为 `1.4826 × max(relative_MAD, 0.10)`。
3. 最新成交量同时满足 `volume_ratio ≥ 2.0` 和 `volume_robust_z ≥ 3.5` 才算异常，避免低方差市场中的微小噪声被放大。
4. 价格基线使用历史相邻收盘绝对收益率的中位数与 MAD；scale floor 为 `0.15` 个百分点。最新绝对收益同时达到 `1.5%` 和 robust z-score `3.5` 才算价格异常。
5. 高量且价格近乎不动记为 `volume_absorption`；高量但价格未达到同步异常标准记为 `volume_price_divergence`。
6. 价格异常但成交量未同步记为 `price_dislocation_up/down`；量价同时异常记为 `synchronized_expansion_up/down`。
7. 所有异常状态输出 `conflict`，因为该 Cell 标记的是风险而不是趋势方向。同步放量上涨也可能是新闻或真实突破，不能直接输出 bullish。
8. 历史成交量中位数不为正时状态为 `invalid_volume_baseline`；正成交量覆盖率低于 `0.80` 时状态为 `degraded_volume_baseline`。两者都失败关闭，不生成方向或异常风险。
9. 异常风险映射采用保守分层：同步扩张的 manipulation multiplier 为 `0.35`，无量价格脱离为 `0.45`，量价背离为 `0.55`，吸收为 `0.65`；价格异常状态同时提高 `volatility_risk`。
10. ManipulationRiskCell 对已经包含价格异常的子结果将振幅分量权重降为 `0.5`，减少同一价格位移被重复累计；长影线仍作为独立形态证据。
11. `manipulation_risk` 表示异常模式对市场完整性的风险贡献，不证明违法行为或交易者意图；单窗口 confidence 最高为 88。

主要异常状态：

```text
insufficient_history
invalid_volume_baseline
degraded_volume_baseline
normal
volume_absorption
volume_price_divergence
price_dislocation_up / price_dislocation_down
synchronized_expansion_up / synchronized_expansion_down
```

### 5.3 固定验证样例

| case_id | 类型 | 预期 |
|---|---|---|
| `stable_volume_and_price_are_normal` | 边界 | 量价均在基线内，neutral |
| `volume_absorption_after_spike` | 正常异常 | 异常放量但价格近乎不动，conflict |
| `high_volume_without_extreme_price_move_diverges` | 正常异常 | 高量与非极端价格位移背离，conflict |
| `synchronized_expansion_up` | 误判防护 | 同步放量上涨只标记异常，不确认操纵 |
| `synchronized_expansion_down` | 正常异常 | 同步放量下跌，波动风险升高 |
| `price_dislocation_without_volume_confirmation` | 误判防护 | 无量价格脱离，conflict |
| `single_historical_volume_outlier_does_not_hide_spike` | 误判防护 | 单个历史极值不污染中位数基线 |
| `persistently_high_volume_regime_is_not_a_spike` | 误判防护 | 持续高量相对自身基线保持 normal |
| `insufficient_history_stays_neutral` | 边界 | 基线历史不足，neutral |
| `sparse_positive_volume_baseline_fails_closed` | 误判防护 | 正成交量覆盖不足，失败关闭 |
| `zero_volume_baseline_fails_closed` | 误判防护 | 零成交量中位数失败关闭 |

### 5.4 已知误判和限制

- 新闻、真实突破、开收盘时段切换和市场制度变化都可能产生合法的同步量价扩张。
- 当前只检查最新一根 K 线，不判断异常持续时间，也没有逐笔主动买卖方向、撤单或账户级证据。
- 不同 venue 和合约的成交量口径可能不同；跨市场比较前必须标准化。
- 拆股、复权、合约换月和错误成交仍可能形成价格脱离，生产数据层必须独立提供质量标记。
- 当前没有带标签的市场完整性事件集，因此两个 Cell 都保持 `experimental`。

## 6. FundingOpenInterestCell

### 6.1 身份、输入和图边界

```text
cell_id          crypto.funding_open_interest
formula_version  robust_funding_open_interest_positioning_v0.1
status           experimental
required_inputs  analysis_request + funding_open_interest_snapshot
validation_data  validation/cells/funding_open_interest_v0.1.json
graph            market.derivatives_analysis@0.1.0
```

FundingOpenInterestCell 只通过 `CellInputBundle` 消费正式 `funding_open_interest_snapshot.v1`。默认 `market.default_analysis` 不包含该能力；调用方必须显式选择 `derivatives_analysis_graph()` 并提供同步资金费率、OI quote notional 和 mark price 时间序列。缺少或存在同类型多份快照时，planning 在 Cell 启动前失败。

边界状态模型：

```text
声明并绑定输入
→ 校验 perpetual-future 血缘、单位和时间排序
→ 检查历史长度、cadence、quality flag 和 fetch latency
→ 计算 funding / OI 稳健基线和同步价格变化
→ 分类定位状态
→ 输出方向、杠杆波动风险和证据
```

输入结构错误直接失败；历史不足或来源质量不足属于可解释业务状态，失败关闭为 neutral。Cell 不读取墙钟时间，不自行访问交易所，也不把定位异常单独解释为操纵。

### 6.2 公式规则

1. 最新点只用于检测，不进入历史基线；至少需要 8 个历史点，最多使用最近 48 个。
2. 资金费率输入是每个 funding interval 的小数费率，并按 `rate × 8 / funding_interval_hours × 10,000` 标准化为 8 小时 bps。快照必须统一声明 `settled` 或 `predicted`，不能在同一序列混合；predicted 仍可用于实时拥挤判断，但 confidence 额外降低 5 分，因为它不是已发生费用。
3. 资金费率历史基线使用中位数与 MAD，scale 为 `1.4826 × max(MAD, 0.5bps)`。最新费率相对中位数偏移至少 `2bps` 且 `|robust_z| ≥ 3.5` 才是异常 shift。
4. 最新标准化资金费率绝对值达到 `5bps/8h` 即视为 crowding。持续高费率即使相对自身历史不异常，仍保留拥挤状态，因为绝对持仓成本没有消失。
5. v1 只接受线性永续合约和明确币种的 quote notional。公式先计算 `base_equivalent_exposure = open_interest_notional / mark_price`，历史基线使用相邻历史点绝对 exposure 变化率的中位数与 MAD，scale floor 为 `0.25` 个百分点；最新绝对变化至少 `2.5%` 且 robust z-score `≥3.5` 才算 OI 异常。原始 notional 变化仍进入 metadata 供审计，但不直接驱动状态。
6. mark price 与 funding/OI 保存在同一时间点。异常增仓配合价格上涨/下跌分别形成 leveraged long/short buildup；异常减仓配合价格下跌/上涨分别形成 long liquidation/short covering。
7. 价格变化绝对值低于 `0.5%` 时不确认方向。异常增仓或减仓但价格未同步，只输出 `conflict`。
8. 增仓方向若同时出现同向极端 funding，状态升级为 crowded long/short buildup 并输出 `conflict`；拥挤市场继续趋势与反向挤压风险并存，不能从单窗口给出强方向。
9. cadence coverage 要求至少 `0.80`，每个 gap 允许相对 `sample_interval_ms` 偏离 `25%`。来源 quality flag、负 fetch latency 或超过 `60s` 的 fetch latency 同样触发 `degraded_input`。
10. `volatility_risk` 表示杠杆拥挤和强制去杠杆风险；`manipulation_risk` 固定为 0，metadata 明确 `not_supported_by_positioning_alone`。有效序列使用 `risk_assessment_status=available`；历史或质量守卫触发时为 `unavailable`，避免把无法评估误读为已确认低风险。单窗口 confidence 最高为 88。
11. `DecisionPolicy@decision_weighted_score_v0.5` 为该可选 Cell 显式保存 `0.9` 权重，使 derivatives graph 的根节点审计不依赖未知 Cell 的隐式默认值；默认图不包含该 Cell，因此既有默认分数不受影响。

主要状态：

```text
insufficient_history
degraded_input
normal
positive_funding_crowding / negative_funding_crowding
funding_shift_up / funding_shift_down
leveraged_long_buildup / leveraged_short_buildup
crowded_long_buildup / crowded_short_buildup
long_liquidation / short_covering
open_interest_surge_without_price_confirmation
deleveraging_without_price_confirmation
```

### 6.3 固定验证样例

| case_id | 类型 | 预期 |
|---|---|---|
| `stable_positioning_is_normal` | 边界 | 费率、OI 和价格稳定，neutral |
| `leveraged_long_buildup_is_bullish` | 正常方向 | 价格上涨并异常增仓，bullish |
| `leveraged_short_buildup_is_bearish` | 正常方向 | 价格下跌并异常增仓，bearish |
| `long_liquidation_is_bearish` | 正常方向 | 价格下跌并异常减仓，bearish |
| `short_covering_is_bullish` | 正常方向 | 价格上涨并异常减仓，bullish |
| `crowded_long_buildup_blocks_direction` | 误判防护 | 多头 funding 拥挤阻断直接看多 |
| `crowded_short_buildup_blocks_direction` | 误判防护 | 空头 funding 拥挤阻断直接看空 |
| `oi_surge_without_price_confirmation_is_conflict` | 误判防护 | OI 激增但价格不确认，conflict |
| `price_only_notional_growth_is_not_position_growth` | 误判防护 | 价格机械推高 quote notional 不算真实增仓 |
| `persistent_high_funding_remains_crowded` | 误判防护 | 持续高绝对费率不被历史基线洗成 normal |
| `funding_shift_without_oi_confirmation_is_conflict` | 误判防护 | 费率异常但 OI 不确认，不生成趋势 |
| `negative_funding_moving_toward_zero_is_shift_up` | 误判防护 | shift 方向按相对基线变化，而不是最新费率正负命名 |
| `single_historical_oi_outlier_does_not_hide_latest_surge` | 误判防护 | 单个历史 OI 跳变不污染稳健基线 |
| `insufficient_history_stays_neutral` | 边界 | 历史不足，neutral |
| `quality_flag_fails_closed` | 误判防护 | 来源报告 sequence gap，失败关闭 |
| `irregular_cadence_fails_closed` | 边界 | 采样连续性不足，失败关闭 |
| `delayed_fetch_fails_closed` | 边界 | 抓取延迟超过公式边界，失败关闭 |

### 6.4 已知误判和限制

- OI 上升只说明新增持仓，不能直接识别主动方；方向必须依赖同步 mark price，仍可能受到基差、指数异常或对冲仓位影响。
- 资金费率是拥挤和持仓成本证据，不是独立的价格反转定时器。高正费率可以持续很久，高负费率也不保证立即轧空。
- v1 只分析一个 venue、一种永续合约和一个采样窗口；不能把多个交易所的不同合约面值直接相加。
- base-equivalent exposure 可以剔除线性 quote-notional 中的主要价格重估影响，但它仍不是交易所原生合约数量；合约规格变化、币种换算或 provider 口径漂移必须由数据 adapter 和 quality flag 独立处理。
- inverse perpetual、quanto 合约和未说明 contract multiplier 的原始 contracts 数量不在 v1 支持范围内，不能伪装成 linear quote notional 输入。
- 当前没有清算明细、主动成交方向、账户级仓位或跨 venue 标签，不能证明强平规模、真实多空账户数量或操纵意图。
- 没有带标签的挤压、清算和后续走势评估集，因此状态保持 `experimental`。
