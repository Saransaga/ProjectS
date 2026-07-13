"""Parse a narrow, fixed set of tags out of NSE quarterly-results XBRL
(`in-bse-fin` taxonomy). See nse_corporate_client.fetch_xbrl for retrieval.

Context-selection caveat: Indian quarterly XBRL filings tag the same concept
under multiple contextRefs (quarter-ended, year-to-date, prior-year
comparatives, ...). Inspecting a real Reliance filing while building this
found that the <context> period dates for these can be identical/unreliable
even though the values genuinely differ — a filer data-quality issue, not
something decodable from the instance document alone. "OneD" is the context
id that, empirically, held the standalone current-quarter figures in every
filing checked — but that's an observed convention, not a taxonomy guarantee.
If a filing doesn't use "OneD", fall back to matching a context's own period
dates against the filing's fromDate/toDate (from the corporates-financial-
results record); if that's still ambiguous, skip the filing rather than
store a guessed number — same "fail clearly, don't guess" approach as
bse_client.py's unverified-endpoint handling.
"""

import re
import xml.etree.ElementTree as ET
from datetime import date

_TAG_RE = re.compile(r"\{.*\}(.+)")
_PREFERRED_CONTEXT_ID = "OneD"

_FIELD_TAGS = {
    "revenue": "RevenueFromOperations",
    "pat": "ProfitLossForPeriod",
    "eps_basic": "BasicEarningsLossPerShareFromContinuingAndDiscontinuedOperations",
    "eps_diluted": "DilutedEarningsLossPerShareFromContinuingAndDiscontinuedOperations",
    "debt_to_equity": "DebtEquityRatio",
    "interest_coverage_ratio": "InterestServiceCoverageRatio",
    "profit_before_tax": "ProfitBeforeTax",
    "finance_costs": "FinanceCosts",
    "depreciation": "DepreciationDepletionAndAmortisationExpense",
    "other_income": "OtherIncome",
    "paid_up_capital": "PaidUpValueOfEquityShareCapital",
    "face_value": "FaceValueOfEquityShareCapital",
}

# The subset of _FIELD_TAGS that's persisted as-is; the rest (profit_before_tax,
# finance_costs, depreciation, other_income, paid_up_capital, face_value) are
# only fetched to derive ebitda_derived/shares_outstanding below, never stored
# under their own name.
_PERSISTED_FIELDS = (
    "revenue", "pat", "eps_basic", "eps_diluted", "debt_to_equity", "interest_coverage_ratio",
)


def _local_name(tag: str) -> str:
    m = _TAG_RE.match(tag)
    return m.group(1) if m else tag


def _parse_contexts(root: ET.Element) -> dict[str, tuple[date | None, date | None]]:
    contexts = {}
    for ctx in root.iter():
        if _local_name(ctx.tag) != "context":
            continue
        start = end = None
        for period in ctx:
            if _local_name(period.tag) != "period":
                continue
            for child in period:
                name = _local_name(child.tag)
                if name == "startDate" and child.text:
                    start = date.fromisoformat(child.text)
                elif name == "endDate" and child.text:
                    end = date.fromisoformat(child.text)
        contexts[ctx.get("id")] = (start, end)
    return contexts


def _pick_context(contexts: dict, from_date: date, to_date: date) -> str | None:
    if _PREFERRED_CONTEXT_ID in contexts:
        return _PREFERRED_CONTEXT_ID
    matches = [cid for cid, (s, e) in contexts.items() if s == from_date and e == to_date]
    return matches[0] if len(matches) == 1 else None


def parse_financial_results(xbrl_bytes: bytes, from_date: date, to_date: date) -> dict | None:
    """Returns a dict with revenue/pat/eps_basic/eps_diluted/debt_to_equity/
    interest_coverage_ratio/ebitda_derived (numeric, None where a tag is
    absent), or None if no context for this period could be confidently
    identified."""
    root = ET.fromstring(xbrl_bytes)
    context_id = _pick_context(_parse_contexts(root), from_date, to_date)
    if context_id is None:
        return None

    facts: dict[str, float] = {}
    for el in root.iter():
        if el.get("contextRef") != context_id or el.text is None:
            continue
        local = _local_name(el.tag)
        if local in _FIELD_TAGS.values():
            try:
                facts[local] = float(el.text)
            except ValueError:
                continue

    def _fact(field: str) -> float | None:
        return facts.get(_FIELD_TAGS[field])

    result = {field: _fact(field) for field in _PERSISTED_FIELDS}

    pbt, fc, dep, oi = (_fact(f) for f in ("profit_before_tax", "finance_costs", "depreciation", "other_income"))
    result["ebitda_derived"] = None if None in (pbt, fc, dep, oi) else pbt + fc + dep - oi

    paid_up, face_value = (_fact(f) for f in ("paid_up_capital", "face_value"))
    result["shares_outstanding"] = (
        None if not paid_up or not face_value else round(paid_up / face_value)
    )

    return result
