"""Every column the ORM expects must exist in a migrated legacy database (checked without SQLAlchemy by
parsing models.py with `ast`). Also: the DB location must not depend on the working directory."""
import ast
import os
import sqlite3
import subprocess
import sys
from pathlib import Path
from app import migrations
from tests.legacy_schema import build_v1

ROOT = Path(__file__).resolve().parent.parent


def orm_columns() -> dict:
    tree = ast.parse((ROOT / "app" / "models.py").read_text(encoding="utf-8"))
    out = {}
    for cls in [n for n in tree.body if isinstance(n, ast.ClassDef)]:
        table, cols = None, []
        for st in cls.body:
            if isinstance(st, ast.Assign) and getattr(st.targets[0], "id", "") == "__tablename__":
                table = st.value.value
            if isinstance(st, ast.AnnAssign) and isinstance(st.value, ast.Call) and getattr(st.value.func, "id", "") == "mapped_column":
                cols.append(st.target.id)
        if table:
            out[table] = cols
    return out


def test_migrated_legacy_db_has_every_column_the_orm_expects(tmp_path):
    db = tmp_path / "a.db"; build_v1(db); migrations.migrate(db, tmp_path / "b")
    con = sqlite3.connect(db)
    try:
        have = {t: {r[1] for r in con.execute(f"PRAGMA table_info({t})")} for (t,) in
                con.execute("SELECT name FROM sqlite_master WHERE type='table'")}
    finally:
        con.close()
    exp = orm_columns()
    assert {"videos", "analysis_jobs", "events", "tracked_people", "reviews", "job_modules"} <= set(exp)
    for table, cols in exp.items():
        if table in have:  # brand-new tables (job_modules, track_observations, model_registry) come from create_all
            missing = [c for c in cols if c not in have[table]]
            assert not missing, f"{table} is missing columns after migration: {missing}"


def test_v3_run_history_flags_after_migration(tmp_path):
    db = tmp_path / "a.db"; build_v1(db)
    con = sqlite3.connect(db)
    con.execute("INSERT INTO analysis_jobs VALUES (3,1,'completed',1.0,NULL,NULL,NULL,0,'2026-10-05','2026-10-05 10:00','2026-10-05 10:05',9,NULL)")
    con.commit(); con.close()
    migrations.migrate(db, tmp_path / "b")
    con = sqlite3.connect(db)
    try:
        rows = con.execute("SELECT id, video_id, attempt, is_current FROM analysis_jobs ORDER BY id").fetchall()
    finally:
        con.close()
    # video 1 has jobs 1 (older) and 3 (newer): both kept, only the newest successful run is current
    assert rows == [(1, 1, 1, 0), (2, 2, 1, 1), (3, 1, 2, 1)]


def test_database_path_does_not_depend_on_working_directory(tmp_path):
    code = "from app import config; print(config.DB_PATH.resolve())"
    env = {**os.environ, "PYTHONPATH": str(ROOT)}
    env.pop("CAMPUS_DATA_DIR", None); env.pop("CAMPUS_DATABASE_URL", None)
    a = subprocess.run([sys.executable, "-c", code], cwd=ROOT, env=env, capture_output=True, text=True).stdout.strip()
    b = subprocess.run([sys.executable, "-c", code], cwd=tmp_path, env=env, capture_output=True, text=True).stdout.strip()
    assert a == b and a.endswith("campus_safety.db") and Path(a).is_absolute()
