# MarketCell 术语表 v0.5

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

一个有名称、有版本的 Cell 子图，表达某个完整市场子系统。

例如：

```text
Crypto Organ = 链上资金 + 合约数据 + 交易所数据 + 技术结构
```

Organ 在 `CellGraphDefinition` 中通过 `organ_id + organ_version + node_ids + output_node_ids` 表达。不同 Organ 可以共享同一 node_id；它是组合概念，不引入新的 Cell 输出或执行协议。

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

## CellGraphDefinition

版本化的 Cell 组合定义。

它描述节点、依赖、聚合关系、root 和命名 Organ，但不描述具体服务位置。当前契约版本为 `cell_graph_definition.v1`。

## ServiceCapabilityCatalog

服务能力目录。

它描述当前有哪些 Cell implementation 以及由哪些逻辑服务承载，允许一个 Cell 多服务和一个服务多 Cell。

## CellServiceBinding

Cell implementation 与逻辑服务之间的绑定。

它包含 implementation、service、runtime、language、task queue 和资源提示，不改变 CellResult。

## CellPlacementDecision

planner 为某个 Cell 选择 implementation 和 service 的审计记录。

它保留候选、历史状态和选择原因。

## CellExecutionPlan

一次分析运行的可执行 DAG 和已选择 binding。

它只保存节点、依赖、输入键和服务绑定，不保存大体积市场数据。

v3 中 `node_id` 是执行身份，`cell_id` 是可重复使用的能力身份，节点通过 `binding_id` 指向具体服务绑定，并通过 `input_reference_ids` 指向输入。

## CellExecutionCoordinator

消费已校验 ExecutionPlan 并维护 DAG 语义的协调接口。

Coordinator 决定何时执行节点、如何读取依赖结果、如何按 node_id 保存局部状态以及失败后停止在哪里；它不实现 Cell 公式。

## CellExecutor

执行已计划 Cell 节点的运行时接口。

Executor 必须上报实际服务位置和运行 trace，不能把计划位置当成真实执行结果。

## PlanExecution

一次已校验计划的协调审计，记录 coordinator、execution_order、completed_node_ids、failed_node_id 和最终状态。

## CellRuntimeTrace

单个 Cell 节点的一次实际执行记录，包含服务、状态、耗时、错误和追踪标识。

## CellRuntimeSummary

按 Cell、公式、实现、服务和 runtime 聚合的性能摘要，用于回归、容量和 placement。

## AnalysisRun

一次分析执行的审计记录。

它保存输入快照、公式版本、执行计划、数据源路由、trace、summary 和成功或失败状态。

## Input Reference

指向行情窗口、特征快照或共享存储对象的稳定引用。

ExecutionPlan v3 使用引用而不是复制整段历史数据。引用携带来源、数据版本、内容哈希和 payload 大小，URI 只负责定位。

## Input Snapshot

包含完整逻辑载荷的不可变输入对象。AnalysisRun 保存完整回放输入，InputSnapshot 同时提供可寻址身份和 payload-free audit。

## Input Resolver

根据 InputReference 读取并校验 InputSnapshot 的端口。当前本地实现使用内存存储，并在每次 run 内由 Coordinator 缓存解析结果。

## Input Resolution Record

某个节点使用某个输入引用的解析审计，记录成功或失败、cache hit、来源、版本和哈希。

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
