"""Moneycontrol's per-stock symbol resolver + "Broker Research" section —
Domain 5's primary source for brokerage calls (rating + target price per
brokerage, most recent first).

VERIFIED LIVE (2026-07-13, from this environment, no bot-protection/warm-up
cookie needed — plain requests.get with a browser User-Agent got real data
every time):

- `resolve_stock`: confirmed against RELIANCE, TCS, HDFCBANK, MARUTI — each
  returned a JSONP array (`suggest1([...])`) of several candidate
  instruments, and only the one whose embedded `<span>ISIN, SYMBOL,
  BSE_CODE</span>` NSE-symbol field matched case-insensitively was selected.
  Confirmed the brief's warning is real: querying "RELIANCE" returns 5+
  distinct listed companies ("Reliance Industries", "Reliance Power",
  "Reliance Infrastructure", "Reliance Communications", "Reliance Chemotex
  Industries", "Reliance Home Finance", ...) that all share the "Reliance"
  name prefix — taking the first result would silently resolve to the wrong
  instrument. Matching the NSE symbol inside the embedded span is the only
  reliable disambiguator seen.

- `fetch_broker_research`: confirmed against Reliance Industries, TCS, HDFC
  Bank and Maruti Suzuki's stock pages. Rating text varies well beyond "BUY"
  — live examples captured: "BUY", "ACCUMULATE", "HOLD", "REDUCE". Button
  CSS class is confirmed unreliable exactly as the brief warned: a live
  "HOLD" call rendered class="button_buy hold", and a live "REDUCE" call
  rendered class="button_buy sell" — neither class cleanly encodes the
  rating on its own, so this module always reads the button's text content,
  never its class. Reco/target price can legitimately be "-" (missing) in
  the table, parsed to None rather than raising. The call date can also be
  "-" on rare rows (seen live on one of Reliance's older entries); since
  call_date is a required field downstream, any entry without a parseable
  date is skipped rather than stored with a guessed date.

  CAVEAT for future readers: every stock page checked (Reliance, TCS, HDFC
  Bank, Maruti) rendered exactly 6 `.brrs_bx` boxes inside #broker_research,
  even though brokerages plainly have longer coverage histories (PDF links on
  different dates reach back over a year). This looks like Moneycontrol's own
  page only ships its most recent ~6 calls server-side (rest is presumably
  paginated/lazy-loaded via JS this client doesn't execute). This function
  returns whatever the page ships — treat brokerage_calls as "recent calls",
  not a full historical archive, unless/until this is revisited with a
  network trace of MC's lazy-load endpoint.

Parsing choice: this module uses `beautifulsoup4` (stdlib `html.parser`
backend, no extra lxml dependency) rather than regex extraction. This was a
deliberate call, not a default: regex parsing was tried first and found
concretely unsafe here — class names like "br_date" and rating-adjacent
markup are reused by unrelated widgets further down the same stock page
(e.g. a bulk/insider-deals section), so a naive regex scan over a large
enough window overcounts wildly (22 raw "br_date" substring matches on
Reliance's page for only 6 genuine broker-research entries). Proper DOM
scoping — find the `#broker_research` div, then only its own `.brrs_bx`
children — is what correctly isolates the real entries, and BeautifulSoup
makes that reliable without hand-rolling a tag-matching stack machine.
"""

import json
import logging
import re
from datetime import datetime

import requests
from bs4 import BeautifulSoup
from tenacity import retry, retry_if_exception_type, stop_after_attempt, wait_exponential

from .config import config

logger = logging.getLogger(__name__)

_AUTOSUGGEST_URL = "https://www.moneycontrol.com/mccode/common/autosuggestion_solr.php/"

_JSONP_RE = re.compile(r"^\s*suggest1\((.*)\)\s*;?\s*$", re.DOTALL)
_SPAN_RE = re.compile(r"<span>(.*?)</span>", re.IGNORECASE | re.DOTALL)
_DATE_FORMAT = "%d %b, %Y"

_HEADERS = {
    "User-Agent": config.HTTP_USER_AGENT,
    "Accept": "*/*",
}


class MoneycontrolFetchError(Exception):
    """Non-200 / unparseable response from a Moneycontrol endpoint."""


@retry(
    stop=stop_after_attempt(3),
    wait=wait_exponential(multiplier=1, min=2, max=10),
    retry=retry_if_exception_type((MoneycontrolFetchError, requests.RequestException)),
    reraise=True,
)
def _get(url: str, params: dict | None = None) -> str:
    resp = requests.get(url, params=params, headers=_HEADERS, timeout=20)
    if resp.status_code != 200:
        raise MoneycontrolFetchError(f"unexpected response ({resp.status_code}) from {url}")
    return resp.text


def _parse_float(text: str | None) -> float | None:
    if not text:
        return None
    cleaned = text.replace(",", "").strip()
    if not cleaned or cleaned == "-":
        return None
    try:
        return float(cleaned)
    except ValueError:
        return None


def resolve_stock(symbol: str) -> dict | None:
    """Resolve an NSE symbol to Moneycontrol's own page URL + internal stock
    code via the autosuggestion endpoint. Returns {"sc_id": ..., "page_url":
    ...} for the first candidate whose embedded NSE symbol matches `symbol`
    case-insensitively, or None if no candidate matches (never guesses by
    taking the first/best-named result — see module docstring for why that's
    unsafe). Raises MoneycontrolFetchError on a non-200 or unparseable
    response."""
    raw = _get(
        _AUTOSUGGEST_URL,
        params={"classic": "true", "query": symbol, "type": "1", "format": "json", "callback": "suggest1"},
    )

    m = _JSONP_RE.match(raw.strip())
    if not m:
        raise MoneycontrolFetchError(
            f"couldn't strip JSONP wrapper from autosuggest response for {symbol!r}: {raw[:200]!r}"
        )
    try:
        candidates = json.loads(m.group(1))
    except json.JSONDecodeError as exc:
        raise MoneycontrolFetchError(
            f"unparseable JSON in autosuggest response for {symbol!r}: {exc}"
        ) from exc

    target = symbol.strip().upper()
    for c in candidates:
        pdt_dis_nm = c.get("pdt_dis_nm") or ""
        span_m = _SPAN_RE.search(pdt_dis_nm)
        if not span_m:
            continue
        parts = [p.strip() for p in span_m.group(1).split(",")]
        if len(parts) < 2:
            continue  # malformed span, e.g. missing the NSE symbol field
        nse_symbol = parts[1].upper()
        if nse_symbol != target:
            continue

        link_src, sc_id = c.get("link_src"), c.get("sc_id")
        if not link_src or not sc_id:
            continue  # symbol matched but the record is otherwise unusable
        return {"sc_id": sc_id, "page_url": link_src}

    return None


def fetch_broker_research(page_url: str) -> list[dict]:
    """Fetch a Moneycontrol stock page and parse its "Broker Research"
    section into a list of {"brokerage_name", "call_date", "raw_rating",
    "reco_price", "target_price", "report_url"} dicts, in whatever order the
    page renders them (observed live as most-recent-first, but that ordering
    isn't guaranteed here — callers shouldn't rely on it).

    Returns [] both when the #broker_research div is entirely absent from the
    page and when it's present but empty — a stock can legitimately have no
    analyst coverage, that's not an error condition. A single malformed entry
    (missing brokerage name / rating / unparseable date) is skipped with a
    logged warning rather than aborting the whole parse — same per-record
    resilience convention as the rest of this codebase.
    MoneycontrolFetchError is raised only for an actual transport/status-code
    failure fetching the page."""
    html = _get(page_url)
    soup = BeautifulSoup(html, "html.parser")

    section = soup.find("div", id="broker_research")
    if section is None:
        return []

    calls = []
    for box in section.find_all("div", class_="brrs_bx"):
        try:
            date_div = box.find("div", class_="br_date")
            date_text = date_div.get_text(strip=True) if date_div else ""
            if not date_text or date_text == "-":
                # call_date is a required field downstream — don't store a
                # guessed date, just skip this one entry (rest of the page
                # is unaffected).
                logger.warning("broker-research entry missing a parseable date on %s, skipping", page_url)
                continue
            call_date = datetime.strptime(date_text, _DATE_FORMAT).date()

            name_div = box.find("div", class_="brstk_name")
            brokerage_name = name_div.get_text(strip=True) if name_div else None
            if not brokerage_name:
                logger.warning("broker-research entry missing brokerage name on %s, skipping", page_url)
                continue

            button = box.find("button")
            raw_rating = button.get_text(strip=True) if button else None
            if not raw_rating:
                logger.warning(
                    "broker-research entry missing rating text on %s (brokerage=%s), skipping",
                    page_url, brokerage_name,
                )
                continue

            report_url = None
            report_div = box.find("div", class_="download_report")
            if report_div is not None:
                a = report_div.find("a")
                if a is not None:
                    report_url = a.get("href")

            reco_price = target_price = None
            table = box.find("table")
            if table is not None:
                strongs = table.find_all("strong")
                if len(strongs) >= 1:
                    reco_price = _parse_float(strongs[0].get_text())
                if len(strongs) >= 2:
                    target_price = _parse_float(strongs[1].get_text())

            calls.append(
                {
                    "brokerage_name": brokerage_name,
                    "call_date": call_date,
                    "raw_rating": raw_rating,
                    "reco_price": reco_price,
                    "target_price": target_price,
                    "report_url": report_url,
                }
            )
        except Exception:
            logger.warning("unparseable broker-research entry on %s, skipping", page_url, exc_info=True)
            continue

    return calls
