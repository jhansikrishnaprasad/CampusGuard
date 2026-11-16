"""Password hashing, session tokens, auth dependencies, login throttling, safe paths."""
from __future__ import annotations
import base64, hashlib, hmac, os, secrets, time
from datetime import timedelta
from pathlib import Path
from fastapi import Depends, HTTPException, Request
from sqlalchemy.orm import Session
from . import config
from .database import get_db
from .models import SessionToken, User, utcnow

_ITER = 390_000


def hash_password(password: str) -> str:
    salt = os.urandom(16)
    dk = hashlib.pbkdf2_hmac("sha256", password.encode(), salt, _ITER)
    return f"pbkdf2_sha256${_ITER}${base64.b64encode(salt).decode()}${base64.b64encode(dk).decode()}"


def verify_password(password: str, stored: str) -> bool:
    try:
        _, it, salt, dk = stored.split("$")
        calc = hashlib.pbkdf2_hmac("sha256", password.encode(), base64.b64decode(salt), int(it))
        return hmac.compare_digest(calc, base64.b64decode(dk))
    except Exception:
        return False


def _th(token: str) -> str:
    return hashlib.sha256(token.encode()).hexdigest()


def create_session(db: Session, user: User) -> str:
    token = secrets.token_urlsafe(32)
    db.add(SessionToken(token_hash=_th(token), user_id=user.id,
                        expires_at=utcnow() + timedelta(hours=config.SESSION_HOURS)))
    db.commit()
    return token


def drop_session(db: Session, token: str) -> None:
    db.query(SessionToken).filter(SessionToken.token_hash == _th(token)).delete()
    db.commit()


def _local_admin(db: Session) -> User:
    """Login-free local mode (config.REQUIRE_LOGIN is false): act as the first active admin account."""
    user = db.query(User).filter(User.active == True, User.role == "admin").order_by(User.id).first()  # noqa: E712
    if not user:
        raise HTTPException(401, "No active administrator account exists")
    return user


def current_user(request: Request, db: Session = Depends(get_db)) -> User:
    token = request.cookies.get("session")
    if not token:
        if not config.REQUIRE_LOGIN:
            return _local_admin(db)
        raise HTTPException(401, "Authentication required")
    st = db.query(SessionToken).filter(SessionToken.token_hash == _th(token)).first()
    if not st or st.expires_at < utcnow():
        if not config.REQUIRE_LOGIN:
            return _local_admin(db)
        raise HTTPException(401, "Session expired or invalid")
    user = db.get(User, st.user_id)
    if not user or not user.active:
        if not config.REQUIRE_LOGIN:
            return _local_admin(db)
        raise HTTPException(401, "Account disabled")
    return user


def admin_user(user: User = Depends(current_user)) -> User:
    if user.role != "admin":
        raise HTTPException(403, "Administrator role required")
    return user


# ---- login throttling (in-memory; fine for a single-process local prototype) ----
_fails: dict[str, list[float]] = {}


def throttle_check(key: str, limit: int = 5, window: int = 300) -> None:
    now = time.time()
    _fails[key] = [t for t in _fails.get(key, []) if now - t < window]
    if len(_fails[key]) >= limit:
        raise HTTPException(429, "Too many failed logins. Try again in a few minutes.")


def throttle_fail(key: str) -> None:
    _fails.setdefault(key, []).append(time.time())


def throttle_clear(key: str) -> None:
    _fails.pop(key, None)


def safe_join(base: Path, rel: str) -> Path:
    """Resolve rel under base, refusing anything that escapes base (path traversal)."""
    base_r = base.resolve()
    target = (base_r / rel).resolve()
    if base_r != target and base_r not in target.parents:
        raise HTTPException(400, "Invalid file path")
    return target
