from __future__ import annotations

from collections import Counter
from dataclasses import asdict, dataclass, field
from typing import Any, Iterable
from uuid import uuid4

from market_cell.events import utc_now_iso
from market_cell.execution.models import CellServiceBinding
from market_cell.models import CellManifest
from market_cell.registry import CellRegistry


SERVICE_CAPABILITY_CATALOG_SCHEMA_VERSION = "service_capability_catalog.v1"


class CapabilityCatalogError(ValueError):
    pass


@dataclass(frozen=True)
class ServiceCapabilityCatalog:
    catalog_id: str
    bindings: list[CellServiceBinding]
    schema_version: str = SERVICE_CAPABILITY_CATALOG_SCHEMA_VERSION
    generated_at: str = field(default_factory=utc_now_iso)
    metadata: dict[str, Any] = field(default_factory=dict)

    def __post_init__(self) -> None:
        binding_counts = Counter(
            (binding.implementation_id, binding.service_id)
            for binding in self.bindings
        )
        duplicates = sorted(
            binding_key
            for binding_key, count in binding_counts.items()
            if count > 1
        )
        if duplicates:
            labels = [
                f"{implementation_id}@{service_id}"
                for implementation_id, service_id in duplicates
            ]
            raise CapabilityCatalogError(
                f"duplicate implementation/service bindings: {', '.join(labels)}"
            )

    @classmethod
    def create(
        cls,
        bindings: Iterable[CellServiceBinding],
        *,
        catalog_id: str | None = None,
        metadata: dict[str, Any] | None = None,
    ) -> "ServiceCapabilityCatalog":
        return cls(
            catalog_id=catalog_id or uuid4().hex,
            bindings=list(bindings),
            metadata=dict(metadata or {}),
        )

    def candidates_for(self, manifest: CellManifest) -> list[CellServiceBinding]:
        return sorted(
            [
                binding
                for binding in self.bindings
                if binding.cell_id == manifest.cell_id
                and binding.formula_version == manifest.formula_version
            ],
            key=lambda binding: (
                binding.priority,
                binding.implementation_id,
                binding.service_id,
            ),
        )

    def to_dict(self) -> dict[str, Any]:
        return {
            "catalog_id": self.catalog_id,
            "bindings": [asdict(binding) for binding in self.bindings],
            "schema_version": self.schema_version,
            "generated_at": self.generated_at,
            "metadata": dict(self.metadata),
        }


def build_local_capability_catalog(
    registry: CellRegistry,
    service_id: str = "python-local",
) -> ServiceCapabilityCatalog:
    return ServiceCapabilityCatalog.create(
        [build_local_service_binding(manifest, service_id) for manifest in registry.manifests()],
        catalog_id=f"{service_id}:{uuid4().hex}",
        metadata={
            "source": "local_registry",
            "service_id": service_id,
        },
    )


def build_local_service_binding(
    manifest: CellManifest,
    service_id: str = "python-local",
) -> CellServiceBinding:
    return CellServiceBinding(
        implementation_id=_implementation_id(service_id, manifest),
        cell_id=manifest.cell_id,
        service_id=service_id,
        runtime="python_local",
        language="python",
        formula_version=manifest.formula_version,
        task_queue=f"cell.{service_id}",
        capabilities=[manifest.category],
    )


def _implementation_id(service_id: str, manifest: CellManifest) -> str:
    return f"{service_id}:{manifest.cell_id}:{manifest.formula_version}"
