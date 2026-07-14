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
    def __init__(self, cells: Sequence[MarketCell]) -> None:
        self._cells = tuple(cells)
        registration_counts = Counter(cell.cell_id for cell in self._cells)
        duplicate_ids = sorted(
            cell_id for cell_id, count in registration_counts.items() if count > 1
        )
        if duplicate_ids:
            raise DuplicateCellRegistrationError(
                f"duplicate local cell registrations: {', '.join(duplicate_ids)}"
            )
        self._cells_by_id = {cell.cell_id: cell for cell in self._cells}

    def all_cells(self) -> list[MarketCell]:
        return list(self._cells)

    def manifests(self) -> list[CellManifest]:
        return [cell.manifest() for cell in self._cells]

    def resolve(self, cell_id: str) -> MarketCell:
        try:
            return self._cells_by_id[cell_id]
        except KeyError as exc:
            raise CellNotRegisteredError(
                f"no local Cell implementation registered for {cell_id}"
            ) from exc


def default_registry(decision_policy: DecisionPolicy | None = None) -> CellRegistry:
    return CellRegistry(
        [
            TrendCell(),
            VolumeCell(),
            VolatilityCell(),
            MarketRegimeCell(),
            NewsEventCell(),
            ManipulationRiskCell(),
            DecisionCell(policy=decision_policy),
        ],
    )
