# MarketCell 后端设计文档 v0.9

## 1. 后端目标

MarketCell 后端第一阶段只做分析闭环：

```text
读取输入
校验数据
执行 Cell
聚合结果
输出报告
```

暂时不做：

- Web 页面
- 用户系统
- 自动交易
- 真实数据爬虫
- 多租户部署

## 2. 后端模块边界

```mermaid
flowchart TD
    CLI["CLI"] --> Loader["Input Loader"]
    Loader --> Models["Domain Models"]
    Models --> Validator["Validator"]
    Validator --> Engine["AnalysisEngine"]
    Engine --> Inputs["InputSnapshot / Resolver"]
    Graph["CellGraphDefinition"] --> Planner["CellExecutionPlanner"]
    Registry["CellRegistry"] --> Planner
    Catalog["ServiceCapabilityCatalog"] --> Planner
    Inputs --> Planner
    Planner --> Plan["CellExecutionPlan"]
    Plan --> Engine
    Engine --> Coordinator["CellExecutionCoordinator"]
    Coordinator --> Inputs
    Coordinator --> Executor["CellExecutor"]
    Executor --> Cells["Cell Library"]
    Cells --> Results["CellResult"]
    Results --> Decision["DecisionCell"]
    Decision --> Report["AnalysisReport"]
    Report --> Output["JSON Output"]
```

## 3. 当前模块职责

| 模块 | 职责 |
|---|---|
| `cli.py` | 命令行入口，负责读取文件和输出 JSON |
| `models.py` | 定义核心数据结构 |
| `events.py` | 轻量事件总线，记录分析开始、Cell 完成、报告保存等事件 |
| `runs.py` | 定义 AnalysisRun，记录一次可复盘分析运行 |
| `validation.py` | 校验输入数据 |
| `registry.py` | 注册并按 cell_id 确定性解析一个本地 Cell 实现，不保存拓扑角色 |
| `graph/` | Graph、Organ、默认组合、共享拓扑算法和结构校验 |
| `inputs/` | InputSnapshot、InputReference、解析协议、本地存储和完整性校验 |
| `engine.py` | 编排规划、协调、报告和运行审计，不持有图执行细节 |
| `execution/models.py` | 执行计划、binding、trace 和 summary 数据对象 |
| `execution/catalog.py` | 服务能力目录和本地 binding 工厂 |
| `execution/placement.py` | 运行时感知的服务放置策略 |
| `execution/planner.py` | 从 Graph、Registry、Catalog 和 Policy 生成执行计划 |
| `execution/plan_validation.py` | 校验 DAG、root、binding、input reference、环和可达性并生成稳定拓扑层 |
| `execution/coordinator.py` | 按 ExecutionPlan 执行拓扑、解析并缓存输入、管理 node_id 结果和失败局部状态 |
| `execution/executor.py` | CellExecutor 协议、本地执行和一致性校验 |
| `execution/telemetry.py` | trace 聚合和性能摘要 |
| `scoring.py` | 评分和方向转换 |
| `policies/` | 可替换策略，例如决策权重、风险分层和行动姿态 |
| `reports/` | 报告保存、读取和列表查询 |
| `replay/` | 基于保存的 input snapshot 重新执行分析，并比较结果漂移 |
| `data/` | K 线数据源协议、质量检查、质量监控、质量问题持久化、路由、缓存和可选 Parquet/DuckDB 存储适配 |
| `features/` | K 线基础特征快照和版本化计算 |
| `cells/` | 具体分析 Cell |
| `contracts/` | 跨语言共享 JSON Schema 契约，位于仓库根目录 |

## 4. 后端核心流程

```mermaid
sequenceDiagram
    participant U as User
    participant CLI as CLI
    participant V as Validator
    participant E as Engine
    participant G as Graph Validator
    participant P as Planner
    participant I as Input Resolver
    participant O as Coordinator
    participant X as Executor
    participant C as Cell
    U->>CLI: analyze input.json
    CLI->>V: AnalysisRequest
    V-->>CLI: valid
    CLI->>E: run(request)
    E->>I: register(InputSnapshot)
    I-->>E: InputReference
    E->>P: build(graph, request, references, registry, catalog)
    P->>G: validate(graph, registry manifests)
    G-->>P: stable topology
    P-->>E: CellExecutionPlan
    E->>O: execute(validated plan)
    O->>I: resolve(reference)
    I-->>O: verified AnalysisRequest snapshot
    O->>X: execute(node, binding, dependencies)
    X->>C: analyze(request)
    C-->>X: CellResult
    X-->>O: outcome + runtime trace
    O->>X: execute(root node, dependency results)
    X-->>O: root result + runtime trace
    O-->>E: PlanExecutionOutcome
    E-->>CLI: AnalysisReport
```

## 5. 第一阶段命令

分析一个输入文件：

```bash
PYTHONPATH=packages/python/src python3 -m market_cell analyze examples/btc_usd_sample.json --pretty
```

查看当前 Cell：

```bash
PYTHONPATH=packages/python/src python3 -m market_cell cells --pretty
```

保存分析报告：

```bash
PYTHONPATH=packages/python/src python3 -m market_cell analyze examples/btc_usd_sample.json --save --pretty
```

列出已保存报告：

```bash
PYTHONPATH=packages/python/src python3 -m market_cell reports --pretty
```

回放报告并比较当前公式结果：

```bash
PYTHONPATH=packages/python/src python3 -m market_cell replay <report_id> --pretty
```

只查看已保存报告：

```bash
PYTHONPATH=packages/python/src python3 -m market_cell replay <report_id> --stored-only --pretty
```

## 6. 后端扩展顺序

扩展顺序只以 `roadmap.md` 为准。当前 Foundation Hardening 与 v0.3 首批 Cell 能力基线已完成，下一步进入 v0.4 MultiHorizonRequest 边界。生产远程 transport、跨进程幂等结果存储和强制 cancellation 保留到服务化阶段。

## 7. 错误处理原则

- 输入错误在 `validation.py` 处理。
- Cell 内部不要吞掉严重错误。
- 可解释的业务异常要进入报告。
- 数据结构错误要直接失败。
- 服务化前就应逐步分类 validation、planning、binding、execution、contract、data_source 和 persistence 错误。
- 失败 AnalysisRun 必须保留 execution_order、completed_node_ids、failed_node_id、已完成 trace、失败 trace 和 summary。
- 输入解析失败必须保留 snapshot audit 和 input resolution records，且任何 Cell 不得绕过 resolver 自行读取计划外 payload。

## 8. 配置原则

第一阶段不引入复杂配置系统。

后期配置来源：

```text
默认配置
项目配置文件
环境变量
命令行参数
```

敏感信息只允许来自环境变量或密钥管理系统。

## 9. 后端设计底线

- Cell 不能直接操作全局状态。
- Cell 不能直接下单。
- Cell 不能绕过标准输出结构。
- Engine 不能写死所有未来逻辑。
- 数据校验不能交给单个 Cell。
- 跨语言模块必须遵守 `contracts/`，不能私自复制一套不兼容模型。
