CREATE EXTENSION IF NOT EXISTS timescaledb;

CREATE TABLE IF NOT EXISTS instruments (
    instrument_id   BIGSERIAL PRIMARY KEY,
    symbol          TEXT NOT NULL,
    exchange        TEXT NOT NULL DEFAULT 'NSE',
    instrument_type TEXT NOT NULL CHECK (instrument_type IN ('EQUITY','INDEX')),
    series          TEXT,
    name            TEXT,
    isin            TEXT,
    first_seen_date DATE NOT NULL,
    last_seen_date  DATE NOT NULL,
    is_active       BOOLEAN NOT NULL DEFAULT TRUE,
    created_at      TIMESTAMPTZ NOT NULL DEFAULT now(),
    updated_at      TIMESTAMPTZ NOT NULL DEFAULT now(),
    UNIQUE (exchange, symbol, instrument_type)
);

CREATE TABLE IF NOT EXISTS ohlcv_daily (
    instrument_id BIGINT NOT NULL REFERENCES instruments(instrument_id),
    trade_date    DATE   NOT NULL,
    open          NUMERIC(14,4) NOT NULL,
    high          NUMERIC(14,4) NOT NULL,
    low           NUMERIC(14,4) NOT NULL,
    close         NUMERIC(14,4) NOT NULL,
    prev_close    NUMERIC(14,4),
    volume        BIGINT,
    turnover      NUMERIC(20,2),
    trades        INTEGER,
    delivery_qty  BIGINT,
    delivery_pct  NUMERIC(6,2),
    source        TEXT NOT NULL DEFAULT 'NSE_BHAVCOPY',
    inserted_at   TIMESTAMPTZ NOT NULL DEFAULT now(),
    PRIMARY KEY (instrument_id, trade_date)
);

SELECT create_hypertable('ohlcv_daily', 'trade_date',
    chunk_time_interval => INTERVAL '6 months',
    if_not_exists => TRUE);

CREATE TABLE IF NOT EXISTS ingestion_log (
    log_id        BIGSERIAL PRIMARY KEY,
    job_name      TEXT NOT NULL,
    run_date      DATE NOT NULL,
    status        TEXT NOT NULL CHECK (status IN ('RUNNING','SUCCESS','FAILED','SKIPPED')),
    rows_ingested INTEGER,
    error         TEXT,
    started_at    TIMESTAMPTZ NOT NULL DEFAULT now(),
    finished_at   TIMESTAMPTZ,
    UNIQUE (job_name, run_date)
);

CREATE MATERIALIZED VIEW IF NOT EXISTS ohlcv_weekly
WITH (timescaledb.continuous) AS
SELECT
    instrument_id,
    time_bucket('1 week', trade_date, origin => DATE '2000-01-03') AS week_start,
    first(open, trade_date)  AS open,
    max(high)                AS high,
    min(low)                 AS low,
    last(close, trade_date)  AS close,
    sum(volume)               AS volume,
    sum(turnover)             AS turnover,
    sum(trades)               AS trades,
    count(*)                  AS trading_days
FROM ohlcv_daily
GROUP BY instrument_id, time_bucket('1 week', trade_date, origin => DATE '2000-01-03')
WITH NO DATA;

DO $$
BEGIN
    PERFORM add_continuous_aggregate_policy('ohlcv_weekly',
        start_offset => INTERVAL '1 month',
        end_offset => INTERVAL '1 day',
        schedule_interval => INTERVAL '1 day');
EXCEPTION WHEN OTHERS THEN
    NULL;
END $$;
