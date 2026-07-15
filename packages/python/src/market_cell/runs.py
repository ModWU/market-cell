from __future__ import annotations

from copy import deepcopy
from dataclasses import asdict, dataclass, field, replace
from typing import Any
from uuid import uuid4

from market_cell import __version__
from market_cell.events import utc_now_iso
from market_cell.hashing import stable_json_hash
from market_cell.inputs.models import InputSnapshot
from market_cell.models import AnalysisRequest, CellManifest


RUN_SCHEMA_VERSION = "analysis_run.v1"


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
    ) -> "AnalysisRun":
        if replay_input is not None:
            if replay_input.input_kind != "analysis_request":
                raise ValueError("AnalysisRun replay input must be an analysis_request")
            if (
                replay_input.target != request.target
                or replay_input.horizon != request.horizon
            ):
                raise ValueError("AnalysisRun replay input does not match the request scope")
            snapshot = deepcopy(replay_input.payload)
            input_hash = replay_input.content_hash
        else:
            snapshot = request_to_snapshot(request)
            input_hash = stable_json_hash(snapshot)
        return cls(
            run_id=uuid4().hex,
            target=request.target,
            horizon=request.horizon,
            engine_version=__version__,
            input_hash=input_hash,
            input_snapshot=snapshot,
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
