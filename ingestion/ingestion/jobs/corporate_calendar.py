from datetime import date, timedelta

from .. import nse_corporate_client
from ..db import get_conn
from ..events.classify import classify_board_meeting_purpose, parse_shareholder_meeting
from ..fundamentals.util import lookup_instrument_id, parse_nse_date
from ..upsert_events import bulk_upsert_corporate_calendar
from .base import BaseJob

_BOARD_MEETING_LOOKAHEAD_DAYS = 60
_ANNOUNCEMENT_LOOKBACK_DAYS = 30


class CorporateCalendarJob(BaseJob):
    """Domain 7's forward calendar, from two NSE sources bundled under one
    job like Domain 6's FiiDiiFlowsJob:

    - Board meetings (fetch_board_meetings): a forward window from run_date,
      the opposite direction from FinancialResultsJob's backward-looking
      window — this table answers "what's coming up", not "what just
      happened". Each meeting's bm_purpose classifies into EARNINGS/
      DIVIDEND/BONUS/SPLIT/BUYBACK/RIGHTS/FUND_RAISING/OTHER
      (events/classify.py).
    - AGM/EGM (fetch_corporate_announcements filtered to desc ==
      'Shareholders meeting'): a backward-looking window, since these are
      filed ahead of the actual meeting date — the meeting date itself is
      text-extracted from the announcement (events/classify.py's
      parse_shareholder_meeting), not the announcement's own filing date.
      Records that don't resolve to a confirmed AGM/EGM + date (postal
      ballots, voting-result outcomes, ambiguous "undefined ... to be held
      on" notices with no AGM/EGM keyword anywhere) are dropped rather than
      stored as OTHER — see that function's docstring for why.

    always_force=True: NSE's board-meetings/announcements endpoints always
    serve "whatever's currently scheduled/filed" (no true point-in-time
    history), the same shape as CorporateActionsJob — a daily re-run is
    meant to re-poll that current state, not be skipped as already-done.
    """

    job_name = "corporate_calendar"
    always_force = True

    def fetch(self, run_date: date) -> list[dict]:
        rows: list[dict] = []
        with get_conn() as conn:
            meetings = nse_corporate_client.fetch_board_meetings(
                run_date, run_date + timedelta(days=_BOARD_MEETING_LOOKAHEAD_DAYS)
            )
            for m in meetings:
                symbol = m.get("bm_symbol")
                event_date = parse_nse_date(m.get("bm_date"))
                purpose = m.get("bm_purpose")
                if not symbol or event_date is None or not purpose:
                    continue
                instrument_id = lookup_instrument_id(conn, symbol)
                if instrument_id is None:
                    continue
                rows.append(
                    {
                        "instrument_id": instrument_id,
                        "event_date": event_date,
                        "event_type": classify_board_meeting_purpose(purpose),
                        "purpose": purpose,
                        "description": m.get("bm_desc"),
                        "consensus_eps_estimate": None,
                        "source": "NSE",
                    }
                )

            announcements = nse_corporate_client.fetch_corporate_announcements(
                run_date - timedelta(days=_ANNOUNCEMENT_LOOKBACK_DAYS), run_date
            )
            for a in announcements:
                if a.get("desc") != "Shareholders meeting":
                    continue
                symbol = a.get("symbol")
                if not symbol:
                    continue
                parsed = parse_shareholder_meeting(a.get("attchmntText"), a.get("attchmntFile"))
                if parsed is None:
                    continue
                instrument_id = lookup_instrument_id(conn, symbol)
                if instrument_id is None:
                    continue
                rows.append(
                    {
                        "instrument_id": instrument_id,
                        "event_date": parsed["event_date"],
                        "event_type": parsed["event_type"],
                        "purpose": "Shareholders meeting",
                        "description": a.get("attchmntText"),
                        "consensus_eps_estimate": None,
                        "source": "NSE",
                    }
                )
        return rows

    def _persist(self, run_date: date, rows: list[dict]) -> int:
        with get_conn() as conn:
            return bulk_upsert_corporate_calendar(conn, rows)
