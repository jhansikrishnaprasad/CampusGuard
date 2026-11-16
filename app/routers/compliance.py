"""Video-level compliance summary API (read-only; derived from stored analysis results)."""
from __future__ import annotations
from typing import Optional
from fastapi import APIRouter, Depends, HTTPException, Query
from sqlalchemy.orm import Session
from ..database import get_db
from ..models import AnalysisJob, User, Video
from ..security import current_user
from ..services import compliance_summary as cs
from .. import constants as C

router = APIRouter(prefix="/api", tags=["compliance"])


def _video(db: Session, vid: int) -> Video:
    v = db.get(Video, vid)
    if not v:
        raise HTTPException(404, "Video not found")
    return v


@router.get("/videos/{vid}/compliance-summary")
def compliance_summary(vid: int, job_id: Optional[int] = None, user: User = Depends(current_user), db: Session = Depends(get_db)):
    """Person-level counts for ONE run: the latest successful run by default, or an explicit job_id."""
    v = _video(db, vid)
    try:
        return cs.summarize(db, v, job_id)
    except LookupError:
        raise HTTPException(404, "Analysis job not found for this video")


@router.get("/videos/{vid}/compliance-people")
def compliance_people(vid: int, job_id: Optional[int] = None, filter: str = Query("all"),
                      user: User = Depends(current_user), db: Session = Depends(get_db)):
    """Person-wise rows of the same run as the summary (temporary track references, never identities)."""
    v = _video(db, vid)
    if filter not in cs.FILTERS:
        raise HTTPException(422, "Unknown filter. Use one of: " + ", ".join(sorted(cs.FILTERS)))
    if job_id is not None:
        job = db.get(AnalysisJob, job_id)
        if job is None or job.video_id != vid:
            raise HTTPException(404, "Analysis job not found for this video")
    else:
        job = cs.latest_done_job(db, vid)
    if job is None or job.status not in C.DONE_STATES:
        return {"video_id": vid, "job_id": job.id if job else None, "filter": filter, "items": []}
    return {"video_id": vid, "job_id": job.id, "filter": filter, "items": cs.person_rows(db, v, job, filter)}


@router.get("/compliance/overview")
def compliance_overview(limit: int = Query(8, ge=1, le=30), user: User = Depends(current_user), db: Session = Depends(get_db)):
    """Dashboard block: latest completed analysis, pending reviews, partial analyses, recent alerts."""
    return cs.overview(db, limit)
