"""Lightweight ticker tagging: match symbol/company-name mentions in text
against the instruments table via word-boundary regex — no NER model.

Caveat (documented, not hidden): this is alias matching, not entity
disambiguation. A company name that collides with a common English word
could false-positive; unusual phrasing that doesn't match any alias just
tags nothing. Good enough for "does this mention a company we track", not
publication-grade NER — see README.

normalize_name is public (not a news-only helper) because query/resolve.py
(Domain 8) reuses it for Telegram free-text symbol resolution — match_tickers
itself only works when the alias is *shorter than or equal to* the input
text (a substring search), which is backwards for a short chat query like
"reliance" that's shorter than the alias "reliance industries"; resolve.py
does its own bidirectional containment check against normalize_name's output
instead of calling match_tickers for that case. See resolve.py's docstring.
"""

import re

_SUFFIX_RE = re.compile(
    r"\b(Limited|Ltd\.?|Pvt\.?\s*Ltd\.?|Private\s+Limited|Inc\.?|Corporation|Corp\.?)\b",
    re.IGNORECASE,
)
_NON_WORD_RE = re.compile(r"[^\w\s]")
_MIN_NAME_LENGTH = 4  # skip normalized names too short/ambiguous to match safely


def normalize_name(name: str) -> str:
    name = _SUFFIX_RE.sub("", name)
    name = _NON_WORD_RE.sub(" ", name)
    return " ".join(name.split()).strip()


def build_alias_index(conn) -> list[tuple[re.Pattern, int]]:
    """One (compiled whole-word/phrase pattern, instrument_id) per alias,
    built once per job run and reused across every item in that run."""
    with conn.cursor() as cur:
        cur.execute(
            "SELECT instrument_id, symbol, name FROM instruments "
            "WHERE exchange = 'NSE' AND instrument_type = 'EQUITY' AND is_active"
        )
        rows = cur.fetchall()

    patterns = []
    for instrument_id, symbol, name in rows:
        patterns.append((re.compile(rf"\b{re.escape(symbol)}\b"), instrument_id))
        normalized = normalize_name(name or "")
        if len(normalized) >= _MIN_NAME_LENGTH:
            patterns.append((re.compile(rf"\b{re.escape(normalized)}\b", re.IGNORECASE), instrument_id))
    return patterns


def match_tickers(text: str, alias_index: list[tuple[re.Pattern, int]], limit: int = 10) -> set[int]:
    matched: set[int] = set()
    for pattern, instrument_id in alias_index:
        if instrument_id in matched:
            continue
        if pattern.search(text):
            matched.add(instrument_id)
            if len(matched) >= limit:
                break
    return matched
