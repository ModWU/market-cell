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
→ 按 Cell 声明绑定类型化输入并生成 ExecutionPlan v5
→ 按计划执行 Cell DAG
→ 聚合成根节点判断
→ 输出结构化 JSON 分析报告
→ 保存可复盘运行记录、计划执行顺序、trace 和性能摘要
```

v0.3 能力扩展已经形成首批完整基线：`SupportResistanceCell` 与 `BreakoutCell` 组成结构确认链；`VolumePriceAnomalyCell` 使用中位数、MAD 和正成交量覆盖率构建稳健量价基线，再由 `ManipulationRiskCell` 聚合长影线和大振幅；`LiquidityCell` 分析近端盘口；`FundingOpenInterestCell` 使用同步资金费率、持仓名义价值和标记价格序列识别杠杆建仓、去杠杆与拥挤风险。所有新增公式都带版本化验证数据和误判防护。

`LiquidityCell` 是 Registry 中的可发现能力，但不会改变无订单簿的默认分析。需要盘口分析时，调用方显式选择 `liquidity_analysis_graph()`，并通过 `AnalysisEngine.run(..., input_snapshots=[order_book_snapshot])` 提供 `order_book_snapshot.v1`；缺失输入会在 planning 阶段失败。

`FundingOpenInterestCell` 同样不污染默认图。需要衍生品定位分析时，调用方显式选择 `derivatives_analysis_graph()`，并提供 `funding_open_interest_snapshot.v1`。快照把资金费率统一为“每个 funding interval 的小数费率”，并显式区分 settled / predicted；v1 限定线性永续合约与指定币种的 quote notional，同时保存同步 mark price、采样周期和来源血缘。公式先换算 base-equivalent exposure，避免把价格造成的名义 OI 增长误判为增仓；predicted 序列会降低置信度。缺失或同类型多份输入会在 planning 阶段失败。

v0.4 已完成多周期分析闭环：`MultiHorizonRequest` 在同一 target/as-of 下安全执行 2–8 个周期，`HorizonDecisionCell` 再按 short / medium / long 分层、长周期结构权威、有效方向门槛和显式冲突类型输出 `horizon_decision.v1`。总体 direction、structural_direction 和 risk/action posture 相互独立，不使用多数票或直接平均掩盖周期冲突。

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
│   ├── product_design.md      # 产品设计文档 v0.4
│   ├── system_architecture.md # 当前系统架构基线和地基缺口
│   ├── documentation_architecture.md # 文档权威边界和维护规则
│   ├── external_architecture_research.md # 外部成熟系统架构研究
│   ├── backend_design.md      # 后端模块设计
│   ├── backend_architecture.md # 后端服务化架构
│   ├── polyglot_architecture.md # 多语言仓库和契约边界
│   ├── runtime_architecture.md # Rust 热路径和 Python 冷路径
│   ├── cell_protocol.md       # Cell 开发协议
│   ├── cell_validation.md     # Cell 公式、验证样例和误判记录
│   ├── multi_horizon_design.md # 多周期请求、时间对齐和批次执行边界
│   ├── horizon_decision_design.md # 周期分层、结构权威、冲突和风险覆盖
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
│       │   ├── horizons/       # 多周期请求、fan-out、分层决策和冲突策略
│       │   ├── inputs/         # 输入快照、轻量引用、解析器和完整性校验
│       │   ├── features/       # K 线基础特征快照
│       │   ├── models.py       # 核心数据结构
│       │   ├── policies/       # 决策策略和风险分层
│       │   ├── replay/         # 基于 input_snapshot 的回放和漂移比较
│       │   ├── reports/        # 报告保存
│       │   └── cells/          # 第一批分析 Cell
│       └── tests/              # Python 测试
├── examples/
│   ├── btc_usd_sample.json    # 单周期示例输入
│   └── btc_usd_multi_horizon_sample.json # 多周期示例输入
├── validation/
│   └── cells/                 # 新 Cell 的机器可读验证与误判样例
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

运行多周期 fan-out（当前只返回独立周期报告，不做总体决策）：

```bash
PYTHONPATH=packages/python/src python3 -m market_cell analyze-multi examples/btc_usd_multi_horizon_sample.json --pretty
```

在全部 child 成功后执行版本化多周期决策：

```bash
PYTHONPATH=packages/python/src python3 -m market_cell analyze-multi examples/btc_usd_multi_horizon_sample.json --decide --pretty
```

保存每个周期的报告和运行记录以便独立回放：

```bash
PYTHONPATH=packages/python/src python3 -m market_cell analyze-multi examples/btc_usd_multi_horizon_sample.json --save --pretty
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
- 回放会比较完整决策树，并分别报告字段路径、树哈希、公式版本和 Graph 版本漂移；子 Cell 证据或 metadata 漂移不能伪装成稳定结果
- 数据源选择可以根据健康趋势、源等级和业务偏好审计
- 实际数据源路由顺序可以从选择计划显式生成和复盘
- 每次分析运行可以保存数据源选择和路由计划审计信息
- 运行记录遵守 `analysis_run.v2` 契约，完整保存本次使用的全部 InputSnapshot，同时兼容旧 v1 回放
- `multi_horizon_request.v1` 是 AnalysisEngine 之上的应用层包络，不是新的 Cell input kind；每个周期继续拥有独立 InputSnapshot、ExecutionPlan、AnalysisRun 和回放证据
- 多周期请求必须共享 target 和显式 as-of，按有效时长从短到长排列；所有周期在执行前必须通过同一 Graph 内容哈希和公式版本预检
- `multi_horizon_analysis.v1` 始终保持未聚合；只有 `HorizonDecisionCell` 可以把完整结果转换为 `horizon_decision.v1`
- `HorizonDecisionCell` 不进入单周期 Registry/DAG，不新增 InputKind；它按 short `<4h`、medium `4h–1w`、long `>=1w` 分层，并分别保存总体 direction 与 structural_direction
- 多周期冲突必须显式区分层内、短线逆高周期、中线逆长线和短中共同逆长线；高风险只覆盖 action posture，不篡改方向事实
- Cell 组合遵守 `cell_graph_definition.v1`，Registry 只注册实现，Graph 独立定义 leaf、aggregator、root 和 Organ
- Graph 不包含服务位置；`cell_graph_validation.v1` 在 planning 前拒绝非法依赖、Organ 或未注册能力
- Cell 执行计划遵守 `cell_execution_plan.v5` 契约，使用唯一 node_id、primary/fallback binding、`required_input_kinds` 和 payload-free input references 对齐 DAG、服务与输入
- `input_snapshot.v1` 保存可回放逻辑输入，`input_reference.v1` 只携带地址、来源、版本、哈希和大小，计划不复制 K 线 payload
- `cell_input_bundle.v1` 把每个节点声明的输入精确组合后交给 Cell；订单簿使用 `order_book_snapshot.v1`，衍生品定位使用 `funding_open_interest_snapshot.v1`，两者共享 `data_provenance.v1`，都不塞入无类型 context
- 默认图 `market.default_analysis@0.4.0` 将 `risk.volume_price_anomaly` 作为叶子、`risk.manipulation` 作为聚合器，避免 VolumeCell、异常检测和操纵风险重复承担职责
- Registry 可以是 Graph 能力的超集；默认图保持额外市场快照可选，`market.liquidity_analysis@0.2.0` 显式组合 LiquidityCell，`market.derivatives_analysis@0.1.0` 显式组合 FundingOpenInterestCell
- Coordinator 在一次 run 内对同一引用只执行一次实际解析，并用 `input_resolution_record.v1` 审计每个节点的解析状态和缓存命中
- 本地 DAG 由 `PlanDrivenLocalCoordinator` 按稳定拓扑层执行，Registry 只解析实现，不决定运行顺序
- 每次协调遵守 `plan_execution.v1` 契约，保存 execution_order、completed_node_ids 和 failed_node_id
- 服务能力目录遵守 `service_capability_catalog.v2` 契约，一个 Cell 可有多个实现，一个服务也可承载多个 Cell
- 每个 Cell 的实现选择会生成 `cell_placement_decision.v3` 审计记录，并基于优先级、历史失败率和 P95 延迟生成 primary 与健康 fallback 顺序
- `CellExecutor` 将计划与实际执行解耦；当前 `LocalCellExecutor` 会拒绝远程 binding，并校验 CellResult 与运行 trace 的一致性
- `ExecutorRouter` 可按精确 `service_id` 优先、`runtime` 兜底，把同一执行计划派发给不同 executor；它不会隐式降级，并会拒绝与计划上下文不一致的下游 trace
- `FailureControlledExecutor` 统一执行 attempt、幂等键、deadline、retry、backpressure、cancellation 和计划内 fallback，结果写入 `execution_control_record.v1`
- 每个 Cell 节点会生成 `cell_runtime_trace.v1` 运行轨迹，记录服务、状态和耗时
- 每次运行会生成 `cell_runtime_summary.v1` 性能摘要，按 Cell、公式版本、实现、服务和运行时聚合耗时与失败信息
- `runtime_summary_snapshot.v1` 从跨运行 trace 生成明确时间窗口，保留 P50/P95/P99、失败率、重试率和最近状态供 placement 使用
- `performance_baseline.v1` 使用固定输入分别守护结果身份、总运行 P95 和节点 P95，CI 将功能测试与 benchmark 分开执行
- 后期可以接入真实数据、AI、可视化和自动交易模块
