"""Video-level uniform / ID-card compliance summary.

Everything here is DERIVED from the existing `tracked_people`, `analysis_jobs`, `job_modules` and `events`
tables - nothing new is stored. Counts are PERSON-level (one tracked person = one count, never frames/events)
and always refer to ONE analysis run (the latest successful run by default, or an explicit `job_id`).
Older runs are never mixed in.

Vocabulary (see app/constants.py - reused, not redefined):
  uniform_overall : COMPLIANT | POSSIBLE_SHIRT/TROUSER/UNIFORM_MISMATCH | UNCERTAIN | NOT_ASSESSED
  id_status       : CARD_VISIBLE | CARD_NOT_DETECTED | UNCERTAIN | NOT_ASSESSED

SAFETY RULE: ID `UNCERTAIN` is never converted into `CARD_NOT_DETECTED`. The default ID heuristic never
returns CARD_NOT_DETECTED at all (a miss is UNCERTAIN); only a custom-trained detector can.

Mutually exclusive person categories (priority order, every person falls in exactly one):
  both            uniform mismatch AND id CARD_NOT_DETECTED
  uniform_only    uniform mismatch, id is not CARD_NOT_DETECTED
  id_only         id CARD_NOT_DETECTED, uniform is not a mismatch
  compliant_both  uniform COMPLIANT and id CARD_VISIBLE
  not_assessed    otherwise, and at least one of the two checks is NOT_ASSESSED (could not be performed)
  uncertain       otherwise (both checks ran, at least one was inconclusive)
Headline (overlapping) figures:
  uniform_non_compliant = uniform_only + both ;  id_not_detected = id_only + both
"""
from __future__ import annotations

import json
import re
from typing import Iterable, Optional

from sqlalchemy import func, select
from sqlalchemy.orm import Session

from .. import config
from .. import constants as C
from ..models import AnalysisJob, Event, TrackedPerson, Video

CATEGORIES = ("both", "uniform_only", "id_only", "compliant_both", "uncertain", "not_assessed")
CATEGORY_LABELS = {
    "both": "Both issues", "uniform_only": "Uniform issue only", "id_only": "ID card not detected only",
    "compliant_both": "Apparently compliant", "uncertain": "Uncertain", "not_assessed": "Not assessed",
}
# filter key -> set of categories it selects (the headline filters overlap by design)
FILTERS = {
    "all": set(CATEGORIES),
    "uniform_issue": {"both", "uniform_only"},
    "id_issue": {"both", "id_only"},
    "both": {"both"}, "uniform_only": {"uniform_only"}, "id_only": {"id_only"},
    "compliant": {"compliant_both"}, "uncertain": {"uncertain"}, "not_assessed": {"not_assessed"},
}
COMPLIANCE_MODULES = ("person_detection", "tracking", "uniform", "id_card")
ID_UNRELIABLE_MESSAGE = "ID-card visibility could not be reliably verified for some people. Please review the evidence manually."


# --------------------------------------------------------------------------------------------------
# PURE LOGIC (no database): unit-testable without any web/database packages
# --------------------------------------------------------------------------------------------------
def classify(uniform_overall: Optional[str], id_status: Optional[str]) -> str:
    """Exactly one mutually exclusive category per person. Unknown values count as NOT_ASSESSED."""
    uo = uniform_overall if uniform_overall in C.UNIFORM_STATES else C.UNI_NOT_ASSESSED
    ids = id_status if id_status in C.ID_STATES else C.ID_NOT_ASSESSED
    u_issue = uo in C.UNIFORM_MISMATCH
    i_issue = ids == C.ID_NOT_DETECTED          # ONLY this exact status; UNCERTAIN is never promoted
    if u_issue and i_issue:
        return "both"
    if u_issue:
        return "uniform_only"
    if i_issue:
        return "id_only"
    if uo == C.UNI_COMPLIANT and ids == C.ID_VISIBLE:
        return "compliant_both"
    if uo == C.UNI_NOT_ASSESSED or ids == C.ID_NOT_ASSESSED:
        return "not_assessed"
    return "uncertain"


def count_people(pairs: Iterable[tuple]) -> dict:
    """pairs of (uniform_overall, id_status) -> all counts. Raises AssertionError if the maths is inconsistent."""
    cat = {k: 0 for k in CATEGORIES}
    total = id_uncertain = id_not_assessed = uni_uncertain = bad_values = 0
    for uo, ids in pairs:
        total += 1
        if uo not in C.UNIFORM_STATES or ids not in C.ID_STATES:
            bad_values += 1
        cat[classify(uo, ids)] += 1
        id_uncertain += ids == C.ID_UNCERTAIN
        id_not_assessed += ids == C.ID_NOT_ASSESSED
        uni_uncertain += uo == C.UNI_UNCERTAIN
    out = {
        "total_people": total,
        "uniform_non_compliant": cat["uniform_only"] + cat["both"],    # headline (overlapping)
        "id_not_detected": cat["id_only"] + cat["both"],               # headline (overlapping)
        "both_issues": cat["both"],                                    # overlapping subset of the two above
        "uniform_only": cat["uniform_only"], "id_only": cat["id_only"],
        "compliant_both": cat["compliant_both"],
        "uncertain": cat["uncertain"], "not_assessed": cat["not_assessed"],
        "inconclusive": cat["uncertain"] + cat["not_assessed"],
        "id_uncertain_people": id_uncertain, "id_not_assessed_people": id_not_assessed,
        "uniform_uncertain_people": uni_uncertain, "unrecognised_values": bad_values,
    }
    check_consistency(out)
    return out


def check_consistency(c: dict) -> None:
    exclusive = c["uniform_only"] + c["id_only"] + c["both_issues"] + c["compliant_both"] + c["uncertain"] + c["not_assessed"]
    assert exclusive == c["total_people"], f"categories sum to {exclusive}, total is {c['total_people']}"
    assert c["uniform_non_compliant"] == c["uniform_only"] + c["both_issues"]
    assert c["id_not_detected"] == c["id_only"] + c["both_issues"]
    assert c["both_issues"] <= min(c["uniform_non_compliant"], c["id_not_detected"])


def _plural(n: int, one: str, many: str) -> str:
    return f"{n} {one if n == 1 else many}"


def _id_state(model_versions: Optional[dict], id_methods: set, modules: list) -> dict:
    m = ((model_versions or {}).get("id_card") or {}).get("method")
    mod = next((x for x in modules if x["module"] == "id_card"), None)
    if mod is not None and not mod["requested"]:
        m = "disabled"
    if not m:
        m = next(iter(id_methods)) if len(id_methods) == 1 else ("mixed" if id_methods else "unknown")
    note = ((model_versions or {}).get("id_card") or {}).get("note")
    return {"method": m, "reliable": m == "custom_yolo", "note": note}


def build_warnings(c: dict, ctx: dict) -> list:
    """Honest, dynamically generated notices. Each: {code, level (info|warn|error), message}."""
    w = []

    def add(code, level, msg):
        w.append({"code": code, "level": level, "message": msg})

    n = c["total_people"]
    mods = ctx.get("modules", [])
    not_run = [m for m in mods if m["requested"] and not m["ran"]]
    if ctx.get("newer_job") and ctx["newer_job"]["status"] in ("queued", "running"):
        add("reprocessing", "info", f"A newer analysis (job #{ctx['newer_job']['id']}) is {ctx['newer_job']['status']}. "
                                    "These figures belong to the previous successful run until it finishes.")
    if n == 0:
        add("no_people", "info", "No people were tracked in this video, so there are no compliance statistics. "
                                 "This does not prove nobody was present: the person detector may have missed people "
                                 "(small, seated or partly hidden people are often missed).")
    if not_run:
        crit = [m["module"] for m in not_run if m["module"] in COMPLIANCE_MODULES]
        names = ", ".join(m["module"] for m in not_run)
        if crit:
            add("compliance_modules_missing", "warn", f"Analysis is PARTIAL and affects compliance results: {', '.join(crit)} did not run. "
                                                      "Missing checks are shown as 'not assessed', never as compliant.")
        else:
            add("partial_other_modules", "info", f"Analysis is PARTIAL: {names} did not run. Dress-code counts below are unaffected, "
                                                 "but incident detection (fighting/smoking) is incomplete for this video.")
    idm = ctx["id_card"]
    if n and idm["method"] == "disabled":
        add("id_disabled", "warn", "The ID-card check was disabled for this run: ID-card status is 'not assessed' for everyone.")
    elif n and not idm["reliable"]:
        add("id_unreliable", "warn", ID_UNRELIABLE_MESSAGE + " The default ID-card check is a low-reliability heuristic: when it finds no card the "
                                    "result is 'uncertain', never 'card not detected'. A custom-trained ID-card detector is needed for reliable "
                                    "'not detected' results.")
    if c["id_uncertain_people"]:
        add("id_uncertain", "warn", f"{_plural(c['id_uncertain_people'], 'person has', 'people have')} an UNCERTAIN ID-card result. "
                                    "They are NOT counted as 'ID card not detected' and must not be assumed to be without a card.")
    if c["uniform_uncertain_people"]:
        add("uniform_uncertain", "info", f"{_plural(c['uniform_uncertain_people'], 'person has', 'people have')} an uncertain uniform result "
                                         "(poor lighting, occlusion or partial colour match). They are not counted as non-compliant.")
    if c["not_assessed"]:
        add("not_assessed_people", "info", f"{_plural(c['not_assessed'], 'person was', 'people were')} too small, partly visible or otherwise "
                                           "not assessable for at least one check.")
    if ctx.get("uniform_method") in ("hsv-colour-baseline", None) and n:
        add("uniform_baseline", "info", "Uniform results come from a colour-range baseline (not a trained model). Lighting, shadows and "
                                        "occlusion can cause errors: every possible mismatch needs human verification.")
    for dw in ctx.get("degraded", []):
        add("degraded", "warn", dw)
    if c["unrecognised_values"]:
        add("data_quality", "warn", f"{c['unrecognised_values']} stored result(s) had an unrecognised status and were treated as 'not assessed'.")
    return w


def build_alert(c: dict, ctx: dict) -> dict:
    """The headline panel. Never describes uncertain / not-assessed people as compliant."""
    flagged = c["uniform_non_compliant"] or c["id_not_detected"]
    limited = any(m["requested"] and not m["ran"] and m["module"] in COMPLIANCE_MODULES for m in ctx.get("modules", []))
    if c["total_people"] == 0:
        return {"level": "none", "title": "NO PEOPLE TRACKED",
                "message": "No people were tracked in this video, so no compliance statistics are available. This does not prove nobody was present."}
    if flagged:
        return {"level": "attention", "title": "ATTENTION",
                "message": "ATTENTION: Possible dress-code compliance issues were identified in this video. "
                           "Please review the flagged individuals and verify the findings."}
    if c["inconclusive"] or limited:
        k = c["inconclusive"]
        return {"level": "caution", "title": "NO POSSIBLE ISSUES FOUND - SOME RESULTS INCONCLUSIVE",
                "message": f"No possible uniform non-compliance or ID-card non-detection was recorded, but {_plural(k, 'person', 'people')} could not "
                           "be conclusively assessed. Do not treat them as compliant; review the evidence manually."}
    return {"level": "clear", "title": "NO POSSIBLE ISSUES FOUND",
            "message": f"No possible dress-code issues were recorded among {c['total_people']} tracked "
                       f"{'person' if c['total_people'] == 1 else 'people'}. This is an automated check and does not replace manual verification."}


def build_notification(c: dict, ctx: dict) -> dict:
    lines = []
    if c["uniform_non_compliant"]:
        k = c["uniform_non_compliant"]
        lines.append(f"{k} person has a possible uniform mismatch." if k == 1 else f"{k} people have possible uniform mismatches.")
    if c["id_not_detected"]:
        k = c["id_not_detected"]
        lines.append(f"{k} person has an ID card not detected." if k == 1 else f"{k} people have ID cards not detected.")
    if c["both_issues"]:
        k = c["both_issues"]
        lines.append(f"{k} person has both issues." if k == 1 else f"{k} people have both issues.")
    if not lines:
        if c["total_people"] == 0:
            lines.append("No people were tracked in this video.")
        elif c["inconclusive"]:
            lines.append(f"No possible issues recorded; {_plural(c['inconclusive'], 'person', 'people')} could not be conclusively assessed.")
        else:
            lines.append("No possible dress-code issues were recorded.")
    if c["total_people"] and not ctx["id_card"]["reliable"]:
        lines.append("ID-card check is low-reliability: please review manually.")
    if ctx["job"]["partial"]:
        lines.append("Partial analysis: some modules did not run.")
    return {"title": "VIDEO ANALYSIS COMPLETED" + (" (PARTIAL)" if ctx["job"]["partial"] else ""), "lines": lines,
            "link_label": "Open compliance report \u2192"}


def build_limitations(ctx: dict) -> list:
    idm, out = ctx["id_card"], []
    if idm["method"] == "custom_yolo":
        out.append("ID-card visibility uses a custom detector; 'card not detected' only means no card was seen - it is never proof that no card is worn.")
    elif idm["method"] == "disabled":
        out.append("ID-card detection was disabled in this run; no ID-card statistics exist.")
    else:
        out.append("ID-card visibility uses a low-reliability geometric heuristic; its misses are reported as 'uncertain', not 'not detected'. "
                   "Reliable results require a custom-trained ID-card detector and labelled data.")
    out.append("Uniform results are colour-range based" if ctx.get("uniform_method") in (None, "hsv-colour-baseline") else
               "Uniform results use a learned colour classifier")
    out[-1] += (" and have " + ("a recorded evaluation." if ctx.get("uniform_evaluated") else "no recorded labelled evaluation (accuracy unknown)."))
    out.append("Tracking references (T1, T2, ...) are temporary and are not verified identities; one person may appear under several references.")
    out.append("All findings are automated predictions that require manual review; no accuracy figure is claimed.")
    return out


def _fmt(t) -> str:
    t = int(t or 0)
    return f"{t // 3600:02d}:{(t % 3600) // 60:02d}:{t % 60:02d}"


def _iso(d):
    return d.isoformat() + "Z" if d else None


def _file_ok(rel: str) -> bool:
    """Does the evidence file exist? Uses the same traversal guard as the download endpoint; never raises."""
    try:
        from ..security import safe_join
        return safe_join(config.EVIDENCE_DIR, rel).is_file()
    except Exception:
        return False


def _track_no(ref: str) -> int:
    m = re.search(r"\d+", ref or "")
    return int(m.group()) if m else 0


# --------------------------------------------------------------------------------------------------
# DATABASE LAYER (thin; uses the same query patterns as the rest of the code base)
# --------------------------------------------------------------------------------------------------
def latest_done_job(db: Session, video_id: int) -> Optional[AnalysisJob]:
    return (db.query(AnalysisJob).filter(AnalysisJob.video_id == video_id, AnalysisJob.status.in_(C.DONE_STATES))
            .order_by(AnalysisJob.id.desc()).first())


def _modules(job: AnalysisJob) -> list:
    return [{"module": m.module, "requested": bool(m.requested), "ran": bool(m.ran), "state": m.state, "result": m.result,
             "evaluation_state": m.evaluation_state, "detail": (m.detail or "")[:200]}
            for m in sorted(job.modules, key=lambda m: m.id)]


def _loads(s, default):
    try:
        return json.loads(s) if s else default
    except ValueError:
        return default


def _empty(video: Video, job: Optional[AnalysisJob], status: str, message: str) -> dict:
    z = count_people([])
    return {"video_id": video.id, "video_filename": video.original_filename, "job_id": job.id if job else None, "status": status,
            "available": False, "message": message, **z, "warnings": [], "requires_manual_review": False,
            "alert": {"level": "none", "title": "NO COMPLIANCE RESULTS", "message": message}, "notification": None,
            "modules": [], "partial": False, "is_current": False, "methods": {}, "limitations": []}


def summarize(db: Session, video: Video, job_id: Optional[int] = None) -> dict:
    """Compliance summary of ONE run. job_id=None -> latest successful run. Raises LookupError for a foreign/unknown job."""
    if job_id is not None:
        job = db.get(AnalysisJob, job_id)
        if job is None or job.video_id != video.id:
            raise LookupError("Analysis job not found for this video")
    else:
        job = latest_done_job(db, video.id)
        if job is None:
            last = db.query(AnalysisJob).filter(AnalysisJob.video_id == video.id).order_by(AnalysisJob.id.desc()).first()
            if last is None:
                return _empty(video, None, "not_analysed", "This video has not been analysed yet. Start an analysis to obtain compliance results.")
            msgs = {"queued": "Analysis is queued; compliance results will appear when it finishes.",
                    "running": "Analysis is running; compliance results will appear when it finishes.",
                    "failed": "The analysis failed, so no compliance results exist for this video.",
                    "cancelled": "The analysis was cancelled, so no compliance results exist for this video."}
            return _empty(video, last, last.status, msgs.get(last.status, "No completed analysis exists for this video."))
    if job.status not in C.DONE_STATES:
        msgs = {"queued": "Analysis is queued.", "running": "Analysis is still running.", "failed": "This analysis failed; it has no compliance results.",
                "cancelled": "This analysis was cancelled; it has no compliance results."}
        return _empty(video, job, job.status, msgs.get(job.status, "This analysis has no compliance results."))

    people = (db.query(TrackedPerson).filter(TrackedPerson.video_id == video.id, TrackedPerson.job_id == job.id).all())
    counts = count_people((p.uniform_overall, p.id_status) for p in people)
    modules = _modules(job)
    mv = _loads(job.model_versions, {})
    id_methods = {p.id_method for p in people if p.id_method}
    uni_methods = {p.uniform_method for p in people if p.uniform_method}
    newer = (db.query(AnalysisJob).filter(AnalysisJob.video_id == video.id, AnalysisJob.id > job.id)
             .order_by(AnalysisJob.id.desc()).first())
    uni_mod = next((m for m in modules if m["module"] == "uniform"), None)
    ctx = {
        "job": {"partial": bool(job.partial) or job.status == "completed_partial"}, "modules": modules,
        "id_card": _id_state(mv, id_methods, modules),
        "uniform_method": next(iter(uni_methods)) if len(uni_methods) == 1 else (None if not uni_methods else "mixed"),
        "uniform_evaluated": bool(uni_mod and uni_mod["evaluation_state"] == "EVALUATED"),
        "newer_job": {"id": newer.id, "status": newer.status} if newer else None,
        "degraded": [w[len("DEGRADED: "):] for w in _loads(job.warnings, []) if isinstance(w, str) and w.startswith("DEGRADED: ")],
    }
    warnings = build_warnings(counts, ctx)
    latest_done = latest_done_job(db, video.id)
    return {
        "video_id": video.id, "video_filename": video.original_filename, "job_id": job.id, "status": job.status, "available": True,
        "partial": ctx["job"]["partial"], "attempt": job.attempt, "is_current": bool(latest_done and latest_done.id == job.id),
        "finished_at": _iso(job.finished_at), "processing_seconds": job.processing_seconds,
        **counts,
        "requires_manual_review": bool(counts["uniform_non_compliant"] or counts["id_not_detected"] or counts["inconclusive"]),
        "alert": build_alert(counts, ctx), "notification": build_notification(counts, ctx),
        "warnings": warnings, "limitations": build_limitations(ctx),
        "methods": {"uniform": {"method": ctx["uniform_method"] or "unknown", "evaluated": ctx["uniform_evaluated"]},
                    "id_card": ctx["id_card"],
                    "person_detector": (mv.get("person_detector") or {}).get("model")},
        "modules": modules,
        "newer_job": ctx["newer_job"],
        "message": None,
    }


def person_rows(db: Session, video: Video, job: AnalysisJob, flt: str = "all") -> list:
    """Person-wise rows of ONE run with their exclusive category, evidence link and review state."""
    wanted = FILTERS.get(flt)
    if wanted is None:
        raise ValueError("Unknown filter")
    people = db.query(TrackedPerson).filter(TrackedPerson.video_id == video.id, TrackedPerson.job_id == job.id).all()
    events = {}
    for e in db.query(Event).filter(Event.video_id == video.id, Event.job_id == job.id, Event.category == config.CATEGORY_UNIFORM).order_by(Event.id).all():
        events.setdefault(e.track_ref, e)
    out = []
    for p in sorted(people, key=lambda p: (_track_no(p.track_ref), p.id)):
        cat = classify(p.uniform_overall, p.id_status)
        if cat not in wanted:
            continue
        ev = next((x for x in p.evidence if x.kind == "frame"), None)
        evd = None
        if ev is not None:
            evd = {"url": f"/api/evidence/{ev.id}/file", "timestamp_s": ev.timestamp_s, "time": _fmt(ev.timestamp_s),
                   "file_available": _file_ok(ev.rel_path)}
        event = events.get(p.track_ref)
        flagged = cat in ("both", "uniform_only", "id_only")
        out.append({
            "person_id": p.id, "track_ref": p.track_ref, "category": cat, "category_label": CATEGORY_LABELS[cat],
            "uniform_issue": cat in ("both", "uniform_only"), "id_not_detected": cat in ("both", "id_only"),
            "first_seen_s": p.first_seen_s, "last_seen_s": p.last_seen_s, "first_seen": _fmt(p.first_seen_s), "last_seen": _fmt(p.last_seen_s),
            "shirt_status": p.shirt_status, "trouser_status": p.trouser_status, "uniform_overall": p.uniform_overall, "id_status": p.id_status,
            "uniform_method": p.uniform_method, "id_method": p.id_method, "observations": p.detections,
            "uniform_samples": p.uniform_samples, "id_samples": p.id_samples, "id_confidence": p.id_confidence,
            "evidence": evd, "jump_to_s": evd["timestamp_s"] if evd and evd["timestamp_s"] is not None else p.first_seen_s,
            "event_id": event.id if event else None,
            # review state comes from the uniform review event of this run (if one exists); ID-only people have no
            # event, so a manual check is recommended instead of inventing a review record
            "review_status": event.review_status if event else ("needs_manual_check" if flagged else "not_applicable"),
        })
    return out


def done_jobs_for_report(db: Session, video_id: Optional[int] = None, job_id: Optional[int] = None,
                         include_history: bool = False, limit: int = 25) -> list:
    """Which runs a report covers: one job; or the latest successful run of each (selected) video; or all runs."""
    if job_id:
        j = db.get(AnalysisJob, job_id)
        return [j] if j and j.status in C.DONE_STATES and (not video_id or j.video_id == video_id) else []
    q = db.query(AnalysisJob).filter(AnalysisJob.status.in_(C.DONE_STATES))
    if video_id:
        q = q.filter(AnalysisJob.video_id == video_id)
    if not include_history:
        latest = select(func.max(AnalysisJob.id)).where(AnalysisJob.status.in_(C.DONE_STATES)).group_by(AnalysisJob.video_id)
        q = q.filter(AnalysisJob.id.in_(latest))
    return q.order_by(AnalysisJob.id.desc()).limit(limit).all()


def overview(db: Session, limit: int = 8) -> dict:
    """Dashboard block: latest completed analysis + recent alerts. Newest successful run of each video only."""
    latest_ids = select(func.max(AnalysisJob.id)).where(AnalysisJob.status.in_(C.DONE_STATES)).group_by(AnalysisJob.video_id)
    jobs = db.query(AnalysisJob).filter(AnalysisJob.id.in_(latest_ids)).order_by(AnalysisJob.id.desc()).all()
    pending_total = (db.query(Event).filter(Event.category == config.CATEGORY_UNIFORM, Event.review_status == "pending_review",
                                            Event.job_id.in_(latest_ids)).count())
    partial_total = sum(1 for j in jobs if j.status == "completed_partial")
    items = []
    for j in jobs[: max(limit * 2, limit)]:
        v = db.get(Video, j.video_id)
        if v is None:
            continue
        s = summarize(db, v, j.id)
        pend = db.query(Event).filter(Event.job_id == j.id, Event.category == config.CATEGORY_UNIFORM, Event.review_status == "pending_review").count()
        items.append({"video_id": v.id, "video_filename": v.original_filename, "job_id": j.id, "status": j.status, "partial": s["partial"],
                      "finished_at": s["finished_at"], "total_people": s["total_people"], "uniform_non_compliant": s["uniform_non_compliant"],
                      "id_not_detected": s["id_not_detected"], "both_issues": s["both_issues"], "uncertain": s["uncertain"],
                      "not_assessed": s["not_assessed"], "compliant_both": s["compliant_both"], "pending_reviews": pend,
                      "requires_manual_review": s["requires_manual_review"], "alert_level": s["alert"]["level"],
                      "alert_message": s["alert"]["message"], "id_reliable": s["methods"]["id_card"]["reliable"] if s.get("methods") else False})
    alerts = [i for i in items if i["alert_level"] in ("attention", "caution") or i["partial"]][:limit]
    return {"latest": items[0] if items else None, "recent_alerts": alerts, "analyses_with_results": len(jobs),
            "pending_reviews_total": pending_total, "partial_analyses": partial_total}
