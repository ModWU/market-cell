import argparse
import json
import sys
from pathlib import Path

from market_cell.engine import AnalysisEngine
from market_cell.horizons import (
    HorizonDecisionCell,
    MultiHorizonAnalyzer,
    MultiHorizonRequest,
)
from market_cell.models import AnalysisRequest
from market_cell.performance import run_performance_benchmark
from market_cell.registry import default_registry
from market_cell.replay import ReplayRunner
from market_cell.reports import FileSystemReportStore


def create_parser() -> argparse.ArgumentParser:
    parser = argparse.ArgumentParser(prog="market-cell", description="MarketCell backend analysis CLI.")
    subparsers = parser.add_subparsers(dest="command", required=True)

    analyze = subparsers.add_parser("analyze", help="Run an analysis request from a JSON file.")
    analyze.add_argument("file", type=Path, help="Path to the analysis input JSON.")
    analyze.add_argument("--pretty", action="store_true", help="Pretty-print JSON output.")
    analyze.add_argument("--save", action="store_true", help="Save report and run metadata for replay.")
    analyze.add_argument("--report-dir", type=Path, default=Path("reports"), help="Report storage directory.")

    analyze_multi = subparsers.add_parser(
        "analyze-multi",
        help="Run an ordered multi-horizon request from a JSON file.",
    )
    analyze_multi.add_argument(
        "file",
        type=Path,
        help="Path to the multi-horizon input JSON.",
    )
    analyze_multi.add_argument(
        "--pretty",
        action="store_true",
        help="Pretty-print JSON output.",
    )
    analyze_multi.add_argument(
        "--save",
        action="store_true",
        help="Save every child horizon report and run for replay.",
    )
    analyze_multi.add_argument(
        "--decide",
        action="store_true",
        help=(
            "Apply the versioned HorizonDecisionCell after all horizons "
            "succeed."
        ),
    )
    analyze_multi.add_argument(
        "--report-dir",
        type=Path,
        default=Path("reports"),
        help="Child report storage directory.",
    )

    cells = subparsers.add_parser("cells", help="List registered MarketCell analyzers.")
    cells.add_argument("--pretty", action="store_true", help="Pretty-print JSON output.")

    reports = subparsers.add_parser("reports", help="List saved report IDs.")
    reports.add_argument("--report-dir", type=Path, default=Path("reports"), help="Report storage directory.")
    reports.add_argument("--pretty", action="store_true", help="Pretty-print JSON output.")

    replay = subparsers.add_parser("replay", help="Replay a saved report from its input snapshot.")
    replay.add_argument("report_id", help="Saved report ID.")
    replay.add_argument("--report-dir", type=Path, default=Path("reports"), help="Report storage directory.")
    replay.add_argument("--stored-only", action="store_true", help="Only print the stored report without rerunning.")
    replay.add_argument("--pretty", action="store_true", help="Pretty-print JSON output.")

    benchmark = subparsers.add_parser(
        "benchmark",
        help="Run a versioned fixed-input performance baseline.",
    )
    benchmark.add_argument(
        "baseline",
        nargs="?",
        type=Path,
        default=Path("benchmarks/default_analysis.json"),
        help="Path to the performance baseline JSON.",
    )
    benchmark.add_argument(
        "--output",
        type=Path,
        help="Optional path for the benchmark result JSON.",
    )
    benchmark.add_argument(
        "--pretty",
        action="store_true",
        help="Pretty-print JSON output.",
    )

    return parser


def load_request(path: Path) -> AnalysisRequest:
    data = json.loads(path.read_text(encoding="utf-8"))
    return AnalysisRequest.from_dict(data)


def load_multi_horizon_request(path: Path) -> MultiHorizonRequest:
    data = json.loads(path.read_text(encoding="utf-8"))
    return MultiHorizonRequest.from_dict(data)


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

    if args.command == "analyze-multi":
        try:
            request = load_multi_horizon_request(args.file)
            store = FileSystemReportStore(args.report_dir) if args.save else None
            analysis = MultiHorizonAnalyzer(
                engine_factory=lambda _: AnalysisEngine(report_store=store)
            ).run(request)
            output = (
                HorizonDecisionCell().analyze(analysis)
                if args.decide
                else analysis
            )
        except Exception as exc:
            print(f"多周期分析失败：{exc}", file=sys.stderr)
            return 1

        indent = 2 if args.pretty else None
        print(json.dumps(output.to_dict(), ensure_ascii=False, indent=indent))
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
        store = FileSystemReportStore(args.report_dir)
        try:
            if args.stored_only:
                output = store.load_report(args.report_id)
            else:
                output = ReplayRunner(store).replay(args.report_id).to_dict()
        except Exception as exc:
            print(f"回放报告失败：{exc}", file=sys.stderr)
            return 1

        indent = 2 if args.pretty else None
        print(json.dumps(output, ensure_ascii=False, indent=indent))
        return 0

    if args.command == "benchmark":
        try:
            result = run_performance_benchmark(args.baseline)
        except Exception as exc:
            print(f"性能基准失败：{exc}", file=sys.stderr)
            return 1

        indent = 2 if args.pretty else None
        output = json.dumps(result.to_dict(), ensure_ascii=False, indent=indent)
        if args.output is not None:
            args.output.parent.mkdir(parents=True, exist_ok=True)
            args.output.write_text(output + "\n", encoding="utf-8")
        print(output)
        if result.correctness_failures:
            return 2
        if result.performance_failures:
            return 3
        return 0

    parser.print_help()
    return 1
