from __future__ import annotations

from copy import deepcopy
from dataclasses import asdict, dataclass, field, replace
from typing import Any
from uuid import uuid4

from market_cell import __version__
from market_cell.events import utc_now_iso
from market_cell.inputs.models import InputSnapshot
from market_cell.models import AnalysisRequest, CellManifest


RUN_SCHEMA_VERSION = "analysis_run.v2"


def request_to_snapshot(request: AnalysisRequest) -> dict[str, Any]:
    return asdict(request)


def manifests_to_dicts(manifests: list[CellManifest]) -> list[dict[str, Any]]:
    return [asdict(manifest) for manifest in manifests]


def formula_versions(manifests: list[CellManifest]) -> dict[str, str]:
    return {manifest.cell_id: manifest.formula_version for manifest in manifests}


@dataclass(frozen=True)
class AnalysisRun:
    run_id: str
    target: str
    horizon: str
    engine_version: str
    input_hash: str
    input_snapshot: dict[str, Any]
    input_snapshots: list[dict[str, Any]]
    formula_versions: dict[str, str]
    cell_manifests: list[dict[str, Any]]
    status: str
    started_at: str
    schema_version: str = RUN_SCHEMA_VERSION
    finished_at: str | None = None
    report_id: str | None = None
    error: str | None = None
    metadata: dict[str, Any] = field(default_factory=dict)

    @classmethod
    def start(
        cls,
        request: AnalysisRequest,
        manifests: list[CellManifest],
        metadata: dict[str, Any] | None = None,
        *,
        replay_input: InputSnapshot | None = None,
        replay_inputs: list[InputSnapshot] | None = None,
    ) -> "AnalysisRun":
        if replay_input is not None and replay_inputs is not None:
            raise ValueError("provide replay_input or replay_inputs, not both")
        inputs = list(replay_inputs) if replay_inputs is not None else [
            replay_input or InputSnapshot.from_analysis_request(request)
        ]
        if not inputs:
            raise ValueError("AnalysisRun requires at least one input snapshot")
        if len({item.snapshot_id for item in inputs}) != len(inputs):
            raise ValueError("AnalysisRun input snapshot ids must be unique")
        input_kinds = [item.input_kind for item in inputs]
        if len(input_kinds) != len(set(input_kinds)):
            raise ValueError("AnalysisRun input kinds must be unique")
        request_inputs = [
            item for item in inputs if item.input_kind == "analysis_request"
        ]
        if len(request_inputs) != 1:
            raise ValueError(
                "AnalysisRun requires exactly one analysis_request input snapshot"
            )
        primary_input = request_inputs[0]
        for item in inputs:
            if item.target != request.target or item.horizon != request.horizon:
                raise ValueError(
                    "AnalysisRun input snapshot does not match the request scope"
                )
        if primary_input.payload != request_to_snapshot(request):
            raise ValueError(
                "AnalysisRun analysis_request snapshot does not match the request payload"
            )
        snapshot = deepcopy(primary_input.payload)
        input_hash = primary_input.content_hash
        return cls(
            run_id=uuid4().hex,
            target=request.target,
            horizon=request.horizon,
            engine_version=__version__,
            input_hash=input_hash,
            input_snapshot=snapshot,
            input_snapshots=[deepcopy(item.to_dict()) for item in inputs],
            formula_versions=formula_versions(manifests),
            cell_manifests=manifests_to_dicts(manifests),
            status="running",
            schema_version=RUN_SCHEMA_VERSION,
            started_at=utc_now_iso(),
            metadata=deepcopy(metadata or {}),
        )

    def complete(self, report_id: str) -> "AnalysisRun":
        return replace(self, status="succeeded", finished_at=utc_now_iso(), report_id=report_id)

    def fail(self, error: str) -> "AnalysisRun":
        return replace(self, status="failed", finished_at=utc_now_iso(), error=error)

    def with_metadata(self, metadata: dict[str, Any]) -> "AnalysisRun":
        payload = deepcopy(self.metadata)
        payload.update(deepcopy(metadata))
        return replace(self, metadata=payload)

    def to_dict(self) -> dict[str, Any]:
        return asdict(self)
