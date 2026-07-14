from collections import Counter
from collections.abc import Sequence

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


class DuplicateCellRegistrationError(ValueError):
    pass


class CellNotRegisteredError(LookupError):
    pass


class CellRegistry:
    def __init__(
        self,
        leaf_cells: Sequence[MarketCell],
        decision_cell: MarketCell,
    ) -> None:
        self.leaf_cells = tuple(leaf_cells)
        self.decision_cell = decision_cell
        cells = self.all_cells()
        registration_counts = Counter(cell.cell_id for cell in cells)
        duplicate_ids = sorted(
            cell_id for cell_id, count in registration_counts.items() if count > 1
        )
        if duplicate_ids:
            raise DuplicateCellRegistrationError(
                f"duplicate local cell registrations: {', '.join(duplicate_ids)}"
            )
        self._cells_by_id = {cell.cell_id: cell for cell in cells}

    def all_cells(self) -> list[MarketCell]:
        return [*self.leaf_cells, self.decision_cell]

    def manifests(self) -> list[CellManifest]:
        return [cell.manifest() for cell in self.all_cells()]

    def resolve(self, cell_id: str) -> MarketCell:
        try:
            return self._cells_by_id[cell_id]
        except KeyError as exc:
            raise CellNotRegisteredError(
                f"no local Cell implementation registered for {cell_id}"
            ) from exc


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
