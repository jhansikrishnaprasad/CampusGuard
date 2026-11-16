from __future__ import annotations
from datetime import date
from typing import Optional
from fastapi import APIRouter, Depends
from fastapi.responses import Response
from sqlalchemy.orm import Session
from .. import config
from ..database import get_db
from ..models import AnalysisJob, Event, Review, User, Video
from ..services.runs import current_run_filter
from ..security import current_user
from ..services import model_status, reporting
from .common import iso, job_dict

router = APIRouter(prefix="/api", tags=["reports"])


@router.get("/dashboard")
def dashboard(user: User = Depends(current_user), db: Session = Depends(get_db)):
    ev = db.query(Event).filter(current_run_filter(Event.job_id))   # current runs only (history stays in the database)
    cats = {}
    for c in config.CATEGORY_LABELS:
        cats[c] = ev.filter(Event.category == c).count()
    recent_reviews = db.query(Review).order_by(Review.id.desc()).limit(8).all()
    models = model_status.snapshot(db)
    return {
        "models": [{"key": m["key"], "title": m["title"], "state": m["state"], "evaluation": m["evaluation"]["state"]} for m in models],
        "model_warnings": model_status.warnings(models),
        "videos_total": db.query(Video).count(),
        "analyses_completed": db.query(AnalysisJob).filter(AnalysisJob.status.in_(["completed", "completed_partial"])).count(),
        "analyses_partial": db.query(AnalysisJob).filter(AnalysisJob.status == "completed_partial").count(),
        "analyses_cancelled": db.query(AnalysisJob).filter(AnalysisJob.status == "cancelled").count(),
        "analyses_failed": db.query(AnalysisJob).filter(AnalysisJob.status == "failed").count(),
        "videos_processing": db.query(Video).filter(Video.status.in_(["queued", "processing"])).count(),
        "pending_review": ev.filter(Event.review_status == "pending_review").count(),
        "confirmed": ev.filter(Event.review_status == "confirmed").count(),
        "dismissed": ev.filter(Event.review_status == "dismissed").count(),
        "inconclusive": ev.filter(Event.review_status == "inconclusive").count(),
        "events_in_history": db.query(Event).count() - ev.count(),
        "by_category": cats, "category_labels": config.CATEGORY_LABELS,
        "recent_jobs": [job_dict(j) for j in db.query(AnalysisJob).order_by(AnalysisJob.id.desc()).limit(6).all()],
        "recent_reviews": [{"event_id": r.event_id, "reviewer": r.reviewer, "decision": r.decision, "at": iso(r.created_at)}
                           for r in recent_reviews],
    }


def _flt(date_from, date_to, video_id, category, review_status, include_history=False, job_id=None):
    return dict(date_from=date_from, date_to=date_to, video_id=video_id, category=category, review_status=review_status,
                include_history=include_history, job_id=job_id)


@router.get("/reports/summary")
def report_summary(date_from: Optional[date] = None, date_to: Optional[date] = None, video_id: Optional[int] = None,
                   category: Optional[str] = None, review_status: Optional[str] = None,
                   include_history: bool = False, job_id: Optional[int] = None,
                   user: User = Depends(current_user), db: Session = Depends(get_db)):
    return reporting.summary(db, **_flt(date_from, date_to, video_id, category, review_status, include_history, job_id))


@router.get("/reports/events.csv")
def report_csv(date_from: Optional[date] = None, date_to: Optional[date] = None, video_id: Optional[int] = None,
               category: Optional[str] = None, review_status: Optional[str] = None,
               include_history: bool = False, job_id: Optional[int] = None,
               user: User = Depends(current_user), db: Session = Depends(get_db)):
    data = reporting.to_csv(db, **_flt(date_from, date_to, video_id, category, review_status, include_history, job_id))
    return Response(data, media_type="text/csv", headers={"Content-Disposition": 'attachment; filename="events.csv"'})


@router.get("/reports/report.pdf")
def report_pdf(date_from: Optional[date] = None, date_to: Optional[date] = None, video_id: Optional[int] = None,
               category: Optional[str] = None, review_status: Optional[str] = None,
               include_history: bool = False, job_id: Optional[int] = None,
               user: User = Depends(current_user), db: Session = Depends(get_db)):
    f = _flt(date_from, date_to, video_id, category, review_status, include_history, job_id)
    desc = {k: (str(v) if v else "") for k, v in f.items()}
    desc["runs"] = "all runs (history)" if include_history else ("run %s" % job_id if job_id else "current run per video")
    data = reporting.to_pdf(db, desc, models=model_status.snapshot(db), evaluations=model_status.evaluations(db), **f)
    return Response(data, media_type="application/pdf", headers={"Content-Disposition": 'attachment; filename="report.pdf"'})


@router.get("/reports/compliance.csv")
def report_compliance_csv(video_id: Optional[int] = None, job_id: Optional[int] = None, include_history: bool = False,
                          user: User = Depends(current_user), db: Session = Depends(get_db)):
    """Person-level uniform / ID-card compliance rows (separate from the event CSV, which is unchanged)."""
    data = reporting.to_people_csv(db, video_id=video_id, job_id=job_id, include_history=include_history)
    return Response(data, media_type="text/csv", headers={"Content-Disposition": 'attachment; filename="compliance_people.csv"'})
