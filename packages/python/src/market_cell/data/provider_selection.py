from __future__ import annotations

from dataclasses import asdict, dataclass, field
from typing import Any, Literal

from market_cell.data.health import ProviderReliabilitySummary
from market_cell.data.sources import SourceProfile


ProviderRole = Literal["primary", "backup", "disabled"]


@dataclass(frozen=True)
class ProviderSelectionPreference:
    preferred_providers: list[str] = field(default_factory=list)
    disabled_providers: list[str] = field(default_factory=list)
    available_api_key_providers: list[str] | None = None
    provider_priorities: dict[str, float] = field(default_factory=dict)
    min_health_score: float = 70.0
    required_history: bool = True
    required_realtime: bool = False


@dataclass(frozen=True)
class ProviderSelectionCandidate:
    provider: str
    tier: str
    role: ProviderRole
    selection_score: float
    health_score: float | None
    business_priority: float
    score_components: dict[str, float]
    reason_codes: list[str]
    profile: SourceProfile
    reliability: ProviderReliabilitySummary | None = None

    def to_dict(self) -> dict[str, Any]:
        payload = asdict(self)
        payload["profile"] = asdict(self.profile)
        payload["reliability"] = self.reliability.to_dict() if self.reliability is not None else None
        return payload


@dataclass(frozen=True)
class ProviderSelectionPlan:
    primary: ProviderSelectionCandidate | None
    backups: list[ProviderSelectionCandidate]
    disabled: list[ProviderSelectionCandidate]
    candidates: list[ProviderSelectionCandidate]

    def to_dict(self) -> dict[str, Any]:
        return {
            "primary": self.primary.to_dict() if self.primary is not None else None,
            "backups": [candidate.to_dict() for candidate in self.backups],
            "disabled": [candidate.to_dict() for candidate in self.disabled],
            "candidates": [candidate.to_dict() for candidate in self.candidates],
        }


class ProviderSelectionPolicy:
    def __init__(
        self,
        tier_weights: dict[str, float] | None = None,
        unknown_health_score: float = 80.0,
        preferred_bonus: float = 5.0,
    ) -> None:
        self.tier_weights = tier_weights or {
            "professional": 12.0,
            "exchange_direct": 6.0,
            "development": 0.0,
        }
        self.unknown_health_score = unknown_health_score
        self.preferred_bonus = preferred_bonus

    def select(
        self,
        profiles: list[SourceProfile],
        reliabilities: list[ProviderReliabilitySummary] | None = None,
        preference: ProviderSelectionPreference | None = None,
    ) -> ProviderSelectionPlan:
        preference = preference or ProviderSelectionPreference()
        reliability_by_provider = {item.source_provider: item for item in reliabilities or []}

        candidates = [
            self._candidate(profile, reliability_by_provider.get(profile.provider), preference)
            for profile in profiles
        ]
        enabled = sorted(
            [candidate for candidate in candidates if candidate.role != "disabled"],
            key=lambda item: (-item.selection_score, item.provider),
        )
        disabled = sorted(
            [candidate for candidate in candidates if candidate.role == "disabled"],
            key=lambda item: (item.provider, -item.selection_score),
        )

        primary = enabled[0] if enabled else None
        backups = [
            _with_role(candidate, "backup")
            for candidate in enabled[1:]
        ]
        if primary is not None:
            primary = _with_role(primary, "primary")

        return ProviderSelectionPlan(
            primary=primary,
            backups=backups,
            disabled=disabled,
            candidates=[candidate for candidate in ([primary] if primary is not None else []) + backups + disabled],
        )

    def _candidate(
        self,
        profile: SourceProfile,
        reliability: ProviderReliabilitySummary | None,
        preference: ProviderSelectionPreference,
    ) -> ProviderSelectionCandidate:
        reason_codes: list[str] = []
        disabled = False

        if profile.provider in preference.disabled_providers:
            disabled = True
            reason_codes.append("disabled_by_preference")
        if preference.required_history and not profile.supports_history:
            disabled = True
            reason_codes.append("missing_history_support")
        if preference.required_realtime and not profile.supports_realtime:
            disabled = True
            reason_codes.append("missing_realtime_support")
        if (
            profile.requires_api_key
            and preference.available_api_key_providers is not None
            and profile.provider not in preference.available_api_key_providers
        ):
            disabled = True
            reason_codes.append("missing_api_key")

        health_score = _selection_health_score(reliability) if reliability is not None else None
        effective_health = health_score if health_score is not None else self.unknown_health_score
        if health_score is None:
            reason_codes.append("unknown_health")
        if effective_health < preference.min_health_score:
            disabled = True
            reason_codes.append("health_below_minimum")
        if reliability is not None and reliability.latest_health_score < preference.min_health_score:
            disabled = True
            reason_codes.append("latest_health_below_minimum")

        tier_bonus = self.tier_weights.get(profile.tier, 0.0)
        business_priority = preference.provider_priorities.get(profile.provider, 0.0)
        preferred_bonus = self.preferred_bonus if profile.provider in preference.preferred_providers else 0.0
        if preferred_bonus:
            reason_codes.append("preferred_provider")
        if tier_bonus:
            reason_codes.append(f"tier_{profile.tier}")
        if business_priority:
            reason_codes.append("business_priority")

        score_components = {
            "health": round(effective_health, 6),
            "tier": round(tier_bonus, 6),
            "business_priority": round(business_priority, 6),
            "preferred": round(preferred_bonus, 6),
        }
        score = sum(score_components.values())
        if disabled:
            score_components["disabled_penalty"] = -1_000.0
            score -= 1_000.0

        return ProviderSelectionCandidate(
            provider=profile.provider,
            tier=profile.tier,
            role="disabled" if disabled else "backup",
            selection_score=round(score, 6),
            health_score=round(health_score, 6) if health_score is not None else None,
            business_priority=business_priority,
            score_components=score_components,
            reason_codes=reason_codes,
            profile=profile,
            reliability=reliability,
        )


def _with_role(candidate: ProviderSelectionCandidate, role: ProviderRole) -> ProviderSelectionCandidate:
    return ProviderSelectionCandidate(
        provider=candidate.provider,
        tier=candidate.tier,
        role=role,
        selection_score=candidate.selection_score,
        health_score=candidate.health_score,
        business_priority=candidate.business_priority,
        score_components=candidate.score_components,
        reason_codes=candidate.reason_codes,
        profile=candidate.profile,
        reliability=candidate.reliability,
    )


def _selection_health_score(reliability: ProviderReliabilitySummary) -> float:
    return (
        reliability.average_health_score * 0.5
        + reliability.latest_health_score * 0.35
        + reliability.worst_health_score * 0.15
    )
