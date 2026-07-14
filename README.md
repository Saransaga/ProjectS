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
| `brokerage`      | `brokerage_calls`, `consensus_ratings`                                  | daily 17:00 IST, after `equity`/`index`                 |
| `momentum`       | `fii_dii_flows`, `bulk_block_deals`, `fno_bhavcopy`, `fno_signals`, `deliverable_volume`, `relative_strength` | 17:15 IST (F&O/delivery/RS) + 18:00 IST (FII/DII) + 2 intraday windows (bulk/block deals) |
| `events`         | `corporate_calendar`, `ipo_listings`, `index_rebalancing_schedule`       | daily 19:00 IST (calendar/IPO) + monthly 1st, 09:00 IST (rebalancing) |
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

## Brokerage recommendations & consensus (Phase 5a)

Two jobs, run in sequence after the daily EOD close:

- **`brokerage_calls`** (`brokerage_calls` + `rating_change_events`):
  Moneycontrol's per-stock "Broker Research" section
  (`moneycontrol_client.py`) is the primary — and only real-time — source,
  walked across every active NSE equity (~2,000+ pages, one HTTP fetch each
  plus a rate-limit sleep, so a full run takes on the order of tens of
  minutes; see the job's docstring). **Observed live under sustained load**
  (a real full-universe backfill, 2026-07-14): the autosuggest endpoint
  (`resolve_stock`), which the spot-checks in `moneycontrol_client.py`'s
  docstring verified fine for a handful of names, started returning HTTP 403
  after only ~4 resolutions in one run — every subsequent instrument then
  burns 3 retries' worth of backoff for nothing, which would turn a "tens of
  minutes" run into several hours with zero further data landing. This
  wasn't caught by the original spot-check verification; treat it as a real
  risk, not a hypothetical one — if a production run stalls with a flat
  `moneycontrol_instrument_map` count, this is the first thing to check.
  Each stock's Moneycontrol page URL/stock code is resolved once via the
  autosuggest endpoint and cached in
  `moneycontrol_instrument_map`, not re-resolved every run. Raw rating text
  ("BUY", "ACCUMULATE", "REDUCE", ...) is classified into the fixed
  STRONG_BUY/BUY/HOLD/SELL/STRONG_SELL scale by `brokerage/classify.py`
  (exact-match against a known vocabulary; unrecognized terms are still
  stored via `raw_rating`, just left unclassified — never dropped, same
  spirit as Domain 3's `corporate_actions.action_type = 'OTHER'`). Every new
  call is diffed against that same brokerage's immediately-prior call for the
  same instrument to emit an `UPGRADE`/`DOWNGRADE`/`REITERATED`/`INITIATED`
  row in `rating_change_events`.
- **`consensus_ratings`** (`consensus_ratings`): a daily recompute (not a
  live feed — `always_force=True`, like `fundamental_ratios`) over each
  instrument's latest-per-brokerage call within a trailing 12-month window:
  majority-vote `consensus_rating_bucket` (ties break toward the more bullish
  bucket, see `brokerage/consensus.py`), `avg_target_price`, and
  `implied_upside_pct` against the latest `ohlcv_daily` close. Best-effort
  cross-checked against Tickertape's server-rendered "Analyst Ratings &
  Forecast" card (`tickertape_client.py`) for `tickertape_pct_buy` /
  `tickertape_analyst_count` — kept as separate columns rather than blended
  into the Moneycontrol-derived fields, since the two sources count
  "analysts" differently and disagreement between them is itself signal.

**Known limitation — Tickertape slug resolution**: Tickertape's own
symbol-search API is IP-blocked from this environment, so there's no
reliable way to resolve an NSE symbol to a Tickertape slug. `guess_slug()`
guesses `{company-name-slug}-{NSE_SYMBOL}`, which is sometimes wrong
(Tickertape's internal ID rarely matches the NSE symbol) — a failed or
wrong guess just leaves `tickertape_pct_buy`/`tickertape_analyst_count`
`NULL` for that instrument/day, and never blocks the Moneycontrol-derived
fields. Full-universe slug resolution (e.g. scraping Tickertape's sitemap)
is deferred.

**Trendlyne dropped from this phase**: the spec's originally-intended
primary source for consensus ratings/targets sits behind a hard AWS WAF
CAPTCHA challenge (verified live) — not merely flaky/IP-blocked like
`bse_client.py`'s endpoints, so a plain HTTP client can never pass it from
any host. Wiring it in would have shipped permanently dead code rather than
a "verify before trusting" caveat.

**Moneycontrol pagination caveat**: every stock page checked server-side
ships exactly the ~6 most recent broker-research entries (older calls are
presumably paginated/lazy-loaded via JS this client doesn't execute) — treat
`brokerage_calls` as "recent calls", not a full historical archive.

See `--job brokerage` in [Usage](#usage) for schedule and CLI.

**Deferred**: full-universe Tickertape slug resolution, a Trendlyne source
once/if its CAPTCHA wall is solvable another way, and paginated/lazy-loaded
Moneycontrol history beyond the ~6 most recent calls per stock.

## Momentum & market microstructure (Phase 6a)

Six jobs, all sourced from NSE's own unauthenticated static archives
(`nsearchives.nseindia.com` — same trust tier as Domain 1's bhavcopy, no
bot protection) or its `fiidiiTradeReact` interactive endpoint:

- **`fii_dii_flows`** (`fii_dii_cash_flows` + `fno_participant_oi`): cash-market
  FII/DII net buy/sell (Rs. crore) from NSE's `fiidiiTradeReact`, which always
  returns "whatever was last published" — no date-range param, same
  "whatever's current" shape as Domain 3's `corporate_actions` — plus NSCCL's
  daily "Participant wise Open Interest" snapshot, broken down by client type
  (Client/DII/FII/Pro) across futures/options × index/stock. NSE does not
  publish a free FII/DII *turnover* figure for the F&O segment the way it
  does for cash — day-over-day deltas in participant OI are the closest free,
  legitimate proxy analysts actually use for F&O institutional positioning;
  don't mistake `fno_participant_oi`'s open-interest columns for a value
  figure. Weekly/monthly cumulative cash flows are a `SUM(net_value_cr)` query
  over a date range on `fii_dii_cash_flows`, not a separately materialized
  rollup.
- **`bulk_block_deals`** (`bulk_block_deals`): NSE's `bulk.csv`/`block.csv`,
  which (like the announcements feeds in Domain 4) only ever serve "today's"
  deals — `always_force=True`, meant to run in the domain spec's "2 intraday
  windows". **NSE only** — every guessed `api.bseindia.com` bulk/block-deal
  endpoint returned an ASP.NET error page, not JSON, from this environment
  (unlike `bse_client.py`'s existing endpoints, which are at least
  intermittently reachable); dropped for the same "don't ship dead code for
  an unverified endpoint" reason Trendlyne was dropped from Domain 5.
- **`fno_bhavcopy`** (`fno_bhavcopy_daily`): every F&O contract (index/stock
  futures + options, ~36,000 rows/day) from NSE's daily UDiFF F&O bhavcopy.
  `instrument_id` is only resolved for stock underlyings — index underlyings
  (`NIFTY`, `BANKNIFTY`, ...) have no matching row in `instruments` (Domain 1
  only carries "Nifty 50"/"Nifty Bank", a different naming convention), so
  `underlying_symbol` is the only reliable join key for index contracts.
- **`fno_signals`** (`fno_signals`, `fno_oi_buildup`, `fno_rollover`): reads
  `fno_bhavcopy_daily` (must run after `fno_bhavcopy` for the same date) and
  computes, per underlying: Put-Call Ratio (OI-based and volume-based) + the
  max-pain strike per expiry's option chain (`momentum/pcr.py`); futures
  OI-buildup classification — LONG_BUILDUP/SHORT_BUILDUP/LONG_UNWINDING/
  SHORT_COVERING — straight off the bhavcopy's own previous-close/change-in-OI
  fields, no separate prior-day lookup needed (`momentum/oi_buildup.py`); and
  near/next-month futures rollover % (`momentum/rollover.py`). "Market-wide"
  PCR per the domain spec is just the `underlying_symbol = 'NIFTY'` rows in
  `fno_signals`, not a separately stored figure.
- **`deliverable_volume`**: backfills `ohlcv_daily.delivery_qty`/
  `delivery_pct` — present in the schema since Domain 1 but always `NULL`
  until now — from NSE's older "full bhavcopy" archive, the only free source
  that carries delivery data (the UDiFF bhavcopy Domain 1 uses doesn't have
  it at all). An `UPDATE` against Domain 1's existing rows, not an `INSERT`.
- **`relative_strength`** (`relative_strength`): reads `ohlcv_daily` directly
  (not an external source, like Domain 2's `technical_indicators`) and
  computes each equity's trailing 1W/1M/3M/6M/1Y total return, that same
  return relative to Nifty 50, and an IBD-style RS Rating (1-99 percentile
  rank of a composite score across every equity with full history that day).
  The composite is a simplified 40/30/30 blend of 3M/6M/1Y returns — IBD's
  official formula weights 3/6/9/12M returns 40/20/20/20, but this phase
  doesn't otherwise need a 9-month return, so substitutes the windows it does
  store (`momentum/relative_strength.py`).

**Dropped from this phase**: BSE bulk/block deals (see above) and Trendlyne
(RS-Rating/momentum-score source per the original spec — sits behind a hard
AWS WAF CAPTCHA, same finding as Domain 5). **Deferred**: sector rotation
signals — `instruments` carries no sector/industry classification in this
phase, and fabricating a rotation signal on top of no sector data would be
worse than not shipping it.

See `--job momentum` in [Usage](#usage) for schedule and CLI.

## Corporate events & calendar (Phase 7a)

Forward-looking triggers ahead of key market events. Ex-dividend/record
dates are deliberately **not** re-collected here — they already live in
Domain 3's `corporate_actions(ex_date, record_date)`; this domain is
additive calendar data, not a duplicate table.

- **`corporate_calendar`** (`corporate_calendar`): two NSE sources bundled
  under one job, `CorporateCalendarJob`.
  - Board meetings (`fetch_board_meetings`, already used by Domain 3's
    `financial_results` to find that day's reporters): a **forward** window
    from today, materializing the same feed as a queryable calendar instead
    of only using it transiently. Each meeting's purpose classifies into
    `EARNINGS`/`DIVIDEND`/`BONUS`/`SPLIT`/`BUYBACK`/`RIGHTS`/`FUND_RAISING`/
    `OTHER` (`events/classify.py`) — the decision-specific action wins over
    routine quarterly earnings when a purpose bundles several (e.g.
    "Financial Results/Dividend" classifies as `DIVIDEND`).
  - AGM/EGM (`fetch_corporate_announcements` filtered to `desc ==
    'Shareholders meeting'`): a **backward** window, since these are filed
    ahead of the actual meeting date — the meeting date itself is
    text-extracted from the free-text announcement (`events/classify.py`'s
    `parse_shareholder_meeting`), not the filing date. Records that don't
    resolve to a confirmed AGM/EGM type + date (postal ballots,
    voting-result outcomes, ambiguous notices with no AGM/EGM keyword
    anywhere) are dropped rather than tagged `OTHER` — without a resolved
    date the row isn't usable calendar data.
  - `consensus_eps_estimate` is always `NULL` this phase — no free,
    reliable consensus-EPS source exists once Trendlyne is dropped (same
    hard AWS WAF CAPTCHA finding as Domain 5, re-confirmed dead for this
    domain rather than re-verified).
- **`ipo_listings`** (`ipo_listings`): NSE's mainboard IPO calendar
  (`all-upcoming-issues?category=ipo` — confirmed live) for issue price
  band/bid window/status, plus **first-day listing data** derived rather
  than fetched: NSE has no "IPO listing-day performance" endpoint, so
  `IpoListingsJob` looks up the newly-listed symbol in `ohlcv_daily` (Domain
  1 already ingests it the moment it starts trading) and backfills the
  first trade date/OHLCV it finds on or after `issue_end_date` — same
  "derive, don't duplicate-fetch" spirit as `ohlcv_weekly`'s continuous
  aggregate. `status` moves `ACTIVE` → `CLOSED` → `LISTED` across runs;
  `instrument_id` stays `NULL` until the backfill resolves (a stock
  mid-bidding has no `instruments` row yet). Only the mainboard category is
  wired in — `category=sme` returned an empty response in this environment
  (no live SME issue at check time, not confirmed broken).
- **`index_rebalancing_schedule`** (`index_rebalancing_schedule`): NSE
  Indices' published rebalancing **cadence** per index — e.g. "Semi-annually
  - Last working day of March and September" for Nifty 50 — scraped from
  niftyindices.com's static rebalancing-schedule page
  (`niftyindices_client.py`, confirmed live: plain server-rendered HTML
  across all 11 index-family tables on that page, 215 indices total, no bot
  protection). A slowly-changing reference table, not a time series;
  refreshed monthly. **Not included**: actual per-cycle inclusion/exclusion
  (which stocks get added/removed) — no free, scrapeable source publishes
  that; NSE Indices' reconstitution announcements are ad hoc PDFs/press
  releases, not a feed. BSE/Sensex has no equivalent at all —
  bseindia.com's corporate-calendar page is an Angular SPA with zero
  server-rendered content, and every guessed `api.bseindia.com`
  calendar-shaped endpoint either redirected (matching `bse_client.py`'s
  already-documented broken pattern) or was really just the generic,
  already-flaky announcements endpoint.
- **`macro_events`** (`macro_events`): RBI MPC meeting dates, the Union
  Budget date, and CPI/WPI/IIP/GDP release dates. **No automated job** —
  the domain spec's own ingestion schedule already calls this "Monthly
  refresh + **manual updates**", and manual is the only option that
  actually exists: RBI's "Monetary Policy" section is an ASP.NET postback
  search UI (`GetYearMonth()` sets hidden form fields and fires a
  `__VIEWSTATE` postback — not a GET-able URL) with no calendar API, and
  RBI announces the year's MPC dates once, in a single annual press
  release, not a queryable schedule. MOSPI's release-calendar page
  (mospi.gov.in) is a client-side React shell — the raw HTML is a bare
  `<div id="root">` with zero server-rendered content, no JSON endpoint
  discoverable. `indiabudget.gov.in` confirms the Union Budget date is
  real and low-churn (~Feb 1 each year) but is likewise one page updated
  once a year, not a calendar feed. Populate via
  `docker compose exec ingestion python -m ingestion.cli macro-event add
  --date 2026-08-06 --category RBI_MPC --description "..."` (`--category`
  one of `RBI_MPC`/`UNION_BUDGET`/`CPI`/`WPI`/`IIP`/`GDP`/`OTHER`).

See `--job events` in [Usage](#usage) for the automated jobs' schedule and
CLI; `macro-event add` (above) is separate since it isn't a scheduled job.

**Deferred**: actual Nifty/Sensex index inclusion/exclusion events (see
`index_rebalancing_schedule` above), an automated RBI/MOSPI macro calendar
(no scrapeable source exists — see `macro_events` above), consensus EPS
estimates (Trendlyne dead, no other free source), and a BSE corporate
calendar (dead — Angular SPA, no working API, same conclusion as
`bse_client.py`'s existing findings).
