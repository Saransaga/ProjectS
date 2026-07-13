"""Minimal operational dashboard: browse the DB, see job status, trigger a run.
Runs as its own service (see docker-compose.yml) on the same image as the
ingestion daemon, so it reuses the same job classes and DB connection code."""

from datetime import date

import pandas as pd
import psycopg2
import streamlit as st

from ingestion.config import config
from ingestion.jobs.candlestick_patterns import CandlestickPatternsJob
from ingestion.jobs.equity_eod import EquityEodJob
from ingestion.jobs.index_eod import IndexEodJob
from ingestion.jobs.signal_events import SignalEventsJob
from ingestion.jobs.technical_indicators import TechnicalIndicatorsJob

st.set_page_config(page_title="Trading Data Pipeline", layout="wide")

JOBS = {
    "equity": EquityEodJob,
    "index": IndexEodJob,
    "technical_indicators": TechnicalIndicatorsJob,
    "candlestick_patterns": CandlestickPatternsJob,
    "signal_events": SignalEventsJob,
}

# table -> (date column to sort/filter by, whether it joins to instruments)
TABLES = {
    "instruments": (None, False),
    "ohlcv_daily": ("trade_date", True),
    "technical_indicators_daily": ("trade_date", True),
    "candlestick_patterns_daily": ("trade_date", True),
    "signal_events": ("event_date", True),
    "support_resistance_levels": ("computed_date", True),
    "ingestion_log": ("run_date", False),
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

    date_col, has_instrument = TABLES[table]
    sql = f"SELECT t.* FROM {table} t"
    params = []
    if has_instrument:
        sql += " JOIN instruments i USING (instrument_id)"
        if symbol:
            sql += " WHERE i.symbol ILIKE %s"
            params.append(f"%{symbol}%")
    if date_col:
        sql += f" ORDER BY t.{date_col} DESC"
    sql += " LIMIT %s"
    params.append(int(limit))

    st.dataframe(run_query(sql, params), use_container_width=True)
