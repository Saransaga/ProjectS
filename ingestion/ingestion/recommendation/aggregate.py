"""Shared weighted-average aggregation for short_term.py/long_term.py — pure,
no I/O. See this domain's plan doc for the NULL-vs-0 discipline this
implements: a component's subscore is None only when its source data
genuinely doesn't exist (excluded from the weighted average entirely, not
counted as a 0), and 0.0 is a real "nothing notable happened" value that
must not be mistaken for missing data.

IMPORTANT: callers must never test a subscore with plain truthiness
(`if subscore:`) — that would treat a legitimate 0.0 as falsy/missing and
silently drop it from the weighted average. Always branch on
`subscore is not None`.
"""

from dataclasses import dataclass, field

# Below this fraction of the weight budget having real data, the composite
# is left NULL entirely rather than computed from a mostly-missing picture.
MIN_AVAILABLE_WEIGHT_FRACTION = 0.5


@dataclass
class ComponentResult:
    name: str
    subscore: float | None  # None = genuinely no data; 0.0 = computed, nothing notable
    weight: float
    detail: dict = field(default_factory=dict)
    # False for a component that isn't instrument-specific (e.g. short_term.py's
    # fii_dii_market_flow — one market-wide value shared by every instrument
    # that day). Such a component still contributes to weighted_score when
    # available, but must not count toward "do we have enough *real,
    # per-instrument* signal" — it's always available regardless of whether
    # this particular instrument has any actual data, so counting it toward
    # the gate would let a stock with zero real technical/fundamental
    # coverage still clear MIN_AVAILABLE_WEIGHT_FRACTION on market noise
    # alone (caught live: 120 instruments with no technicals/RS/F&O at all
    # still got a "confident" short-term action before this was added).
    counts_toward_gate: bool = True


def aggregate_components(components: list[ComponentResult]) -> dict:
    """Weighted average over components with subscore is not None. Returns
    the exact rationale shape stored in stock_recommendations.*_rationale:
    {weighted_score, available_weight, insufficient_data, components: [...]}.
    weighted_score is None whenever insufficient_data is True — the caller
    (recommendation_engine.py) must not call bucketize() in that case.

    insufficient_data/available_weight are computed only from
    counts_toward_gate components — see ComponentResult's docstring — so a
    non-instrument-specific overlay can't single-handedly clear the gate for
    an instrument with no real per-instrument data; weighted_score itself
    still uses every available component (gating or not)."""
    gating = [c for c in components if c.counts_toward_gate]
    total_gate_weight = sum(c.weight for c in gating)
    available_gate_weight = sum(c.weight for c in gating if c.subscore is not None)
    fraction = (available_gate_weight / total_gate_weight) if total_gate_weight else 0.0
    insufficient = fraction < MIN_AVAILABLE_WEIGHT_FRACTION

    available = [c for c in components if c.subscore is not None]
    available_weight = sum(c.weight for c in available)
    weighted_score = None
    if not insufficient and available_weight > 0:
        weighted_score = sum(c.subscore * c.weight for c in available) / available_weight

    return {
        "weighted_score": weighted_score,
        "available_weight": round(fraction, 3),
        "insufficient_data": insufficient,
        "components": [
            {
                "name": c.name,
                "subscore": c.subscore,
                "weight": c.weight,
                "weighted": (c.subscore * c.weight) if c.subscore is not None else None,
                "detail": c.detail,
            }
            for c in components
        ],
    }
