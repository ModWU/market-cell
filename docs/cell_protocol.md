# MarketCell Cell 协议 v0.2

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

所有 Cell 必须实现：

```text
analyze(request, child_results) -> CellResult
```

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
status: experimental
```

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
- 在 `cell_dictionary.md` 记录
- 添加测试
- 添加公式版本
- 输出 evidence

## 9. 重要边界

Cell 不能：

- 直接下单
- 直接修改全局权重
- 直接决定自己部署在哪个服务
- 隐式读取外部文件
- 绕过 AnalysisRequest
- 输出无法解释的黑盒结论

Cell 可以：

- 使用 request 中的数据
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

当前本地测试时，所有 Cell 可以绑定到：

```text
service_id = python-local
runtime = python_local
task_queue = cell.python-local
```

未来多服务集群时，可以一个 Cell 对应多个服务，也可以一个服务承载多个 Cell，但 `CellResult` 输出协议不能因此变化。Cell 也不能读取 task queue、endpoint 或 service health 来自行决定位置。

身份规则：`cell_id` 可以在一个 Graph 中重复使用，`node_id` 才是一次计划内的唯一执行身份。任何依赖、trace 和结果收集都应优先按 node_id 对齐。
