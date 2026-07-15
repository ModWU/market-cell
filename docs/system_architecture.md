# MarketCell 系统架构基线 v0.5

## 1. 文档职责

本文只回答三个问题：

- MarketCell 的稳定系统边界是什么。
- 当前代码已经落到哪一层。
- 地基阶段还有哪些结构性缺口。

详细执行协议见 `cell_execution_fabric.md`，多语言边界见 `polyglot_architecture.md` 和 `runtime_architecture.md`，实施顺序只以 `roadmap.md` 为准。

## 2. 架构目标

MarketCell 不是指标集合，而是可组合、可追踪、可替换执行位置的 Cell 分析系统。

地基必须同时满足：

- 单机本地运行简单可靠。
- 一个 Cell 可以有多个实现和多个服务承载。
- 一个服务可以承载多个 Cell。
- Cell 组合关系与具体执行位置解耦。
- Python、Rust 和未来其他语言共享稳定契约。
- 每次分析、放置、执行、失败和输出都可以复盘。
- 分析系统与自动交易系统长期隔离。

## 3. 不可破坏的系统约束

```text
Cell 是能力，不是服务位置。
Graph 是组合关系，不是执行器实现。
ExecutionPlan 是一次运行计划，不是大数据载体。
Executor 负责真实执行，不能伪造服务归属。
CellResult 是稳定领域输出，不能混入调度细节。
AnalysisRun 是审计记录，AnalysisReport 是用户结果。
Rust 负责动态热点，Python 负责研究、编排和静态分析。
Trading Gateway 只能消费分析结果，不能反向污染 Cell。
```

## 4. 当前系统基线

```mermaid
flowchart TD
    Input["CLI / JSON Input"] --> Validate["Input Validator"]
    Validate --> Engine["AnalysisEngine"]
    Engine --> Snapshot["InputSnapshot"]
    Snapshot --> InputStore["InputSnapshotStore"]
    InputStore --> InputRef["InputReference"]

    Graph["CellGraphDefinition"] --> Planner["CellExecutionPlanner"]
    Registry["Cell Implementation Registry"] --> Planner
    Catalog["ServiceCapabilityCatalog"] --> Planner
    Placement["RuntimeAwarePlacementPolicy"] --> Planner
    InputRef --> Planner
    Planner --> Plan["CellExecutionPlan"]
    Plan --> Engine

    Engine --> Coordinator["CellExecutionCoordinator"]
    Coordinator --> Resolver["InputResolver"]
    Resolver --> InputStore
    Coordinator --> Executor["CellExecutor"]
    Executor --> Local["LocalCellExecutor"]
    Local --> Cells["Python Cell Implementations"]
    Cells --> Results["CellResult"]
    Results --> Decision["DecisionCell / DecisionPolicy"]
    Decision --> Report["AnalysisReport"]

    Executor --> Trace["CellRuntimeTrace"]
    Trace --> Summary["CellRuntimeSummary"]
    Plan --> Run["AnalysisRun"]
    Graph --> Run
    Snapshot --> Run
    Resolver --> Run
    Trace --> Run
    Summary --> Run
    Report --> Store["ReportStore"]
    Run --> Store

    Data["Candle / Event / Context"] --> Engine
    Rust["Rust Market Data / Realtime Core"] -. shared contracts .-> Data
```

当前运行仍是同步单进程，但 planner、coordinator、binding、executor 和 trace 已经分层。这个阶段不引入消息队列或服务发现。

## 5. 分层和依赖方向

| 层 | 当前职责 | 允许依赖 | 不应承担 |
|---|---|---|---|
| Interface | CLI、JSON 输入输出 | Application、Contracts | 分析公式、服务放置 |
| Application | Engine、Planner、Replay、运行编排 | Domain、Execution、Storage ports | 具体指标公式 |
| Domain | Cell、Manifest、Graph、Organ、Result、Evidence、DecisionPolicy | 基础数据模型 | 网络、数据库、任务队列、服务位置 |
| Execution | Catalog、Placement、Plan、Input Resolver ports、Executor、Telemetry | Domain contracts | 用户报告语义、行情采集 |
| Data / Feature | 数据源、质量、缓存、基础特征 | Domain data contracts | Cell 决策聚合 |
| Infrastructure | 文件、Parquet、DuckDB、交易所、Rust 服务 | Ports、共享契约 | 修改领域输出语义 |

依赖方向应尽量由外向内。跨语言协作必须经过 `contracts/`，不能依赖某个 Python dataclass 的偶然结构。

## 6. 稳定对象和动态对象

### 6.1 稳定对象

这些对象应优先版本化并保持向后兼容：

- `AnalysisRequest`
- `CellManifest`
- `CellResult`
- `AnalysisReport`
- `AnalysisRun`
- `CellGraphDefinition`
- `InputSnapshot`
- `InputReference`
- `InputResolutionRecord`
- `FeatureSnapshot`
- `CellServiceBinding`
- `CellExecutionPlan`
- `PlanExecution`
- `CellRuntimeTrace`
- `CellRuntimeSummary`

### 6.2 动态对象

这些对象可以随运行状态变化，但必须留下审计结果：

- 服务能力目录快照
- placement decision
- executor 选择
- 服务健康和容量
- 重试、超时和降级
- 数据源路由

动态策略不能直接改变 CellResult 协议。

## 7. Cell 组合模型

MarketCell 的长期组合关系应分成三层：

```text
CellManifest       描述单个能力
CellGraphDefinition 描述 Cell 之间的依赖和组合
CellExecutionPlan  描述本次运行选择的实现和服务
```

`Organ` 是 Graph 内的版本化命名子图，通过 `organ_id + organ_version + node_ids + output_node_ids` 表达。Organ 必须包含自身依赖闭包；多个 Organ 可以包含同一 node_id，从而共享一次执行结果，而不是重复计算。

当前 `CellRegistry` 已经是纯 implementation 解析表，不再保存 leaf / root 角色。默认组合关系位于 `graph/defaults.py`；自定义 Graph 可以表达 leaf、aggregator、root 多层结构、同一 Cell 多节点和共享 Organ。Planner 只负责把已校验 Graph 解析为 Manifest、placement 和 binding。

## 8. Execution Fabric 当前状态

已经完成：

- `ServiceCapabilityCatalog`：表达一个 Cell 多服务、一个服务多 Cell。
- `RuntimeAwarePlacementPolicy`：按公式兼容、失败率、优先级和 P95 延迟选择 binding。
- `CellPlacementDecision`：记录候选和选择原因。
- `CellExecutor` / `LocalCellExecutor`：把执行从 AnalysisEngine 中拆出。
- `CellGraphDefinition`：版本化保存 node、dependency、root 和命名 Organ，不包含服务位置。
- Graph Validator：检查 root、依赖、环、可达性、Organ 闭包和 Registry 能力兼容性。
- ExecutionPlan v3：node_id 与 cell_id 分离，节点显式引用 binding_id 和 input_reference_ids。
- `InputSnapshot`、`InputReference`、`InputResolutionRecord` 和 `FeatureSnapshot` 版本化契约。
- `LocalInputResolver`：内容寻址、来源/版本身份、payload hash/size 完整性校验和幂等注册。
- Coordinator 运行内按 reference_id 缓存，同一输入最多实际解析和物化一次，同时保留逐节点解析审计。
- implementation、service 和 runtime 由 binding 单点定义，node 不保存重复副本。
- Plan Validator：检查 root、依赖、binding、input reference、环和可达性，并输出稳定拓扑层。
- Graph 与 Plan Validator 共用确定性拓扑算法。
- `PlanDrivenLocalCoordinator`：按拓扑层执行，按 node_id 保存结果，并按节点依赖顺序传递 child_results。
- `plan_execution.v1`：审计执行顺序、完成节点和失败节点。
- plan、trace、CellResult 一致性校验。
- 成功和失败 AnalysisRun 的 trace / summary 审计。
- Registry 的本地 cell_id 唯一解析和重复注册拒绝。

仍未完成：

1. 缺少 Executor Router，当前只有本地 Python executor。
2. Runtime summary 只有单次运行聚合，缺少跨运行、带时间窗口的历史存储。
3. 缺少性能预算和回归阈值，CI 目前只守功能正确性。
4. 当前 planner 把 analysis request reference 分配给所有节点；未来 Graph 输入声明稳定后再收窄到节点所需引用。

这些缺口应先于大规模新增业务 Cell 解决。

## 9. 数据和输入边界

当前 `AnalysisRequest` 仍直接携带 candles、events 和 context，作为本地入口和 `AnalysisRun.input_snapshot` 的完整回放载荷。执行边界已经区分：

```text
Input Snapshot   可复盘的逻辑输入
Input Reference  executor 获取大数据的引用
Feature Snapshot Cell 消费的稳定特征
```

ExecutionPlan v3 只保存引用、键和版本，不复制大体积行情。Input Resolver 负责把引用解析为本地快照，并校验来源、数据版本、内容哈希和 payload 大小；本地 coordinator 在一次 run 内缓存每个 reference 和已物化 AnalysisRequest。默认内存 store 也是 run-scoped，避免长生命周期 Engine 无界保留历史 payload。

`AnalysisRun.input_snapshot` 与 `InputSnapshot` 不是重复职责：前者是当前回放权威载荷，后者定义多服务可寻址和可校验的输入对象。生产级对象存储、Parquet 窗口或 Rust 实时状态只替换 resolver/store adapter，不能改变 ExecutionPlan、Graph 或 CellResult。

## 10. Python 与 Rust 边界

Python 负责：

- Cell 编排和参考实现
- 静态数据分析
- 策略和风险解释
- 历史回放与研究
- 契约参考实现

Rust 负责：

- WebSocket 和实时数据状态
- K 线动态聚合
- 订单簿和高频特征热点
- CPU 密集、低延迟 worker

语言选择由工作负载决定，不按模块名称机械划分。详细规则见 `runtime_architecture.md`。

## 11. 存储和审计边界

```text
AnalysisReport  用户结果
AnalysisRun     一次执行的完整审计
Raw / Candle    原始和标准化行情
Feature         可复用特征快照
Runtime State   服务健康、容量和短期状态
```

这些数据必须分开存储和设置生命周期。报告不能成为运行日志，运行 metadata 也不能成为业务输出字段的垃圾桶。

当前文件存储是参考实现；后续 PostgreSQL、Parquet、DuckDB 或 Redis 只能替换存储适配器，不能改变领域契约。

## 12. 扩展性和性能约束

未来大量 Cell 运行时必须遵守：

- DAG 中无依赖节点可以并行，但结果排序和聚合必须确定性。
- executor 必须声明支持的 runtime、并发和批处理能力。
- 调度必须有超时、重试、背压和熔断边界。
- 同一 run / node 的执行需要幂等标识，避免重试产生重复结果。
- placement 不能只看平均耗时，应使用样本量、失败率和尾延迟。
- 远程执行必须传播 trace_id、run_id、plan_id 和 parent_span_id。
- 任何性能优化都不能绕过公式版本、输入哈希和结果契约。

## 13. 文档导航

| 问题 | 权威文档 |
|---|---|
| 产品目标和边界 | `product_design.md` |
| 当前系统基线 | `system_architecture.md` |
| Cell 开发协议 | `cell_protocol.md` |
| Cell 多服务执行 | `cell_execution_fabric.md` |
| 后端服务化 | `backend_architecture.md` |
| Python / Rust 分工 | `runtime_architecture.md` |
| 多语言仓库和契约 | `polyglot_architecture.md` |
| 数据字段 | `data_contract.md`, `contracts/` |
| 稳定性要求 | `stability_design.md` |
| 实施顺序 | `roadmap.md` |
| 历史设计记录 | `design_review.md` |

## 14. 地基退出标准

进入大规模 Cell 扩展前，至少应满足：

- Graph Validator 和 Plan Validator 能分别拒绝非法组合图与非法执行计划。（已完成）
- Registry 与 Graph 拓扑解耦，多级 aggregator 和共享 Organ 可稳定执行。（已完成）
- 本地执行顺序由 ExecutionPlan 驱动，而不是 Registry 固定循环。（已完成）
- Input Reference / Resolver 边界确定。（已完成）
- Runtime summary 可以跨运行聚合并进入 placement。
- 有最小性能基线和回归阈值。
- 失败运行、重试和降级都有可复盘记录。

具体实施顺序只维护在 `roadmap.md`。
