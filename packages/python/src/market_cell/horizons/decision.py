from __future__ import annotations

from market_cell.events import utc_now_iso
from market_cell.hashing import stable_json_hash
from market_cell.horizons.decision_models import (
    HorizonDecision,
    HorizonSignal,
)
from market_cell.horizons.models import MultiHorizonAnalysis
from market_cell.horizons.policy import (
    HorizonDecisionAssessment,
    HorizonDecisionPolicy,
)
from market_cell.models import Evidence


class HorizonDecisionCell:
    """Aggregate a complete MultiHorizonAnalysis outside the single-horizon DAG."""

    cell_id = "horizon.decision"
    name = "HorizonDecisionCell"
    category = "decision"
    description = (
        "按周期层级、结构权威、冲突类型和风险覆盖形成多周期判断。"
    )
    status = "experimental"
    input_schema_versions = ["multi_horizon_analysis.v1"]
    output_schema_version = "horizon_decision.v1"

    def __init__(self, policy: HorizonDecisionPolicy | None = None) -> None:
        self.policy = policy or HorizonDecisionPolicy()
        self.formula_version = self.policy.formula_version

    def analyze(self, analysis: MultiHorizonAnalysis) -> HorizonDecision:
        if not isinstance(analysis, MultiHorizonAnalysis):
            raise TypeError(
                "HorizonDecisionCell requires MultiHorizonAnalysis"
            )
        signals = self._signals(analysis)
        assessment = self.policy.evaluate(signals)
        decision_hash = stable_json_hash(
            self.identity_payload(
                analysis,
                signals=signals,
                assessment=assessment,
            )
        )
        decision_id = f"horizon-decision:{decision_hash[:24]}"
        weights = self.policy.signal_weights(signals)
        evidence = [
            Evidence(
                source=f"horizon:{signal.horizon}",
                summary=(
                    f"{self.policy.band_for(signal.horizon)} / "
                    f"{signal.horizon}: direction={signal.direction}, "
                    f"score={signal.score:.3f}, "
                    f"confidence={signal.confidence:.1f}, "
                    f"risk=({signal.volatility_risk:.1f}, "
                    f"{signal.manipulation_risk:.1f})"
                ),
                weight=weights[signal.horizon],
                freshness=100,
                reliability=signal.confidence,
            )
            for signal in signals
        ]
        return HorizonDecision(
            decision_id=decision_id,
            decision_hash=decision_hash,
            source_batch_id=analysis.batch_id,
            request_id=analysis.request_id,
            request_hash=analysis.request_hash,
            target=analysis.target,
            as_of_ms=analysis.as_of_ms,
            horizon_order=list(analysis.horizon_order),
            source_signals=signals,
            direction=assessment.direction,
            structural_direction=assessment.structural_direction,
            structural_score=assessment.structural_score,
            strength=assessment.strength,
            confidence=assessment.confidence,
            volatility_risk=assessment.volatility_risk,
            manipulation_risk=assessment.manipulation_risk,
            urgency=assessment.urgency,
            risk_level=assessment.risk_level,
            action_posture=assessment.action_posture,
            risk_breakdown=dict(assessment.risk_breakdown),
            alignment_status=assessment.alignment_status,
            conflict_type=assessment.conflict_type,
            conflict_score=assessment.conflict_score,
            band_decisions=assessment.band_decisions,
            evidence=evidence,
            explanation=assessment.explanation,
            source_graph_id=analysis.graph_id,
            source_graph_version=analysis.graph_version,
            source_graph_content_hash=analysis.graph_content_hash,
            source_formula_versions=dict(analysis.formula_versions),
            policy=self.policy.identity_payload(),
            formula_version=self.formula_version,
            created_at=utc_now_iso(),
            metadata={
                "source_aggregation_status": analysis.aggregation_status,
            },
        )

    def identity_payload(
        self,
        analysis: MultiHorizonAnalysis,
        *,
        signals: list[HorizonSignal] | None = None,
        assessment: HorizonDecisionAssessment | None = None,
    ) -> dict[str, object]:
        normalized = signals or self._signals(analysis)
        result = assessment or self.policy.evaluate(normalized)
        return {
            "source_schema_version": analysis.schema_version,
            "request_hash": analysis.request_hash,
            "target": analysis.target,
            "as_of_ms": analysis.as_of_ms,
            "horizon_order": list(analysis.horizon_order),
            "graph_id": analysis.graph_id,
            "graph_version": analysis.graph_version,
            "graph_content_hash": analysis.graph_content_hash,
            "source_formula_versions": dict(analysis.formula_versions),
            "signals": [item.identity_payload() for item in normalized],
            "policy": self.policy.identity_payload(),
            "decision": {
                "direction": result.direction,
                "structural_direction": result.structural_direction,
                "structural_score": result.structural_score,
                "strength": result.strength,
                "confidence": result.confidence,
                "volatility_risk": result.volatility_risk,
                "manipulation_risk": result.manipulation_risk,
                "urgency": result.urgency,
                "risk_level": result.risk_level,
                "action_posture": result.action_posture,
                "alignment_status": result.alignment_status,
                "conflict_type": result.conflict_type,
                "conflict_score": result.conflict_score,
                "band_decisions": [
                    item.to_dict() for item in result.band_decisions
                ],
                "risk_breakdown": dict(result.risk_breakdown),
            },
        }

    def _signals(
        self,
        analysis: MultiHorizonAnalysis,
    ) -> list[HorizonSignal]:
        return [
            HorizonSignal(
                horizon=report.horizon,
                direction=report.decision.direction,
                score=report.decision.score,
                strength=report.decision.strength,
                confidence=report.decision.confidence,
                volatility_risk=report.decision.volatility_risk,
                manipulation_risk=report.decision.manipulation_risk,
            )
            for report in analysis.reports
        ]
