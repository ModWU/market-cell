from __future__ import annotations

from dataclasses import asdict, dataclass, field
from typing import Any, Literal


CELL_GRAPH_DEFINITION_SCHEMA_VERSION = "cell_graph_definition.v1"


GraphNodeRole = Literal["leaf", "aggregator", "root"]


@dataclass(frozen=True)
class CellGraphNode:
    node_id: str
    cell_id: str
    execution_role: GraphNodeRole
    dependencies: list[str] = field(default_factory=list)
    metadata: dict[str, Any] = field(default_factory=dict)


@dataclass(frozen=True)
class CellOrganDefinition:
    organ_id: str
    organ_version: str
    name: str
    node_ids: list[str]
    output_node_ids: list[str]
    description: str = ""
    metadata: dict[str, Any] = field(default_factory=dict)


@dataclass(frozen=True)
class CellGraphDefinition:
    graph_id: str
    graph_version: str
    name: str
    root_node_id: str
    nodes: list[CellGraphNode]
    organs: list[CellOrganDefinition] = field(default_factory=list)
    description: str = ""
    schema_version: str = CELL_GRAPH_DEFINITION_SCHEMA_VERSION
    metadata: dict[str, Any] = field(default_factory=dict)

    def to_dict(self) -> dict[str, Any]:
        return asdict(self)

    def to_run_metadata(self) -> dict[str, Any]:
        return {"cell_graph_definition": self.to_dict()}
