from datetime import date, datetime

_DATE_FORMATS = ("%d-%b-%Y", "%d-%B-%Y")
_DATETIME_FORMATS = ("%d-%b-%Y %H:%M:%S", "%d-%B-%Y %H:%M:%S")


def _parse_nse(value: str | None, formats: tuple[str, ...]) -> datetime | None:
    if not value or value == "-":
        return None
    for fmt in formats:
        try:
            return datetime.strptime(value.strip(), fmt)
        except ValueError:
            continue
    return None


def parse_nse_date(value: str | None) -> date | None:
    dt = _parse_nse(value, _DATE_FORMATS)
    return dt.date() if dt else None


def parse_nse_datetime(value: str | None) -> datetime | None:
    return _parse_nse(value, _DATETIME_FORMATS)


def lookup_instrument_id(conn, symbol: str) -> int | None:
    with conn.cursor() as cur:
        cur.execute(
            "SELECT instrument_id FROM instruments WHERE exchange = 'NSE' AND symbol = %s AND instrument_type = 'EQUITY'",
            (symbol,),
        )
        row = cur.fetchone()
        return row[0] if row else None
