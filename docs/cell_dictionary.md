# MarketCell Cell 字典 v0.1

## 技术结构类

- TrendCell：趋势方向、趋势强度
- SupportResistanceCell：支撑压力
- MomentumCell：动量变化
- VolumeCell：成交量变化
- VolatilityCell：波动压力
- MarketRegimeCell：趋势、震荡、剧烈震荡、混合状态识别

## 操纵风险类

- ManipulationRiskCell：操纵风险聚合
- VolumePriceAnomalyCell：量价异常
- PumpDumpCell：拉盘出货风险
- SpoofingLayeringCell：虚假挂单风险
- LayeringCell：多层虚假挂单风险
- MomentumIgnitionCell：动量点火风险
- WashTradingCell：刷量/对倒风险
- LiquidityFragilityCell：流动性脆弱
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
- FundingOpenInterestCell：资金费率和持仓
- ETFInstitutionCell：ETF 和机构资金

## 决策类

- DecisionCell：根节点聚合
- HorizonDecisionCell：多周期判断
- StrategyModeCell：当前适合短线、波段、观望还是风险规避
