# Project Status — NSE/BSE Trading Data Pipeline

_Last updated: 2026-07-14_

A self-hosted market-data pipeline for Indian equities: TimescaleDB + Redis
storage, a Python ingestion service (APScheduler-driven), and a Streamlit
operational dashboard. Built domain-by-domain against a spec that groups
data into 7 "domains." This document summarizes what's actually been
built and verified, what's deliberately dropped/deferred (and why), and
counts the scheduled flows that currently run inside the `ingestion`
container.

Companion docs: [`DATABASE_ERD.md`](./DATABASE_ERD.md) for the full schema
diagram, [`OPERATIONS.md`](./OPERATIONS.md) for the scheduled-downtime
window and a running changelog of fixes/features per session.

---

## 1. What's built, by domain

### Domain 1 — Core price data
- **Tables**: `instruments`, `ohlcv_daily` (TimescaleDB hypertable), `ohlcv_weekly`
  (continuous aggregate), `ingestion_log`.
- **Jobs**: `equity` (NSE equity EOD bhavcopy), `index` (Nifty 50/Nifty Bank;
  Sensex wired in but the BSE index-history endpoint is **unverified/broken**
  from this environment — fails gracefully, logs a warning).
- **Deferred**: intraday timeframes, real-time ticks (needs a broker API), the
  rest of the index list, F&O (that arrived later, in Domain 6), pre-open/
  circuit-limit/Level-2 data.

### Domain 2 — Technical indicators & price patterns
- **Tables**: `technical_indicators_daily` (EMA/SMA/ADX/Supertrend/Ichimoku/
  RSI/MACD/Stochastic/ROC/CCI/OBV/VWAP/MFI/Bollinger/ATR/Keltner),
  `candlestick_patterns_daily` (9 TA-Lib `CDL*` patterns),
  `signal_events` + `support_resistance_levels` (breakout/breakdown, 52-week
  proximity, golden/death cross, pivot-based S/R clustering).
- **Jobs**: `analytics` (technical_indicators → candlestick_patterns →
  signal_events, each depending on the previous).
- **Deferred**: geometric chart-pattern detection (Head & Shoulders, Double
  Top/Bottom, Cup & Handle, Flags/Pennants, Triangles, Wedges) — no standard
  library implementation exists; needs its own design/tuning pass.

### Domain 3 — Fundamental data (Phase 3a)
- **Tables**: `corporate_actions`, `shareholding_pattern`,
  `fundamentals_quarterly`, `fundamental_ratios`.
- **Jobs**: `fundamentals` (corporate_actions, shareholding_pattern,
  financial_results, fundamental_ratios).
- **Known gaps (verified, not assumed)**: `debt_to_equity`/
  `interest_coverage_ratio` are SEBI LODR Reg 52(4) ratios for *listed debt
  securities* only, not general leverage. No balance sheet/cash flow data
  (SEBI LODR Reg 33 — Indian companies only file those annually, not
  quarterly — a disclosure-frequency fact, not a parsing gap).
  `pb_ratio`/`ev_ebitda`/`pfcf_ratio`/`forward_pe`/`roe`/`roce`/`roa` columns
  exist but stay `NULL` until Phase 3b (need annual XBRL / consensus
  estimates).
- **Verified-live caveat**: NSE's interactive `/api/*` corporate-filings
  endpoints sit behind Akamai bot protection; a warm-up cookie makes them
  work, but this class of endpoint is known to be IP-blocked from some
  cloud hosts — if these jobs start failing, a blocked IP is the first
  thing to check.

### Domain 4 — News & sentiment (Phase 4a)
- **Tables**: `news_items` (one unified table across every source type,
  unlike the per-source pattern of Domains 1-3), `news_item_tickers`
  (many-to-many).
- **Jobs**: `announcements` (nse_announcements, bse_announcements — every 5
  min, market hours), `news` (rss_news, reddit_sentiment — every 30 min,
  around the clock).
- **Dropped/flaky**: BSE announcements endpoint is flaky (seen both real
  50-record payloads and empty `{}` bodies in the same session). Business
  Standard's RSS feed is unverified (HTTP 403/Akamai from this
  environment) but stays wired in. Reddit is optional infra — no
  credentials means 0 rows, not a failure.
- **Deferred**: a trained NER/FinBERT sentiment model in place of the
  keyword-lexicon heuristic; any paid-API source.

### Domain 5 — Brokerage recommendations & consensus (Phase 5a)
- **Tables**: `moneycontrol_instrument_map`, `brokerage_calls`,
  `rating_change_events`, `consensus_ratings`.
- **Jobs**: `brokerage` (brokerage_calls, consensus_ratings).
- **Dropped**: **Trendlyne** — the spec's originally-intended primary
  source — sits behind a hard AWS WAF CAPTCHA, verified live; no plain
  HTTP client can ever pass it. This finding recurs and gets re-cited
  (not re-verified) in every later domain that also wanted a Trendlyne
  feed (5, 6, 7).
- **Known limitation**: Tickertape's symbol-search API is IP-blocked, so
  slug resolution is a best-effort guess (`{company-slug}-{NSE_SYMBOL}`),
  sometimes wrong — a failed guess just leaves the two Tickertape-derived
  columns `NULL`, never blocks the Moneycontrol-derived fields.
- **Operational risk observed live**: under a real full-universe backfill,
  Moneycontrol's autosuggest endpoint started returning HTTP 403 after
  only ~4 resolutions in one run — a stalled `moneycontrol_instrument_map`
  count is the first thing to check if this job hangs.

### Domain 6 — Momentum & market microstructure (Phase 6a)
- **Tables**: `fii_dii_cash_flows`, `fno_participant_oi`,
  `bulk_block_deals`, `fno_bhavcopy_daily`, `fno_signals`,
  `fno_oi_buildup`, `fno_rollover`, `relative_strength`.
- **Jobs**: `momentum` (fii_dii_flows, bulk_block_deals, fno_bhavcopy,
  fno_signals, deliverable_volume, relative_strength).
- **Dropped**: BSE bulk/block deals — every guessed `api.bseindia.com`
  endpoint returned an ASP.NET error page, not JSON. Trendlyne again
  (RS-Rating/momentum-score source) — same CAPTCHA wall.
- **Deferred**: sector rotation signals — `instruments` carries no sector/
  industry classification in this phase; fabricating a rotation signal on
  top of no sector data would be worse than not shipping it.

### Domain 7 — Corporate events & calendar (Phase 7a)
- **Tables**: `corporate_calendar`, `ipo_listings`,
  `index_rebalancing_schedule`, `macro_events`.
- **Jobs**: `events` (corporate_calendar, ipo_listings,
  index_rebalancing_schedule).
- **Design note**: ex-dividend/record dates are **not** re-collected here —
  they already live in Domain 3's `corporate_actions`; this domain is
  additive calendar data only.
- **Dropped/verified dead** (each independently re-checked this phase,
  not just assumed from prior findings):
  - RBI MPC schedule — no calendar API; `rbi.org.in`'s "Monetary Policy"
    section is an ASP.NET postback search UI (`GetYearMonth()` sets hidden
    form fields and fires a `__VIEWSTATE` postback), and RBI only ever
    publishes the year's dates in one annual press release.
  - MOSPI release calendar — `mospi.gov.in` is a client-side React shell;
    the raw HTML is a bare `<div id="root">` with zero server content.
  - BSE corporate calendar — Angular SPA, no working API (same conclusion
    as `bse_client.py`'s existing findings).
  - Actual Nifty/Sensex index inclusion/exclusion events — only the
    rebalancing *cadence* is scrapeable (niftyindices.com, static HTML,
    verified live, 215 indices); which stocks actually get added/removed
    each cycle is only published as ad hoc PDFs/press releases, not a feed.
  - Consensus EPS estimates — Trendlyne still dead (see Domain 5).
- **Design consequence**: `macro_events` has **no automated job** — none
  of RBI/MOSPI/Budget expose a scrapeable calendar, matching the domain
  spec's own "manual updates" cadence. Populated via
  `cli.py macro-event add`.
- **Bugs caught during build** (fixed, not just noted): NSE's
  board-meetings feed returns genuine duplicate rows for the same
  (symbol, date, purpose); `IpoListingsJob`'s same-run backfill can target
  the same conflict key as its own fresh-feed fetch. Both caused
  `ON CONFLICT DO UPDATE` cardinality errors until de-duped in
  `upsert_events.py` — caught by actually running the jobs against the
  live DB, not just by code review.

---

## 2. Scheduled flows (as of this write-up)

The `ingestion` service runs one **APScheduler `BlockingScheduler`**
(`ingestion/scheduler.py`) with **13 distinct cron entries**, executing
**27 job classes** in total (some jobs are bundled 2-6 to a slot). All
times are IST. A 14th, always-on process (`telegram-listener`, Domain 8) is
a permanent long-poll loop, not a cron entry — see its own row below the
table.

| # | APScheduler `id` | Cron | Job classes run (in order) |
|---|---|---|---|
| 1 | `daily_eod_ingest` | 16:00 daily | EquityEod, IndexEod, TechnicalIndicators, CandlestickPatterns, SignalEvents |
| 2 | `daily_brokerage_ingest` | 17:00 daily | BrokerageCalls, ConsensusRatings |
| 3 | `daily_momentum_ingest` | 17:15 daily | FnoBhavcopy, FnoSignals, DeliverableVolume, RelativeStrength |
| 4 | `fii_dii_ingest` | 18:00 daily | FiiDiiFlows |
| 5 | `daily_fundamentals_ingest` | 18:30 daily | CorporateActions, FinancialResults |
| 6 | `weekly_fundamentals_ingest` | Sun 20:00 | ShareholdingPattern, FundamentalRatios |
| 7 | `announcements_poll` | every 5 min, 09:00-15:59, Mon-Fri | NseAnnouncements, BseAnnouncements |
| 8 | `news_poll` | every 30 min, every day | RssNews, RedditSentiment |
| 9 | `bulk_block_deals_poll` | 12:00 & 16:00, Mon-Fri | BulkBlockDeals |
| 10 | `daily_events_ingest` | 19:00 daily | CorporateCalendar, IpoListings |
| 11 | `monthly_index_rebalancing` | 1st of month, 09:00 | IndexRebalancingSchedule |
| 12 | `monthly_industry_classification` | 1st of month, 08:30 | IndustryClassification |
| 13 | `daily_recommendation_ingest` | 21:00 daily | RecommendationEngine, TelegramAlerts |

`telegram-listener` (Domain 8) runs as its own always-on `docker-compose`
service, not a cron entry — a Telegram long-poll loop blocks forever by
design, so it can't be modeled as a scheduled tick the way the 13 rows
above are.

Every job also carries `misfire_grace_time` + `coalesce=True` (a missed
tick catches up once, doesn't pile up), and reads/writes its own row in
`ingestion_log` (job_name, run_date, status, rows_ingested, error) — the
dashboard's "Latest run per job" / "Recent job runs" views are just
queries over that table.

**Airflow migration — done, not just planned.** All 13 rows above now also
exist as Airflow DAGs (`airflow/dags/`, one file per row, same names),
verified live end-to-end in this environment: `docker compose up` brings
up a dedicated Airflow (its own Postgres metadata DB, LocalExecutor), each
DAG's tasks use `DockerOperator` to launch a fresh container from the
already-built `project-ingestion` image and call the same CLI — Airflow
only orchestrates, no job logic moved. `cli.py`'s existing `--job` groups
(`equity`/`index`/`analytics`/.../`events`) were too coarse to reuse
as-is — e.g. `--job momentum` bundles `fii_dii_flows` and
`bulk_block_deals` in with the F&O jobs, but `scheduler.py` runs those two
on **separate** schedules (18:00 daily and 12:00/16:00 Mon-Fri
respectively) for real reasons (FII/DII publishes once around 18:00;
bulk/block deals need 2 intraday windows) — so `cli.py` gained single-job
addressing (`--job <job_name>`) and every DAG calls one job by name,
replicating the table above exactly. See `airflow/README.md` for how to
bring it up, two real permission bugs hit and fixed while standing it up
(log-volume ownership, docker-socket group membership), and the cutover
plan from `scheduler.py`.

---

## 3. What's still pending / open

- **No spec provided yet beyond Domain 7.** Everything above is the full
  known scope as of this write-up.
- **Phase 3b** (Domain 3): annual income statement/balance sheet/cash
  flow, YoY/QoQ growth, ROE/ROCE/ROA, P/B, EV/EBITDA, P/FCF, Forward P/E.
- **Chart pattern detection** (Domain 2): needs its own geometric-heuristic
  design pass, not a drop-in library.
- **Sector/industry classification**: `instruments.sector` now exists
  (Domain 8's `IndustryClassificationJob`), but coverage is partial
  (sectoral-index members only) and untuned — sector-rotation signals
  (Domain 6) are still deferred, not unblocked by this alone.
- **Sensex/BSE data generally**: index history, bulk/block deals,
  corporate calendar, and general BSE API reliability are all either
  unverified or confirmed dead in this environment. Every BSE finding
  should be re-verified from a different network/host before assuming
  it's permanently unusable — the recurring failure mode (ASP.NET error
  pages, Angular SPA shells) suggests host/IP-based blocking as much as a
  nonexistent feature.
- **Trendlyne**: hard CAPTCHA wall, re-confirmed dead across 3 domains
  (5, 6, 7). Would need a different integration approach entirely (a
  headless browser solving the CAPTCHA, or a paid API) if this data is
  ever required.
- **RBI/MOSPI macro calendar automation**: genuinely unautomatable via
  free scraping today; `macro_events` is manual-entry only by design.
- **Orchestration**: Airflow DAGs now exist and are verified working
  (`airflow/`) alongside the original `scheduler.py` — see §2 above and
  `airflow/README.md`. Neither system has been turned off yet: DAGs are
  paused by default, and the cutover is meant to happen one DAG at a time
  (unpause, watch it succeed for a few days, then remove that entry from
  `scheduler.py`), not as a single switch-flip. `scheduler.py` should stay
  running until all 13 DAGs have been individually cut over.
- **No alerting configured yet** on the Airflow side (e.g. on-failure
  Slack/email callbacks) — task failures are currently only visible by
  checking the Airflow UI or `ingestion_log`, same visibility gap as
  before for anyone not actively watching either.

### Domain 8 — Recommendation engine & Telegram alerts/Q&A (Phase 8a)
- **Tables**: `stock_recommendations`, `telegram_chats`, `telegram_watchlist`,
  `telegram_watchlist_alert_state`, `telegram_alert_log`. Also adds
  `instruments.sector`/`instruments.industry` (Domain 6's long-deferred
  sector-rotation blocker — only the `sector` column is actually populated;
  see below).
- **Jobs**: `industry_classification` (populates `instruments.sector` from
  NSE Indices' sectoral/thematic-index constituent CSVs — coverage is
  partial by design, only symbols that are members of a curated sectoral
  index get classified), `recommendation_engine` (recomputes a short-term/
  long-term BUY..SELL recommendation per instrument from Domains 1-7's
  tables — see `ingestion/ingestion/recommendation/` for the pure scoring
  functions and `rating_vocabulary.py` for the shared 5-level bucket
  vocabulary also used by Domain 5's consensus ratings), `telegram_alerts`
  (pushes watchlist-change alerts + a daily top-N buy/sell digest to every
  chat that's ever messaged the bot).
- **New always-on process** (not a cron job): `telegram_bot/telegram_listener.py`
  long-polls the Telegram Bot API and answers inbound chat messages —
  `/watch`, `/unwatch`, `/list`, `/recommend`, `/top` (today's top 5
  short-term BUY ideas, on demand), or a bare symbol/company-name lookup
  (resolved via `query/resolve.py`, which reuses Domain 4's
  `news/ticker_matching.normalize_name` for company-name fuzzy matching).
  Runs as its own `docker-compose` service (`telegram-listener`) since a
  long-poll loop is a permanent blocking process, not a scheduled tick.
- **Price targets, exit levels, and a pace estimate**: every recommendation
  (`/recommend`, `/top`, watchlist alerts, the daily digest) now shows a
  direction-aware target/exit price derived from `support_resistance_levels`
  (Domain 2's real pivot-clustered data) — BUY gets nearest resistance as
  target / nearest support as exit trigger, SELL the reverse — falling back
  to an ATR(14)-based projection (`close ± multiple × ATR`, labeled
  `ATR-projected`) when no historical level exists yet (e.g. a breakout to
  a new high). A "time to target" pace estimate (distance ÷ ATR14) is shown
  alongside it, deliberately framed as a pace, not a forecast or a
  fabricated date. See `docs/OPERATIONS.md` for the full changelog.
- **Justification bullets**: the top 2-3 highest-weighted contributing
  factors from the rationale JSONB, rendered as plain English
  (`recommendation/rationale_text.py`).
- **Design notes**:
  - Scoring is 100% deterministic/heuristic (weighted subscores, see
    `recommendation/short_term.py`/`long_term.py`), deliberately no LLM.
  - Short-term now draws on Domains 1/2/4/6/7 (technicals, signal events,
    relative strength/F&O/bulk-block-deals/FII-DII flow, news sentiment,
    upcoming corporate events); long-term on 3/5/6 (fundamentals,
    valuation, shareholding trend, brokerage consensus, relative strength).
    `fii_dii_market_flow` is market-wide (one value shared by every
    instrument that day), so it's excluded from the "do we have enough
    real per-instrument data" gate (`ComponentResult.counts_toward_gate` in
    `aggregate.py`) even though it can still influence the final score —
    otherwise a non-instrument-specific signal could single-handedly fake
    "sufficient data" for a stock with no real coverage at all (caught
    live, see `docs/OPERATIONS.md`).
  - A component subscore is `NULL` only when its source data genuinely
    doesn't exist for that instrument (e.g. no F&O contract, fewer than 2
    shareholding periods) — never a fabricated 0; `aggregate.py` leaves the
    whole composite score `NULL` when fewer than half the weight budget had
    real data, rather than compute from a mostly-missing picture.
  - `TELEGRAM_BOT_TOKEN` is the only new required secret (from
    @BotFather); left unset, both `telegram_alerts` and the listener log a
    clear message and no-op rather than crashing — same graceful-degradation
    pattern as Domain 4's Reddit credentials. There's deliberately no
    hardcoded `TELEGRAM_CHAT_ID` — the broadcast audience is entirely
    DB-driven (`telegram_chats`, auto-populated as chats message the bot),
    since multi-user support is a requirement from day one.
- **Known limitation carried over from Domain 6**: `instruments.industry`
  is deliberately left `NULL` by `industry_classification` — the sectoral
  CSVs' own "Industry" column is actually sector-tier granularity, not
  NSE's finer 4-tier industry scheme, so populating it there would silently
  overstate this source's precision. Sector-rotation signals (deferred in
  Domain 6) are *still* deferred even though `sector` now exists: coverage
  is partial (sectoral-index members only) and untuned against real data.
