"""Transparent colour-based uniform baseline (beige shirt, navy trousers).

This is a BASELINE, not a trained classifier. It measures what fraction of the pixels in a
torso/leg region fall inside configurable HSV ranges and returns one of:
  ok | inconsistent | uncertain | unable_to_verify
Shirt and trousers are judged independently. Poor visibility never produces a violation.
"""
from __future__ import annotations
import cv2
import numpy as np
from .. import constants as C

SHIRT_BOX = (0.15, 0.20, 0.85, 0.48)    # x1,y1,x2,y2 as fractions of the person box
TROUSER_BOX = (0.15, 0.56, 0.85, 0.90)


def _region(frame, box, frac):
    x1, y1, x2, y2 = box
    w, h = x2 - x1, y2 - y1
    rx1, ry1 = int(max(0, x1 + frac[0] * w)), int(max(0, y1 + frac[1] * h))
    rx2, ry2 = int(min(frame.shape[1], x1 + frac[2] * w)), int(min(frame.shape[0], y1 + frac[3] * h))
    if rx2 - rx1 < 6 or ry2 - ry1 < 6:
        return None
    return frame[ry1:ry2, rx1:rx2]


def _mask(hsv, r: dict):
    lo = np.array([r["h_min"], r["s_min"], r["v_min"]], np.uint8)
    hi = np.array([r["h_max"], r["s_max"], r["v_max"]], np.uint8)
    return cv2.inRange(hsv, lo, hi)


def _normalise_v(hsv):
    """Shadow tolerance for light fabrics: if the region is uniformly under-exposed (90th-percentile
    brightness 80..205) rescale V (max x2) so a beige shirt in shade is compared on hue/saturation.
    Very dark regions (p90 < 80) are NOT rescaled, so black clothing is never turned into beige."""
    p90 = float(np.percentile(hsv[..., 2], 90))
    if 80 <= p90 < 205:
        out = hsv.copy()
        out[..., 2] = np.clip(hsv[..., 2].astype(np.float32) * min(2.0, 215.0 / p90), 0, 255).astype(np.uint8)
        return out
    return hsv


def judge_region(crop, rng: dict, cfg: dict, near_white_check: bool, clf=None) -> dict:
    if crop is None:
        return {"status": "unable_to_verify", "fraction": None, "reason": "region outside frame"}
    hsv = cv2.cvtColor(crop, cv2.COLOR_BGR2HSV)
    mean_v = float(hsv[..., 2].mean())
    if mean_v < cfg["min_region_mean_v"]:
        return {"status": "uncertain", "fraction": None, "reason": "region too dark to judge"}
    if float(np.mean(hsv[..., 2] >= 252)) > 0.5:
        return {"status": "uncertain", "fraction": None, "reason": "region over-exposed"}
    if clf is not None:  # trained classifier: same visibility gates as above, learned colour decision
        p_ok = clf.prob_ok(crop)
        hi, lo = cfg.get("clf_ok", 0.8), cfg.get("clf_bad", 0.2)
        st = "ok" if p_ok >= hi else "inconsistent" if p_ok <= lo else "uncertain"
        return {"status": st, "fraction": p_ok, "reason": f"classifier P(in uniform colour)={p_ok:.2f}"}
    if near_white_check:  # light garment (shirt): tolerate shade
        hsv = _normalise_v(hsv)
    frac = float(np.count_nonzero(_mask(hsv, rng)) / hsv.shape[0] / hsv.shape[1])
    if frac >= cfg["ok_fraction"]:
        return {"status": "ok", "fraction": frac, "reason": "colour within configured range"}
    if frac <= cfg["bad_fraction"]:
        if near_white_check:  # very pale/white shirts are hard to separate from cream under camera white balance
            white = float(np.count_nonzero((hsv[..., 1] < 8) & (hsv[..., 2] > 200)) / hsv.shape[0] / hsv.shape[1])
            if white > 0.3:
                return {"status": "uncertain", "fraction": frac, "reason": "near-white; cannot separate from beige"}
        return {"status": "inconsistent", "fraction": frac, "reason": "colour outside configured range"}
    return {"status": "uncertain", "fraction": frac, "reason": "partial colour match"}


def assess_person(frame, box, cfg: dict, clfs: dict | None = None) -> dict:
    clfs = clfs or {}
    h = box[3] - box[1]
    if h < cfg["min_person_height_px"]:
        return {"shirt": {"status": "unable_to_verify", "fraction": None, "reason": "person too small"},
                "trouser": {"status": "unable_to_verify", "fraction": None, "reason": "person too small"},
                "overall": C.UNI_NOT_ASSESSED}
    # Persons touching the bottom/top edge are partially visible: trousers unreliable.
    cut_bottom = box[3] >= frame.shape[0] - 3
    shirt = judge_region(_region(frame, box, SHIRT_BOX), cfg["beige"], cfg, True, clfs.get("shirt"))
    if cut_bottom:
        trouser = {"status": "unable_to_verify", "fraction": None, "reason": "legs cut off by frame edge"}
    else:
        trouser = judge_region(_region(frame, box, TROUSER_BOX), cfg["navy"], cfg, False, clfs.get("trouser"))
    return {"shirt": shirt, "trouser": trouser, "overall": overall(shirt["status"], trouser["status"])}


def overall(s: str, t: str) -> str:
    """Combine the two independently judged items. A mismatch needs positive evidence of a
    colour outside the range; unclear / hidden / dark items never count as mismatches."""
    if s == "unable_to_verify" and t == "unable_to_verify":
        return C.UNI_NOT_ASSESSED
    if s == "ok" and t == "ok":
        return C.UNI_COMPLIANT
    if s == "inconsistent" and t == "inconsistent":
        return C.UNI_BOTH
    if s == "inconsistent":
        return C.UNI_SHIRT
    if t == "inconsistent":
        return C.UNI_TROUSER
    return C.UNI_UNCERTAIN


def aggregate(samples: list[dict], cfg: dict) -> dict:
    """Combine many per-frame assessments of one tracked person into one verdict."""
    out = {}
    for part in ("shirt", "trouser"):
        concl = [s[part]["status"] for s in samples if s[part]["status"] in ("ok", "inconsistent")]
        fr = [s[part]["fraction"] for s in samples if s[part]["fraction"] is not None]
        out[part + "_fraction"] = float(np.median(fr)) if fr else None
        if not samples or all(s[part]["status"] == "unable_to_verify" for s in samples):
            out[part] = "unable_to_verify"
        elif len(concl) < cfg["min_samples_for_verdict"]:
            out[part] = "uncertain"
        else:
            ok = concl.count("ok") / len(concl)
            bad = concl.count("inconsistent") / len(concl)
            out[part] = "ok" if ok >= cfg["majority"] else "inconsistent" if bad >= cfg["majority"] else "uncertain"
    out["overall"] = overall(out["shirt"], out["trouser"])
    return out


LABELS = {
    "ok": "Colour within range", "inconsistent": "Colour outside range", "uncertain": "Uncertain",
    "unable_to_verify": "Unable to verify",
    C.UNI_COMPLIANT: "Appears compliant", C.UNI_SHIRT: "Possible shirt mismatch",
    C.UNI_TROUSER: "Possible trouser mismatch", C.UNI_BOTH: "Possible uniform mismatch",
    C.UNI_UNCERTAIN: "Uncertain", C.UNI_NOT_ASSESSED: "Not assessed",
}
