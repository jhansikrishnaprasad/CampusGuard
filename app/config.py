"""Central configuration. Paths come from env vars / .env, never hardcoded."""
from __future__ import annotations
import copy
import os
from pathlib import Path

RESOURCE_DIR = Path(__file__).resolve().parent.parent          # where the code/static files live (read-only when packaged)
# BASE_DIR = writable working root (data/, models/, reference_images/, .env). Normally the project folder; the Windows
# launcher sets CAMPUS_HOME to %LOCALAPPDATA%\CampusGuard so nothing is ever written into the temporary bundle folder.
BASE_DIR = Path(os.getenv("CAMPUS_HOME") or RESOURCE_DIR).resolve()


def _load_dotenv() -> None:
    f = BASE_DIR / ".env"
    if not f.exists():
        return
    for line in f.read_text(encoding="utf-8").splitlines():
        line = line.strip()
        if not line or line.startswith("#") or "=" not in line:
            continue
        k, v = line.split("=", 1)
        os.environ.setdefault(k.strip(), v.strip().strip('"').strip("'"))


_load_dotenv()


def _path(env: str, default: Path) -> Path:
    p = Path(os.getenv(env, str(default)))
    return p if p.is_absolute() else (BASE_DIR / p)


DATA_DIR = _path("CAMPUS_DATA_DIR", BASE_DIR / "data")
VIDEO_DIR = DATA_DIR / "videos"
EVIDENCE_DIR = DATA_DIR / "evidence"
BACKUP_DIR = DATA_DIR / "backups"
MODELS_DIR = _path("CAMPUS_MODELS_DIR", BASE_DIR / "models")
REFERENCE_DIR = _path("CAMPUS_REFERENCE_DIR", BASE_DIR / "reference_images")
DB_PATH = DATA_DIR / "campus_safety.db"
DATABASE_URL = os.getenv("CAMPUS_DATABASE_URL", f"sqlite:///{DB_PATH.as_posix()}")
STATIC_DIR = Path(__file__).resolve().parent / "static"

ADMIN_USERNAME = os.getenv("ADMIN_USERNAME", "admin")
ADMIN_PASSWORD = os.getenv("ADMIN_PASSWORD", "")  # empty -> random one printed on first start
SESSION_HOURS = int(os.getenv("SESSION_HOURS", "8"))
COOKIE_SECURE = os.getenv("COOKIE_SECURE", "false").lower() == "true"
# Local single-user mode: when false (default) there is no sign-in screen and every request runs as the admin user.
# Set CAMPUS_REQUIRE_LOGIN=true in .env to restore username/password login (do this before exposing the app to any network).
REQUIRE_LOGIN = os.getenv("CAMPUS_REQUIRE_LOGIN", "false").lower() == "true"
# Set only by the local Windows launcher: lets the signed-in local admin stop the server from the UI (loopback requests only).
ALLOW_SHUTDOWN = os.getenv("CAMPUS_ALLOW_SHUTDOWN", "false").lower() == "true"
ALLOWED_EXTENSIONS = {".mp4", ".avi", ".mov"}

CATEGORY_FIGHT = "possible_physical_fighting"
CATEGORY_SMOKING = "possible_smoking"
CATEGORY_UNIFORM = "uniform_possible_violation"
CATEGORY_LABELS = {
    CATEGORY_FIGHT: "Possible physical fighting",
    CATEGORY_SMOKING: "Possible smoking",
    CATEGORY_UNIFORM: "Possible uniform non-compliance",
}

# Defaults for every configurable value. Stored overrides live in the `settings` table.
# Uniform ranges are OpenCV HSV (H 0-179, S/V 0-255). Defaults were sampled from the
# college group photograph (cream/beige shirts: H~6-25, S~10-45, V~200-240; navy
# trousers: H~110-125, S~45-150, V~55-160) and widened to allow lighting variation.
DEFAULT_SETTINGS: dict = {
    "uniform": {
        "beige": {"h_min": 5, "h_max": 35, "s_min": 8, "s_max": 95, "v_min": 140, "v_max": 255},
        "navy": {"h_min": 100, "h_max": 130, "s_min": 40, "s_max": 255, "v_min": 20, "v_max": 200},
        "ok_fraction": 0.25,
        "bad_fraction": 0.08,
        "min_person_height_px": 140,
        "min_region_mean_v": 45,
        "sample_interval_s": 2.0,
        "max_samples_per_track": 20,
        "min_samples_for_verdict": 3,
        "majority": 0.6,
        "create_review_events": True,
        "shirt_classifier_path": "models/uniform_shirt_clf.json",     # optional trained model (see docs/TRAINING.md)
        "trouser_classifier_path": "models/uniform_trouser_clf.json",
        "clf_ok": 0.8, "clf_bad": 0.2,
        "observation_interval_s": 1.0,
    },
    "idcard": {
        "enabled": True,
        "min_person_height_px": 160,
        "min_samples": 3,
        "custom_model_path": "",
        "custom_conf": 0.5,
    },
    "person": {
        "backend": "auto",  # auto | yolo | hog
        "weights_path": "models/yolov8n.pt",
        "conf": 0.35,
        "tracker": "auto",  # auto | bytetrack | iou
        "max_age_s": 2.0,
        "iou_match": 0.3,
        "min_hits": 2,
        "process_width": 960,
    },
    "processing": {
        "person_fps": 2.0,
        "activity_fps": 4.0,
        "clip_padding_s": 2.0,
        "max_clip_s": 20.0,
        "max_file_mb": 4096,
        "min_duration_s": 5,
        "max_duration_s": 5400,
        "max_evidence_frames_per_event": 3,
    },
    "activity": {
        "fight": {
            "enabled": True, "model_path": "models/fight_model.pt",
            "threshold": 0.70, "uncertain_low": 0.50, "min_duration_s": 2.0,
            "merge_gap_s": 3.0, "min_hits": 2, "window_s": 4.0, "stride_s": 2.0,
        },
        "smoking": {
            "enabled": True, "model_path": "models/smoking_model.pt",
            "threshold": 0.75, "uncertain_low": 0.55, "min_duration_s": 3.0,
            "merge_gap_s": 4.0, "min_hits": 2, "window_s": 4.0, "stride_s": 2.0,
        },
    },
    "retention": {"video_days": 90, "evidence_days": 180, "auto_cleanup": False},
}


def deep_merge(base: dict, over: dict) -> dict:
    out = copy.deepcopy(base)
    for k, v in over.items():
        if isinstance(v, dict) and isinstance(out.get(k), dict):
            out[k] = deep_merge(out[k], v)
        else:
            out[k] = v
    return out


def resolve_path(p: str) -> Path:
    """Relative paths are resolved against the project root."""
    pp = Path(p)
    return pp if pp.is_absolute() else BASE_DIR / pp


def ensure_dirs() -> None:
    for d in (DATA_DIR, VIDEO_DIR, EVIDENCE_DIR, BACKUP_DIR, MODELS_DIR, REFERENCE_DIR):
        d.mkdir(parents=True, exist_ok=True)
