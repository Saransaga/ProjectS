"""Analyst consensus (rating/target-price coverage) scraped from Tickertape's
server-rendered stock page, used as a cross-check signal for Domain 5's own
brokerage_calls-derived consensus.

VERIFIED LIVE (during implementation of this module):
  - GET https://www.tickertape.in/stocks/{slug_id} with a browser User-Agent
    (config.HTTP_USER_AGENT) returns HTTP 200 and a full Next.js
    server-rendered page for a real slug, e.g.
    https://www.tickertape.in/stocks/reliance-industries-RELI.
  - The page embeds a `<script id="__NEXT_DATA__" type="application/json">`
    tag containing the full page's props as JSON. The analyst data lives at
    data["props"]["pageProps"]["securitySummary"]["forecast"], e.g. for
    Reliance: {"totalReco": 30, "percBuyReco": 100} (30 analysts covering the
    stock, 100% of them rating it Buy).
  - For stocks with no analyst coverage, the page still renders 200 with a
    `forecast` dict present, but its values are JSON null — confirmed via
    https://www.tickertape.in/stocks/apis-india-API (a small-cap with no
    coverage), which returns forecast: {"totalReco": null, "percBuyReco":
    null}. This module treats that as "no data" and returns None — see
    fetch_analyst_consensus's docstring.
  - An unresolvable/nonexistent slug returns HTTP 404, and its __NEXT_DATA__
    has an empty pageProps (no "securitySummary" key at all) — confirmed via
    https://www.tickertape.in/stocks/totally-bogus-slug-XYZ123. This module
    raises TickertapeFetchError for any non-200 response, including 404 —
    callers resolving slugs heuristically (see guess_slug below) MUST expect
    and handle this per-instrument, not let it fail an entire job run.
  - Tickertape's own `/search` API (api.tickertape.in/search), which would
    otherwise be the correct way to resolve an NSE symbol to its Tickertape
    slug_id, is IP-blocked from this environment — it returns a "VPN_BLOCKED"
    response regardless of query. Do not use it. See guess_slug's docstring
    for the (best-effort, unreliable) fallback used instead.

NOT verified: Tickertape's rate limits / bot-detection thresholds under
sustained polling. This module makes one request per call with no retry loop
(a 404 from a bad slug guess isn't worth retrying) — if this starts seeing
429s or blocks under production volume, add backoff similar to
nse_corporate_client.py's session-based warm-up pattern.
"""

import json
import re

import requests

from .config import config

_BASE = "https://www.tickertape.in/stocks"

_HEADERS = {
    "User-Agent": config.HTTP_USER_AGENT,
    "Accept": "text/html,application/xhtml+xml,application/xml;q=0.9,*/*;q=0.8",
}

_NEXT_DATA_RE = re.compile(
    r'<script id="__NEXT_DATA__" type="application/json">(.*?)</script>', re.DOTALL
)

# Corporate suffixes commonly present in `instruments.name` but absent from
# Tickertape's company-name slug segment (e.g. "Reliance Industries Limited"
# -> "reliance-industries", not "reliance-industries-limited"). Stripping
# these improves guess_slug's hit rate but does not make it reliable — see
# its docstring.
_SUFFIX_RE = re.compile(r"\b(limited|ltd)\.?\s*$", re.IGNORECASE)


class TickertapeFetchError(Exception):
    """Raised on a genuine transport/HTTP-status failure (non-200 response,
    connection error, timeout). NOT raised for "no analyst coverage" — that's
    a valid, expected result (see fetch_analyst_consensus)."""


def fetch_analyst_consensus(slug_id: str) -> dict | None:
    """GETs the Tickertape stock page for `slug_id` and extracts the
    "Analyst Ratings & Forecast" card's data from the embedded __NEXT_DATA__
    JSON: data["props"]["pageProps"]["securitySummary"]["forecast"].

    Returns a dict {"total_reco": int, "perc_buy_reco": float} when the stock
    has analyst coverage (both fields present and non-null in the source
    JSON). Returns None when the page loads fine but has no analyst coverage
    (forecast present with null totalReco/percBuyReco, or missing/empty
    forecast/securitySummary) — chosen over "a dict with None values" so
    callers get a single, unambiguous falsy signal for "nothing to persist".

    Raises TickertapeFetchError for an actual transport/HTTP-status failure
    (non-200 response, request exception, or a 200 response whose HTML
    doesn't contain a parseable __NEXT_DATA__ blob at all — a sign the page
    layout changed, not that this stock lacks coverage).
    """
    url = f"{_BASE}/{slug_id}"
    try:
        resp = requests.get(url, headers=_HEADERS, timeout=20)
    except requests.RequestException as exc:
        raise TickertapeFetchError(f"request failed for {slug_id}: {exc}") from exc

    if resp.status_code != 200:
        raise TickertapeFetchError(f"{slug_id}: got HTTP {resp.status_code}")

    match = _NEXT_DATA_RE.search(resp.text)
    if not match:
        raise TickertapeFetchError(f"{slug_id}: __NEXT_DATA__ script tag not found in response")

    try:
        data = json.loads(match.group(1))
    except json.JSONDecodeError as exc:
        raise TickertapeFetchError(f"{slug_id}: __NEXT_DATA__ payload is not valid JSON: {exc}") from exc

    page_props = data.get("props", {}).get("pageProps", {}) or {}
    security_summary = page_props.get("securitySummary") or {}
    forecast = security_summary.get("forecast") or {}

    total_reco = forecast.get("totalReco")
    perc_buy_reco = forecast.get("percBuyReco")

    if total_reco is None or perc_buy_reco is None:
        return None

    return {"total_reco": int(total_reco), "perc_buy_reco": float(perc_buy_reco)}


def guess_slug(symbol: str, company_name: str) -> str:
    """Best-effort heuristic for a Tickertape slug_id from an NSE symbol +
    company name, in the `{company-name-slug}-{SID}` shape Tickertape uses
    (e.g. "reliance-industries-RELI").

    NOT reliable: Tickertape's trailing SID segment (e.g. "RELI" for
    Reliance) is an internal Tickertape security id that has no derivable
    relationship to the NSE trading symbol (e.g. "RELIANCE") or any other
    field this pipeline ingests — there is no algorithm that produces it in
    the general case. This function guesses the NSE `symbol` itself as the
    SID suffix, which is sometimes wrong (Reliance's real SID is "RELI", not
    "RELIANCE") and sometimes right by coincidence, but is the only
    deterministic guess available without a working slug-resolution API (see
    module docstring re: /search being IP-blocked).

    Full-universe slug resolution (e.g. scraping Tickertape's sitemap or an
    alternate lookup endpoint) is explicitly deferred to a later phase —
    callers must treat this as producing a *candidate* to try, and must
    handle TickertapeFetchError / a None result gracefully when it's wrong.
    """
    name = _SUFFIX_RE.sub("", company_name or "").strip().lower()
    name_slug = re.sub(r"[^a-z0-9]+", "-", name).strip("-")
    return f"{name_slug}-{symbol}"
