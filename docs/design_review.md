# MarketCell 设计完善历史记录 v0.2

> 状态：historical。本文保留早期设计判断及其演进背景，不再作为当前实施顺序；当前基线见 `system_architecture.md`，当前优先级见 `roadmap.md`。

## 1. 当前设计判断

MarketCell 的方向是合理的，但它不能只做成“指标集合”。

真正有价值的系统形态应该是：

```text
细胞级分析单元
+ 因子图关系
+ 分析树执行
+ 证据链
+ 风险分层
+ 公式版本
+ 回放审计
```

MarketCell 的核心竞争力不是某一个指标，而是一套能够持续进化的市场分析生命体。

## 2. 需要补强的系统能力

### 2.1 Cell Manifest

每个 Cell 都必须有自己的说明书：

- cell_id
- name
- category
- description
- inputs
- outputs
- formula_version
- risk_dimensions
- status

这样系统后期有几十个甚至几百个 Cell 时，仍然可以管理。

### 2.2 输入数据校验

分析系统最怕脏数据。

任何分析前都必须先检查：

- target 是否为空
- horizon 是否为空
- K 线是否存在
- high / low / open / close 是否合理
- volume 是否为负

交易系统很多错误不是算法错，而是数据错。

### 2.3 证据可信度

Evidence 不应该只是文本说明，还应该包含：

- source
- summary
- weight
- freshness
- reliability

后期新闻、社交媒体、链上数据、交易所数据的可信度不同，必须进入系统。

### 2.4 风险和方向分离

方向和风险不能混成一个分数。

例如：

```text
方向偏多
但操纵风险高
```

这不是矛盾，而是重要状态。

系统输出必须同时保留：

- direction
- strength
- confidence
- volatility_risk
- manipulation_risk
- urgency

### 2.5 公式版本化

每个 Cell 的公式必须有版本。

例如：

```text
trend_close_change_v0.1
price_volume_shape_manipulation_v0.1
```

以后某次分析为什么输出不同，必须能追踪到是不是公式版本变了。

## 3. 长期架构建议

长期系统可以分成五层：

```text
Data Layer       数据采集、清洗、缓存
Feature Layer    特征计算和指标计算
Cell Layer       细胞级分析
Graph Layer      因子图和任务树
Report Layer     输出报告、AI 解释、可视化
```

后期自动交易要作为第六层：

```text
Trading Layer    风控、订单、仓位、交易所接入
```

但 Trading Layer 不能反过来污染 Analysis Layer。

## 4. Cell 生命周期

一个成熟 Cell 应该经历：

```text
draft
experimental
validated
deprecated
```

进入 validated 之前必须满足：

- 有 Manifest
- 有单元测试
- 有公式版本
- 有样例输入输出
- 有误判案例记录

## 5. 因子图和分析树

MarketCell 后期不要只用固定树。

更好的方式：

```text
Factor Graph：保存真实世界影响关系
Analysis Tree：每次分析从图中生成任务树
```

例子：

```text
战争风险
  → 石油价格
  → 通胀预期
  → 利率预期
  → 美元流动性
  → BTC 风险资产表现
```

同一个因子可以影响多个资产，所以底层必须是图。

## 6. 操纵风险系统

操纵风险应该单独形成一个 Cell 族。

第一阶段：

- 异常放量
- 剧烈振幅
- 长影线

第二阶段：

- 多交易所价格偏离
- 盘口虚假挂单
- 合约持仓和资金费率异常
- 流动性突然消失

第三阶段：

- 社交热度和真实资金不匹配
- 大户钱包集中行为
- 拉盘出货模式识别

输出一定要叫“风险”，不要叫“确定操纵”。

## 7. 下一步实现优先级

本节是早期快照，其中 MarketRegimeCell、报告保存、回放和部分数据接入地基已经完成。

随着多服务 Cell 目标明确，当前优先级已经调整为先完成 Plan Validator、plan-driven coordinator、Cell Graph Definition、Input Resolver 和跨运行性能历史，再继续大规模新增 Cell。唯一有效顺序见 `roadmap.md`。

## 8. 当前最重要的克制

不要急着加自动交易。

先把这三件事做稳：

```text
分析结构稳定
Cell 输出稳定
风险解释稳定
```

这三件事稳定后，后面接 AI、界面、自动交易都会顺。

## 9. 数据源选择补充

K 线数据源不能只靠配置顺序决定主备。系统已经开始把选择逻辑抽成独立策略：

```text
SourceProfile
+ ProviderReliabilitySummary
+ ProviderSelectionPreference
→ ProviderSelectionPlan
```

这个策略目前只输出 primary / backups / disabled 建议，不直接修改 `MarketDataRouter`。这样做的好处是：

- 数据源选择可以被测试和复盘。
- 专业数据商、交易所直连、本地回放源可以按不同角色管理。
- API key、实时/历史能力、最近健康下滑这些运行条件不会混进 Cell。
- 后续 Rust 热路径可以产出同类健康信号，而不用改 Python Cell 协议。

`RouterPlanBuilder` 已经完成。后续数据工作以专业数据商 adapter、SLA 和回放审计为主，具体顺序见 `roadmap.md`。
