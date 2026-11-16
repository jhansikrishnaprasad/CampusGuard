"""Trained colour classifier for ONE clothing region (shirt or trousers) - safe JSON format (no pickle).

Features are colour statistics of the region (hue histogram of saturated pixels, saturation/value/Lab
statistics). `scripts/train_uniform_classifier.py` fits a logistic regression on labelled crops, splitting by
recording session, and writes <name>.json. Inference needs only NumPy. Without a JSON file the app uses the
HSV baseline; a loaded classifier is reported by the registry with its own evaluation state.
"""
from __future__ import annotations
import json
from pathlib import Path
import cv2
import numpy as np

FEATURE_NAMES = [f"hue_bin_{i}" for i in range(12)] + ["sat_mean", "sat_std", "val_mean", "val_std", "val_p10", "val_p90",
                                                      "lab_a_mean", "lab_b_mean", "lab_a_std", "lab_b_std", "low_sat_frac", "dark_frac"]


def extract_features(crop_bgr: np.ndarray) -> np.ndarray:
    c = cv2.resize(crop_bgr, (32, 32), interpolation=cv2.INTER_AREA)
    hsv = cv2.cvtColor(c, cv2.COLOR_BGR2HSV).reshape(-1, 3).astype(np.float32)
    lab = cv2.cvtColor(c, cv2.COLOR_BGR2LAB).reshape(-1, 3).astype(np.float32)
    h, s, v = hsv[:, 0], hsv[:, 1], hsv[:, 2]
    sat = s >= 20
    hist = np.histogram(h[sat], bins=12, range=(0, 180))[0].astype(np.float32) / max(1, sat.sum()) if sat.any() else np.zeros(12, np.float32)
    f = list(hist) + [s.mean() / 255, s.std() / 255, v.mean() / 255, v.std() / 255, np.percentile(v, 10) / 255, np.percentile(v, 90) / 255,
                      lab[:, 1].mean() / 255, lab[:, 2].mean() / 255, lab[:, 1].std() / 255, lab[:, 2].std() / 255,
                      float(np.mean(s < 20)), float(np.mean(v < 50))]
    return np.asarray(f, np.float32)


class LinearRegionClassifier:
    def __init__(self, meta: dict):
        self.meta = meta
        self.mean, self.std = np.asarray(meta["mean"], np.float32), np.maximum(np.asarray(meta["std"], np.float32), 1e-6)
        self.coef, self.intercept = np.asarray(meta["coef"], np.float32), float(meta["intercept"])
        self.version = str(meta.get("version", "unknown"))
        self.part = meta.get("part")

    @staticmethod
    def validate(meta) -> str | None:
        if not isinstance(meta, dict) or meta.get("type") != "logistic":
            return "type must be 'logistic'"
        n = len(FEATURE_NAMES)
        if meta.get("feature_names") != FEATURE_NAMES:
            return "feature_names do not match this version of the application"
        for k in ("mean", "std", "coef"):
            if not (isinstance(meta.get(k), list) and len(meta[k]) == n and all(isinstance(x, (int, float)) for x in meta[k])):
                return f"'{k}' must be a list of {n} numbers"
        if not isinstance(meta.get("intercept"), (int, float)):
            return "'intercept' must be a number"
        return None

    @classmethod
    def load(cls, path: Path) -> "LinearRegionClassifier":
        meta = json.loads(Path(path).read_text(encoding="utf-8"))
        err = cls.validate(meta)
        if err:
            raise ValueError(err)
        return cls(meta)

    def prob_ok(self, crop_bgr: np.ndarray) -> float:
        z = float(((extract_features(crop_bgr) - self.mean) / self.std) @ self.coef + self.intercept)
        return float(1.0 / (1.0 + np.exp(-np.clip(z, -30, 30))))


def fit_logistic(X: np.ndarray, y: np.ndarray, part: str, version: str, extra: dict | None = None) -> dict:
    """Fit a standardised logistic regression (y: 1 = in uniform colour, 0 = not) and return the JSON-able model."""
    from sklearn.linear_model import LogisticRegression
    mean, std = X.mean(0), np.maximum(X.std(0), 1e-6)
    lr = LogisticRegression(C=1.0, max_iter=2000, class_weight="balanced").fit((X - mean) / std, y)
    return {"type": "logistic", "part": part, "version": version, "feature_names": FEATURE_NAMES,
            "mean": mean.tolist(), "std": std.tolist(), "coef": lr.coef_[0].tolist(), "intercept": float(lr.intercept_[0]),
            "classes": ["inconsistent", "ok"], **(extra or {})}
