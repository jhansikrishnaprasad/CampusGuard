from __future__ import annotations
import shutil
from pathlib import Path
from typing import Optional
from fastapi import APIRouter, Depends, File, Form, HTTPException, Query, UploadFile
from fastapi.responses import FileResponse
from sqlalchemy.orm import Session
from .. import config
from ..database import get_db
from ..models import AnalysisJob, Event, Evidence, TrackedPerson, User, Video
from ..security import admin_user, current_user, safe_join
from ..services import jobs, video_io
from ..services.runs import current_run_filter
from ..services.settings_service import get_settings
from .common import audit, event_dict, job_dict, person_dict, video_dict

router = APIRouter(prefix="/api", tags=["videos"])
MEDIA = {".mp4": "video/mp4", ".mov": "video/quicktime", ".avi": "video/x-msvideo", ".jpg": "image/jpeg"}


def _video(db: Session, vid: int) -> Video:
    v = db.get(Video, vid)
    if not v:
        raise HTTPException(404, "Video not found")
    return v


@router.post("/videos", status_code=201)
async def upload_video(file: UploadFile = File(...), start_analysis: bool = Form(False),
                       user: User = Depends(current_user), db: Session = Depends(get_db)):
    settings = get_settings(db)
    path, name, size, digest = await video_io.save_upload(file, settings["processing"]["max_file_mb"])
    try:
        meta = video_io.probe(path, path.suffix.lower(), settings)
    except HTTPException:
        path.unlink(missing_ok=True)
        raise
    v = Video(original_filename=name[:255], stored_name=path.name, size_bytes=size, uploaded_by=user.username, sha256=digest, **meta)
    db.add(v)
    audit(db, user.username, "video_uploaded", name[:90])
    db.commit()
    if start_analysis:
        jobs.create_job(db, v)
        db.refresh(v)
    return video_dict(v, db)


@router.get("/videos")
def list_videos(q: Optional[str] = None, status: Optional[str] = None, limit: int = Query(50, le=200),
                offset: int = 0, user: User = Depends(current_user), db: Session = Depends(get_db)):
    qry = db.query(Video)
    if q:
        qry = qry.filter(Video.original_filename.like(f"%{q}%"))
    if status:
        qry = qry.filter(Video.status == status)
    total = qry.count()
    rows = qry.order_by(Video.id.desc()).offset(offset).limit(limit).all()
    return {"total": total, "items": [video_dict(v, db) for v in rows]}


@router.get("/videos/{vid}")
def get_video(vid: int, user: User = Depends(current_user), db: Session = Depends(get_db)):
    v = _video(db, vid)
    d = video_dict(v, db)
    d["jobs"] = [job_dict(j) for j in sorted(v.jobs, key=lambda j: j.id, reverse=True)]
    return d


@router.get("/videos/{vid}/stream")
def stream_video(vid: int, user: User = Depends(current_user), db: Session = Depends(get_db)):
    v = _video(db, vid)
    name = v.preview_name or v.stored_name
    p = safe_join(config.VIDEO_DIR, name)
    if not p.exists():
        raise HTTPException(404, "Video file is no longer available (removed by retention policy?)")
    return FileResponse(p, media_type=MEDIA.get(p.suffix.lower(), "application/octet-stream"))


@router.delete("/videos/{vid}")
def delete_video(vid: int, admin: User = Depends(admin_user), db: Session = Depends(get_db)):
    v = _video(db, vid)
    if db.query(AnalysisJob).filter(AnalysisJob.video_id == vid, AnalysisJob.status.in_(jobs.ACTIVE)).first():
        raise HTTPException(409, "Cancel the running job before deleting the video")
    for n in (v.stored_name, v.preview_name):
        if n:
            safe_join(config.VIDEO_DIR, n).unlink(missing_ok=True)
    shutil.rmtree(config.EVIDENCE_DIR / f"video_{vid}", ignore_errors=True)
    audit(db, admin.username, "video_deleted", v.original_filename[:90])
    db.delete(v)
    db.commit()
    return {"ok": True}


@router.post("/videos/{vid}/analyze", status_code=202)
def analyze_video(vid: int, user: User = Depends(current_user), db: Session = Depends(get_db)):
    v = _video(db, vid)
    if not safe_join(config.VIDEO_DIR, v.stored_name).exists():
        raise HTTPException(410, "Video file no longer exists")
    job = jobs.create_job(db, v)
    audit(db, user.username, "analysis_started", f"video {vid}"); db.commit()
    return job_dict(job)


@router.get("/videos/{vid}/events")
def video_events(vid: int, include_history: bool = False, job_id: Optional[int] = None,
                 user: User = Depends(current_user), db: Session = Depends(get_db)):
    _video(db, vid)
    q = db.query(Event).filter(Event.video_id == vid)
    if job_id:
        q = q.filter(Event.job_id == job_id)
    elif not include_history:
        q = q.filter(current_run_filter(Event.job_id))
    rows = q.order_by(Event.start_s).all()
    return [event_dict(e, detail=True) for e in rows]


@router.get("/people")
def list_people(video_id: Optional[int] = None, uniform: Optional[str] = None, id_status: Optional[str] = None,
                include_history: bool = False, job_id: Optional[int] = None,
                user: User = Depends(current_user), db: Session = Depends(get_db)):
    qry = db.query(TrackedPerson)
    if video_id:
        qry = qry.filter(TrackedPerson.video_id == video_id)
    if job_id:
        qry = qry.filter(TrackedPerson.job_id == job_id)
    elif not include_history:
        qry = qry.filter(current_run_filter(TrackedPerson.job_id))
    if uniform:
        qry = qry.filter(TrackedPerson.uniform_overall == uniform)
    if id_status:
        qry = qry.filter(TrackedPerson.id_status == id_status)
    return [person_dict(p) for p in qry.order_by(TrackedPerson.id.desc()).limit(500).all()]


# ---- jobs ----
@router.get("/jobs")
def list_jobs(limit: int = Query(30, le=200), status: Optional[str] = None,
              user: User = Depends(current_user), db: Session = Depends(get_db)):
    qry = db.query(AnalysisJob)
    if status:
        qry = qry.filter(AnalysisJob.status == status)
    return [job_dict(j) for j in qry.order_by(AnalysisJob.id.desc()).limit(limit).all()]


@router.get("/jobs/{jid}")
def get_job(jid: int, user: User = Depends(current_user), db: Session = Depends(get_db)):
    j = db.get(AnalysisJob, jid)
    if not j:
        raise HTTPException(404, "Job not found")
    return job_dict(j)


@router.post("/jobs/{jid}/cancel")
def cancel(jid: int, user: User = Depends(current_user), db: Session = Depends(get_db)):
    j = db.get(AnalysisJob, jid)
    if not j:
        raise HTTPException(404, "Job not found")
    jobs.cancel_job(db, j)
    audit(db, user.username, "job_cancel_requested", f"job {jid}"); db.commit()
    return job_dict(j)


@router.post("/jobs/{jid}/retry", status_code=202)
def retry(jid: int, user: User = Depends(current_user), db: Session = Depends(get_db)):
    j = db.get(AnalysisJob, jid)
    if not j:
        raise HTTPException(404, "Job not found")
    new = jobs.create_job(db, j.video)
    audit(db, user.username, "job_reprocess", f"video {j.video_id}"); db.commit()
    return job_dict(new)


# ---- evidence ----
@router.get("/evidence/{eid}/file")
def evidence_file(eid: int, user: User = Depends(current_user), db: Session = Depends(get_db)):
    e = db.get(Evidence, eid)
    if not e:
        raise HTTPException(404, "Evidence not found")
    p = safe_join(config.EVIDENCE_DIR, e.rel_path)
    if not p.is_file():
        raise HTTPException(404, "Evidence file missing")
    return FileResponse(p, media_type=MEDIA.get(p.suffix.lower(), "application/octet-stream"))
