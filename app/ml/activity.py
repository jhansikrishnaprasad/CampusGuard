"""Adapter for video action-recognition models (fighting / smoking).

NO model ships with this project. A capability is only usable when ALL of these hold:
  1. a TorchScript file exists at the configured path (default models/fight_model.pt, models/smoking_model.pt)
  2. PyTorch is installed
  3. a sidecar JSON with the same stem is valid, e.g. models/fight_model.json:
       {"name": "r3d18-rwf2000", "version": "2026-01", "classes": ["non_violent", "violent"],
        "positive_class": "violent", "clip_len": 16, "size": 112, "layout": "BCTHW",
        "mean": [0.43, 0.40, 0.38], "std": [0.23, 0.22, 0.22]}
  4. a dry-run forward pass on a dummy clip succeeds and the output size equals len(classes)
Otherwise the state is one of FILE_MISSING / DEPENDENCY_MISSING / NOT_CONFIGURED / LOAD_FAILED and NO
predictions are produced (never random or placeholder output).
"""
from __future__ import annotations
import hashlib
import json
import logging
import numpy as np
import cv2
from .. import config
from .. import constants as C

log = logging.getLogger(__name__)


def validate_sidecar(meta) -> str | None:
    """Return an error string, or None when the metadata is usable."""
    if not isinstance(meta, dict):
        return "sidecar JSON must be an object"
    cls = meta.get("classes")
    if not (isinstance(cls, list) and len(cls) >= 2 and all(isinstance(c, str) for c in cls)):
        return "'classes' must be a list of at least 2 class names"
    if meta.get("positive_class") not in cls:
        return "'positive_class' must be one of 'classes'"
    if not (isinstance(meta.get("clip_len"), int) and 2 <= meta["clip_len"] <= 128):
        return "'clip_len' must be an integer between 2 and 128"
    if not (isinstance(meta.get("size"), int) and 32 <= meta["size"] <= 512):
        return "'size' must be an integer between 32 and 512"
    if meta.get("layout", "BCTHW") not in ("BCTHW", "BTCHW"):
        return "'layout' must be BCTHW or BTCHW"
    for k in ("mean", "std"):
        if k in meta and not (isinstance(meta[k], list) and len(meta[k]) == 3 and all(isinstance(x, (int, float)) for x in meta[k])):
            return f"'{k}' must be 3 numbers"
    if "std" in meta and any(x <= 0 for x in meta["std"]):
        return "'std' values must be > 0"
    return None


class ActivityRecognizer:
    def __init__(self, key: str, category: str, cfg: dict):
        self.key, self.category, self.cfg = key, category, cfg
        self.model = None
        self.meta: dict = {}
        self.status = C.M_NOT_CONFIGURED
        self.detail = ""
        self.device = "cpu"
        self.sha = None
        if not cfg.get("enabled", True):
            self.status, self.detail = C.M_DISABLED, "Disabled in settings"
            return
        if not cfg.get("model_path"):
            self.detail = "No model path configured"
            return
        path = config.resolve_path(cfg["model_path"])
        side = path.with_suffix(".json")
        if not path.is_file():
            self.status, self.detail = C.M_FILE_MISSING, f"Model file not found: {path.name} (see models/README.md)"
            return
        try:
            import torch
        except Exception as e:
            self.status, self.detail = C.M_DEP_MISSING, f"PyTorch not installed ({type(e).__name__}): pip install -r requirements-ml.txt"
            return
        if not side.is_file():
            self.detail = f"Sidecar metadata {side.name} missing (classes, clip_len, size, ...): model is not configured"
            return
        try:
            self.meta = json.loads(side.read_text(encoding="utf-8"))
        except Exception as e:
            self.status, self.detail = C.M_LOAD_FAILED, f"Sidecar JSON unreadable: {e}"
            return
        err = validate_sidecar(self.meta)
        if err:
            self.status, self.detail = C.M_LOAD_FAILED, f"Invalid sidecar: {err}"
            return
        try:
            self.device = "cuda" if torch.cuda.is_available() else "cpu"
            self.model = torch.jit.load(str(path), map_location=self.device).eval()
            self._dry_run(torch)
            self.sha = hashlib.sha256(path.read_bytes()).hexdigest()[:12]
            self.status, self.detail = C.M_LOADED, f"Loaded on {self.device}; dry-run forward pass OK"
        except Exception as e:
            self.model = None
            self.status, self.detail = C.M_LOAD_FAILED, f"{type(e).__name__}: {e}"[:300]

    def _dry_run(self, torch) -> None:
        t, s = self.clip_len, self.size
        shape = (1, 3, t, s, s) if self.meta.get("layout", "BCTHW") == "BCTHW" else (1, t, 3, s, s)
        with torch.no_grad():
            out = self.model(torch.zeros(*shape, device=self.device))
        n = int(out.numel())
        if n != len(self.meta["classes"]):
            raise ValueError(f"model outputs {n} values but sidecar lists {len(self.meta['classes'])} classes")
        if not bool(torch.isfinite(out).all()):
            raise ValueError("model produced non-finite output on dummy input")

    @property
    def ready(self) -> bool:
        return self.status == C.M_LOADED

    @property
    def name(self) -> str:
        return self.meta.get("name", self.key)

    @property
    def version(self) -> str:
        v = str(self.meta.get("version", "unknown"))
        return f"{v}+{self.sha}" if self.sha else v

    @property
    def clip_len(self) -> int:
        return int(self.meta.get("clip_len", 16))

    @property
    def size(self) -> int:
        return int(self.meta.get("size", 112))

    def describe(self) -> dict:
        return {"capability": self.key, "status": self.status, "detail": self.detail,
                "model": self.name if self.ready else None, "version": self.version if self.ready else None,
                "device": self.device if self.ready else None, "category": self.category,
                "classes": self.meta.get("classes") if self.ready else None}

    def prepare(self, frame_bgr) -> np.ndarray:
        s = self.size
        return cv2.resize(frame_bgr, (s, s), interpolation=cv2.INTER_AREA)

    def predict(self, frames: list[np.ndarray]) -> float:
        """frames: already-resized BGR frames (len == clip_len). Returns P(positive_class)."""
        import torch
        arr = np.stack([cv2.cvtColor(f, cv2.COLOR_BGR2RGB) for f in frames]).astype(np.float32) / 255.0
        mean = np.array(self.meta.get("mean", [0.5] * 3), np.float32)
        std = np.array(self.meta.get("std", [0.5] * 3), np.float32)
        arr = (arr - mean) / std  # T,H,W,C
        if self.meta.get("layout", "BCTHW") == "BCTHW":
            x = torch.from_numpy(arr).permute(3, 0, 1, 2).unsqueeze(0)
        else:
            x = torch.from_numpy(arr).permute(0, 3, 1, 2).unsqueeze(0)
        with torch.no_grad():
            probs = torch.softmax(self.model(x.to(self.device)).float(), dim=-1).cpu().numpy().reshape(-1)
        return float(probs[self.meta["classes"].index(self.meta["positive_class"])])
