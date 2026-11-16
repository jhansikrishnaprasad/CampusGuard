"""Central model registry: loads every model once, validates it, and reports an honest state per model.

States: LOADED | FILE_MISSING | DEPENDENCY_MISSING | LOAD_FAILED | NOT_CONFIGURED | DISABLED
Evaluation (separate axis): NOT_EVALUATED (no recorded labelled evaluation) | EVALUATED (metrics recorded).
Nothing is silently substituted: when YOLO is unavailable the OpenCV HOG fallback is listed as a
separate, clearly labelled entry and the active detector is reported as the fallback.
"""
from __future__ import annotations
import json
import logging
import threading
from .. import config
from .. import constants as C
from .activity import ActivityRecognizer
from .idcard import IdCardDetector
from .person import PersonDetector
from .uniform_clf import LinearRegionClassifier

log = logging.getLogger(__name__)


def _signature(s: dict) -> str:
    keep = {"person": s["person"], "idcard": s["idcard"],
            "uclf": [s["uniform"].get("shirt_classifier_path"), s["uniform"].get("trouser_classifier_path")],
            "act": {k: {"enabled": v["enabled"], "model_path": v["model_path"]} for k, v in s["activity"].items()}}
    return json.dumps(keep, sort_keys=True)


class ModelRegistry:
    def __init__(self):
        self._lock = threading.RLock()
        self._sig = None
        self.detector: PersonDetector | None = None
        self.idc: IdCardDetector | None = None
        self.recognizers: dict[str, ActivityRecognizer] = {}
        self.uniform_clfs: dict[str, LinearRegionClassifier] = {}
        self.uniform_clf_notes: dict[str, str] = {}

    def ensure(self, settings: dict) -> "ModelRegistry":
        """(Re)load models when the relevant configuration changed. Safe to call often."""
        with self._lock:
            sig = _signature(settings)
            if sig != self._sig:
                log.info("Loading models")
                self.detector = PersonDetector(settings["person"])
                self.idc = IdCardDetector(settings["idcard"])
                a = settings["activity"]
                self.recognizers = {"fight": ActivityRecognizer("fight", config.CATEGORY_FIGHT, a["fight"]),
                                    "smoking": ActivityRecognizer("smoking", config.CATEGORY_SMOKING, a["smoking"])}
                self.uniform_clfs, self.uniform_clf_notes = {}, {}
                for part in ("shirt", "trouser"):
                    path = settings["uniform"].get(f"{part}_classifier_path") or ""
                    if not path:
                        continue
                    fp = config.resolve_path(path)
                    if not fp.is_file():
                        self.uniform_clf_notes[part] = "no trained model file: using HSV baseline"
                        continue
                    try:
                        self.uniform_clfs[part] = LinearRegionClassifier.load(fp)
                        self.uniform_clf_notes[part] = f"trained classifier loaded ({fp.name})"
                    except Exception as e:
                        self.uniform_clf_notes[part] = f"LOAD_FAILED ({e}): using HSV baseline"
                self._sig = sig
            return self

    def for_job(self, settings: dict):
        """Models for one analysis run (person tracker state is reset)."""
        with self._lock:
            self.ensure(settings)
            self.detector.reset()
            return self.detector, self.idc, self.recognizers

    def snapshot(self, settings: dict, evaluations: list[dict] | None = None) -> list[dict]:
        with self._lock:
            self.ensure(settings)
            ev = evaluations or []

            def evaluation(key: str) -> dict:
                for e in ev:  # newest first
                    if e.get("model_name") == key and e.get("status", "completed") == "completed":
                        return {"state": "EVALUATED", "dataset": e.get("dataset_name"), "precision": e.get("precision"),
                                "recall": e.get("recall"), "f1": e.get("f1"), "evaluated_at": e.get("evaluated_at")}
                return {"state": "NOT_EVALUATED"}

            d = self.detector
            yolo_ok = d.backend == "yolo"
            out = [
                {"key": "person_yolo", "title": "Person detector (YOLO)", "state": d.yolo_state, "detail": d.yolo_detail,
                 "name": d.model_name if yolo_ok else None, "version": d.model_version if yolo_ok else None,
                 "active": yolo_ok, "requested": True, "evaluation": evaluation("person_yolo")},
                {"key": "person_hog", "title": "Person detector fallback (OpenCV HOG)", "state": C.M_LOADED,
                 "detail": "Weak fallback: misses small, seated or partially visible people" + ("" if not yolo_ok else " (not in use)"),
                 "name": "OpenCV HOG pedestrian detector", "version": d.model_version if not yolo_ok else None,
                 "active": not yolo_ok, "requested": False, "evaluation": evaluation("person_hog")},
                {"key": "tracker", "title": "Tracker", "state": C.M_LOADED,
                 "detail": d.describe()["tracker"] + ("" if d.tracker_name == "bytetrack" else " - IDs fragment under occlusion"),
                 "name": d.describe()["tracker"], "version": None, "active": True, "requested": True,
                 "evaluation": evaluation("tracker")},
                {"key": "uniform", "title": "Uniform colour assessment", "state": C.M_LOADED,
                 "detail": ("Trained colour classifier active for: " + ", ".join(self.uniform_clfs) + ". " if self.uniform_clfs else
                            "Transparent HSV colour-range rules, NOT a trained classifier. ")
                           + "; ".join(f"{k}: {v}" for k, v in self.uniform_clf_notes.items()),
                 "name": "linear-colour-classifier" if self.uniform_clfs else "hsv-colour-baseline",
                 "version": "+".join(sorted({c.version for c in self.uniform_clfs.values()})) if self.uniform_clfs else "hsv-v2",
                 "active": True, "requested": True,
                 "evaluation": evaluation("uniform_classifier" if self.uniform_clfs else "uniform_baseline")},
            ]
            i = self.idc
            out.append({"key": "id_card", "title": "ID-card / lanyard detector",
                        "state": C.M_DISABLED if not i.enabled else C.M_LOADED,
                        "detail": i.note, "name": i.method, "version": None, "active": i.enabled,
                        "requested": i.enabled, "evaluation": evaluation("id_card_detector")})
            for k, r in self.recognizers.items():
                out.append({"key": k, "title": "Fighting recognition" if k == "fight" else "Smoking recognition",
                            "state": r.status, "detail": r.detail, "name": r.name if r.ready else None,
                            "version": r.version if r.ready else None, "device": r.device if r.ready else None,
                            "active": r.ready, "requested": r.status != C.M_DISABLED, "category": r.category,
                            "evaluation": evaluation(r.category)})
            wf = {"person_yolo": settings["person"]["weights_path"], "fight": settings["activity"]["fight"]["model_path"],
                  "smoking": settings["activity"]["smoking"]["model_path"], "id_card": settings["idcard"].get("custom_model_path") or None}
            for e in out:
                e["weight_file"] = wf.get(e["key"])
            return out


registry = ModelRegistry()
