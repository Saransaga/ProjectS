from contextlib import contextmanager

import psycopg2
from psycopg2 import pool

from .config import config

_pool = None


def get_pool():
    global _pool
    if _pool is None:
        _pool = psycopg2.pool.ThreadedConnectionPool(
            minconn=1,
            maxconn=10,
            host=config.POSTGRES_HOST,
            port=config.POSTGRES_PORT,
            user=config.POSTGRES_READONLY_USER,
            password=config.POSTGRES_READONLY_PASSWORD,
            dbname=config.POSTGRES_DB,
        )
    return _pool


@contextmanager
def get_conn():
    """A connection logged in as the read-only trading_readonly role
    (readonly_role.sh) — this service can never write even if a query
    function were misused, a real DB-level guarantee rather than only an
    app-level flag (dashboard.py's conn.set_session(readonly=True) is the
    same belt-and-suspenders idea, but that one still logs in as the
    privileged POSTGRES_USER underneath; this one doesn't). autocommit=True
    since every query here is a plain SELECT — nothing to commit/rollback."""
    conn = get_pool().getconn()
    conn.set_session(readonly=True, autocommit=True)
    try:
        yield conn
    finally:
        get_pool().putconn(conn)
