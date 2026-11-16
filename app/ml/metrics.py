"""Evaluation metrics (no model code): second-level, event-level and crop-level."""
from __future__ import annotations
import numpy as np


def iou_1d(a, b) -> float:
    inter = max(0.0, min(a[1], b[1]) - max(a[0], b[0]))
    union = (a[1] - a[0]) + (b[1] - b[0]) - inter
    return inter / union if union > 0 else 0.0


def to_bins(duration_s: float, intervals) -> np.ndarray:
    n = max(1, int(np.ceil(duration_s)))
    v = np.zeros(n, int)
    for s, e in intervals:
        lo, hi = max(0, int(s)), min(n, int(np.ceil(e)))
        if hi > lo:
            v[lo:hi] = 1
    return v


def prf(tp: int, fp: int, fn: int) -> dict:
    p = tp / (tp + fp) if tp + fp else None
    r = tp / (tp + fn) if tp + fn else None
    f = 2 * p * r / (p + r) if p and r else (0.0 if (p is not None and r is not None) else None)
    return {"precision": p, "recall": r, "f1": f}


def bin_metrics(y_true, y_pred) -> dict:
    t, p = np.asarray(y_true, int), np.asarray(y_pred, int)
    tp, fp = int(((t == 1) & (p == 1)).sum()), int(((t == 0) & (p == 1)).sum())
    fn, tn = int(((t == 1) & (p == 0)).sum()), int(((t == 0) & (p == 0)).sum())
    m = prf(tp, fp, fn)
    m.update(tp=tp, fp=fp, fn=fn, tn=tn, confusion=[[tn, fp], [fn, tp]],
             false_positive_rate=fp / (fp + tn) if fp + tn else None)
    return m


def match_events(pred, truth, iou_thr: float = 0.3) -> dict:
    """One-to-one greedy matching by IoU: a single true event can be matched by only ONE prediction, so
    duplicate predictions of the same event count as false positives (not extra true positives)."""
    pairs = sorted(((iou_1d(p, t), i, j) for i, p in enumerate(pred) for j, t in enumerate(truth)), reverse=True)
    up, ut, ious = set(), set(), []
    for v, i, j in pairs:
        if v < iou_thr:
            break
        if i in up or j in ut:
            continue
        up.add(i); ut.add(j); ious.append(v)
    tp = len(ious)
    m = prf(tp, len(pred) - tp, len(truth) - tp)
    m.update(tp=tp, fp=len(pred) - tp, fn=len(truth) - tp, mean_iou=float(np.mean(ious)) if ious else None)
    return m


def crop_metrics(rows, positive: str = "inconsistent") -> dict:
    """rows: (true_label, predicted_label). Predicted may be 'uncertain'/'unable_to_verify' (abstentions).
    Precision/recall are computed on ALL samples: an abstention on a true positive counts as a miss."""
    n = len(rows)
    abst = sum(1 for _, p in rows if p in ("uncertain", "unable_to_verify"))
    tp = sum(1 for t, p in rows if t == positive and p == positive)
    fp = sum(1 for t, p in rows if t != positive and p == positive)
    fn = sum(1 for t, p in rows if t == positive and p != positive)
    m = prf(tp, fp, fn)
    labels = sorted({t for t, _ in rows} | {p for _, p in rows})
    m.update(n=n, abstention_rate=abst / n if n else None, tp=tp, fp=fp, fn=fn,
             confusion={t: {p: sum(1 for a, b in rows if a == t and b == p) for p in labels} for t in labels})
    return m
