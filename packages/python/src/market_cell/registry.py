from market_cell.cells import (
    DecisionCell,
    ManipulationRiskCell,
    MarketRegimeCell,
    NewsEventCell,
    TrendCell,
    VolatilityCell,
    VolumeCell,
)
from market_cell.cells.base import MarketCell
from market_cell.models import CellManifest
from market_cell.policies import DecisionPolicy


class CellRegistry:
    def __init__(self, leaf_cells: list[MarketCell], decision_cell: MarketCell) -> None:
        self.leaf_cells = leaf_cells
        self.decision_cell = decision_cell

    def all_cells(self) -> list[MarketCell]:
        return [*self.leaf_cells, self.decision_cell]

    def manifests(self) -> list[CellManifest]:
        return [cell.manifest() for cell in self.all_cells()]


def default_registry(decision_policy: DecisionPolicy | None = None) -> CellRegistry:
    return CellRegistry(
        leaf_cells=[
            TrendCell(),
            VolumeCell(),
            VolatilityCell(),
            MarketRegimeCell(),
            NewsEventCell(),
            ManipulationRiskCell(),
        ],
        decision_cell=DecisionCell(policy=decision_policy),
    )
