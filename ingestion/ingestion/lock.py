from datetime import date

import redis

from .config import config

_redis = redis.Redis(host=config.REDIS_HOST, port=config.REDIS_PORT, decode_responses=True)

_LOCK_TTL_MS = 90 * 60 * 1000  # 90 minutes — above even BrokerageCallsJob's "tens of minutes" full-universe scrape


class JobLock:
    """Redis-backed lock so a scheduled run and a manual backfill can't race on
    the same job/date and double-insert."""

    def __init__(self, job_name: str, run_date: date):
        self._key = f"ingestion:lock:{job_name}:{run_date.isoformat()}"
        self._acquired = False

    def __enter__(self) -> bool:
        self._acquired = bool(_redis.set(self._key, "1", nx=True, px=_LOCK_TTL_MS))
        return self._acquired

    def __exit__(self, exc_type, exc, tb):
        if self._acquired:
            _redis.delete(self._key)
