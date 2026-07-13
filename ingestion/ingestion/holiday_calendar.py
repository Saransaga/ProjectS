"""Weekend/holiday pre-filter for scheduling.

This is only an optimization to skip obviously-closed days before making an HTTP
call — it is NOT the source of truth for whether a trading day actually had
data. A date that slips through here but has no bhavcopy published (e.g. an
undocumented holiday) is still handled correctly by the jobs, which treat a
"no data for this date" response from the exchange as a SKIPPED run rather
than a failure.

`holidays.json` ships empty. NSE's trading-holiday calendar changes every year
(it isn't fetchable from a fixed, unauthenticated URL) — populate this file
from NSE's official yearly holiday circular if you want scheduled runs to
avoid making a request on known holidays.
"""

import json
import os
from datetime import date, datetime, time
from zoneinfo import ZoneInfo

_HOLIDAYS_PATH = os.path.join(os.path.dirname(__file__), "holidays.json")
_IST = ZoneInfo("Asia/Kolkata")
_MARKET_OPEN = time(9, 15)
_MARKET_CLOSE = time(15, 30)


def _load_holidays() -> set[str]:
    if not os.path.exists(_HOLIDAYS_PATH):
        return set()
    with open(_HOLIDAYS_PATH) as f:
        return set(json.load(f))


_HOLIDAYS = _load_holidays()


def is_trading_day(d: date) -> bool:
    if d.weekday() >= 5:  # Saturday=5, Sunday=6
        return False
    if d.isoformat() in _HOLIDAYS:
        return False
    return True


def is_market_hours(dt: datetime | None = None) -> bool:
    """NSE/BSE regular trading session (09:15-15:30 IST) on a trading day.
    Used to gate high-frequency polling (exchange announcements) to when new
    filings can actually land — RSS/social jobs run around the clock since
    news doesn't stop at 15:30."""
    now = (dt or datetime.now(_IST)).astimezone(_IST)
    if not is_trading_day(now.date()):
        return False
    return _MARKET_OPEN <= now.time() <= _MARKET_CLOSE
