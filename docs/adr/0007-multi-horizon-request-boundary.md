# ADR-0007: 多周期请求与单周期执行边界

- 状态：Accepted
- 日期：2026-07-18
- 决策范围：MultiHorizonRequest、时间对齐、批次预检、子运行审计和未聚合结果

## 背景

现有 AnalysisEngine、ExecutionPlan、InputSnapshot、AnalysisRun 和 ReplayRunner 都以一个 target + horizon 为稳定作用域。直接把多套 K 线塞入 AnalysisRequest.context，或把多个周期交给一个 Cell 自行拆分，会破坏输入身份、计划 scope、子运行失败边界和回放证据。

同时，HorizonDecisionCell 的规则尚未设计。如果 MultiHorizonRequest 阶段直接返回“总体看多/看空”，系统会在没有版本化冲突规则的情况下固化错误产品语义。

## 决策

### 1. MultiHorizonRequest 是应用层包络

它包含同一 target、显式 as_of 和 2–8 个完整 AnalysisRequest。它不加入 InputKind，也不进入单个 ExecutionPlan。每个 child 继续独立生成 analysis_request InputSnapshot 和 AnalysisRun。

### 2. v1 强制短到长和显式时间对齐

horizon 使用无前导零的正整数加 `s/m/h/d/w/M` 规范，禁止重复字符串和等价时长。每个 K 线序列严格升序，最新时间不得晚于 as_of，也不得陈旧超过一个周期。所有判断只使用请求内 as_of，不读取墙钟。

### 3. 全部引擎先预检，再启动任何 Cell

批次中的 Graph id、Graph version、Graph canonical content hash 和公式版本集合必须完全一致。差异在 batch preflight 阶段失败，避免已知不兼容仍产生部分运行。

### 4. v1 顺序执行并 fail-fast

顺序与 request.horizon_order 一致。执行失败后抛出结构化 MultiHorizonExecutionError，保存 completed/failed horizon 边界。已经成功并持久化的 child run 不回滚，但批次不返回成功结果。

### 5. 结果明确标记未聚合

`multi_horizon_analysis.v1` 保存有序 AnalysisReport、Graph/公式身份和 `aggregation_status=not_computed`，不包含总体 direction、score、risk 或 action posture。

## 结果

正向结果：

- 复用全部单周期执行、审计和回放地基。
- 多周期输入拥有稳定 request hash 和 request id。
- 陈旧或未来周期数据在分析前失败。
- Graph/公式漂移不能混入同一个批次。
- HorizonDecisionCell 可以建立在确定、完整、有序的子决策上。

约束和代价：

- v1 顺序执行，延迟是各 horizon 之和。
- 批次包络尚未形成独立持久父运行；`--save` 保存每个 child report/run。
- 不同 Graph 的周期分析必须拆成不同批次，不能直接比较。
- 30 天规范月只用于周期排序和陈旧边界，不是市场日历月。

## 放弃的方案

把多周期 K 线放入 AnalysisRequest.context：无类型、无独立输入身份，Cell 和计划无法知道真实 scope。

一个 ExecutionPlan 同时包含多个 horizon：现有 node、trace、input reference 和 CellResult horizon 身份都会变得歧义，且会把应用编排和 Cell DAG 混为一层。

立即实现总体方向：HorizonDecisionCell 尚无公式版本、冲突状态和验证数据，简单投票不具备专业解释力。

允许不同 Graph 混合：结果差异可能来自能力集合而不是周期本身，无法专业比较。
