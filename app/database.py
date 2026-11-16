from __future__ import annotations
import os
from pathlib import Path
from sqlalchemy import create_engine, event
from sqlalchemy.orm import sessionmaker
from . import config

_engine = None
SessionLocal = sessionmaker(autoflush=False, expire_on_commit=False)


def get_engine():
    global _engine
    if _engine is None:
        config.ensure_dirs()
        _engine = create_engine(config.DATABASE_URL, connect_args={"check_same_thread": False, "timeout": 30}, pool_pre_ping=True)

        @event.listens_for(_engine, "connect")
        def _pragmas(dbapi_conn, _):  # foreign keys + WAL for concurrent worker/web access
            cur = dbapi_conn.cursor()
            cur.execute("PRAGMA foreign_keys=ON")
            cur.execute("PRAGMA journal_mode=WAL")
            cur.execute("PRAGMA busy_timeout=5000")
            cur.close()

        SessionLocal.configure(bind=_engine)
    return _engine


def init_db() -> dict:
    """Safe schema initialisation: migrate an existing DB (after an automatic backup), create missing
    tables, stamp the schema version. Never drops anything."""
    from . import migrations
    from .models import Base
    eng = get_engine()
    check_database()
    info = {"migrated": False}
    path = eng.url.database if eng.url.get_backend_name() == "sqlite" else None
    if path:
        info = migrations.migrate(Path(path), config.BACKUP_DIR)
    Base.metadata.create_all(eng)
    if path:
        migrations.stamp(Path(path))
    return info


def check_database() -> None:
    """Fail at start-up with a clear message instead of limping along on a wrong/unwritable database."""
    from sqlalchemy import text
    from sqlalchemy.exc import SQLAlchemyError
    eng = get_engine()
    if eng.url.get_backend_name() == "sqlite" and eng.url.database:
        p = Path(eng.url.database)
        if not os.access(p.parent, os.W_OK):
            raise RuntimeError(f"Database folder is not writable: {p.parent}. Check permissions or CAMPUS_DATA_DIR.")
    try:
        with eng.connect() as c:
            c.execute(text("SELECT 1"))
    except SQLAlchemyError as e:
        raise RuntimeError(f"Cannot open the database ({type(e).__name__}). Is another program locking it, or is the file damaged? "
                           "Restore a backup with scripts/restore_db.py.") from e


def get_db():
    get_engine()
    db = SessionLocal()
    try:
        yield db
    except Exception:
        db.rollback()   # a failed request never leaves a half-finished transaction behind
        raise
    finally:
        db.close()
