"""Domain 8's core recompute: turns Domains 1-7's tables into a per-instrument
BUY/HOLD/SELL-style recommendation, separately for short-term (technical/
momentum) and long-term (fundamentals/valuation) horizons. See
recommendation/short_term.py and recommendation/long_term.py for the actual
scoring; this module's job is purely data-shaping — one bulk DISTINCT
ON/ROW_NUMBER query per source table (same idiom as
ConsensusRatingsJob._trailing_calls), building in-memory per-instrument
lookup dicts so the scoring loop itself makes zero further DB round-trips.

always_force=True: like ConsensusRatingsJob, this is a recompute over
already-ingested data, not a live market fetch — it must run daily
regardless of is_trading_day()'s weekday/holiday gate, and manual backfills
need to work on any date.
"""

import logging
from collections import defaultdict
from datetime import date, timedelta

from ..db import get_conn
from ..recommendation.bucketize import bucketize
from ..recommendation.long_term import score_long_term
from ..recommendation.short_term import score_short_term
from ..upsert_recommendations import bulk_upsert_stock_recommendations
from .base import BaseJob

logger = logging.getLogger(__name__)

_TREND_EVENT_TYPES = ("BREAKOUT", "BREAKDOWN", "GOLDEN_CROSS", "DEATH_CROSS")
_PROXIMITY_EVENT_TYPES = ("HIGH_52W_PROXIMITY", "LOW_52W_PROXIMITY")
_SIGNAL_EVENTS_WINDOW_DAYS = 10
_PROXIMITY_WINDOW_DAYS = 5
_CORPORATE_ACTIONS_WINDOW_DAYS = 365
_FUNDAMENTALS_LOOKBACK_QUARTERS = 6
_NEWS_WINDOW_DAYS = 5  # Domain 4: news_items has no fixed cadence, unlike the daily EOD tables above
_BULK_BLOCK_DEALS_WINDOW_DAYS = 10  # Domain 6: same window as signal_events_recency's trend events
_UPCOMING_EVENTS_WINDOW_DAYS = 30  # Domain 7: forward-looking, unlike every other _WINDOW_DAYS above


def _f(value) -> float | None:
    """Decimal (psycopg2's default NUMERIC type) -> float. This package's
    pure scoring functions deliberately work in plain floats only — mixing
    Decimal and float in arithmetic raises TypeError, so casting happens
    once, here, at the DB boundary."""
    return None if value is None else float(value)


class RecommendationEngineJob(BaseJob):
    job_name = "recommendation_engine"
    always_force = True

    def fetch(self, run_date: date) -> list[dict]:
        with get_conn() as conn:
            with conn.cursor() as cur:
                cur.execute(
                    "SELECT instrument_id, symbol FROM instruments "
                    "WHERE exchange = 'NSE' AND instrument_type = 'EQUITY' AND is_active"
                )
                universe = cur.fetchall()  # [(instrument_id, symbol), ...]

            technicals = self._fetch_technicals(conn, run_date)
            events = self._fetch_signal_events(conn, run_date)
            rel_strength = self._fetch_relative_strength(conn, run_date)
            fno_buildup, fno_pcr = self._fetch_fno(conn, run_date)
            fundamentals = self._fetch_fundamentals(conn, run_date)
            pe_ratios = self._fetch_pe_ratios(conn, run_date)
            shareholding = self._fetch_shareholding(conn, run_date)
            consensus = self._fetch_consensus(conn, run_date)
            corp_actions = self._fetch_corporate_actions(conn, run_date)
            news = self._fetch_news(conn, run_date)
            bulk_block_deals = self._fetch_bulk_block_deals(conn, run_date)
            fii_dii_net_value_cr = self._fetch_fii_dii_flow(conn, run_date)
            upcoming_events = self._fetch_upcoming_corporate_events(conn, run_date)

        rows = []
        for instrument_id, symbol in universe:
            short_inputs = self._build_short_term_inputs(
                instrument_id, symbol, technicals, events, rel_strength, fno_buildup, fno_pcr,
                news, bulk_block_deals, fii_dii_net_value_cr, upcoming_events,
            )
            long_inputs = self._build_long_term_inputs(
                instrument_id, fundamentals, pe_ratios, shareholding, consensus, corp_actions, rel_strength
            )

            short = score_short_term(short_inputs)
            long = score_long_term(long_inputs)

            rows.append({
                "instrument_id": instrument_id,
                "as_of_date": run_date,
                "short_term_score": short["weighted_score"],
                "short_term_action": None if short["weighted_score"] is None else bucketize(short["weighted_score"]),
                "short_term_rationale": short,
                "long_term_score": long["weighted_score"],
                "long_term_action": None if long["weighted_score"] is None else bucketize(long["weighted_score"]),
                "long_term_rationale": long,
            })
        return rows

    def _persist(self, run_date: date, rows: list[dict]) -> int:
        with get_conn() as conn:
            return bulk_upsert_stock_recommendations(conn, rows)

    # -- bulk lookups: one query per source table, DISTINCT ON/ROW_NUMBER to
    # get "latest as of run_date" (or "latest 2", where a comparison is
    # needed) per instrument, no per-instrument round-trips. --------------

    def _fetch_technicals(self, conn, run_date: date) -> dict[int, list[dict]]:
        """Latest 2 technical_indicators_daily rows per instrument (today +
        prior, for macd_momentum's day-over-day comparison)."""
        with conn.cursor() as cur:
            cur.execute(
                """
                SELECT instrument_id, trade_date, ema_9, ema_21, ema_50, rsi_14, macd_hist, supertrend_direction
                FROM (
                    SELECT *, ROW_NUMBER() OVER (PARTITION BY instrument_id ORDER BY trade_date DESC) AS rn
                    FROM technical_indicators_daily
                    WHERE trade_date <= %s
                ) t
                WHERE rn <= 2
                ORDER BY instrument_id, trade_date DESC
                """,
                (run_date,),
            )
            by_instrument = defaultdict(list)
            for instrument_id, trade_date, ema_9, ema_21, ema_50, rsi_14, macd_hist, supertrend in cur.fetchall():
                by_instrument[instrument_id].append({
                    "trade_date": trade_date,
                    "ema_9": _f(ema_9), "ema_21": _f(ema_21), "ema_50": _f(ema_50),
                    "rsi_14": _f(rsi_14), "macd_hist": _f(macd_hist),
                    "supertrend_direction": supertrend,
                })
            return dict(by_instrument)

    def _fetch_signal_events(self, conn, run_date: date) -> dict[int, list[dict]]:
        with conn.cursor() as cur:
            cur.execute(
                """
                SELECT instrument_id, event_type, event_date
                FROM signal_events
                WHERE event_date BETWEEN %s AND %s
                  AND event_type IN %s
                """,
                (
                    run_date - timedelta(days=_SIGNAL_EVENTS_WINDOW_DAYS),
                    run_date,
                    _TREND_EVENT_TYPES + _PROXIMITY_EVENT_TYPES,
                ),
            )
            by_instrument = defaultdict(list)
            for instrument_id, event_type, event_date in cur.fetchall():
                by_instrument[instrument_id].append(
                    {"event_type": event_type, "days_ago": (run_date - event_date).days}
                )
            return dict(by_instrument)

    def _fetch_relative_strength(self, conn, run_date: date) -> dict[int, dict]:
        with conn.cursor() as cur:
            cur.execute(
                """
                SELECT DISTINCT ON (instrument_id)
                    instrument_id, return_1w, return_1m, return_1y, rs_rating
                FROM relative_strength
                WHERE trade_date <= %s
                ORDER BY instrument_id, trade_date DESC
                """,
                (run_date,),
            )
            return {
                instrument_id: {
                    "return_1w": _f(return_1w), "return_1m": _f(return_1m),
                    "return_1y": _f(return_1y), "rs_rating": _f(rs_rating),
                }
                for instrument_id, return_1w, return_1m, return_1y, rs_rating in cur.fetchall()
            }

    def _fetch_fno(self, conn, run_date: date) -> tuple[dict[str, dict], dict[str, dict]]:
        """Keyed by underlying_symbol (not instrument_id) — the only
        reliable join key for F&O tables, see init.sql's Domain 6 notes.
        "Near-month contract" = most recent trade_date's earliest expiry."""
        with conn.cursor() as cur:
            cur.execute(
                """
                SELECT DISTINCT ON (underlying_symbol) underlying_symbol, buildup_type
                FROM fno_oi_buildup
                WHERE trade_date <= %s
                ORDER BY underlying_symbol, trade_date DESC, expiry_date ASC
                """,
                (run_date,),
            )
            buildup = {symbol: {"buildup_type": buildup_type} for symbol, buildup_type in cur.fetchall()}

            cur.execute(
                """
                SELECT DISTINCT ON (underlying_symbol) underlying_symbol, pcr_oi
                FROM fno_signals
                WHERE trade_date <= %s
                ORDER BY underlying_symbol, trade_date DESC, expiry_date ASC
                """,
                (run_date,),
            )
            pcr = {symbol: {"pcr_oi": _f(pcr_oi)} for symbol, pcr_oi in cur.fetchall()}
        return buildup, pcr

    def _fetch_fundamentals(self, conn, run_date: date) -> dict[int, list[dict]]:
        with conn.cursor() as cur:
            cur.execute(
                """
                SELECT instrument_id, period_end_date, financial_year, reporting_quarter,
                       consolidated, eps_basic, eps_diluted
                FROM (
                    SELECT *, ROW_NUMBER() OVER (
                        PARTITION BY instrument_id, consolidated ORDER BY period_end_date DESC
                    ) AS rn
                    FROM fundamentals_quarterly
                    WHERE period_end_date <= %s
                ) t
                WHERE rn <= %s
                """,
                (run_date, _FUNDAMENTALS_LOOKBACK_QUARTERS),
            )
            by_instrument = defaultdict(list)
            for instrument_id, period_end, fy, quarter, consolidated, eps_basic, eps_diluted in cur.fetchall():
                by_instrument[instrument_id].append({
                    "period_end_date": period_end, "financial_year": fy, "reporting_quarter": quarter,
                    "consolidated": consolidated, "eps": _f(eps_diluted) if eps_diluted is not None else _f(eps_basic),
                })
            # Prefer consolidated over standalone when both exist for the same period_end_date.
            deduped = {}
            for instrument_id, periods in by_instrument.items():
                by_period = {}
                for p in sorted(periods, key=lambda p: p["consolidated"]):  # False (standalone) before True
                    by_period[p["period_end_date"]] = p  # consolidated overwrites standalone if both present
                deduped[instrument_id] = sorted(by_period.values(), key=lambda p: p["period_end_date"], reverse=True)
            return deduped

    def _fetch_pe_ratios(self, conn, run_date: date) -> dict[int, float]:
        with conn.cursor() as cur:
            cur.execute(
                """
                SELECT DISTINCT ON (instrument_id) instrument_id, pe_ratio
                FROM fundamental_ratios
                WHERE as_of_date <= %s
                ORDER BY instrument_id, as_of_date DESC
                """,
                (run_date,),
            )
            return {instrument_id: _f(pe_ratio) for instrument_id, pe_ratio in cur.fetchall()}

    def _fetch_shareholding(self, conn, run_date: date) -> dict[int, list[dict]]:
        with conn.cursor() as cur:
            cur.execute(
                """
                SELECT instrument_id, period_end_date, promoter_pct, fii_pct, pledged_promoter_pct
                FROM (
                    SELECT *, ROW_NUMBER() OVER (PARTITION BY instrument_id ORDER BY period_end_date DESC) AS rn
                    FROM shareholding_pattern
                    WHERE period_end_date <= %s
                ) t
                WHERE rn <= 2
                ORDER BY instrument_id, period_end_date DESC
                """,
                (run_date,),
            )
            by_instrument = defaultdict(list)
            for instrument_id, period_end, promoter_pct, fii_pct, pledged_pct in cur.fetchall():
                by_instrument[instrument_id].append({
                    "period_end_date": period_end,
                    "promoter_pct": _f(promoter_pct), "fii_pct": _f(fii_pct),
                    "pledged_promoter_pct": _f(pledged_pct),
                })
            return dict(by_instrument)

    def _fetch_consensus(self, conn, run_date: date) -> dict[int, dict]:
        with conn.cursor() as cur:
            cur.execute(
                """
                SELECT DISTINCT ON (instrument_id) instrument_id, consensus_rating_bucket, implied_upside_pct
                FROM consensus_ratings
                WHERE as_of_date <= %s
                ORDER BY instrument_id, as_of_date DESC
                """,
                (run_date,),
            )
            return {
                instrument_id: {"consensus_rating_bucket": bucket, "implied_upside_pct": _f(upside)}
                for instrument_id, bucket, upside in cur.fetchall()
            }

    def _fetch_corporate_actions(self, conn, run_date: date) -> dict[int, list[str]]:
        with conn.cursor() as cur:
            cur.execute(
                """
                SELECT instrument_id, action_type
                FROM corporate_actions
                WHERE ex_date IS NOT NULL AND ex_date BETWEEN %s AND %s
                """,
                (run_date - timedelta(days=_CORPORATE_ACTIONS_WINDOW_DAYS), run_date),
            )
            by_instrument = defaultdict(list)
            for instrument_id, action_type in cur.fetchall():
                by_instrument[instrument_id].append(action_type)
            return dict(by_instrument)

    def _fetch_news(self, conn, run_date: date) -> dict[int, list[dict]]:
        """Domain 4: news_items joined through news_item_tickers (a company
        story can name several instruments, hence the many-to-many join
        rather than a direct instrument_id column on news_items)."""
        with conn.cursor() as cur:
            cur.execute(
                """
                SELECT nit.instrument_id, ni.sentiment_score, ni.relevance_score,
                       ni.source_credibility_weight, ni.urgency, ni.published_at
                FROM news_item_tickers nit
                JOIN news_items ni ON ni.news_item_id = nit.news_item_id
                WHERE ni.published_at IS NOT NULL
                  AND ni.published_at::date BETWEEN %s AND %s
                """,
                (run_date - timedelta(days=_NEWS_WINDOW_DAYS), run_date),
            )
            by_instrument = defaultdict(list)
            for instrument_id, sentiment_score, relevance_score, credibility, urgency, published_at in cur.fetchall():
                by_instrument[instrument_id].append({
                    "sentiment_score": _f(sentiment_score),
                    "relevance_score": _f(relevance_score),
                    "source_credibility_weight": _f(credibility),
                    "urgency": urgency,
                    "days_ago": (run_date - published_at.date()).days,
                })
            return dict(by_instrument)

    def _fetch_bulk_block_deals(self, conn, run_date: date) -> dict[int, list[dict]]:
        with conn.cursor() as cur:
            cur.execute(
                """
                SELECT instrument_id, buy_sell, quantity
                FROM bulk_block_deals
                WHERE deal_date BETWEEN %s AND %s
                """,
                (run_date - timedelta(days=_BULK_BLOCK_DEALS_WINDOW_DAYS), run_date),
            )
            by_instrument = defaultdict(list)
            for instrument_id, buy_sell, quantity in cur.fetchall():
                by_instrument[instrument_id].append({"buy_sell": buy_sell, "quantity": quantity})
            return dict(by_instrument)

    def _fetch_fii_dii_flow(self, conn, run_date: date) -> float | None:
        """Domain 6: fii_dii_cash_flows is a market-wide daily figure (one
        row per category per date, not per instrument) — combines FII+DII
        net_value_cr for the most recent flow_date on or before run_date
        into a single value every instrument's short-term score shares."""
        with conn.cursor() as cur:
            cur.execute(
                """
                SELECT sum(net_value_cr) FROM fii_dii_cash_flows
                WHERE flow_date = (SELECT max(flow_date) FROM fii_dii_cash_flows WHERE flow_date <= %s)
                """,
                (run_date,),
            )
            row = cur.fetchone()
            return _f(row[0]) if row else None

    def _fetch_upcoming_corporate_events(self, conn, run_date: date) -> dict[int, list[dict]]:
        """Domain 7: corporate_calendar, forward-looking (event_date >=
        run_date) — the counterpart to _fetch_corporate_actions above, which
        looks backward at corporate_actions' already-happened ex-dates."""
        with conn.cursor() as cur:
            cur.execute(
                """
                SELECT instrument_id, event_type
                FROM corporate_calendar
                WHERE event_date BETWEEN %s AND %s
                """,
                (run_date, run_date + timedelta(days=_UPCOMING_EVENTS_WINDOW_DAYS)),
            )
            by_instrument = defaultdict(list)
            for instrument_id, event_type in cur.fetchall():
                by_instrument[instrument_id].append({"event_type": event_type})
            return dict(by_instrument)

    # -- per-instrument input shaping for recommendation/short_term.py and
    # recommendation/long_term.py -----------------------------------------

    def _build_short_term_inputs(
        self, instrument_id, symbol, technicals, events, rel_strength, fno_buildup, fno_pcr,
        news, bulk_block_deals, fii_dii_net_value_cr, upcoming_events,
    ) -> dict:
        rows = technicals.get(instrument_id, [])
        latest = rows[0] if rows else None
        prior = rows[1] if len(rows) > 1 else None

        instrument_events = events.get(instrument_id, [])
        trend_events = [e for e in instrument_events if e["event_type"] in _TREND_EVENT_TYPES]
        near_high = any(
            e["event_type"] == "HIGH_52W_PROXIMITY" and e["days_ago"] <= _PROXIMITY_WINDOW_DAYS
            for e in instrument_events
        )
        near_low = any(
            e["event_type"] == "LOW_52W_PROXIMITY" and e["days_ago"] <= _PROXIMITY_WINDOW_DAYS
            for e in instrument_events
        )

        rs = rel_strength.get(instrument_id, {})
        buildup = fno_buildup.get(symbol)
        pcr = fno_pcr.get(symbol)

        return {
            "technical_indicators": latest,
            "macd_hist_prev": prior["macd_hist"] if prior else None,
            "trend_events": trend_events,
            "near_52w_high": near_high,
            "near_52w_low": near_low,
            "rs_rating": rs.get("rs_rating"),
            "return_1w": rs.get("return_1w"),
            "return_1m": rs.get("return_1m"),
            "has_fno": buildup is not None or pcr is not None,
            "fno_buildup_type": buildup["buildup_type"] if buildup else None,
            "fno_pcr_oi": pcr["pcr_oi"] if pcr else None,
            "news_items": news.get(instrument_id, []),
            "bulk_block_deals": bulk_block_deals.get(instrument_id, []),
            "fii_dii_net_value_cr": fii_dii_net_value_cr,
            "upcoming_corporate_events": upcoming_events.get(instrument_id, []),
        }

    def _build_long_term_inputs(
        self, instrument_id, fundamentals, pe_ratios, shareholding, consensus, corp_actions, rel_strength
    ) -> dict:
        eps_growth_pct, eps_growth_basis = self._compute_eps_growth(fundamentals.get(instrument_id, []))

        shares = shareholding.get(instrument_id, [])
        current_share = shares[0] if shares else None
        previous_share = shares[1] if len(shares) > 1 else None

        rs = rel_strength.get(instrument_id, {})
        consensus_row = consensus.get(instrument_id, {})

        return {
            "eps_growth_pct": eps_growth_pct,
            "eps_growth_basis": eps_growth_basis,
            "pe_ratio": pe_ratios.get(instrument_id),
            "shareholding_current": current_share,
            "shareholding_previous": previous_share,
            "consensus_rating_bucket": consensus_row.get("consensus_rating_bucket"),
            "implied_upside_pct": consensus_row.get("implied_upside_pct"),
            "corporate_action_types": corp_actions.get(instrument_id, []),
            "rs_rating_1y": rs.get("rs_rating"),
            "return_1y": rs.get("return_1y"),
        }

    @staticmethod
    def _compute_eps_growth(periods: list[dict]) -> tuple[float | None, str | None]:
        """periods: sorted newest-first, deduped consolidated-over-standalone
        (see _fetch_fundamentals). YoY preferred (same reporting_quarter, one
        year prior financial_year); QoQ fallback (immediately prior period).
        None when fewer than 2 comparable periods exist yet — e.g. a recent
        listing, or Phase 3a's board-meeting-driven filing cadence not
        having reached this instrument yet."""
        if len(periods) < 2:
            return None, None

        latest = periods[0]
        if latest["eps"] is None:
            return None, None

        # YoY: same reporting_quarter, financial_year numerically one less
        # (financial_year is free text like "2025-26" — compare the leading
        # 4-digit year token rather than assuming an exact string format).
        def _year_token(fy: str | None) -> int | None:
            if not fy or not fy[:4].isdigit():
                return None
            return int(fy[:4])

        latest_year = _year_token(latest["financial_year"])
        for candidate in periods[1:]:
            if (
                candidate["reporting_quarter"] == latest["reporting_quarter"]
                and latest_year is not None
                and _year_token(candidate["financial_year"]) == latest_year - 1
                and candidate["eps"] is not None
                and candidate["eps"] != 0
            ):
                growth = (latest["eps"] - candidate["eps"]) / abs(candidate["eps"]) * 100
                return growth, "YoY"

        # QoQ fallback: immediately prior period, regardless of quarter label.
        prior = periods[1]
        if prior["eps"] is not None and prior["eps"] != 0:
            growth = (latest["eps"] - prior["eps"]) / abs(prior["eps"]) * 100
            return growth, "QoQ"

        return None, None
