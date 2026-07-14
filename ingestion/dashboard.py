"""Minimal operational dashboard: browse the DB, see job status, trigger a run.
Runs as its own service (see docker-compose.yml) on the same image as the
ingestion daemon, so it reuses the same job classes and DB connection code."""

from datetime import date

import pandas as pd
import psycopg2
import streamlit as st

from ingestion.config import config
from ingestion.jobs.brokerage_calls import BrokerageCallsJob
from ingestion.jobs.bse_announcements import BseAnnouncementsJob
from ingestion.jobs.bulk_block_deals import BulkBlockDealsJob
from ingestion.jobs.candlestick_patterns import CandlestickPatternsJob
from ingestion.jobs.consensus_ratings import ConsensusRatingsJob
from ingestion.jobs.corporate_actions import CorporateActionsJob
from ingestion.jobs.corporate_calendar import CorporateCalendarJob
from ingestion.jobs.deliverable_volume import DeliverableVolumeJob
from ingestion.jobs.equity_eod import EquityEodJob
from ingestion.jobs.fii_dii_flows import FiiDiiFlowsJob
from ingestion.jobs.financial_results import FinancialResultsJob
from ingestion.jobs.fno_bhavcopy import FnoBhavcopyJob
from ingestion.jobs.fno_signals import FnoSignalsJob
from ingestion.jobs.fundamental_ratios import FundamentalRatiosJob
from ingestion.jobs.index_eod import IndexEodJob
from ingestion.jobs.index_rebalancing import IndexRebalancingScheduleJob
from ingestion.jobs.ipo_listings import IpoListingsJob
from ingestion.jobs.nse_announcements import NseAnnouncementsJob
from ingestion.jobs.reddit_sentiment import RedditSentimentJob
from ingestion.jobs.relative_strength import RelativeStrengthJob
from ingestion.jobs.rss_news import RssNewsJob
from ingestion.jobs.shareholding_pattern import ShareholdingPatternJob
from ingestion.jobs.signal_events import SignalEventsJob
from ingestion.jobs.technical_indicators import TechnicalIndicatorsJob

st.set_page_config(page_title="Trading Data Pipeline", layout="wide")

JOBS = {
    "equity": EquityEodJob,
    "index": IndexEodJob,
    "technical_indicators": TechnicalIndicatorsJob,
    "candlestick_patterns": CandlestickPatternsJob,
    "signal_events": SignalEventsJob,
    "corporate_actions": CorporateActionsJob,
    "shareholding_pattern": ShareholdingPatternJob,
    "financial_results": FinancialResultsJob,
    "fundamental_ratios": FundamentalRatiosJob,
    "nse_announcements": NseAnnouncementsJob,
    "bse_announcements": BseAnnouncementsJob,
    "rss_news": RssNewsJob,
    "reddit_sentiment": RedditSentimentJob,
    "brokerage_calls": BrokerageCallsJob,
    "consensus_ratings": ConsensusRatingsJob,
    "fii_dii_flows": FiiDiiFlowsJob,
    "bulk_block_deals": BulkBlockDealsJob,
    "fno_bhavcopy": FnoBhavcopyJob,
    "fno_signals": FnoSignalsJob,
    "deliverable_volume": DeliverableVolumeJob,
    "relative_strength": RelativeStrengthJob,
    "corporate_calendar": CorporateCalendarJob,
    "ipo_listings": IpoListingsJob,
    "index_rebalancing_schedule": IndexRebalancingScheduleJob,
}

# table -> (date column to sort/filter by, symbol-filter mode: None = no
# filter, "instrument" = join instruments on instrument_id, "underlying" =
# filter directly on the table's own underlying_symbol column — used by the
# Domain 6 F&O tables, which key on underlying_symbol text rather than a
# resolved instrument_id (see init.sql's fno_bhavcopy_daily comment: index
# underlyings like NIFTY never resolve to an instruments row, so an INNER
# JOIN would silently drop them).
TABLES = {
    "instruments": (None, None),
    "ohlcv_daily": ("trade_date", "instrument"),
    "technical_indicators_daily": ("trade_date", "instrument"),
    "candlestick_patterns_daily": ("trade_date", "instrument"),
    "signal_events": ("event_date", "instrument"),
    "support_resistance_levels": ("computed_date", "instrument"),
    "corporate_actions": ("ex_date", "instrument"),
    "shareholding_pattern": ("period_end_date", "instrument"),
    "fundamentals_quarterly": ("period_end_date", "instrument"),
    "fundamental_ratios": ("as_of_date", "instrument"),
    "news_items": ("published_at", None),
    "brokerage_calls": ("call_date", "instrument"),
    "rating_change_events": ("event_date", "instrument"),
    "consensus_ratings": ("as_of_date", "instrument"),
    "fii_dii_cash_flows": ("flow_date", None),
    "fno_participant_oi": ("oi_date", None),
    "bulk_block_deals": ("deal_date", "instrument"),
    "fno_bhavcopy_daily": ("trade_date", "underlying"),
    "fno_signals": ("trade_date", "underlying"),
    "fno_oi_buildup": ("trade_date", "underlying"),
    "fno_rollover": ("trade_date", "underlying"),
    "relative_strength": ("trade_date", "instrument"),
    "corporate_calendar": ("event_date", "instrument"),
    "ipo_listings": ("issue_start_date", "symbol"),
    "index_rebalancing_schedule": ("updated_at", None),
    "macro_events": ("event_date", None),
    "ingestion_log": ("run_date", None),
}


@st.cache_resource
def get_connection():
    conn = psycopg2.connect(
        host=config.POSTGRES_HOST,
        port=config.POSTGRES_PORT,
        user=config.POSTGRES_USER,
        password=config.POSTGRES_PASSWORD,
        dbname=config.POSTGRES_DB,
    )
    conn.autocommit = True
    return conn


def run_query(sql: str, params=None) -> pd.DataFrame:
    return pd.read_sql(sql, get_connection(), params=params)


st.title("Trading Data Pipeline")

tab_overview, tab_jobs, tab_browse = st.tabs(["Overview", "Run Jobs", "Browse Data"])

with tab_overview:
    col1, col2, col3, col4 = st.columns(4)
    col1.metric("Instruments", int(run_query("SELECT count(*) c FROM instruments").iloc[0]["c"]))
    col2.metric("Latest OHLCV date", str(run_query("SELECT max(trade_date) d FROM ohlcv_daily").iloc[0]["d"]))
    col3.metric(
        "Latest indicators date",
        str(run_query("SELECT max(trade_date) d FROM technical_indicators_daily").iloc[0]["d"]),
    )
    col4.metric("Signal events (total)", int(run_query("SELECT count(*) c FROM signal_events").iloc[0]["c"]))

    st.subheader("Latest run per job")
    st.dataframe(
        run_query(
            """
            SELECT DISTINCT ON (job_name) job_name, run_date, status, rows_ingested, error, finished_at
            FROM ingestion_log
            ORDER BY job_name, run_date DESC
            """
        ),
        use_container_width=True,
    )

    st.caption(
        "Automatic daily schedule (runs inside the `ingestion` service, 16:00 IST): "
        "equity → index → technical_indicators → candlestick_patterns → signal_events."
    )

with tab_jobs:
    st.subheader("Run a job now")
    col1, col2, col3 = st.columns(3)
    job_name = col1.selectbox("Job", list(JOBS))
    run_date = col2.date_input("Date", value=date.today())
    force = col3.checkbox("Force re-run")

    if st.button("Run"):
        with st.spinner(f"Running {job_name} for {run_date}..."):
            status = JOBS[job_name]().run(run_date, force=force)
        st.success(f"{job_name} {run_date} -> {status}")

    st.subheader("Recent job runs")
    st.dataframe(
        run_query(
            "SELECT job_name, run_date, status, rows_ingested, error, started_at, finished_at "
            "FROM ingestion_log ORDER BY started_at DESC LIMIT 100"
        ),
        use_container_width=True,
    )

with tab_browse:
    table = st.selectbox("Table", list(TABLES))
    symbol = st.text_input("Filter by symbol (optional)")
    limit = st.number_input("Row limit", value=200, min_value=10, max_value=5000)

    date_col, symbol_mode = TABLES[table]
    sql = f"SELECT t.* FROM {table} t"
    params = []
    if symbol_mode == "instrument":
        sql += " JOIN instruments i USING (instrument_id)"
        if symbol:
            sql += " WHERE i.symbol ILIKE %s"
            params.append(f"%{symbol}%")
    elif symbol_mode == "underlying" and symbol:
        sql += " WHERE t.underlying_symbol ILIKE %s"
        params.append(f"%{symbol}%")
    elif symbol_mode == "symbol" and symbol:
        # ipo_listings carries its own symbol column rather than a resolved
        # instrument_id (mid-bidding stocks have no instruments row yet, see
        # init.sql's ipo_listings comment) — filter directly, no join.
        sql += " WHERE t.symbol ILIKE %s"
        params.append(f"%{symbol}%")
    if date_col:
        sql += f" ORDER BY t.{date_col} DESC"
    sql += " LIMIT %s"
    params.append(int(limit))

    st.dataframe(run_query(sql, params), use_container_width=True)
