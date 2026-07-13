"""Lightweight sentiment scoring via a small hand-curated financial keyword
lexicon — deliberately not Loughran-McDonald or FinBERT (see README: avoiding
an unverified third-party word list and a multi-GB transformer dependency for
this phase). Counts positive vs negative keyword hits and normalizes to a
score in [-1, 1]. A first-pass signal, not publication-grade sentiment
analysis — extend the word lists as gaps show up in practice.
"""

import re

_POSITIVE_WORDS = {
    "profit", "profits", "growth", "surge", "surged", "rally", "rallied",
    "beat", "beats", "upgrade", "upgraded", "expansion", "record", "strong",
    "robust", "gain", "gains", "gained", "outperform", "bullish", "rebound",
    "recovery", "improve", "improved", "improvement", "boost", "boosted",
    "win", "wins", "won", "approval", "approved", "buyback", "dividend",
    "bonus", "milestone", "breakthrough", "partnership", "acquisition",
    "success", "successful", "positive", "rise", "rises", "rising",
    "jump", "jumped", "soar", "soared", "top", "topped", "high", "highest",
}

_NEGATIVE_WORDS = {
    "loss", "losses", "decline", "declined", "fall", "fell", "falling",
    "slump", "plunge", "plunged", "downgrade", "downgraded", "default",
    "defaulted", "fraud", "scam", "raid", "probe", "investigation",
    "resign", "resigns", "resigned", "resignation", "lawsuit", "penalty",
    "penalized", "fine", "fined", "delay", "delayed", "shutdown", "closure",
    "layoff", "layoffs", "bankruptcy", "insolvency", "warning", "cut",
    "cuts", "weak", "weakness", "underperform", "bearish", "crash",
    "crashed", "concern", "concerns", "risk", "risks", "negative", "drop",
    "dropped", "recall", "ban", "banned", "suspend", "suspended", "strike",
    "protest", "controversy", "scandal", "low", "lowest", "slowdown",
}

_LABEL_THRESHOLD = 0.15
_WORD_RE = re.compile(r"[a-z]+")


def score(text: str) -> tuple[str, float]:
    """Returns (sentiment_label, sentiment_score)."""
    words = _WORD_RE.findall(text.lower())
    pos = sum(1 for w in words if w in _POSITIVE_WORDS)
    neg = sum(1 for w in words if w in _NEGATIVE_WORDS)

    total_hits = pos + neg
    if total_hits == 0:
        return "NEUTRAL", 0.0

    raw = (pos - neg) / total_hits
    if raw > _LABEL_THRESHOLD:
        label = "POSITIVE"
    elif raw < -_LABEL_THRESHOLD:
        label = "NEGATIVE"
    else:
        label = "NEUTRAL"
    return label, round(raw, 4)
