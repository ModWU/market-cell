# MarketCell 后端设计文档 v0.2

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
    Registry["CellRegistry"] --> Planner["CellExecutionPlanner"]
    Catalog["ServiceCapabilityCatalog"] --> Planner
    Planner --> Plan["CellExecutionPlan"]
    Plan --> Engine
    Engine --> Executor["CellExecutor"]
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
| `registry.py` | 注册和列出 Cell |
| `engine.py` | 编排一次分析运行，不持有具体执行实现 |
| `execution/models.py` | 执行计划、binding、trace 和 summary 数据对象 |
| `execution/catalog.py` | 服务能力目录和本地 binding 工厂 |
| `execution/placement.py` | 运行时感知的服务放置策略 |
| `execution/planner.py` | 从 Registry、Catalog 和 Policy 生成执行计划 |
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
    participant P as Planner
    participant X as Executor
    participant C as Cell
    U->>CLI: analyze input.json
    CLI->>V: AnalysisRequest
    V-->>CLI: valid
    CLI->>E: run(request)
    E->>P: build(request, registry, catalog)
    P-->>E: CellExecutionPlan
    E->>X: execute(cell, context)
    X->>C: analyze(request)
    C-->>X: CellResult
    X-->>E: outcome + runtime trace
    E->>X: execute(decision, child_results)
    X-->>E: decision + runtime trace
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

扩展顺序只以 `roadmap.md` 为准。当前后端优先完成：

1. Plan / Graph Validator。
2. plan-driven local coordinator。
3. Cell Graph Definition。
4. Input Reference / Resolver。
5. Runtime Summary Store 和性能基线。

这些边界稳定后再进入更多 Cell、多周期、API 和远程执行。

## 7. 错误处理原则

- 输入错误在 `validation.py` 处理。
- Cell 内部不要吞掉严重错误。
- 可解释的业务异常要进入报告。
- 数据结构错误要直接失败。
- 服务化前就应逐步分类 validation、planning、binding、execution、contract、data_source 和 persistence 错误。
- 失败 AnalysisRun 必须保留已完成 trace、失败 trace 和 summary。

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
