# MarketCell 多周期决策设计 v0.1

## 1. 文档职责

本文定义 `HorizonDecisionCell` 如何消费完整的 `multi_horizon_analysis.v1`，输出版本化 `horizon_decision.v1`。它解决周期分层、结构方向、冲突类型和风险覆盖，不承担下单、仓位计算或收益预测。

## 2. 架构边界

`HorizonDecisionCell` 是应用层类型化聚合 Cell，不进入单周期 `CellRegistry`、`CellGraphDefinition` 或 `CellExecutionPlan`，也不新增 `InputKind`：

```text
MultiHorizonRequest
→ MultiHorizonAnalyzer
→ MultiHorizonAnalysis(完整、有序、同 Graph/公式)
→ HorizonDecisionCell
→ HorizonDecision
```

这样做保留了两个稳定事实：每个 child 仍能独立回放；跨周期公式不会伪装成单周期 DAG 节点。未来若建立父级运行协议，应为 MultiHorizonAnalysis 和 HorizonDecision 单独定义持久化契约，而不是复用 AnalysisRun 的单 horizon scope。

## 3. 周期分层

公式 `horizon_structure_alignment_v0.1` 使用名义时长分层：

| 层级 | 边界 | 典型周期 |
|---|---|---|
| short | `< 4h` | 15m、1h |
| medium | `>= 4h` 且 `< 1w` | 4h、1d |
| long | `>= 1w` | 1w、1M |

`M` 延续 MultiHorizonRequest 的 30 天规范月，只用于排序和分层，不代表日历月运算。

同一层级内按短到长使用指数权威权重 `1, 2, 4, ...`，因此最长 horizon 始终至少拥有该层级一半权威。跨层级基础权威为：

```text
short  = 0.2
medium = 0.3
long   = 0.5
```

缺失层级时只在现有层级之间归一化，不能把缺失 long 伪装成完整长周期确认。

## 4. 有效方向门槛

child report 只有同时满足以下条件才进入方向确认：

```text
direction in {bullish, bearish}
abs(score) >= 12
strength >= 15
confidence >= 45
```

低置信度反向信号仍保留在 evidence 和结构分数中，但不能与已确认的更高周期方向等权制造冲突。显式 `conflict` 只有在 strength 和 confidence 同样达到门槛时才成为实质层内冲突。

## 5. 方向和结构方向

`direction` 表示当前多周期结论：

- 多个已确认层级同向且没有未决层级：bullish / bearish。
- 任一层级内部存在实质冲突，或层级之间出现相反方向：conflict。
- 没有有效方向：neutral。

`structural_direction` 单独保存最高可用层级的有效方向。发生短线逆长线时：

```text
direction = conflict
structural_direction = bullish / bearish
```

这样既不会隐藏交易窗口冲突，也不会丢失较高周期结构事实。若最高层级自身 conflict，则 structural_direction 保持 neutral，低层级共识不能覆盖未决长周期结构。

## 6. 对齐与冲突类型

`alignment_status`：

| 状态 | 含义 |
|---|---|
| aligned | 至少两个现有层级同向，且所有现有层级都有有效方向 |
| partial | 只有一个有效层级，或仍有中性/低置信度层级未确认 |
| conflicted | 层内或层间存在实质方向冲突 |
| indeterminate | 没有足够方向证据 |

`conflict_type`：

| 类型 | 含义 |
|---|---|
| none | 无冲突 |
| intra_band | 同一 short / medium / long 层级内部冲突 |
| short_vs_higher | short 与更高有效结构相反 |
| medium_vs_long | medium 与 long 相反，short 未共同站在 medium 一侧 |
| lower_vs_long | short 与 medium 共同逆向于 long |
| broad | 无法归入以上结构的广泛冲突 |

冲突检测独立于最终加权分数，禁止让正负分数相互抵消后伪装成 neutral。

## 7. 风险覆盖

方向和风险继续分离。总体 volatility/manipulation risk 取所有 child 的最大值，避免平均值掩盖极端风险。风险只覆盖行动姿态：

```text
extreme → avoid_chasing
high    → reduce_exposure
medium  → wait_for_confirmation
conflict → wait_for_confirmation
indeterminate 且低风险 → observe
低风险且方向有效 → cautious_follow
```

因此允许以下结果稳定存在：

```text
direction = bullish
risk_level = high
action_posture = reduce_exposure
```

## 8. 身份与证据

`decision_hash` 使用 canonical JSON SHA-256，覆盖所有会影响公式行为的字段：

- source request hash、target、as-of、horizon order；
- source Graph id/version/content hash 和公式版本集合；
- 每个 child 的 horizon、direction、score、strength、confidence 和两类风险；
- HorizonDecisionPolicy 的完整参数与 formula version。
- 标准化决策语义，包括总体/结构方向、分层结果、冲突、风险和行动姿态。

把标准化结果纳入身份，可以在某个语言运行时实现漂移但忘记升级 formula version 时立即暴露跨语言差异。batch id、report/run id、created_at、解释文案和 metadata 不参与身份，因此同一事实回放仍会得到相同 decision id。固定向量位于 `contracts/test_vectors/horizon_decision_v1.json`。

结果显式保存规范化 `source_signals`、完整 `policy` 和 `risk_breakdown`，使 decision report 在没有内嵌完整 child reports 时仍能重算并校验 decision hash。每个 horizon 另保留一条 Evidence，weight 同时反映层级权威和层内顺序，reliability 使用 child confidence。`band_decisions` 保存每层成员、anchor、有效方向成员、结构分数、风险和 conflict score。

## 9. 验证与误判防护

机器可读样例位于 `validation/cells/horizon_decision_v0.1.json`，至少覆盖：

- 短中长同向 bullish / bearish；
- short 逆更高周期；
- medium 逆 long；
- short + medium 共同逆 long；
- 层内方向冲突；
- 层内冲突与层间冲突同时出现时归为 broad；
- 高风险覆盖 posture 而不篡改 direction；
- 低置信度短线反向噪音不制造假冲突；
- long 自身冲突阻断低层级共识；
- 全中性保持 indeterminate。

## 10. 当前限制

- 当前仍是规则研究基线，状态为 experimental。
- 尚无独立父运行持久化、历史走势标签、概率校准或收益评估。
- 固定名义时长不替代交易所 session 和专业市场日历。
- 长周期结构权威是保守治理规则，不证明长周期在所有市场都更准确。
- 输出不能直接进入下单；Signal Adapter 和 Risk Guard 仍是独立后续边界。

下一项进入 Organ 组合和共享 Cell；HorizonDecision 的父级持久化与历史校准在进入生产使用前补齐。
