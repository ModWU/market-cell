from abc import ABC, abstractmethod

from market_cell.inputs import CellInputBundle
from market_cell.models import AnalysisRequest, CellManifest, CellResult


class MarketCell(ABC):
    cell_id: str
    name: str
    category: str
    description: str = ""
    formula_version: str = "unknown"
    inputs: list[str] = []
    required_input_kinds: list[str] = ["analysis_request"]
    outputs: list[str] = []
    risk_dimensions: list[str] = []
    status: str = "experimental"

    def manifest(self) -> CellManifest:
        return CellManifest(
            cell_id=self.cell_id,
            name=self.name,
            category=self.category,
            description=self.description,
            inputs=list(self.inputs),
            outputs=list(self.outputs),
            formula_version=self.formula_version,
            required_input_kinds=list(self.required_input_kinds),
            risk_dimensions=list(self.risk_dimensions),
            status=self.status,
        )

    def analyze_inputs(
        self,
        inputs: CellInputBundle,
        child_results: list[CellResult] | None = None,
    ) -> CellResult:
        """Analyze typed inputs while preserving the request-based Cell API."""
        return self.analyze(inputs.analysis_request, child_results)

    @abstractmethod
    def analyze(self, request: AnalysisRequest, child_results: list[CellResult] | None = None) -> CellResult:
        """Analyze a request and return one normalized CellResult."""
