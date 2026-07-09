import json
import unittest
from pathlib import Path

from market_cell.engine import AnalysisEngine
from market_cell.models import AnalysisRequest, Candle


ROOT = Path(__file__).resolve().parents[3]


class ContractTests(unittest.TestCase):
    def test_json_contracts_are_valid_json(self):
        contract_paths = sorted((ROOT / "contracts" / "json_schema").glob("*.schema.json"))

        self.assertGreaterEqual(len(contract_paths), 2)
        for path in contract_paths:
            with self.subTest(path=path.name):
                data = json.loads(path.read_text(encoding="utf-8"))
                self.assertEqual(data["$schema"], "https://json-schema.org/draft/2020-12/schema")
                self.assertIn("title", data)

    def test_market_data_contracts_exist_for_realtime_and_batch_paths(self):
        proto = (ROOT / "contracts" / "protobuf" / "market_data.proto").read_text(encoding="utf-8")
        parquet = (ROOT / "contracts" / "parquet" / "candle_schema.md").read_text(encoding="utf-8")

        self.assertIn("package market_cell.market_data.v1", proto)
        self.assertIn("message MarketDataEvent", proto)
        self.assertIn("message CandleClosed", proto)
        self.assertIn("source_provider", parquet)
        self.assertIn("quality_flags", parquet)

    def test_analysis_report_contains_contract_required_fields(self):
        schema = json.loads(
            (ROOT / "contracts" / "json_schema" / "analysis_report.schema.json").read_text(encoding="utf-8")
        )
        request = AnalysisRequest(
            target="BTC/USD",
            horizon="1h",
            candles=[
                Candle("t1", open=100, high=101, low=99, close=100, volume=1000),
                Candle("t2", open=100, high=102, low=99, close=101, volume=1200),
            ],
        )

        report = AnalysisEngine().run(request).to_dict()

        for field_name in schema["required"]:
            with self.subTest(field_name=field_name):
                self.assertIn(field_name, report)


if __name__ == "__main__":
    unittest.main()
