"""Run without the web stack: pure sqlite3. Proves the v1 -> v2 upgrade keeps and converts data safely."""
import sqlite3
from pathlib import Path
from app import migrations
from app.services import backup
from tests.legacy_schema import build_v1


def q(path, sql):
    con = sqlite3.connect(path)
    try:
        return con.execute(sql).fetchall()
    finally:
        con.close()


def test_legacy_db_detected_then_migrated_with_backup(tmp_path):
    db = tmp_path / "app.db"; build_v1(db)
    assert migrations.get_version(db) == 1
    info = migrations.migrate(db, tmp_path / "bk")
    assert info["migrated"] and info["to"] == migrations.CURRENT_VERSION
    bk = tmp_path / "bk" / info["backup"]
    assert bk.exists() and q(bk, "SELECT COUNT(*) FROM videos") == [(2,)]       # untouched pre-migration copy
    assert migrations.get_version(db) == migrations.CURRENT_VERSION


def test_no_rows_lost_and_values_converted(tmp_path):
    db = tmp_path / "app.db"; build_v1(db); migrations.migrate(db, tmp_path / "bk")
    assert q(db, "SELECT COUNT(*) FROM videos") == [(2,)] and q(db, "SELECT COUNT(*) FROM events") == [(2,)]
    ppl = dict(q(db, "SELECT track_ref, uniform_overall FROM tracked_people"))
    assert ppl == {"T1": "POSSIBLE_SHIRT_MISMATCH", "T2": "COMPLIANT", "T3": "NOT_ASSESSED"}
    ids = dict(q(db, "SELECT track_ref, id_status FROM tracked_people"))
    assert ids == {"T1": "UNCERTAIN", "T2": "CARD_VISIBLE", "T3": "NOT_ASSESSED"}
    # prior job skipped AI modules -> now truthfully reported as partial; failed job untouched
    assert dict(q(db, "SELECT id, status FROM analysis_jobs")) == {1: "completed_partial", 2: "failed"}
    assert dict(q(db, "SELECT id, status FROM videos")) == {1: "completed_partial", 2: "failed"}
    # review history preserved and mirrored onto the event; original prediction columns intact
    ev = q(db, "SELECT review_status, reviewed_by, reviewed_at, predicted_class, confidence FROM events WHERE id=1")[0]
    assert ev[0] == "confirmed" and ev[1] == "admin" and ev[2] == "2026-10-03 09:00" and ev[3] == "POSSIBLE_SHIRT_MISMATCH"
    assert q(db, "SELECT predicted_class FROM events WHERE id=2") == [("POSSIBLE_SMOKING",)]
    assert q(db, "SELECT COUNT(*) FROM reviews") == [(1,)] and q(db, "SELECT COUNT(*) FROM evidence") == [(1,)]
    assert q(db, "SELECT processing_started_at FROM videos WHERE id=1") == [("2026-10-01 10:00",)]


def test_migration_is_idempotent_and_unique_dedupe_index_exists(tmp_path):
    db = tmp_path / "app.db"; build_v1(db)
    migrations.migrate(db, tmp_path / "bk")
    assert migrations.migrate(db, tmp_path / "bk")["migrated"] is False
    keys = [r[0] for r in q(db, "SELECT dedupe_key FROM events")]
    assert len(set(keys)) == len(keys)
    con = sqlite3.connect(db)
    try:
        import pytest
        with pytest.raises(sqlite3.IntegrityError):
            con.execute("UPDATE events SET dedupe_key=(SELECT dedupe_key FROM events WHERE id=1) WHERE id=2")
    finally:
        con.close()


def test_failed_migration_rolls_back_and_keeps_data(tmp_path):
    import pytest
    db = tmp_path / "app.db"; build_v1(db)
    con = sqlite3.connect(db); con.execute("UPDATE events SET start_s=0"); con.commit(); con.close()
    orig = migrations._v1_to_v2
    def boom(c):
        c.execute("ALTER TABLE videos ADD COLUMN processing_started_at DATETIME")
        raise RuntimeError("simulated failure")
    migrations._v1_to_v2 = boom
    try:
        with pytest.raises(migrations.MigrationError):
            migrations.migrate(db, tmp_path / "bk")
    finally:
        migrations._v1_to_v2 = orig
    assert migrations.get_version(db) == 1                                   # still legacy
    assert "processing_started_at" not in [c[1] for c in q(db, "PRAGMA table_info(videos)")]   # DDL rolled back
    assert q(db, "SELECT COUNT(*) FROM videos") == [(2,)]


def test_fresh_or_missing_db_not_touched(tmp_path):
    assert migrations.migrate(tmp_path / "none.db", tmp_path / "bk")["migrated"] is False


def test_backup_validate_and_restore_roundtrip(tmp_path):
    import pytest
    db = tmp_path / "app.db"; build_v1(db); migrations.migrate(db, tmp_path / "bk")
    bk = backup.create_backup(db, tmp_path / "backups")
    v = backup.validate_backup(bk)
    assert v["ok"] and v["counts"]["videos"] == 2 and v["schema_version"] == migrations.CURRENT_VERSION
    con = sqlite3.connect(db); con.execute("DELETE FROM reviews"); con.execute("DELETE FROM videos WHERE id=2"); con.commit(); con.close()
    keep = backup.restore_backup(bk, db, tmp_path / "backups")
    assert keep is not None and keep.exists()                          # current state preserved before swap
    assert q(db, "SELECT COUNT(*) FROM videos") == [(2,)] and q(db, "SELECT COUNT(*) FROM reviews") == [(1,)]


def test_restore_refuses_garbage_and_wrong_database(tmp_path):
    import pytest
    db = tmp_path / "app.db"; build_v1(db)
    junk = tmp_path / "junk.db"; junk.write_bytes(b"not sqlite" * 50)
    other = tmp_path / "other.db"; c = sqlite3.connect(other); c.execute("CREATE TABLE x(a)"); c.commit(); c.close()
    for bad in (junk, other, tmp_path / "missing.db"):
        assert backup.validate_backup(bad)["ok"] is False
        with pytest.raises(ValueError):
            backup.restore_backup(bad, db, tmp_path / "b")
    assert q(db, "SELECT COUNT(*) FROM videos") == [(2,)]               # live DB untouched


def test_validate_detects_newer_schema(tmp_path):
    db = tmp_path / "app.db"; build_v1(db); migrations.migrate(db, tmp_path / "bk")
    con = sqlite3.connect(db); con.execute("INSERT INTO schema_version VALUES (99,'x')"); con.commit(); con.close()
    r = backup.validate_backup(db)
    assert not r["ok"] and any("newer" in e for e in r["errors"])
