from __future__ import annotations

from dataclasses import dataclass, replace
from threading import Event, Lock
from time import perf_counter
from typing import Protocol
from uuid import uuid4

from market_cell.cells.base import MarketCell
from market_cell.events import utc_now_iso
from market_cell.execution.executor import (
    CellExecutionBindingError,
    CellExecutionContext,
    CellExecutionError,
    CellExecutionOutcome,
    CellExecutor,
    CellResultContractError,
    ExecutionTraceMismatchError,
    cell_input_trace_metadata,
)
from market_cell.execution.models import (
    CellExecutionAttempt,
    CellRuntimeTrace,
    CellServiceBinding,
    ExecutionControlRecord,
    ExecutionFailureKind,
)
from market_cell.execution.router import (
    ExecutorDispatchError,
    ExecutorRouteNotFoundError,
)
from market_cell.hashing import stable_json_hash
from market_cell.models import AnalysisRequest, CellResult


IDEMPOTENT_EXECUTION_CAPABILITY = "idempotent_execution"


class CellExecutionControlError(CellExecutionError):
    pass


class CellExecutionTimeoutError(CellExecutionControlError):
    pass


class CellExecutionBackpressureError(CellExecutionControlError):
    pass


class CellExecutionCanceledError(CellExecutionControlError):
    pass


class ExecutionControlMismatchError(CellExecutionControlError):
    pass


@dataclass(frozen=True)
class FailureClassification:
    kind: ExecutionFailureKind
    retryable: bool
    allows_fallback: bool


class FailureClassifier(Protocol):
    def classify(self, error: Exception) -> FailureClassification:
        ...


class DefaultFailureClassifier:
    def classify(self, error: Exception) -> FailureClassification:
        if isinstance(error, ExecutorRouteNotFoundError):
            return FailureClassification("routing", False, True)
        if isinstance(error, ExecutorDispatchError):
            return FailureClassification("dispatch", True, True)
        if isinstance(error, CellExecutionTimeoutError):
            return FailureClassification("timeout", True, True)
        if isinstance(error, CellExecutionBackpressureError):
            return FailureClassification("backpressure", False, True)
        if isinstance(error, CellExecutionCanceledError):
            return FailureClassification("canceled", False, False)
        if isinstance(
            error,
            (
                CellExecutionBindingError,
                CellResultContractError,
                ExecutionTraceMismatchError,
            ),
        ):
            return FailureClassification("contract", False, False)
        return FailureClassification("execution", False, False)


class AdmissionLease(Protocol):
    def release(self) -> None:
        ...


class ExecutionAdmissionController(Protocol):
    @property
    def name(self) -> str:
        ...

    def try_acquire(self, binding: CellServiceBinding) -> AdmissionLease | None:
        ...


class UnlimitedAdmissionController:
    @property
    def name(self) -> str:
        return "unlimited_admission_controller_v0.1"

    def try_acquire(self, binding: CellServiceBinding) -> AdmissionLease:
        return _NoopAdmissionLease()


class InMemoryConcurrencyAdmissionController:
    def __init__(self) -> None:
        self._lock = Lock()
        self._active_by_binding: dict[str, int] = {}

    @property
    def name(self) -> str:
        return "in_memory_concurrency_admission_controller_v0.1"

    def try_acquire(self, binding: CellServiceBinding) -> AdmissionLease | None:
        if binding.max_concurrency is None:
            return _NoopAdmissionLease()
        with self._lock:
            active = self._active_by_binding.get(binding.binding_id, 0)
            if active >= binding.max_concurrency:
                return None
            self._active_by_binding[binding.binding_id] = active + 1
        return _ConcurrencyAdmissionLease(self, binding.binding_id)

    def _release(self, binding_id: str) -> None:
        with self._lock:
            active = self._active_by_binding.get(binding_id, 0)
            if active <= 1:
                self._active_by_binding.pop(binding_id, None)
            else:
                self._active_by_binding[binding_id] = active - 1


class CancellationToken:
    def __init__(self) -> None:
        self._event = Event()

    def cancel(self) -> None:
        self._event.set()

    def is_cancellation_requested(self) -> bool:
        return self._event.is_set()


class FailureControlledExecutor:
    """Applies retry, fallback, deadline, admission, and cancellation rules."""

    def __init__(
        self,
        delegate: CellExecutor,
        *,
        admission_controller: ExecutionAdmissionController | None = None,
        failure_classifier: FailureClassifier | None = None,
    ) -> None:
        self.delegate = delegate
        self.admission_controller = (
            admission_controller or InMemoryConcurrencyAdmissionController()
        )
        self.failure_classifier = failure_classifier or DefaultFailureClassifier()

    @property
    def name(self) -> str:
        return "failure_controlled_executor_v0.1"

    @property
    def service_id(self) -> str | None:
        value = getattr(self.delegate, "service_id", None)
        return value if isinstance(value, str) and value.strip() else None

    def execute(
        self,
        *,
        cell: MarketCell,
        request: AnalysisRequest,
        context: CellExecutionContext,
        child_results: list[CellResult] | None = None,
    ) -> CellExecutionOutcome:
        if context.plan_id is None or context.node is None or context.binding is None:
            raise CellExecutionControlError(
                "failure control requires plan_id, execution node, and service binding"
            )
        expected_fallback_ids = list(context.node.fallback_binding_ids)
        actual_fallback_ids = [
            binding.binding_id for binding in context.fallback_bindings
        ]
        if actual_fallback_ids != expected_fallback_ids:
            raise CellExecutionControlError(
                f"node {context.node.node_id} fallback bindings do not match the plan"
            )

        started_at = utc_now_iso()
        idempotency_key = context.idempotency_key or execution_idempotency_key(
            context
        )
        candidate_bindings = [context.binding, *context.fallback_bindings]
        attempts: list[CellExecutionAttempt] = []
        traces: list[CellRuntimeTrace] = []
        final_outcome: CellExecutionOutcome | None = None

        for fallback_index, binding in enumerate(candidate_bindings):
            timeout_ms = min(
                context.node.resource_hints.expected_timeout_ms,
                binding.resource_hints.expected_timeout_ms,
            )
            max_retries = min(
                context.node.resource_hints.max_retries,
                binding.resource_hints.max_retries,
            )
            max_attempts = max_retries + 1
            for binding_attempt_number in range(1, max_attempts + 1):
                attempt_number = len(attempts) + 1
                attempt_id = execution_attempt_id(
                    idempotency_key,
                    binding.binding_id,
                    attempt_number,
                )
                attempt_context = replace(
                    context,
                    node=replace(
                        context.node,
                        binding_id=binding.binding_id,
                    ),
                    binding=binding,
                    fallback_bindings=(),
                    idempotency_key=idempotency_key,
                    attempt_id=attempt_id,
                    attempt_number=attempt_number,
                    timeout_ms=timeout_ms,
                )
                outcome, observed_duration_ms = self._execute_attempt(
                    cell=cell,
                    request=request,
                    context=attempt_context,
                    child_results=child_results,
                )
                is_retry = binding_attempt_number > 1
                classification = (
                    None
                    if outcome.error is None
                    else _effective_classification(
                        self.failure_classifier.classify(outcome.error),
                        binding,
                    )
                )
                outcome = _annotate_attempt_outcome(
                    outcome,
                    attempt_id=attempt_id,
                    idempotency_key=idempotency_key,
                    attempt_number=attempt_number,
                    binding_attempt_number=binding_attempt_number,
                    fallback_index=fallback_index,
                    timeout_ms=timeout_ms,
                    is_retry=is_retry,
                    classification=classification,
                )
                traces.extend(outcome.runtime_traces)
                attempt = _attempt_record(
                    outcome=outcome,
                    binding=binding,
                    attempt_id=attempt_id,
                    idempotency_key=idempotency_key,
                    attempt_number=attempt_number,
                    binding_attempt_number=binding_attempt_number,
                    fallback_index=fallback_index,
                    observed_duration_ms=observed_duration_ms,
                    classification=classification,
                    timeout_ms=timeout_ms,
                )
                attempts.append(attempt)
                final_outcome = outcome

                if outcome.error is None:
                    return _finalize_outcome(
                        outcome=outcome,
                        traces=traces,
                        record=_control_record(
                            executor=self,
                            context=context,
                            idempotency_key=idempotency_key,
                            attempts=attempts,
                            started_at=started_at,
                        ),
                    )

                if (
                    classification is not None
                    and classification.retryable
                    and binding_attempt_number < max_attempts
                ):
                    continue
                break

            if final_outcome is None or final_outcome.error is None:
                break
            final_classification = _effective_classification(
                self.failure_classifier.classify(final_outcome.error),
                binding,
            )
            if (
                final_classification.allows_fallback
                and fallback_index + 1 < len(candidate_bindings)
            ):
                continue
            break

        if final_outcome is None:
            raise CellExecutionControlError("failure control completed without an attempt")
        return _finalize_outcome(
            outcome=final_outcome,
            traces=traces,
            record=_control_record(
                executor=self,
                context=context,
                idempotency_key=idempotency_key,
                attempts=attempts,
                started_at=started_at,
            ),
        )

    def _execute_attempt(
        self,
        *,
        cell: MarketCell,
        request: AnalysisRequest,
        context: CellExecutionContext,
        child_results: list[CellResult] | None,
    ) -> tuple[CellExecutionOutcome, float]:
        if _is_canceled(context):
            error = CellExecutionCanceledError(
                f"node {context.node.node_id} was canceled before attempt"
            )
            return (
                _boundary_failure(
                    cell=cell,
                    context=context,
                    error=error,
                    phase="cancellation",
                ),
                0.0,
            )

        try:
            lease = self.admission_controller.try_acquire(context.binding)
        except Exception as exc:
            error = CellExecutionControlError(
                f"admission controller {self.admission_controller.name} failed: {exc}"
            )
            error.__cause__ = exc
            return (
                _boundary_failure(
                    cell=cell,
                    context=context,
                    error=error,
                    phase="admission_control",
                    metadata={"cause_type": type(exc).__name__},
                ),
                0.0,
            )
        if lease is None:
            error = CellExecutionBackpressureError(
                f"binding {context.binding.binding_id} reached max_concurrency"
            )
            return (
                _boundary_failure(
                    cell=cell,
                    context=context,
                    error=error,
                    phase="admission",
                    metadata={
                        "admission_controller": self.admission_controller.name,
                    },
                ),
                0.0,
            )

        started = perf_counter()
        release_error: Exception | None = None
        try:
            try:
                outcome = self.delegate.execute(
                    cell=cell,
                    request=request,
                    context=context,
                    child_results=child_results,
                )
                if not isinstance(outcome, CellExecutionOutcome):
                    raise TypeError(
                        f"executor {self.delegate.name} returned "
                        f"{type(outcome).__name__}, expected CellExecutionOutcome"
                    )
            except Exception as exc:
                if isinstance(exc, CellExecutionError):
                    error = exc
                else:
                    error = ExecutorDispatchError(
                        f"executor {self.delegate.name} raised before returning an outcome: {exc}"
                    )
                    error.__cause__ = exc
                outcome = _boundary_failure(
                    cell=cell,
                    context=context,
                    error=error,
                    phase="dispatch",
                    metadata={"cause_type": type(exc).__name__},
                )
        finally:
            try:
                lease.release()
            except Exception as exc:
                release_error = exc

        observed_duration_ms = round((perf_counter() - started) * 1000, 6)
        effective_duration_ms = max(
            observed_duration_ms,
            *(trace.duration_ms for trace in outcome.runtime_traces),
        )
        if release_error is not None:
            error = CellExecutionControlError(
                f"admission lease release failed: {release_error}"
            )
            error.__cause__ = release_error
            outcome = _replace_outcome_error(
                outcome,
                error,
                metadata={
                    "admission_release_status": "failed",
                    "cause_type": type(release_error).__name__,
                    "delegate_error": outcome.trace.error,
                },
            )
        if effective_duration_ms > context.timeout_ms:
            error = CellExecutionTimeoutError(
                f"binding {context.binding.binding_id} exceeded "
                f"timeout {context.timeout_ms}ms with {effective_duration_ms}ms"
            )
            outcome = _replace_outcome_error(
                outcome,
                error,
                metadata={
                    "deadline_status": "expired",
                    "timeout_ms": context.timeout_ms,
                    "observed_duration_ms": effective_duration_ms,
                },
            )
        elif _is_canceled(context) and outcome.error is None:
            error = CellExecutionCanceledError(
                f"node {context.node.node_id} was canceled during attempt"
            )
            outcome = _replace_outcome_error(
                outcome,
                error,
                metadata={"cancellation_status": "observed_after_attempt"},
            )
        return outcome, effective_duration_ms


@dataclass
class _NoopAdmissionLease:
    def release(self) -> None:
        return None


class _ConcurrencyAdmissionLease:
    def __init__(
        self,
        controller: InMemoryConcurrencyAdmissionController,
        binding_id: str,
    ) -> None:
        self._controller = controller
        self._binding_id = binding_id
        self._released = False

    def release(self) -> None:
        if self._released:
            return
        self._released = True
        self._controller._release(self._binding_id)


def execution_idempotency_key(context: CellExecutionContext) -> str:
    if context.plan_id is None or context.node is None:
        raise ValueError("execution idempotency requires plan_id and node")
    return stable_json_hash(
        {
            "schema_version": "execution_idempotency.v1",
            "run_id": context.run_id,
            "plan_id": context.plan_id,
            "node_id": context.node.node_id,
        }
    )


def execution_attempt_id(
    idempotency_key: str,
    binding_id: str,
    attempt_number: int,
) -> str:
    if attempt_number < 1:
        raise ValueError("attempt_number must be at least 1")
    return stable_json_hash(
        {
            "schema_version": "execution_attempt_identity.v1",
            "idempotency_key": idempotency_key,
            "binding_id": binding_id,
            "attempt_number": attempt_number,
        }
    )


def execution_control_id(idempotency_key: str) -> str:
    return stable_json_hash(
        {
            "schema_version": "execution_control_identity.v1",
            "idempotency_key": idempotency_key,
        }
    )


def validate_execution_control_record(
    record: ExecutionControlRecord,
    context: CellExecutionContext,
    traces: list[CellRuntimeTrace],
) -> None:
    if context.plan_id is None or context.node is None or context.binding is None:
        raise ExecutionControlMismatchError(
            "execution control validation requires planned context"
        )
    expected_idempotency_key = (
        context.idempotency_key or execution_idempotency_key(context)
    )
    expected_fallback_ids = [
        binding.binding_id for binding in context.fallback_bindings
    ]
    mismatches: list[str] = []
    if record.control_id != execution_control_id(expected_idempotency_key):
        mismatches.append("control_id")
    if record.idempotency_key != expected_idempotency_key:
        mismatches.append("idempotency_key")
    if record.run_id != context.run_id:
        mismatches.append("run_id")
    if record.plan_id != context.plan_id:
        mismatches.append("plan_id")
    if record.node_id != context.node.node_id:
        mismatches.append("node_id")
    if record.primary_binding_id != context.binding.binding_id:
        mismatches.append("primary_binding_id")
    if record.fallback_binding_ids != expected_fallback_ids:
        mismatches.append("fallback_binding_ids")

    trace_span_ids = {trace.span_id for trace in traces}
    if any(
        attempt.trace_span_id is None
        or attempt.trace_span_id not in trace_span_ids
        or attempt.attempt_id
        != execution_attempt_id(
            expected_idempotency_key,
            attempt.binding_id,
            attempt.attempt_number,
        )
        for attempt in record.attempts
    ):
        mismatches.append("attempt_identity")
    if not traces or record.attempts[-1].trace_span_id != traces[-1].span_id:
        mismatches.append("final_trace")
    if mismatches:
        raise ExecutionControlMismatchError(
            f"execution control record for {record.node_id} does not match context: "
            f"{', '.join(sorted(set(mismatches)))}"
        )


def _is_canceled(context: CellExecutionContext) -> bool:
    return (
        context.cancellation_signal is not None
        and context.cancellation_signal.is_cancellation_requested()
    )


def _effective_classification(
    classification: FailureClassification,
    binding: CellServiceBinding,
) -> FailureClassification:
    repeat_is_safe = (
        not binding.resource_hints.stateful
        or IDEMPOTENT_EXECUTION_CAPABILITY in binding.capabilities
    )
    if repeat_is_safe or classification.kind not in {"dispatch", "timeout"}:
        return classification
    return FailureClassification(
        kind=classification.kind,
        retryable=False,
        allows_fallback=False,
    )


def _boundary_failure(
    *,
    cell: MarketCell,
    context: CellExecutionContext,
    error: Exception,
    phase: str,
    metadata: dict[str, object] | None = None,
) -> CellExecutionOutcome:
    manifest = cell.manifest()
    timestamp = utc_now_iso()
    binding = context.binding
    trace = CellRuntimeTrace(
        trace_id=context.trace_id,
        span_id=uuid4().hex,
        run_id=context.run_id,
        plan_id=context.plan_id,
        node_id=context.node.node_id if context.node is not None else f"cell:{cell.cell_id}",
        cell_id=manifest.cell_id,
        formula_version=manifest.formula_version,
        status="failed",
        started_at=timestamp,
        finished_at=timestamp,
        duration_ms=0.0,
        error=str(error),
        metadata={
            "executor": "failure_controlled_executor_v0.1",
            "execution_phase": phase,
            "planned_binding_id": binding.binding_id if binding is not None else None,
            "planned_implementation_id": (
                binding.implementation_id if binding is not None else None
            ),
            "planned_service_id": binding.service_id if binding is not None else None,
            "planned_runtime": binding.runtime if binding is not None else None,
            **cell_input_trace_metadata(context),
            **(metadata or {}),
        },
    )
    return CellExecutionOutcome(trace=trace, error=error)


def _replace_outcome_error(
    outcome: CellExecutionOutcome,
    error: Exception,
    *,
    metadata: dict[str, object],
) -> CellExecutionOutcome:
    trace = replace(
        outcome.trace,
        status="failed",
        error=str(error),
        metadata={**outcome.trace.metadata, **metadata},
    )
    return CellExecutionOutcome(
        trace=trace,
        error=error,
        prior_traces=outcome.prior_traces,
    )


def _annotate_attempt_outcome(
    outcome: CellExecutionOutcome,
    *,
    attempt_id: str,
    idempotency_key: str,
    attempt_number: int,
    binding_attempt_number: int,
    fallback_index: int,
    timeout_ms: int,
    is_retry: bool,
    classification: FailureClassification | None,
) -> CellExecutionOutcome:
    trace = replace(
        outcome.trace,
        retry_count=1 if is_retry else 0,
        metadata={
            **outcome.trace.metadata,
            "execution_control": {
                "attempt_id": attempt_id,
                "idempotency_key": idempotency_key,
                "attempt_number": attempt_number,
                "binding_attempt_number": binding_attempt_number,
                "fallback_index": fallback_index,
                "timeout_ms": timeout_ms,
                "failure_kind": (
                    classification.kind if classification is not None else None
                ),
                "placement_eligible": (
                    classification is None or classification.kind != "canceled"
                ),
            },
        },
    )
    return CellExecutionOutcome(
        trace=trace,
        result=outcome.result,
        error=outcome.error,
        prior_traces=outcome.prior_traces,
    )


def _attempt_record(
    *,
    outcome: CellExecutionOutcome,
    binding: CellServiceBinding,
    attempt_id: str,
    idempotency_key: str,
    attempt_number: int,
    binding_attempt_number: int,
    fallback_index: int,
    observed_duration_ms: float,
    classification: FailureClassification | None,
    timeout_ms: int,
) -> CellExecutionAttempt:
    trace = outcome.trace
    if classification is None:
        status = "succeeded"
    elif classification.kind == "timeout":
        status = "timed_out"
    elif classification.kind == "backpressure":
        status = "backpressured"
    elif classification.kind == "canceled":
        status = "canceled"
    else:
        status = "failed"
    return CellExecutionAttempt(
        attempt_id=attempt_id,
        idempotency_key=idempotency_key,
        attempt_number=attempt_number,
        binding_attempt_number=binding_attempt_number,
        fallback_index=fallback_index,
        binding_id=binding.binding_id,
        is_retry=binding_attempt_number > 1,
        status=status,
        failure_kind=classification.kind if classification is not None else None,
        retryable=classification.retryable if classification is not None else False,
        started_at=trace.started_at,
        finished_at=trace.finished_at,
        duration_ms=observed_duration_ms,
        trace_span_id=trace.span_id,
        actual_implementation_id=trace.implementation_id,
        actual_service_id=trace.service_id,
        actual_runtime=trace.runtime,
        error=str(outcome.error) if outcome.error is not None else None,
        metadata={
            "timeout_ms": timeout_ms,
            "stateful": binding.resource_hints.stateful,
            "idempotent_execution": (
                IDEMPOTENT_EXECUTION_CAPABILITY in binding.capabilities
            ),
            "allows_fallback": (
                classification.allows_fallback
                if classification is not None
                else False
            ),
        },
    )


def _control_record(
    *,
    executor: FailureControlledExecutor,
    context: CellExecutionContext,
    idempotency_key: str,
    attempts: list[CellExecutionAttempt],
    started_at: str,
) -> ExecutionControlRecord:
    final_attempt = attempts[-1]
    status = (
        "succeeded"
        if final_attempt.status == "succeeded"
        else "canceled"
        if final_attempt.status == "canceled"
        else "failed"
    )
    return ExecutionControlRecord(
        control_id=execution_control_id(idempotency_key),
        idempotency_key=idempotency_key,
        run_id=context.run_id,
        plan_id=context.plan_id or "",
        node_id=context.node.node_id if context.node is not None else "",
        primary_binding_id=(
            context.binding.binding_id if context.binding is not None else ""
        ),
        fallback_binding_ids=[
            binding.binding_id for binding in context.fallback_bindings
        ],
        status=status,
        attempts=list(attempts),
        retry_count=sum(attempt.is_retry for attempt in attempts),
        fallback_count=max(attempt.fallback_index for attempt in attempts),
        final_binding_id=final_attempt.binding_id,
        final_failure_kind=final_attempt.failure_kind,
        started_at=started_at,
        finished_at=utc_now_iso(),
        metadata={
            "executor": executor.name,
            "delegate_executor": executor.delegate.name,
            "admission_controller": executor.admission_controller.name,
            "failure_classifier": type(executor.failure_classifier).__name__,
        },
    )


def _finalize_outcome(
    *,
    outcome: CellExecutionOutcome,
    traces: list[CellRuntimeTrace],
    record: ExecutionControlRecord,
) -> CellExecutionOutcome:
    if not traces:
        raise CellExecutionControlError("execution control completed without traces")
    return CellExecutionOutcome(
        trace=traces[-1],
        result=outcome.result,
        error=outcome.error,
        prior_traces=tuple(traces[:-1]),
        control_record=record,
    )
