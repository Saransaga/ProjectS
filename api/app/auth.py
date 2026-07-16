"""Shared-password session auth — one app-wide password, not per-user
accounts (see config.py). A signed, timestamped token (itsdangerous) in an
httpOnly cookie stands in for a session; there's no server-side session
store/revocation list, since rotating APP_SECRET_KEY is enough to invalidate
every outstanding session if that's ever needed for a single-password tool
like this one.
"""

import hmac

from itsdangerous import BadSignature, SignatureExpired, URLSafeTimedSerializer

from .config import config

SESSION_COOKIE_NAME = "session"
SESSION_MAX_AGE_SECONDS = 7 * 24 * 3600  # 7 days

_serializer = URLSafeTimedSerializer(config.APP_SECRET_KEY, salt="dashboard-session")


def verify_password(password: str) -> bool:
    """Constant-time comparison — a shared secret compared with `==` would
    leak timing information about how many leading characters matched."""
    return hmac.compare_digest(password, config.APP_PASSWORD)


def create_session_token() -> str:
    return _serializer.dumps({"authenticated": True})


def verify_session_token(token: str | None) -> bool:
    if not token:
        return False
    try:
        _serializer.loads(token, max_age=SESSION_MAX_AGE_SECONDS)
    except (BadSignature, SignatureExpired):
        return False
    return True
