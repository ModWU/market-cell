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
→ 执行多个分析 Cell
→ 聚合成根节点判断
→ 输出结构化 JSON 分析报告
```

## 项目结构

```text
market-cell/
├── contracts/
│   ├── json_schema/            # 跨语言共享 JSON Schema 契约
│   ├── protobuf/               # 实时行情事件契约
│   └── parquet/                # 历史 K 线批量存储契约
├── docs/
│   ├── product_design.md      # 产品设计文档 v0.2
│   ├── system_architecture.md # 系统架构文档 v0.2
│   ├── documentation_architecture.md # 文档体系和闭环关系
│   ├── external_architecture_research.md # 外部成熟系统架构研究
│   ├── backend_design.md      # 后端模块设计
│   ├── backend_architecture.md # 后端服务化架构
│   ├── polyglot_architecture.md # 多语言仓库和契约边界
│   ├── runtime_architecture.md # Rust 热路径和 Python 冷路径
│   ├── cell_protocol.md       # Cell 开发协议
│   ├── data_contract.md       # 输入输出数据契约
│   ├── data_source_strategy.md # K 线和行情数据源策略
│   ├── feature_layer_design.md # K 线基础特征层设计
│   ├── evaluation_strategy.md # 评估和验证策略
│   ├── stability_design.md    # 分析结构、Cell 输出和风险解释稳定性
│   ├── cell_dictionary.md     # Cell 分类字典
│   ├── roadmap.md             # 阶段路线图
│   ├── risk_and_governance.md # 风险治理边界
│   ├── glossary.md            # 核心术语表
│   └── design_review.md       # 设计完善记录
├── packages/
│   └── python/
│       ├── pyproject.toml      # Python 包配置
│       ├── src/market_cell/
│       │   ├── cli.py          # 命令行入口
│       │   ├── data/           # K 线数据源协议、质量检查、缓存和适配器
│       │   ├── engine.py       # 分析执行器
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
- 后期可以接入真实数据、AI、可视化和自动交易模块
