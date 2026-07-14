"""Best-effort classifiers for Domain 7's two free-text NSE sources: board-
meeting purpose strings (fetch_board_meetings) and AGM/EGM announcement text
(fetch_corporate_announcements, desc == 'Shareholders meeting'). Same "regex
over free text, imperfect by nature" spirit as fundamentals/corporate_actions.py."""

import re
from datetime import date, datetime

_EVENT_TYPE_KEYWORDS = [
    ("BUYBACK", ("buyback", "buy-back", "buy back")),
    ("SPLIT", ("stock split", "sub-division", "sub division")),
    ("BONUS", ("bonus",)),
    ("RIGHTS", ("rights issue", "rights")),
    ("DIVIDEND", ("dividend",)),
    ("EARNINGS", ("financial result",)),
    ("FUND_RAISING", ("fund raising", "fund-raising")),
]


def classify_board_meeting_purpose(purpose: str) -> str:
    """Board meetings often bundle several concerns in one purpose string
    (e.g. "Financial Results/Dividend") — the decision-specific action
    (buyback/split/bonus/rights/dividend) wins over routine quarterly
    earnings, since that's the more actionable forward-looking signal.
    Falls back to OTHER for "Board Meeting Intimation", "Voluntary
    Delisting", "Other business matters", etc. — never dropped, same as
    corporate_actions.action_type='OTHER'."""
    lower = (purpose or "").lower()
    for event_type, keywords in _EVENT_TYPE_KEYWORDS:
        if any(kw in lower for kw in keywords):
            return event_type
    return "OTHER"


_HELD_ON_RE = re.compile(r"held\s+on\s+([A-Za-z0-9,\s]+?\d{4})", re.IGNORECASE)
_WEEKDAY_RE = re.compile(r"\b(Monday|Tuesday|Wednesday|Thursday|Friday|Saturday|Sunday)\b,?", re.IGNORECASE)
_ORDINAL_RE = re.compile(r"(\d{1,2})(st|nd|rd|th)\b", re.IGNORECASE)
_DATE_FORMATS = ("%d %B %Y", "%B %d %Y", "%d %b %Y", "%b %d %Y")


def _loose_parse_date(snippet: str) -> date | None:
    cleaned = _WEEKDAY_RE.sub("", snippet)
    cleaned = _ORDINAL_RE.sub(r"\1", cleaned)
    cleaned = cleaned.replace(",", " ")
    cleaned = re.sub(r"\s+", " ", cleaned).strip()
    for fmt in _DATE_FORMATS:
        try:
            return datetime.strptime(cleaned, fmt).date()
        except ValueError:
            continue
    return None


def parse_shareholder_meeting(desc_text: str, filename: str) -> dict | None:
    """Extracts AGM/EGM meeting type + date out of NSE's free-text
    'Shareholders meeting' announcement (attchmntText / attchmntFile URL).
    Unlike classify_board_meeting_purpose, an unparseable record is dropped
    (returns None) rather than tagged OTHER: without a confirmed AGM/EGM type
    and a resolved date, the row isn't usable "calendar" data — this also
    filters out same-category noise like Postal Ballot outcomes and voting-
    result filings that carry no future meeting date at all."""
    desc_text = desc_text or ""
    filename = filename or ""
    lower = desc_text.lower()
    fname_lower = filename.lower()

    # Filenames concatenate words with no separators (e.g. "AMSEGMNotice...pdf"),
    # so a word-boundary regex would miss real notices — a plain substring
    # check is the only thing that works here, and "agm"/"egm" are distinctive
    # enough acronyms that a false positive from an unrelated word is unlikely.
    if "annual general meeting" in lower or "agm" in fname_lower:
        event_type = "AGM"
    elif "extraordinary general meeting" in lower or "egm" in fname_lower:
        event_type = "EGM"
    else:
        return None

    m = _HELD_ON_RE.search(desc_text)
    if not m:
        return None
    meeting_date = _loose_parse_date(m.group(1))
    if meeting_date is None:
        return None

    return {"event_type": event_type, "event_date": meeting_date}
