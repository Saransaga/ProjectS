"""Hand-curated backlog transcribed from README.md's and
docs/PROJECT_STATUS.md's per-domain "Deferred"/"Dropped" call-outs — static
Python data, not live-parsed markdown (those docs are prose meant for humans;
re-deriving structure from them at request time would be brittle and add no
real value over transcribing once). Update this list by hand whenever a new
domain section documents a fresh deferred/dropped item, or a deferred item
above gets built (move/remove it).

`status`: "DEFERRED" (in-scope, not built yet, no blocker) vs "DROPPED"
(actively investigated and found dead/unusable in this environment — e.g. a
CAPTCHA wall or a client-side-only SPA with no API). `source_related`: True
for items that are specifically about a data source being broken/unverified/
blocked, not a missing feature — these also populate GET /api/sources/known-gaps.
"""

ROADMAP = [
    {
        "domain": "Domain 1 — Core price data",
        "title": "Intraday timeframes (1m/5m/15m/1h) and real-time WebSocket ticks",
        "status": "DEFERRED",
        "description": "Needs a broker API (Zerodha/Upstox/Angel One) — out of scope for the current free/scraped-source phase.",
        "source_related": False,
    },
    {
        "domain": "Domain 1 — Core price data",
        "title": "Rest of the index list (Nifty IT, Midcap 150, Next 50, sectoral indices)",
        "status": "DEFERRED",
        "description": "Only Nifty 50/Nifty Bank are ingested today.",
        "source_related": False,
    },
    {
        "domain": "Domain 1 — Core price data",
        "title": "Pre-open session data, circuit limits, Level 2 depth",
        "status": "DEFERRED",
        "description": "Not available from the free bhavcopy archives this project sources from.",
        "source_related": False,
    },
    {
        "domain": "Domain 1 — Core price data",
        "title": "Sensex/BSE index history",
        "status": "DROPPED",
        "description": "bse_client.py's BSE index endpoint is unverified — fails gracefully and logs a warning rather than blocking the NSE indices.",
        "source_related": True,
    },
    {
        "domain": "Domain 2 — Technical indicators & patterns",
        "title": "Geometric chart pattern detection (Head & Shoulders, Double Top/Bottom, Cup & Handle, Flags/Pennants, Triangles, Wedges)",
        "status": "DEFERRED",
        "description": "No standard library implementation exists — needs custom peak/trough detection and shape matching, tuned against known historical examples, as its own design pass.",
        "source_related": False,
    },
    {
        "domain": "Domain 3 — Fundamental data",
        "title": "Full annual Income Statement / Balance Sheet / Cash Flow (annual XBRL)",
        "status": "DEFERRED",
        "description": "Phase 3b — Indian companies only file balance sheet/cash flow annually (SEBI LODR Reg 33), not quarterly, so today's fundamentals_quarterly table structurally can't carry it yet.",
        "source_related": False,
    },
    {
        "domain": "Domain 3 — Fundamental data",
        "title": "ROE/ROCE/ROA, P/B, EV/EBITDA, P/FCF, Forward P/E",
        "status": "DEFERRED",
        "description": "Columns exist in fundamental_ratios but stay NULL — need the annual balance sheet/cash flow above, or (for Forward P/E) consensus estimates this phase doesn't collect.",
        "source_related": False,
    },
    {
        "domain": "Domain 3 — Fundamental data",
        "title": "FII/DII/pledge shareholding percentage breakdown",
        "status": "DEFERRED",
        "description": "Needs the dimensional shareholding-pattern XBRL (shareholder category is an XBRL dimension member, not a flat tag) — out of scope for this pass.",
        "source_related": False,
    },
    {
        "domain": "Domain 4 — News & sentiment",
        "title": "Trained NER/sentiment model (FinBERT or similar)",
        "status": "DEFERRED",
        "description": "Sentiment today is a hand-curated keyword lexicon, deliberately not FinBERT/Loughran-McDonald, to avoid an unverified third-party word list or multi-GB model dependency this phase.",
        "source_related": False,
    },
    {
        "domain": "Domain 4 — News & sentiment",
        "title": "Business Standard RSS feed",
        "status": "DROPPED",
        "description": "HTTP 403 (Akamai/WAF block) from this environment — stays wired in in case it works elsewhere.",
        "source_related": True,
    },
    {
        "domain": "Domain 4 — News & sentiment",
        "title": "BSE announcements endpoint",
        "status": "DROPPED",
        "description": "Flaky — observed both a real 50-record payload and an empty body in the same session; degrades to zero rows and a logged warning rather than failing the job.",
        "source_related": True,
    },
    {
        "domain": "Domain 4 — News & sentiment",
        "title": "Reddit sentiment (r/IndiaInvestments, r/stocks)",
        "status": "DROPPED",
        "description": "Unverified from this environment (HTTP 403, Akamai/PerimeterX block) — confirm from the real deployment host before relying on it.",
        "source_related": True,
    },
    {
        "domain": "Domain 5 — Brokerage & consensus",
        "title": "Trendlyne (consensus ratings/targets)",
        "status": "DROPPED",
        "description": "Sits behind a hard AWS WAF CAPTCHA, verified live — no plain HTTP client can ever pass it from any host. Re-cited (not re-verified) in every later domain that also wanted a Trendlyne feed.",
        "source_related": True,
    },
    {
        "domain": "Domain 5 — Brokerage & consensus",
        "title": "Full-universe Tickertape slug resolution",
        "status": "DEFERRED",
        "description": "Tickertape's own symbol-search API is IP-blocked; guess_slug() is a best-effort guess that's sometimes wrong, leaving those two columns NULL rather than blocking Moneycontrol-derived fields.",
        "source_related": True,
    },
    {
        "domain": "Domain 5 — Brokerage & consensus",
        "title": "Moneycontrol history beyond ~6 recent calls per stock",
        "status": "DEFERRED",
        "description": "Every stock page ships exactly the ~6 most recent broker-research entries — older calls are presumably paginated/lazy-loaded via JS this client doesn't execute.",
        "source_related": True,
    },
    {
        "domain": "Domain 6 — Momentum & microstructure",
        "title": "BSE bulk/block deals",
        "status": "DROPPED",
        "description": "Every guessed api.bseindia.com endpoint returned an ASP.NET error page, not JSON.",
        "source_related": True,
    },
    {
        "domain": "Domain 6 — Momentum & microstructure",
        "title": "Sector rotation signals",
        "status": "DEFERRED",
        "description": "instruments.sector coverage is partial by design (only sectoral-index members) and untuned against real data — fabricating a rotation signal on top of that would be worse than not shipping it.",
        "source_related": False,
    },
    {
        "domain": "Domain 7 — Corporate events & calendar",
        "title": "Actual Nifty/Sensex index inclusion/exclusion events",
        "status": "DEFERRED",
        "description": "NSE Indices' reconstitution announcements are ad hoc PDFs/press releases, not a scrapeable feed. BSE/Sensex has no equivalent calendar at all.",
        "source_related": False,
    },
    {
        "domain": "Domain 7 — Corporate events & calendar",
        "title": "Automated RBI/MOSPI macro calendar (MPC dates, CPI/WPI/IIP/GDP releases)",
        "status": "DROPPED",
        "description": "RBI's site is an ASP.NET postback search UI with no calendar API; MOSPI's release-calendar page is a client-side React shell with zero server-rendered content. macro_events stays manual-entry only.",
        "source_related": True,
    },
    {
        "domain": "Domain 7 — Corporate events & calendar",
        "title": "Consensus EPS estimates",
        "status": "DROPPED",
        "description": "No free, reliable consensus-EPS source exists once Trendlyne is dropped (same CAPTCHA finding as Domain 5).",
        "source_related": True,
    },
    {
        "domain": "Domain 7 — Corporate events & calendar",
        "title": "BSE corporate calendar",
        "status": "DROPPED",
        "description": "bseindia.com's corporate-calendar page is an Angular SPA with zero server-rendered content; every guessed api.bseindia.com calendar endpoint either redirected or was really the already-flaky announcements endpoint.",
        "source_related": True,
    },
    {
        "domain": "Domain 8 — Recommendation engine & Telegram bot",
        "title": "Sector-rotation signals folded into the recommendation score",
        "status": "DEFERRED",
        "description": "Blocked on Domain 6's own sector-rotation deferral above — instruments.sector coverage isn't tuned enough yet.",
        "source_related": False,
    },
    {
        "domain": "Domain 8 — Recommendation engine & Telegram bot",
        "title": "Trained ranking model in place of the deterministic heuristic scorer",
        "status": "DEFERRED",
        "description": "Scoring is 100% deterministic/heuristic today, deliberately no LLM/ML model.",
        "source_related": False,
    },
    {
        "domain": "Domain 8 — Recommendation engine & Telegram bot",
        "title": "Long-term (fundamentals/valuation) call outcome tracking",
        "status": "DEFERRED",
        "description": "recommendation_outcomes currently only tracks short-term calls — long_term_action has no natural target/stop (support/resistance and ATR are short-horizon technical concepts), so a long-term equivalent needs its own resolution criteria (e.g. a forward return window) before it can be tracked the same way.",
        "source_related": False,
    },
]

# Subset specifically about a data source being broken/unverified/blocked —
# powers GET /api/sources/known-gaps (the "least-used data sources" view's
# static half, alongside query/browse.py::source_health's live metrics).
KNOWN_GAPS = [item for item in ROADMAP if item["source_related"]]
