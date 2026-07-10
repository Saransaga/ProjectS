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
