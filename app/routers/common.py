from __future__ import annotations
import json
import os
from sqlalchemy.orm import Session
from .. import config
from ..models import AnalysisJob, AuditLog, Evidence, Event, TrackedPerson, Video
from .. import constants as C
from ..services.reporting import fmt_ts
from ..services.runs import current_run_filter


def audit(db: Session, user: str, action: str, target: str = "", detail: str = "") -> None:
    db.add(AuditLog(username=user, action=action, target=target[:96], detail=detail[:1000]))


def iso(d):
    return d.isoformat() + "Z" if d else None


def ev_dict(e: Evidence) -> dict:
    exists = (config.EVIDENCE_DIR / e.rel_path).is_file()
    return {"id": e.id, "kind": e.kind, "timestamp_s": e.timestamp_s, "url": f"/api/evidence/{e.id}/file",
            "file_available": exists}


def video_dict(v: Video, db: Session | None = None) -> dict:
    d = {"id": v.id, "filename": v.original_filename, "size_bytes": v.size_bytes, "duration_s": v.duration_s,
         "fps": round(v.fps, 2), "width": v.width, "height": v.height, "uploaded_at": iso(v.uploaded_at),
         "status": v.status, "error": v.error, "stream_url": f"/api/videos/{v.id}/stream",
         "has_preview": bool(v.preview_name), "sha256": (v.sha256 or "")[:16],
         "processing_started_at": iso(v.processing_started_at), "processing_completed_at": iso(v.processing_completed_at)}
    if db is not None:
        d["event_count"] = db.query(Event).filter(Event.video_id == v.id, current_run_filter(Event.job_id)).count()
        d["duplicate_of"] = [x for (x,) in db.query(Video.id).filter(Video.sha256 == v.sha256, Video.id != v.id).all()] if v.sha256 else []
        j = db.query(AnalysisJob).filter(AnalysisJob.video_id == v.id).order_by(AnalysisJob.id.desc()).first()
        d["latest_job"] = job_dict(j) if j else None
    return d


def job_dict(j: AnalysisJob) -> dict:
    return {"id": j.id, "video_id": j.video_id, "status": j.status, "progress": round(j.progress or 0, 4),
            "created_at": iso(j.created_at), "started_at": iso(j.started_at), "finished_at": iso(j.finished_at),
            "processing_seconds": j.processing_seconds, "error": j.error,
            "warnings": json.loads(j.warnings) if j.warnings else [], "partial": bool(j.partial), "attempt": j.attempt, "is_current": bool(j.is_current),
            "modules": [{"module": m.module, "requested": m.requested, "ran": m.ran, "state": m.state, "result": m.result,
                         "model": m.model_name, "version": m.model_version, "evaluation": m.evaluation_state, "detail": m.detail}
                        for m in sorted(j.modules, key=lambda m: m.id)],
            "coverage": json.loads(j.coverage) if j.coverage else None,
            "model_versions": json.loads(j.model_versions) if j.model_versions else None,
            "video_name": j.video.original_filename if j.video else None}


def event_dict(e: Event, detail: bool = False) -> dict:
    d = {"id": e.id, "video_id": e.video_id, "video": e.video.original_filename, "track_ref": e.track_ref,
         "category": e.category, "category_label": config.CATEGORY_LABELS.get(e.category, e.category),
         "start_s": e.start_s, "end_s": e.end_s, "start": fmt_ts(e.start_s), "end": fmt_ts(e.end_s),
         "confidence": e.confidence, "model": f"{e.model_name} {e.model_version}",
         "automated_status": e.automated_status, "review_status": e.review_status,
         "review_notes": e.review_notes, "summary": e.summary, "created_at": iso(e.created_at),
         "predicted_class": e.predicted_class, "job_id": e.job_id, "reviewed_at": iso(e.reviewed_at), "reviewed_by": e.reviewed_by,
         "evidence_available": any((config.EVIDENCE_DIR / x.rel_path).is_file() for x in e.evidence)}
    if detail:
        d["evidence"] = [ev_dict(x) for x in e.evidence]
        d["reviews"] = [{"reviewer": r.reviewer, "decision": r.decision, "notes": r.notes, "at": iso(r.created_at)}
                        for r in sorted(e.reviews, key=lambda r: r.id, reverse=True)]
    return d


def person_dict(p: TrackedPerson) -> dict:
    return {"id": p.id, "video_id": p.video_id, "video": p.video.original_filename if p.video else None,
            "track_ref": p.track_ref, "first_seen_s": p.first_seen_s, "last_seen_s": p.last_seen_s,
            "first_seen": fmt_ts(p.first_seen_s), "last_seen": fmt_ts(p.last_seen_s), "detections": p.detections,
            "shirt_status": p.shirt_status, "trouser_status": p.trouser_status, "uniform_overall": p.uniform_overall, "uniform_simple": C.UNIFORM_SIMPLE.get(p.uniform_overall, p.uniform_overall),
            "uniform_score": p.uniform_score, "uniform_method": p.uniform_method, "uniform_version": p.uniform_version,
            "id_confidence": p.id_confidence, "id_method": p.id_method, "id_version": p.id_version,
            "id_association": p.id_association, "job_id": p.job_id,
            "id_status": p.id_status, "uniform_samples": p.uniform_samples, "shirt_fraction": p.shirt_fraction,
            "trouser_fraction": p.trouser_fraction, "membership_status": p.membership_status,
            "evidence": [ev_dict(x) for x in p.evidence]}
