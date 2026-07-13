"""Best-effort classifier for NSE's free-text corporate-action subject line
(e.g. "Dividend - Rs 2 Per Share", "Bonus issue 1:1") into a structured
action_type + numeric fields. Regex-based and necessarily imperfect —
anything that doesn't match a known pattern is stored as action_type='OTHER'
with the raw subject preserved, never dropped."""

import re

_BUYBACK_RE = re.compile(r"buy\s*-?\s*back", re.IGNORECASE)
_SPLIT_RE = re.compile(r"Rs\.?\s*(\d+(?:\.\d+)?).*?Rs\.?\s*(\d+(?:\.\d+)?)", re.IGNORECASE)
_RATIO_RE = re.compile(r"(\d+)\s*:\s*(\d+)")
_AMOUNT_RE = re.compile(r"Rs\.?\s*(\d+(?:\.\d+)?)", re.IGNORECASE)


def classify(subject: str) -> dict:
    result = {
        "action_type": "OTHER",
        "amount_per_share": None,
        "ratio_new": None,
        "ratio_old": None,
        "face_value_from": None,
        "face_value_to": None,
    }
    lower = subject.lower()

    if _BUYBACK_RE.search(subject):
        result["action_type"] = "BUYBACK"
        return result

    if "split" in lower or "sub-division" in lower or "sub division" in lower:
        m = _SPLIT_RE.search(subject)
        if m:
            result["action_type"] = "SPLIT"
            result["face_value_from"] = float(m.group(1))
            result["face_value_to"] = float(m.group(2))
            return result

    if "bonus" in lower:
        m = _RATIO_RE.search(subject)
        if m:
            result["action_type"] = "BONUS"
            result["ratio_new"] = int(m.group(1))
            result["ratio_old"] = int(m.group(2))
            return result

    if "rights" in lower:
        m = _RATIO_RE.search(subject)
        if m:
            result["action_type"] = "RIGHTS"
            result["ratio_new"] = int(m.group(1))
            result["ratio_old"] = int(m.group(2))
            return result

    if "dividend" in lower:
        m = _AMOUNT_RE.search(subject)
        result["action_type"] = "DIVIDEND"
        if m:
            result["amount_per_share"] = float(m.group(1))
        return result

    return result
