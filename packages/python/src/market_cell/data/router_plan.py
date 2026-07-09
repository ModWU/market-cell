from __future__ import annotations

from dataclasses import asdict, dataclass
from typing import Any

from market_cell.data.provider_selection import (
    ProviderSelectionCandidate,
    ProviderSelectionPlan,
    ProviderSelectionPolicy,
    ProviderSelectionPreference,
)
from market_cell.data.health import ProviderReliabilitySummary
from market_cell.data.sources import CandleSource, MarketDataRouter


@dataclass(frozen=True)
class RouterPlanEntry:
    provider: str
    role: str
    selection_score: float
    reason_codes: list[str]
    source: CandleSource
    candidate: ProviderSelectionCandidate

    def to_dict(self) -> dict[str, Any]:
        return {
            "provider": self.provider,
            "role": self.role,
            "selection_score": self.selection_score,
            "reason_codes": list(self.reason_codes),
            "profile": asdict(self.candidate.profile),
            "candidate": self.candidate.to_dict(),
        }


@dataclass(frozen=True)
class RouterPlan:
    entries: list[RouterPlanEntry]
    disabled: list[ProviderSelectionCandidate]
    missing_providers: list[str]
    ignored_providers: list[str]

    @property
    def ordered_sources(self) -> list[CandleSource]:
        return [entry.source for entry in self.entries]

    def to_router(self) -> MarketDataRouter:
        if not self.entries:
            raise ValueError("没有可用于路由的数据源")
        return MarketDataRouter(self.ordered_sources)

    def to_dict(self) -> dict[str, Any]:
        return {
            "entries": [entry.to_dict() for entry in self.entries],
            "disabled": [candidate.to_dict() for candidate in self.disabled],
            "missing_providers": list(self.missing_providers),
            "ignored_providers": list(self.ignored_providers),
        }


class RouterPlanBuilder:
    def build(
        self,
        sources: list[CandleSource],
        selection_plan: ProviderSelectionPlan,
    ) -> RouterPlan:
        source_by_provider = _source_map(sources)
        active_candidates = [
            candidate
            for candidate in ([selection_plan.primary] if selection_plan.primary is not None else [])
            + selection_plan.backups
        ]

        entries: list[RouterPlanEntry] = []
        missing_providers: list[str] = []
        for candidate in active_candidates:
            source = source_by_provider.get(candidate.provider)
            if source is None:
                missing_providers.append(candidate.provider)
                continue
            entries.append(
                RouterPlanEntry(
                    provider=candidate.provider,
                    role=candidate.role,
                    selection_score=candidate.selection_score,
                    reason_codes=candidate.reason_codes,
                    source=source,
                    candidate=candidate,
                )
            )

        planned_providers = {candidate.provider for candidate in active_candidates + selection_plan.disabled}
        ignored_providers = sorted(provider for provider in source_by_provider if provider not in planned_providers)

        return RouterPlan(
            entries=entries,
            disabled=selection_plan.disabled,
            missing_providers=sorted(missing_providers),
            ignored_providers=ignored_providers,
        )

    def build_from_sources(
        self,
        sources: list[CandleSource],
        reliabilities: list[ProviderReliabilitySummary] | None = None,
        preference: ProviderSelectionPreference | None = None,
        policy: ProviderSelectionPolicy | None = None,
    ) -> RouterPlan:
        selection_policy = policy or ProviderSelectionPolicy()
        selection_plan = selection_policy.select(
            profiles=[source.profile for source in sources],
            reliabilities=reliabilities,
            preference=preference,
        )
        return self.build(sources, selection_plan)


def _source_map(sources: list[CandleSource]) -> dict[str, CandleSource]:
    source_by_provider: dict[str, CandleSource] = {}
    duplicates: list[str] = []
    for source in sources:
        provider = source.profile.provider
        if provider in source_by_provider:
            duplicates.append(provider)
            continue
        source_by_provider[provider] = source
    if duplicates:
        raise ValueError("数据源 provider 必须唯一：" + ", ".join(sorted(set(duplicates))))
    return source_by_provider
