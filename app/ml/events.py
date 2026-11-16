"""Temporal grouping of window-level predictions into incident intervals."""
from __future__ import annotations
from dataclasses import dataclass, field


@dataclass
class Pred:
    t0: float
    t1: float
    category: str
    prob: float


@dataclass
class Interval:
    category: str
    start: float
    end: float
    max_conf: float
    mean_conf: float
    hits: int
    status: str  # predicted | uncertain
    preds: list = field(default_factory=list)

    @property
    def peak_time(self) -> float:
        p = max(self.preds, key=lambda x: x.prob)
        return (p.t0 + p.t1) / 2


def group_predictions(preds: list[Pred], threshold: float, uncertain_low: float,
                      min_duration_s: float, merge_gap_s: float, min_hits: int) -> list[Interval]:
    """Only predictions of the SAME category are merged, and only when the gap between
    consecutive windows is <= merge_gap_s. Clusters shorter than min_duration_s or with fewer
    than min_hits windows are discarded. A cluster with no window >= threshold is 'uncertain'."""
    out: list[Interval] = []
    cats = {p.category for p in preds}
    for cat in sorted(cats):
        items = sorted((p for p in preds if p.category == cat and p.prob >= uncertain_low), key=lambda p: p.t0)
        cluster: list[Pred] = []

        def flush():
            if not cluster:
                return
            start, end = cluster[0].t0, max(p.t1 for p in cluster)
            if len(cluster) >= min_hits and (end - start) >= min_duration_s:
                probs = [p.prob for p in cluster]
                out.append(Interval(cat, start, end, max(probs), sum(probs) / len(probs), len(cluster),
                                    "predicted" if max(probs) >= threshold else "uncertain", list(cluster)))
        for p in items:
            if cluster and p.t0 - max(q.t1 for q in cluster) > merge_gap_s:
                flush(); cluster = []
            cluster.append(p)
        flush()
    return sorted(out, key=lambda i: (i.start, i.category))
