# MarketCell 稳定性设计 v0.1

## 1. 目标

当前阶段最重要的是先稳定三件事：

- 分析结构稳定
- Cell 输出稳定
- 风险解释稳定

这三件事稳定之后，后续增加多语言实现、真实数据源、AI 解释层和交易前置系统时，系统才不会变成互相猜字段、猜含义、猜风险语气的松散脚本集合。

## 2. 分析结构稳定

当前结构：

```text
AnalysisRequest
→ validate_request
→ AnalysisEngine
→ CellRegistry
→ leaf CellResult[]
→ DecisionPolicy
→ DecisionCell
→ AnalysisReport
→ ReportStore / JSON output
→ ReplayRunner / drift comparison
```

稳定点：

- `AnalysisEngine` 只负责编排，不直接写具体分析公式。
- `CellRegistry` 统一管理 Cell 列表，调用方不依赖具体 Cell 类。
- `AnalysisRun` 保存输入快照、公式版本和 Cell Manifest。
- `AnalysisReport` 带 `schema_version`、`engine_version`、`formula_versions`。
- `ReplayRunner` 使用 `input_snapshot` 重新执行分析，比较决策方向、风险姿态、分数和公式版本漂移。
- 多语言模块通过 `contracts/` 共享 JSON Schema。

后续扩展原则：

- 新增数据源走 Data Connector，不绕过 `AnalysisRequest`。
- 新增报告存储走 ReportStore，不把保存逻辑写进 Cell。
- 新增决策口径优先新增或替换 Policy，不改 Engine 主流程。

## 3. Cell 输出稳定

所有 Cell 必须输出标准 `CellResult`：

```text
direction
strength
confidence
volatility_risk
manipulation_risk
urgency
score
explanation
risk_level
action_posture
evidence
children
metadata
```

稳定点：

- 方向只能是 `bullish / bearish / neutral / conflict`。
- 风险值统一使用 0 到 100。
- 每个非空判断必须尽量提供 evidence。
- `metadata` 可以扩展，但关键消费字段不能只藏在 metadata。
- `formula_version` 通过 Manifest 和 AnalysisRun 记录。

后续扩展原则：

- 新 Cell 必须更新 `cell_dictionary.md` 和测试。
- 新字段必须同步 Python 模型、JSON Schema 和文档。
- 不能输出无法解释的黑盒分数。

## 4. 风险解释稳定

MarketCell 必须长期保持“方向和风险分离”：

```text
方向偏多
但风险中等或偏高
```

当前稳定输出：

- `risk_level`: `low / medium / high / extreme`
- `action_posture`: `observe / wait_for_confirmation / cautious_follow / reduce_exposure / avoid_chasing`
- `risk_breakdown`: 各风险维度的等级
- `risk_notes`: 面向用户的主要风险短句

这些字段由 `DecisionPolicy` 统一生成，`DecisionCell` 只负责封装根节点结果。

后续扩展原则：

- 风险解释不能使用“确定操纵”“必涨必跌”等越界表达。
- 新增风险维度时，要进入 `risk_breakdown`，而不是只写在自然语言里。
- UI、AI 解释和交易前置系统优先读取结构化风险字段，再读取 explanation。

## 5. 当前守护测试

稳定性由这些测试守住：

- `test_stability.py`: 分析结构、Cell 输出和风险解释稳定性。
- `test_contracts.py`: JSON Schema 和报告顶层字段。
- `test_replay.py`: 历史输入快照可重跑，并能发现公式版本变化。
- `test_decision_policy.py`: 方向和风险分层分离。
- `test_registry_validation.py`: 输入契约边界。

运行：

```bash
make test
```
