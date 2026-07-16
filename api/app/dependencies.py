from fastapi import Cookie, HTTPException, status

from . import auth


def require_session(session: str | None = Cookie(default=None)) -> None:
    """FastAPI dependency applied to every router below except auth/health —
    raises 401 (the SPA redirects to /login on this) unless the signed
    session cookie set by POST /api/auth/login is present and unexpired."""
    if not auth.verify_session_token(session):
        raise HTTPException(status_code=status.HTTP_401_UNAUTHORIZED, detail="Not authenticated")
