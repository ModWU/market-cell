# MarketCell 数据契约 v0.2

## 1. 契约目标

数据契约保证不同模块对输入输出的理解一致。

MarketCell 后期会有很多 Cell，如果数据结构不稳定，系统会很快变乱。

## 2. AnalysisRequest

一次分析任务的输入。

```json
{
  "target": "BTC/USD",
  "horizon": "1h",
  "candles": [],
  "events": [],
  "context": {}
}
```

字段：

| 字段 | 类型 | 说明 |
|---|---|---|
| `target` | string | 分析目标，例如 BTC/USD |
| `horizon` | string | 分析周期，例如 1h |
| `candles` | array | K 线数据 |
| `events` | array | 外部事件 |
| `context` | object | 额外上下文 |

## 3. Candle

```json
{
  "timestamp": "2026-07-09T00:00:00Z",
  "open": 108000,
  "high": 108500,
  "low": 107500,
  "close": 108200,
  "volume": 1240
}
```

校验规则：

- `timestamp` 不能为空
- `timestamp` 在一次请求中不能重复
- `open/high/low/close` 必须大于 0
- `open/high/low/close/volume` 必须是有效数字
- `high >= open`
- `high >= close`
- `low <= open`
- `low <= close`
- `high >= low`
- `volume >= 0`

## 4. MarketEvent

```json
{
  "title": "大型机构继续增加 BTC ETF 风险敞口",
  "category": "institution",
  "sentiment": 0.55,
  "impact": 70,
  "freshness": 85
}
```

字段：

| 字段 | 范围 | 说明 |
|---|---|---|
| `sentiment` | -1 到 1 | 负面到正面 |
| `impact` | 0 到 100 | 影响力 |
| `freshness` | 0 到 100 | 新鲜度 |

校验规则：

- `title` 不能为空
- `category` 不能为空
- `sentiment` 必须在 -1 到 1 之间
- `impact` 必须在 0 到 100 之间
- `freshness` 必须在 0 到 100 之间

## 5. CellResult

```json
{
  "cell_id": "technical.trend",
  "direction": "bullish",
  "strength": 30,
  "confidence": 60,
  "volatility_risk": 10,
  "manipulation_risk": 0,
  "urgency": 20,
  "score": 18,
  "explanation": "...",
  "risk_level": "medium",
  "action_posture": "wait_for_confirmation",
  "evidence": [],
  "metadata": {
    "risk_breakdown": {
      "volatility_risk": "medium",
      "manipulation_risk": "medium"
    }
  }
}
```

方向枚举：

```text
bullish
bearish
neutral
conflict
```

风险等级枚举：

```text
low
medium
high
extreme
```

行动姿态枚举：

```text
observe
wait_for_confirmation
cautious_follow
reduce_exposure
avoid_chasing
```

## 6. Evidence

```json
{
  "source": "candles.close",
  "summary": "首尾收盘价上涨 3.14%",
  "weight": 1.0,
  "freshness": 100,
  "reliability": 70
}
```

## 7. AnalysisReport

```json
{
  "target": "BTC/USD",
  "horizon": "1h",
  "decision": {},
  "summary": "...",
  "run_id": "abc123",
  "report_id": "abc123",
  "schema_version": "analysis_report.v1",
  "engine_version": "0.1.0",
  "formula_versions": {
    "technical.trend": "trend_close_change_v0.1",
    "root.decision": "decision_weighted_score_v0.2"
  },
  "created_at": "2026-07-09T00:00:01+00:00",
  "disclaimer": "MarketCell 只提供结构化分析和风险提示，不构成投资建议。"
}
```

`AnalysisReport` 面向使用者，必须能直接说明这份报告遵守哪个 schema、由哪个引擎版本生成、使用了哪些公式版本。

## 8. AnalysisRun

一次可复盘的分析运行。

```json
{
  "run_id": "abc123",
  "target": "BTC/USD",
  "horizon": "1h",
  "engine_version": "0.1.0",
  "input_hash": "...",
  "input_snapshot": {},
  "formula_versions": {},
  "cell_manifests": [],
  "status": "succeeded",
  "schema_version": "analysis_run.v1",
  "started_at": "2026-07-09T00:00:00+00:00",
  "finished_at": "2026-07-09T00:00:01+00:00",
  "report_id": "abc123",
  "metadata": {
    "data_sources": {
      "provider_selection_plan": {},
      "router_plan": {}
    }
  }
}
```

`AnalysisRun` 关注“这次分析如何产生”，`AnalysisReport` 关注“这次分析输出什么”。

`AnalysisRun.metadata` 是运行审计扩展区。当前已经稳定预留：

```text
metadata.data_sources.provider_selection_plan
metadata.data_sources.router_plan
```

规则：

- `AnalysisRun` 必须带 `schema_version = analysis_run.v1`。
- 数据源选择和实际路由计划只进入 `AnalysisRun.metadata`，不进入 `AnalysisReport.decision`。
- metadata 可以继续扩展，但已经命名的领域必须保持结构稳定。
- 回放时应该优先读取 `input_snapshot`、`formula_versions` 和 `metadata`，不要依赖临时日志。

## 9. 版本策略

## 9. CellExecutionPlan

一次分析的 Cell 执行计划。

```json
{
  "plan_id": "plan123",
  "target": "BTC/USD",
  "horizon": "1h",
  "root_node_id": "cell:root.decision",
  "nodes": [],
  "service_bindings": [],
  "schema_version": "cell_execution_plan.v1",
  "created_at": "2026-07-10T00:00:00+00:00",
  "metadata": {}
}
```

`CellExecutionPlan` 关注“本次分析如何执行 Cell DAG”，不是 Cell 输出本身。

当前单服务本地执行也必须能生成计划：

```text
service_id = python-local
runtime = python_local
endpoint = null
```

未来多服务集群可以替换 service binding 和 executor，但不能改变 `CellResult` 输出契约。

## 10. 版本策略

当前已经在 `AnalysisReport` 中加入：

```text
schema_version
engine_version
formula_versions
```

当前已经在 `AnalysisRun` 中加入：

```text
schema_version
engine_version
input_hash
input_snapshot
formula_versions
metadata
```

跨语言 schema 保存在：

```text
contracts/json_schema/
```

后续字段变更必须同步更新：

- Python 模型
- JSON Schema
- 文档示例
- 契约测试
