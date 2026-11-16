"""Safe, reversible, data-preserving schema migrations (standard library sqlite3 only).

* Existing databases (schema v1, no schema_version table) are backed up first, then upgraded in ONE
  transaction (all-or-nothing). Nothing is dropped; old rows are converted to the new status vocabulary.
* Fresh databases are created by SQLAlchemy `create_all` and then stamped with CURRENT_VERSION.
"""
from __future__ import annotations
import sqlite3
from datetime import datetime
from pathlib import Path

CURRENT_VERSION = 4


class MigrationError(RuntimeError):
    pass


def _tables(con) -> set:
    return {r[0] for r in con.execute("SELECT name FROM sqlite_master WHERE type='table'")}


def _cols(con, table) -> set:
    return {r[1] for r in con.execute(f"PRAGMA table_info({table})")}


def get_version(db_path: Path) -> int | None:
    """None = no application tables yet; 1 = legacy DB without version table."""
    if not Path(db_path).exists():
        return None
    con = sqlite3.connect(db_path)
    try:
        t = _tables(con)
        if "videos" not in t:
            return None
        if "schema_version" not in t:
            return 1
        row = con.execute("SELECT MAX(version) FROM schema_version").fetchone()
        return int(row[0]) if row and row[0] is not None else 1
    finally:
        con.close()


def stamp(db_path: Path, version: int = CURRENT_VERSION) -> None:
    con = sqlite3.connect(db_path)
    try:
        con.execute("CREATE TABLE IF NOT EXISTS schema_version (version INTEGER NOT NULL, applied_at TEXT NOT NULL)")
        if con.execute("SELECT COUNT(*) FROM schema_version WHERE version=?", (version,)).fetchone()[0] == 0:
            con.execute("INSERT INTO schema_version VALUES (?, ?)", (version, datetime.utcnow().isoformat()))
        con.commit()
    finally:
        con.close()


_ADD_V2 = {
    "videos": [("processing_started_at", "DATETIME"), ("processing_completed_at", "DATETIME")],
    "analysis_jobs": [("partial", "INTEGER NOT NULL DEFAULT 0"), ("coverage", "TEXT")],
    "events": [("reviewed_at", "DATETIME"), ("reviewed_by", "VARCHAR(64)"),
               ("predicted_class", "VARCHAR(48)"), ("dedupe_key", "VARCHAR(160)")],
    "model_evaluations": [("sample_count", "INTEGER"), ("positive_count", "INTEGER"), ("thresholds", "TEXT"),
                          ("status", "VARCHAR(16) NOT NULL DEFAULT 'completed'")],
}


def _v1_to_v2(con: sqlite3.Connection) -> None:
    t = _tables(con)
    for table, cols in _ADD_V2.items():
        if table not in t:
            continue
        have = _cols(con, table)
        for name, ddl in cols:
            if name not in have:
                con.execute(f"ALTER TABLE {table} ADD COLUMN {name} {ddl}")
    if "tracked_people" in t:
        con.execute("""UPDATE tracked_people SET uniform_overall = CASE
            WHEN uniform_overall='compliant' THEN 'COMPLIANT'
            WHEN uniform_overall='uncertain' THEN 'UNCERTAIN'
            WHEN uniform_overall='unable_to_verify' THEN 'NOT_ASSESSED'
            WHEN uniform_overall='possible_non_compliance' THEN CASE
                 WHEN shirt_status='inconsistent' AND trouser_status='inconsistent' THEN 'POSSIBLE_UNIFORM_MISMATCH'
                 WHEN shirt_status='inconsistent' THEN 'POSSIBLE_SHIRT_MISMATCH'
                 WHEN trouser_status='inconsistent' THEN 'POSSIBLE_TROUSER_MISMATCH'
                 ELSE 'UNCERTAIN' END
            ELSE uniform_overall END""")
        con.execute("""UPDATE tracked_people SET id_status = CASE id_status
            WHEN 'detected' THEN 'CARD_VISIBLE' WHEN 'not_detected' THEN 'CARD_NOT_DETECTED'
            WHEN 'uncertain' THEN 'UNCERTAIN' WHEN 'not_configured' THEN 'NOT_ASSESSED' ELSE id_status END""")
    if "events" in t:
        con.execute("""UPDATE events SET predicted_class = CASE
            WHEN category='uniform_possible_violation' THEN COALESCE((
                SELECT p.uniform_overall FROM tracked_people p
                WHERE p.video_id=events.video_id AND p.track_ref=events.track_ref LIMIT 1), 'POSSIBLE_UNIFORM_MISMATCH')
            ELSE UPPER(category) END WHERE predicted_class IS NULL""")
        if "reviews" in t:
            con.execute("""UPDATE events SET
                reviewed_at=(SELECT MAX(created_at) FROM reviews r WHERE r.event_id=events.id),
                reviewed_by=(SELECT reviewer FROM reviews r WHERE r.event_id=events.id ORDER BY r.id DESC LIMIT 1)
                WHERE review_status!='pending_review' AND reviewed_at IS NULL""")
        con.execute("UPDATE events SET dedupe_key='legacy:' || id WHERE dedupe_key IS NULL")
        con.execute("CREATE UNIQUE INDEX IF NOT EXISTS ux_events_dedupe ON events(dedupe_key)")
    if "analysis_jobs" in t:
        # Earlier jobs that skipped requested AI modules were reported as plain 'completed': correct that.
        con.execute("""UPDATE analysis_jobs SET partial=1, status='completed_partial'
                       WHERE status='completed' AND warnings LIKE '%recognition not run%'""")
        if "videos" in t:
            con.execute("""UPDATE videos SET status='completed_partial' WHERE status='completed' AND EXISTS (
                SELECT 1 FROM analysis_jobs j WHERE j.video_id=videos.id AND j.status='completed_partial'
                AND j.id=(SELECT MAX(id) FROM analysis_jobs j2 WHERE j2.video_id=videos.id))""")
            con.execute("""UPDATE videos SET
                processing_started_at=(SELECT started_at FROM analysis_jobs j WHERE j.video_id=videos.id ORDER BY id DESC LIMIT 1),
                processing_completed_at=(SELECT finished_at FROM analysis_jobs j WHERE j.video_id=videos.id ORDER BY id DESC LIMIT 1)
                WHERE processing_started_at IS NULL""")


_ADD_V3 = {
    "videos": [("sha256", "VARCHAR(64)")],
    "analysis_jobs": [("attempt", "INTEGER NOT NULL DEFAULT 1"), ("is_current", "INTEGER NOT NULL DEFAULT 1")],
    "tracked_people": [("uniform_score", "FLOAT"), ("uniform_method", "VARCHAR(48)"), ("uniform_version", "VARCHAR(32)"),
                       ("id_confidence", "FLOAT"), ("id_method", "VARCHAR(48)"), ("id_version", "VARCHAR(32)"),
                       ("id_association", "VARCHAR(32)")],
    "reviews": [("previous_status", "VARCHAR(16)")],
}


def _v2_to_v3(con: sqlite3.Connection) -> None:
    t = _tables(con)
    for table, cols in _ADD_V3.items():
        if table not in t:
            continue
        have = _cols(con, table)
        for name, ddl in cols:
            if name not in have:
                con.execute(f"ALTER TABLE {table} ADD COLUMN {name} {ddl}")
    if "videos" in t:
        con.execute("CREATE INDEX IF NOT EXISTS ix_videos_sha256 ON videos(sha256)")
    if "analysis_jobs" in t:
        con.execute("CREATE INDEX IF NOT EXISTS ix_analysis_jobs_is_current ON analysis_jobs(is_current)")
        # run number per video (1 = first run); history is preserved, only the latest successful run is "current"
        con.execute("""UPDATE analysis_jobs SET attempt =
            (SELECT COUNT(*) FROM analysis_jobs j2 WHERE j2.video_id=analysis_jobs.video_id AND j2.id<=analysis_jobs.id)""")
        con.execute("UPDATE analysis_jobs SET is_current=0")
        con.execute("""UPDATE analysis_jobs SET is_current=1 WHERE id IN (
            SELECT MAX(id) FROM analysis_jobs WHERE status IN ('completed','completed_partial') GROUP BY video_id)""")
        con.execute("""UPDATE analysis_jobs SET is_current=1 WHERE id IN (
            SELECT MAX(id) FROM analysis_jobs GROUP BY video_id
            HAVING SUM(status IN ('completed','completed_partial'))=0)""")


def _v3_to_v4(con: sqlite3.Connection) -> None:
    """Self-heal: databases created by a build whose ORM model lacked reviews.previous_status (v3-stamped
    but without the column). Only ADDS the column when it is missing; nothing is changed or dropped."""
    if "reviews" in _tables(con) and "previous_status" not in _cols(con, "reviews"):
        con.execute("ALTER TABLE reviews ADD COLUMN previous_status VARCHAR(16)")


def migrate(db_path: Path, backup_dir: Path) -> dict:
    """Upgrade an existing database in place. Returns info dict; never loses data (backup + transaction)."""
    ver = get_version(db_path)
    if ver is None or ver >= CURRENT_VERSION:
        return {"migrated": False, "from": ver, "to": ver}
    from .services.backup import create_backup  # stdlib-only module
    backup_dir.mkdir(parents=True, exist_ok=True)
    bk = create_backup(db_path, backup_dir, prefix=f"pre_migration_v{ver}")
    con = sqlite3.connect(db_path, isolation_level=None)
    try:
        con.execute("BEGIN IMMEDIATE")
        try:
            if ver < 2:
                _v1_to_v2(con)
            if ver < 3:
                _v2_to_v3(con)
            if ver < 4:
                _v3_to_v4(con)
            con.execute("CREATE TABLE IF NOT EXISTS schema_version (version INTEGER NOT NULL, applied_at TEXT NOT NULL)")
            con.execute("INSERT INTO schema_version VALUES (?, ?)", (CURRENT_VERSION, datetime.utcnow().isoformat()))
            con.execute("COMMIT")
        except Exception as e:
            con.execute("ROLLBACK")
            raise MigrationError(f"Migration failed and was rolled back. Your data is unchanged. Backup: {bk.name}. Cause: {e}") from e
    finally:
        con.close()
    return {"migrated": True, "from": ver, "to": CURRENT_VERSION, "backup": bk.name}
