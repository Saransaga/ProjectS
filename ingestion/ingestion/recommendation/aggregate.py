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


def aggregate_components(components: list[ComponentResult]) -> dict:
    """Weighted average over components with subscore is not None. Returns
    the exact rationale shape stored in stock_recommendations.*_rationale:
    {weighted_score, available_weight, insufficient_data, components: [...]}.
    weighted_score is None whenever insufficient_data is True — the caller
    (recommendation_engine.py) must not call bucketize() in that case."""
    total_weight = sum(c.weight for c in components)
    available = [c for c in components if c.subscore is not None]
    available_weight = sum(c.weight for c in available)
    fraction = (available_weight / total_weight) if total_weight else 0.0
    insufficient = fraction < MIN_AVAILABLE_WEIGHT_FRACTION

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
