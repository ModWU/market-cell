# ADR-0005: Cell 执行尝试、幂等与失败控制

- 状态：Accepted
- 日期：2026-07-18
- 决策范围：单节点 attempt、幂等、超时、重试、背压、取消和显式 fallback

## 背景

Executor Router 已经能按 ExecutionPlan 派发节点并校验实际执行位置，但一次调用失败后仍缺少统一语义：哪些错误允许重试、超时后是否接受结果、服务拥塞如何表达、取消何时生效，以及切换备用 binding 后如何证明没有执行计划漂移。

这些行为如果分别隐藏在 transport、worker 或 Cell 内，会形成不可复盘的第二套调度逻辑。失败控制必须位于 Coordinator 与具体 Executor 之间，并使用跨语言契约保存每次 attempt。

## 决策

### 1. 逻辑节点与执行尝试使用两级身份

同一 `run_id + plan_id + node_id` 生成一个稳定 `idempotency_key`。该节点的所有重试和 fallback attempt 共享此键，远程 worker 必须用它抑制重复副作用。

每次 attempt 再由以下字段生成唯一 `attempt_id`：

```text
idempotency_key
binding_id
attempt_number
```

两种身份都使用 canonical JSON 的 SHA-256，算法由 `contracts/test_vectors/execution_identity_v1.json` 固定。

### 2. ExecutionPlan 显式保存 fallback binding

ExecutionPlan v4 首次引入、当前 v5 继续保留以下字段：

```text
binding_id
fallback_binding_ids[]
```

primary 和 fallback 必须属于同一 `cell_id + formula_version`，必须存在于计划的 `service_bindings`，且不能重复。Planner 根据 placement 的健康候选顺序生成 fallback；Router 仍只执行当前 context binding，不做隐式切换。

### 3. FailureControlledExecutor 是唯一失败控制状态机

状态迁移为：

```text
planned
→ admitted / backpressured / canceled
→ attempt running
→ succeeded / failed / timed_out
→ retry same binding
→ fallback next binding
→ terminal succeeded / failed / canceled
```

规则：

- 先耗尽当前 binding 的显式 retry budget，再考虑 fallback。
- routing、dispatch、timeout 和 backpressure 可以进入 fallback。
- 只有 dispatch 和 timeout 默认允许同 binding 重试。
- contract failure、未知 execution failure 和 canceled 不重试、不 fallback。
- fallback 只能使用 ExecutionPlan 已列出的 binding。
- `stateful=true` 的 binding 遇到 dispatch 或 timeout 时，只有声明 `idempotent_execution` capability 才允许 retry 或 fallback。

### 4. Timeout 是结果接收边界，不伪装强制终止

本地同步 Python 无法安全杀死任意正在执行的函数。参考实现使用单调时钟和 executor trace 检查 deadline：超过 `expected_timeout_ms` 的结果被拒收并记录为 timeout，但不会声称已经强制停止底层代码。

生产远程 transport 必须把同一 timeout budget 传给网络调用或 worker，并在 transport 层实现真正的 deadline/cancellation。禁止用无法停止后台工作的线程超时伪装可靠取消。

### 5. Backpressure 和取消在安全边界生效

`max_concurrency` 是每个 service binding 的 admission 上限。达到上限时节点在调用 executor 前返回 backpressure failure，不进入 Cell。

取消信号在 attempt 前、attempt 返回后和 retry/fallback 之间检查。若本地 Cell 已开始执行，参考实现只能拒收其返回结果；远程 adapter 负责传播并尽力终止实际工作。

### 6. 每次 attempt 和最终控制结果都进入 AnalysisRun

`execution_control_record.v1` 保存：

```text
idempotency_key
primary / fallback bindings
attempts[]
retry_count / fallback_count
final binding / final failure kind
terminal status
```

每个 attempt 记录计划 binding、实际服务、状态、失败分类、是否可重试、耗时、trace span 和错误。所有 attempt trace 继续进入 `cell_runtime_traces`，最终 trace 的 `retry_count` 只标记该 attempt 是否为 retry，避免聚合重复累计。

canceled attempt 会保留在 AnalysisRun 和 trace store 中，但标记为不参与 placement window，避免用户取消被误算成服务健康失败。

## 结果

正向结果：

- retry、fallback 和普通失败拥有同一状态机和审计结构。
- Router 保持纯路由职责，运行时降级不会变成隐式行为。
- 远程 worker 可以使用稳定幂等键和 attempt identity。
- 超时与取消不会虚假宣称本地代码已被强制终止。
- 背压在 Cell 启动前生效，不把过载误记成公式失败。

约束和代价：

- 本地同步 executor 只能拒收过期或取消后的结果，不能安全中断任意 Python Cell。
- 内存 admission controller 只约束当前 runtime 实例；跨进程容量由未来 worker/control plane adapter 负责。
- fallback 会增加计划大小和 trace 数量。
- 未分类的普通 execution error 默认不重试，可能牺牲部分可用性以避免重复执行确定性错误。
- 生产级跨进程幂等结果存储仍由未来 remote executor adapter 实现。

## 放弃的方案

Router 内部捕获异常并直接调用本地 fallback：会绕过 ExecutionPlan，无法校验实际 binding。

对所有异常自动重试：公式错误、契约错误和输入错误会被重复执行并掩盖根因。

使用线程池 timeout 后立即返回：Python 线程仍会继续运行，无法保证取消、资源释放或无副作用。

只在最终 trace 写 `retry_count`：无法复盘每次失败 attempt 的服务位置、耗时和原因。
