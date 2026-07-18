# MarketCell Cell 协议 v0.5

## 1. Cell 是什么

Cell 是 MarketCell 的最小分析单元。

一个 Cell 只做一类分析，例如：

- 趋势
- 成交量
- 波动率
- 新闻事件
- 操纵风险
- 多周期决策

## 2. 标准接口

所有 Cell 保留请求式公式接口：

```text
analyze(request, child_results) -> CellResult
```

计划执行统一通过类型化入口：

```text
analyze_inputs(input_bundle, child_results) -> CellResult
```

基类默认从 `input_bundle.analysis_request` 转发到 `analyze`，所以只消费 K 线和事件的现有 Cell 无需重复实现。需要订单簿等额外数据的 Cell 必须重写 `analyze_inputs`，并通过声明的 input kind 读取快照；它不能自行访问交易所、文件或数据库。

叶子 Cell 可以忽略 `child_results`。

父 Cell 必须通过 `child_results` 聚合结果。

## 3. Manifest 要求

每个 Cell 必须暴露 Manifest：

```text
cell_id
name
category
description
inputs
required_input_kinds
outputs
formula_version
risk_dimensions
status
```

示例：

```text
cell_id: technical.market_regime
name: MarketRegimeCell
category: technical
formula_version: trend_efficiency_regime_v0.1
required_input_kinds: [analysis_request]
status: experimental
```

`analysis_request` 对所有 Cell 都是必需类型。v1 每种 required input kind 恰好绑定一个快照。例如 LiquidityCell 应声明：

```text
required_input_kinds:
  - analysis_request
  - order_book_snapshot
```

FundingOpenInterestCell 则声明：

```text
required_input_kinds:
  - analysis_request
  - funding_open_interest_snapshot
```

新增 input kind 不是只改一个字符串：必须同步领域对象、InputKind、Resolver 白名单、全部引用该枚举的 JSON Schema、跨语言身份向量、篡改测试和回放测试。

## 4. CellResult 要求

所有 Cell 输出必须包含：

```text
direction
strength
confidence
volatility_risk
manipulation_risk
urgency
score
explanation
evidence
metadata
```

禁止只输出一个分数。

## 5. Evidence 要求

每个非中性结论必须尽量提供 evidence。

Evidence 至少包含：

```text
source
summary
weight
freshness
reliability
```

## 6. 命名规则

Cell ID 使用点分层：

```text
technical.trend
technical.volume
risk.volume_price_anomaly
risk.manipulation
external.news
root.decision
```

Python 类名使用 PascalCase：

```text
TrendCell
ManipulationRiskCell
DecisionCell
```

## 7. 生命周期

```text
draft
experimental
validated
deprecated
```

默认新 Cell 是 `experimental`。

进入 `validated` 前必须有：

- Manifest
- 单元测试
- 样例输入
- 样例输出
- 公式说明
- 误判记录或回测证据

## 8. 新增 Cell Checklist

新增 Cell 时必须完成：

- 在 `cells/` 中实现 Cell
- 在 `cells/__init__.py` 导出
- 在 `registry.py` 注册
- 需要进入默认分析时，在 `graph/defaults.py` 添加节点和依赖
- 在 `cell_dictionary.md` 记录
- 声明 `required_input_kinds`；新增类型时同步领域模型、JSON Schema 和契约向量
- 添加测试
- 添加公式版本
- 输出 evidence

## 9. 重要边界

Cell 不能：

- 直接下单
- 直接修改全局权重
- 直接决定自己部署在哪个服务
- 隐式读取外部文件
- 绕过 CellInputBundle / AnalysisRequest 的统一 scope
- 输出无法解释的黑盒结论

Cell 可以：

- 使用 bundle 中已声明、已校验的数据
- 调用子节点结果
- 输出风险
- 输出不确定性
- 输出冲突状态

本地 Registry 可能让同一 Cell implementation 服务多个 node_id。默认 Cell 必须是无状态、可重入的：

- 不在实例字段中保存某次 run 的中间结果。
- 不依赖调用顺序产生输出。
- 同一输入、公式版本和依赖结果应产生确定性结果。
- 可变状态应进入显式 runtime state、输入或结果，不进入共享 Cell 实例。

确实需要状态的实现必须声明 `resource_hints.stateful = true`，并由未来 actor / worker 生命周期管理；在该能力落地前不能并行共享执行。

## 10. 执行位置和服务绑定

Cell 协议只描述输入、输出、公式版本和解释结构，不描述运行位置。

运行位置由 `CellExecutionPlan` 和 `CellServiceBinding` 决定：

```text
CellManifest          描述能力
CellGraphDefinition   描述 Cell 组合和依赖
CellServiceBinding    描述哪个服务承载该能力
CellExecutionPlan     描述本次分析如何执行 Cell DAG
CellExecutionCoordinator 维护 DAG 顺序和 node_id 结果
CellExecutor          执行已经确定的节点
```

`CellExecutionPlan v5` 会把 Manifest 的 `required_input_kinds` 固化到节点，并只绑定对应的 `input_reference_ids`。Coordinator 解析引用后创建 `cell_input_bundle.v1`；Executor 会校验 bundle、节点和当前 implementation 的输入声明一致。计划外输入不能传给 Cell，缺失输入也不能等到公式内部才发现。

当前本地测试时，所有 Cell 可以绑定到：

```text
service_id = python-local
runtime = python_local
task_queue = cell.python-local
```

未来多服务集群时，可以一个 Cell 对应多个服务，也可以一个服务承载多个 Cell，但 `CellResult` 输出协议不能因此变化。Cell 也不能读取 task queue、endpoint 或 service health 来自行决定位置。

身份规则：`cell_id` 可以在一个 Graph 中重复使用，`node_id` 才是一次计划内的唯一执行身份。任何依赖、trace 和结果收集都应优先按 node_id 对齐。

Registry 只注册 implementation。leaf、aggregator、root 和 Organ 归属只能出现在 Graph Definition 中，不能重新塞回 Registry。
