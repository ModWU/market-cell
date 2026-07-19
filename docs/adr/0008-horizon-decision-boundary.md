# ADR-0008: 多周期决策的结构权威与冲突边界

- 状态：Accepted
- 日期：2026-07-19
- 决策范围：HorizonDecisionCell、周期分层、结构方向、冲突类型、风险覆盖和稳定身份

## 背景

MultiHorizonAnalysis 已能证明 child report 同 target/as-of、同 Graph、同公式集合并保持稳定顺序，但它故意不输出总体方向。直接多数票、平均 score 或选择最高 confidence 会混淆不同时间尺度，并可能让两个短周期票数覆盖一个长周期结构事实。

现有 MarketCell 协议和 ExecutionPlan 都是单 target + 单 horizon scope。把跨周期决策硬塞进默认 Cell DAG 会让 AnalysisRequest、InputSnapshot、node scope 和回放身份产生歧义。

## 决策

### 1. HorizonDecisionCell 是应用层类型化聚合 Cell

它消费完整 `multi_horizon_analysis.v1`，输出 `horizon_decision.v1`。v1 不注册到单周期 CellRegistry、不进入 CellGraphDefinition、不新增 InputKind。

### 2. 周期先分层，再按结构权威聚合

short `<4h`，medium `4h–1w`，long `>=1w`。层内最长 horizon 使用指数递增权重；跨层基础权威为 short 0.2、medium 0.3、long 0.5。缺失层级只在现有层级中归一化。

### 3. 方向必须先通过质量门槛

只有方向、score、strength 和 confidence 同时达到版本化门槛的 child 才进入确认。低置信度反向噪音不能制造与高周期等权的假冲突。

### 4. 总体方向与结构方向分开

层内或层间冲突时总体 direction 为 conflict；最高有效层级方向单独保存在 structural_direction。最高层级自身 conflict 时，结构方向保持 neutral。

### 5. 冲突使用类型而不是自然语言猜测

v1 固定区分 intra_band、short_vs_higher、medium_vs_long、lower_vs_long 和 broad，并输出 0–100 conflict score。

### 6. 风险覆盖 posture，不改写方向

总体风险取 child 最大值。high/extreme risk 分别覆盖为 reduce_exposure/avoid_chasing；方向事实继续独立保存。

### 7. 决策身份只覆盖行为输入

decision hash 覆盖 source request/Graph/formula identity、公式使用的 child 信号字段、完整 policy 参数和标准化决策语义；这样跨语言实现漂移不能在相同 id 下隐藏。batch/run/report identity、时间戳、解释文案和 metadata 不参与。

## 结果

正向结果：

- 不用票数掩盖周期尺度差异。
- 可以同时表达“总体冲突”和“长周期结构偏多/偏空”。
- 低置信度噪音、高风险和长周期未决状态都有显式保护。
- 同一事实回放得到稳定 decision id。
- 未来可以单独评估冲突分类、结构方向和行动姿态。

约束与代价：

- HorizonDecisionCell 暂不享有单周期 ExecutionPlan/AnalysisRun 的运行持久化。
- 固定时长分层和权威权重需要历史标签校准后才能进入 validated。
- 规则保守，可能比简单投票更频繁输出 partial、conflict 或 wait_for_confirmation。

## 放弃的方案

简单多数票：周期数量不等于结构权威，调用方可通过重复短周期操纵票数。

直接平均 score：正负抵消会把强冲突伪装成 neutral。

长周期永远覆盖短周期：会隐藏真实的战术逆趋势和风险窗口。

方向和风险合成单分数：无法表达“偏多但高风险”。

注册进默认 Cell DAG：现有协议是单 horizon scope，会破坏输入、计划和回放边界。
