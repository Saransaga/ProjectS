import csv
import io
import zipfile
from datetime import date

import requests
from tenacity import retry, retry_if_exception_type, stop_after_attempt, wait_exponential

from .config import config

_EQUITY_BHAVCOPY_URL = (
    "https://nsearchives.nseindia.com/content/cm/"
    "BhavCopy_NSE_CM_0_0_0_{yyyymmdd}_F_0000.csv.zip"
)
_INDEX_CLOSE_URL = "https://nsearchives.nseindia.com/content/indices/ind_close_all_{ddmmyyyy}.csv"

_TARGET_INDEX_NAMES = {"Nifty 50", "Nifty Bank"}

_HEADERS = {
    "User-Agent": config.HTTP_USER_AGENT,
    "Accept": "*/*",
}


class NseNoDataError(Exception):
    """Raised when NSE has no file for the given date (holiday / not yet published)."""


class NseFetchError(Exception):
    """Raised for a genuine fetch failure (network error, unexpected status, bad content)."""


@retry(
    stop=stop_after_attempt(3),
    wait=wait_exponential(multiplier=1, min=2, max=10),
    retry=retry_if_exception_type((NseFetchError, requests.RequestException)),
    reraise=True,
)
def _get(url: str) -> requests.Response:
    resp = requests.get(url, headers=_HEADERS, timeout=20)
    if resp.status_code == 404:
        raise NseNoDataError(f"no data at {url}")
    if resp.status_code != 200:
        raise NseFetchError(f"unexpected status {resp.status_code} for {url}")
    return resp


def fetch_equity_bhavcopy(trade_date: date) -> list[dict]:
    """Equities (SERIES=EQ) OHLCV for a trading day. Raises NseNoDataError on holidays."""
    url = _EQUITY_BHAVCOPY_URL.format(yyyymmdd=trade_date.strftime("%Y%m%d"))
    resp = _get(url)

    try:
        zf = zipfile.ZipFile(io.BytesIO(resp.content))
        csv_name = next(n for n in zf.namelist() if n.lower().endswith(".csv"))
        raw_text = zf.read(csv_name).decode("utf-8")
    except (zipfile.BadZipFile, StopIteration) as exc:
        raise NseFetchError(f"malformed bhavcopy zip for {trade_date}: {exc}") from exc

    rows = []
    for row in csv.DictReader(io.StringIO(raw_text)):
        if row.get("FinInstrmTp") != "STK" or row.get("SctySrs") != "EQ":
            continue
        rows.append(
            {
                "symbol": row["TckrSymb"].strip(),
                "name": row["FinInstrmNm"].strip(),
                "isin": row["ISIN"].strip(),
                "open": row["OpnPric"],
                "high": row["HghPric"],
                "low": row["LwPric"],
                "close": row["ClsPric"],
                "prev_close": row["PrvsClsgPric"],
                "volume": row["TtlTradgVol"],
                "turnover": row["TtlTrfVal"],
                "trades": row["TtlNbOfTxsExctd"],
            }
        )
    return rows


def fetch_index_close(trade_date: date) -> list[dict]:
    """Nifty 50 / Nifty Bank daily close. Raises NseNoDataError on holidays."""
    url = _INDEX_CLOSE_URL.format(ddmmyyyy=trade_date.strftime("%d%m%Y"))
    resp = _get(url)

    rows = []
    for row in csv.DictReader(io.StringIO(resp.content.decode("utf-8"))):
        name = row.get("Index Name", "").strip()
        if name not in _TARGET_INDEX_NAMES:
            continue
        rows.append(
            {
                "symbol": name,
                "name": name,
                "open": row["Open Index Value"],
                "high": row["High Index Value"],
                "low": row["Low Index Value"],
                "close": row["Closing Index Value"],
                "volume": row.get("Volume") or None,
                "turnover": row.get("Turnover (Rs. Cr.)") or None,
            }
        )
    return rows
