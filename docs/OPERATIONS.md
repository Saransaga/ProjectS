# Operations — scheduled downtime & session changelog

_Last updated: 2026-07-14_ — companion to [`PROJECT_STATUS.md`](./PROJECT_STATUS.md)
and [`DATABASE_ERD.md`](./DATABASE_ERD.md).

## 1. Scheduled downtime window: 21:45–07:45 IST

The server is intentionally stopped daily from **21:45 IST to 07:45 IST**
(cost saving). This window was chosen because it's the only stretch with no
cron activity: `daily_recommendation_ingest` (21:00, the last daily slot)
has finished by 21:45, and the next activity isn't until
`monthly_industry_classification`/`monthly_index_rebalancing` (08:30/09:00,
**1st of the month only**) or `announcements_poll` picking back up at 09:00
on a trading day.

**Caveat**: if the downtime window ever needs to span across midnight into
the **1st of a month**, `monthly_index_rebalancing` (09:00) and
`monthly_industry_classification` (08:30) will be missed for that month —
see the manual catch-up command below.

### What survives a stop/start cycle automatically
- **All containers**: every service in `docker-compose.yml` has
  `restart: unless-stopped`, so `docker compose stop` → `docker compose start`
  (or `up -d`) brings everything back cleanly, including Postgres/Redis data
  (on a named volume — never run `docker compose down -v`, that deletes it).
- **`telegram-listener`**: reconnects and resumes long-polling on restart
  (verified — logs a successful `getMe` call, resumes `getUpdates` with its
  last offset). Telegram itself should queue messages sent while it's down
  and deliver them once polling resumes, though that specific gap-recovery
  behavior hasn't been explicitly tested in this environment.
- **"Always current" feeds** (`nse_announcements`, `bse_announcements`,
  `rss_news`, `reddit_sentiment`, `corporate_actions`, `financial_results`):
  these pull "whatever's current right now," not a historical point-in-time
  snapshot, so a missed poll just means slightly stale data until the next
  successful one — no backfill needed.

### What does NOT survive automatically — by design, not an oversight
Neither orchestrator auto-backfills a missed cron slot:
- `scheduler.py`'s APScheduler uses an in-memory job store (no persistence
  configured). If the `ingestion` container is down when a slot fires, it
  has zero memory of that miss on restart — it just resumes ticking forward
  from whenever it comes back. `misfire_grace_time` (mostly 3600s) only
  covers brief in-process delays, not the container being off.
- Every Airflow DAG is explicitly `catchup=False` (see
  `airflow/dags/_ingestion_docker.py`'s `START_DATE` comment) — same
  no-auto-backfill behavior, deliberately, to avoid a stampede of backfill
  runs on every restart.

**Manual catch-up after a downtime window that clipped a scheduled job**:
```bash
docker compose exec ingestion python -m ingestion.cli backfill-range --job all --from <off-date> --to <on-date>
```
Safe to run generously — `ingestion_log`'s per-(job, date) idempotency check
makes re-running an already-succeeded date a no-op.

## 2. Orchestration status (as of 2026-07-14)

All **13 of 13** Airflow DAGs are now unpaused (`daily_recommendation_ingest`
and `monthly_industry_classification` — Domain 8's two — were the last
holdouts, unpaused this session). Both `scheduler.py` and Airflow currently
run the full schedule in parallel; `ingestion_log`'s idempotency check means
whichever system gets to a (job, date) first wins and the other's attempt
becomes a cheap `SKIPPED` — see `airflow/README.md` for the full mechanism.

**Next step, not yet done**: per the project's own documented cutover plan,
once each of the two newly-unpaused DAGs has succeeded a few times on its
own via Airflow, remove its matching `scheduler.add_job(...)` entry from
`ingestion/ingestion/scheduler.py`. Don't remove `scheduler.py` itself until
every entry has been individually cut over this way.

## 3. This session's changes — Domain 8 hardening & Telegram bot enhancements

Domain 8 (recommendation engine + Telegram bot) had already been built in a
prior session but was uncommitted and unverified. This session verified it
end-to-end against the live system, found and fixed several real bugs along
the way, and extended it. Commits, newest first:

| Commit | Summary |
|---|---|
| `54f95d9` | ATR-projected fallback target + "time to target" pace estimate; current price shown on every digest/`/top` line |
| `06395b3` | Domains 4 (news/sentiment), 6 (bulk/block deals, FII/DII flow), 7 (upcoming corporate events) factored into the short-term score |
| `9c2976a` | `/top` command; price target/exit levels; justification bullets on every recommendation |
| `a588642` | Domain 8 committed & pushed (recommendation engine, Telegram bot, sector classification) |

### Bugs found and fixed (each caught by actually exercising the live system, not by inspection)

1. **Stale technical indicators from a scheduler race.** `technical_indicators`
   had run and logged `SUCCESS` with 0 rows on 07-13, because it started
   (10:30:01) and finished in under a second — *before* `nse_equity_eod`
   (which took until 13:50 that day) had written any OHLCV rows. The
   `ingestion_log` idempotency guard then permanently locked in that empty
   result for the day, matching the documented "cross-DAG ordering isn't
   enforced" caveat. Fixed by force-re-running the analytics chain once real
   price data existed. Also discovered the environment only had **4 trading
   days** of price history on record — nowhere near enough for EMA50/MACD —
   and backfilled to 61 trading days to unlock real technical scoring
   (`short_term_action` coverage went from 0 → 2,424/2,670 instruments).

2. **Telegram Markdown parser breaking message delivery outright.** Legacy
   Telegram `Markdown` parse mode treats a bare `_` as an italic delimiter.
   Several of this project's own enum values contain literal underscores
   (`SHORT_BUILDUP`, `STRONG_BUY`, `GOLDEN_CROSS`, ...) — one unescaped
   underscore anywhere breaks entity parsing for the *entire* message, not
   just that value. Caught live: a real watchlist alert failed to send with
   `can't parse entities`. Fixed with a `_esc()` helper applied to every
   piece of dynamic text (symbol, name, action words, justification
   reasons) before interpolation.

3. **Failed alert sends silently and permanently dropped.** `TelegramAlertsJob`
   was updating `telegram_watchlist_alert_state` (the anti-spam
   "already alerted this action" tracker) *unconditionally*, even when the
   actual Telegram send failed (bug #2 above triggered this in practice) —
   so a failed alert was never retried, since the state already reflected
   the new action. Fixed so `alert_state` only updates on confirmed
   delivery.

4. **A market-wide signal could single-handedly fake "sufficient data."**
   After adding `fii_dii_market_flow` (Domain 6) as a new short-term
   component, 120 instruments with **zero** real technical/relative-strength/
   F&O signal still received a confident recommendation — because
   `fii_dii_market_flow` is a single value shared by the whole market (not
   per-instrument) and is therefore *always* available, and combined with
   the other newly-added "always-real-zero" components it alone cleared the
   50% availability gate. This directly contradicted the project's own
   "never compute from a mostly-missing picture" design principle. Fixed by
   adding `counts_toward_gate` to `ComponentResult`
   (`recommendation/aggregate.py`) — a non-instrument-specific overlay can
   still influence the final score when available, but can't by itself
   satisfy the "do we have real per-instrument data" gate. Coverage
   corrected from a false 2,670/2,670 down to a real 2,550/2,670.

### Features added
- **`/top`** — on-demand top-5 short-term BUY ideas (previously only a
  pushed daily digest existed).
- **Price targets and exit levels** on every recommendation
  (`/recommend`, `/top`, watchlist alerts, daily digest), direction-aware:
  BUY gets nearest resistance as target / nearest support as exit trigger;
  SELL gets the reverse. Falls back to an ATR(14)-based projection
  (`close ± multiple × ATR`, clearly labeled `ATR-projected`) when a stock
  has no historical support/resistance on record yet — e.g. a breakout to a
  new high has nothing recorded above it.
- **"Time to target" pace estimate** — distance to target ÷ the
  instrument's own ATR(14), e.g. *"~2 trading days at the recent pace"*.
  Deliberately framed as a pace estimate, not a forecast or a fabricated
  calendar date — this engine is 100% deterministic/heuristic with no LLM,
  and doesn't invent precision it doesn't have.
- **Justification bullets** — the top 2-3 highest-weighted contributing
  factors from the scoring engine's own rationale, rendered as plain
  English (`recommendation/rationale_text.py`).
- **Current price shown inline** on digest/`/top` lines, not just `/recommend`.
- **Domains 4/6/7 now feed the score.** Previously short-term only drew on
  Domains 1/2/6(partial); long-term only on 3/5/6(partial). Added:
  `news_sentiment` (Domain 4, weighted by relevance + per-source
  credibility), `bulk_block_deals` (Domain 6), `fii_dii_market_flow`
  (Domain 6, market-wide), `upcoming_corporate_events` (Domain 7 — forward
  counterpart to the long-term score's existing backward-looking
  `corporate_actions_signal`). All 11 short-term weights still sum to 1.0.
  Deliberately **not** added: `macro_events`/`index_rebalancing_schedule`
  (no genuine directional signal without fabricating one) and
  sector-rotation off `instruments.sector` (stays deferred per this
  project's own prior documented reasoning — partial, untuned coverage).

### Operational actions taken (not code)
- Backfilled OHLCV history from 4 → 61 trading days and re-ran the analytics
  chain, to give the recommendation engine real technical data to score
  against.
- Attempted a full-universe `brokerage_calls` backfill; confirmed the
  previously-documented Moneycontrol rate-limiting (HTTP throttling after
  ~4 resolutions) still reproduces — left as a known dead end, not retried
  further.
- Unpaused all 13 Airflow DAGs (see §2 above).
