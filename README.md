# Storage (self-hosted)

PostgreSQL 15 + TimescaleDB and Redis 7, persisted to `/data` on the host.

## Start

```bash
docker compose up -d
```

## Verify

```bash
docker compose ps
docker compose exec postgres psql -U trading -d trading -c "\dx"
docker compose exec redis redis-cli ping
```

## Stop

```bash
docker compose down
```

Data lives on the host at `/data/postgres` and `/data/redis` and survives `docker compose down`.

## Dashboard

A minimal Streamlit dashboard (`ingestion/dashboard.py`, `dashboard` service) at
**http://localhost:8501** for operational visibility: an overview of
instrument counts and latest data dates, the latest status of every job, a
button to trigger any job for any date on demand (bypassing the 16:00 IST
schedule), and a raw browser over every table (with a symbol filter). It
runs on the same image as `ingestion` and reuses its job classes directly —
no separate API.

## Usage

Every job is run through one CLI (`ingestion/ingestion/cli.py`), grouped by
`--job`:

```bash
docker compose exec ingestion python -m ingestion.cli backfill --job <group> --date 2026-07-09
docker compose exec ingestion python -m ingestion.cli backfill-range --job <group> --from 2026-07-01 --to 2026-07-09
```

| `--job`         | Runs                                                                     | Schedule                                              |
|------------------|---------------------------------------------------------------------------|--------------------------------------------------------|
| `equity`         | NSE equity EOD OHLCV                                                     | daily 16:00 IST                                        |
| `index`          | Nifty 50 / Nifty Bank (+ unverified Sensex)                              | daily 16:00 IST                                        |
| `analytics`      | `technical_indicators` → `candlestick_patterns` → `signal_events`        | daily 16:00 IST, after `equity`/`index`                |
| `fundamentals`   | `corporate_actions`, `shareholding_pattern`, `financial_results`, `fundamental_ratios` | actions + results daily 18:30 IST; the rest weekly Sun 20:00 IST |
| `announcements`  | `nse_announcements`, `bse_announcements`                                | every 5 min, market hours only (09:15-15:30 IST, mon-fri) |
| `news`           | `rss_news`, `reddit_sentiment`                                          | every 30 min, around the clock                          |
| `all`            | everything above                                                         | —                                                        |

Re-running a date that already succeeded is a safe no-op — add `--force` to
re-ingest. Every job's outcome is tracked in `ingestion_log` (also browsable
in the dashboard). For the always-current feeds (`corporate_actions`,
`financial_results`, `nse_announcements`, `bse_announcements`, `rss_news`,
`reddit_sentiment`), `--date` only tags the `ingestion_log` row — these pull
"whatever's current right now", not a point-in-time historical replay.

## Ingestion

The `ingestion` service (Python, see `ingestion/`) pulls NSE end-of-day bhavcopy data
daily at 16:00 IST: equity OHLCV (`ohlcv_daily`, instrument_type `EQUITY`) and
Nifty 50 / Nifty Bank index closes (instrument_type `INDEX`). Weekly candles are
a TimescaleDB continuous aggregate (`ohlcv_weekly`), refreshed after each run.

A Sensex/BSE fetch is wired in but uses an **unverified** BSE endpoint (see the
docstring in `ingestion/ingestion/bse_client.py`) — it fails gracefully and logs
a warning rather than blocking the NSE indices, but needs a real endpoint
before Sensex data will actually land.

**Deferred to later phases**: intraday timeframes (1m/5m/15m/1h), real-time
WebSocket ticks (needs a broker API — Zerodha/Upstox/Angel One), the rest of
the index list (Nifty IT, Midcap 150, Next 50, sectoral indices), F&O
(futures OI, options chain, Greeks, PCR), pre-open session data, circuit
limits, and Level 2 depth.

## Technical indicators & price patterns

After the EOD price jobs, three analytics jobs read `ohlcv_daily` and store
pre-computed results — nothing here is recomputed at query time:

- **`technical_indicators`** (`technical_indicators_daily`): EMA 9/21/50/100/200,
  SMA 20/50/200, ADX(14), Supertrend(7,3), Ichimoku Cloud, RSI(14),
  MACD(12,26,9), Stochastic(14,3,3), ROC(12), CCI(14), OBV, a 20-day rolling
  VWAP, Volume SMA(20), MFI(14), Bollinger Bands(20,2), ATR(14), Keltner
  Channels. Computed via TA-Lib over a 450-calendar-day lookback per
  instrument; indicators without enough history yet (e.g. EMA 200 on a
  recently-listed stock) are left `NULL` rather than guessed at.
- **`candlestick_patterns`** (`candlestick_patterns_daily`): the 9 single/multi-
  candle patterns in scope — Doji, Engulfing, Hammer, Shooting Star, Morning/
  Evening Star, Harami, Three White Soldiers, Three Black Crows — via TA-Lib's
  `CDL*` functions. Stored as TA-Lib's signed value (positive = bullish,
  negative = bearish, 0 = not present).
- **`signal_events`** (`signal_events` + `support_resistance_levels`):
  Breakout/Breakdown (close beyond the prior 20-day close range on ≥1.5x
  average volume), 52-week high/low proximity (within 2%), Golden/Death Cross
  (SMA 50 vs SMA 200, so this runs after `technical_indicators`), and
  pivot-based support/resistance clustering (swing highs/lows within the
  lookback window, merged into levels within 0.75% of each other, ranked by
  touch count — top 5 support + top 5 resistance per instrument, replaced in
  full on every run).

Jobs run in that order (each depends on the previous): `equity`/`index` →
`technical_indicators` → `candlestick_patterns` → `signal_events` — see
`--job analytics` in [Usage](#usage).

**VWAP caveat**: only EOD bars are ingested (no intraday ticks), so `vwap_20`
is a rolling 20-day volume-weighted typical price, not a true intraday
session VWAP.

**Deferred to a follow-up phase**: chart pattern detection (Head & Shoulders
and inverse, Double Top/Bottom, Cup & Handle, Flags, Pennants, Ascending/
Descending Triangles, Rising/Falling Wedges). Unlike the indicators above,
none of these have a standard library implementation — they need custom
geometric heuristics (peak/trough detection + shape matching) that deserve
their own design and tuning pass against known historical examples rather
than being bolted on here.

## Fundamental data (Phase 3a)

Four jobs pull from NSE's corporate-filings API (`ingestion/ingestion/nse_corporate_client.py`)
— corporate actions, shareholding pattern, quarterly financial results, and
weekly ratios derived from them:

- **`corporate_actions`** (`corporate_actions`): dividends, bonus, splits,
  buybacks, rights — from NSE's daily corporate-actions calendar, classified
  from the free-text subject line via regex
  (`fundamentals/corporate_actions.py`). Anything the classifier doesn't
  recognize is still stored, as `action_type = 'OTHER'` with the raw text —
  never dropped.
- **`shareholding_pattern`** (`shareholding_pattern`): Promoter % and Public %
  come straight off NSE's bulk filings list, no parsing needed. FII %/DII
  %/Pledged % need the *dimensional* shareholding-pattern XBRL (shareholder
  category is an XBRL dimension member, not a flat tag) — out of scope for
  this pass, columns exist but stay `NULL`.
- **`financial_results`** (`fundamentals_quarterly`): Revenue, PAT, EPS
  (basic/diluted), and a derived EBITDA (PBT + finance costs + depreciation −
  other income) parsed from the `in-bse-fin` XBRL taxonomy
  (`fundamentals/xbrl_financial.py`). Finding *which* symbols to fetch is
  board-meeting-driven, not a blind daily loop over ~2,400 equities: NSE's
  bulk board-meetings calendar is polled for "Financial Results" purpose
  entries, and only those symbols get a per-symbol XBRL fetch. Also stores
  `shares_outstanding` (paid-up capital ÷ face value, from the same filing)
  for P/S.
- **`fundamental_ratios`** (`fundamental_ratios`): P/E, P/S (both trailing
  4-quarter), Dividend Yield, and Payout Ratio (both trailing 12-month, from
  `corporate_actions`), recomputed weekly (`fundamentals/ratios.py`).

**Known gaps in the XBRL data, verified not assumed**:
- `debt_to_equity`/`interest_coverage_ratio` in `fundamentals_quarterly` ARE
  tagged directly in the XBRL — but they're the SEBI LODR **Reg 52(4) ratios
  for listed debt securities** (NCDs/bonds) specifically, not the company's
  overall leverage. A company with no listed bonds shows ~0 here regardless
  of actual debt. Don't treat these as general quality signals without
  checking the company has listed debt securities.
- No balance sheet (Total Debt, Cash, Net Worth, Total Assets, Working
  Capital) or cash flow (OCF, FCF, CapEx) in `fundamentals_quarterly` —
  under SEBI LODR Reg 33, Indian companies only file those with **annual**
  results, not quarterly. This is a disclosure-frequency fact, not a parsing
  gap.
- `pb_ratio`, `ev_ebitda`, `pfcf_ratio`, `forward_pe`, `roe`, `roce`, `roa`
  columns exist in `fundamental_ratios` but are always `NULL` in this phase —
  they need the annual balance sheet/cash flow above, or (for Forward P/E)
  consensus estimates this phase doesn't collect.

**NSE's interactive API caveat**: unlike the static bhavcopy/XBRL archives,
`corporate_actions`/`shareholding_pattern`/`financial_results` call
`www.nseindia.com/api/*`, which sits behind Akamai bot protection. A cookie
warm-up (even a 403 response sets a usable cookie) makes it work — verified
live from this environment — but this class of endpoint is known to be
IP-blocked from some cloud/server hosts. If these jobs start failing, a
blocked IP is the first thing to check, same "verify before trusting" spirit
as `bse_client.py`'s already-unverified BSE endpoint.

See `--job fundamentals` in [Usage](#usage) for schedule and CLI.

**Deferred to Phase 3b**: full Income Statement/Balance Sheet/Cash Flow
(annual XBRL), YoY/QoQ growth rates, ROE/ROCE/ROA, P/B, EV/EBITDA, P/FCF,
Forward P/E, FII/DII/pledge shareholding breakdown, and Tickertape/Trendlyne
(not needed yet — everything above comes from NSE directly).

## News & sentiment (Phase 4a)

Four jobs feed one unified table, `news_items` (plus the `news_item_tickers`
many-to-many join) — a single row shape and enrichment pipeline across every
source, rather than a table per source like Domains 1-3, since the point of
this domain is "breaking news for ticker X across every source":

- **`nse_announcements`** (`ingestion/jobs/nse_announcements.py`): NSE's
  real-time corporate-announcements feed
  (`nse_corporate_client.fetch_corporate_announcements`), polled every 5
  minutes during market hours. Carries NSE's own `symbol`, so ticker tagging
  is the union of that direct, authoritative lookup and text-based alias
  matching (an announcement can also name other companies, e.g. M&A).
- **`bse_announcements`** (`ingestion/jobs/bse_announcements.py`): BSE
  counterpart, same 5-minute cadence. **Flaky/unverified endpoint** — BSE's
  `AnnSubCategoryGetData` API returned both a real 50-record payload and an
  empty `{}` body in the same session (see `bse_client.py`); a fetch failure
  degrades to zero rows and a logged warning rather than failing the job,
  same pattern as `bse_client.py`'s Sensex close. Only a numeric scrip code
  and company long-name come back (no NSE-style ticker), so ticker tagging
  is text-based alias matching only.
- **`rss_news`** (`ingestion/jobs/rss_news.py`): six Indian financial-news
  RSS feeds (`rss_client.py`) — ET Markets, Moneycontrol Business, Moneycontrol
  Markets, Mint, a Google News NSE-scoped search, and Business Standard.
  Business Standard's feed is **unverified from this environment** (HTTP 403,
  Akamai/WAF block) but stays wired in in case it works elsewhere. One bad
  feed is caught and logged per-feed, never takes the whole job down.
- **`reddit_sentiment`** (`ingestion/jobs/reddit_sentiment.py`): r/IndiaInvestments
  + r/stocks via PRAW (`reddit_client.py`), read-only. Reddit credentials
  (`REDDIT_CLIENT_ID`/`REDDIT_CLIENT_SECRET`, from a registered "script" app
  at reddit.com/prefs/apps) are optional infra — unset, the job just reports
  0 rows instead of failing the run.

**Enrichment** (`ingestion/news/pipeline.py`, run once per item by every job
above): ticker tagging via alias-index regex matching against `instruments`
(`news/ticker_matching.py` — symbol + normalized company name, whole-word,
not NER); sentiment via a small hand-curated keyword lexicon
(`news/sentiment.py` — deliberately not Loughran-McDonald or FinBERT, to
avoid an unverified third-party word list / multi-GB model dependency this
phase); urgency (`BREAKING` on a hand-picked keyword set — resignations,
fraud/probe, defaults, rating downgrades, M&A, etc. — else `ROUTINE`); and a
static per-source `source_credibility_weight` (`news/classify.py`): exchange
filings 1.0, mainstream RSS 0.75-0.80, Google News aggregation 0.6, Reddit
0.3. All of this is a first-pass heuristic signal, not publication-grade NLP
— expected to need tuning as gaps show up in practice.

See `--job announcements` / `--job news` in [Usage](#usage) for schedule and
CLI — `rss_news`/`reddit_sentiment` run with `force=True` under the hood
since news doesn't stop on weekends the way the trading-day-gated jobs do.

**Deferred**: a trained NER/sentiment model (FinBERT or similar) in place of
the keyword heuristics above, plus any source requiring paid API access.
