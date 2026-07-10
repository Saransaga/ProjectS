"""Sensex EOD close, fetched from BSE.

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
"""

from datetime import date

import requests
from tenacity import retry, retry_if_exception_type, stop_after_attempt, wait_exponential

from .config import config

_INDEX_HISTORY_URL = "https://api.bseindia.com/BseIndiaAPI/api/IndexArchiveData/w"

_HEADERS = {
    "User-Agent": config.HTTP_USER_AGENT,
    "Accept": "application/json, text/plain, */*",
    "Referer": "https://www.bseindia.com/markets/equity/EQReports/IndexArchiveData.aspx",
    "Origin": "https://www.bseindia.com",
}


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
