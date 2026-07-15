from dataclasses import replace
import json
from pathlib import Path
import tempfile
import unittest
from unittest.mock import patch

from market_cell.engine import AnalysisEngine
from market_cell.events import EventBus
from market_cell.execution import (
    LocalCellExecutor,
    PlanDrivenLocalCoordinator,
    build_local_execution_plan,
    validate_execution_plan,
)
from market_cell.features import build_feature_snapshot
from market_cell.inputs import (
    InputCompositionError,
    InputIntegrityError,
    InputReferenceNotFoundError,
    InputSnapshot,
    LocalInputResolver,
)
from market_cell.models import AnalysisRequest, Candle
from market_cell.registry import default_registry
from market_cell.reports import FileSystemReportStore


class InputSnapshotTests(unittest.TestCase):
    def test_snapshot_and_reference_identity_are_deterministic(self):
        first = InputSnapshot.from_analysis_request(_request())
        second = InputSnapshot.from_analysis_request(_request())

        self.assertEqual(first.content_hash, second.content_hash)
        self.assertEqual(first.snapshot_id, second.snapshot_id)
        self.assertEqual(
            first.to_reference().reference_id,
            second.to_reference().reference_id,
        )

    def test_provenance_is_part_of_snapshot_identity_not_payload_hash(self):
        primary = InputSnapshot.from_analysis_request(
            _request(),
            source="provider.primary",
        )
        backup = InputSnapshot.from_analysis_request(
            _request(),
            source="provider.backup",
        )

        self.assertEqual(primary.content_hash, backup.content_hash)
        self.assertNotEqual(primary.snapshot_id, backup.snapshot_id)
        self.assertNotEqual(
            primary.to_reference().reference_id,
            backup.to_reference().reference_id,
        )

    def test_non_finite_values_are_rejected_from_canonical_payloads(self):
        with self.assertRaises(ValueError):
            InputSnapshot.create(
                input_kind="feature_snapshot",
                target="BTC/USD",
                horizon="1h",
                payload={"value": float("nan")},
                data_version="test.v1",
                source="unit_test",
            )

    def test_feature_snapshot_can_be_registered_as_versioned_input(self):
        features = build_feature_snapshot(
            _request().candles,
            source_input_hash="a" * 64,
        )
        snapshot = InputSnapshot.from_feature_snapshot(
            features,
            target="BTC/USD",
            horizon="1h",
        )
        resolver = LocalInputResolver()

        reference = resolver.register(snapshot)
        resolved = resolver.resolve(reference)

        self.assertEqual(reference.input_kind, "feature_snapshot")
        self.assertEqual(reference.data_version, features.feature_version)
        self.assertEqual(resolved.payload, features.to_dict())
        self.assertEqual(resolved.schema_version, "input_snapshot.v1")

    def test_reference_does_not_inherit_snapshot_metadata_payloads(self):
        snapshot = InputSnapshot.from_analysis_request(
            _request(),
            metadata={"raw_provider_response": "PAYLOAD_SENTINEL"},
        )

        reference = snapshot.to_reference()

        self.assertEqual(reference.metadata, {})
        self.assertIn("raw_provider_response", snapshot.metadata)


class LocalInputResolverTests(unittest.TestCase):
    def test_resolver_returns_registered_snapshot(self):
        snapshot = InputSnapshot.from_analysis_request(_request())
        resolver = LocalInputResolver()
        reference = resolver.register(snapshot)

        resolved = resolver.resolve(reference)

        self.assertEqual(resolved, snapshot)
        self.assertEqual(resolver.resolve_count, 1)

    def test_registering_same_logical_snapshot_is_idempotent(self):
        resolver = LocalInputResolver()
        first = InputSnapshot.from_analysis_request(_request())
        second = InputSnapshot.from_analysis_request(_request())

        first_reference = resolver.register(first)
        second_reference = resolver.register(second)

        self.assertEqual(first_reference, second_reference)
        self.assertEqual(resolver.resolve(second_reference), second)

    def test_resolver_rejects_missing_reference(self):
        reference = InputSnapshot.from_analysis_request(_request()).to_reference()

        with self.assertRaises(InputReferenceNotFoundError):
            LocalInputResolver().resolve(reference)

    def test_resolver_rejects_tampered_reference_hash_and_size(self):
        resolver = LocalInputResolver()
        reference = resolver.register(
            InputSnapshot.from_analysis_request(_request())
        )

        with self.assertRaises(InputIntegrityError) as hash_error:
            resolver.resolve(replace(reference, content_hash="0" * 64))
        with self.assertRaises(InputIntegrityError) as size_error:
            resolver.resolve(
                replace(
                    reference,
                    payload_size_bytes=reference.payload_size_bytes + 1,
                )
            )

        self.assertIn("content_hash", str(hash_error.exception))
        self.assertIn("payload_size_bytes", str(size_error.exception))
        self.assertEqual(
            hash_error.exception.actual_content_hash,
            reference.content_hash,
        )
        self.assertEqual(
            size_error.exception.actual_payload_size_bytes,
            reference.payload_size_bytes,
        )

    def test_resolver_rejects_tampered_contract_version(self):
        resolver = LocalInputResolver()
        reference = resolver.register(
            InputSnapshot.from_analysis_request(_request())
        )

        with self.assertRaises(InputIntegrityError) as context:
            resolver.resolve(replace(reference, schema_version="input_reference.v2"))

        self.assertIn("schema_version", str(context.exception))

    def test_resolver_rejects_tampered_stored_payload(self):
        resolver = LocalInputResolver()
        snapshot = InputSnapshot.from_analysis_request(_request())
        reference = resolver.register(snapshot)
        snapshot.payload["target"] = "ETH/USD"

        with self.assertRaises(InputIntegrityError) as context:
            resolver.resolve(reference)

        self.assertIn("content_hash", str(context.exception))


class InputExecutionTests(unittest.TestCase):
    def test_many_nodes_resolve_each_reference_once_per_run(self):
        resolver = LocalInputResolver()

        with tempfile.TemporaryDirectory() as temp_dir:
            store = FileSystemReportStore(Path(temp_dir))
            report = AnalysisEngine(
                input_resolver=resolver,
                report_store=store,
            ).run(_request())
            run = store.load_run(report.run_id or "")

        records = run["metadata"]["input_resolution_records"]
        nodes = run["metadata"]["cell_execution_plan"]["nodes"]
        reference = run["metadata"]["cell_execution_plan"]["input_references"][0]
        audit = run["metadata"]["input_snapshot_audit"]
        self.assertEqual(resolver.resolve_count, 1)
        self.assertEqual(len(records), len(nodes))
        self.assertEqual(sum(not record["cache_hit"] for record in records), 1)
        self.assertTrue(all(record["status"] == "succeeded" for record in records))
        self.assertEqual(run["input_hash"], reference["content_hash"])
        self.assertEqual(reference["content_hash"], audit["content_hash"])
        self.assertEqual(
            reference["payload_size_bytes"],
            audit["payload_size_bytes"],
        )
        self.assertNotIn("payload", audit)

    def test_same_engine_can_run_same_input_more_than_once(self):
        resolver = LocalInputResolver()
        engine = AnalysisEngine(input_resolver=resolver)

        first = engine.run(_request())
        second = engine.run(_request())

        self.assertNotEqual(first.run_id, second.run_id)
        self.assertEqual(resolver.resolve_count, 2)

    def test_default_local_input_store_is_scoped_to_each_run(self):
        with patch(
            "market_cell.engine.LocalInputResolver",
            wraps=LocalInputResolver,
        ) as resolver_factory:
            engine = AnalysisEngine()
            engine.run(_request())
            engine.run(_request(timestamp="t3"))

        self.assertEqual(resolver_factory.call_count, 2)

    def test_many_nodes_materialize_analysis_request_once_per_run(self):
        original = InputSnapshot.to_analysis_request

        with patch.object(
            InputSnapshot,
            "to_analysis_request",
            autospec=True,
            side_effect=original,
        ) as materialize:
            AnalysisEngine().run(_request())

        self.assertEqual(materialize.call_count, 1)

    def test_failed_run_persists_input_resolution_audit(self):
        resolver = _MissingAfterRegisterResolver()
        event_bus = EventBus()

        with tempfile.TemporaryDirectory() as temp_dir:
            store = FileSystemReportStore(Path(temp_dir))
            engine = AnalysisEngine(
                event_bus=event_bus,
                input_resolver=resolver,
                report_store=store,
            )
            with self.assertRaises(InputReferenceNotFoundError):
                engine.run(_request())
            failed_event = next(
                event
                for event in event_bus.events
                if event.name == "analysis.failed"
            )
            run = store.load_run(failed_event.payload["run_id"])

        records = run["metadata"]["input_resolution_records"]
        self.assertEqual(run["status"], "failed")
        self.assertEqual(len(records), 1)
        self.assertEqual(records[0]["status"], "failed")
        self.assertFalse(records[0]["cache_hit"])
        self.assertGreater(records[0]["expected_payload_size_bytes"], 0)
        self.assertIsNone(records[0]["actual_payload_size_bytes"])
        self.assertIn("was not found", records[0]["error"])

    def test_invalid_domain_payload_is_a_composition_failure_after_resolution(self):
        resolver = LocalInputResolver()
        snapshot = InputSnapshot.create(
            input_kind="analysis_request",
            target="BTC/USD",
            horizon="1h",
            payload={
                "target": "BTC/USD",
                "horizon": "1h",
                "candles": [{"timestamp": "t1"}],
                "events": [],
                "context": {},
            },
            data_version="analysis_request.v1",
            source="unit_test",
        )
        reference = resolver.register(snapshot)
        plan = build_local_execution_plan(
            default_registry(),
            _request(),
            input_references=[reference],
        )

        outcome = PlanDrivenLocalCoordinator().execute(
            validated_plan=validate_execution_plan(plan),
            registry=default_registry(),
            executor=LocalCellExecutor(),
            input_resolver=resolver,
            run_id="test-run",
            trace_id="test-trace",
        )

        self.assertIsInstance(outcome.error, InputCompositionError)
        self.assertEqual(resolver.resolve_count, 1)
        self.assertEqual(outcome.input_resolution_records[0].status, "succeeded")

    def test_execution_plan_contains_references_not_candle_payloads(self):
        request = _request(timestamp="CANDLE_PAYLOAD_SENTINEL")
        plan = build_local_execution_plan(default_registry(), request).to_dict()
        serialized = json.dumps(plan, sort_keys=True)

        self.assertTrue(plan["input_references"])
        self.assertTrue(
            all("payload" not in reference for reference in plan["input_references"])
        )
        self.assertNotIn("CANDLE_PAYLOAD_SENTINEL", serialized)


class _MissingAfterRegisterResolver(LocalInputResolver):
    def register(self, snapshot):
        return snapshot.to_reference("memory://market-cell-input/missing")


def _request(timestamp: str = "t1") -> AnalysisRequest:
    return AnalysisRequest(
        target="BTC/USD",
        horizon="1h",
        candles=[
            Candle(timestamp, 100, 102, 99, 101, 1000),
            Candle("t2", 101, 104, 100, 103, 1200),
        ],
    )


if __name__ == "__main__":
    unittest.main()
