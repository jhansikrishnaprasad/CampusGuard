from __future__ import annotations
from datetime import date
from typing import Optional
from fastapi import APIRouter, Depends, HTTPException, Query
from pydantic import BaseModel, Field
from sqlalchemy.orm import Session
from ..database import get_db
from ..models import AuditLog, Event, Review, User, utcnow
from ..security import admin_user, current_user
from ..services.reporting import event_query
from .common import audit, event_dict, iso

router = APIRouter(prefix="/api", tags=["events"])


class ReviewIn(BaseModel):
    decision: str = Field(pattern="^(confirmed|dismissed|inconclusive)$")
    notes: Optional[str] = Field(default=None, max_length=2000)


@router.get("/events")
def list_events(date_from: Optional[date] = None, date_to: Optional[date] = None, video_id: Optional[int] = None,
                category: Optional[str] = None, review_status: Optional[str] = None, q: Optional[str] = None,
                include_history: bool = False, job_id: Optional[int] = None,
                limit: int = Query(50, ge=1, le=200), offset: int = Query(0, ge=0),
                user: User = Depends(current_user), db: Session = Depends(get_db)):
    qry = event_query(db, date_from, date_to, video_id, category, review_status, q, include_history=include_history, job_id=job_id)
    total = qry.count()
    return {"total": total, "items": [event_dict(e) for e in qry.offset(offset).limit(limit).all()]}


@router.get("/events/{eid}")
def get_event(eid: int, user: User = Depends(current_user), db: Session = Depends(get_db)):
    e = db.get(Event, eid)
    if not e:
        raise HTTPException(404, "Event not found")
    return event_dict(e, detail=True)


@router.post("/events/{eid}/review")
def review_event(eid: int, body: ReviewIn, user: User = Depends(current_user), db: Session = Depends(get_db)):
    e = db.get(Event, eid)
    if not e:
        raise HTTPException(404, "Event not found")
    prev = e.review_status
    if e.review_status != "pending_review" and body.decision == e.review_status and (body.notes or None) == (e.review_notes or None):
        raise HTTPException(409, "This decision is already recorded")  # no duplicate audit rows for a no-op resubmission
    # Only review_* columns change: confidence, automated_status, predicted_class, model fields keep the
    # ORIGINAL model output. Every decision is also kept as an immutable row in `reviews`.
    db.add(Review(event_id=eid, reviewer=user.username, decision=body.decision, notes=body.notes,
                  previous_status=prev))
    e.review_status, e.review_notes = body.decision, body.notes
    e.reviewed_at, e.reviewed_by = utcnow(), user.username
    audit(db, user.username, "event_review", f"event {eid}", f"{prev} -> {body.decision}")
    db.commit()
    return event_dict(e, detail=True)


@router.get("/audit")
def audit_log(limit: int = Query(100, le=500), admin: User = Depends(admin_user), db: Session = Depends(get_db)):
    rows = db.query(AuditLog).order_by(AuditLog.id.desc()).limit(limit).all()
    return [{"id": r.id, "user": r.username, "action": r.action, "target": r.target, "detail": r.detail,
             "at": iso(r.created_at)} for r in rows]
