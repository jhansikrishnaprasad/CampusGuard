from __future__ import annotations
import logging
import secrets
import threading
from contextlib import asynccontextmanager
from urllib.parse import urlparse
from fastapi import FastAPI, Request
from fastapi.responses import JSONResponse
from fastapi.staticfiles import StaticFiles
from . import config
from .database import SessionLocal, get_engine, init_db
from .models import User
from .routers import auth, compliance, events, reports, system, videos
from .security import hash_password
from .services.jobs import manager

logging.basicConfig(level=logging.INFO, format="%(asctime)s %(levelname)s %(name)s: %(message)s")
log = logging.getLogger("campus")


def seed_admin() -> None:
    with SessionLocal() as db:
        if db.query(User).count():
            return
        pw = config.ADMIN_PASSWORD
        generated = not pw
        if generated:
            pw = secrets.token_urlsafe(9)
        db.add(User(username=config.ADMIN_USERNAME, password_hash=hash_password(pw), role="admin"))
        db.commit()
    banner = "=" * 64
    if generated:
        print(f"\n{banner}\n FIRST RUN: administrator account created\n   username: {config.ADMIN_USERNAME}\n   password: {pw}\n"
              f" Write this down - it is shown only once. Reset: python scripts/reset_admin_password.py\n{banner}\n", flush=True)
    else:
        print(f"Administrator '{config.ADMIN_USERNAME}' created with the password from .env", flush=True)


def _warm_models() -> None:
    """Load/validate models in the background so the first analysis and the status page are fast."""
    try:
        from .ml.registry import registry
        from .services.settings_service import get_settings
        from .services import model_status
        with SessionLocal() as db:
            s = get_settings(db)
            registry.ensure(s)
            model_status.persist_registry(db, registry.snapshot(s, model_status.evaluations(db)))
    except Exception:
        log.exception("Model warm-up failed (status page will show details)")


@asynccontextmanager
async def lifespan(app: FastAPI):
    config.ensure_dirs()
    get_engine()
    log.info("Database file in use: %s", config.DB_PATH if config.DATABASE_URL.startswith("sqlite") else "(custom URL)")
    info = init_db()
    if info.get("migrated"):
        log.warning("Database migrated v%s -> v%s (backup: %s)", info["from"], info["to"], info["backup"])
    seed_admin()
    threading.Thread(target=_warm_models, name="model-loader", daemon=True).start()
    manager.start()
    from .services import settings_service
    from .routers.system import run_retention
    with SessionLocal() as db:
        if settings_service.get_settings(db)["retention"]["auto_cleanup"]:
            log.info("Retention cleanup: %s", run_retention(db))
    yield
    manager.shutdown()


app = FastAPI(title="Campus Safety Video Analytics", version="1.4.0", lifespan=lifespan)


@app.middleware("http")
async def security_middleware(request: Request, call_next):
    # CSRF defence: reject cross-origin state-changing requests (cookie is also SameSite=Lax)
    if request.method not in ("GET", "HEAD", "OPTIONS"):
        origin = request.headers.get("origin")
        if origin and urlparse(origin).netloc != request.headers.get("host"):
            return JSONResponse({"detail": "Cross-origin request rejected"}, status_code=403)
    resp = await call_next(request)
    resp.headers.setdefault("X-Content-Type-Options", "nosniff")
    resp.headers.setdefault("X-Frame-Options", "DENY")
    resp.headers.setdefault("Referrer-Policy", "same-origin")
    if request.url.path.startswith("/api/"):
        resp.headers.setdefault("Cache-Control", "no-store")
    return resp


@app.exception_handler(Exception)
async def unhandled(request: Request, exc: Exception):
    log.exception("Unhandled error on %s %s", request.method, request.url.path)  # details stay in the server log
    return JSONResponse({"detail": "Internal server error"}, status_code=500)


for r in (auth.router, videos.router, events.router, reports.router, system.router, compliance.router):
    app.include_router(r)


@app.get("/api/health")
def health():
    return {"status": "ok"}


app.mount("/", StaticFiles(directory=config.STATIC_DIR, html=True), name="static")
