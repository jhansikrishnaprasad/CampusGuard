"""Person detection + tracking.

Backends
  yolo : Ultralytics YOLO (needs `pip install ultralytics` + weights file). Tracking via
         ByteTrack (Ultralytics built-in) when settings.person.tracker is auto/bytetrack.
  hog  : OpenCV's built-in HOG+SVM pedestrian detector. Needs NO download, so the app works
         out of the box, but it is much less accurate than YOLO (misses small / seated /
         partially visible people). Tracking uses the simple IoU tracker below.
Track IDs are TEMPORARY references, never verified identities.
"""
from __future__ import annotations
import logging
from dataclasses import dataclass
from typing import Optional
import cv2
import numpy as np
from .. import config

log = logging.getLogger(__name__)


@dataclass
class Det:
    track_id: int
    box: tuple  # x1, y1, x2, y2 in ORIGINAL frame pixels
    conf: float


def iou(a, b) -> float:
    ix1, iy1, ix2, iy2 = max(a[0], b[0]), max(a[1], b[1]), min(a[2], b[2]), min(a[3], b[3])
    inter = max(0, ix2 - ix1) * max(0, iy2 - iy1)
    ua = (a[2] - a[0]) * (a[3] - a[1]) + (b[2] - b[0]) * (b[3] - b[1]) - inter
    return inter / ua if ua > 0 else 0.0


class SimpleTracker:
    """Greedy tracker (NOT ByteTrack) with constant-velocity prediction.

    Each track's box is moved by its estimated velocity before matching, so people who move a lot between
    sampled frames (2 fps) or disappear for a short gap keep their id. Matching is by IoU first, then by
    centre distance with a size-consistency check. It has no appearance model: crossing paths and long
    occlusions still fragment tracks (documented limitation)."""

    def __init__(self, iou_match: float = 0.3, max_age_s: float = 2.0, min_hits: int = 2):
        self.iou_match, self.max_age, self.min_hits = iou_match, max_age_s, min_hits
        self.tracks: dict[int, dict] = {}
        self.next_id = 1

    @staticmethod
    def _centre(b):
        return ((b[0] + b[2]) / 2, (b[1] + b[3]) / 2)

    def _predict(self, tr, t):
        dt = min(max(t - tr["last_t"], 0.0), 3.0)
        vx, vy = tr["vel"]
        return (tr["box"][0] + vx * dt, tr["box"][1] + vy * dt, tr["box"][2] + vx * dt, tr["box"][3] + vy * dt)

    def update(self, dets: list[tuple], t: float) -> list[Det]:
        pairs = []
        for tid, tr in self.tracks.items():
            pred = self._predict(tr, t)
            h_t = tr["box"][3] - tr["box"][1]
            for di, d in enumerate(dets):
                v = max(iou(pred, d[:4]), iou(tr["box"], d[:4]))
                if v >= self.iou_match:
                    pairs.append((1.0 + v, tid, di))
                    continue
                h_d = d[3] - d[1]
                ratio = h_d / h_t if h_t > 0 else 0
                (px, py), (dx, dy) = self._centre(pred), self._centre(d[:4])
                dist = ((px - dx) ** 2 + (py - dy) ** 2) ** 0.5 / max(h_t, h_d, 1.0)
                if dist < 0.5 and 0.6 <= ratio <= 1.6:
                    pairs.append((1.0 - dist, tid, di))
        pairs.sort(reverse=True)
        used_t, used_d, out = set(), set(), []
        for _, tid, di in pairs:
            if tid in used_t or di in used_d:
                continue
            used_t.add(tid); used_d.add(di)
            tr, d = self.tracks[tid], dets[di]
            dt = t - tr["last_t"]
            if dt > 1e-6:
                (ox, oy), (nx, ny) = self._centre(tr["box"]), self._centre(d[:4])
                tr["vel"] = (0.5 * tr["vel"][0] + 0.5 * (nx - ox) / dt, 0.5 * tr["vel"][1] + 0.5 * (ny - oy) / dt)
            tr.update(box=d[:4], last_t=t, hits=tr["hits"] + 1, conf=d[4])
            if tr["hits"] >= self.min_hits:
                out.append(Det(tid, tuple(tr["box"]), tr["conf"]))
        for di, d in enumerate(dets):
            if di in used_d:
                continue
            self.tracks[self.next_id] = {"box": d[:4], "last_t": t, "hits": 1, "conf": d[4], "vel": (0.0, 0.0)}
            if self.min_hits <= 1:
                out.append(Det(self.next_id, tuple(d[:4]), d[4]))
            self.next_id += 1
        for tid in [k for k, tr in self.tracks.items() if t - tr["last_t"] > self.max_age]:
            del self.tracks[tid]
        return out


class PersonDetector:
    def __init__(self, cfg: dict):
        self.cfg = cfg
        self.conf = float(cfg.get("conf", 0.35))
        self.process_width = int(cfg.get("process_width", 960))
        self.backend = "hog"
        self.model = None
        self.model_name = "OpenCV HOG pedestrian detector"
        self.model_version = f"opencv-{cv2.__version__}"
        self.tracker_name = "iou"
        self.note = ""
        self.yolo_state = "NOT_CONFIGURED"   # state of the preferred YOLO detector (registry reports this)
        self.yolo_detail = ""
        want = cfg.get("backend", "auto")
        if want in ("auto", "yolo"):
            self._try_yolo()
        else:
            self.yolo_state, self.yolo_detail = "DISABLED", "backend forced to 'hog' in settings"
        if self.backend == "hog":
            self.hog = cv2.HOGDescriptor()
            self.hog.setSVMDetector(cv2.HOGDescriptor_getDefaultPeopleDetector())
        self.tracker = SimpleTracker(cfg.get("iou_match", 0.3), cfg.get("max_age_s", 2.0),
                                     cfg.get("min_hits", 2))

    def _try_yolo(self) -> None:
        w = config.resolve_path(self.cfg.get("weights_path", "models/yolov8n.pt"))
        try:
            from ultralytics import YOLO  # AGPL-3.0 licence - see docs/ML_METHODOLOGY.md
        except Exception as e:
            self.note = f"ultralytics not installed ({type(e).__name__}); using HOG fallback"
            self.yolo_state, self.yolo_detail = "DEPENDENCY_MISSING", "ultralytics/PyTorch not installed (pip install -r requirements-ml.txt)"
            return
        if not w.exists():
            self.note = f"YOLO weights not found at {w.name}; using HOG fallback"
            self.yolo_state, self.yolo_detail = "FILE_MISSING", f"weights file {w.name} not found in models/"
            return
        try:
            self.model = YOLO(str(w))
            self.backend = "yolo"
            self.model_name = f"Ultralytics YOLO ({w.name})"
            import ultralytics
            self.model_version = f"ultralytics-{ultralytics.__version__}"
            self.yolo_state, self.yolo_detail = "LOADED", f"{w.name} loaded"
            tr = self.cfg.get("tracker", "auto")
            self.tracker_name = "bytetrack" if tr in ("auto", "bytetrack") else "iou"
        except Exception as e:
            self.model = None
            self.note = f"YOLO failed to load ({e}); using HOG fallback"
            self.yolo_state, self.yolo_detail = "LOAD_FAILED", f"{type(e).__name__}: {e}"[:200]

    def reset(self) -> None:
        """Forget tracks from a previous video (detector instances are reused across jobs)."""
        self.tracker = SimpleTracker(self.cfg.get("iou_match", 0.3), self.cfg.get("max_age_s", 2.0),
                                     self.cfg.get("min_hits", 2))
        if self.model is not None and getattr(self.model, "predictor", None) is not None:
            self.model.predictor = None  # Ultralytics re-creates (and so resets) its ByteTrack state

    def describe(self) -> dict:
        return {"backend": self.backend, "model": self.model_name, "version": self.model_version,
                "tracker": "ByteTrack (Ultralytics)" if self.tracker_name == "bytetrack" else "simple IoU tracker",
                "note": self.note}

    def process(self, frame: np.ndarray, t: float) -> list[Det]:
        if self.backend == "yolo":
            return self._yolo(frame, t)
        return self._hog(frame, t)

    def _hog(self, frame, t) -> list[Det]:
        h, w = frame.shape[:2]
        s = min(1.0, self.process_width / w)
        small = cv2.resize(frame, (int(w * s), int(h * s))) if s < 1 else frame
        rects, weights = self.hog.detectMultiScale(small, winStride=(8, 8), padding=(8, 8), scale=1.05)
        boxes, scores = [], []
        for (x, y, rw, rh), wt in zip(rects, np.asarray(weights).reshape(-1)):
            conf = float(min(0.99, max(0.0, wt / 2.5)))  # HOG SVM score squashed to 0..1 (not a probability)
            if conf >= self.conf * 0.5:
                boxes.append([int(x), int(y), int(rw), int(rh)]); scores.append(conf)
        keep = cv2.dnn.NMSBoxes(boxes, scores, 0.0, 0.4) if boxes else []
        dets = []
        for i in np.asarray(keep).reshape(-1):
            x, y, rw, rh = boxes[i]
            dets.append((x / s, y / s, (x + rw) / s, (y + rh) / s, scores[i]))
        return self.tracker.update(dets, t)

    def _yolo(self, frame, t) -> list[Det]:
        if self.tracker_name == "bytetrack":
            res = self.model.track(frame, persist=True, classes=[0], conf=self.conf,
                                   tracker="bytetrack.yaml", verbose=False)[0]
            if res.boxes is None or res.boxes.id is None:
                return []
            return [Det(int(i), tuple(map(float, b)), float(c)) for b, i, c in
                    zip(res.boxes.xyxy.cpu().numpy(), res.boxes.id.cpu().numpy(), res.boxes.conf.cpu().numpy())]
        res = self.model.predict(frame, classes=[0], conf=self.conf, verbose=False)[0]
        dets = [(*map(float, b), float(c)) for b, c in
                zip(res.boxes.xyxy.cpu().numpy(), res.boxes.conf.cpu().numpy())]
        return self.tracker.update(dets, t)
