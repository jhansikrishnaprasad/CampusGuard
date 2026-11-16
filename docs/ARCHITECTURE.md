# Architecture

```
Browser (vanilla JS SPA)  ──REST/cookie──►  FastAPI  (app/main.py, routers/*)
                                               │  services/ (settings, video_io, reporting, jobs, membership)
                                               ├─ SQLite via SQLAlchemy (app/models.py)
                                               ├─ data/videos, data/evidence  (files; DB stores relative paths)
                                               └─ JobManager thread ──► ml/pipeline.analyze()
                                                      person.py (YOLO+ByteTrack | HOG+IoU) → uniform.py + idcard.py
                                                      activity.py (TorchScript adapters) → events.py (temporal grouping)
```
* **Upload**: streamed to disk in 1 MB chunks, validated (extension, signature, decode first frame, metadata, limits), DB row created, job queued; HTTP returns immediately.
* **Pipeline**: `cap.grab()` skips frames cheaply, `retrieve()` only on sampled frames (default 2 fps persons; 4 fps if an activity model is ready). Rolling buffers of a few seconds only; the file is never loaded into RAM. Progress is written to the DB every ~2 s; cancellation is polled every ~1 s.
* **Jobs**: statuses `queued→running→completed|failed|cancelled`, video status `uploaded→queued→processing→completed|failed|cancelled`. On restart, `running` jobs become `failed (interrupted)`, `queued` jobs are re-queued. One active job per video (HTTP 409 otherwise). Single worker thread (local prototype).
* **Findings workflow**: model output → `Event(automated_status predicted|uncertain, review_status pending_review)` → human `Review` → `confirmed|dismissed|inconclusive`. Reports count only `confirmed` as incidents.
* **Uniform/ID**: per-person samples every 2 s → majority aggregation with minimum sample count. `uncertain` / `unable_to_verify` never create events; only `possible_non_compliance` creates a review event.
* **Tables**: users, session_tokens, videos, analysis_jobs, tracked_people, events, evidence, reviews, model_evaluations, settings, audit_log (FKs, check constraint, indexes in `models.py`).
* **Replaceable parts**: add detectors by implementing `process(frame,t)->[Det]`; add activity models via TorchScript+JSON; custom ID detector via settings path.

## v1.1 additions
* **Registry** (`ml/registry.py`): models load once (warm-up thread at start-up), are re-validated when relevant settings change, and expose state + evaluation status to the API/UI/PDF.
* **Coverage / partial status**: `pipeline.build_coverage` records which requested modules ran; `jobs._run_job` stores it and sets `completed_partial` when any did not.
* **Schema versioning**: `migrations.py` (raw sqlite3, transactional) runs before SQLAlchemy `create_all`; `backup.py` validates and restores.
* **Failure containment**: `run_job` wraps `_run_job`; any unexpected error is written by `_mark_failed` in a fresh session.
