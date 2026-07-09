# MarketCell 术语表 v0.1

## Cell

最小分析单元。

一个 Cell 负责一个明确维度，例如趋势、成交量、新闻、操纵风险。

## Tissue

同类 Cell 组成的分析组织。

例如：

```text
Technical Tissue = TrendCell + VolumeCell + VolatilityCell
```

## Organ

一个完整市场子系统。

例如：

```text
Crypto Organ = 链上资金 + 合约数据 + 交易所数据 + 技术结构
```

## Body

全局市场分析系统。

它聚合宏观、资源、地缘、加密、技术、新闻等多个系统。

## Factor

影响市场的因素。

例如：

- 美元流动性
- 石油价格
- 战争风险
- ETF 资金流
- 成交量异常

## Factor Graph

保存因子之间影响关系的图结构。

它表达真实世界中“谁影响谁”。

## Analysis Tree

一次分析任务临时生成的执行树。

它表达“这次分析要调用哪些 Cell，以及如何聚合结果”。

## AnalysisRequest

一次分析任务的输入。

当前包括：

- target
- horizon
- candles
- events
- context

## CellResult

单个 Cell 的标准输出。

它必须包含方向、强度、置信度、风险、证据和解释。

## Evidence

支持某个 CellResult 的证据。

Evidence 不是装饰字段，而是可解释系统的核心。

## Direction

方向判断。

当前枚举：

```text
bullish
bearish
neutral
conflict
```

## Strength

影响强度。

范围：

```text
0-100
```

## Confidence

置信度。

表示系统对当前 Cell 判断的可信程度。

## Volatility Risk

波动风险。

表示后续发生剧烈波动的风险，不代表方向。

## Manipulation Risk

操纵风险。

表示存在异常交易结构、量价异常、流动性异常等风险。

它不能被表达为“确定有人操纵”。

## Urgency

紧急程度。

用于表达这个风险或信号是否需要马上关注。

## DecisionCell

根节点聚合 Cell。

它聚合多个 CellResult，输出最终结构化分析。

## MarketRegime

市场状态。

当前计划包括：

```text
trend_up
trend_down
range
volatile_range
mixed
unknown
```

## Replay

回放历史分析。

用于回答：

- 当时系统为什么这么判断？
- 后来结果如何？
- 哪个 Cell 贡献了错误判断？

## Shadow Run

影子运行。

系统生成分析，但不参与真实交易决策，只用于观察和验证。

## Trading Gateway

未来自动交易前置系统。

它必须独立于分析系统，不能让 DecisionCell 直接下单。
