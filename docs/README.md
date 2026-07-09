# MarketCell 文档索引

## 推荐阅读顺序

1. `documentation_architecture.md`：先看文档体系和闭环关系。
2. `external_architecture_research.md`：理解成熟系统有什么值得吸收。
3. `product_design.md`：理解产品到底要做什么。
4. `system_architecture.md`：理解整体系统如何分层、如何扩展。
5. `backend_design.md`：理解后端模块、边界和第一阶段实现方式。
6. `backend_architecture.md`：理解后端未来服务化、数据流和部署演进。
7. `polyglot_architecture.md`：理解多语言目录、共享契约和语言职责边界。
8. `cell_protocol.md`：以后新增 Cell 必须遵守的协议。
9. `data_contract.md`：输入输出数据结构和校验规则。
10. `data_source_strategy.md`：理解 K 线和行情数据源如何分层、降级和缓存。
11. `feature_layer_design.md`：理解 K 线基础特征如何统一计算和版本化。
12. `evaluation_strategy.md`：理解如何判断 Cell 和分析报告是否可靠。
13. `stability_design.md`：理解分析结构、Cell 输出和风险解释如何保持稳定。
14. `risk_and_governance.md`：风险边界、自动交易隔离和合规原则。
15. `roadmap.md`：阶段路线。
16. `cell_dictionary.md`：Cell 分类字典。
17. `glossary.md`：统一术语。
18. `design_review.md`：设计完善记录。

## 文档层次

```text
L0 文档入口：README.md
L1 产品层：product_design.md
L2 架构层：system_architecture.md
L3 后端工程层：backend_design.md / backend_architecture.md
L4 协议契约层：cell_protocol.md / data_contract.md / data_source_strategy.md / feature_layer_design.md / polyglot_architecture.md / contracts/
L5 验证治理层：evaluation_strategy.md / stability_design.md / risk_and_governance.md
L6 研究规划字典层：external_architecture_research.md / roadmap.md / cell_dictionary.md / glossary.md
L7 历史记录层：design_review.md
```

## 文档闭环

```text
产品目标
→ 系统架构
→ 后端设计
→ 协议和数据契约
→ 代码实现
→ 测试和验证
→ 评估和复盘
→ 路线图调整
→ 产品目标
```

## 当前文档状态

| 文档 | 作用 | 状态 |
|---|---|---|
| `documentation_architecture.md` | 文档层级和闭环关系 | v0.1 |
| `external_architecture_research.md` | 外部成熟系统架构研究 | v0.1 |
| `product_design.md` | 产品定位、用户、场景、路线 | v0.2 |
| `system_architecture.md` | 总体架构、分层、图、数据流 | v0.2 |
| `backend_design.md` | 后端模块设计和接口边界 | v0.1 |
| `backend_architecture.md` | 后端服务化架构和演进路线 | v0.1 |
| `polyglot_architecture.md` | 多语言仓库结构和共享契约边界 | v0.1 |
| `cell_protocol.md` | Cell 开发协议 | v0.1 |
| `data_contract.md` | 输入输出数据契约 | v0.2 |
| `data_source_strategy.md` | K 线和行情数据源策略 | v0.1 |
| `feature_layer_design.md` | K 线基础特征层设计 | v0.1 |
| `evaluation_strategy.md` | Cell 和报告的验证方法 | v0.1 |
| `stability_design.md` | 分析结构、Cell 输出和风险解释稳定性设计 | v0.1 |
| `cell_dictionary.md` | Cell 分类字典 | v0.1 |
| `roadmap.md` | 版本路线图 | v0.1 |
| `risk_and_governance.md` | 风险治理和交易边界 | v0.1 |
| `glossary.md` | 核心术语表 | v0.1 |
| `design_review.md` | 设计补充记录 | v0.2 |

## 文档原则

- 产品文档回答“为什么做”和“做什么”。
- 架构文档回答“系统怎么长大”。
- 后端文档回答“代码怎么组织和运行”。
- 协议文档回答“新增能力必须遵守什么规则”。
- 风险文档回答“系统不能越过哪些边界”。
- 评估文档回答“如何判断系统是否真的有用”。
