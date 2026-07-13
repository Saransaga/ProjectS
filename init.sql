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

-- ============================================================================
-- Domain 2 — Technical Indicators & Price Patterns
-- Pre-computed daily from ohlcv_daily by the `ingestion` service's analytics
-- jobs (technical_indicators, candlestick_patterns, signal_events). Never
-- recomputed at query time.
-- ============================================================================

CREATE TABLE IF NOT EXISTS technical_indicators_daily (
    instrument_id         BIGINT NOT NULL REFERENCES instruments(instrument_id),
    trade_date            DATE   NOT NULL,

    -- Trend
    ema_9                 NUMERIC(14,4),
    ema_21                NUMERIC(14,4),
    ema_50                NUMERIC(14,4),
    ema_100               NUMERIC(14,4),
    ema_200               NUMERIC(14,4),
    sma_20                NUMERIC(14,4),
    sma_50                NUMERIC(14,4),
    sma_200               NUMERIC(14,4),
    adx_14                NUMERIC(10,4),
    supertrend_7_3        NUMERIC(14,4),
    supertrend_direction  TEXT CHECK (supertrend_direction IN ('UP','DOWN')),
    ichimoku_tenkan       NUMERIC(14,4),
    ichimoku_kijun        NUMERIC(14,4),
    ichimoku_senkou_a     NUMERIC(14,4),
    ichimoku_senkou_b     NUMERIC(14,4),
    ichimoku_chikou       NUMERIC(14,4),

    -- Momentum
    rsi_14                NUMERIC(10,4),
    macd                  NUMERIC(14,4),
    macd_signal           NUMERIC(14,4),
    macd_hist             NUMERIC(14,4),
    stoch_k               NUMERIC(10,4),
    stoch_d               NUMERIC(10,4),
    roc_12                NUMERIC(10,4),
    cci_14                NUMERIC(14,4),

    -- Volume
    obv                   BIGINT,
    vwap_20               NUMERIC(14,4),
    volume_sma_20         BIGINT,
    mfi_14                NUMERIC(10,4),

    -- Volatility
    bb_upper              NUMERIC(14,4),
    bb_mid                NUMERIC(14,4),
    bb_lower              NUMERIC(14,4),
    atr_14                NUMERIC(14,4),
    keltner_upper         NUMERIC(14,4),
    keltner_mid           NUMERIC(14,4),
    keltner_lower         NUMERIC(14,4),

    computed_at           TIMESTAMPTZ NOT NULL DEFAULT now(),
    PRIMARY KEY (instrument_id, trade_date)
);

SELECT create_hypertable('technical_indicators_daily', 'trade_date',
    chunk_time_interval => INTERVAL '6 months',
    if_not_exists => TRUE);

CREATE TABLE IF NOT EXISTS candlestick_patterns_daily (
    instrument_id            BIGINT NOT NULL REFERENCES instruments(instrument_id),
    trade_date                DATE   NOT NULL,
    -- TA-Lib CDL* raw output: positive = bullish signal, negative = bearish,
    -- 0 = pattern not present. Magnitude (100/200) reflects TA-Lib's own
    -- confidence weighting for that pattern.
    cdl_doji                  SMALLINT,
    cdl_engulfing              SMALLINT,
    cdl_hammer                SMALLINT,
    cdl_shooting_star          SMALLINT,
    cdl_morning_star           SMALLINT,
    cdl_evening_star           SMALLINT,
    cdl_harami                 SMALLINT,
    cdl_three_white_soldiers   SMALLINT,
    cdl_three_black_crows      SMALLINT,
    computed_at                TIMESTAMPTZ NOT NULL DEFAULT now(),
    PRIMARY KEY (instrument_id, trade_date)
);

SELECT create_hypertable('candlestick_patterns_daily', 'trade_date',
    chunk_time_interval => INTERVAL '6 months',
    if_not_exists => TRUE);

CREATE TABLE IF NOT EXISTS signal_events (
    event_id      BIGSERIAL PRIMARY KEY,
    instrument_id BIGINT NOT NULL REFERENCES instruments(instrument_id),
    event_date    DATE   NOT NULL,
    event_type    TEXT NOT NULL CHECK (event_type IN
                      ('BREAKOUT', 'BREAKDOWN', 'HIGH_52W_PROXIMITY', 'LOW_52W_PROXIMITY',
                       'GOLDEN_CROSS', 'DEATH_CROSS')),
    details       JSONB,
    created_at    TIMESTAMPTZ NOT NULL DEFAULT now(),
    UNIQUE (instrument_id, event_date, event_type)
);

CREATE INDEX IF NOT EXISTS idx_signal_events_instrument ON signal_events (instrument_id, event_date DESC);
CREATE INDEX IF NOT EXISTS idx_signal_events_type ON signal_events (event_type, event_date DESC);

CREATE TABLE IF NOT EXISTS support_resistance_levels (
    level_id          BIGSERIAL PRIMARY KEY,
    instrument_id     BIGINT NOT NULL REFERENCES instruments(instrument_id),
    level_type        TEXT NOT NULL CHECK (level_type IN ('SUPPORT', 'RESISTANCE')),
    price_level       NUMERIC(14,4) NOT NULL,
    strength          INTEGER NOT NULL,
    first_touch_date  DATE NOT NULL,
    last_touch_date   DATE NOT NULL,
    -- Recomputed in full each EOD run: the job deletes an instrument's prior
    -- rows and reinserts the freshly clustered set, stamped with the date it
    -- ran (not a per-level history).
    computed_date     DATE NOT NULL,
    created_at        TIMESTAMPTZ NOT NULL DEFAULT now()
);

CREATE INDEX IF NOT EXISTS idx_sr_levels_instrument_computed ON support_resistance_levels (instrument_id, computed_date DESC);
