import argparse
import json
import sys
from pathlib import Path

from market_cell.engine import AnalysisEngine
from market_cell.models import AnalysisRequest
from market_cell.registry import default_registry
from market_cell.reports import FileSystemReportStore


def create_parser() -> argparse.ArgumentParser:
    parser = argparse.ArgumentParser(prog="market-cell", description="MarketCell backend analysis CLI.")
    subparsers = parser.add_subparsers(dest="command", required=True)

    analyze = subparsers.add_parser("analyze", help="Run an analysis request from a JSON file.")
    analyze.add_argument("file", type=Path, help="Path to the analysis input JSON.")
    analyze.add_argument("--pretty", action="store_true", help="Pretty-print JSON output.")
    analyze.add_argument("--save", action="store_true", help="Save report and run metadata for replay.")
    analyze.add_argument("--report-dir", type=Path, default=Path("reports"), help="Report storage directory.")

    cells = subparsers.add_parser("cells", help="List registered MarketCell analyzers.")
    cells.add_argument("--pretty", action="store_true", help="Pretty-print JSON output.")

    reports = subparsers.add_parser("reports", help="List saved report IDs.")
    reports.add_argument("--report-dir", type=Path, default=Path("reports"), help="Report storage directory.")
    reports.add_argument("--pretty", action="store_true", help="Pretty-print JSON output.")

    replay = subparsers.add_parser("replay", help="Print a saved report by report ID.")
    replay.add_argument("report_id", help="Saved report ID.")
    replay.add_argument("--report-dir", type=Path, default=Path("reports"), help="Report storage directory.")
    replay.add_argument("--pretty", action="store_true", help="Pretty-print JSON output.")

    return parser


def load_request(path: Path) -> AnalysisRequest:
    data = json.loads(path.read_text(encoding="utf-8"))
    return AnalysisRequest.from_dict(data)


def main(argv: list[str] | None = None) -> int:
    parser = create_parser()
    args = parser.parse_args(argv)

    if args.command == "analyze":
        try:
            request = load_request(args.file)
            store = FileSystemReportStore(args.report_dir) if args.save else None
            report = AnalysisEngine(report_store=store).run(request)
        except Exception as exc:
            print(f"分析失败：{exc}", file=sys.stderr)
            return 1

        indent = 2 if args.pretty else None
        print(json.dumps(report.to_dict(), ensure_ascii=False, indent=indent))
        return 0

    if args.command == "cells":
        indent = 2 if args.pretty else None
        manifests = [manifest.__dict__ for manifest in default_registry().manifests()]
        print(json.dumps(manifests, ensure_ascii=False, indent=indent))
        return 0

    if args.command == "reports":
        indent = 2 if args.pretty else None
        reports = FileSystemReportStore(args.report_dir).list_reports()
        print(json.dumps(reports, ensure_ascii=False, indent=indent))
        return 0

    if args.command == "replay":
        try:
            report = FileSystemReportStore(args.report_dir).load_report(args.report_id)
        except Exception as exc:
            print(f"读取报告失败：{exc}", file=sys.stderr)
            return 1

        indent = 2 if args.pretty else None
        print(json.dumps(report, ensure_ascii=False, indent=indent))
        return 0

    parser.print_help()
    return 1
