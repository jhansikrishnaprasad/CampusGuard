"""Video analysis pipeline. Pure Python/OpenCV - no database access (the job worker persists results).

Memory: frames are read one at a time with cap.grab()/retrieve(); only small rolling buffers
(a few seconds of down-scaled frames for action recognition) are held. A one-hour file is never
loaded into RAM.
"""
from __future__ import annotations
import logging
import shutil
import subprocess
import time
from collections import deque
from dataclasses import dataclass, field
from pathlib import Path
from typing import Callable, Optional
import cv2
import numpy as np
from .. import config
from .. import constants as C
from . import idcard as idmod
from . import uniform as unimod
from .activity import ActivityRecognizer
from .events import Pred, group_predictions
from .person import PersonDetector

log = logging.getLogger(__name__)


class Cancelled(Exception):
    pass


@dataclass
class AnalysisResult:
    people: list = field(default_factory=list)
    events: list = field(default_factory=list)
    warnings: list = field(default_factory=list)
    model_versions: dict = field(default_factory=dict)
    coverage: dict = field(default_factory=dict)
    module_results: dict = field(default_factory=dict)
    degraded: list = field(default_factory=list)
    partial: bool = False
    frames_decoded: int = 0
    frames_analysed: int = 0
    expected_frames: int = 0
    seconds: float = 0.0


def fmt_ts(t: float) -> str:
    t = int(t)
    return f"{t // 3600:02d}:{(t % 3600) // 60:02d}:{t % 60:02d}"


def _annotate(frame, box, label_lines, color=(235, 94, 49)):
    img = frame.copy()
    x1, y1, x2, y2 = [int(v) for v in box]
    cv2.rectangle(img, (x1, y1), (x2, y2), color, 3)
    y = max(18, y1 - 6)
    for line in label_lines:
        cv2.putText(img, line, (x1, y), cv2.FONT_HERSHEY_SIMPLEX, 0.6, (0, 0, 0), 4, cv2.LINE_AA)
        cv2.putText(img, line, (x1, y), cv2.FONT_HERSHEY_SIMPLEX, 0.6, (255, 255, 255), 1, cv2.LINE_AA)
        y -= 20
    return img


def _read_frame_at(video_path: Path, t: float) -> Optional[np.ndarray]:
    cap = cv2.VideoCapture(str(video_path))
    try:
        cap.set(cv2.CAP_PROP_POS_MSEC, max(0.0, t) * 1000)
        ok, fr = cap.read()
        return fr if ok else None
    finally:
        cap.release()


def make_clip(video_path: Path, start: float, end: float, out_path: Path, max_width: int = 854) -> bool:
    """Write a short H.264 clip (needs ffmpeg for browser-playable output; else mp4v fallback)."""
    cap = cv2.VideoCapture(str(video_path))
    try:
        fps = cap.get(cv2.CAP_PROP_FPS) or 25.0
        w, h = int(cap.get(cv2.CAP_PROP_FRAME_WIDTH)), int(cap.get(cv2.CAP_PROP_FRAME_HEIGHT))
        s = min(1.0, max_width / max(w, 1))
        ow, oh = int(w * s) // 2 * 2, int(h * s) // 2 * 2
        cap.set(cv2.CAP_PROP_POS_MSEC, max(0.0, start) * 1000)
        raw = out_path.with_name(out_path.stem + "_raw.mp4")
        vw = cv2.VideoWriter(str(raw), cv2.VideoWriter_fourcc(*"mp4v"), fps, (ow, oh))
        if not vw.isOpened():
            return False
        n_max = int((end - start) * fps) + 1
        n = 0
        while n < n_max:
            ok, fr = cap.read()
            if not ok:
                break
            vw.write(cv2.resize(fr, (ow, oh)) if s < 1 else fr)
            n += 1
        vw.release()
        if n == 0:
            raw.unlink(missing_ok=True)
            return False
        ff = shutil.which("ffmpeg")
        if ff:
            r = subprocess.run([ff, "-y", "-loglevel", "error", "-i", str(raw), "-c:v", "libx264",
                                "-pix_fmt", "yuv420p", "-preset", "veryfast", "-crf", "27", "-an", str(out_path)],
                               capture_output=True)
            if r.returncode == 0 and out_path.exists():
                raw.unlink(missing_ok=True)
                return True
            log.warning("ffmpeg clip transcode failed: %s", r.stderr[-300:])
        raw.replace(out_path)
        return True
    finally:
        cap.release()


def _uniform_score(agg: dict, ucfg: dict, learned: bool):
    """0..1 closeness of the evidence to the configured colours (NOT a calibrated probability)."""
    vals = []
    for part in ("shirt_fraction", "trouser_fraction"):
        f = agg.get(part)
        if f is not None:
            vals.append(float(f) if learned else min(1.0, float(f) / max(ucfg["ok_fraction"], 1e-6)))
    return round(sum(vals) / len(vals), 3) if vals else None


def build_coverage(detector, idc, recognizers) -> tuple[dict, list]:
    """Which requested AI modules actually ran. A job is PARTIAL if any requested module did not run."""
    d = detector.describe()
    degraded = []
    person_note = d["model"]
    if detector.backend == "hog":
        person_note += f" - FALLBACK ({detector.note or 'YOLO not requested'})"
        degraded.append("Person detection used the weak OpenCV HOG fallback: people may be missed")
    if detector.tracker_name != "bytetrack":
        degraded.append("Tracking used the simple IoU tracker: IDs fragment when people are occluded")
    cov = {"person_detection": {"requested": True, "ran": True, "state": C.M_LOADED, "note": person_note},
           "tracking": {"requested": True, "ran": True, "state": C.M_LOADED, "note": d["tracker"]},
           "uniform": {"requested": True, "ran": True, "state": C.M_LOADED, "note": "HSV colour baseline (not a trained model)"},
           "id_card": {"requested": idc.enabled, "ran": idc.enabled, "state": C.M_LOADED if idc.enabled else C.M_DISABLED,
                       "note": idc.note}}
    if idc.enabled and idc.method == "heuristic":
        degraded.append("ID-card check used the low-reliability heuristic")
    for k, r in recognizers.items():
        cov[k] = {"requested": r.status != C.M_DISABLED, "ran": r.ready, "state": r.status, "note": r.detail}
    return cov, degraded


def analyze(video_path: Path, out_dir: Path, rel_prefix: str, settings: dict,
            progress_cb: Optional[Callable[[float], None]] = None,
            cancel_cb: Optional[Callable[[], bool]] = None,
            detector: Optional[PersonDetector] = None,
            idc: Optional[idmod.IdCardDetector] = None,
            recognizers: Optional[dict] = None,
            uniform_clfs: Optional[dict] = None) -> AnalysisResult:
    t_start = time.time()
    res = AnalysisResult()
    out_dir.mkdir(parents=True, exist_ok=True)
    (out_dir / "people").mkdir(exist_ok=True)
    ucfg, pcfg, acfg = settings["uniform"], settings["processing"], settings["activity"]

    detector = detector or PersonDetector(settings["person"])
    idc = idc or idmod.IdCardDetector(settings["idcard"])
    if recognizers is None:
        recognizers = {"fight": ActivityRecognizer("fight", config.CATEGORY_FIGHT, acfg["fight"]),
                       "smoking": ActivityRecognizer("smoking", config.CATEGORY_SMOKING, acfg["smoking"])}
    active = {k: r for k, r in recognizers.items() if r.ready}
    res.model_versions = {
        "person_detector": detector.describe(), "id_card": idc.describe(),
        "uniform": {"method": "hsv-colour-baseline", "version": "hsv-v1"},
        "activity": {k: r.describe() for k, r in recognizers.items()},
    }
    res.coverage, res.degraded = build_coverage(detector, idc, recognizers)
    for k, r in recognizers.items():
        if not r.ready:
            res.warnings.append(f"{k} recognition not run: {r.status} - {r.detail}")
    if detector.note:
        res.warnings.append(detector.note)

    cap = cv2.VideoCapture(str(video_path))
    if not cap.isOpened():
        raise RuntimeError("Video could not be opened by the decoder")
    try:
        fps = cap.get(cv2.CAP_PROP_FPS) or 25.0
        res.expected_frames = int(cap.get(cv2.CAP_PROP_FRAME_COUNT) or 0)
        step_fps = max(float(pcfg["person_fps"]), float(pcfg["activity_fps"]) if active else 0.0)
        step = max(1, int(round(fps / step_fps)))
        person_interval = 1.0 / float(pcfg["person_fps"])

        buffers = {k: deque(maxlen=int(acfg[k]["window_s"] * step_fps) + 3) for k in active}
        last_pred = {k: -1e9 for k in active}
        preds: dict[str, list[Pred]] = {k: [] for k in active}

        people: dict[int, dict] = {}
        last_person_t = -1e9
        idx, fails, last_prog = -1, 0, 0.0

        while True:
            ok = cap.grab()
            if not ok:
                fails += 1
                if fails > 30 or (res.expected_frames and idx + 1 >= res.expected_frames):
                    break
                continue
            fails = 0
            idx += 1
            res.frames_decoded += 1
            if idx % step:
                continue
            ok, frame = cap.retrieve()
            if not ok or frame is None:
                continue
            res.frames_analysed += 1
            t = idx / fps

            # ---- persons / uniform / ID card ----
            if t - last_person_t >= person_interval - 1e-6:
                last_person_t = t
                try:
                    dets = detector.process(frame, t)
                except Exception as e:  # recover from per-frame inference failure
                    log.warning("person inference failed at %.1fs: %s", t, e)
                    dets = []
                for d in dets:
                    p = people.setdefault(d.track_id, {"first": t, "last": t, "n": 0, "u": [], "id": [],
                                                       "last_sample_t": -1e9, "best_area": 0, "best_t": t,
                                                       "best_box": None, "obs": [], "last_obs_t": -1e9,
                                                       "id_conf": []})
                    p["last"], p["n"] = t, p["n"] + 1
                    if t - p["last_obs_t"] >= ucfg.get("observation_interval_s", 1.0) and len(p["obs"]) < 300:
                        p["last_obs_t"] = t
                        p["obs"].append((t, tuple(float(v) for v in d.box), float(d.conf)))
                    if (t - p["last_sample_t"] >= ucfg["sample_interval_s"]
                            and len(p["u"]) < ucfg["max_samples_per_track"]):
                        p["last_sample_t"] = t
                        a = unimod.assess_person(frame, d.box, ucfg, uniform_clfs)
                        i = idc.detect(frame, d.box)
                        p["u"].append(a); p["id"].append(i["status"])
                        if i.get("conf") is not None:
                            p["id_conf"].append(float(i["conf"]))
                        area = (d.box[2] - d.box[0]) * (d.box[3] - d.box[1])
                        conclusive = a["overall"] != C.UNI_NOT_ASSESSED
                        if conclusive and area > p["best_area"]:
                            p["best_area"], p["best_t"], p["best_box"] = area, t, d.box
                            lines = [f"T{d.track_id} @ {fmt_ts(t)}",
                                     f"shirt:{a['shirt']['status']} trousers:{a['trouser']['status']}",
                                     f"ID:{i['status']}"]
                            cv2.imwrite(str(out_dir / "people" / f"t{d.track_id}.jpg"),
                                        _annotate(frame, d.box, lines), [cv2.IMWRITE_JPEG_QUALITY, 85])
                            p["has_img"] = True

            # ---- activity windows ----
            for k, r in active.items():
                cfg = acfg[k]
                buffers[k].append((t, r.prepare(frame)))
                if t - last_pred[k] >= cfg["stride_s"] and buffers[k] and t - buffers[k][0][0] >= cfg["window_s"] * 0.9:
                    last_pred[k] = t
                    win = [f for (tt, f) in buffers[k] if tt >= t - cfg["window_s"]]
                    sel = [win[int(i)] for i in np.linspace(0, len(win) - 1, r.clip_len)]
                    try:
                        prob = r.predict(sel)
                        preds[k].append(Pred(t - cfg["window_s"], t, r.category, prob))
                    except Exception as e:
                        log.warning("%s inference failed at %.1fs: %s", k, t, e)
                        res.warnings.append(f"{k} inference error at {fmt_ts(t)}: {e}")

            prog = idx / res.expected_frames if res.expected_frames else 0.0
            if progress_cb and prog - last_prog >= 0.005:
                last_prog = prog
                progress_cb(min(prog, 0.97))
                if cancel_cb and cancel_cb():
                    raise Cancelled()
    finally:
        cap.release()

    if res.frames_decoded == 0:
        raise RuntimeError("No frames could be decoded from this video")
    if res.expected_frames and res.frames_decoded < 0.9 * res.expected_frames:
        res.coverage["video_decoding"] = {"requested": True, "ran": False, "state": "LOAD_FAILED",
                                          "note": "Video only partly decodable"}
        res.warnings.append(f"Only {res.frames_decoded}/{res.expected_frames} frames decoded "
                            f"({100 * res.frames_decoded / res.expected_frames:.0f}%): file may be truncated or corrupted. "
                            "Results cover the decodable part only.")

    # ---- finalise people ----
    min_hits = settings["person"].get("min_hits", 2)
    for tid, p in sorted(people.items()):
        agg = unimod.aggregate(p["u"], ucfg) if p["u"] else {
            "shirt": "unable_to_verify", "trouser": "unable_to_verify", "overall": C.UNI_NOT_ASSESSED,
            "shirt_fraction": None, "trouser_fraction": None}
        idstat = idmod.aggregate(p["id"], settings["idcard"]["min_samples"]) if p["id"] else C.ID_NOT_ASSESSED
        res.people.append({
            "track_ref": f"T{tid}", "first_seen_s": p["first"], "last_seen_s": p["last"], "detections": p["n"],
            "shirt_status": agg["shirt"], "trouser_status": agg["trouser"], "uniform_overall": agg["overall"],
            "shirt_fraction": agg["shirt_fraction"], "trouser_fraction": agg["trouser_fraction"],
            "id_status": idstat, "uniform_samples": len(p["u"]), "id_samples": len(p["id"]),
            "evidence_frame": f"{rel_prefix}/people/t{tid}.jpg" if p.get("has_img") else None,
            "best_t": p["best_t"],
            "uniform_score": _uniform_score(agg, ucfg, bool(uniform_clfs)),
            "uniform_method": "linear-colour-classifier" if uniform_clfs else "hsv-colour-baseline",
            "uniform_version": "+".join(sorted({c.version for c in uniform_clfs.values()})) if uniform_clfs else "hsv-v2",
            "id_confidence": max(p["id_conf"]) if p["id_conf"] else None,
            "id_method": idc.method, "id_version": "heuristic-v1" if idc.method == "heuristic" else idc.note[:30],
            "id_association": "inside-person-torso-box",
            "observations": p["obs"],
        })

    # ---- uniform review events (possible non-compliance only; uncertain never becomes an event) ----
    if ucfg.get("create_review_events", True):
        for pr in res.people:
            if pr["uniform_overall"] in C.UNIFORM_MISMATCH:
                bits = []
                for part, nm in (("shirt", "Shirt"), ("trouser", "Trousers")):
                    fr = pr[f"{part}_fraction"]
                    bits.append(f"{nm}: {unimod.LABELS[pr[part + '_status']]}" + (f" (in-range pixels {fr:.0%})" if fr is not None else ""))
                res.events.append({
                    "category": config.CATEGORY_UNIFORM, "track_ref": pr["track_ref"],
                    "start_s": pr["first_seen_s"], "end_s": pr["last_seen_s"], "confidence": None,
                    "model_name": "Colour-range baseline", "model_version": "hsv-v1",
                    "automated_status": "predicted", "predicted_class": pr["uniform_overall"],
                    "summary": "; ".join(bits) + ". Colour-based baseline - lighting, shadows, or occlusion can cause errors; human review required.",
                    "evidence": [{"kind": "frame", "rel_path": pr["evidence_frame"], "timestamp_s": pr["best_t"]}] if pr["evidence_frame"] else [],
                })

    # ---- activity events ----
    for k, r in active.items():
        c = acfg[k]
        for iv in group_predictions(preds[k], c["threshold"], c["uncertain_low"], c["min_duration_s"],
                                    c["merge_gap_s"], c["min_hits"]):
            ctx = [f"T{tid}" for tid, p in sorted(people.items()) if p["first"] <= iv.end and p["last"] >= iv.start]
            ev = {"category": iv.category, "track_ref": None, "start_s": iv.start, "end_s": iv.end,
                  "confidence": iv.max_conf, "model_name": r.name, "model_version": r.version,
                  "automated_status": iv.status, "predicted_class": iv.category.upper(),
                  "context_tracks": ctx,
                  "summary": f"{iv.hits} model windows; max {iv.max_conf:.2f}, mean {iv.mean_conf:.2f}. "
                             f"Whole-frame model: NOT attributed to a specific person. People tracked during this interval "
                             f"(context only): {', '.join(ctx) if ctx else 'none detected (detector may miss people)'}.",
                  "evidence": []}
            res.events.append(ev)

    # ---- evidence for activity events (frames + clip) ----
    n_ev = 0
    for ev in res.events:
        if ev["category"] == config.CATEGORY_UNIFORM:
            continue
        n_ev += 1
        base = f"{ev['category']}_{n_ev}"
        pk = (ev["start_s"] + ev["end_s"]) / 2
        for j, tt in enumerate(sorted({ev["start_s"], pk, ev["end_s"]})[: pcfg["max_evidence_frames_per_event"]]):
            fr = _read_frame_at(video_path, tt)
            if fr is not None:
                cv2.putText(fr, f"{fmt_ts(tt)}", (10, 28), cv2.FONT_HERSHEY_SIMPLEX, 0.8, (255, 255, 255), 2, cv2.LINE_AA)
                rel = f"{rel_prefix}/{base}_f{j}.jpg"
                cv2.imwrite(str(out_dir / f"{base}_f{j}.jpg"), fr)
                ev["evidence"].append({"kind": "frame", "rel_path": rel, "timestamp_s": tt})
        s = max(0.0, ev["start_s"] - pcfg["clip_padding_s"])
        e = min(ev["end_s"] + pcfg["clip_padding_s"], s + pcfg["max_clip_s"])
        if make_clip(video_path, s, e, out_dir / f"{base}.mp4"):
            ev["evidence"].append({"kind": "clip", "rel_path": f"{rel_prefix}/{base}.mp4", "timestamp_s": s})
        else:
            res.warnings.append(f"Could not write evidence clip for {base}")

    res.partial = any(c["requested"] and not c["ran"] for c in res.coverage.values())
    mr = {"person_detection": f"{len(res.people)} track(s)", "tracking": f"{len(res.people)} track(s)",
          "uniform": ", ".join(f"{n} {k}" for k, n in sorted(
              {u: sum(1 for p in res.people if p["uniform_overall"] == u) for u in {p["uniform_overall"] for p in res.people}}.items())) or "no people",
          "id_card": ", ".join(f"{n} {k}" for k, n in sorted(
              {u: sum(1 for p in res.people if p["id_status"] == u) for u in {p["id_status"] for p in res.people}}.items())) or "no people"}
    for k, cat in (("fight", config.CATEGORY_FIGHT), ("smoking", config.CATEGORY_SMOKING)):
        if k not in res.coverage or not res.coverage[k]["ran"]:
            mr[k] = C.R_NOT_ASSESSED          # module did not run: NOT evidence that nothing happened
        else:
            evs = [e for e in res.events if e["category"] == cat]
            mr[k] = (C.R_POSSIBLE[k] if any(e["automated_status"] == "predicted" for e in evs)
                     else C.R_UNCERTAIN if evs else C.R_NOT_DETECTED)
    res.module_results = mr
    res.seconds = time.time() - t_start
    if progress_cb:
        progress_cb(1.0)
    return res
