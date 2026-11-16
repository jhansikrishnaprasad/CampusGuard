"""Report data, CSV and PDF generation - everything comes from stored database records."""
from __future__ import annotations
import csv
import io
from collections import Counter
from datetime import date, datetime, timedelta, timezone
from typing import Optional
from xml.sax.saxutils import escape
from sqlalchemy import func
from sqlalchemy.orm import Session
from .. import config
from .. import constants as C
from ..models import AnalysisJob, Event, JobModule, TrackedPerson, Video
from .runs import current_run_filter

REVIEW_LABELS = {"pending_review": "Pending review", "confirmed": "Confirmed", "dismissed": "Dismissed",
                 "inconclusive": "Inconclusive"}


def fmt_ts(t: float) -> str:
    t = int(t or 0)
    return f"{t // 3600:02d}:{(t % 3600) // 60:02d}:{t % 60:02d}"


def event_query(db: Session, date_from: Optional[date] = None, date_to: Optional[date] = None,
                video_id: Optional[int] = None, category: Optional[str] = None,
                review_status: Optional[str] = None, q: Optional[str] = None,
                include_history: bool = False, job_id: Optional[int] = None):
    qry = db.query(Event).join(Video, Video.id == Event.video_id)
    if job_id:                       # one specific processing run
        qry = qry.filter(Event.job_id == job_id)
    elif not include_history:        # default: current (latest successful) run of every video
        qry = qry.filter(current_run_filter(Event.job_id))
    if date_from:
        qry = qry.filter(Event.created_at >= datetime.combine(date_from, datetime.min.time()))
    if date_to:
        qry = qry.filter(Event.created_at < datetime.combine(date_to + timedelta(days=1), datetime.min.time()))
    if video_id:
        qry = qry.filter(Event.video_id == video_id)
    if category:
        qry = qry.filter(Event.category == category)
    if review_status:
        qry = qry.filter(Event.review_status == review_status)
    if q:
        like = f"%{q}%"
        qry = qry.filter((Video.original_filename.like(like)) | (Event.track_ref.like(like)) | (Event.review_notes.like(like)))
    return qry.order_by(Event.id.desc())


def summary(db: Session, **flt) -> dict:
    events = event_query(db, **flt).all()
    vids = {e.video_id for e in events}
    cats = Counter(e.category for e in events)
    stat = Counter(e.review_status for e in events)
    auto = Counter(e.automated_status for e in events)
    by_day = Counter(e.created_at.date().isoformat() for e in events)
    # uniform / ID summary from tracked people of the same (filtered) videos
    pq = db.query(TrackedPerson)
    if flt.get("video_id"):
        pq = pq.filter(TrackedPerson.video_id == flt["video_id"])
    if flt.get("job_id"):
        pq = pq.filter(TrackedPerson.job_id == flt["job_id"])
    elif not flt.get("include_history"):
        pq = pq.filter(current_run_filter(TrackedPerson.job_id))
    if flt.get("date_from") or flt.get("date_to"):   # people have no timestamp: use the finish time of their run
        pq = pq.join(AnalysisJob, AnalysisJob.id == TrackedPerson.job_id)
        if flt.get("date_from"):
            pq = pq.filter(AnalysisJob.finished_at >= datetime.combine(flt["date_from"], datetime.min.time()))
        if flt.get("date_to"):
            pq = pq.filter(AnalysisJob.finished_at < datetime.combine(flt["date_to"] + timedelta(days=1), datetime.min.time()))
    people = pq.all()
    modules = module_summary(db, **{k: flt.get(k) for k in ("date_from", "date_to", "video_id", "include_history", "job_id")})
    return {
        "total_events": len(events),
        "by_category": dict(cats),
        "by_review_status": {k: stat.get(k, 0) for k in REVIEW_LABELS},
        "by_automated_status": dict(auto),
        "confirmed": stat.get("confirmed", 0), "dismissed": stat.get("dismissed", 0),
        "events_per_day": dict(sorted(by_day.items())),
        "videos_with_events": len(vids),
        "uniform": dict(Counter(p.uniform_overall for p in people)),
        "id_card": dict(Counter(p.id_status for p in people)),
        "people_tracked": len(people),
        "uniform_simple": dict(Counter(C.UNIFORM_SIMPLE.get(p.uniform_overall, p.uniform_overall) for p in people)),
        "modules": modules["modules"], "coverage_warning": modules["warning"],
        "processing": _processing(db),
    }


def module_summary(db: Session, date_from=None, date_to=None, video_id=None, include_history=False, job_id=None) -> dict:
    """How often each AI module actually RAN in the selected analyses (zero findings from a module that did not run
    is NOT evidence that nothing happened)."""
    q = db.query(JobModule).join(AnalysisJob, AnalysisJob.id == JobModule.job_id).filter(
        AnalysisJob.status.in_(["completed", "completed_partial"]))
    if job_id:
        q = q.filter(JobModule.job_id == job_id)
    elif not include_history:
        q = q.filter(AnalysisJob.is_current.is_(True))
    if video_id:
        q = q.filter(AnalysisJob.video_id == video_id)
    if date_from:
        q = q.filter(AnalysisJob.finished_at >= datetime.combine(date_from, datetime.min.time()))
    if date_to:
        q = q.filter(AnalysisJob.finished_at < datetime.combine(date_to + timedelta(days=1), datetime.min.time()))
    mods: dict = {}
    for m in q.all():
        d = mods.setdefault(m.module, {"runs": 0, "ran": 0, "not_run": 0, "evaluation": m.evaluation_state})
        d["runs"] += 1
        d["ran" if m.ran else "not_run"] += 1
    gaps = [f"{k} did not run in {v['not_run']} of {v['runs']} analyses" for k, v in sorted(mods.items()) if v["not_run"]]
    unev = [k for k, v in sorted(mods.items()) if v["ran"] and v["evaluation"] != "EVALUATED" and k in ("fight", "smoking")]
    warn = None
    if gaps or unev:
        warn = ("; ".join(gaps) + ("." if gaps else "") + (" Modules that ran without a recorded evaluation: " + ", ".join(unev) + "." if unev else "")
                + " A count of zero findings does NOT mean no incident occurred for modules that did not run or are unvalidated.")
    return {"modules": mods, "warning": warn}


def _processing(db: Session) -> dict:
    jobs = db.query(AnalysisJob).filter(AnalysisJob.status.in_(["completed", "completed_partial"]),
                                        AnalysisJob.processing_seconds.isnot(None)).all()
    out = {"completed_jobs": len(jobs), "partial_jobs": sum(1 for j in jobs if j.status == "completed_partial"),
           "failed_jobs": db.query(AnalysisJob).filter(AnalysisJob.status == "failed").count(),
           "cancelled_jobs": db.query(AnalysisJob).filter(AnalysisJob.status == "cancelled").count(),
           "avg_seconds_per_footage_minute": None}
    tot_s = sum(j.processing_seconds for j in jobs)
    tot_m = sum(j.video.duration_s for j in jobs) / 60
    if tot_m > 0:
        out["avg_seconds_per_footage_minute"] = round(tot_s / tot_m, 2)
    return out


def event_row(e: Event) -> dict:
    return {
        "event_id": e.id, "video": e.video.original_filename, "category": config.CATEGORY_LABELS.get(e.category, e.category),
        "start": fmt_ts(e.start_s), "end": fmt_ts(e.end_s), "track_ref": e.track_ref or "",
        "confidence": "" if e.confidence is None else f"{e.confidence:.2f}",
        "model": f"{e.model_name} {e.model_version}", "predicted_class": e.predicted_class or "",
        "automated_status": e.automated_status,
        "review_status": REVIEW_LABELS.get(e.review_status, e.review_status), "review_notes": e.review_notes or "",
        "reviewed_by": e.reviewed_by or "", "reviewed_at_utc": e.reviewed_at.strftime("%Y-%m-%d %H:%M") if e.reviewed_at else "",
        "detected_at_utc": e.created_at.strftime("%Y-%m-%d %H:%M"),
    }


def to_csv(db: Session, **flt) -> bytes:
    rows = [event_row(e) for e in event_query(db, **flt).all()]
    buf = io.StringIO()
    cols = ["event_id", "video", "category", "start", "end", "track_ref", "confidence", "model", "predicted_class",
            "automated_status", "review_status", "review_notes", "reviewed_by", "reviewed_at_utc", "detected_at_utc"]
    w = csv.DictWriter(buf, fieldnames=cols)
    w.writeheader()
    for r in rows:
        # neutralise spreadsheet formula injection
        w.writerow({k: ("'" + v if isinstance(v, str) and v and v[0] in "=+-@\t\r" else v) for k, v in r.items()})
    return ("\ufeff" + buf.getvalue()).encode("utf-8")


PEOPLE_CSV_COLS = ["video_id", "video", "job_id", "run_status", "track_ref_temporary", "category", "possible_uniform_noncompliance",
                   "id_card_not_detected", "uniform_overall", "shirt", "trouser", "id_status", "uniform_method", "id_method",
                   "observations", "uniform_samples", "id_samples", "first_seen", "last_seen", "evidence_time", "review_status",
                   "review_event_id", "note"]


def _safe(v):
    """Neutralise spreadsheet formula injection (same rule as the event CSV)."""
    return "'" + v if isinstance(v, str) and v and v[0] in "=+-@\t\r" else v


def to_people_csv(db: Session, video_id: Optional[int] = None, job_id: Optional[int] = None, include_history: bool = False) -> bytes:
    """Person-level compliance rows (one row per tracked person per analysis run) from stored results only."""
    from . import compliance_summary as cs
    buf = io.StringIO()
    w = csv.DictWriter(buf, fieldnames=PEOPLE_CSV_COLS)
    w.writeheader()
    for job in cs.done_jobs_for_report(db, video_id, job_id, include_history, limit=200):
        v = db.get(Video, job.video_id)
        if v is None:
            continue
        for r in cs.person_rows(db, v, job, "all"):
            w.writerow({k: _safe(x) for k, x in {
                "video_id": v.id, "video": v.original_filename, "job_id": job.id, "run_status": job.status,
                "track_ref_temporary": r["track_ref"], "category": r["category_label"],
                "possible_uniform_noncompliance": "yes" if r["uniform_issue"] else "no",
                "id_card_not_detected": "yes" if r["id_not_detected"] else "no",
                "uniform_overall": r["uniform_overall"], "shirt": r["shirt_status"], "trouser": r["trouser_status"],
                "id_status": r["id_status"], "uniform_method": r["uniform_method"] or "", "id_method": r["id_method"] or "",
                "observations": r["observations"], "uniform_samples": r["uniform_samples"], "id_samples": r["id_samples"],
                "first_seen": r["first_seen"], "last_seen": r["last_seen"],
                "evidence_time": r["evidence"]["time"] if r["evidence"] else "", "review_status": r["review_status"],
                "review_event_id": r["event_id"] or "",
                "note": "Temporary tracking reference, not an identity. 'ID card not detected' is not proof that no card is worn."}.items()})
    return ("\ufeff" + buf.getvalue()).encode("utf-8")


def _compliance_flowables(db: Session, flt: dict, st, tbl, mm) -> list:
    """PDF section 'VIDEO-LEVEL UNIFORM AND ID-CARD COMPLIANCE SUMMARY' (real stored results, one block per analysis run)."""
    from reportlab.platypus import Paragraph, Spacer
    from . import compliance_summary as cs
    out = [Paragraph("VIDEO-LEVEL UNIFORM AND ID-CARD COMPLIANCE SUMMARY", st["Heading2"]),
           Paragraph("Person-level counts of tracked people (not events or frames). The first three figures overlap: people with both issues "
                     "are included in the uniform count AND in the ID-card count, so do not add them together.", st["Normal"])]
    jobs = cs.done_jobs_for_report(db, flt.get("video_id"), flt.get("job_id"), bool(flt.get("include_history")), limit=15)
    if not jobs:
        out.append(Paragraph("No completed analysis exists in this selection.", st["Normal"]))
        return out
    for job in jobs:
        v = db.get(Video, job.video_id)
        if v is None:
            continue
        s = cs.summarize(db, v, job.id)
        out += [Spacer(1, 6), Paragraph(f"<b>Video:</b> {escape(v.original_filename)} &nbsp; <b>Analysis job:</b> #{job.id} "
                                        f"({escape(job.status)}{', partial' if s['partial'] else ''}, run {job.attempt}"
                                        f"{'' if s['is_current'] else ', earlier run'})", st["Normal"])]
        out.append(tbl([["Measure", "People"],
                        ["Total tracked people", s["total_people"]],
                        ["Possible uniform non-compliance", s["uniform_non_compliant"]],
                        ["ID card not detected (detector returned CARD_NOT_DETECTED)", s["id_not_detected"]],
                        ["Both issues (overlapping subset of the two rows above)", s["both_issues"]],
                        ["Uniform issue only", s["uniform_only"]], ["ID-card issue only", s["id_only"]],
                        ["Apparently compliant in both checks", s["compliant_both"]],
                        ["Uncertain", s["uncertain"]], ["Not assessed (a check could not be performed)", s["not_assessed"]]],
                       [120 * mm, 25 * mm]))
        out.append(Paragraph("<b>" + escape(s["alert"]["message"]) + "</b>", st["Normal"]))
        for wn in s["warnings"]:
            out.append(Paragraph(f"[{escape(wn['level'].upper())}] " + escape(wn["message"]), st["Normal"]))
        out.append(Paragraph("<b>Model limitations:</b> " + escape(" ".join(s["limitations"])), st["Normal"]))
        out.append(Paragraph("<b>Manual review:</b> " + ("RECOMMENDED - review the flagged and inconclusive people listed below against the footage."
                                                          if s["requires_manual_review"] else
                                                          "No flagged or inconclusive people; automated results still do not replace manual verification."), st["Normal"]))
        rows = [r for r in cs.person_rows(db, v, job, "all") if r["category"] != "compliant_both"]
        if rows:
            data = [["Ref", "First", "Last", "Shirt", "Trousers", "Uniform", "ID card", "Methods", "Obs.", "Category", "Review"]]
            for r in rows[:40]:
                data.append([r["track_ref"], r["first_seen"], r["last_seen"], r["shirt_status"], r["trouser_status"], r["uniform_overall"], r["id_status"],
                             Paragraph(escape(f"{r['uniform_method'] or '-'} / {r['id_method'] or '-'}"), st["BodyText"]), r["observations"],
                             Paragraph(escape(r["category_label"]), st["BodyText"]), r["review_status"]])
            out.append(Spacer(1, 3))
            out.append(tbl(data, [12 * mm, 16 * mm, 16 * mm, 20 * mm, 20 * mm, 36 * mm, 30 * mm, 44 * mm, 10 * mm, 30 * mm, 26 * mm]))
            if len(rows) > 40:
                out.append(Paragraph(f"Showing 40 of {len(rows)} flagged/inconclusive people; the full list is in the compliance CSV export.", st["Normal"]))
    return out


def _f(v):
    return "n/a" if v is None else f"{v:.3f}"


def to_pdf(db: Session, filters_desc: dict, models: list | None = None, evaluations: list | None = None, **flt) -> bytes:
    from reportlab.lib import colors
    from reportlab.lib.pagesizes import A4, landscape
    from reportlab.lib.styles import getSampleStyleSheet
    from reportlab.lib.units import mm
    from reportlab.platypus import Paragraph, SimpleDocTemplate, Spacer, Table, TableStyle

    s = summary(db, **flt)
    events = event_query(db, **flt).limit(500).all()
    st = getSampleStyleSheet()
    buf = io.BytesIO()
    doc = SimpleDocTemplate(buf, pagesize=landscape(A4), leftMargin=14 * mm, rightMargin=14 * mm,
                            topMargin=14 * mm, bottomMargin=14 * mm, title="Campus Safety Analytics Report")
    navy = colors.HexColor("#101B35")

    def tbl(data, widths=None, header=True):
        t = Table(data, colWidths=widths, repeatRows=1 if header else 0)
        style = [("FONTSIZE", (0, 0), (-1, -1), 8), ("GRID", (0, 0), (-1, -1), 0.25, colors.lightgrey),
                 ("VALIGN", (0, 0), (-1, -1), "TOP")]
        if header:
            style += [("BACKGROUND", (0, 0), (-1, 0), navy), ("TEXTCOLOR", (0, 0), (-1, 0), colors.white)]
        t.setStyle(TableStyle(style))
        return t

    el = [Paragraph("Campus Safety &amp; Dress-Code Analytics Report", st["Title"]),
          Paragraph(f"Generated: {datetime.now(timezone.utc).strftime('%Y-%m-%d %H:%M UTC')}", st["Normal"]),
          Paragraph("Filters: " + (", ".join(escape(f"{k}={v}") for k, v in filters_desc.items() if v) or "none (all records)"), st["Normal"]),
          Spacer(1, 6),
          Paragraph("<b>Important:</b> AI findings are predictions that require human review. Only events with review "
                    "status <i>Confirmed</i> have been verified by a reviewer. Absence of a detection (e.g. ID card) is not "
                    "proof of absence. Tracking references are temporary and are not identities.", st["Normal"]),
          Spacer(1, 8), Paragraph("Review status", st["Heading2"]),
          tbl([["Status", "Events"]] + [[REVIEW_LABELS[k], v] for k, v in s["by_review_status"].items()] + [["Total", s["total_events"]]],
              [60 * mm, 25 * mm]),
          Paragraph("Events by category", st["Heading2"]),
          tbl([["Category", "Events"]] + ([[config.CATEGORY_LABELS.get(k, k), v] for k, v in s["by_category"].items()] or [["No events", 0]]),
              [80 * mm, 25 * mm]),
          Paragraph("Uniform and ID-card summary (tracked people; baseline models)", st["Heading2"]),
          tbl([["Uniform result", "People"]] + ([[k, v] for k, v in s["uniform"].items()] or [["No data", 0]]), [80 * mm, 25 * mm]),
          Spacer(1, 4),
          tbl([["ID-card visibility", "People"]] + ([[k, v] for k, v in s["id_card"].items()] or [["No data", 0]]), [80 * mm, 25 * mm]),
          Paragraph("<b>Coverage:</b> " + escape(s["coverage_warning"]) if s.get("coverage_warning") else
                    "All requested modules ran in the selected analyses.", st["Normal"]),
          Paragraph("Processing", st["Heading2"]),
          Paragraph(f"Completed analyses: {s['processing']['completed_jobs']} (of which partial - some requested AI modules did "
                    f"not run: {s['processing']['partial_jobs']}); failed: {s['processing']['failed_jobs']}; cancelled: "
                    f"{s['processing']['cancelled_jobs']}. Avg time: {s['processing']['avg_seconds_per_footage_minute'] or 'n/a'} s per footage-minute.", st["Normal"]),
          Paragraph("Model status and limitations", st["Heading2"])]
    if models:
        el.append(tbl([["Module", "State", "Evaluation", "Note"]] + [
            [Paragraph(escape(m["title"]), st["BodyText"]), m["state"], m["evaluation"]["state"],
             Paragraph(escape((m["detail"] or "")[:110]), st["BodyText"])] for m in models], [55 * mm, 35 * mm, 32 * mm, 120 * mm]))
    ev_rows = [e for e in (evaluations or []) if e.get("status", "completed") == "completed"]
    if ev_rows:
        el.append(Spacer(1, 4)); el.append(tbl([["Evaluated model", "Dataset", "Precision", "Recall", "F1"]] + [
            [escape(str(e["model_name"])), escape(str(e["dataset_name"])), _f(e["precision"]), _f(e["recall"]), _f(e["f1"])]
            for e in ev_rows[:15]], [70 * mm, 70 * mm, 30 * mm, 30 * mm, 30 * mm]))
    else:
        el.append(Paragraph("No labelled evaluation has been recorded: no accuracy claim is made for any module.", st["Normal"]))
    el[5:5] = _compliance_flowables(db, flt, st, tbl, mm) + [Spacer(1, 8)]   # prominent: right after the disclaimer
    el.append(Paragraph(f"Events (showing {len(events)} of {s['total_events']})", st["Heading2"]))
    data = [["ID", "Video", "Category", "Start", "End", "Track", "Conf.", "Auto", "Review", "Notes"]]
    for e in events:
        r = event_row(e)
        data.append([r["event_id"], Paragraph(escape(r["video"][:40]), st["BodyText"]), Paragraph(escape(r["category"]), st["BodyText"]), r["start"], r["end"],
                     r["track_ref"], r["confidence"], r["automated_status"], r["review_status"],
                     Paragraph(escape((r["review_notes"] or "")[:80]), st["BodyText"])])
    el.append(tbl(data, [10 * mm, 50 * mm, 45 * mm, 20 * mm, 20 * mm, 14 * mm, 13 * mm, 20 * mm, 25 * mm, 45 * mm]))
    doc.build(el)
    return buf.getvalue()
