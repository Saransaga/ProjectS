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

## Ingestion

The `ingestion` service (Python, see `ingestion/`) pulls NSE end-of-day bhavcopy data
daily at 16:00 IST: equity OHLCV (`ohlcv_daily`, instrument_type `EQUITY`) and
Nifty 50 / Nifty Bank index closes (instrument_type `INDEX`). Weekly candles are
a TimescaleDB continuous aggregate (`ohlcv_weekly`), refreshed after each run.

A Sensex/BSE fetch is wired in but uses an **unverified** BSE endpoint (see the
docstring in `ingestion/ingestion/bse_client.py`) — it fails gracefully and logs
a warning rather than blocking the NSE indices, but needs a real endpoint
before Sensex data will actually land.

Manual backfill:

```bash
docker compose exec ingestion python -m ingestion.cli backfill --job all --date 2026-07-09
docker compose exec ingestion python -m ingestion.cli backfill-range --job all --from 2026-07-01 --to 2026-07-09
```

Re-running a date that already succeeded is a safe no-op (add `--force` to
re-ingest). Job runs are tracked in `ingestion_log`.

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
`technical_indicators` → `candlestick_patterns` → `signal_events`. The daily
scheduler runs the whole sequence at 16:00 IST; the CLI groups them under
`--job analytics` (or `--job all` for everything):

```bash
docker compose exec ingestion python -m ingestion.cli backfill --job analytics --date 2026-07-09
docker compose exec ingestion python -m ingestion.cli backfill-range --job all --from 2026-07-01 --to 2026-07-09
```

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
