# MarketCell 多语言架构文档 v0.6

## 1. 为什么提前设计多语言边界

MarketCell 后期可能同时包含：

- Python：分析编排、Cell 参考实现、CLI、研究工作流。
- Rust：实时计算、高性能特征、低延迟数据处理。
- TypeScript：未来 Web UI、可视化、API SDK。
- SQL / DuckDB：研究查询、特征回放、历史数据分析。

多语言本身不是目标。目标是让不同语言承担最合适的职责，同时不让领域模型分裂。

## 2. 当前目录判断

当前目录已经采用多语言 workspace 边界：

```text
packages/python/          Python 包，内部采用 src-layout
crates/market_data_core/  Rust 行情领域原语和质量函数
crates/realtime_core/     Rust crate，采用 Cargo workspace 习惯
contracts/                跨语言共享契约
```

这个结构适合即将出现的多语言实现。

原因：

- `packages/python/src/market_cell` 保留 Python src-layout 的打包优势。
- `crates/` 保留 Rust 多 crate workspace 的生态习惯。
- `contracts/` 把跨语言共享模型放在根部，避免每种语言私自发明字段。
- 后续新增 TypeScript、Go 或服务应用时，可以进入 `apps/` 或新的 `packages/*`。

## 3. 新增共享契约层

跨语言边界统一放到：

```text
contracts/
├── json_schema/
│   ├── analysis_request.schema.json
│   ├── analysis_report.schema.json
│   ├── analysis_run.schema.json
│   ├── input_snapshot.schema.json
│   ├── input_snapshot_audit.schema.json
│   ├── input_reference.schema.json
│   ├── input_resolution_record.schema.json
│   ├── feature_snapshot.schema.json
│   ├── cell_graph_definition.schema.json
│   ├── cell_graph_validation.schema.json
│   ├── cell_execution_plan.schema.json
│   ├── cell_service_binding.schema.json
│   ├── service_capability_catalog.schema.json
│   ├── cell_placement_decision.schema.json
│   ├── execution_plan_validation.schema.json
│   ├── plan_execution.schema.json
│   ├── cell_runtime_trace.schema.json
│   ├── cell_runtime_summary.schema.json
│   ├── runtime_summary_snapshot.schema.json
│   ├── runtime_summary_write.schema.json
│   ├── performance_baseline.schema.json
│   └── performance_benchmark_result.schema.json
├── protobuf/
│   └── market_data.proto
├── parquet/
│   └── candle_schema.md
└── test_vectors/
    └── input_identity_v1.json
```

所有语言模块都必须围绕 `contracts/` 对齐输入输出。

原则：

- Python dataclass 是参考实现，不是唯一契约。
- Rust / TypeScript / API 服务不能私自定义不兼容字段。
- 实时行情事件走 Protobuf，历史批量 K 线走 Parquet schema，分析输入输出走 JSON Schema。
- Cell 执行计划走 JSON Schema，后续 Python / Rust / API worker 都不能私自定义不兼容调度字段。
- InputSnapshot、InputReference 和 resolution audit 走 JSON Schema；计划只携带引用，所有语言必须使用相同 canonical JSON hash 和 identity 字段。
- Cell Graph 和 Organ 走 JSON Schema，所有语言共享同一组合关系，但各 runtime 可以选择不同 implementation 和 service binding。
- 服务能力目录和 Cell 放置决策走 JSON Schema，使 Python planner、Rust worker 和未来控制面共享同一能力描述与选择审计。
- Plan execution 走 JSON Schema，使本地 coordinator 和未来集群 scheduler 使用同一节点顺序、完成状态和失败身份审计。
- Cell 运行 trace 走 JSON Schema，后续远程 worker 必须按同一格式上报服务、耗时、错误和重试信息。
- Cell 运行 summary 走 JSON Schema，后续调度器、容量规划和性能回归测试必须基于同一类聚合口径，并保留 implementation 维度避免多实现性能混淆。
- 报告必须带 `schema_version`，避免历史报告无法解释。
- 公式版本和引擎版本必须进入报告或运行记录。

## 4. 目标仓库结构

短中期建议结构：

```text
market-cell/
├── contracts/                  # 跨语言数据契约
│   └── json_schema/
├── packages/
│   └── python/                  # Python 分析内核
│       ├── pyproject.toml
│       ├── src/market_cell/
│       │   ├── cells/
│       │   ├── execution/
│       │   ├── policies/
│       │   ├── reports/
│       │   └── ...
│       └── tests/
├── crates/                      # Rust 性能模块
│   ├── market_data_core/
│   └── realtime_core/
├── examples/                    # 语言无关示例输入
├── docs/                        # 架构和产品文档
├── Makefile                     # 多语言 workspace 的统一命令入口
└── future apps/                 # 后期需要时再引入
```

后期如果出现独立应用，再增加：

```text
apps/
├── api/                         # FastAPI 或其他服务入口
├── web/                         # Web UI
└── worker/                      # 后台任务进程
```

后期如果 Python 包变多，可以拆成：

```text
packages/
├── python/
└── python-connectors/
```

拆分条件是出现独立发布、独立依赖或独立生命周期，不按文件数量机械拆包。

## 5. 各语言职责

| 语言 / 层 | 主要职责 | 不应该承担 |
|---|---|---|
| Python `packages/python` | Cell 协议、编排、报告、研究验证、静态回放 | 低延迟实时计算 |
| Rust `crates/market_data_core` | 行情领域原语、K 线质量函数、热点小函数 | 决策报告文案和产品策略 |
| Rust `crates/realtime_core` | 后续实时 worker、聚合器、数据流状态 | 研究报告和 Cell 策略 |
| TypeScript `apps/web` | 可视化、交互、报告查看 | 重新实现决策逻辑 |
| SQL / DuckDB | 历史查询、特征回放 | 领域决策聚合 |

## 6. 跨语言集成顺序

建议按复杂度递进：

1. JSON 文件和 schema：最简单、最稳定。
2. 子进程调用：Python 调 Rust CLI 或工具程序。
3. HTTP / WebSocket：服务化后用于实时数据或 API。
4. PyO3 / FFI：只有明确性能热点时才使用。
5. 消息队列：只有出现实时任务流时再引入。

不要过早把 Rust 嵌进 Python 内核。先用 Python 保持领域模型可读，再把证明有效的热点下沉。

## 7. 设计模式选择

当前适合使用的模式：

- Strategy：决策策略、权重、风险阈值可替换。
- Registry：统一注册 Cell，不让调用方依赖具体类。
- Ports and Adapters：后期数据源、报告存储、AI 解释都走接口。
- Event Bus：运行事件、观测和未来任务系统解耦。
- Contract-first：跨语言数据先定义契约，再写各语言实现。

当前不建议使用的模式：

- 复杂插件系统：Cell 数量还少，过早插件化会增加负担。
- 微服务拆分：领域模型还在收敛期。
- 复杂依赖注入容器：普通构造函数和协议接口足够。

## 8. 架构底线

- 跨语言共享的是契约，不是直接共享内部对象。
- Python 和 Rust 不能各自发明一套不同评分含义。
- 性能模块不能绕过 AnalysisRequest / AnalysisReport。
- 报告层必须能解释每个结论来自哪个 Cell 和哪个公式版本。
- 自动交易永远作为独立层，不能反向污染分析内核。
