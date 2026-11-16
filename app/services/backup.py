"""Database backup / validation / restore (standard library only, safe against corrupt files)."""
from __future__ import annotations
import os
import shutil
import sqlite3
from datetime import datetime
from pathlib import Path

REQUIRED_TABLES = {"users", "videos", "analysis_jobs", "tracked_people", "events", "evidence", "reviews",
                   "settings", "audit_log"}


def create_backup(db_path: Path, dest_dir: Path, prefix: str = "campus_safety") -> Path:
    """Consistent online backup (sqlite backup API) that is verified before being returned."""
    db_path, dest_dir = Path(db_path), Path(dest_dir)
    if not db_path.exists():
        raise FileNotFoundError("Database file does not exist")
    dest_dir.mkdir(parents=True, exist_ok=True)
    dest = dest_dir / f"{prefix}_{datetime.now():%Y%m%d_%H%M%S_%f}.db"
    src, dst = sqlite3.connect(db_path), sqlite3.connect(dest)
    try:
        src.backup(dst)
    finally:
        dst.close(); src.close()
    res = validate_backup(dest, require_app_tables=False)
    # Orphaned rows (foreign-key problems) must not block taking a safety copy of a damaged DB;
    # only real corruption does.
    hard = [e for e in res["errors"] if not e.endswith("foreign-key violation(s)")]
    if hard:
        dest.unlink(missing_ok=True)
        raise RuntimeError("Backup verification failed: " + "; ".join(hard))
    return dest


def validate_backup(path: Path, require_app_tables: bool = True) -> dict:
    """Open read-only, run integrity + foreign-key checks, confirm it is a CampusGuard database."""
    from ..migrations import CURRENT_VERSION
    out = {"ok": False, "errors": [], "warnings": [], "schema_version": None, "counts": {}}
    path = Path(path)
    if not path.is_file():
        out["errors"].append("File not found"); return out
    try:
        with open(path, "rb") as f:
            if f.read(16) != b"SQLite format 3\x00":
                out["errors"].append("Not an SQLite database file"); return out
        con = sqlite3.connect(f"file:{path.as_posix()}?mode=ro", uri=True)
    except Exception as e:
        out["errors"].append(f"Cannot open: {e}"); return out
    try:
        ic = [r[0] for r in con.execute("PRAGMA integrity_check")]
        if ic != ["ok"]:
            out["errors"].append("integrity_check failed: " + "; ".join(ic[:3]))
        fk = con.execute("PRAGMA foreign_key_check").fetchall()
        if fk:
            out["errors"].append(f"{len(fk)} foreign-key violation(s)")
        tables = {r[0] for r in con.execute("SELECT name FROM sqlite_master WHERE type='table'")}
        if require_app_tables:
            missing = REQUIRED_TABLES - tables
            if missing:
                out["errors"].append("Missing tables: " + ", ".join(sorted(missing)))
        if "schema_version" in tables:
            v = con.execute("SELECT MAX(version) FROM schema_version").fetchone()[0]
            out["schema_version"] = v
            if v and v > CURRENT_VERSION:
                out["errors"].append(f"Backup schema v{v} is newer than this application (v{CURRENT_VERSION})")
        elif "videos" in tables:
            out["schema_version"] = 1
            out["warnings"].append("Legacy schema v1: it will be migrated automatically on next start")
        for t in ("videos", "events", "reviews", "users"):
            if t in tables:
                out["counts"][t] = con.execute(f"SELECT COUNT(*) FROM {t}").fetchone()[0]
    except Exception as e:
        out["errors"].append(f"Validation error: {e}")
    finally:
        con.close()
    out["ok"] = not out["errors"]
    return out


def restore_backup(backup: Path, db_path: Path, backup_dir: Path) -> Path | None:
    """Validate, keep a copy of the current DB, then atomically swap. Server MUST be stopped."""
    res = validate_backup(backup)
    if not res["ok"]:
        raise ValueError("Refusing to restore invalid backup: " + "; ".join(res["errors"]))
    db_path = Path(db_path)
    keep = None
    if db_path.exists():
        keep = create_backup(db_path, backup_dir, prefix="pre_restore")
    for ext in ("-wal", "-shm"):
        Path(str(db_path) + ext).unlink(missing_ok=True)
    tmp = db_path.with_suffix(".restoring")
    shutil.copy2(backup, tmp)
    os.replace(tmp, db_path)
    return keep
