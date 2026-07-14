import csv
import io
import zipfile
from datetime import date, datetime

import requests
from tenacity import retry, retry_if_exception_type, stop_after_attempt, wait_exponential

from .config import config

_EQUITY_BHAVCOPY_URL = (
    "https://nsearchives.nseindia.com/content/cm/"
    "BhavCopy_NSE_CM_0_0_0_{yyyymmdd}_F_0000.csv.zip"
)
_INDEX_CLOSE_URL = "https://nsearchives.nseindia.com/content/indices/ind_close_all_{ddmmyyyy}.csv"

# Domain 6 — all verified live (2026-07-14), all static nsearchives.nseindia.com
# archives with no bot protection, same trust tier as the two URLs above.
_FNO_BHAVCOPY_URL = (
    "https://nsearchives.nseindia.com/content/fo/"
    "BhavCopy_NSE_FO_0_0_0_{yyyymmdd}_F_0000.csv.zip"
)
# NSE's older "full bhavcopy" format — superseded by the UDiFF CM bhavcopy
# above for OHLCV, but still the only free source for DELIV_QTY/DELIV_PER
# (delivery volume), which UDiFF doesn't carry at all.
_DELIVERY_BHAVCOPY_URL = "https://nsearchives.nseindia.com/products/content/sec_bhavdata_full_{ddmmyyyy}.csv"
_BULK_DEALS_URL = "https://nsearchives.nseindia.com/content/equities/bulk.csv"
_BLOCK_DEALS_URL = "https://nsearchives.nseindia.com/content/equities/block.csv"
# NSCCL's daily "Participant wise Open Interest" snapshot — see init.sql's
# fno_participant_oi comment for why this (not a turnover figure) is what
# stands in for "FII/DII F&O activity" in this phase.
_PARTICIPANT_OI_URL = "https://nsearchives.nseindia.com/content/nsccl/fao_participant_oi_{ddmmyyyy}.csv"

_TARGET_INDEX_NAMES = {"Nifty 50", "Nifty Bank"}

# FinInstrmTp codes in the F&O bhavcopy: ID = index underlying, ST = stock
# underlying; trailing F = future, O = option.
_FNO_UNDERLYING_TYPE = {"IDF": "INDEX", "IDO": "INDEX", "STF": "STOCK", "STO": "STOCK"}
_FNO_CONTRACT_TYPE = {"IDF": "FUT", "IDO": "OPT", "STF": "FUT", "STO": "OPT"}

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


def fetch_fno_bhavcopy(trade_date: date) -> list[dict]:
    """Every F&O contract (index/stock futures + options) traded on
    `trade_date`, from NSE's daily UDiFF bhavcopy. Raises NseNoDataError on
    holidays (same 404 convention as fetch_equity_bhavcopy). ~36,000 rows on
    a typical day — this returns all of them, filtering is the caller's job.
    """
    url = _FNO_BHAVCOPY_URL.format(yyyymmdd=trade_date.strftime("%Y%m%d"))
    resp = _get(url)

    try:
        zf = zipfile.ZipFile(io.BytesIO(resp.content))
        csv_name = next(n for n in zf.namelist() if n.lower().endswith(".csv"))
        raw_text = zf.read(csv_name).decode("utf-8")
    except (zipfile.BadZipFile, StopIteration) as exc:
        raise NseFetchError(f"malformed F&O bhavcopy zip for {trade_date}: {exc}") from exc

    rows = []
    for row in csv.DictReader(io.StringIO(raw_text)):
        fin_type = row.get("FinInstrmTp")
        underlying_type = _FNO_UNDERLYING_TYPE.get(fin_type)
        contract_type = _FNO_CONTRACT_TYPE.get(fin_type)
        if underlying_type is None or contract_type is None:
            continue  # not one of the 4 contract kinds this pipeline models
        rows.append(
            {
                "underlying_symbol": row["TckrSymb"].strip(),
                "underlying_type": underlying_type,
                "contract_type": contract_type,
                "expiry_date": date.fromisoformat(row["XpryDt"].strip()),
                "option_type": row["OptnTp"].strip() or None,
                "strike_price": row["StrkPric"].strip() or None,
                "open_price": row["OpnPric"],
                "high_price": row["HghPric"],
                "low_price": row["LwPric"],
                "close_price": row["ClsPric"],
                "settle_price": row["SttlmPric"],
                "prev_close": row["PrvsClsgPric"],
                "underlying_price": row["UndrlygPric"],
                "open_interest": row["OpnIntrst"],
                "change_in_oi": row["ChngInOpnIntrst"],
                "volume": row["TtlTradgVol"],
                "turnover": row["TtlTrfVal"],
                "trades": row["TtlNbOfTxsExctd"],
                "lot_size": row["NewBrdLotQty"],
            }
        )
    return rows


def fetch_delivery_bhavcopy(trade_date: date) -> list[dict]:
    """EQ-series delivery volume for `trade_date`, from NSE's older "full
    bhavcopy" archive — the UDiFF bhavcopy fetch_equity_bhavcopy() uses
    doesn't carry DELIV_QTY/DELIV_PER at all, this is the only free source
    for it. Column names AND values in this CSV carry leading spaces (a
    quirk of NSE's own export, confirmed live) — stripped here so callers
    never see it. Raises NseNoDataError on holidays."""
    url = _DELIVERY_BHAVCOPY_URL.format(ddmmyyyy=trade_date.strftime("%d%m%Y"))
    resp = _get(url)

    rows = []
    reader = csv.DictReader(io.StringIO(resp.content.decode("utf-8")))
    for raw_row in reader:
        row = {k.strip(): (v.strip() if v else v) for k, v in raw_row.items()}
        if row.get("SERIES") != "EQ":
            continue
        rows.append(
            {
                "symbol": row["SYMBOL"],
                "delivery_qty": row["DELIV_QTY"],
                "delivery_pct": row["DELIV_PER"],
            }
        )
    return rows


def _parse_deal_date(value: str) -> date:
    return datetime.strptime(value.strip(), "%d-%b-%Y").date()


def _fetch_deals_csv(url: str) -> list[dict]:
    """bulk.csv/block.csv only ever serve "today's" deals (no date-range
    param NSE-side) — same "whatever's current right now" shape as
    corporate_actions, not a point-in-time historical fetch."""
    resp = _get(url)
    rows = []
    for row in csv.DictReader(io.StringIO(resp.content.decode("utf-8"))):
        rows.append(
            {
                "deal_date": _parse_deal_date(row["Date"]),
                "symbol": row["Symbol"].strip(),
                "client_name": row["Client Name"].strip(),
                "buy_sell": row["Buy/Sell"].strip().upper(),
                "quantity": row["Quantity Traded"],
                "trade_price": row["Trade Price / Wght. Avg. Price"],
            }
        )
    return rows


def fetch_bulk_deals() -> list[dict]:
    return _fetch_deals_csv(_BULK_DEALS_URL)


def fetch_block_deals() -> list[dict]:
    return _fetch_deals_csv(_BLOCK_DEALS_URL)


def fetch_participant_oi(trade_date: date) -> list[dict]:
    """NSCCL's daily participant-wise (Client/DII/FII/Pro) open-interest
    snapshot across every F&O contract category. Raises NseNoDataError on
    holidays. See init.sql's fno_participant_oi comment for what this is a
    proxy for and what it isn't."""
    url = _PARTICIPANT_OI_URL.format(ddmmyyyy=trade_date.strftime("%d%m%Y"))
    resp = _get(url)

    text = resp.content.decode("utf-8")
    lines = text.splitlines()
    # First line is a quoted title ("Participant wise Open Interest ... as on
    # <date>"), not the header row — the real header (Client Type, Future
    # Index Long, ...) is line 2.
    reader = csv.DictReader(io.StringIO("\n".join(lines[1:])))

    rows = []
    for raw_row in reader:
        # A couple of NSE's own header names carry trailing whitespace
        # ("Future Stock Short       ", "Total Long Contracts      ",
        # confirmed live) — normalize keys so callers never have to guess
        # how many trailing spaces NSE shipped this time.
        row = {k.strip(): v for k, v in raw_row.items()}
        client_type = (row.get("Client Type") or "").strip().upper()
        if client_type not in ("CLIENT", "DII", "FII", "PRO"):
            continue  # skips the trailing TOTAL row
        rows.append(
            {
                "client_type": client_type,
                "fut_index_long": row.get("Future Index Long"),
                "fut_index_short": row.get("Future Index Short"),
                "fut_stock_long": row.get("Future Stock Long"),
                "fut_stock_short": row.get("Future Stock Short"),
                "opt_index_call_long": row.get("Option Index Call Long"),
                "opt_index_put_long": row.get("Option Index Put Long"),
                "opt_index_call_short": row.get("Option Index Call Short"),
                "opt_index_put_short": row.get("Option Index Put Short"),
                "opt_stock_call_long": row.get("Option Stock Call Long"),
                "opt_stock_put_long": row.get("Option Stock Put Long"),
                "opt_stock_call_short": row.get("Option Stock Call Short"),
                "opt_stock_put_short": row.get("Option Stock Put Short"),
                "total_long_contracts": row.get("Total Long Contracts"),
                "total_short_contracts": row.get("Total Short Contracts"),
            }
        )
    return rows
