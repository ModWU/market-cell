# MarketCell

MarketCell 是一个面向交易分析的“市场细胞级因子分析系统”。

它的目标不是做一个普通技术指标工具，而是把影响市场波动的因素拆成可扩展、可测试、可追踪的 Cell：

- 技术结构 Cell
- 成交量 Cell
- 波动率 Cell
- 新闻事件 Cell
- 操纵风险 Cell
- 宏观和资源 Cell
- 资产决策 Cell

第一阶段只做后台分析系统，不做界面，不做自动交易。

## 当前版本能力

v0.1 提供一个最小闭环：

```text
输入市场样例数据
→ 建立 InputSnapshot 和轻量 InputReference
→ 校验 CellGraphDefinition 并生成 ExecutionPlan v3
→ 按计划执行 Cell DAG
→ 聚合成根节点判断
→ 输出结构化 JSON 分析报告
→ 保存可复盘运行记录、计划执行顺序、trace 和性能摘要
```

## 项目结构

```text
market-cell/
├── contracts/
│   ├── json_schema/            # 跨语言共享 JSON Schema 契约
│   ├── protobuf/               # 实时行情事件契约
│   ├── parquet/                # 历史 K 线批量存储契约
│   └── test_vectors/           # 跨语言哈希和身份算法固定向量
├── docs/
│   ├── adr/                    # 重大架构决策记录
│   ├── product_design.md      # 产品设计文档 v0.2
│   ├── system_architecture.md # 当前系统架构基线和地基缺口
│   ├── documentation_architecture.md # 文档权威边界和维护规则
│   ├── external_architecture_research.md # 外部成熟系统架构研究
│   ├── backend_design.md      # 后端模块设计
│   ├── backend_architecture.md # 后端服务化架构
│   ├── polyglot_architecture.md # 多语言仓库和契约边界
│   ├── runtime_architecture.md # Rust 热路径和 Python 冷路径
│   ├── cell_protocol.md       # Cell 开发协议
│   ├── data_contract.md       # 输入输出数据契约
│   ├── data_source_strategy.md # K 线和行情数据源策略
│   ├── storage_layer_design.md # Parquet/DuckDB 存储适配
│   ├── source_quality_monitoring.md # 数据源质量监控
│   ├── provider_selection_policy.md # 主源/备源选择策略
│   ├── feature_layer_design.md # K 线基础特征层设计
│   ├── evaluation_strategy.md # 评估和验证策略
│   ├── stability_design.md    # 分析、执行、审计和性能稳定性
│   ├── cell_dictionary.md     # Cell 分类字典
│   ├── roadmap.md             # 唯一实施顺序和地基退出标准
│   ├── risk_and_governance.md # 风险治理边界
│   ├── glossary.md            # 核心术语表
│   └── design_review.md       # 历史设计快照
├── packages/
│   └── python/
│       ├── pyproject.toml      # Python 包配置
│       ├── src/market_cell/
│       │   ├── cli.py          # 命令行入口
│       │   ├── data/           # K 线数据源协议、质量检查、缓存和适配器
│       │   ├── engine.py       # 分析执行器
│       │   ├── execution/      # 能力目录、放置、计划、协调、执行和运行遥测
│       │   ├── graph/          # Cell 组合图、Organ、默认图和结构校验
│       │   ├── inputs/         # 输入快照、轻量引用、解析器和完整性校验
│       │   ├── features/       # K 线基础特征快照
│       │   ├── models.py       # 核心数据结构
│       │   ├── policies/       # 决策策略和风险分层
│       │   ├── replay/         # 基于 input_snapshot 的回放和漂移比较
│       │   ├── reports/        # 报告保存
│       │   └── cells/          # 第一批分析 Cell
│       └── tests/              # Python 测试
├── examples/
│   └── btc_usd_sample.json    # 示例输入
└── crates/
    ├── market_data_core/       # Rust 行情领域原语和质量函数
    └── realtime_core/          # Rust 实时模块预留
```

## 运行

```bash
cd /Users/wikiglobal/projects/market-cell
python3 -m venv .venv
source .venv/bin/activate
python3 -m pip install -e packages/python
market-cell analyze examples/btc_usd_sample.json --pretty
```

也可以不用安装，直接运行：

```bash
PYTHONPATH=packages/python/src python3 -m market_cell analyze examples/btc_usd_sample.json --pretty
```

如果要启用 Parquet/DuckDB 本地行情存储扩展：

```bash
python3 -m pip install -e 'packages/python[storage]'
```

查看当前已经注册的 Cell：

```bash
PYTHONPATH=packages/python/src python3 -m market_cell cells --pretty
```

保存分析报告，供后续回放：

```bash
PYTHONPATH=packages/python/src python3 -m market_cell analyze examples/btc_usd_sample.json --save --pretty
```

查看已保存报告：

```bash
PYTHONPATH=packages/python/src python3 -m market_cell reports --pretty
```

回放某个报告，并比较当前公式结果是否漂移：

```bash
PYTHONPATH=packages/python/src python3 -m market_cell replay <report_id> --pretty
```

只查看已保存报告：

```bash
PYTHONPATH=packages/python/src python3 -m market_cell replay <report_id> --stored-only --pretty
```

## 测试

```bash
make test
```

GitHub Actions 会在 `main` 分支 push 和 pull request 时自动运行同一组测试。

性能基准与功能测试独立运行：

```bash
make benchmark
```

也可以直接运行并保存结构化结果：

```bash
PYTHONPATH=packages/python/src python3 -m market_cell benchmark benchmarks/default_analysis.json --pretty --output benchmark-result.json
```

也可以分别运行：

```bash
PYTHONPATH=packages/python/src python3 -m unittest discover -s packages/python/tests
cargo test
```

## 重要边界

MarketCell 输出的是分析结果和风险解释，不是投资建议，也不会保证预测正确。

系统设计目标是：

- 每个结论都有证据
- 每个 Cell 可以独立测试
- 每次分析可以复盘
- 每套公式可以版本化
- 每次保存的输入快照可以重新执行并比较漂移
- 回放会分别报告结果、公式版本和 Graph 版本漂移
- 数据源选择可以根据健康趋势、源等级和业务偏好审计
- 实际数据源路由顺序可以从选择计划显式生成和复盘
- 每次分析运行可以保存数据源选择和路由计划审计信息
- 运行记录遵守 `analysis_run.v1` 契约，便于后续跨语言和服务化复盘
- Cell 组合遵守 `cell_graph_definition.v1`，Registry 只注册实现，Graph 独立定义 leaf、aggregator、root 和 Organ
- Graph 不包含服务位置；`cell_graph_validation.v1` 在 planning 前拒绝非法依赖、Organ 或未注册能力
- Cell 执行计划遵守 `cell_execution_plan.v3` 契约，使用唯一 node_id、显式 binding_id 和 payload-free input references 对齐 DAG、服务与输入
- `input_snapshot.v1` 保存可回放逻辑输入，`input_reference.v1` 只携带地址、来源、版本、哈希和大小，计划不复制 K 线 payload
- Coordinator 在一次 run 内对同一引用只执行一次实际解析，并用 `input_resolution_record.v1` 审计每个节点的解析状态和缓存命中
- 本地 DAG 由 `PlanDrivenLocalCoordinator` 按稳定拓扑层执行，Registry 只解析实现，不决定运行顺序
- 每次协调遵守 `plan_execution.v1` 契约，保存 execution_order、completed_node_ids 和 failed_node_id
- 服务能力目录遵守 `service_capability_catalog.v2` 契约，一个 Cell 可有多个实现，一个服务也可承载多个 Cell
- 每个 Cell 的实现选择会生成 `cell_placement_decision.v2` 审计记录，并基于优先级、历史失败率和 P95 延迟做稳定放置
- `CellExecutor` 将计划与实际执行解耦；当前 `LocalCellExecutor` 会拒绝远程 binding，并校验 CellResult 与运行 trace 的一致性
- 每个 Cell 节点会生成 `cell_runtime_trace.v1` 运行轨迹，记录服务、状态和耗时
- 每次运行会生成 `cell_runtime_summary.v1` 性能摘要，按 Cell、公式版本、实现、服务和运行时聚合耗时与失败信息
- `runtime_summary_snapshot.v1` 从跨运行 trace 生成明确时间窗口，保留 P50/P95/P99、失败率、重试率和最近状态供 placement 使用
- `performance_baseline.v1` 使用固定输入分别守护结果身份、总运行 P95 和节点 P95，CI 将功能测试与 benchmark 分开执行
- 后期可以接入真实数据、AI、可视化和自动交易模块
