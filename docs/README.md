# MarketCell 文档索引

## 快速阅读

第一次了解项目：

1. `product_design.md`：产品定位和边界。
2. `system_architecture.md`：当前系统基线和地基缺口。
3. `roadmap.md`：唯一实施顺序。
4. `cell_protocol.md`：Cell 开发协议。
5. `cell_execution_fabric.md`：本地到多服务执行架构。
6. `data_contract.md`：核心数据契约。

准备参与地基开发：

1. `documentation_architecture.md`
2. `system_architecture.md`
3. `backend_design.md`
4. `cell_execution_fabric.md`
5. `runtime_architecture.md`
6. `polyglot_architecture.md`
7. `stability_design.md`
8. `roadmap.md`

## 权威文档

| 主题 | 文档 | 状态 |
|---|---|---|
| 文档治理 | `documentation_architecture.md` | baseline v0.2 |
| 产品定位 | `product_design.md` | baseline v0.2 |
| 系统基线 | `system_architecture.md` | baseline v0.3 |
| 实施顺序 | `roadmap.md` | baseline v0.2 |
| 后端模块 | `backend_design.md` | baseline |
| 服务化演进 | `backend_architecture.md` | baseline |
| Cell 协议 | `cell_protocol.md` | baseline |
| Cell 执行织网 | `cell_execution_fabric.md` | baseline |
| 数据契约 | `data_contract.md`, `../contracts/` | baseline |
| Python / Rust 运行时 | `runtime_architecture.md` | baseline |
| 多语言仓库 | `polyglot_architecture.md` | baseline |
| 稳定性 | `stability_design.md` | baseline |
| 评估方法 | `evaluation_strategy.md` | baseline |
| 风险治理 | `risk_and_governance.md` | baseline |

路线和版本只维护在 `roadmap.md`，其他文档不得复制独立版本计划。

## 数据专项

- `data_source_strategy.md`：专业数据商、交易所直连和本地回放分层。
- `provider_selection_policy.md`：主源、备源和禁用源选择。
- `source_quality_monitoring.md`：缺口、陈旧、异常和跨源偏差。
- `storage_layer_design.md`：Parquet / DuckDB 存储边界。
- `feature_layer_design.md`：基础特征计算和版本化。

## 研究和参考

- `external_architecture_research.md`：成熟系统研究输入。
- `cell_dictionary.md`：Cell 能力字典。
- `glossary.md`：统一术语。
- `design_review.md`：历史设计快照，不作为当前实施顺序。

## 未来专项

达到对应阶段时再创建：

- `factor_graph_design.md`
- `multi_horizon_design.md`
- `ai_explainer_design.md`
- `trading_gateway_design.md`
- `adr/`

## 维护规则

- 公共字段变化必须同步 schema、模型、文档和契约测试。
- 执行架构变化必须同步 Execution Fabric、Runtime 和稳定性测试。
- 新 Cell 必须同步 Cell 字典、公式版本、验证样例和误判记录。
- 重大技术取舍使用 ADR，历史评审不覆盖当前基线。
