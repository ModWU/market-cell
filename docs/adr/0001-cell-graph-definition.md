# ADR-0001: Cell Graph Definition 与 Registry 解耦

- 状态：Accepted
- 日期：2026-07-14
- 决策范围：Graph / Organ 核心表示

## 背景

早期本地闭环由 `CellRegistry` 的“叶子列表 + 一个 DecisionCell”隐式定义拓扑。这个结构无法稳定表达多级 aggregator、同一 Cell 多节点、共享子图和多个 Organ，也会让能力注册、组合关系和服务放置相互污染。

MarketCell 需要同时支持本地单服务和未来多服务集群，因此组合图必须能在不同 runtime 和 placement 结果之间复用。

## 决策

引入版本化 `CellGraphDefinition`，并采用以下边界：

```text
CellRegistry         本地 Cell implementation 解析
CellGraphDefinition  node、dependency、root 和 Organ 组合
CellExecutionPlan    本次公式版本、binding 和执行位置
```

Graph 节点只保存 `node_id`、`cell_id`、执行角色、依赖和节点 metadata，不保存 implementation、service、runtime 或 endpoint。

Organ 使用 `organ_id + organ_version + node_ids + output_node_ids` 表达版本化命名子图。Organ 必须对依赖闭包完整；不同 Organ 可以包含同一 node_id，从而共享一次执行结果。Graph 仍只有一个整体 `root_node_id`。

Registry 改为通用 implementation 集合，不再暴露 leaf/root 角色。Planner 先校验 Graph 及其与 Registry 的兼容性，再解析 Manifest、执行 placement，并生成 ExecutionPlan。

公式版本不固定在 Graph 中。它由本次 Registry Manifest 提供，并固化到 ExecutionPlan、AnalysisRun 和 trace；这样公式升级不要求修改组合图，同时历史运行仍可准确复盘。

## 结果

正向结果：

- 默认图、专业市场图和未来多周期图可以独立版本化。
- 多级 aggregator 和同一 Cell 多节点成为正式能力。
- Organ 可以共享节点，不会重复执行共享结果。
- 本地和多服务运行复用同一 Graph 契约。
- Graph Validator 与 Plan Validator 共用稳定拓扑算法。

约束和代价：

- 新增默认 Cell 时必须同时更新 Registry、默认 Graph 和契约测试。
- Graph v1 的 Organ 是依赖闭合子图；外部输入通过 ADR-0002 的显式 Input Reference 进入 ExecutionPlan，不写入 Graph。
- 当前 placement 仍按唯一 Cell capability 选择一次 binding；需要节点级资源差异时再升级 placement 决策契约。

## 放弃的方案

继续使用 Registry 列表定义拓扑：无法表达任意 DAG，并把实现注册与组合关系耦合。

把 service binding 写入 Graph：会导致本地、Python 服务和 Rust 服务需要维护不同图版本。

每个 Organ 单独生成并执行计划：共享 Cell 会重复计算，也无法形成统一 root、trace 和失败审计。
