import sys, types, json, threading, io
sys.path.insert(0, "" + __import__("os").environ.get("CAMPUS_ROOT", ".") + "")
sa = types.ModuleType("sqlalchemy"); sa.func = sa.select = sa.or_ = None; sys.modules["sqlalchemy"] = sa
orm = types.ModuleType("sqlalchemy.orm"); orm.Session = object; sys.modules["sqlalchemy.orm"] = orm
m = types.ModuleType("app.models")
for n in ("AnalysisJob", "Event", "TrackedPerson", "Video", "JobModule"): setattr(m, n, type(n, (), {}))
sys.modules["app.models"] = m
from app.services import compliance_summary as cs
from app import constants as C
from http.server import BaseHTTPRequestHandler, ThreadingHTTPServer
from urllib.parse import urlparse, parse_qs
import cv2, numpy as np

STATIC = "" + __import__("os").environ.get("CAMPUS_ROOT", ".") + "/app/static"
STATE = {"job_status": "running", "hits": []}

# 100 tracked people: both 4, uniform_only 8, id_only 4, compliant 70, uncertain 8, not_assessed 6
spec = [(4, C.UNI_BOTH, C.ID_NOT_DETECTED), (8, C.UNI_SHIRT, C.ID_VISIBLE), (4, C.UNI_COMPLIANT, C.ID_NOT_DETECTED),
        (70, C.UNI_COMPLIANT, C.ID_VISIBLE), (8, C.UNI_COMPLIANT, C.ID_UNCERTAIN), (6, C.UNI_NOT_ASSESSED, C.ID_NOT_ASSESSED)]
PEOPLE = [(u, i) for n, u, i in spec for _ in range(n)]
counts = cs.count_people(PEOPLE)
modules = [{"module": k, "requested": True, "ran": True, "state": "LOADED", "result": None, "evaluation_state": None, "detail": ""} for k in cs.COMPLIANCE_MODULES] + \
          [{"module": "fight", "requested": True, "ran": False, "state": "FILE_MISSING", "result": "NOT_ASSESSED", "evaluation_state": None, "detail": ""}]
ctx = {"job": {"partial": True}, "modules": modules, "id_card": {"method": "heuristic", "reliable": False, "note": "heuristic"},
       "uniform_method": "hsv-colour-baseline", "uniform_evaluated": False, "newer_job": None, "degraded": []}
SUMMARY = {"video_id": 1, "video_filename": "gate_cam.mp4", "job_id": 2, "status": "completed_partial", "available": True, "partial": True, "attempt": 1, "is_current": True,
           "finished_at": "2026-11-04T10:00:00Z", "processing_seconds": 12.0, **counts,
           "requires_manual_review": True, "alert": cs.build_alert(counts, ctx), "notification": cs.build_notification(counts, ctx),
           "warnings": cs.build_warnings(counts, ctx), "limitations": cs.build_limitations(ctx),
           "methods": {"uniform": {"method": "hsv-colour-baseline", "evaluated": False}, "id_card": ctx["id_card"], "person_detector": "OpenCV HOG"},
           "modules": modules, "newer_job": None, "message": None}
ROWS = []
for k, (u, i) in enumerate(PEOPLE):
    c = cs.classify(u, i); flagged = c in ("both", "uniform_only", "id_only")
    ROWS.append({"person_id": k + 1, "track_ref": f"T{k+1}", "category": c, "category_label": cs.CATEGORY_LABELS[c], "uniform_issue": c in ("both", "uniform_only"),
                 "id_not_detected": c in ("both", "id_only"), "first_seen_s": k, "last_seen_s": k + 20, "first_seen": cs._fmt(k), "last_seen": cs._fmt(k + 20),
                 "shirt_status": "ok", "trouser_status": "ok", "uniform_overall": u, "id_status": i, "uniform_method": "hsv-colour-baseline", "id_method": "heuristic",
                 "observations": 11, "uniform_samples": 5, "id_samples": 5, "id_confidence": None,
                 "evidence": {"url": "/api/evidence/1/file", "timestamp_s": k + 3, "time": cs._fmt(k + 3), "file_available": True},
                 "jump_to_s": k + 3, "event_id": None, "review_status": "needs_manual_check" if flagged else "not_applicable"})
def job(): return {"id": 2, "video_id": 1, "status": STATE["job_status"], "progress": 0.5, "video_name": "gate_cam.mp4", "partial": True, "attempt": 1, "is_current": True,
                   "warnings": [], "modules": [], "error": None, "processing_seconds": None}
JPG = cv2.imencode(".jpg", np.full((120, 80, 3), 90, np.uint8))[1].tobytes()
def overview():
    L = {"video_id": 1, "video_filename": "gate_cam.mp4", "job_id": 2, "status": "completed_partial", "partial": True, "finished_at": SUMMARY["finished_at"], **{k: counts[k] for k in ("total_people","uniform_non_compliant","id_not_detected","both_issues","uncertain","not_assessed","compliant_both")},
         "pending_reviews": 12, "requires_manual_review": True, "alert_level": SUMMARY["alert"]["level"], "alert_message": SUMMARY["alert"]["message"], "id_reliable": False}
    return {"latest": L, "recent_alerts": [L], "analyses_with_results": 1, "pending_reviews_total": 12, "partial_analyses": 1}
def route(path, q):
    if path == "/api/auth/me": return {"username": "admin", "role": "admin", "login_required": False, "can_shutdown": True}
    if path == "/api/dashboard": return {"models": [], "model_warnings": [], "videos_total": 1, "analyses_completed": 1, "analyses_partial": 1, "analyses_cancelled": 0, "analyses_failed": 0,
        "videos_processing": 0, "pending_review": 12, "confirmed": 0, "dismissed": 0, "inconclusive": 0, "events_in_history": 0, "by_category": {"possible_smoking": 0}, "category_labels": {"possible_smoking": "Possible smoking"},
        "recent_jobs": [job()], "recent_reviews": []}
    if path == "/api/compliance/overview": return overview()
    if path == "/api/jobs": return [job()]
    if path == "/api/videos/1": return {"id": 1, "filename": "gate_cam.mp4", "size_bytes": 1000, "duration_s": 120, "fps": 25, "width": 640, "height": 480, "uploaded_at": "2026-11-04T09:00:00Z",
        "status": STATE["job_status"], "stream_url": "/x.mp4", "has_preview": False, "duplicate_of": [], "jobs": [{**job(), "modules": modules, "created_at": None}]}
    if path == "/api/videos/1/events": return []
    if path == "/api/videos/1/compliance-summary":
        if STATE["job_status"] in ("queued", "running"): return {**SUMMARY, "available": False, "message": "Analysis is running; compliance results will appear when it finishes.", "status": "running"}
        return SUMMARY
    if path == "/api/videos/1/compliance-people":
        f = q.get("filter", ["all"])[0]; return {"video_id": 1, "job_id": 2, "filter": f, "items": [r for r in ROWS if r["category"] in cs.FILTERS[f]]}
    return None
class H(BaseHTTPRequestHandler):
    def log_message(self, *a): pass
    def do_GET(self):
        u = urlparse(self.path); q = parse_qs(u.query)
        if u.path == "/__set":   # test control
            STATE["job_status"] = q["s"][0]; return self._send(b"ok", "text/plain")
        if u.path.startswith("/api/evidence/"): return self._send(JPG, "image/jpeg")
        if u.path.startswith("/api/"):
            STATE["hits"].append(u.path); d = route(u.path, q)
            return self._send(json.dumps(d).encode(), "application/json") if d is not None else self._send(b'{"detail":"nf"}', "application/json", 404)
        p = "/index.html" if u.path == "/" else u.path
        try: data = open(STATIC + p, "rb").read()
        except OSError: return self._send(b"nf", "text/plain", 404)
        self._send(data, {"html": "text/html", "css": "text/css", "js": "application/javascript"}.get(p.rsplit(".", 1)[-1], "application/octet-stream"))
    def do_POST(self):
        u = urlparse(self.path); n = int(self.headers.get("Content-Length") or 0); self.rfile.read(n)
        if u.path == "/api/system/shutdown": STATE["shutdown"] = True; return self._send(b'{"ok":true}', "application/json")
        return self._send(b'{"detail":"nf"}', "application/json", 404)
    def _send(self, b, ct, code=200):
        self.send_response(code); self.send_header("Content-Type", ct); self.send_header("Content-Length", str(len(b))); self.end_headers(); self.wfile.write(b)
ThreadingHTTPServer(("127.0.0.1", 8765), H).serve_forever()
