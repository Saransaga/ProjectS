"""DB writes for the Telegram tables (telegram_chats/telegram_watchlist/
telegram_watchlist_alert_state/telegram_alert_log, see init.sql's Domain 8
section) — shared by telegram_bot/commands.py (the reactive, per-message
side) and jobs/telegram_alerts.py (the proactive, once-a-day push side).
"""


def upsert_chat(conn, chat_id: int, chat_type: str, username: str | None) -> None:
    """Called on every inbound update, not just /start — this *is* how
    telegram_chats gets populated, and re-messaging after being blocked
    (is_active FALSE) re-activates the chat rather than requiring a manual
    reset."""
    with conn.cursor() as cur:
        cur.execute(
            """
            INSERT INTO telegram_chats (chat_id, chat_type, username, first_interaction_at, last_interaction_at, is_active)
            VALUES (%s, %s, %s, now(), now(), TRUE)
            ON CONFLICT (chat_id) DO UPDATE SET
                chat_type = EXCLUDED.chat_type,
                username = EXCLUDED.username,
                last_interaction_at = now(),
                is_active = TRUE
            """,
            (chat_id, chat_type, username),
        )


def mark_chat_inactive(conn, chat_id: int) -> None:
    """Called when sendMessage gets an HTTP 403 (bot blocked by that user) —
    stops the digest/alert broadcast from retrying a dead chat forever."""
    with conn.cursor() as cur:
        cur.execute("UPDATE telegram_chats SET is_active = FALSE WHERE chat_id = %s", (chat_id,))


def get_active_chat_ids(conn) -> list[int]:
    with conn.cursor() as cur:
        cur.execute("SELECT chat_id FROM telegram_chats WHERE is_active ORDER BY chat_id")
        return [row[0] for row in cur.fetchall()]


def add_watch(conn, chat_id: int, instrument_id: int) -> bool:
    """Returns True if newly added, False if already on the watchlist."""
    with conn.cursor() as cur:
        cur.execute(
            """
            INSERT INTO telegram_watchlist (chat_id, instrument_id)
            VALUES (%s, %s)
            ON CONFLICT (chat_id, instrument_id) DO NOTHING
            """,
            (chat_id, instrument_id),
        )
        return cur.rowcount > 0


def remove_watch(conn, chat_id: int, instrument_id: int) -> bool:
    """Returns True if a row was removed. The composite FK's ON DELETE
    CASCADE (see init.sql) means the matching telegram_watchlist_alert_state
    row disappears atomically with this delete — no second statement here."""
    with conn.cursor() as cur:
        cur.execute(
            "DELETE FROM telegram_watchlist WHERE chat_id = %s AND instrument_id = %s",
            (chat_id, instrument_id),
        )
        return cur.rowcount > 0


def list_watchlist(conn, chat_id: int) -> list[dict]:
    with conn.cursor() as cur:
        cur.execute(
            """
            SELECT i.instrument_id, i.symbol, i.name
            FROM telegram_watchlist tw
            JOIN instruments i ON i.instrument_id = tw.instrument_id
            WHERE tw.chat_id = %s
            ORDER BY i.symbol
            """,
            (chat_id,),
        )
        return [
            {"instrument_id": instrument_id, "symbol": symbol, "name": name}
            for instrument_id, symbol, name in cur.fetchall()
        ]


def get_watchlist_alert_candidates(conn, as_of_date) -> list[dict]:
    """One row per (active chat, watched instrument) that has a
    stock_recommendations row for as_of_date — includes the last-alerted
    action (NULL if never alerted) so the caller (TelegramAlertsJob) can
    decide whether anything actually changed, plus each rationale JSONB so
    the alert message can show the same target/exit levels + top reasons
    /recommend does (see telegram_bot/formatting.format_recommendation)."""
    with conn.cursor() as cur:
        cur.execute(
            """
            SELECT tw.chat_id, tw.instrument_id, i.symbol, i.name,
                   r.short_term_score, r.short_term_action, r.short_term_rationale,
                   r.long_term_score, r.long_term_action, r.long_term_rationale,
                   tas.last_short_term_action, tas.last_long_term_action
            FROM telegram_watchlist tw
            JOIN telegram_chats tc ON tc.chat_id = tw.chat_id AND tc.is_active
            JOIN instruments i ON i.instrument_id = tw.instrument_id
            JOIN stock_recommendations r ON r.instrument_id = tw.instrument_id AND r.as_of_date = %s
            LEFT JOIN telegram_watchlist_alert_state tas
                ON tas.chat_id = tw.chat_id AND tas.instrument_id = tw.instrument_id
            """,
            (as_of_date,),
        )
        rows = cur.fetchall()

    return [
        {
            "chat_id": chat_id,
            "instrument_id": instrument_id,
            "symbol": symbol,
            "name": name,
            "short_term_score": float(s_score) if s_score is not None else None,
            "short_term_action": s_action,
            "short_term_rationale": s_rationale,
            "long_term_score": float(l_score) if l_score is not None else None,
            "long_term_action": l_action,
            "long_term_rationale": l_rationale,
            "last_short_term_action": last_s_action,
            "last_long_term_action": last_l_action,
        }
        for (
            chat_id, instrument_id, symbol, name,
            s_score, s_action, s_rationale, l_score, l_action, l_rationale,
            last_s_action, last_l_action,
        ) in rows
    ]


def upsert_alert_state(
    conn, chat_id: int, instrument_id: int, short_action: str | None, long_action: str | None, as_of_date
) -> None:
    with conn.cursor() as cur:
        cur.execute(
            """
            INSERT INTO telegram_watchlist_alert_state
                (chat_id, instrument_id, last_short_term_action, last_long_term_action, last_alerted_date, updated_at)
            VALUES (%s, %s, %s, %s, %s, now())
            ON CONFLICT (chat_id, instrument_id) DO UPDATE SET
                last_short_term_action = EXCLUDED.last_short_term_action,
                last_long_term_action = EXCLUDED.last_long_term_action,
                last_alerted_date = EXCLUDED.last_alerted_date,
                updated_at = now()
            """,
            (chat_id, instrument_id, short_action, long_action, as_of_date),
        )


def log_alert(
    conn, chat_id: int, alert_scope: str, instrument_id: int | None, as_of_date,
    message_text: str, delivery_status: str, error: str | None,
) -> None:
    with conn.cursor() as cur:
        cur.execute(
            """
            INSERT INTO telegram_alert_log
                (chat_id, alert_scope, instrument_id, as_of_date, message_text, delivery_status, error)
            VALUES (%s, %s, %s, %s, %s, %s, %s)
            """,
            (chat_id, alert_scope, instrument_id, as_of_date, message_text, delivery_status, error),
        )
