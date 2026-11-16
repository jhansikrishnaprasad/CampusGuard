from __future__ import annotations
import hashlib
import secrets
import shutil
import subprocess
from pathlib import Path
import cv2
from fastapi import HTTPException, UploadFile
from .. import config

CHUNK = 1024 * 1024


def _magic_ok(path: Path, ext: str) -> bool:
    with open(path, "rb") as f:
        head = f.read(16)
    if ext in (".mp4", ".mov"):
        return head[4:8] in (b"ftyp", b"moov", b"mdat", b"free", b"wide", b"skip")
    if ext == ".avi":
        return head[:4] == b"RIFF" and head[8:12] == b"AVI "
    return False


async def save_upload(file: UploadFile, max_mb: int) -> tuple[Path, str, int, str]:
    """Stream the upload to disk in chunks (never buffers the whole file in RAM)."""
    name = "".join(ch for ch in Path((file.filename or "").replace("\\", "/")).name if ch.isprintable())[:200]
    ext = Path(name).suffix.lower()
    if ext not in config.ALLOWED_EXTENSIONS:
        raise HTTPException(415, f"Unsupported file type '{ext}'. Allowed: MP4, AVI, MOV")
    config.ensure_dirs()
    stored = f"{secrets.token_hex(12)}{ext}"
    dest = config.VIDEO_DIR / stored
    size, limit = 0, max_mb * 1024 * 1024
    h = hashlib.sha256()
    try:
        with open(dest, "wb") as out:
            while chunk := await file.read(CHUNK):
                size += len(chunk)
                if size > limit:
                    raise HTTPException(413, f"File exceeds the {max_mb} MB limit")
                out.write(chunk)
                h.update(chunk)
    except BaseException:
        dest.unlink(missing_ok=True)
        raise
    if size == 0:
        dest.unlink(missing_ok=True)
        raise HTTPException(400, "Uploaded file is empty")
    return dest, name, size, h.hexdigest()


def probe(path: Path, ext: str, settings: dict) -> dict:
    """Validate content + decoding and extract metadata. Raises HTTPException(422) when invalid."""
    if not _magic_ok(path, ext):
        raise HTTPException(422, "File content does not match its extension (not a valid video container)")
    cap = cv2.VideoCapture(str(path))
    try:
        if not cap.isOpened():
            raise HTTPException(422, "Video could not be opened (unsupported codec or corrupted file)")
        fps = float(cap.get(cv2.CAP_PROP_FPS) or 0)
        frames = float(cap.get(cv2.CAP_PROP_FRAME_COUNT) or 0)
        w, h = int(cap.get(cv2.CAP_PROP_FRAME_WIDTH)), int(cap.get(cv2.CAP_PROP_FRAME_HEIGHT))
        ok, frame = cap.read()
        if not ok or frame is None:
            raise HTTPException(422, "The first frame could not be decoded (corrupted or unsupported codec)")
    finally:
        cap.release()
    if fps <= 0 or fps > 240 or frames <= 0 or w <= 0 or h <= 0:
        raise HTTPException(422, "Invalid video metadata (frame rate, size or frame count missing)")
    dur = frames / fps
    p = settings["processing"]
    if dur < p["min_duration_s"]:
        raise HTTPException(422, f"Video is {dur:.1f}s long; minimum is {p['min_duration_s']}s (configurable)")
    if dur > p["max_duration_s"]:
        raise HTTPException(422, f"Video is {dur / 60:.0f} min long; maximum is {p['max_duration_s'] / 60:.0f} min (configurable)")
    return {"duration_s": dur, "fps": fps, "width": w, "height": h}


def make_preview(src: Path, dest: Path) -> bool:
    """Browser-playable H.264 copy for AVI/MOV (requires ffmpeg on PATH)."""
    ff = shutil.which("ffmpeg")
    if not ff:
        return False
    r = subprocess.run([ff, "-y", "-loglevel", "error", "-i", str(src), "-c:v", "libx264", "-pix_fmt", "yuv420p",
                        "-preset", "veryfast", "-crf", "28", "-an", "-movflags", "+faststart", str(dest)],
                       capture_output=True)
    return r.returncode == 0 and dest.exists()
