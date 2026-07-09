import unittest

from market_cell.data import (
    ProviderReliabilitySummary,
    ProviderSelectionPolicy,
    ProviderSelectionPreference,
    SourceProfile,
)


class ProviderSelectionTests(unittest.TestCase):
    def test_policy_prefers_professional_healthy_provider(self):
        profiles = [
            _profile("coinapi", "professional"),
            _profile("binance_spot", "exchange_direct"),
            _profile("local_json", "development"),
        ]
        reliabilities = [
            _reliability("coinapi", 94),
            _reliability("binance_spot", 96),
            _reliability("local_json", 100),
        ]

        plan = ProviderSelectionPolicy().select(profiles, reliabilities)

        self.assertEqual(plan.primary.provider, "coinapi")
        self.assertEqual([candidate.provider for candidate in plan.backups], ["binance_spot", "local_json"])
        self.assertIn("tier_professional", plan.primary.reason_codes)

    def test_policy_can_apply_business_priority_and_preferred_bonus(self):
        profiles = [
            _profile("coinapi", "professional"),
            _profile("kaiko", "professional"),
        ]
        reliabilities = [
            _reliability("coinapi", 95),
            _reliability("kaiko", 95),
        ]
        preference = ProviderSelectionPreference(
            preferred_providers=["kaiko"],
            provider_priorities={"kaiko": 2},
        )

        plan = ProviderSelectionPolicy().select(profiles, reliabilities, preference)

        self.assertEqual(plan.primary.provider, "kaiko")
        self.assertIn("preferred_provider", plan.primary.reason_codes)
        self.assertIn("business_priority", plan.primary.reason_codes)

    def test_policy_disables_explicitly_disabled_and_unhealthy_providers(self):
        profiles = [
            _profile("kaiko", "professional"),
            _profile("broken_source", "professional"),
            _profile("disabled_source", "professional"),
        ]
        reliabilities = [
            _reliability("kaiko", 92),
            _reliability("broken_source", 60),
            _reliability("disabled_source", 99),
        ]
        preference = ProviderSelectionPreference(disabled_providers=["disabled_source"], min_health_score=70)

        plan = ProviderSelectionPolicy().select(profiles, reliabilities, preference)

        self.assertEqual(plan.primary.provider, "kaiko")
        disabled = {candidate.provider: candidate for candidate in plan.disabled}
        self.assertIn("health_below_minimum", disabled["broken_source"].reason_codes)
        self.assertIn("disabled_by_preference", disabled["disabled_source"].reason_codes)

    def test_policy_disables_provider_with_recent_health_drop(self):
        profiles = [
            _profile("stable_provider", "professional"),
            _profile("recently_degraded", "professional"),
        ]
        reliabilities = [
            _reliability("stable_provider", 90),
            _reliability(
                "recently_degraded",
                average_score=94,
                latest_score=60,
                worst_score=60,
            ),
        ]

        plan = ProviderSelectionPolicy().select(profiles, reliabilities)

        self.assertEqual(plan.primary.provider, "stable_provider")
        self.assertEqual(plan.disabled[0].provider, "recently_degraded")
        self.assertIn("latest_health_below_minimum", plan.disabled[0].reason_codes)

    def test_policy_can_disable_sources_missing_configured_api_key(self):
        profiles = [
            _profile("kaiko", "professional", requires_api_key=True),
            _profile("binance_spot", "exchange_direct"),
        ]
        preference = ProviderSelectionPreference(available_api_key_providers=[])

        plan = ProviderSelectionPolicy().select(profiles, preference=preference)

        self.assertEqual(plan.primary.provider, "binance_spot")
        self.assertEqual(plan.disabled[0].provider, "kaiko")
        self.assertIn("missing_api_key", plan.disabled[0].reason_codes)

    def test_policy_respects_required_realtime_support(self):
        profiles = [
            _profile("historical_only", "professional", supports_realtime=False),
            _profile("streaming_source", "exchange_direct", supports_realtime=True),
        ]
        preference = ProviderSelectionPreference(required_realtime=True)

        plan = ProviderSelectionPolicy().select(profiles, preference=preference)

        self.assertEqual(plan.primary.provider, "streaming_source")
        self.assertEqual(plan.disabled[0].provider, "historical_only")
        self.assertIn("missing_realtime_support", plan.disabled[0].reason_codes)

    def test_policy_marks_unknown_health_without_blocking_by_default(self):
        profiles = [_profile("new_provider", "professional")]

        plan = ProviderSelectionPolicy().select(profiles)

        self.assertEqual(plan.primary.provider, "new_provider")
        self.assertIsNone(plan.primary.health_score)
        self.assertIn("unknown_health", plan.primary.reason_codes)
        self.assertEqual(plan.primary.score_components["health"], 80)


def _profile(
    provider: str,
    tier: str,
    *,
    supports_realtime: bool = False,
    supports_history: bool = True,
    requires_api_key: bool = False,
) -> SourceProfile:
    return SourceProfile(
        provider=provider,
        tier=tier,
        description=f"{provider} profile",
        supports_realtime=supports_realtime,
        supports_history=supports_history,
        requires_api_key=requires_api_key,
    )


def _reliability(
    provider: str,
    score: float | None = None,
    *,
    average_score: float | None = None,
    latest_score: float | None = None,
    worst_score: float | None = None,
) -> ProviderReliabilitySummary:
    average = average_score if average_score is not None else score
    latest = latest_score if latest_score is not None else score
    worst = worst_score if worst_score is not None else score
    if average is None or latest is None or worst is None:
        raise ValueError("reliability score is required")
    return ProviderReliabilitySummary(
        source_provider=provider,
        trend_point_count=1,
        record_count=1,
        average_health_score=average,
        latest_health_score=latest,
        worst_health_score=worst,
        health_grade="good",
    )


if __name__ == "__main__":
    unittest.main()
