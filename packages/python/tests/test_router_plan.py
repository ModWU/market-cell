import unittest

from market_cell.data import (
    CandleBatch,
    CandleQuery,
    ProviderReliabilitySummary,
    ProviderSelectionPlan,
    ProviderSelectionPolicy,
    ProviderSelectionPreference,
    RouterPlanBuilder,
    SourceProfile,
)
from market_cell.models import Candle


class RouterPlanTests(unittest.TestCase):
    def test_builder_orders_sources_from_provider_selection_plan(self):
        sources = [
            _source("binance_spot", "exchange_direct"),
            _source("kaiko", "professional"),
        ]
        plan = RouterPlanBuilder().build_from_sources(
            sources,
            reliabilities=[
                _reliability("binance_spot", 96),
                _reliability("kaiko", 94),
            ],
        )

        self.assertEqual([entry.provider for entry in plan.entries], ["kaiko", "binance_spot"])
        self.assertIsNotNone(plan.selection_plan)

    def test_router_plan_exports_run_metadata(self):
        plan = RouterPlanBuilder().build_from_sources(
            [
                _source("binance_spot", "exchange_direct"),
                _source("kaiko", "professional"),
            ],
            reliabilities=[
                _reliability("binance_spot", 96),
                _reliability("kaiko", 94),
            ],
        )

        metadata = plan.to_run_metadata()

        self.assertEqual(
            metadata["data_sources"]["router_plan"]["entries"][0]["provider"],
            "kaiko",
        )
        self.assertEqual(
            metadata["data_sources"]["provider_selection_plan"]["primary"]["provider"],
            "kaiko",
        )

    def test_router_uses_ordered_sources_and_falls_back(self):
        empty_primary = _source("kaiko", "professional", candles=[])
        good_backup = _source(
            "binance_spot",
            "exchange_direct",
            candles=[Candle("t1", open=100, high=101, low=99, close=100, volume=10)],
        )
        plan = RouterPlanBuilder().build_from_sources([empty_primary, good_backup])

        batch = plan.to_router().fetch_candles(CandleQuery(symbol="BTC/USD", horizon="1h"))

        self.assertEqual(batch.source.provider, "binance_spot")

    def test_builder_excludes_disabled_sources_from_router_entries(self):
        sources = [
            _source("kaiko", "professional", requires_api_key=True),
            _source("binance_spot", "exchange_direct"),
        ]
        plan = RouterPlanBuilder().build_from_sources(
            sources,
            preference=ProviderSelectionPreference(available_api_key_providers=[]),
        )

        self.assertEqual([entry.provider for entry in plan.entries], ["binance_spot"])
        self.assertEqual([candidate.provider for candidate in plan.disabled], ["kaiko"])
        self.assertEqual([source.profile.provider for source in plan.ordered_sources], ["binance_spot"])

    def test_builder_tracks_missing_selected_provider_implementation(self):
        policy_plan = ProviderSelectionPolicy().select(
            profiles=[
                _profile("kaiko", "professional"),
                _profile("binance_spot", "exchange_direct"),
            ],
            reliabilities=[
                _reliability("kaiko", 95),
                _reliability("binance_spot", 90),
            ],
        )

        plan = RouterPlanBuilder().build([_source("binance_spot", "exchange_direct")], policy_plan)

        self.assertEqual(plan.missing_providers, ["kaiko"])
        self.assertEqual([entry.provider for entry in plan.entries], ["binance_spot"])

    def test_builder_tracks_sources_not_covered_by_plan(self):
        policy_plan = ProviderSelectionPlan(primary=None, backups=[], disabled=[], candidates=[])

        plan = RouterPlanBuilder().build([_source("local_json", "development")], policy_plan)

        self.assertEqual(plan.ignored_providers, ["local_json"])
        with self.assertRaises(ValueError):
            plan.to_router()

    def test_builder_rejects_duplicate_source_providers(self):
        with self.assertRaises(ValueError):
            RouterPlanBuilder().build_from_sources(
                [
                    _source("binance_spot", "exchange_direct"),
                    _source("binance_spot", "exchange_direct"),
                ]
            )


class _StaticSource:
    def __init__(
        self,
        provider: str,
        tier: str,
        *,
        candles: list[Candle] | None = None,
        requires_api_key: bool = False,
    ) -> None:
        self.profile = _profile(provider, tier, requires_api_key=requires_api_key)
        self.candles = (
            candles
            if candles is not None
            else [Candle("t1", open=100, high=101, low=99, close=100, volume=10)]
        )

    def fetch_candles(self, query: CandleQuery) -> CandleBatch:
        return CandleBatch(query=query, candles=self.candles, source=self.profile)


def _source(
    provider: str,
    tier: str,
    *,
    candles: list[Candle] | None = None,
    requires_api_key: bool = False,
) -> _StaticSource:
    return _StaticSource(provider, tier, candles=candles, requires_api_key=requires_api_key)


def _profile(provider: str, tier: str, *, requires_api_key: bool = False) -> SourceProfile:
    return SourceProfile(
        provider=provider,
        tier=tier,
        description=f"{provider} profile",
        requires_api_key=requires_api_key,
    )


def _reliability(provider: str, score: float) -> ProviderReliabilitySummary:
    return ProviderReliabilitySummary(
        source_provider=provider,
        trend_point_count=1,
        record_count=1,
        average_health_score=score,
        latest_health_score=score,
        worst_health_score=score,
        health_grade="good",
    )


if __name__ == "__main__":
    unittest.main()
