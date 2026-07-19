# MarketCell Cell 字典 v0.3

## 技术结构类

- TrendCell：趋势方向、趋势强度
- SupportResistanceCell（experimental）：使用重复高低点聚类识别支撑压力区，只在最新 K 线明确拒绝已确认价位时给出方向；公式 `support_resistance_cluster_rejection_v0.1`，验证与误判记录见 `cell_validation.md`。
- BreakoutCell（experimental）：消费 SupportResistanceCell 的结构破坏结果，只在首次越界、强收盘和放量同时成立时确认突破；公式 `breakout_structure_volume_confirmation_v0.1`，验证与误判记录见 `cell_validation.md`。
- MomentumCell：动量变化
- VolumeCell（experimental）：只判断最新量能是否支持价格方向，不再输出操纵风险；公式 `volume_direction_confirmation_v0.2`。
- VolatilityCell：波动压力
- MarketRegimeCell：趋势、震荡、剧烈震荡、混合状态识别

## 市场微观结构类

- LiquidityCell（experimental）：消费正式 `order_book_snapshot.v1`，分析中点上下 100bps 内的点差、双侧 quote notional、深度失衡和单侧集中度；宽点差、档位不足、单墙集中或数据质量异常时阻断强方向，公式 `order_book_depth_spread_imbalance_v0.1`，只在显式 `market.liquidity_analysis@0.2.0` 图中执行。

## 操纵风险类

- VolumePriceAnomalyCell（experimental）：使用最多 48 根历史 K 线的成交量中位数、相对 MAD、正成交量覆盖率和绝对收益 MAD，识别吸收、量价背离、同步扩张和无量价格脱离；公式 `robust_volume_price_anomaly_v0.2`，异常只表示风险模式。
- ManipulationRiskCell（experimental）：消费一个 VolumePriceAnomalyCell 结果，再组合长影线和大振幅；公式 `shape_anomaly_manipulation_risk_v0.3`，不证明真实操纵意图。
- PumpDumpCell：拉盘出货风险
- SpoofingLayeringCell：虚假挂单风险
- LayeringCell：多层虚假挂单风险
- MomentumIgnitionCell：动量点火风险
- WashTradingCell：刷量/对倒风险
- LiquidityFragilityCell：基于多快照持续性、撤单和冲击成本的流动性脆弱聚合（未来能力，不等同于当前单快照 LiquidityCell）
- WhaleConcentrationCell：大户集中风险
- SocialHypeMismatchCell：社交热度和资金不匹配

## 宏观类

- DollarLiquidityCell：美元流动性
- InterestRateCell：利率预期
- InflationCell：通胀压力
- RiskAppetiteCell：全球风险偏好

## 资源类

- OilCell：石油价格和供需冲击
- GoldCell：避险资产状态
- NaturalGasCell：能源风险
- CommodityCell：大宗商品状态

## 地缘和新闻类

- WarRiskCell：战争风险
- SanctionCell：制裁风险
- SocialUnrestCell：社会动荡
- TechnologyEventCell：科技重大事件
- NewsEventCell：新闻事件聚合

## 加密市场类

- OnChainFlowCell：链上资金流
- StablecoinFlowCell：稳定币流入流出
- ExchangeBalanceCell：交易所余额
- FundingOpenInterestCell（experimental）：消费正式 `funding_open_interest_snapshot.v1`，显式区分 settled / predicted funding，把不同结算周期的费率标准化到 8 小时口径，并用同步 OI quote notional、mark price 与 base-equivalent exposure 的稳健变化识别杠杆建仓、去杠杆和拥挤风险；公式 `robust_funding_open_interest_positioning_v0.1`，只在显式 `market.derivatives_analysis@0.1.0` 图中执行，单独定位数据不证明操纵。
- ETFInstitutionCell：ETF 和机构资金

## 决策类

- DecisionCell：根节点聚合
- HorizonDecisionCell（experimental）：消费完整 `multi_horizon_analysis.v1`，按 short `<4h`、medium `4h–1w`、long `>=1w` 分层，以较高周期结构权威、方向质量门槛和显式冲突类型生成 `horizon_decision.v1`；公式 `horizon_structure_alignment_v0.1`。它是应用层类型化聚合 Cell，不注册进单周期 Registry/DAG；验证与误判记录见 `validation/cells/horizon_decision_v0.1.json`。
- StrategyModeCell：当前适合短线、波段、观望还是风险规避
