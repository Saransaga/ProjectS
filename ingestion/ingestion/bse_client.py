"""Sensex EOD close, plus real-time corporate announcements, fetched from BSE.

UNVERIFIED ENDPOINT: unlike the NSE endpoints in nse_client.py (which were
confirmed live during implementation), BSE's api.bseindia.com index-history
endpoints returned redirects to an error page for every URL pattern tried
from this environment (BSE may be blocking/misrouting requests outside a real
browser session, or the correct path is undocumented and differs from what's
below). Before relying on this in production: open bseindia.com's index
historical-data page in a browser, capture the actual XHR request from
devtools' Network tab, and update `_INDEX_HISTORY_URL` / the response parsing
to match. Until then, calling `fetch_sensex_close()` will surface that
failure clearly via BseFetchError rather than silently returning wrong data.

`fetch_announcements()` below hits a different api.bseindia.com endpoint and
has shown both symptoms in the same session: an empty `{}` body one moment,
50 real announcement records the next. Treat it as flaky, not reliably
reachable — see its own docstring for what a real response looks like.
"""

from datetime import date

import requests
from tenacity import retry, retry_if_exception_type, stop_after_attempt, wait_exponential

from .config import config

_INDEX_HISTORY_URL = "https://api.bseindia.com/BseIndiaAPI/api/IndexArchiveData/w"
_ANNOUNCEMENTS_URL = "https://api.bseindia.com/BseIndiaAPI/api/AnnSubCategoryGetData/w"

_HEADERS = {
    "User-Agent": config.HTTP_USER_AGENT,
    "Accept": "application/json, text/plain, */*",
    "Referer": "https://www.bseindia.com/markets/equity/EQReports/IndexArchiveData.aspx",
    "Origin": "https://www.bseindia.com",
}

_ANNOUNCEMENTS_HEADERS = {**_HEADERS, "Referer": "https://www.bseindia.com/"}


class BseNoDataError(Exception):
    """Raised when BSE has no data for the given date (holiday / not yet published)."""


class BseFetchError(Exception):
    """Raised for a genuine fetch failure — see module docstring, endpoint is unverified."""


@retry(
    stop=stop_after_attempt(3),
    wait=wait_exponential(multiplier=1, min=2, max=10),
    retry=retry_if_exception_type((BseFetchError, requests.RequestException)),
    reraise=True,
)
def fetch_sensex_close(trade_date: date) -> dict | None:
    ddmmyyyy = trade_date.strftime("%d-%m-%Y")
    resp = requests.get(
        _INDEX_HISTORY_URL,
        params={"strIndex": "SENSEX", "FromDate": ddmmyyyy, "ToDate": ddmmyyyy},
        headers=_HEADERS,
        timeout=20,
    )
    if resp.status_code != 200 or "application/json" not in resp.headers.get("content-type", ""):
        raise BseFetchError(
            f"unexpected response ({resp.status_code}, "
            f"{resp.headers.get('content-type')}) from BSE index history endpoint "
            "— see bse_client.py module docstring, this endpoint needs re-verification"
        )

    payload = resp.json()
    records = payload.get("Table") or payload.get("data") or []
    if not records:
        raise BseNoDataError(f"no Sensex data for {trade_date}")

    row = records[0]
    return {
        "symbol": "Sensex",
        "name": "S&P BSE SENSEX",
        "open": row.get("Open"),
        "high": row.get("High"),
        "low": row.get("Low"),
        "close": row.get("Close"),
        "volume": None,
        "turnover": None,
    }


@retry(
    stop=stop_after_attempt(3),
    wait=wait_exponential(multiplier=1, min=2, max=10),
    retry=retry_if_exception_type((BseFetchError, requests.RequestException)),
    reraise=True,
)
def fetch_announcements(from_date: date, to_date: date) -> list[dict]:
    """Real-time corporate announcements from BSE, mirrored to line up with
    nse_corporate_client.fetch_corporate_announcements().

    FLAKY/UNVERIFIED ENDPOINT — inconsistent even within this build: a GET to
    api.bseindia.com/BseIndiaAPI/api/AnnSubCategoryGetData/w with
    pageno=1&strCat=-1&subcategory=-1&strPrevDate=<YYYYMMDD>&strToDate=<YYYYMMDD>
    &strSearch=P&strscrip=&strType=C plus an Origin/Referer of bseindia.com
    was reported returning HTTP 200 with an empty `{}` body moments before
    this was written (same "blocked/misrouted" symptom already documented
    above for fetch_sensex_close()/_INDEX_HISTORY_URL) — but a follow-up check
    while wiring this up got a real HTTP 200 with `{"Table": [...], "Table1":
    [...]}` containing 50 genuine announcement records. Treat this as
    intermittently reachable, not reliably up: don't be surprised if it's back
    to an empty body by the time this runs again — that's exactly the
    BseFetchError path below. No cookie/session warm-up is used here (unlike
    nse_corporate_client.py) since a plain GET was enough to get real data
    back this time, but that may not hold under whatever's causing the
    flakiness.

    Response shape: top-level `Table` holds the announcement list (confirmed
    against real data — see BseAnnouncementsJob for the field mapping used on
    each record, also confirmed against a real response).
    """
    ymd_from = from_date.strftime("%Y%m%d")
    ymd_to = to_date.strftime("%Y%m%d")
    resp = requests.get(
        _ANNOUNCEMENTS_URL,
        params={
            "pageno": 1,
            "strCat": "-1",
            "subcategory": "-1",
            "strPrevDate": ymd_from,
            "strToDate": ymd_to,
            "strSearch": "P",
            "strscrip": "",
            "strType": "C",
        },
        headers=_ANNOUNCEMENTS_HEADERS,
        timeout=20,
    )
    if resp.status_code != 200 or "application/json" not in resp.headers.get("content-type", ""):
        raise BseFetchError(
            f"unexpected response ({resp.status_code}, "
            f"{resp.headers.get('content-type')}) from BSE announcements endpoint "
            "— see bse_client.py module docstring / fetch_announcements docstring, "
            "this endpoint needs re-verification"
        )

    payload = resp.json()
    if "Table" not in payload and "data" not in payload:
        raise BseFetchError(
            f"unrecognized response shape (keys: {list(payload.keys())}) from BSE "
            "announcements endpoint — matches the known empty-body symptom "
            "documented in fetch_announcements' docstring; not treating this as "
            "'legitimately zero announcements' since the shape itself is unexpected"
        )

    records = payload.get("Table") or payload.get("data") or []
    return records
