"""Corporate filings from NSE's interactive API (corporate actions, board
meetings, shareholding pattern, financial-results XBRL index).

Unlike nse_client.py's static bhavcopy archives, these endpoints live behind
Akamai bot protection: a bare GET to nseindia.com returns 403, but it still
sets a usable cookie that the JSON API endpoints then accept — the same
warm-up-cookie pattern the community NseIndiaApi library uses. This class of
endpoint is known to be IP-blocked from some cloud/server hosts; it was
verified working from the environment this was built in, but if it starts
failing elsewhere, a changed/blocked IP is the first thing to check — same
"verify before trusting" spirit as bse_client.py's unverified-endpoint note.

XBRL filings themselves (fetch_xbrl) live on nsearchives.nseindia.com, a
static archive with no bot protection — same trust tier as nse_client.py's
bhavcopy downloads.
"""

from datetime import date

import requests
from tenacity import retry, retry_if_exception_type, stop_after_attempt, wait_exponential

from .config import config

_BASE = "https://www.nseindia.com/api"
_WARMUP_URL = "https://www.nseindia.com/"

_HEADERS = {
    "User-Agent": config.HTTP_USER_AGENT,
    "Accept": "application/json, text/plain, */*",
    "Accept-Language": "en-US,en;q=0.9",
}


class NseCorporateFetchError(Exception):
    """Non-2xx / non-JSON response from an NSE corporate-filings endpoint."""


_session: requests.Session | None = None


def _get_session() -> requests.Session:
    global _session
    if _session is None:
        _session = requests.Session()
        # Tolerate non-200 here — even a 403 from Akamai sets a usable
        # bot-detection cookie that the JSON API endpoints accept.
        _session.get(_WARMUP_URL, headers=_HEADERS, timeout=15)
    return _session


@retry(
    stop=stop_after_attempt(3),
    wait=wait_exponential(multiplier=1, min=2, max=10),
    retry=retry_if_exception_type((NseCorporateFetchError, requests.RequestException)),
    reraise=True,
)
def _get_json(path: str, params: dict, referer: str):
    session = _get_session()
    headers = {**_HEADERS, "Referer": referer}
    resp = session.get(f"{_BASE}/{path}", params=params, headers=headers, timeout=20)

    if resp.status_code in (401, 403):
        global _session
        _session = None  # likely expired — next attempt re-warms before retrying
        raise NseCorporateFetchError(f"{path}: got {resp.status_code}, re-warming session")

    if resp.status_code != 200 or "application/json" not in resp.headers.get("content-type", ""):
        raise NseCorporateFetchError(
            f"unexpected response ({resp.status_code}, {resp.headers.get('content-type')}) from {path}"
        )

    return resp.json()


def fetch_corporate_actions(from_date: date | None = None, to_date: date | None = None) -> list[dict]:
    params = {"index": "equities"}
    if from_date and to_date:
        params["from_date"] = from_date.strftime("%d-%m-%Y")
        params["to_date"] = to_date.strftime("%d-%m-%Y")
    return _get_json(
        "corporates-corporateActions",
        params,
        referer="https://www.nseindia.com/companies-listing/corporate-filings-actions",
    )


def fetch_board_meetings(from_date: date, to_date: date) -> list[dict]:
    params = {
        "index": "equities",
        "from_date": from_date.strftime("%d-%m-%Y"),
        "to_date": to_date.strftime("%d-%m-%Y"),
    }
    return _get_json(
        "corporate-board-meetings",
        params,
        referer="https://www.nseindia.com/companies-listing/corporate-filings-board-meetings",
    )


def fetch_financial_results(
    symbol: str, from_date: date, to_date: date, period: str = "Quarterly"
) -> list[dict]:
    """Requires a symbol — NSE doesn't support a bulk/all-equities listing for
    this endpoint (confirmed: bulk calls return an empty list). Also requires
    a date range in practice: without one, NSE returns a company's entire
    filing history (100+ rows for an old company going back to pre-XBRL
    years, where the xbrl field is just "-") instead of recent filings."""
    params = {
        "index": "equities",
        "symbol": symbol,
        "period": period,
        "from_date": from_date.strftime("%d-%m-%Y"),
        "to_date": to_date.strftime("%d-%m-%Y"),
    }
    return _get_json(
        "corporates-financial-results",
        params,
        referer="https://www.nseindia.com/companies-listing/corporate-filings-financial-results",
    )


def fetch_corporate_announcements(
    from_date: date, to_date: date, symbol: str | None = None
) -> list[dict]:
    """Real-time exchange corporate announcements (results, board decisions,
    SEBI/regulatory filings, agreements, etc.) — the announcement feed that
    Domain 4 polls every few minutes during market hours. Confirmed live:
    https://www.nseindia.com/api/corporate-announcements?index=equities
    returns HTTP 200 with real JSON from this environment, same session/cookie
    behavior as the other endpoints in this file. Each item carries a `seq_id`
    that is NSE's own stable unique id — use it as the dedup/external_id key
    rather than deriving one."""
    params = {
        "index": "equities",
        "from_date": from_date.strftime("%d-%m-%Y"),
        "to_date": to_date.strftime("%d-%m-%Y"),
    }
    if symbol:
        params["symbol"] = symbol
    return _get_json(
        "corporate-announcements",
        params,
        referer="https://www.nseindia.com/companies-listing/corporate-filings-announcements",
    )


def fetch_shareholding_master() -> list[dict]:
    return _get_json(
        "corporate-share-holdings-master",
        {"index": "equities"},
        referer="https://www.nseindia.com/companies-listing/corporate-filings-shareholding-pattern",
    )


def fetch_xbrl(url: str) -> bytes:
    resp = requests.get(url, headers={"User-Agent": config.HTTP_USER_AGENT}, timeout=20)
    resp.raise_for_status()
    return resp.content
