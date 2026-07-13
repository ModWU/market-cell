from dataclasses import replace
import unittest

from market_cell.execution import (
    CapabilityCatalogError,
    CellRuntimeSummary,
    PlacementUnavailableError,
    RuntimeAwarePlacementPolicy,
    ServiceCapabilityCatalog,
    build_execution_plan,
    build_local_capability_catalog,
    service_binding_id,
)
from market_cell.models import AnalysisRequest, Candle
from market_cell.registry import default_registry


class ExecutionPlacementTests(unittest.TestCase):
    def test_catalog_supports_many_cells_per_service_and_multiple_services_per_cell(self):
        registry = default_registry()
        local_catalog = build_local_capability_catalog(registry)
        trend_manifest = next(
            manifest
            for manifest in registry.manifests()
            if manifest.cell_id == "technical.trend"
        )
        local_trend = local_catalog.candidates_for(trend_manifest)[0]
        rust_trend = replace(
            local_trend,
            implementation_id=f"rust-hot:{trend_manifest.cell_id}:{trend_manifest.formula_version}",
            service_id="rust-hot",
            runtime="rust_service",
            language="rust",
            task_queue="cell.rust-hot",
        )
        catalog = ServiceCapabilityCatalog.create(
            [*local_catalog.bindings, rust_trend],
            catalog_id="test-catalog",
        )

        self.assertGreater(len(local_catalog.bindings), 1)
        self.assertEqual(
            {binding.service_id for binding in catalog.candidates_for(trend_manifest)},
            {"python-local", "rust-hot"},
        )

    def test_catalog_rejects_duplicate_implementation_service_bindings(self):
        binding = build_local_capability_catalog(default_registry()).bindings[0]

        with self.assertRaises(CapabilityCatalogError):
            ServiceCapabilityCatalog.create([binding, binding])

    def test_catalog_allows_same_implementation_on_multiple_services(self):
        registry = default_registry()
        binding = build_local_capability_catalog(registry).bindings[0]
        replica = replace(binding, service_id="python-backup", task_queue="cell.python-backup")

        catalog = ServiceCapabilityCatalog.create([binding, replica])

        candidates = catalog.candidates_for(registry.manifests()[0])
        self.assertEqual(
            {(candidate.implementation_id, candidate.service_id) for candidate in candidates},
            {
                (binding.implementation_id, "python-local"),
                (binding.implementation_id, "python-backup"),
            },
        )
        self.assertEqual(
            replica.binding_id,
            service_binding_id(replica.implementation_id, replica.service_id),
        )
        decision = RuntimeAwarePlacementPolicy().select(
            registry.manifests()[0],
            candidates,
            [
                _summary(binding, trace_count=20, failed_count=0, p95_duration_ms=20),
                _summary(replica, trace_count=20, failed_count=0, p95_duration_ms=5),
            ],
        )
        self.assertEqual(decision.selected_binding.service_id, "python-backup")

    def test_planner_uses_runtime_latency_between_equally_prioritized_services(self):
        registry = default_registry()
        catalog, local_trend, rust_trend = _catalog_with_rust_trend(registry)
        summaries = [
            _summary(local_trend, trace_count=20, failed_count=0, p95_duration_ms=30),
            _summary(rust_trend, trace_count=20, failed_count=0, p95_duration_ms=5),
        ]

        plan = build_execution_plan(
            registry,
            _request(),
            catalog,
            runtime_summaries=summaries,
        )

        trend_node = next(node for node in plan.nodes if node.cell_id == "technical.trend")
        trend_binding = next(
            binding
            for binding in plan.service_bindings
            if binding.binding_id == trend_node.binding_id
        )
        decision = next(
            item
            for item in plan.metadata["placement_decisions"]
            if item["cell_id"] == "technical.trend"
        )
        self.assertEqual(trend_binding.implementation_id, rust_trend.implementation_id)
        self.assertEqual(decision["selected_service_id"], "rust-hot")
        self.assertIn("selected_by_runtime_latency", decision["reason_codes"])
        self.assertEqual(decision["schema_version"], "cell_placement_decision.v2")
        self.assertEqual(decision["selected_binding_id"], rust_trend.binding_id)

    def test_planner_avoids_unhealthy_service_even_when_it_has_higher_priority(self):
        registry = default_registry()
        catalog, local_trend, rust_trend = _catalog_with_rust_trend(
            registry,
            rust_priority=10,
        )
        summaries = [
            _summary(local_trend, trace_count=20, failed_count=0, p95_duration_ms=30),
            _summary(rust_trend, trace_count=20, failed_count=10, p95_duration_ms=5),
        ]

        plan = build_execution_plan(
            registry,
            _request(),
            catalog,
            runtime_summaries=summaries,
        )

        decision = next(
            item
            for item in plan.metadata["placement_decisions"]
            if item["cell_id"] == "technical.trend"
        )
        self.assertEqual(decision["selected_service_id"], "python-local")
        self.assertIn("unhealthy_candidates_avoided", decision["reason_codes"])

    def test_policy_rejects_incompatible_formula_versions(self):
        manifest = default_registry().manifests()[0]
        binding = build_local_capability_catalog(default_registry()).bindings[0]
        incompatible = replace(binding, formula_version="other-version")

        with self.assertRaises(PlacementUnavailableError):
            RuntimeAwarePlacementPolicy().select(manifest, [incompatible])


def _catalog_with_rust_trend(registry, rust_priority: int = 100):
    local_catalog = build_local_capability_catalog(registry)
    trend_manifest = next(
        manifest
        for manifest in registry.manifests()
        if manifest.cell_id == "technical.trend"
    )
    local_trend = local_catalog.candidates_for(trend_manifest)[0]
    rust_trend = replace(
        local_trend,
        implementation_id=f"rust-hot:{trend_manifest.cell_id}:{trend_manifest.formula_version}",
        service_id="rust-hot",
        runtime="rust_service",
        language="rust",
        task_queue="cell.rust-hot",
        priority=rust_priority,
    )
    return (
        ServiceCapabilityCatalog.create(
            [*local_catalog.bindings, rust_trend],
            catalog_id="test-catalog",
        ),
        local_trend,
        rust_trend,
    )


def _summary(
    binding,
    *,
    trace_count: int,
    failed_count: int,
    p95_duration_ms: float,
) -> CellRuntimeSummary:
    succeeded_count = trace_count - failed_count
    return CellRuntimeSummary(
        cell_id=binding.cell_id,
        formula_version=binding.formula_version,
        implementation_id=binding.implementation_id,
        service_id=binding.service_id,
        runtime=binding.runtime,
        trace_count=trace_count,
        succeeded_count=succeeded_count,
        failed_count=failed_count,
        skipped_count=0,
        average_duration_ms=p95_duration_ms,
        max_duration_ms=p95_duration_ms,
        min_duration_ms=p95_duration_ms,
        p95_duration_ms=p95_duration_ms,
        error_count=failed_count,
        retry_count=0,
    )


def _request() -> AnalysisRequest:
    return AnalysisRequest(
        target="BTC/USD",
        horizon="1h",
        candles=[
            Candle("t1", 100, 102, 99, 101, 1000),
            Candle("t2", 101, 104, 100, 103, 1200),
        ],
    )


if __name__ == "__main__":
    unittest.main()
