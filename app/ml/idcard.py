"""ID-card / lanyard visibility.

Default: a LOW-CONFIDENCE geometric heuristic (card-like bright rectangle on the chest).
Best: a custom-trained YOLO detector (classes containing 'id' / 'card' / 'lanyard') set via
settings.idcard.custom_model_path. Two reference photos are NOT enough to train one - see
docs/ML_METHODOLOGY.md.

Heuristic misses are reported as 'uncertain'; 'not_detected' only comes from a custom model.
Statuses: detected | not_detected | uncertain | not_configured.
`not_detected` means "no card seen by this detector" - it is NEVER proof that no card exists.
Nothing here reads names/numbers or verifies identity.
"""
from __future__ import annotations
from typing import Optional
import cv2
import numpy as np
from .. import config
from .. import constants as C

LABELS = {
    C.ID_VISIBLE: "ID card visible",
    C.ID_NOT_DETECTED: "Card not detected (NOT proof that no card is worn)",
    C.ID_UNCERTAIN: "Uncertain", C.ID_NOT_ASSESSED: "Not assessed",
}


class IdCardDetector:
    def __init__(self, cfg: dict):
        self.cfg = cfg
        self.enabled = bool(cfg.get("enabled", True))
        self.model = None
        self.method = "heuristic" if self.enabled else "disabled"
        self.note = "Geometric heuristic (low confidence). Train a custom detector for reliable results."
        p = cfg.get("custom_model_path") or ""
        if self.enabled and p:
            path = config.resolve_path(p)
            try:
                from ultralytics import YOLO
                if path.exists():
                    self.model = YOLO(str(path)); self.method = "custom_yolo"
                    self.note = f"Custom model {path.name}"
                else:
                    self.note = f"Custom model {path.name} not found; using heuristic"
            except Exception as e:
                self.note = f"Custom model unavailable ({type(e).__name__}); using heuristic"

    def describe(self) -> dict:
        return {"enabled": self.enabled, "method": self.method, "note": self.note}

    def detect(self, frame, box) -> dict:
        if not self.enabled:
            return {"status": "not_configured", "conf": None}
        h = box[3] - box[1]
        if h < self.cfg["min_person_height_px"]:
            return {"status": "uncertain", "conf": None, "reason": "person too small"}
        x1, y1, x2, y2 = [int(v) for v in box]
        w = x2 - x1
        crop = frame[max(0, y1 + int(0.15 * h)):max(0, y1 + int(0.75 * h)),
                     max(0, x1 + int(0.2 * w)):max(0, x1 + int(0.8 * w))]
        if crop.size == 0:
            return {"status": "uncertain", "conf": None}
        if self.model is not None:
            r = self.model.predict(crop, conf=self.cfg.get("custom_conf", 0.5), verbose=False)[0]
            names = {i: str(n).lower() for i, n in r.names.items()}
            hits = [float(c) for c, k in zip(r.boxes.conf.cpu().numpy(), r.boxes.cls.cpu().numpy())
                    if any(s in names[int(k)] for s in ("id", "card", "lanyard"))]
            return {"status": "detected", "conf": max(hits)} if hits else {"status": "not_detected", "conf": None}
        return self._heuristic(crop, h)

    @staticmethod
    def _heuristic(crop, person_h) -> dict:
        g = cv2.GaussianBlur(cv2.cvtColor(crop, cv2.COLOR_BGR2GRAY), (3, 3), 0)
        edges = cv2.dilate(cv2.Canny(g, 60, 150), np.ones((3, 3), np.uint8))
        cnts, _ = cv2.findContours(edges, cv2.RETR_LIST, cv2.CHAIN_APPROX_SIMPLE)
        hsv = cv2.cvtColor(crop, cv2.COLOR_BGR2HSV)
        lo_a, hi_a = 0.0012 * person_h ** 2, 0.04 * person_h ** 2
        best = 0.0
        for c in cnts:
            (cx, cy), (rw, rh), _ = cv2.minAreaRect(c)
            if rw < 4 or rh < 4:
                continue
            short, long_ = min(rw, rh), max(rw, rh)
            ratio = short / long_
            area = rw * rh
            if not (0.45 <= ratio <= 0.85 and lo_a <= area <= hi_a):
                continue
            x, y, w, h = cv2.boundingRect(c)
            patch = hsv[y:y + h, x:x + w]
            if patch.size == 0:
                continue
            bright_low_sat = float(np.mean((patch[..., 1] < 50) & (patch[..., 2] > 170)))
            fill = cv2.contourArea(c) / max(area, 1)
            score = bright_low_sat * 0.6 + min(fill, 1) * 0.2 + ratio * 0.2
            best = max(best, score)
        if best >= 0.62:
            return {"status": "detected", "conf": round(min(0.6, best * 0.6), 2)}  # capped: heuristic
        # The heuristic is unreliable (measured 0/4 recall on the reference photo), so a miss is
        # reported as UNCERTAIN, never as "not detected".
        return {"status": "uncertain", "conf": None, "reason": "heuristic found no card (low reliability)"}


def aggregate(samples: list[str], min_samples: int) -> str:
    """Per-frame detector outputs (detected/not_detected/uncertain/not_configured) -> one status.
    CARD_NOT_DETECTED requires enough conclusive observations AND no sighting; it is never
    proof of absence (hidden, turned, small or blurred cards are common)."""
    if not samples or all(x == "not_configured" for x in samples):
        return C.ID_NOT_ASSESSED
    concl = [x for x in samples if x in ("detected", "not_detected")]
    if "detected" in concl and concl.count("detected") >= max(1, int(0.1 * len(concl))):
        return C.ID_VISIBLE
    if len(concl) >= min_samples:
        return C.ID_NOT_DETECTED
    return C.ID_UNCERTAIN
