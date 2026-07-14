from __future__ import annotations

from dataclasses import dataclass, field
from typing import Callable, Protocol

from market_cell.execution.executor import (
    CellExecutionContext,
    CellExecutor,
    validate_cell_result,
    validate_execution_trace,
)
from market_cell.execution.models import (
    CellRuntimeTrace,
    ExecutionRole,
)
from market_cell.execution.plan_validation import ValidatedExecutionPlan
from market_cell.models import AnalysisRequest, CellResult
from market_cell.registry import CellRegistry


PLAN_EXECUTION_SCHEMA_VERSION = "plan_execution.v1"


@dataclass(frozen=True)
class NodeExecutionCompletion:
    node_id: str
    cell_id: str
    binding_id: str
    execution_role: ExecutionRole
    result: CellResult | None
    trace: CellRuntimeTrace | None
    error: Exception | None = field(default=None, repr=False, compare=False)


NodeCompletionHandler = Callable[[NodeExecutionCompletion], None]


@dataclass(frozen=True)
class PlanExecutionOutcome:
    coordinator: str
    plan_id: str
    root_node_id: str
    results_by_node_id: dict[str, CellResult]
    runtime_traces: list[CellRuntimeTrace]
    execution_order: list[str]
    root_result: CellResult | None = None
    failed_node_id: str | None = None
    error: Exception | None = field(default=None, repr=False, compare=False)
    schema_version: str = PLAN_EXECUTION_SCHEMA_VERSION

    def __post_init__(self) -> None:
        if self.error is None:
            if self.root_result is None or self.failed_node_id is not None:
                raise ValueError(
                    "successful plan execution requires a root result and no failed node"
                )
            if self.root_node_id not in self.results_by_node_id:
                raise ValueError("root result must be stored by root_node_id")
            return
        if self.root_result is not None or self.failed_node_id is None:
            raise ValueError(
                "failed plan execution requires an error and failed_node_id"
            )

    @property
    def succeeded(self) -> bool:
        return self.root_result is not None and self.error is None

    def unwrap(self) -> CellResult:
        if self.error is not None:
            raise self.error
        if self.root_result is None:
            raise RuntimeError(
                f"plan {self.plan_id} completed without root result {self.root_node_id}"
            )
        return self.root_result

    def to_dict(self) -> dict[str, object]:
        return {
            "schema_version": self.schema_version,
            "coordinator": self.coordinator,
            "plan_id": self.plan_id,
            "root_node_id": self.root_node_id,
            "status": "succeeded" if self.succeeded else "failed",
            "execution_order": list(self.execution_order),
            "completed_node_ids": list(self.results_by_node_id),
            "failed_node_id": self.failed_node_id,
            "error": str(self.error) if self.error is not None else None,
        }

    def to_run_metadata(self) -> dict[str, object]:
        return {"plan_execution": self.to_dict()}


class CellExecutionCoordinator(Protocol):
    @property
    def name(self) -> str:
        ...

    def execute(
        self,
        *,
        validated_plan: ValidatedExecutionPlan,
        registry: CellRegistry,
        executor: CellExecutor,
        request: AnalysisRequest,
        run_id: str,
        trace_id: str,
        on_node_completed: NodeCompletionHandler | None = None,
    ) -> PlanExecutionOutcome:
        ...


class PlanDrivenLocalCoordinator:
    @property
    def name(self) -> str:
        return "plan_driven_local_coordinator_v0.1"

    def execute(
        self,
        *,
        validated_plan: ValidatedExecutionPlan,
        registry: CellRegistry,
        executor: CellExecutor,
        request: AnalysisRequest,
        run_id: str,
        trace_id: str,
        on_node_completed: NodeCompletionHandler | None = None,
    ) -> PlanExecutionOutcome:
        plan = validated_plan.plan
        nodes_by_id = {node.node_id: node for node in plan.nodes}
        bindings_by_id = {
            binding.binding_id: binding for binding in plan.service_bindings
        }
        results_by_node_id: dict[str, CellResult] = {}
        runtime_traces: list[CellRuntimeTrace] = []
        execution_order: list[str] = []

        for level in validated_plan.topological_levels:
            for node_id in level:
                node = nodes_by_id[node_id]
                binding = bindings_by_id[node.binding_id]
                execution_order.append(node_id)
                trace: CellRuntimeTrace | None = None
                try:
                    cell = registry.resolve(node.cell_id)
                    child_results = (
                        [results_by_node_id[dependency_id] for dependency_id in node.dependencies]
                        if node.dependencies
                        else None
                    )
                    cell_outcome = executor.execute(
                        cell=cell,
                        request=request,
                        child_results=child_results,
                        context=CellExecutionContext(
                            run_id=run_id,
                            trace_id=trace_id,
                            plan_id=plan.plan_id,
                            node=node,
                            binding=binding,
                        ),
                    )
                    trace = cell_outcome.trace
                    runtime_traces.append(trace)
                    result = cell_outcome.unwrap()
                    validate_execution_trace(trace, plan)
                    validate_cell_result(cell, request, result)
                except Exception as exc:
                    completion = NodeExecutionCompletion(
                        node_id=node.node_id,
                        cell_id=node.cell_id,
                        binding_id=node.binding_id,
                        execution_role=node.execution_role,
                        result=None,
                        trace=trace,
                        error=exc,
                    )
                    if on_node_completed is not None:
                        on_node_completed(completion)
                    return PlanExecutionOutcome(
                        coordinator=self.name,
                        plan_id=plan.plan_id,
                        root_node_id=plan.root_node_id,
                        results_by_node_id=results_by_node_id,
                        runtime_traces=runtime_traces,
                        execution_order=execution_order,
                        failed_node_id=node.node_id,
                        error=exc,
                    )

                results_by_node_id[node.node_id] = result
                if on_node_completed is not None:
                    on_node_completed(
                        NodeExecutionCompletion(
                            node_id=node.node_id,
                            cell_id=node.cell_id,
                            binding_id=node.binding_id,
                            execution_role=node.execution_role,
                            result=result,
                            trace=trace,
                        )
                    )

        root_result = results_by_node_id.get(plan.root_node_id)
        if root_result is None:
            error = RuntimeError(
                f"plan {plan.plan_id} completed without root result {plan.root_node_id}"
            )
            return PlanExecutionOutcome(
                coordinator=self.name,
                plan_id=plan.plan_id,
                root_node_id=plan.root_node_id,
                results_by_node_id=results_by_node_id,
                runtime_traces=runtime_traces,
                execution_order=execution_order,
                failed_node_id=plan.root_node_id,
                error=error,
            )
        return PlanExecutionOutcome(
            coordinator=self.name,
            plan_id=plan.plan_id,
            root_node_id=plan.root_node_id,
            results_by_node_id=results_by_node_id,
            runtime_traces=runtime_traces,
            execution_order=execution_order,
            root_result=root_result,
        )
