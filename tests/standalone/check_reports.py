import sys, types, io, csv
import pathlib; sys.path.insert(0, str(pathlib.Path(__file__).resolve().parents[2]))
sa = types.ModuleType("sqlalchemy"); sa.func = None; sa.select = None; sa.or_ = None; sys.modules["sqlalchemy"] = sa
orm = types.ModuleType("sqlalchemy.orm"); orm.Session = object; sys.modules["sqlalchemy.orm"] = orm
models = types.ModuleType("app.models")
class V:  # fake video
    id = 7; original_filename = "=cctv <gate> & more.mp4"
for n in ("AnalysisJob", "Event", "JobModule", "TrackedPerson"): setattr(models, n, type(n, (), {}))
models.Video = V; sys.modules["app.models"] = models
from app.services import compliance_summary as cs
from app.services import reporting
from app import constants as C
class J: id = 3; video_id = 7; status = "completed_partial"; attempt = 2
class DB:
    def get(self, model, i): return V()
rows_in = [("T1", C.UNI_SHIRT, C.ID_NOT_DETECTED), ("T2", C.UNI_COMPLIANT, C.ID_UNCERTAIN), ("T3", C.UNI_COMPLIANT, C.ID_VISIBLE), ("T4", C.UNI_NOT_ASSESSED, C.ID_NOT_ASSESSED)]
counts = cs.count_people((u, i) for _, u, i in rows_in)
ctx = {"job": {"partial": True}, "modules": [{"module": "fight", "requested": True, "ran": False}], "id_card": {"method": "heuristic", "reliable": False}, "uniform_method": "hsv-colour-baseline", "degraded": []}
summ = {**counts, "partial": True, "is_current": True, "alert": cs.build_alert(counts, ctx), "warnings": cs.build_warnings(counts, ctx),
        "limitations": cs.build_limitations(ctx), "requires_manual_review": True}
people = [dict(person_id=i, track_ref=r, category=cs.classify(u, d), category_label=cs.CATEGORY_LABELS[cs.classify(u, d)], uniform_issue=u in C.UNIFORM_MISMATCH,
               id_not_detected=d == C.ID_NOT_DETECTED, first_seen="00:00:01", last_seen="00:00:09", shirt_status="ok", trouser_status="ok",
               uniform_overall=u, id_status=d, uniform_method="hsv-colour-baseline", id_method="heuristic", observations=9, uniform_samples=4, id_samples=4,
               evidence={"time": "00:00:03"}, event_id=None, review_status="needs_manual_check") for i, (r, u, d) in enumerate(rows_in)]
cs.done_jobs_for_report = lambda *a, **k: [J()]
cs.summarize = lambda db, v, jid: summ
cs.person_rows = lambda db, v, j, f="all": [p for p in people if f == "all" or p["category"] == f]
# CSV
data = reporting.to_people_csv(DB(), 7).decode("utf-8-sig")
rd = list(csv.DictReader(io.StringIO(data)))
assert len(rd) == 4 and rd[0]["video"].startswith("'=") and rd[0]["possible_uniform_noncompliance"] == "yes" and rd[0]["id_card_not_detected"] == "yes"
assert rd[1]["id_card_not_detected"] == "no" and rd[1]["id_status"] == "UNCERTAIN"
# PDF flowables rendered through reportlab
from reportlab.lib import colors; from reportlab.lib.pagesizes import A4, landscape; from reportlab.lib.styles import getSampleStyleSheet
from reportlab.lib.units import mm; from reportlab.platypus import SimpleDocTemplate, Table, TableStyle
def tbl(data, widths=None, header=True):
    t = Table(data, colWidths=widths, repeatRows=1); t.setStyle(TableStyle([("FONTSIZE",(0,0),(-1,-1),8),("GRID",(0,0),(-1,-1),.25,colors.lightgrey)])); return t
fl = reporting._compliance_flowables(DB(), {"video_id": 7, "job_id": None, "include_history": False}, getSampleStyleSheet(), tbl, mm)
buf = io.BytesIO(); SimpleDocTemplate(buf, pagesize=landscape(A4)).build(fl)
assert buf.getvalue().startswith(b"%PDF") and len(buf.getvalue()) > 2000
open(__import__("tempfile").gettempdir() + "/compliance_section_demo.pdf", "wb").write(buf.getvalue())
print("CSV + PDF section OK;", len(fl), "flowables")
