# Changelog

## 1.4.0 - release preparation (packaging, documentation, deployment files)
* **Windows launcher + PyInstaller packaging** (`launcher.py`, `CampusGuard.spec`, `build_exe.ps1`, `requirements-build.txt`): data/models/logs/.env live in `%LOCALAPPDATA%\CampusGuard`
  (new `CAMPUS_HOME` setting; `config.BASE_DIR` is the writable root, `STATIC_DIR` stays with the code), readable start-up errors, browser auto-open, port fallback, `--selftest`.
  **The .exe must be built on Windows; it was not built in the release environment.**
* **Clean shutdown:** `POST /api/system/shutdown` (admin, loopback client only, only when the launcher sets `CAMPUS_ALLOW_SHUTDOWN=true`) + "Quit CampusGuard" button.
* **Deployment files (untested here):** `Dockerfile`, `docker-compose.yml` (Caddy HTTPS), `Caddyfile`, `.env.deploy.example`, `docs/DEPLOYMENT.md`.
* **Documentation:** new README, `docs/DATASETS.md`, `docs/ML_STATUS.md`, `docs/INSTALLATION_GUIDE.md`, `docs/DEPLOYMENT.md`, `TESTING_REPORT.md`, `LICENSE` (MIT), `THIRD_PARTY_NOTICES.md`, screenshots.
* **Publishing:** `scripts/publish_to_github.ps1` (GitHub CLI browser sign-in; no password/token handling), hardened `.gitignore`.
* **GitHub Actions:** `build-windows-exe.yml` (builds + self-tests CampusGuard.exe on a GitHub Windows runner) and `tests.yml` (pytest). Not yet run.
* **Datasets:** `docs/DATASETS.md` re-checked against official pages (RWF-2000 videos currently unavailable; HMDB51 `hit`/`push` are not violence classes; Kinetics/UCF101 licences unconfirmed).
* **Publishing:** `docs/PUBLISH_TO_GITHUB.md`; the publish script now fills in your repository URL and starts the cloud builds.
* **Tests:** `tests/test_packaging.py`.

## 1.3.0 – video-level compliance warnings and notifications
**Upgrade:** extract over the project folder and start. No new packages. A v3 database is backed up and migrated to v4 automatically (adds nothing but a missing `reviews.previous_status` column; no data is changed or removed).
* **Compliance summary (new, derived only from existing `tracked_people` / `analysis_jobs` rows; no new table):** `app/services/compliance_summary.py`.
  Person-level counts for ONE run (latest successful run by default, or `?job_id=`): total, possible uniform non-compliance, ID card not detected, both (overlapping subset),
  uniform-only, ID-only, apparently compliant, uncertain, not assessed. Every person falls into exactly one exclusive group (validated on every call).
  ID `UNCERTAIN` is never converted to `CARD_NOT_DETECTED`; the default heuristic can only return UNCERTAIN, so its counts stay honest.
* **API:** `GET /api/videos/{id}/compliance-summary`, `GET /api/videos/{id}/compliance-people?filter=`, `GET /api/compliance/overview`, `GET /api/reports/compliance.csv`.
* **UI:** "VIDEO COMPLIANCE ALERTS" section on the video page (6 cards, exclusive breakdown bar, dynamic warning panel, person-wise review with filters, evidence modal, jump-to-timestamp),
  compliance overview + recent alerts on the dashboard, in-app completion notifications (no duplicates while polling / after refresh / on navigation), optional browser notifications (opt-in by click).
* **Reports:** PDF gains "VIDEO-LEVEL UNIFORM AND ID-CARD COMPLIANCE SUMMARY"; separate person-level compliance CSV. Existing event CSV and filters unchanged.
* **Bug fix:** `models.Review` was missing the `previous_status` column that `events.py`, the v3 migration and the docs already use (reviewing an event failed on a fresh database). Added to the model + v4 self-healing migration.
* **No sign-in screen by default (local single-user mode):** the app opens straight on the dashboard and acts as the admin user. Set `CAMPUS_REQUIRE_LOGIN=true` in `.env` to restore username/password login.
  Only run in this mode on `127.0.0.1` (the default in `run.ps1`); turn login back on before exposing the app to any network.
* **Tests:** `tests/test_nologin.py`, `tests/test_compliance.py`, `tests/frontend_notifications.test.js`.

## 1.2.0 – run history, per-module outcomes, trained-model paths, E2E persistence test
**Upgrade:** extract over the project folder and start. A v1/v2 database is backed up and migrated to v3 automatically.
* **Database:** schema v3 (videos.sha256, analysis_jobs.attempt/is_current, job_modules, track_observations, model_registry, tracked_people score/method/version, reviews.previous_status).
  Reprocessing now KEEPS earlier runs; lists/reports use the current run, `include_history=true` shows all. Duplicate uploads are flagged by content hash.
  Connection hardening (timeout, pre-ping, rollback per request, start-up checks), `GET /api/system/db`, `docs/DATABASE.md`.
* **Honest outcomes:** per-run module table (ran / not assessed / nothing detected / possible ...). Reports state when modules did not run so zero findings is never read as "nothing happened".
  Uniform shows both the detailed result and the simple COMPLIANT / POSSIBLE_VIOLATION / UNCERTAIN / NOT_ASSESSED mapping.
* **AI:** tracker with motion prediction and size-checked centre matching (fewer ID breaks); optional trained uniform colour classifier (safe JSON, session-split training and
  side-by-side evaluation vs the baseline); activity events list the people tracked in the interval (context only); training scripts for ID-card YOLO and action models.
  The ID-card heuristic was re-tested and NOT changed (0/4 on the reference photo; evidence did not support an improvement).
* **UI:** Uniform & ID cards redesigned (responsive grid, wrapping labels), module outcomes, run history, coverage warnings, database panel, earlier-runs toggles.
* **Tests:** `tests/test_e2e.py` (upload -> report -> restart), schema-consistency, tracker, classifier, review audit, history.

## 1.1.0 – database safety, honest model status, partial-analysis reporting
**Safe upgrade:** start the new version on your existing project folder. If `data/campus_safety.db` is an older (v1) database it is
backed up to `data/backups/pre_migration_v1_*.db` and upgraded in one all-or-nothing transaction. No rows are deleted.

### Database
* `schema_version` table + `app/migrations.py` (stdlib sqlite3, transactional, idempotent, rolls back on failure).
* New columns: `videos.processing_started_at/completed_at`; `analysis_jobs.partial/coverage`; `events.predicted_class/reviewed_at/reviewed_by/dedupe_key`;
  `model_evaluations.sample_count/positive_count/thresholds/status`.
* Unique index `ux_events_dedupe` (no duplicate findings per job/category/track/start); CHECK constraints on status columns for new databases
  (existing databases are protected by application validation because SQLite cannot add CHECKs to existing tables).
* Old values converted to the new vocabulary; earlier jobs that had skipped AI modules are relabelled `completed_partial`.
* `app/services/backup.py`: verified backups (integrity + foreign-key + required tables + schema version), validation without restoring, safe restore script.
* Review decisions only write `review_*` columns; the original prediction (`confidence`, `automated_status`, `predicted_class`, model fields) is never overwritten.
* Worker: every crash path now marks the job and video `failed` (no video stuck in PROCESSING); results are saved in one transaction with per-finding savepoints.

### AI / honesty
* `app/ml/registry.py`: one place that loads and validates models; states LOADED / FILE_MISSING / DEPENDENCY_MISSING / LOAD_FAILED / NOT_CONFIGURED / DISABLED,
  plus NOT_EVALUATED / EVALUATED. TorchScript models get a sidecar-schema check and a dry-run forward pass at load time.
* Jobs finish as `completed_partial` when any requested module did not run; per-module coverage is stored and shown.
* Uniform results: COMPLIANT / POSSIBLE_SHIRT_MISMATCH / POSSIBLE_TROUSER_MISMATCH / POSSIBLE_UNIFORM_MISMATCH / UNCERTAIN / NOT_ASSESSED, with shadow-tolerant beige test.
* ID card: CARD_VISIBLE / CARD_NOT_DETECTED (never proof of absence) / UNCERTAIN / NOT_ASSESSED.
* Evaluation: one-to-one event matching (duplicates are false positives), `scripts/evaluate.py` records thresholds and sample counts, new `scripts/evaluate_uniform.py`.

### Security / UX
* Generic 500 handler (details only in the server log), error text stripped of local paths, uploaded filenames sanitised, retention never deletes footage/evidence of findings still pending review.
* UI: partial-analysis banners, model-registry table, model warnings on Dashboard/Upload, missing-evidence placeholders, backup validation button.
