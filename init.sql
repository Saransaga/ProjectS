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

-- ============================================================================
-- Domain 3 — Fundamental Data (Phase 3a)
-- Sourced from NSE's corporate-filings APIs (corporate actions, board
-- meetings, shareholding pattern, financial-results XBRL). See
-- ingestion/ingestion/nse_corporate_client.py for the source endpoints and
-- README.md for what's deferred to Phase 3b (full income statement/balance
-- sheet/cash flow, ROE/ROCE/ROA, P/B, EV/EBITDA, P/FCF, Forward P/E).
-- ============================================================================

-- One row per corporate action, best-effort classified from NSE's free-text
-- subject line (e.g. "Dividend - Rs 2 Per Share", "Bonus 1:1").
CREATE TABLE IF NOT EXISTS corporate_actions (
    action_id          BIGSERIAL PRIMARY KEY,
    instrument_id       BIGINT NOT NULL REFERENCES instruments(instrument_id),
    ex_date             DATE,
    record_date         DATE,
    action_type         TEXT CHECK (action_type IN ('DIVIDEND','BONUS','SPLIT','BUYBACK','RIGHTS','OTHER')),
    amount_per_share    NUMERIC(14,4),
    ratio_new           INTEGER,
    ratio_old           INTEGER,
    face_value_from     NUMERIC(10,2),
    face_value_to       NUMERIC(10,2),
    raw_subject         TEXT NOT NULL,
    series              TEXT,
    source              TEXT NOT NULL DEFAULT 'NSE',
    created_at          TIMESTAMPTZ NOT NULL DEFAULT now()
);

-- A plain UNIQUE(instrument_id, ex_date, raw_subject) can't dedup a pending
-- action NSE hasn't dated yet (ex_date NULL) — Postgres treats NULL <> NULL
-- for uniqueness, so CorporateActionsJob's daily re-fetch of "whatever's
-- current" would insert a fresh duplicate row every day until NSE publishes
-- an ex-date. COALESCE to a fixed sentinel so NULL participates too.
CREATE UNIQUE INDEX IF NOT EXISTS idx_corporate_actions_dedup
    ON corporate_actions (instrument_id, COALESCE(ex_date, DATE '0001-01-01'), raw_subject);

CREATE INDEX IF NOT EXISTS idx_corporate_actions_instrument ON corporate_actions (instrument_id, ex_date DESC);
CREATE INDEX IF NOT EXISTS idx_corporate_actions_type ON corporate_actions (action_type, ex_date DESC);

-- Promoter %/Public % come straight off NSE's bulk shareholding-pattern list
-- (no XBRL parsing needed); FII/DII/pledged % require parsing the dimensional
-- shareholding-pattern XBRL and are populated best-effort — may be NULL.
CREATE TABLE IF NOT EXISTS shareholding_pattern (
    instrument_id         BIGINT NOT NULL REFERENCES instruments(instrument_id),
    period_end_date       DATE NOT NULL,
    promoter_pct          NUMERIC(6,3),
    public_pct            NUMERIC(6,3),
    fii_pct               NUMERIC(6,3),
    dii_pct               NUMERIC(6,3),
    pledged_promoter_pct  NUMERIC(6,3),
    submission_date       DATE,
    xbrl_url              TEXT,
    source                TEXT NOT NULL DEFAULT 'NSE',
    created_at            TIMESTAMPTZ NOT NULL DEFAULT now(),
    PRIMARY KEY (instrument_id, period_end_date)
);

-- Quarterly P&L line items pulled from the `in-bse-fin` XBRL taxonomy.
-- ebitda_derived is a standard reconciliation (PBT + finance costs +
-- depreciation - other income), not a disclosed figure.
-- CAVEAT (verified against a real filing, not assumed): debt_to_equity and
-- interest_coverage_ratio are tagged directly in the XBRL, but they are the
-- SEBI LODR Reg 52(4) ratios scoped to *listed debt securities* (NCDs/bonds)
-- only, not the company's overall debt position. A company with no listed
-- bonds will show ~0 here even if genuinely leveraged — do not treat these
-- as general leverage/quality signals without checking the company actually
-- has listed debt securities. General D/E needs the (annual-only) balance
-- sheet — see README, deferred to Phase 3b.
-- No balance sheet/cash flow columns here: SEBI LODR Reg 33 only requires
-- those with annual results, not quarterly (see README).
CREATE TABLE IF NOT EXISTS fundamentals_quarterly (
    instrument_id            BIGINT NOT NULL REFERENCES instruments(instrument_id),
    period_end_date          DATE NOT NULL,
    financial_year           TEXT,
    reporting_quarter        TEXT,
    consolidated             BOOLEAN NOT NULL,
    revenue                  NUMERIC(20,2),
    pat                      NUMERIC(20,2),
    eps_basic                NUMERIC(10,4),
    eps_diluted               NUMERIC(10,4),
    debt_to_equity           NUMERIC(10,4),
    interest_coverage_ratio  NUMERIC(10,4),
    ebitda_derived           NUMERIC(20,2),
    shares_outstanding       BIGINT,  -- derived: paid-up capital / face value, for P/S
    broadcast_date           TIMESTAMPTZ,
    xbrl_url                 TEXT,
    source                   TEXT NOT NULL DEFAULT 'NSE',
    created_at               TIMESTAMPTZ NOT NULL DEFAULT now(),
    PRIMARY KEY (instrument_id, period_end_date, consolidated)
);

-- Recomputed weekly from fundamentals_quarterly + latest close (ohlcv_daily)
-- + trailing dividends (corporate_actions). The Phase-3b-only columns
-- (pb_ratio, ev_ebitda, pfcf_ratio, forward_pe, roe, roce, roa) are created
-- now so this table won't need an ALTER later — they stay NULL until 3b.
CREATE TABLE IF NOT EXISTS fundamental_ratios (
    instrument_id     BIGINT NOT NULL REFERENCES instruments(instrument_id),
    as_of_date        DATE NOT NULL,
    pe_ratio          NUMERIC(12,4),
    ps_ratio          NUMERIC(12,4),
    dividend_yield    NUMERIC(8,4),
    payout_ratio      NUMERIC(8,4),
    pb_ratio          NUMERIC(12,4),
    ev_ebitda         NUMERIC(12,4),
    pfcf_ratio        NUMERIC(12,4),
    forward_pe        NUMERIC(12,4),
    roe               NUMERIC(8,4),
    roce              NUMERIC(8,4),
    roa               NUMERIC(8,4),
    computed_at       TIMESTAMPTZ NOT NULL DEFAULT now(),
    PRIMARY KEY (instrument_id, as_of_date)
);

-- ============================================================================
-- Domain 4 — News & Sentiment (Phase 4a)
-- One unified table across every source type rather than a table per source
-- (the pattern Domains 1-3 used) — the spec wants one sentiment/ticker/
-- urgency treatment across heterogeneous sources, and a "breaking news for
-- ticker X across every source" query is the whole point of this domain.
-- NLP is lightweight by design (see README): alias-matching for ticker tags,
-- a small hand-curated keyword lexicon for sentiment — not a trained NER/
-- FinBERT model.
-- ============================================================================

CREATE TABLE IF NOT EXISTS news_items (
    news_item_id              BIGSERIAL PRIMARY KEY,
    source_type                TEXT NOT NULL CHECK (source_type IN (
                                    'NSE_ANNOUNCEMENT', 'BSE_ANNOUNCEMENT',
                                    'RSS_ET_MARKETS', 'RSS_MONEYCONTROL_BUSINESS',
                                    'RSS_MONEYCONTROL_MARKETS', 'RSS_MINT',
                                    'RSS_GOOGLE_NEWS', 'RSS_BUSINESS_STANDARD',
                                    'REDDIT'
                                )),
    -- Source's own dedup key: NSE seq_id, RSS item guid/link, Reddit post id.
    external_id                 TEXT NOT NULL,
    headline                    TEXT NOT NULL,
    summary                     TEXT,
    url                         TEXT,
    published_at                TIMESTAMPTZ,
    fetched_at                  TIMESTAMPTZ NOT NULL DEFAULT now(),
    sentiment_label              TEXT CHECK (sentiment_label IN ('POSITIVE', 'NEGATIVE', 'NEUTRAL')),
    sentiment_score               NUMERIC(5,4),  -- -1 (very negative) .. 1 (very positive)
    urgency                     TEXT CHECK (urgency IN ('BREAKING', 'ROUTINE')),
    relevance_score              NUMERIC(5,4),   -- 0..1, company-specific scores higher than generic market news
    source_credibility_weight     NUMERIC(4,3),  -- static per source_type, see news/classify.py
    created_at                  TIMESTAMPTZ NOT NULL DEFAULT now(),
    UNIQUE (source_type, external_id)
);

CREATE INDEX IF NOT EXISTS idx_news_items_published ON news_items (published_at DESC);
CREATE INDEX IF NOT EXISTS idx_news_items_urgency ON news_items (urgency, published_at DESC);

-- Many-to-many: one article can name several companies (e.g. an M&A story).
-- Keyed instrument-first since "recent news for ticker X" is the primary
-- access pattern this table exists to serve.
CREATE TABLE IF NOT EXISTS news_item_tickers (
    instrument_id   BIGINT NOT NULL REFERENCES instruments(instrument_id),
    news_item_id    BIGINT NOT NULL REFERENCES news_items(news_item_id) ON DELETE CASCADE,
    PRIMARY KEY (instrument_id, news_item_id)
);

CREATE INDEX IF NOT EXISTS idx_news_item_tickers_item ON news_item_tickers (news_item_id);
