"""Urgency and relevance heuristics, plus static per-source credibility
weights. Keyword-based, not a trained classifier — see README."""

_BREAKING_KEYWORDS = {
    "resign", "resigns", "resigned", "resignation", "fraud", "scam", "raid",
    "cbi", "sebi action", "probe", "investigation", "default", "defaulted",
    "bankruptcy", "insolvency", "winding up", "delisting", "delisted",
    "downgrade", "downgraded", "credit rating", "fire", "explosion",
    "accident", "recall", "ban", "banned", "suspended", "suspension",
    "acquisition", "merger", "takeover", "stake sale", "open offer",
    "arrest", "arrested", "scandal", "penalty", "fined",
}

# Static, hand-assigned — official exchange filings are ground truth (1.0),
# established mainstream outlets next, aggregators/social lowest since
# they're unverified or mix in low-quality underlying sources.
SOURCE_CREDIBILITY_WEIGHTS = {
    "NSE_ANNOUNCEMENT": 1.000,
    "BSE_ANNOUNCEMENT": 1.000,
    "RSS_ET_MARKETS": 0.800,
    "RSS_MINT": 0.800,
    "RSS_BUSINESS_STANDARD": 0.800,
    "RSS_MONEYCONTROL_BUSINESS": 0.750,
    "RSS_MONEYCONTROL_MARKETS": 0.750,
    "RSS_GOOGLE_NEWS": 0.600,
    "REDDIT": 0.300,
}
_DEFAULT_CREDIBILITY_WEIGHT = 0.500


def classify_urgency(text: str) -> str:
    lower = text.lower()
    return "BREAKING" if any(kw in lower for kw in _BREAKING_KEYWORDS) else "ROUTINE"


def compute_relevance(has_ticker_tags: bool, source_type: str) -> float:
    """Company-specific items (ticker-tagged) score higher than generic
    sector/macro/market news; official exchange filings score highest."""
    if source_type in ("NSE_ANNOUNCEMENT", "BSE_ANNOUNCEMENT"):
        return 1.0
    return 0.7 if has_ticker_tags else 0.4


def credibility_weight(source_type: str) -> float:
    return SOURCE_CREDIBILITY_WEIGHTS.get(source_type, _DEFAULT_CREDIBILITY_WEIGHT)
