# MarketCell 产品设计文档 v0.4

## 1. 产品一句话

MarketCell 是一个面向交易分析的细胞级因子分析系统。

它把市场看成一个复杂生命体：K 线、成交量、订单簿、链上资金、新闻、战争、石油、美元、利率、科技周期、社会情绪、操纵风险，都是影响市场状态的 Cell。

系统目标不是神秘预测价格，而是持续构建一棵可解释、可验证、可复盘的市场推理树。

## 2. 产品定位

MarketCell 前期是分析系统，不是交易机器人。

第一阶段只回答：

- 当前市场处于什么状态？
- 影响目标资产的主要因子是什么？
- 不同因子的方向、强度、置信度分别是多少？
- 当前是否存在剧烈波动、流动性脆弱、操纵风险？
- 短线、中线、长线分别适合观察、轻仓验证、趋势跟随还是风险规避？
- 每个结论的证据是什么？

后期才接入：

- 可视化界面
- 真实数据源
- AI 解释层
- 自动交易前置模块

## 3. 为什么不是普通量化系统

普通量化工具通常围绕指标和策略：

```text
指标 → 信号 → 买卖
```

MarketCell 的设计是：

```text
世界事件 → 因子 Cell → 证据链 → 分层聚合 → 风险判断 → 多周期分析结论
```

普通系统容易输出：

```text
MACD 金叉，建议买入。
```

MarketCell 需要输出：

```text
BTC/USD 1h 周期偏多，但操纵风险和波动风险正在上升。

主要证据：
1. TrendCell 显示短周期趋势上行
2. SupportResistanceCell 显示价格在重复支撑区获得承接
3. VolumeCell 显示量能支持方向，VolumePriceAnomalyCell 单独标记异常量价关系
4. MarketRegimeCell 识别为 trend_up
5. ManipulationRiskCell 检测到长影线和量价异常
6. NewsEventCell 显示机构消息偏正面

结论：
短线可以观察顺势机会，但不适合重仓追涨。
```

## 4. 产品愿景

MarketCell 最终要成为一套市场智能操作系统。

它不是单一策略，也不是单一指标库，而是一个可以不断扩展的分析生命体：

```text
Cell      单个分析细胞
Tissue    同类 Cell 组成的分析组织
Organ     一个完整市场子系统
Body      全球市场综合分析系统
Nervous   事件总线和任务调度
Memory    历史数据、特征、报告和回放
Immune    操纵风险、异常风险、数据异常检测
```

这个生命体的价值在于：

- 能成长
- 能复盘
- 能解释
- 能替换算法
- 能验证历史判断
- 能为未来自动交易提供稳定分析底座

## 5. 核心用户

### 5.1 第一阶段用户

- 系统设计者
- 策略研究者
- 量化初学者
- 想建立自己交易分析框架的人
- 想用 AI 辅助分析但不想依赖黑盒的人

### 5.2 后期用户

- 半自动交易者
- 自动交易系统开发者
- 多市场监控系统使用者
- 需要风险监控和复盘的人

## 6. 核心使用场景

### 6.1 单资产分析

输入：

```text
BTC/USD
1h
最近 K 线
新闻事件
市场上下文
```

输出：

```text
方向：bullish / bearish / neutral / conflict
强度：0-100
置信度：0-100
波动风险：0-100
操纵风险：0-100
市场状态：trend_up / trend_down / range / volatile_range / mixed
解释：结构化证据
```

### 6.2 多周期分析

`MultiHorizonRequest v1` 已经完成同 target/as-of、短到长时间对齐和独立子运行边界；`HorizonDecisionCell` 再以版本化结构权威和冲突规则形成产品判断。未聚合事实仍保留在 MultiHorizonAnalysis，不能被覆盖。

同一个资产同时分析：

```text
15m
1h
4h
1d
```

目标是判断：

- 短线是否适合来回做
- 中线是否有趋势
- 长线是否处于风险区
- 多周期结论是否冲突

### 6.3 操纵风险分析

分析某个币种是否存在异常风险：

- 异常放量
- 长影线
- 价格剧烈拉升后回落
- 多交易所价格偏离
- 合约持仓异常
- 资金费率异常
- 社交热度和真实流动性不匹配

输出必须是风险判断，不是司法意义上的断言。

### 6.4 世界因素分析

把外部世界事件纳入分析：

- 战争
- 石油
- 美元
- 利率
- 通胀
- 科技政策
- 社会动荡
- 监管政策

这些事件先进入对应 Cell，再通过因子图影响目标资产。

## 7. 核心产品能力

### 7.1 Cell 化分析

每个 Cell 是一个独立分析单元。

它必须具备：

- 明确职责
- 明确输入
- 明确输出
- 明确公式版本
- 明确证据
- 独立测试

### 7.2 证据链

系统的每个结论都必须有 evidence。

Evidence 当前包含：

- source
- summary
- weight
- freshness
- reliability

后期会扩展：

- url
- timestamp
- raw_value
- normalized_value
- provider
- confidence_reason

### 7.3 风险和方向分离

MarketCell 必须允许这种结论存在：

```text
方向偏多
但风险很高
```

所以方向和风险不能合并成单一分数。

核心输出必须同时包含：

- direction
- strength
- confidence
- volatility_risk
- manipulation_risk
- urgency

### 7.4 多周期判断

单一周期很容易误判。

多周期请求与决策已经支持以下名义时长分层：

```text
短线：15m / 1h
中线：4h / 1d
长线：1w / 1M
```

多周期之间要输出冲突关系。

当前正式输出同时包含：

```text
direction              总体多周期方向
structural_direction   最高有效层级结构方向
alignment_status       aligned / partial / conflicted / indeterminate
conflict_type          层内或层间冲突类型
band_decisions         short / medium / long 分层证据
risk + action_posture  风险上位约束
```

短线逆长线时不能只返回长线方向，也不能把正负分数平均成 neutral；总体 direction 应为 conflict，同时保留 structural_direction。

### 7.5 回放和复盘

每次分析都应该可保存、可回放。

系统后期必须能回答：

- 当时为什么判断偏多？
- 哪些 Cell 起了关键作用？
- 后来真实行情是否验证了判断？
- 哪些公式应该调整？

## 8. 当前 MVP

v0.1 / v0.2 阶段只做后台命令行。

输入：

```text
JSON 文件
```

输出：

```text
结构化 JSON 报告
```

当前已经包含的 Cell：

- TrendCell
- SupportResistanceCell
- BreakoutCell
- VolumeCell
- VolumePriceAnomalyCell
- VolatilityCell
- MarketRegimeCell
- NewsEventCell
- ManipulationRiskCell
- LiquidityCell（显式订单簿图）
- DecisionCell

当前不做：

- 页面
- 自动交易
- 生产级实时交易所采集
- 新闻爬虫
- 真实链上数据
- AI 自动决策

## 9. 产品边界

MarketCell 输出的是分析，不是投资建议。

禁止把系统设计成：

```text
一定上涨
一定下跌
保证收益
确定有人操纵
```

推荐输出：

```text
偏多，但风险偏高
方向不明，等待确认
操纵风险上升，降低仓位
多周期冲突，不适合重仓
```

## 10. 产品阶段门槛

具体实施顺序只维护在 `roadmap.md`。本文只保留产品层门槛：

- 地基阶段：分析、执行、失败和契约可以稳定复盘。
- 能力扩展阶段：新 Cell 有验证数据、公式版本和误判记录。
- 多周期阶段：冲突可以结构化表达，不靠自然语言猜测。
- 数据接入阶段：主源、备源、质量和来源审计形成闭环。
- AI 阶段：AI 只解释结构化结果，不替代规则决策事实。
- 交易前置阶段：Trading Gateway 与分析系统物理和职责隔离。

任何阶段都不能以功能数量替代稳定性门槛。

## 11. 成功标准

第一阶段成功标准：

- 能稳定读取输入
- 能执行多个 Cell
- 能输出完整 JSON 报告
- 每个结论都有证据
- 每个 Cell 都可独立测试
- 文档能解释系统为什么这样设计

中期成功标准：

- 支持多周期
- 支持真实行情
- 支持报告保存和回放
- 支持操纵风险细分
- 支持 AI 解释

长期成功标准：

- 系统能稳定扩展到几十个 Cell
- 能复盘历史分析质量
- 能分辨趋势、震荡、极端波动和异常操纵风险
- 能作为自动交易系统的分析底座
