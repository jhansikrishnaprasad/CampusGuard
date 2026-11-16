from __future__ import annotations
import importlib.util
import platform
import shutil
import sqlite3
import sys
from datetime import timedelta
from functools import lru_cache
from pathlib import Path
from typing import Optional
import cv2
import numpy as np
from fastapi import APIRouter, Body, Depends, File, HTTPException, Request, UploadFile
from sqlalchemy.orm import Session
from .. import __version__, config
from ..database import get_db
from ..models import Event, Evidence, User, Video, utcnow
from ..security import admin_user, current_user, safe_join
from .. import migrations
from ..services import backup as backup_svc, model_status, settings_service
from ..services.membership import get_verifier
from ..services.errors import sanitize_error
from .common import audit

router = APIRouter(prefix="/api", tags=["system"])

shutdown_hook = None   # assigned by launcher.py (stops uvicorn cleanly); None when running normally


@router.post("/system/shutdown")
def shutdown(request: Request, admin: User = Depends(admin_user), db: Session = Depends(get_db)):
    """Stop the local server (Windows launcher only). Disabled unless CAMPUS_ALLOW_SHUTDOWN=true and the caller is on this computer."""
    host = request.client.host if request.client else ""
    if not (config.ALLOW_SHUTDOWN and shutdown_hook and host in ("127.0.0.1", "::1", "localhost")):
        raise HTTPException(403, "Shutdown from the web interface is not enabled")
    audit(db, admin.username, "server_shutdown"); db.commit()
    import threading
    threading.Timer(0.5, shutdown_hook).start()      # let this response reach the browser first
    return {"ok": True, "message": "CampusGuard is shutting down"}


@router.get("/settings")
def read_settings(user: User = Depends(current_user), db: Session = Depends(get_db)):
    return settings_service.get_settings(db)


@router.put("/settings")
def write_settings(patch: dict = Body(...), admin: User = Depends(admin_user), db: Session = Depends(get_db)):
    try:
        out = settings_service.update_settings(db, patch)
    except ValueError as e:
        raise HTTPException(422, str(e))
    audit(db, admin.username, "settings_updated", "", ",".join(patch.keys())); db.commit()
    return out


def _dir_size(p: Path) -> int:
    return sum(f.stat().st_size for f in p.rglob("*") if f.is_file()) if p.exists() else 0


@lru_cache(maxsize=1)
def _torch_info() -> dict:
    if importlib.util.find_spec("torch") is None:
        return {"installed": False, "version": None, "cuda": False}
    import torch
    return {"installed": True, "version": torch.__version__, "cuda": bool(torch.cuda.is_available()),
            "device_name": torch.cuda.get_device_name(0) if torch.cuda.is_available() else "CPU"}


@router.get("/system/db")
def db_info(admin: User = Depends(admin_user)):
    """Which physical SQLite file is in use, its schema version and row counts (read-only check)."""
    import sqlite3
    p = config.DB_PATH
    out = {"path": str(p), "exists": p.exists(), "size_mb": round(p.stat().st_size / 1e6, 3) if p.exists() else 0,
           "schema_version": migrations.get_version(p), "tables": {}, "other_database_files": []}
    if p.exists():
        con = sqlite3.connect(f"file:{p.as_posix()}?mode=ro", uri=True)
        try:
            for (t,) in con.execute("SELECT name FROM sqlite_master WHERE type='table' ORDER BY name"):
                out["tables"][t] = con.execute(f'SELECT COUNT(*) FROM "{t}"').fetchone()[0]
            out["foreign_key_violations"] = len(con.execute("PRAGMA foreign_key_check").fetchall())
        finally:
            con.close()
    # a second, accidental database (e.g. created by starting the app from another folder) would show up here
    for root in {config.BASE_DIR, config.BASE_DIR / "app", Path.cwd()}:
        for f in root.glob("*.db"):
            if f.resolve() != p.resolve():
                out["other_database_files"].append(str(f))
    return out


@router.get("/system/models")
def models(user: User = Depends(current_user), db: Session = Depends(get_db)):
    m = model_status.snapshot(db)
    return {"models": m, "warnings": model_status.warnings(m)}


@router.get("/system/status")
def status(user: User = Depends(current_user), db: Session = Depends(get_db)):
    torch = _torch_info()
    m = model_status.snapshot(db)
    refs = sorted(p.name for p in config.REFERENCE_DIR.glob("*") if p.suffix.lower() in (".jpg", ".jpeg", ".png")) if config.REFERENCE_DIR.exists() else []
    ver = get_verifier()
    return {
        "app_version": __version__, "schema_version": migrations.get_version(config.DB_PATH),
        "python": sys.version.split()[0], "platform": platform.platform(), "opencv": cv2.__version__, "numpy": np.__version__,
        "ffmpeg": shutil.which("ffmpeg") is not None, "torch": torch,
        "ultralytics_installed": importlib.util.find_spec("ultralytics") is not None,
        "models": m, "model_warnings": model_status.warnings(m),
        "uniform_module": {"method": "HSV colour-range baseline", "status": "ready", "reference_images": refs},
        "membership_verification": {"configured": ver.configured, "provider": ver.name, "displayed_as": "Membership unverified"},
        "storage": {"videos_mb": round(_dir_size(config.VIDEO_DIR) / 1e6, 1), "evidence_mb": round(_dir_size(config.EVIDENCE_DIR) / 1e6, 1),
                    "backups_mb": round(_dir_size(config.BACKUP_DIR) / 1e6, 1),
                    "disk_free_gb": round(shutil.disk_usage(config.DATA_DIR).free / 1e9, 1), "database": config.DB_PATH.name},
        "backup_instructions": "Create/validate backups here. To RESTORE (server stopped): python scripts/restore_db.py <backup file>",
    }


@router.get("/system/evaluations")
def evaluations(user: User = Depends(current_user), db: Session = Depends(get_db)):
    return model_status.evaluations(db)


@router.post("/system/backup")
def backup(admin: User = Depends(admin_user), db: Session = Depends(get_db)):
    try:
        dest = backup_svc.create_backup(config.DB_PATH, config.BACKUP_DIR)
    except Exception as e:
        raise HTTPException(500, "Backup failed: " + sanitize_error(e))
    audit(db, admin.username, "db_backup", dest.name); db.commit()
    return {"file": dest.name}


@router.get("/system/backups")
def backups(admin: User = Depends(admin_user)):
    return sorted(p.name for p in config.BACKUP_DIR.glob("*.db"))[::-1]


@router.post("/system/backups/validate")
def validate_backup(name: str = Body(..., embed=True), admin: User = Depends(admin_user)):
    """Check a backup (integrity, foreign keys, tables, schema version) WITHOUT restoring it."""
    return backup_svc.validate_backup(safe_join(config.BACKUP_DIR, name))


@router.post("/system/retention/run")
def retention(admin: User = Depends(admin_user), db: Session = Depends(get_db)):
    return run_retention(db, admin.username)


def run_retention(db: Session, who: str = "system") -> dict:
    """Explicit cleanup only (never runs unless called / auto_cleanup=true). Footage and evidence that
    belong to findings still PENDING REVIEW are always kept."""
    s = settings_service.get_settings(db)["retention"]
    now = utcnow()
    pending_videos = {e.video_id for e in db.query(Event.video_id).filter(Event.review_status == "pending_review")}
    n_vid = n_ev = 0
    for v in db.query(Video).filter(Video.uploaded_at < now - timedelta(days=s["video_days"])).all():
        if v.id in pending_videos:
            continue
        removed = False
        for n in (v.stored_name, v.preview_name):
            if n:
                p = safe_join(config.VIDEO_DIR, n)
                if p.exists():
                    p.unlink(); removed = True
        n_vid += removed
    for e in db.query(Evidence).filter(Evidence.created_at < now - timedelta(days=s["evidence_days"])).all():
        if e.event is not None and e.event.review_status == "pending_review":
            continue
        safe_join(config.EVIDENCE_DIR, e.rel_path).unlink(missing_ok=True)
        db.delete(e); n_ev += 1
    audit(db, who, "retention_run", "", f"videos={n_vid} evidence={n_ev}"); db.commit()
    return {"videos_files_removed": n_vid, "evidence_removed": n_ev}


@router.get("/reference-images")
def list_refs(user: User = Depends(current_user)):
    return sorted(p.name for p in config.REFERENCE_DIR.glob("*") if p.suffix.lower() in (".jpg", ".jpeg", ".png"))


@router.post("/reference-images", status_code=201)
async def add_ref(file: UploadFile = File(...), admin: User = Depends(admin_user), db: Session = Depends(get_db)):
    ext = Path(file.filename or "").suffix.lower()
    if ext not in (".jpg", ".jpeg", ".png"):
        raise HTTPException(415, "Only JPG/PNG reference images are accepted")
    data = await file.read(10 * 1024 * 1024 + 1)
    if len(data) > 10 * 1024 * 1024:
        raise HTTPException(413, "Image larger than 10 MB")
    if cv2.imdecode(np.frombuffer(data, np.uint8), cv2.IMREAD_COLOR) is None:
        raise HTTPException(422, "File is not a valid image")
    config.ensure_dirs()
    name = f"ref_{utcnow().strftime('%Y%m%d_%H%M%S')}{ext}"
    (config.REFERENCE_DIR / name).write_bytes(data)
    audit(db, admin.username, "reference_added", name); db.commit()
    return {"file": name}
