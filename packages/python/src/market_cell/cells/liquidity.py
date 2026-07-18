from __future__ import annotations

from dataclasses import dataclass
from typing import Literal

from market_cell.cells.base import MarketCell
from market_cell.data import OrderBookLevel, OrderBookSnapshot
from market_cell.inputs import CellInputBundle, InputCompositionError
from market_cell.models import AnalysisRequest, CellResult, Evidence
from market_cell.scoring import clamp, score


DEPTH_WINDOW_BPS = 100.0
MINIMUM_LEVELS_PER_SIDE = 3
DIRECTIONAL_IMBALANCE_THRESHOLD = 0.18
TIGHT_SPREAD_BPS = 5.0
NORMAL_SPREAD_BPS = 15.0
FRAGILE_SPREAD_BPS = 30.0
CONCENTRATION_GUARD_THRESHOLD = 0.72
MAX_ACCEPTABLE_FETCH_LATENCY_MS = 1_000
SINGLE_SNAPSHOT_CONFIDENCE_CAP = 88.0


@dataclass(frozen=True)
class _SideDepth:
    quote_notional: float
    level_count: int
    concentration: float


class LiquidityCell(MarketCell):
    cell_id = "microstructure.liquidity"
    name = "LiquidityCell"
    category = "microstructure"
    description = (
        "分析单一订单簿快照的近端点差、双侧深度、失衡和集中度，"
        "识别短时流动性方向与脆弱性。"
    )
    formula_version = "order_book_depth_spread_imbalance_v0.1"
    required_input_kinds = ["analysis_request", "order_book_snapshot"]
    inputs = [
        "analysis_request.target",
        "analysis_request.horizon",
        "order_book_snapshot.bids",
        "order_book_snapshot.asks",
        "order_book_snapshot.provenance",
    ]
    outputs = [
        "direction",
        "strength",
        "confidence",
        "volatility_risk",
        "liquidity_state",
        "spread_bps",
        "depth_imbalance",
        "depth_concentration",
    ]
    risk_dimensions = ["volatility_risk"]
    status = "experimental"

    def analyze_inputs(
        self,
        inputs: CellInputBundle,
        child_results: list[CellResult] | None = None,
    ) -> CellResult:
        order_book = OrderBookSnapshot.from_input_snapshot(
            inputs.require_one("order_book_snapshot")
        )
        return self._analyze_order_book(inputs.analysis_request, order_book)

    def analyze(
        self,
        request: AnalysisRequest,
        child_results: list[CellResult] | None = None,
    ) -> CellResult:
        raise InputCompositionError(
            "LiquidityCell requires a typed order_book_snapshot; "
            "execute it through analyze_inputs"
        )

    def _analyze_order_book(
        self,
        request: AnalysisRequest,
        order_book: OrderBookSnapshot,
    ) -> CellResult:
        if order_book.target != request.target:
            raise InputCompositionError(
                "LiquidityCell order-book target does not match analysis request"
            )

        bid_depth = _side_depth(
            order_book.bids,
            mid_price=order_book.mid_price,
            side="bid",
        )
        ask_depth = _side_depth(
            order_book.asks,
            mid_price=order_book.mid_price,
            side="ask",
        )
        total_depth = bid_depth.quote_notional + ask_depth.quote_notional
        depth_imbalance = (
            (bid_depth.quote_notional - ask_depth.quote_notional) / total_depth
            if total_depth
            else 0.0
        )
        maximum_concentration = max(
            bid_depth.concentration,
            ask_depth.concentration,
        )
        fetch_latency_ms = (
            order_book.provenance.fetched_at_ms
            - order_book.provenance.event_time_ms
        )
        quality_flags = list(order_book.provenance.quality_flags)
        input_degraded = bool(quality_flags) or not (
            0 <= fetch_latency_ms <= MAX_ACCEPTABLE_FETCH_LATENCY_MS
        )
        spread_band = _spread_band(order_book.spread_bps)
        state, direction = _classify_liquidity(
            bid_level_count=bid_depth.level_count,
            ask_level_count=ask_depth.level_count,
            depth_imbalance=depth_imbalance,
            spread_bps=order_book.spread_bps,
            maximum_concentration=maximum_concentration,
            input_degraded=input_degraded,
        )
        active_guards = _active_guards(
            bid_level_count=bid_depth.level_count,
            ask_level_count=ask_depth.level_count,
            spread_bps=order_book.spread_bps,
            maximum_concentration=maximum_concentration,
            fetch_latency_ms=fetch_latency_ms,
            quality_flags=quality_flags,
        )
        volatility_risk = _volatility_risk(
            spread_bps=order_book.spread_bps,
            minimum_level_count=min(
                bid_depth.level_count,
                ask_depth.level_count,
            ),
            maximum_concentration=maximum_concentration,
            fetch_latency_ms=fetch_latency_ms,
            quality_flags=quality_flags,
        )
        confidence = _confidence(
            bid_level_count=bid_depth.level_count,
            ask_level_count=ask_depth.level_count,
            spread_bps=order_book.spread_bps,
            maximum_concentration=maximum_concentration,
            sequence=order_book.provenance.sequence,
            fetch_latency_ms=fetch_latency_ms,
            state=state,
        )
        strength = _strength(
            direction=direction,
            depth_imbalance=depth_imbalance,
            volatility_risk=volatility_risk,
        )

        return CellResult(
            cell_id=self.cell_id,
            name=self.name,
            category=self.category,
            target=request.target,
            horizon=request.horizon,
            direction=direction,
            strength=strength,
            confidence=confidence,
            volatility_risk=volatility_risk,
            manipulation_risk=0,
            urgency=round(
                max(volatility_risk, strength if direction == "conflict" else strength * 0.6),
                4,
            ),
            score=score(direction, strength, confidence),
            explanation=_explanation(
                state=state,
                spread_bps=order_book.spread_bps,
                depth_imbalance=depth_imbalance,
                bid_depth_notional=bid_depth.quote_notional,
                ask_depth_notional=ask_depth.quote_notional,
                quality_flags=quality_flags,
            ),
            evidence=[
                Evidence(
                    source="order_book.depth_100bps",
                    summary=(
                        f"bid_notional={bid_depth.quote_notional:.4f}, "
                        f"ask_notional={ask_depth.quote_notional:.4f}, "
                        f"imbalance={depth_imbalance:.4f}, "
                        f"levels={bid_depth.level_count}/{ask_depth.level_count}"
                    ),
                    reliability=confidence,
                ),
                Evidence(
                    source="order_book.spread_concentration",
                    summary=(
                        f"spread={order_book.spread_bps:.4f}bps ({spread_band}), "
                        f"concentration={bid_depth.concentration:.4f}/"
                        f"{ask_depth.concentration:.4f}"
                    ),
                    reliability=confidence,
                ),
                Evidence(
                    source="order_book.provenance",
                    summary=(
                        f"provider={order_book.provenance.source_provider}, "
                        f"venue={order_book.provenance.venue}, "
                        f"sequence={order_book.provenance.sequence}, "
                        f"fetch_latency_ms={fetch_latency_ms}, "
                        f"quality_flags={quality_flags}"
                    ),
                    freshness=_freshness_from_latency(fetch_latency_ms),
                    reliability=40 if input_degraded else 90,
                ),
            ],
            metadata={
                "formula_version": self.formula_version,
                "liquidity_state": state,
                "depth_window_bps": DEPTH_WINDOW_BPS,
                "depth_unit": "quote_notional",
                "mid_price": round(order_book.mid_price, 8),
                "spread_bps": round(order_book.spread_bps, 4),
                "spread_band": spread_band,
                "bid_depth_notional": round(bid_depth.quote_notional, 4),
                "ask_depth_notional": round(ask_depth.quote_notional, 4),
                "depth_imbalance": round(depth_imbalance, 6),
                "bid_level_count": bid_depth.level_count,
                "ask_level_count": ask_depth.level_count,
                "bid_depth_concentration": round(
                    bid_depth.concentration,
                    6,
                ),
                "ask_depth_concentration": round(
                    ask_depth.concentration,
                    6,
                ),
                "maximum_side_concentration": round(
                    maximum_concentration,
                    6,
                ),
                "minimum_levels_per_side": MINIMUM_LEVELS_PER_SIDE,
                "directional_imbalance_threshold": (
                    DIRECTIONAL_IMBALANCE_THRESHOLD
                ),
                "concentration_guard_threshold": (
                    CONCENTRATION_GUARD_THRESHOLD
                ),
                "tight_spread_threshold_bps": TIGHT_SPREAD_BPS,
                "normal_spread_threshold_bps": NORMAL_SPREAD_BPS,
                "fragile_spread_threshold_bps": FRAGILE_SPREAD_BPS,
                "single_snapshot_confidence_cap": (
                    SINGLE_SNAPSHOT_CONFIDENCE_CAP
                ),
                "source_provider": order_book.provenance.source_provider,
                "venue": order_book.provenance.venue,
                "market_type": order_book.provenance.market_type,
                "provenance_sequence": order_book.provenance.sequence,
                "source_event_id": order_book.provenance.source_event_id,
                "event_time_ms": order_book.provenance.event_time_ms,
                "fetched_at_ms": order_book.provenance.fetched_at_ms,
                "fetch_latency_ms": fetch_latency_ms,
                "quality_flags": quality_flags,
                "input_degraded": input_degraded,
                "active_guards": active_guards,
                "manipulation_inference": "not_supported_by_single_snapshot",
            },
        )


def _side_depth(
    levels: list[OrderBookLevel],
    *,
    mid_price: float,
    side: Literal["bid", "ask"],
) -> _SideDepth:
    if side == "bid":
        included = [
            level
            for level in levels
            if (mid_price - level.price) / mid_price * 10_000
            <= DEPTH_WINDOW_BPS
        ]
    else:
        included = [
            level
            for level in levels
            if (level.price - mid_price) / mid_price * 10_000
            <= DEPTH_WINDOW_BPS
        ]
    notionals = [level.price * level.quantity for level in included]
    quote_notional = sum(notionals)
    concentration = (
        max(notionals, default=0.0) / quote_notional
        if quote_notional
        else 0.0
    )
    return _SideDepth(
        quote_notional=quote_notional,
        level_count=len(included),
        concentration=concentration,
    )


def _classify_liquidity(
    *,
    bid_level_count: int,
    ask_level_count: int,
    depth_imbalance: float,
    spread_bps: float,
    maximum_concentration: float,
    input_degraded: bool,
) -> tuple[str, str]:
    if min(bid_level_count, ask_level_count) < MINIMUM_LEVELS_PER_SIDE:
        return "insufficient_depth", "neutral"
    if input_degraded:
        return "degraded_input", "neutral"
    if spread_bps >= FRAGILE_SPREAD_BPS:
        return "fragile_wide_spread", "conflict"
    if maximum_concentration >= CONCENTRATION_GUARD_THRESHOLD:
        return "concentrated_depth", "conflict"
    if depth_imbalance >= DIRECTIONAL_IMBALANCE_THRESHOLD:
        return "bid_heavy", "bullish"
    if depth_imbalance <= -DIRECTIONAL_IMBALANCE_THRESHOLD:
        return "ask_heavy", "bearish"
    return "balanced", "neutral"


def _spread_band(spread_bps: float) -> str:
    if spread_bps <= TIGHT_SPREAD_BPS:
        return "tight"
    if spread_bps <= NORMAL_SPREAD_BPS:
        return "normal"
    if spread_bps < FRAGILE_SPREAD_BPS:
        return "elevated"
    return "fragile"


def _active_guards(
    *,
    bid_level_count: int,
    ask_level_count: int,
    spread_bps: float,
    maximum_concentration: float,
    fetch_latency_ms: int,
    quality_flags: list[str],
) -> list[str]:
    guards: list[str] = []
    if min(bid_level_count, ask_level_count) < MINIMUM_LEVELS_PER_SIDE:
        guards.append("insufficient_depth")
    if quality_flags:
        guards.append("quality_flags")
    if fetch_latency_ms < 0:
        guards.append("invalid_fetch_latency")
    elif fetch_latency_ms > MAX_ACCEPTABLE_FETCH_LATENCY_MS:
        guards.append("delayed_fetch")
    if spread_bps >= FRAGILE_SPREAD_BPS:
        guards.append("wide_spread")
    if maximum_concentration >= CONCENTRATION_GUARD_THRESHOLD:
        guards.append("concentrated_depth")
    return guards


def _volatility_risk(
    *,
    spread_bps: float,
    minimum_level_count: int,
    maximum_concentration: float,
    fetch_latency_ms: int,
    quality_flags: list[str],
) -> float:
    spread_risk = clamp(spread_bps / FRAGILE_SPREAD_BPS * 60)
    if minimum_level_count < MINIMUM_LEVELS_PER_SIDE:
        depth_risk = clamp(
            60 + (MINIMUM_LEVELS_PER_SIDE - minimum_level_count) * 20
        )
    else:
        depth_risk = clamp((5 - minimum_level_count) * 8)
    concentration_risk = clamp(maximum_concentration * 100)
    quality_risk = 60.0 if quality_flags else 0.0
    latency_risk = (
        60.0
        if not 0 <= fetch_latency_ms <= MAX_ACCEPTABLE_FETCH_LATENCY_MS
        else clamp((fetch_latency_ms - 250) / 750 * 35)
    )
    return round(
        max(
            spread_risk,
            depth_risk,
            concentration_risk,
            quality_risk,
            latency_risk,
        ),
        4,
    )


def _confidence(
    *,
    bid_level_count: int,
    ask_level_count: int,
    spread_bps: float,
    maximum_concentration: float,
    sequence: int | None,
    fetch_latency_ms: int,
    state: str,
) -> float:
    minimum_level_count = min(bid_level_count, ask_level_count)
    if state == "insufficient_depth":
        return round(min(25.0, 12.0 + minimum_level_count * 5.0), 4)

    confidence = (
        44.0
        + min(minimum_level_count, 10) * 3.2
        + min(bid_level_count + ask_level_count, 20) * 0.6
    )
    if spread_bps > NORMAL_SPREAD_BPS:
        confidence -= 5.0
    if spread_bps >= FRAGILE_SPREAD_BPS:
        confidence -= 8.0
    if maximum_concentration >= CONCENTRATION_GUARD_THRESHOLD:
        confidence -= 8.0
    if sequence is None:
        confidence -= 3.0
    if 250 < fetch_latency_ms <= MAX_ACCEPTABLE_FETCH_LATENCY_MS:
        confidence -= 5.0
    if state == "degraded_input":
        confidence = min(confidence, 35.0)
    return round(
        clamp(confidence, maximum=SINGLE_SNAPSHOT_CONFIDENCE_CAP),
        4,
    )


def _strength(
    *,
    direction: str,
    depth_imbalance: float,
    volatility_risk: float,
) -> float:
    imbalance_strength = clamp(abs(depth_imbalance) * 100)
    if direction in {"bullish", "bearish"}:
        return round(imbalance_strength, 4)
    if direction == "conflict":
        return round(max(imbalance_strength, volatility_risk), 4)
    return 0.0


def _freshness_from_latency(fetch_latency_ms: int) -> float:
    if fetch_latency_ms < 0:
        return 0.0
    return round(clamp(100 - fetch_latency_ms / 20), 4)


def _explanation(
    *,
    state: str,
    spread_bps: float,
    depth_imbalance: float,
    bid_depth_notional: float,
    ask_depth_notional: float,
    quality_flags: list[str],
) -> str:
    state_text = {
        "insufficient_depth": "近端双侧有效档位不足，不能形成可靠方向判断",
        "degraded_input": (
            "数据质量或抓取延迟未通过防护，盘口方向信号已降级为中性"
        ),
        "fragile_wide_spread": (
            "点差进入脆弱区间，即使深度失衡也不输出强方向"
        ),
        "concentrated_depth": (
            "近端深度被单一大档位主导，孤立挂单墙不足以确认方向"
        ),
        "bid_heavy": "近端买方深度分布式占优，短时盘口承接偏多",
        "ask_heavy": "近端卖方深度分布式占优，短时盘口压力偏空",
        "balanced": "近端双侧深度基本均衡，盘口方向保持中性",
    }[state]
    quality_text = f"，质量标记={quality_flags}" if quality_flags else ""
    return (
        f"{state_text}。100bps 内买/卖深度名义额为 "
        f"{bid_depth_notional:.2f}/{ask_depth_notional:.2f}，"
        f"失衡 {depth_imbalance:.3f}，点差 {spread_bps:.2f}bps"
        f"{quality_text}。该结论只描述单一快照，不用于推断 spoofing 或操纵。"
    )
