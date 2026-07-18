from __future__ import annotations

from typing import Protocol

from market_cell.hashing import canonical_json_hash_and_size
from market_cell.inputs.models import (
    INPUT_SNAPSHOT_SCHEMA_VERSION,
    InputReference,
    InputSnapshot,
)


class InputResolutionError(RuntimeError):
    def __init__(
        self,
        message: str,
        *,
        actual_content_hash: str | None = None,
        actual_payload_size_bytes: int | None = None,
    ) -> None:
        super().__init__(message)
        self.actual_content_hash = actual_content_hash
        self.actual_payload_size_bytes = actual_payload_size_bytes


class InputReferenceNotFoundError(InputResolutionError):
    pass


class InputIntegrityError(InputResolutionError):
    pass


class InputCompositionError(InputResolutionError):
    pass


class InputResolver(Protocol):
    @property
    def name(self) -> str:
        ...

    def resolve(self, reference: InputReference) -> InputSnapshot:
        ...


class InputSnapshotStore(InputResolver, Protocol):
    def register(self, snapshot: InputSnapshot) -> InputReference:
        ...


class LocalInputResolver:
    def __init__(self) -> None:
        self._snapshots_by_uri: dict[str, InputSnapshot] = {}
        self.resolve_count = 0

    @property
    def name(self) -> str:
        return "local_memory_input_resolver_v0.1"

    def register(self, snapshot: InputSnapshot) -> InputReference:
        _validate_snapshot(snapshot)
        reference = snapshot.to_reference()
        existing = self._snapshots_by_uri.get(reference.uri)
        if existing is not None:
            _validate_snapshot(existing)
            mismatches = _reference_mismatches(
                reference,
                existing.to_reference(reference.uri),
            )
            if mismatches:
                raise InputIntegrityError(
                    f"input URI collision for {reference.uri}: "
                    f"{', '.join(mismatches)}",
                    actual_content_hash=existing.content_hash,
                    actual_payload_size_bytes=existing.payload_size_bytes,
                )
        self._snapshots_by_uri[reference.uri] = snapshot
        return reference

    def resolve(self, reference: InputReference) -> InputSnapshot:
        self.resolve_count += 1
        snapshot = self._snapshots_by_uri.get(reference.uri)
        if snapshot is None:
            raise InputReferenceNotFoundError(
                f"input reference {reference.reference_id} was not found at {reference.uri}"
            )
        _validate_snapshot(snapshot)
        expected_reference = snapshot.to_reference(reference.uri)
        mismatches = _reference_mismatches(reference, expected_reference)
        if mismatches:
            raise InputIntegrityError(
                f"input reference {reference.reference_id} failed integrity checks: "
                f"{', '.join(mismatches)}",
                actual_content_hash=snapshot.content_hash,
                actual_payload_size_bytes=snapshot.payload_size_bytes,
            )
        return snapshot


def _validate_snapshot(snapshot: InputSnapshot) -> None:
    if not isinstance(snapshot.payload, dict):
        raise InputIntegrityError(
            f"input snapshot {snapshot.snapshot_id} payload must be an object"
        )
    try:
        actual_hash, actual_size = canonical_json_hash_and_size(snapshot.payload)
    except (TypeError, ValueError) as exc:
        raise InputIntegrityError(
            f"input snapshot {snapshot.snapshot_id} is not canonical JSON"
        ) from exc
    mismatches: list[str] = []
    if snapshot.schema_version != INPUT_SNAPSHOT_SCHEMA_VERSION:
        mismatches.append("schema_version")
    if snapshot.input_kind not in (
        "analysis_request",
        "candle_batch",
        "funding_open_interest_snapshot",
        "feature_snapshot",
        "order_book_snapshot",
    ):
        mismatches.append("input_kind")
    for field_name in ("target", "horizon", "data_version", "source"):
        value = getattr(snapshot, field_name)
        if not isinstance(value, str) or not value.strip():
            mismatches.append(field_name)
    if snapshot.snapshot_id != snapshot.expected_snapshot_id():
        mismatches.append("snapshot_id")
    if snapshot.content_hash != actual_hash:
        mismatches.append("content_hash")
    if snapshot.payload_size_bytes != actual_size:
        mismatches.append("payload_size_bytes")
    if snapshot.input_kind == "analysis_request" or "target" in snapshot.payload:
        payload_target = snapshot.payload.get("target")
        if not isinstance(payload_target, str) or snapshot.target != payload_target:
            mismatches.append("target")
    if snapshot.input_kind == "analysis_request" or "horizon" in snapshot.payload:
        payload_horizon = snapshot.payload.get("horizon", "1h")
        if not isinstance(payload_horizon, str) or snapshot.horizon != payload_horizon:
            mismatches.append("horizon")
    if mismatches:
        raise InputIntegrityError(
            f"input snapshot {snapshot.snapshot_id} failed integrity checks: "
            f"{', '.join(mismatches)}",
            actual_content_hash=actual_hash,
            actual_payload_size_bytes=actual_size,
        )


def _reference_mismatches(
    reference: InputReference,
    expected_reference: InputReference,
) -> list[str]:
    mismatches: list[str] = []
    for field_name in (
        "reference_id",
        "snapshot_id",
        "input_kind",
        "content_hash",
        "data_version",
        "source",
        "target",
        "horizon",
        "payload_size_bytes",
        "schema_version",
    ):
        if getattr(reference, field_name) != getattr(expected_reference, field_name):
            mismatches.append(field_name)
    return mismatches
