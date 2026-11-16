# Database: connection, schema, migrations, verification

**Engine:** SQLite via SQLAlchemy 2.x. **File:** `<project>/data/campus_safety.db` (resolved from the location of `app/config.py`, so it is the
same file whatever folder you start the app from). Override with `CAMPUS_DATA_DIR` (folder) or `CAMPUS_DATABASE_URL` in `.env`.
Tests set `CAMPUS_DATA_DIR` to a temporary folder (`tests/conftest.py`), so the real database is never touched.

**Connection settings** (`app/database.py`): `PRAGMA foreign_keys=ON` and `busy_timeout` on every connection, WAL journal mode, 30 s timeout, `pool_pre_ping`,
one session per request (`get_db`, rolled back on error) and one short-lived session per worker operation. The analysis worker never holds a transaction while
inference runs: progress writes are tiny separate transactions and results are saved in ONE transaction at the end (per-finding savepoints, rollback on failure).
Start-up fails with a clear message if the folder is not writable or the database cannot be opened. The log line `Database file in use: ...` and
Settings -> *Database in use* (admin; `GET /api/system/db`) show the physical file, schema version, row counts, foreign-key violations and any other `.db`
files found next to the project (a sign of an accidental second database).

## Tables (schema v3)
users, session_tokens, **videos** (hash, metadata, status, processing start/finish), **analysis_jobs** (status, progress, attempt, is_current, partial, coverage,
model_versions, settings_snapshot, warnings, error), **job_modules** (per module: requested/ran/state/result/model/version/evaluation), **tracked_people**
(temporary track id, first/last seen, shirt/trouser/overall uniform result, score, method, version, ID result, confidence, association),
**track_observations** (sampled boxes + confidence + time), **events** (category, interval, confidence, model, original `predicted_class`/`automated_status`, review fields,
`dedupe_key`), **evidence** (relative path, kind, time), **reviews** (decision, previous_status, reviewer, notes, time), **model_registry** (last known state per module),
**model_evaluations** (metrics, sample counts, thresholds, status), settings, audit_log, schema_version.
Foreign keys use ON DELETE CASCADE from videos/jobs; CHECK constraints on status columns (new databases); unique index on `events.dedupe_key`, unique (job_id, module).
Timestamps are UTC.

## Runs and history
Every analysis creates a new `analysis_jobs` row (`attempt` 1, 2, ...). Nothing from earlier runs is deleted. The latest **successful** run has `is_current=1`; lists,
dashboard and reports use the current run by default (`include_history=true` or `job_id=N` to see others). A failed or cancelled retry never replaces the current results.
Reviews belong to events and stay with their run. Re-running therefore does not erase decisions, and the same finding of two runs is not double counted in default views.

## Review rules
Decisions: confirmed / dismissed / inconclusive (cannot be set back to pending). Every decision writes an immutable `reviews` row (with `previous_status`) and an audit row;
the event keeps its original prediction fields. Re-sending the identical decision is rejected (409) so history is not padded.

## Migrations
`app/migrations.py` (plain sqlite3): detects the schema version, **copies the database to `data/backups/pre_migration_v<N>_*.db`**, then upgrades inside one transaction and
rolls back on any error. v1->v2 and v2->v3 only add columns/indexes and convert old values; nothing is dropped. SQLAlchemy `create_all` then adds new tables.
`tests/test_migrations.py` and `tests/test_schema_consistency.py` check this against a hand-built v1 database.

## Backup / restore
Settings buttons or `scripts/backup_db.py` (verified copy), `scripts/restore_db.py <file>` (validate only) and `... --yes` (restore; server stopped; current DB kept as `pre_restore_*.db`).
Backups contain the database only; copy `data/videos` and `data/evidence` for footage.

## Verifying persistence yourself
`tests/test_e2e.py` performs: DB file check -> upload -> job -> stored results/evidence -> review -> report -> reprocess -> **restart** -> verify counts, history, evidence files,
foreign keys, and that no second `.db` exists. Run `run_tests.ps1`.
