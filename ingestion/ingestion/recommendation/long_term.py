"""Long-term (fundamentals/valuation) composite scoring — pure functions, no
I/O. jobs/recommendation_engine.py owns fetching per-instrument data from
fundamentals_quarterly/fundamental_ratios/shareholding_pattern/
consensus_ratings/corporate_actions/relative_strength and shaping it into the
`inputs` dict score_long_term() expects; see recommendation/aggregate.py for
the shared NULL-vs-0 weighted-average discipline every component follows.
"""

from .aggregate import ComponentResult, aggregate_components

WEIGHTS = {
    "eps_growth": 0.25,
    "valuation_pe": 0.15,
    "shareholding_trend": 0.20,
    "consensus_signal": 0.20,
    "corporate_actions_signal": 0.10,
    "relative_strength_long": 0.10,
}
assert abs(sum(WEIGHTS.values()) - 1.0) < 1e-9

_CONSENSUS_BUCKET_SCORE = {
    "STRONG_BUY": 2.0,
    "BUY": 1.0,
    "HOLD": 0.0,
    "SELL": -1.0,
    "STRONG_SELL": -2.0,
}


def _eps_growth(growth_pct: float | None, basis: str | None) -> tuple[float | None, dict]:
    """growth_pct: YoY preferred, QoQ fallback (basis records which one the
    job used) — job returns None when fewer than 2 comparable quarters have
    been filed yet, e.g. a recent listing or Phase 3a's board-meeting-driven
    filing cadence not having reached this instrument yet."""
    if growth_pct is None:
        return None, {"reason": "fewer than 2 comparable fundamentals_quarterly periods"}
    if growth_pct >= 20:
        score = 2.0
    elif growth_pct >= 10:
        score = 1.0
    elif growth_pct >= 0:
        score = 0.5
    elif growth_pct >= -10:
        score = -0.5
    else:
        score = -1.5
    return score, {"eps_growth_pct": growth_pct, "basis": basis}


def _valuation_pe(pe_ratio: float | None) -> tuple[float | None, dict]:
    """None here already means "no P/E" (loss-making or no data) per
    fundamental_ratios.compute_pe_ratio's own None-on-non-positive-EPS
    convention — nothing further to distinguish at this layer."""
    if pe_ratio is None or pe_ratio <= 0:
        return None, {"reason": "no P/E (loss-making or not yet computed)"}
    if pe_ratio <= 15:
        score = 1.0
    elif pe_ratio <= 25:
        score = 0.5
    elif pe_ratio <= 40:
        score = 0.0
    elif pe_ratio <= 60:
        score = -0.5
    else:
        score = -1.0
    return score, {"pe_ratio": pe_ratio}


def _shareholding_trend(current: dict | None, previous: dict | None) -> tuple[float | None, dict]:
    """current/previous: {"promoter_pct", "fii_pct", "pledged_promoter_pct"}
    from the latest and next-most-recent shareholding_pattern rows. fii_pct
    is best-effort per Domain 3 (dimensional XBRL, may be NULL even when
    promoter_pct is present) — handled as an independently-optional part of
    this component, not an all-or-nothing requirement."""
    if current is None or previous is None:
        return None, {"reason": "fewer than 2 shareholding_pattern periods"}

    parts = []
    detail = {}
    if current.get("promoter_pct") is not None and previous.get("promoter_pct") is not None:
        delta = current["promoter_pct"] - previous["promoter_pct"]
        parts.append(1.0 if delta > 0.1 else (-1.0 if delta < -0.1 else 0.0))
        detail["promoter_pct_delta"] = delta
    if current.get("fii_pct") is not None and previous.get("fii_pct") is not None:
        delta = current["fii_pct"] - previous["fii_pct"]
        parts.append(0.5 if delta > 0.1 else (-0.5 if delta < -0.1 else 0.0))
        detail["fii_pct_delta"] = delta

    if not parts:
        return None, {"reason": "promoter_pct/fii_pct not comparable across the two periods"}

    score = sum(parts)
    if current.get("pledged_promoter_pct") is not None and previous.get("pledged_promoter_pct") is not None:
        pledge_delta = current["pledged_promoter_pct"] - previous["pledged_promoter_pct"]
        if pledge_delta > 1.0:
            score -= 1.0
            detail["pledged_promoter_pct_delta"] = pledge_delta

    return max(-2.0, min(2.0, score)), detail


def _consensus_signal(bucket: str | None, implied_upside_pct: float | None) -> tuple[float | None, dict]:
    if bucket is None or bucket not in _CONSENSUS_BUCKET_SCORE:
        return None, {"reason": "no consensus_ratings coverage for this instrument"}

    score = _CONSENSUS_BUCKET_SCORE[bucket]
    if implied_upside_pct is not None:
        if implied_upside_pct >= 20:
            score += 0.5
        elif implied_upside_pct <= -10:
            score -= 0.5
    return max(-2.0, min(2.0, score)), {"consensus_rating_bucket": bucket, "implied_upside_pct": implied_upside_pct}


def _corporate_actions_signal(action_types: list[str]) -> tuple[float, dict]:
    """action_types: corporate_actions.action_type values in the trailing 12
    months. Always a real 0.0 (never None) when empty — no actions is a
    valid observation, not missing data."""
    _POINTS = {"BUYBACK": 1.0, "BONUS": 0.5, "RIGHTS": -1.0}
    total = sum(_POINTS.get(t, 0.0) for t in action_types)
    return max(-2.0, min(2.0, total)), {"action_types": action_types}


def _relative_strength_long(rs_rating: float | None, return_1y: float | None) -> tuple[float | None, dict]:
    if rs_rating is None:
        return None, {"reason": "no relative_strength row for this instrument/date"}

    if rs_rating >= 80:
        base = 1.5
    elif rs_rating >= 60:
        base = 0.75
    elif rs_rating >= 40:
        base = 0.0
    elif rs_rating >= 20:
        base = -0.75
    else:
        base = -1.5

    adjustment = 0.0
    if return_1y is not None:
        if base > 0 and return_1y > 0:
            adjustment = 0.5
        elif base < 0 and return_1y < 0:
            adjustment = -0.5

    return max(-2.0, min(2.0, base + adjustment)), {"rs_rating": rs_rating, "return_1y": return_1y}


def score_long_term(inputs: dict) -> dict:
    """inputs keys: eps_growth_pct (float|None), eps_growth_basis (str|None),
    pe_ratio (float|None), shareholding_current (dict|None),
    shareholding_previous (dict|None), consensus_rating_bucket (str|None),
    implied_upside_pct (float|None), corporate_action_types (list[str]),
    rs_rating_1y (float|None), return_1y (float|None). Returns the
    aggregate.py rationale dict."""
    eps_score, eps_detail = _eps_growth(inputs.get("eps_growth_pct"), inputs.get("eps_growth_basis"))
    pe_score, pe_detail = _valuation_pe(inputs.get("pe_ratio"))
    shareholding_score, shareholding_detail = _shareholding_trend(
        inputs.get("shareholding_current"), inputs.get("shareholding_previous")
    )
    consensus_score, consensus_detail = _consensus_signal(
        inputs.get("consensus_rating_bucket"), inputs.get("implied_upside_pct")
    )
    actions_score, actions_detail = _corporate_actions_signal(inputs.get("corporate_action_types", []))
    rs_score, rs_detail = _relative_strength_long(inputs.get("rs_rating_1y"), inputs.get("return_1y"))

    components = [
        ComponentResult("eps_growth", eps_score, WEIGHTS["eps_growth"], eps_detail),
        ComponentResult("valuation_pe", pe_score, WEIGHTS["valuation_pe"], pe_detail),
        ComponentResult(
            "shareholding_trend", shareholding_score, WEIGHTS["shareholding_trend"], shareholding_detail
        ),
        ComponentResult("consensus_signal", consensus_score, WEIGHTS["consensus_signal"], consensus_detail),
        ComponentResult(
            "corporate_actions_signal", actions_score, WEIGHTS["corporate_actions_signal"], actions_detail
        ),
        ComponentResult(
            "relative_strength_long", rs_score, WEIGHTS["relative_strength_long"], rs_detail
        ),
    ]
    return aggregate_components(components)
