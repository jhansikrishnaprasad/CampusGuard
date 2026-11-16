"""Background analysis worker: one daemon thread, DB-backed job state (survives restarts)."""
from __future__ import annotations
import json
import logging
import queue
import shutil
import threading
import time
from pathlib import Path
from fastapi import HTTPException
from sqlalchemy import func
from sqlalchemy.exc import IntegrityError
from sqlalchemy.orm import Session
from .. import config
from ..database import SessionLocal
from .. import constants as C
from ..ml import pipeline
from ..ml.registry import registry
from ..models import (AnalysisJob, Event, Evidence, JobModule, ModelEvaluation, TrackedPerson, TrackObservation, Video,
                      utcnow)
from . import video_io
from .errors import sanitize_error
from . import model_status
from .settings_service import get_settings

log = logging.getLogger(__name__)
ACTIVE = ("queued", "running")


class JobManager:
    def __init__(self):
        self.q: "queue.Queue[int]" = queue.Queue()
        self.thread: threading.Thread | None = None
        self.stop = threading.Event()

    def start(self) -> None:
        with SessionLocal() as db:
            for j in db.query(AnalysisJob).filter(AnalysisJob.status == "running").all():
                j.status, j.error, j.finished_at = "failed", "Interrupted by application restart. Use Reprocess.", utcnow()
                if j.video:
                    j.video.status, j.video.error = "failed", j.error
                    j.video.processing_completed_at = j.finished_at
            queued = [j.id for j in db.query(AnalysisJob).filter(AnalysisJob.status == "queued").order_by(AnalysisJob.id)]
            db.commit()
        self.q = queue.Queue()          # fresh queue per start: a stale shutdown marker can never kill the new worker
        for jid in queued:
            self.q.put(jid)
        self.stop = threading.Event()
        self.thread = threading.Thread(target=self._loop, args=(self.q, self.stop), name="analysis-worker", daemon=True)
        self.thread.start()

    def shutdown(self) -> None:
        self.stop.set()
        self.q.put(-1)
        if self.thread is not None:
            self.thread.join(timeout=5)

    def enqueue(self, job_id: int) -> None:
        self.q.put(job_id)

    def _loop(self, q, stop) -> None:
        while not stop.is_set():
            jid = q.get()
            if jid < 0:
                break
            try:
                run_job(jid)
            except Exception:  # last-resort guard: never kill the worker
                log.exception("Unhandled worker error for job %s", jid)


manager = JobManager()


def create_job(db: Session, video: Video) -> AnalysisJob:
    if db.query(AnalysisJob).filter(AnalysisJob.video_id == video.id, AnalysisJob.status.in_(ACTIVE)).first():
        raise HTTPException(409, "An analysis job for this video is already queued or running")
    attempt = (db.query(func.count(AnalysisJob.id)).filter(AnalysisJob.video_id == video.id).scalar() or 0) + 1
    job = AnalysisJob(video_id=video.id, status="queued", attempt=attempt)
    video.status, video.error = "queued", None
    db.add(job)
    db.commit()
    manager.enqueue(job.id)
    return job


def cancel_job(db: Session, job: AnalysisJob) -> None:
    if job.status not in ACTIVE:
        raise HTTPException(409, f"Job is already {job.status}")
    job.cancel_requested = True
    if job.status == "queued":
        job.status, job.finished_at = "cancelled", utcnow()
        job.video.status = "cancelled"
    db.commit()


def _delete_files(rel_paths: list[str]) -> None:
    for rel in rel_paths:
        (config.EVIDENCE_DIR / rel).unlink(missing_ok=True)


def _mark_failed(job_id: int, message: str) -> None:
    """Last-resort writer in a FRESH session: guarantees a video can never stay stuck in PROCESSING."""
    with SessionLocal() as db:
        job = db.get(AnalysisJob, job_id)
        if job and job.status in ACTIVE:
            job.status, job.error, job.finished_at = "failed", sanitize_error(message), utcnow()
            if job.video:
                job.video.status, job.video.error = "failed", job.error
                job.video.processing_completed_at = job.finished_at
            db.commit()


def run_job(job_id: int) -> None:
    try:
        _run_job(job_id)
    except Exception as e:
        log.exception("Job %s crashed", job_id)
        try:
            _mark_failed(job_id, f"Unexpected error: {type(e).__name__}")
        except Exception:
            log.exception("Could not record failure of job %s", job_id)


def _eval_rows(db: Session) -> list[dict]:
    return [{"model_name": e.model_name, "status": e.status, "dataset_name": e.dataset_name, "precision": e.precision,
             "recall": e.recall, "f1": e.f1, "evaluated_at": e.evaluated_at.isoformat() if e.evaluated_at else None}
            for e in db.query(ModelEvaluation).order_by(ModelEvaluation.id.desc()).all()]


def _run_job(job_id: int) -> None:
    db = SessionLocal()
    try:
        job = db.get(AnalysisJob, job_id)
        if not job or job.status != "queued":
            return  # cancelled while waiting
        video = job.video
        settings = get_settings(db)
        job.status, job.started_at, job.progress = "running", utcnow(), 0.0
        job.settings_snapshot = json.dumps(settings)
        video.status, video.error = "processing", None
        video.processing_started_at, video.processing_completed_at = job.started_at, None
        db.commit()
        vpath = config.VIDEO_DIR / video.stored_name
        t0 = time.time()
        state = {"wp": 0.0, "wc": 0.0}

        def progress(p: float) -> None:
            if time.time() - state["wp"] > 2 or p >= 1:
                state["wp"] = time.time()
                with SessionLocal() as s:
                    s.query(AnalysisJob).filter(AnalysisJob.id == job_id).update({"progress": p})
                    s.commit()

        def cancelled() -> bool:
            if time.time() - state["wc"] < 1:
                return False
            state["wc"] = time.time()
            with SessionLocal() as s:
                j = s.get(AnalysisJob, job_id)
                return bool(j and j.cancel_requested)

        evals = _eval_rows(db)
        try:
            if not vpath.is_file():
                raise FileNotFoundError("Video file is missing from storage")
            if Path(video.stored_name).suffix.lower() != ".mp4" and not video.preview_name:
                pn = Path(video.stored_name).stem + "_preview.mp4"
                if video_io.make_preview(vpath, config.VIDEO_DIR / pn):
                    video.preview_name = pn
                    db.commit()
            detector, idc, recognizers = registry.for_job(settings)
            prefix = f"video_{video.id}/job_{job.id}"
            res = pipeline.analyze(vpath, config.EVIDENCE_DIR / f"video_{video.id}" / f"job_{job.id}", prefix,
                                   settings, progress, cancelled, detector=detector, idc=idc, recognizers=recognizers,
                                   uniform_clfs=registry.uniform_clfs)
        except pipeline.Cancelled:
            job.status, job.finished_at, video.status = "cancelled", utcnow(), "cancelled"
            video.processing_completed_at = job.finished_at
            job.processing_seconds = time.time() - t0
            db.commit()
            shutil.rmtree(config.EVIDENCE_DIR / f"video_{video.id}" / f"job_{job.id}", ignore_errors=True)
            return
        except Exception as e:
            log.exception("Job %s failed", job_id)
            job.status, job.error, job.finished_at = "failed", sanitize_error(f"{type(e).__name__}: {e}"), utcnow()
            job.processing_seconds = time.time() - t0
            video.status, video.error, video.processing_completed_at = "failed", job.error, job.finished_at
            db.commit()
            shutil.rmtree(config.EVIDENCE_DIR / f"video_{video.id}" / f"job_{job.id}", ignore_errors=True)
            return

        # ---- notices that must accompany the results ----
        warnings = list(res.warnings) + [f"DEGRADED: {d}" for d in res.degraded]
        for m in registry.snapshot(settings, evals):
            if m["key"] in res.coverage and res.coverage[m["key"]]["ran"] and m["evaluation"]["state"] == "NOT_EVALUATED" \
                    and m["key"] in ("fight", "smoking"):
                warnings.append(f"{m['title']} has NO recorded labelled evaluation: its predictions are unvalidated")
        if "uniform" in res.coverage:
            warnings.append("Uniform and ID-card results come from untrained baseline rules (no recorded evaluation)")

        # ---- persist atomically. Earlier runs of this video are KEPT (history); this run becomes the current one ----
        snap = {m["key"]: m for m in registry.snapshot(settings, evals)}
        old_files: list[str] = []
        try:
            people_by_ref = {}
            for pr in res.people:
                tp = TrackedPerson(video_id=video.id, job_id=job.id, track_ref=pr["track_ref"],
                                   first_seen_s=pr["first_seen_s"], last_seen_s=pr["last_seen_s"],
                                   detections=pr["detections"], shirt_status=pr["shirt_status"],
                                   trouser_status=pr["trouser_status"], uniform_overall=pr["uniform_overall"],
                                   id_status=pr["id_status"], uniform_samples=pr["uniform_samples"],
                                   id_samples=pr["id_samples"], shirt_fraction=pr["shirt_fraction"],
                                   trouser_fraction=pr["trouser_fraction"], uniform_score=pr["uniform_score"],
                                   uniform_method=pr["uniform_method"], uniform_version=pr["uniform_version"],
                                   id_confidence=pr["id_confidence"], id_method=pr["id_method"], id_version=pr["id_version"],
                                   id_association=pr["id_association"])
                db.add(tp)
                for (t_s, bx, cf) in pr["observations"]:
                    db.add(TrackObservation(video_id=video.id, job_id=job.id, track_ref=pr["track_ref"], t_s=t_s,
                                            x1=bx[0], y1=bx[1], x2=bx[2], y2=bx[3], conf=cf))
                people_by_ref[pr["track_ref"]] = (tp, pr)
            db.flush()
            for tp, pr in people_by_ref.values():
                if pr["evidence_frame"]:
                    db.add(Evidence(video_id=video.id, person_id=tp.id, kind="frame",
                                    rel_path=pr["evidence_frame"], timestamp_s=pr["best_t"]))
            seen, dupes = set(), 0
            for e in res.events:
                key = f"{job.id}:{e['category']}:{e['track_ref'] or '-'}:{int(round(e['start_s'] * 10))}"
                if key in seen:
                    dupes += 1
                    continue
                seen.add(key)
                ev = Event(video_id=video.id, job_id=job.id, track_ref=e["track_ref"], category=e["category"],
                           start_s=e["start_s"], end_s=max(e["end_s"], e["start_s"]), confidence=e["confidence"],
                           model_name=e["model_name"], model_version=e["model_version"],
                           automated_status=e["automated_status"], predicted_class=e.get("predicted_class"),
                           dedupe_key=key, summary=e["summary"])
                try:
                    with db.begin_nested():  # savepoint: a duplicate never aborts the whole job
                        db.add(ev)
                        db.flush()
                except IntegrityError:
                    dupes += 1
                    continue
                for evd in e["evidence"]:
                    db.add(Evidence(video_id=video.id, event_id=ev.id, kind=evd["kind"],
                                    rel_path=evd["rel_path"], timestamp_s=evd["timestamp_s"]))
            if dupes:
                warnings.append(f"{dupes} duplicate finding(s) were suppressed")
            # per-module outcome of THIS run (a finished job can still contain modules that never ran)
            key_of = {"person_detection": "person_yolo" if detector.backend == "yolo" else "person_hog", "tracking": "tracker"}
            for mod, c in res.coverage.items():
                m = snap.get(key_of.get(mod, mod), {})
                db.add(JobModule(job_id=job.id, module=mod, requested=c["requested"], ran=c["ran"], state=c["state"],
                                 result=res.module_results.get(mod, C.R_NOT_ASSESSED if not c["ran"] else None),
                                 model_name=m.get("name"), model_version=m.get("version"),
                                 evaluation_state=(m.get("evaluation") or {}).get("state"), detail=(c.get("note") or "")[:400]))
            db.query(AnalysisJob).filter(AnalysisJob.video_id == video.id, AnalysisJob.id != job.id).update({"is_current": False})
            job.is_current = True
            job.status = "completed_partial" if res.partial else "completed"
            job.partial = res.partial
            job.coverage = json.dumps(res.coverage)
            job.progress, job.finished_at, job.processing_seconds = 1.0, utcnow(), res.seconds
            job.model_versions = json.dumps(res.model_versions)
            job.warnings = json.dumps(warnings)
            video.status = job.status
            video.processing_completed_at = job.finished_at
            db.commit()
        except Exception:
            db.rollback()  # nothing from this run is half-saved
            raise
        model_status.persist_registry(db, list(snap.values()))
    finally:
        db.close()
