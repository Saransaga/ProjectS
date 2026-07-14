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

-- ============================================================================
-- Domain 5 — Brokerage Recommendations (Phase 5a)
-- Sourced from Moneycontrol's per-stock "Broker Research" section (verified
-- live: real dated calls with brokerage name, rating, reco price, target
-- price, PDF report link) plus Tickertape's server-rendered "Analyst Ratings
-- & Forecast" card (verified live: % buy recommendation + analyst count).
-- Trendlyne — the spec's originally-intended primary source for consensus
-- ratings/targets/upgrade-downgrade history — is dropped from this phase:
-- verified live to sit behind a hard AWS WAF CAPTCHA challenge, not merely
-- flaky/IP-blocked like bse_client.py's endpoints. A plain HTTP client can
-- never pass that wall from any host, so wiring it in would ship permanently
-- dead code rather than a "verify before trusting" caveat. See README.
-- ============================================================================

-- Resolves an instrument to Moneycontrol's own internal stock code + page
-- URL (needed because MC's URLs aren't derivable from the NSE symbol, e.g.
-- Reliance Industries -> /india/stockpricequote/refineries/relianceindustries/RI).
-- Cached here after first resolution so BrokerageCallsJob's daily run only
-- pays the (rate-limited) autosuggest lookup once per instrument, not once
-- per run.
CREATE TABLE IF NOT EXISTS moneycontrol_instrument_map (
    instrument_id   BIGINT PRIMARY KEY REFERENCES instruments(instrument_id),
    mc_sc_id        TEXT NOT NULL,
    mc_page_url     TEXT NOT NULL,
    resolved_at     TIMESTAMPTZ NOT NULL DEFAULT now()
);

-- One row per individual brokerage call, as published on Moneycontrol's
-- stock page. raw_rating is always kept (e.g. "ACCUMULATE", "ADD",
-- "REDUCE") even when rating_bucket can't be confidently classified into
-- the 5-level scale — never dropped, same "OTHER but keep the raw text"
-- spirit as Domain 3's corporate_actions.
CREATE TABLE IF NOT EXISTS brokerage_calls (
    call_id         BIGSERIAL PRIMARY KEY,
    instrument_id   BIGINT NOT NULL REFERENCES instruments(instrument_id),
    brokerage_name  TEXT NOT NULL,
    call_date       DATE NOT NULL,
    raw_rating      TEXT NOT NULL,
    rating_bucket   TEXT CHECK (rating_bucket IN ('STRONG_BUY','BUY','HOLD','SELL','STRONG_SELL')),
    reco_price      NUMERIC(14,4),
    target_price    NUMERIC(14,4),
    report_url      TEXT,
    source          TEXT NOT NULL DEFAULT 'MONEYCONTROL',
    created_at      TIMESTAMPTZ NOT NULL DEFAULT now(),
    UNIQUE (instrument_id, brokerage_name, call_date, source)
);

CREATE INDEX IF NOT EXISTS idx_brokerage_calls_instrument ON brokerage_calls (instrument_id, call_date DESC);

-- One row per detected rating change for a given (instrument, brokerage)
-- pair, computed by BrokerageCallsJob at ingest time by comparing each new
-- call's rating_bucket against that same brokerage's immediately-prior call
-- for the same instrument.
CREATE TABLE IF NOT EXISTS rating_change_events (
    event_id                BIGSERIAL PRIMARY KEY,
    instrument_id           BIGINT NOT NULL REFERENCES instruments(instrument_id),
    brokerage_name          TEXT NOT NULL,
    event_date              DATE NOT NULL,
    change_type             TEXT NOT NULL CHECK (change_type IN ('UPGRADE','DOWNGRADE','INITIATED','REITERATED')),
    previous_rating_bucket  TEXT,
    new_rating_bucket       TEXT NOT NULL,
    previous_target_price   NUMERIC(14,4),
    new_target_price        NUMERIC(14,4),
    source                  TEXT NOT NULL DEFAULT 'MONEYCONTROL',
    created_at               TIMESTAMPTZ NOT NULL DEFAULT now(),
    UNIQUE (instrument_id, brokerage_name, event_date, source)
);

CREATE INDEX IF NOT EXISTS idx_rating_change_events_instrument ON rating_change_events (instrument_id, event_date DESC);
CREATE INDEX IF NOT EXISTS idx_rating_change_events_type ON rating_change_events (change_type, event_date DESC);

-- Daily aggregate snapshot: consensus_rating_bucket/avg_target_price/
-- implied_upside_pct/num_analysts are computed from brokerage_calls (trailing
-- window) + the latest close (ohlcv_daily); tickertape_pct_buy/
-- tickertape_analyst_count are Tickertape's own cross-check numbers, kept as
-- separate columns rather than blended into num_analysts/consensus_rating_bucket
-- since the two sources count "analysts" differently and disagreement between
-- them is itself useful signal, not noise to average away.
CREATE TABLE IF NOT EXISTS consensus_ratings (
    instrument_id             BIGINT NOT NULL REFERENCES instruments(instrument_id),
    as_of_date                DATE NOT NULL,
    consensus_rating_bucket   TEXT CHECK (consensus_rating_bucket IN ('STRONG_BUY','BUY','HOLD','SELL','STRONG_SELL')),
    num_analysts               INTEGER,
    avg_target_price          NUMERIC(14,4),
    implied_upside_pct        NUMERIC(8,4),
    tickertape_pct_buy        NUMERIC(6,3),
    tickertape_analyst_count  INTEGER,
    computed_at               TIMESTAMPTZ NOT NULL DEFAULT now(),
    PRIMARY KEY (instrument_id, as_of_date)
);

-- ============================================================================
-- Domain 6 — Momentum & Market Microstructure (Phase 6a)
-- All sources here are NSE's own unauthenticated static archives
-- (nsearchives.nseindia.com) or its fiidiiTradeReact interactive endpoint —
-- see nse_client.py / nse_corporate_client.py docstrings for what's verified
-- live. BSE bulk/block deals are dropped from this phase: every guessed
-- api.bseindia.com endpoint returned an ASP.NET error page, not JSON, from
-- this environment (unlike bse_client.py's existing endpoints, which are at
-- least intermittently reachable) — same "don't ship dead code for an
-- unverified endpoint" call as dropping Trendlyne in Domain 5. Trendlyne
-- (the spec's RS-Rating/momentum-score source) is dropped for the same
-- AWS-WAF-CAPTCHA reason already documented in Domain 5's section above.
-- ============================================================================

-- NSE's daily cash-market (equity segment) FII/DII net buy/sell, from
-- fiidiiTradeReact. This is turnover value in Rs. crore, provisional and
-- published once daily — NOT a point-in-time-queryable history (the
-- endpoint only ever returns "the latest published day", see
-- FiiDiiFlowsJob). Weekly/monthly cumulative flows are a SUM(net_value_cr)
-- over a date range on this table, not a separately materialized rollup —
-- there's no derived math involved worth precomputing and storing.
CREATE TABLE IF NOT EXISTS fii_dii_cash_flows (
    flow_date       DATE NOT NULL,
    category        TEXT NOT NULL CHECK (category IN ('FII','DII')),
    buy_value_cr    NUMERIC(14,2) NOT NULL,
    sell_value_cr   NUMERIC(14,2) NOT NULL,
    net_value_cr    NUMERIC(14,2) NOT NULL,
    source          TEXT NOT NULL DEFAULT 'NSE',
    created_at      TIMESTAMPTZ NOT NULL DEFAULT now(),
    PRIMARY KEY (flow_date, category)
);

-- NSE's "Participant wise Open Interest in Equity Derivatives" daily CSV —
-- the closest free, legitimate proxy for "FII/DII activity in the F&O
-- segment": NSE does not publish a free FII/DII net-buy/sell *turnover*
-- figure for F&O the way fiidiiTradeReact does for cash, only end-of-day
-- *open interest* by participant type and contract category. Day-over-day
-- deltas in these columns are what analysts actually use as the F&O-segment
-- read on institutional positioning — don't mistake open_interest here for
-- a turnover/value figure, it's a contract count.
CREATE TABLE IF NOT EXISTS fno_participant_oi (
    oi_date                    DATE NOT NULL,
    client_type                TEXT NOT NULL CHECK (client_type IN ('CLIENT','DII','FII','PRO')),
    fut_index_long             BIGINT,
    fut_index_short            BIGINT,
    fut_stock_long             BIGINT,
    fut_stock_short            BIGINT,
    opt_index_call_long        BIGINT,
    opt_index_put_long         BIGINT,
    opt_index_call_short       BIGINT,
    opt_index_put_short        BIGINT,
    opt_stock_call_long        BIGINT,
    opt_stock_put_long         BIGINT,
    opt_stock_call_short       BIGINT,
    opt_stock_put_short        BIGINT,
    total_long_contracts       BIGINT,
    total_short_contracts      BIGINT,
    source                     TEXT NOT NULL DEFAULT 'NSE',
    created_at                 TIMESTAMPTZ NOT NULL DEFAULT now(),
    PRIMARY KEY (oi_date, client_type)
);

-- NSE-only (see section header). bulk.csv/block.csv each only ever serve
-- "today's" deals (no date-range param, like corporate_actions), so a
-- symbol/date/client/qty/price natural key is the only available dedup —
-- a re-poll within the same day's 2 intraday windows just re-upserts
-- deals already seen.
CREATE TABLE IF NOT EXISTS bulk_block_deals (
    deal_id         BIGSERIAL PRIMARY KEY,
    instrument_id   BIGINT NOT NULL REFERENCES instruments(instrument_id),
    deal_date       DATE NOT NULL,
    deal_type       TEXT NOT NULL CHECK (deal_type IN ('BULK','BLOCK')),
    client_name     TEXT NOT NULL,
    buy_sell        TEXT NOT NULL CHECK (buy_sell IN ('BUY','SELL')),
    quantity        BIGINT NOT NULL,
    trade_price     NUMERIC(14,4),
    source          TEXT NOT NULL DEFAULT 'NSE',
    created_at      TIMESTAMPTZ NOT NULL DEFAULT now(),
    UNIQUE (instrument_id, deal_date, deal_type, client_name, buy_sell, quantity, trade_price)
);

CREATE INDEX IF NOT EXISTS idx_bulk_block_deals_instrument ON bulk_block_deals (instrument_id, deal_date DESC);

-- One row per F&O contract per day, from NSE's daily F&O bhavcopy (same
-- UDiFF zip format as nse_client.py's equity bhavcopy, just the FO segment).
-- underlying_symbol is always populated from the bhavcopy's own TckrSymb;
-- instrument_id is only resolved for stock underlyings (STO/STF), where
-- TckrSymb matches instruments.symbol exactly — index underlyings (IDO/IDF,
-- e.g. "NIFTY", "BANKNIFTY") have no matching row in `instruments` (which
-- only carries "Nifty 50"/"Nifty Bank" from Domain 1's index_eod job, a
-- different naming convention), so instrument_id stays NULL for those and
-- underlying_symbol is the only reliable join key. option_type/strike_price
-- are NULL for futures rows — the dedup index below COALESCEs them, same
-- technique as Domain 3's corporate_actions dedup index.
CREATE TABLE IF NOT EXISTS fno_bhavcopy_daily (
    trade_date          DATE NOT NULL,
    underlying_symbol   TEXT NOT NULL,
    underlying_type     TEXT NOT NULL CHECK (underlying_type IN ('STOCK','INDEX')),
    instrument_id       BIGINT REFERENCES instruments(instrument_id),
    contract_type       TEXT NOT NULL CHECK (contract_type IN ('FUT','OPT')),
    expiry_date         DATE NOT NULL,
    option_type         TEXT CHECK (option_type IN ('CE','PE')),
    strike_price        NUMERIC(14,4),
    open_price          NUMERIC(14,4),
    high_price          NUMERIC(14,4),
    low_price           NUMERIC(14,4),
    close_price         NUMERIC(14,4),
    settle_price        NUMERIC(14,4),
    prev_close          NUMERIC(14,4),
    underlying_price    NUMERIC(14,4),
    open_interest       BIGINT,
    change_in_oi        BIGINT,
    volume              BIGINT,
    turnover            NUMERIC(20,2),
    trades              INTEGER,
    lot_size            INTEGER,
    source              TEXT NOT NULL DEFAULT 'NSE_BHAVCOPY',
    inserted_at         TIMESTAMPTZ NOT NULL DEFAULT now()
);

SELECT create_hypertable('fno_bhavcopy_daily', 'trade_date',
    chunk_time_interval => INTERVAL '3 months',
    if_not_exists => TRUE);

CREATE UNIQUE INDEX IF NOT EXISTS idx_fno_bhavcopy_dedup ON fno_bhavcopy_daily
    (underlying_symbol, contract_type, expiry_date, COALESCE(option_type, ''), COALESCE(strike_price, -1), trade_date);

CREATE INDEX IF NOT EXISTS idx_fno_bhavcopy_underlying ON fno_bhavcopy_daily (underlying_symbol, trade_date DESC);

-- Derived from fno_bhavcopy_daily by FnoSignalsJob (must run after
-- FnoBhavcopyJob for the same trade_date). One row per underlying+expiry:
-- PCR across that expiry's whole option chain, and the max-pain strike
-- (the strike at which option writers' aggregate payout is smallest).
-- "Market-wide" PCR per the domain spec is just underlying_symbol='NIFTY'
-- here, not a separately stored figure.
CREATE TABLE IF NOT EXISTS fno_signals (
    trade_date          DATE NOT NULL,
    underlying_symbol   TEXT NOT NULL,
    expiry_date         DATE NOT NULL,
    pcr_oi              NUMERIC(10,4),
    pcr_volume          NUMERIC(10,4),
    max_pain_strike     NUMERIC(14,4),
    computed_at         TIMESTAMPTZ NOT NULL DEFAULT now(),
    PRIMARY KEY (underlying_symbol, expiry_date, trade_date)
);

CREATE INDEX IF NOT EXISTS idx_fno_signals_trade_date ON fno_signals (trade_date DESC);

-- Futures-only OI-buildup classification (long/short buildup, long
-- unwinding, short covering) from each underlying's near-month futures
-- contract's day-over-day price and OI change. NULL buildup_type when
-- price or OI is unchanged — there's no bullish/bearish read on a flat
-- session, not a missing-data gap.
CREATE TABLE IF NOT EXISTS fno_oi_buildup (
    trade_date          DATE NOT NULL,
    underlying_symbol   TEXT NOT NULL,
    expiry_date         DATE NOT NULL,
    price_change_pct    NUMERIC(8,4),
    oi_change_pct       NUMERIC(8,4),
    buildup_type        TEXT CHECK (buildup_type IN ('LONG_BUILDUP','SHORT_BUILDUP','LONG_UNWINDING','SHORT_COVERING')),
    computed_at         TIMESTAMPTZ NOT NULL DEFAULT now(),
    PRIMARY KEY (underlying_symbol, expiry_date, trade_date)
);

-- Rollover %: next-month futures OI / (near-month + next-month OI) for each
-- underlying with 2+ live future expiries that day. Only meaningful in the
-- days immediately before near_expiry — early in a contract's life this
-- number is naturally small and isn't a rollover signal yet, it's just the
-- next contract opening up. next_oi/rollover_pct are NULL when there's no
-- next-month contract trading yet (e.g. far out from expiry for some
-- underlyings) rather than assumed zero.
CREATE TABLE IF NOT EXISTS fno_rollover (
    trade_date       DATE NOT NULL,
    underlying_symbol TEXT NOT NULL,
    near_expiry      DATE NOT NULL,
    next_expiry      DATE,
    near_oi          BIGINT NOT NULL,
    next_oi          BIGINT,
    rollover_pct     NUMERIC(8,4),
    computed_at      TIMESTAMPTZ NOT NULL DEFAULT now(),
    PRIMARY KEY (underlying_symbol, trade_date)
);

-- Computed entirely from ohlcv_daily (RelativeStrengthJob reads it directly,
-- no external source) — trailing total return per window, the same
-- window's return relative to Nifty 50, and an IBD-style composite
-- percentile rank. rs_rating's composite is a simplified 40/30/30 blend of
-- 3M/6M/1Y returns (IBD's official formula uses 3/6/9/12M weighted
-- 40/20/20/20; this phase doesn't otherwise need a 9-month return, so
-- substitutes the windows it does need to store — see
-- momentum/relative_strength.py). Sector rotation signals are deferred:
-- `instruments` carries no sector/industry classification in this phase
-- (see README), and fabricating a rotation signal on top of no sector data
-- would be worse than not shipping it.
CREATE TABLE IF NOT EXISTS relative_strength (
    instrument_id            BIGINT NOT NULL REFERENCES instruments(instrument_id),
    trade_date               DATE NOT NULL,
    return_1w                NUMERIC(10,4),
    return_1m                NUMERIC(10,4),
    return_3m                NUMERIC(10,4),
    return_6m                NUMERIC(10,4),
    return_1y                NUMERIC(10,4),
    relative_return_1w       NUMERIC(10,4),
    relative_return_1m       NUMERIC(10,4),
    relative_return_3m       NUMERIC(10,4),
    relative_return_6m       NUMERIC(10,4),
    relative_return_1y       NUMERIC(10,4),
    rs_rating                SMALLINT,
    computed_at              TIMESTAMPTZ NOT NULL DEFAULT now(),
    PRIMARY KEY (instrument_id, trade_date)
);

SELECT create_hypertable('relative_strength', 'trade_date',
    chunk_time_interval => INTERVAL '6 months',
    if_not_exists => TRUE);
