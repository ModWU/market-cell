from __future__ import annotations

import hashlib
import json
from dataclasses import asdict, dataclass, field, replace
from typing import Any
from uuid import uuid4

from market_cell import __version__
from market_cell.events import utc_now_iso
from market_cell.models import AnalysisRequest, CellManifest


def stable_json_hash(data: dict[str, Any]) -> str:
    raw = json.dumps(data, ensure_ascii=False, sort_keys=True, separators=(",", ":"))
    return hashlib.sha256(raw.encode("utf-8")).hexdigest()


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
    finished_at: str | None = None
    report_id: str | None = None
    error: str | None = None
    metadata: dict[str, Any] = field(default_factory=dict)

    @classmethod
    def start(cls, request: AnalysisRequest, manifests: list[CellManifest]) -> "AnalysisRun":
        snapshot = request_to_snapshot(request)
        return cls(
            run_id=uuid4().hex,
            target=request.target,
            horizon=request.horizon,
            engine_version=__version__,
            input_hash=stable_json_hash(snapshot),
            input_snapshot=snapshot,
            formula_versions=formula_versions(manifests),
            cell_manifests=manifests_to_dicts(manifests),
            status="running",
            started_at=utc_now_iso(),
        )

    def complete(self, report_id: str) -> "AnalysisRun":
        return replace(self, status="succeeded", finished_at=utc_now_iso(), report_id=report_id)

    def fail(self, error: str) -> "AnalysisRun":
        return replace(self, status="failed", finished_at=utc_now_iso(), error=error)

    def to_dict(self) -> dict[str, Any]:
        return asdict(self)
