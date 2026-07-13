from __future__ import annotations

import json
from pathlib import Path
from typing import Protocol

from market_cell.models import AnalysisReport
from market_cell.runs import AnalysisRun


class ReportStore(Protocol):
    def save(self, report: AnalysisReport, run: AnalysisRun) -> str:
        ...

    def load_report(self, report_id: str) -> dict:
        ...

    def load_run(self, run_id: str) -> dict:
        ...

    def save_run(self, run: AnalysisRun) -> str:
        ...


class FileSystemReportStore:
    def __init__(self, root: Path | str = "reports") -> None:
        self.root = Path(root)
        self.reports_dir = self.root / "reports"
        self.runs_dir = self.root / "runs"

    def save(self, report: AnalysisReport, run: AnalysisRun) -> str:
        report_id = report.report_id or run.run_id
        self.reports_dir.mkdir(parents=True, exist_ok=True)

        self._write_json(self.reports_dir / f"{report_id}.json", report.to_dict())
        self.save_run(run)
        return report_id

    def save_run(self, run: AnalysisRun) -> str:
        self.runs_dir.mkdir(parents=True, exist_ok=True)
        self._write_json(self.runs_dir / f"{run.run_id}.json", run.to_dict())
        return run.run_id

    def load_report(self, report_id: str) -> dict:
        return self._read_json(self.reports_dir / f"{report_id}.json")

    def load_run(self, run_id: str) -> dict:
        return self._read_json(self.runs_dir / f"{run_id}.json")

    def list_reports(self) -> list[str]:
        if not self.reports_dir.exists():
            return []
        return sorted(path.stem for path in self.reports_dir.glob("*.json"))

    @staticmethod
    def _write_json(path: Path, data: dict) -> None:
        path.write_text(json.dumps(data, ensure_ascii=False, indent=2), encoding="utf-8")

    @staticmethod
    def _read_json(path: Path) -> dict:
        return json.loads(path.read_text(encoding="utf-8"))
