from psycopg2.extras import execute_values

_NEWS_ITEM_COLUMNS = [
    "external_id", "headline", "summary", "url", "published_at",
    "sentiment_label", "sentiment_score", "urgency", "relevance_score",
    "source_credibility_weight",
]


def bulk_upsert_news_items(conn, source_type: str, rows: list[dict]) -> dict[str, int]:
    """Each row: external_id, headline, summary, url, published_at, plus the
    news.pipeline.enrich() output (sentiment_label, sentiment_score, urgency,
    relevance_score, source_credibility_weight). Returns {external_id:
    news_item_id} for the upserted rows, so the caller can then write
    news_item_tickers."""
    if not rows:
        return {}

    values = [(source_type,) + tuple(r.get(c) for c in _NEWS_ITEM_COLUMNS) for r in rows]
    set_clause = ", ".join(f"{c} = EXCLUDED.{c}" for c in _NEWS_ITEM_COLUMNS if c != "external_id")

    with conn.cursor() as cur:
        result = execute_values(
            cur,
            f"""
            INSERT INTO news_items (source_type, {", ".join(_NEWS_ITEM_COLUMNS)})
            VALUES %s
            ON CONFLICT (source_type, external_id) DO UPDATE SET {set_clause}
            RETURNING news_item_id, external_id
            """,
            values,
            fetch=True,
        )
    return {external_id: news_item_id for news_item_id, external_id in result}


def persist_news_items(conn, source_type: str, rows: list[dict]) -> int:
    """Single entry point for every news job's _persist(): dedup by
    external_id (last-one-wins — a source can list the same item twice
    within one fetch, e.g. an RSS feed repeat or a Reddit crosspost, and
    ON CONFLICT DO UPDATE can't touch the same conflict target twice in one
    statement), upsert into news_items, then replace ticker tags for the
    whole batch in one delete + one insert rather than a pair of queries per
    row. A re-poll of the same item re-runs ticker matching from scratch, so
    replace rather than accumulate — same reasoning as Domain 2's
    signal_events fix (a condition that no longer holds shouldn't leave a
    stale row behind)."""
    deduped = list({r["external_id"]: r for r in rows}.values())
    id_map = bulk_upsert_news_items(conn, source_type, deduped)

    news_item_ids = list(id_map.values())
    ticker_rows = [
        (instrument_id, id_map[r["external_id"]])
        for r in deduped
        if r["external_id"] in id_map
        for instrument_id in r["ticker_ids"]
    ]
    with conn.cursor() as cur:
        if news_item_ids:
            cur.execute("DELETE FROM news_item_tickers WHERE news_item_id = ANY(%s)", (news_item_ids,))
        if ticker_rows:
            execute_values(
                cur,
                "INSERT INTO news_item_tickers (instrument_id, news_item_id) VALUES %s",
                ticker_rows,
            )

    return len(id_map)
