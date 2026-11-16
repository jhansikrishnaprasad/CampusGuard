"""Video-level uniform / ID-card compliance summary, warnings, reports and notification contract.

Needs the full requirements (run with .\\run_tests.ps1). Uses a temporary database (see conftest.py).
Most tests seed `tracked_people` rows directly (fast, exact control of the status mix); one test drives the REAL
pipeline with injected detectors to prove the default ID heuristic can never produce CARD_NOT_DETECTED.
"""
import csv
import io
import itertools
import json
import os
import shutil
import sqlite3
import subprocess
import time
from pathlib import Path

import pytest
from fastapi.testclient import TestClient

from app import config, constants as C, migrations
from app.database import SessionLocal
from app.main import app
from app.models import AnalysisJob, Event, Evidence, JobModule, Review, TrackedPerson, Video, utcnow
from app.services import compliance_summary as cs
from tests.helpers import make_video
from tests.legacy_schema import build_v1

PW = "test-password-123"
ROOT = Path(__file__).resolve().parent.parent
_n = itertools.count(1)

U_OK, U_SHIRT, U_TROUSER, U_BOTH, U_UNC, U_NA = (C.UNI_COMPLIANT, C.UNI_SHIRT, C.UNI_TROUSER, C.UNI_BOTH, C.UNI_UNCERTAIN, C.UNI_NOT_ASSESSED)
I_VIS, I_NOT, I_UNC, I_NA = C.ID_VISIBLE, C.ID_NOT_DETECTED, C.ID_UNCERTAIN, C.ID_NOT_ASSESSED


@pytest.fixture(scope="module")
def client():
    with TestClient(app) as c:
        assert c.post("/api/auth/login", json={"username": "admin", "password": PW}).status_code == 200
        yield c


def seed(spec, *, status="completed", partial=False, video=None, id_method="heuristic", modules=None, attempt=1, name=None):
    """spec = [(count, uniform_overall, id_status), ...] -> (video_id, job_id). Creates a finished run with those people."""
    i = next(_n)
    with SessionLocal() as db:
        if video is None:
            v = Video(original_filename=name or f"cmp_{i}.mp4", stored_name=f"cmp_{i}_{os.getpid()}.mp4", size_bytes=1, duration_s=60, fps=25,
                      width=640, height=480, status=status)
            db.add(v); db.commit(); vid = v.id
        else:
            vid = video
        mv = {"id_card": {"enabled": id_method != "disabled", "method": id_method, "note": "test"}, "person_detector": {"model": "fake"}}
        job = AnalysisJob(video_id=vid, status=status, attempt=attempt, partial=partial, finished_at=utcnow(), progress=1.0,
                          model_versions=json.dumps(mv), warnings=json.dumps([]))
        db.add(job); db.flush()
        if attempt > 1 or video is not None:   # newest successful run becomes the current one (as the worker does)
            db.query(AnalysisJob).filter(AnalysisJob.video_id == vid, AnalysisJob.id != job.id).update({"is_current": False})
        for m in (modules if modules is not None else [("person_detection", True, True), ("tracking", True, True), ("uniform", True, True),
                                                       ("id_card", True, True), ("fight", True, not partial), ("smoking", True, not partial)]):
            db.add(JobModule(job_id=job.id, module=m[0], requested=m[1], ran=m[2], state="LOADED" if m[2] else "FILE_MISSING",
                             evaluation_state="NOT_EVALUATED"))
        k = 0
        for count, uo, ids in spec:
            for _ in range(count):
                k += 1
                db.add(TrackedPerson(video_id=vid, job_id=job.id, track_ref=f"T{k}", first_seen_s=k, last_seen_s=k + 5, detections=7,
                                     uniform_overall=uo, id_status=ids, uniform_samples=4, id_samples=4, id_method=id_method,
                                     uniform_method="hsv-colour-baseline", shirt_status="ok", trouser_status="ok"))
        db.commit()
        return vid, job.id


def summary(client, vid, job_id=None):
    r = client.get(f"/api/videos/{vid}/compliance-summary" + (f"?job_id={job_id}" if job_id else ""))
    assert r.status_code == 200, r.text
    return r.json()


def exclusive_total(s):
    return s["uniform_only"] + s["id_only"] + s["both_issues"] + s["compliant_both"] + s["uncertain"] + s["not_assessed"]


# ------------------------------------------------------------------ pure logic (no web stack involved)
def test_every_status_combination_lands_in_exactly_one_category():
    for uo, ids in itertools.product(C.UNIFORM_STATES, C.ID_STATES):
        assert cs.classify(uo, ids) in cs.CATEGORIES
        c = cs.count_people([(uo, ids)])
        assert exclusive_total(c) == 1 == c["total_people"]


def test_uncertain_id_is_never_promoted_to_not_detected():
    for uo in C.UNIFORM_STATES:
        assert cs.classify(uo, I_UNC) not in ("id_only", "both")
    assert cs.count_people([(U_OK, I_UNC)] * 5)["id_not_detected"] == 0


def test_overlap_arithmetic():
    c = cs.count_people([(U_BOTH, I_NOT)] * 4 + [(U_SHIRT, I_VIS)] * 8 + [(U_OK, I_NOT)] * 4 + [(U_OK, I_VIS)] * 70 + [(U_OK, I_UNC)] * 8 + [(U_NA, I_NA)] * 6)
    assert (c["total_people"], c["uniform_non_compliant"], c["id_not_detected"], c["both_issues"]) == (100, 12, 8, 4)
    assert (c["uniform_only"], c["id_only"], c["compliant_both"], c["uncertain"], c["not_assessed"]) == (8, 4, 70, 8, 6)


# ------------------------------------------------------------------ TEST 1-5: counting through the real API
def test_1_uniform_mismatch_only(client):
    vid, jid = seed([(2, U_SHIRT, I_VIS), (8, U_OK, I_VIS)])
    s = summary(client, vid)
    assert (s["total_people"], s["uniform_non_compliant"], s["id_not_detected"], s["both_issues"]) == (10, 2, 0, 0)
    assert s["uniform_only"] == 2 and s["compliant_both"] == 8 and exclusive_total(s) == 10
    assert s["job_id"] == jid and s["video_id"] == vid and s["alert"]["level"] == "attention"


def test_2_id_card_issue_only(client):
    vid, _ = seed([(3, U_OK, I_NOT), (7, U_OK, I_VIS)])
    s = summary(client, vid)
    assert (s["uniform_non_compliant"], s["id_not_detected"], s["both_issues"], s["id_only"]) == (0, 3, 0, 3)
    assert exclusive_total(s) == 10


def test_3_both_issues(client):
    vid, _ = seed([(1, U_BOTH, I_NOT), (1, U_TROUSER, I_VIS), (2, U_OK, I_NOT), (6, U_OK, I_VIS)])
    s = summary(client, vid)
    assert (s["uniform_non_compliant"], s["id_not_detected"], s["both_issues"], s["uniform_only"], s["id_only"]) == (2, 3, 1, 1, 2)
    assert exclusive_total(s) == s["total_people"] == 10
    assert s["notification"]["lines"][:3] == ["2 people have possible uniform mismatches.", "3 people have ID cards not detected.", "1 person has both issues."]


def test_4_uncertain_id_detection_is_explained_and_not_counted(client):
    vid, _ = seed([(4, U_OK, I_UNC), (6, U_OK, I_VIS)])
    s = summary(client, vid)
    assert s["id_not_detected"] == 0 and s["uncertain"] == 4 and s["compliant_both"] == 6
    codes = {w["code"]: w["message"] for w in s["warnings"]}
    assert "id_uncertain" in codes and "NOT counted" in codes["id_uncertain"]
    assert cs.ID_UNRELIABLE_MESSAGE in codes["id_unreliable"]            # heuristic => honest limitation message
    assert s["alert"]["level"] == "caution" and "Do not treat them as compliant" in s["alert"]["message"]
    assert s["requires_manual_review"] is True


def test_4b_custom_detector_has_no_unreliable_warning(client):
    vid, _ = seed([(5, U_OK, I_VIS)], id_method="custom_yolo")
    s = summary(client, vid)
    assert "id_unreliable" not in {w["code"] for w in s["warnings"]} and s["methods"]["id_card"]["reliable"] is True
    assert s["alert"]["level"] == "clear"                                 # all conclusive + compliant


def test_5_empty_video(client):
    vid, _ = seed([])
    s = summary(client, vid)
    assert s["available"] is True and s["total_people"] == 0 and exclusive_total(s) == 0
    assert all(s[k] == 0 for k in ("uniform_non_compliant", "id_not_detected", "both_issues", "uncertain", "not_assessed", "compliant_both"))
    assert s["alert"]["level"] == "none" and "No people were tracked" in s["alert"]["message"]
    assert any(w["code"] == "no_people" for w in s["warnings"])
    assert client.get(f"/api/videos/{vid}/compliance-people").json()["items"] == []


def test_no_analysis_yet_and_failed_and_running(client, tmp_path):
    p = make_video(tmp_path / "n.mp4")
    vid = client.post("/api/videos", files={"file": ("n.mp4", p.read_bytes(), "video/mp4")}, data={"start_analysis": "false"}).json()["id"]
    s = summary(client, vid)
    assert s["status"] == "not_analysed" and s["available"] is False and s["total_people"] == 0 and "not been analysed" in s["message"]
    with SessionLocal() as db:
        db.add(AnalysisJob(video_id=vid, status="failed", error="boom")); db.commit()
    s = summary(client, vid)
    assert s["status"] == "failed" and s["available"] is False and "failed" in s["message"]


# ------------------------------------------------------------------ TEST 6: reprocessing / current vs historical
def test_6_reprocessing_uses_latest_successful_run_and_keeps_history(client):
    vid, j1 = seed([(5, U_SHIRT, I_VIS), (5, U_OK, I_VIS)], name="reproc.mp4")
    with SessionLocal() as db:   # a human review on run 1 must survive
        e = Event(video_id=vid, job_id=j1, track_ref="T1", category=config.CATEGORY_UNIFORM, start_s=1, end_s=5, model_name="m",
                  model_version="1", dedupe_key=f"cmp-ev-{vid}", predicted_class=U_SHIRT)
        db.add(e); db.flush(); db.add(Review(event_id=e.id, reviewer="admin", decision="confirmed", previous_status="pending_review"))
        e.review_status = "confirmed"; db.commit(); eid = e.id
    _, j2 = seed([(2, U_BOTH, I_NOT), (8, U_OK, I_VIS)], video=vid, attempt=2)
    cur = summary(client, vid)
    assert cur["job_id"] == j2 and cur["is_current"] is True and cur["total_people"] == 10        # NOT 20: no double counting
    assert (cur["uniform_non_compliant"], cur["id_not_detected"], cur["both_issues"]) == (2, 2, 2)
    old = summary(client, vid, j1)
    assert old["job_id"] == j1 and old["is_current"] is False and (old["total_people"], old["uniform_non_compliant"]) == (10, 5)   # history intact
    assert {p["track_ref"] for p in client.get(f"/api/videos/{vid}/compliance-people").json()["items"]} == {f"T{k}" for k in range(1, 11)}
    rows_old = client.get(f"/api/videos/{vid}/compliance-people?job_id={j1}&filter=uniform_issue").json()["items"]
    assert len(rows_old) == 5 and rows_old[0]["review_status"] == "confirmed" and rows_old[0]["event_id"] == eid   # review linked, not deleted
    with SessionLocal() as db:
        assert db.query(Review).filter(Review.event_id == eid).count() == 1 and db.query(TrackedPerson).filter(TrackedPerson.video_id == vid).count() == 20


def test_6b_newer_failed_run_does_not_replace_results_and_running_run_is_announced(client):
    vid, j1 = seed([(3, U_OK, I_VIS)])
    with SessionLocal() as db:
        db.add(AnalysisJob(video_id=vid, status="running", attempt=2)); db.commit()
    s = summary(client, vid)
    assert s["job_id"] == j1 and s["total_people"] == 3 and any(w["code"] == "reprocessing" for w in s["warnings"])


# ------------------------------------------------------------------ TEST 7: partial analysis
def test_7_partial_analysis_is_declared_and_counts_remain(client):
    vid, _ = seed([(2, U_SHIRT, I_VIS), (3, U_OK, I_VIS)], status="completed_partial", partial=True)
    s = summary(client, vid)
    assert s["status"] == "completed_partial" and s["partial"] is True and s["available"] is True
    assert s["uniform_non_compliant"] == 2 and s["total_people"] == 5
    assert {m["module"] for m in s["modules"] if m["requested"] and not m["ran"]} == {"fight", "smoking"}
    assert any(w["code"] == "partial_other_modules" for w in s["warnings"])
    assert s["notification"]["title"] == "VIDEO ANALYSIS COMPLETED (PARTIAL)"


def test_7b_missing_compliance_module_is_never_shown_as_compliant(client):
    mods = [("person_detection", True, True), ("tracking", True, True), ("uniform", True, True), ("id_card", True, False)]
    vid, _ = seed([(4, U_OK, I_NA)], status="completed_partial", partial=True, modules=mods, id_method="heuristic")
    s = summary(client, vid)
    assert s["compliant_both"] == 0 and s["not_assessed"] == 4
    assert any(w["code"] == "compliance_modules_missing" for w in s["warnings"])
    assert s["alert"]["level"] == "caution" and "compliant" not in s["alert"]["title"].lower()


def test_7c_disabled_id_module(client):
    mods = [("person_detection", True, True), ("tracking", True, True), ("uniform", True, True), ("id_card", False, False)]
    vid, _ = seed([(3, U_OK, I_NA)], modules=mods, id_method="disabled")
    s = summary(client, vid)
    assert any(w["code"] == "id_disabled" for w in s["warnings"]) and s["id_not_detected"] == 0 and s["compliant_both"] == 0


# ------------------------------------------------------------------ person rows, filters, evidence, review linkage
def test_person_rows_filters_and_evidence(client):
    vid, jid = seed([(1, U_BOTH, I_NOT), (2, U_SHIRT, I_VIS), (1, U_OK, I_NOT), (3, U_OK, I_VIS), (2, U_OK, I_UNC), (1, U_NA, I_NA)])
    with SessionLocal() as db:
        p = db.query(TrackedPerson).filter(TrackedPerson.job_id == jid, TrackedPerson.track_ref == "T1").one()
        db.add(Evidence(video_id=vid, person_id=p.id, kind="frame", rel_path="../../etc/passwd", timestamp_s=3.2))   # hostile path
        e = Event(video_id=vid, job_id=jid, track_ref="T1", category=config.CATEGORY_UNIFORM, start_s=0, end_s=3, model_name="m", model_version="1",
                  dedupe_key=f"cmp-pr-{vid}", predicted_class=U_BOTH)
        db.add(e); db.commit()
    s = summary(client, vid)
    want = {"all": 10, "uniform_issue": s["uniform_non_compliant"], "id_issue": s["id_not_detected"], "both": 1, "compliant": 3, "uncertain": 2, "not_assessed": 1}
    for f, n in want.items():
        got = client.get(f"/api/videos/{vid}/compliance-people?filter={f}").json()["items"]
        assert len(got) == n, (f, len(got), n)
    allrows = client.get(f"/api/videos/{vid}/compliance-people").json()["items"]
    assert sum(r["category"] == "uncertain" for r in allrows) == 2
    t1 = next(r for r in allrows if r["track_ref"] == "T1")
    assert t1["review_status"] == "pending_review" and t1["event_id"] and t1["evidence"]["file_available"] is False and t1["jump_to_s"] == 3.2
    assert t1["evidence"]["url"].startswith("/api/evidence/") and "passwd" not in json.dumps(allrows)    # no filesystem path exposed
    assert next(r for r in allrows if r["category"] == "id_only")["review_status"] == "needs_manual_check"
    assert client.get(f"/api/videos/{vid}/compliance-people?filter=nonsense").status_code == 422


# ------------------------------------------------------------------ reports
def test_people_csv_and_pdf_use_stored_results(client):
    vid, jid = seed([(1, U_BOTH, I_NOT), (2, U_OK, I_UNC), (2, U_OK, I_VIS)], name="=report test.mp4")
    r = client.get(f"/api/reports/compliance.csv?video_id={vid}")
    assert r.status_code == 200 and r.headers["content-type"].startswith("text/csv")
    rows = list(csv.DictReader(io.StringIO(r.text.lstrip("\ufeff"))))
    assert len(rows) == 5 and {x["job_id"] for x in rows} == {str(jid)}
    assert rows[0]["video"].startswith("'=")                                                   # formula injection neutralised
    assert sum(x["id_card_not_detected"] == "yes" for x in rows) == 1 and sum(x["id_status"] == "UNCERTAIN" for x in rows) == 2
    assert all(x["track_ref_temporary"].startswith("T") for x in rows)
    pdf = client.get(f"/api/reports/report.pdf?video_id={vid}")
    assert pdf.status_code == 200 and pdf.content.startswith(b"%PDF")
    assert client.get("/api/reports/events.csv").status_code == 200                                  # existing event CSV unchanged
    assert client.get("/api/reports/report.pdf").content.startswith(b"%PDF")


def test_overview_matches_latest_stored_analysis(client):
    vid, jid = seed([(3, U_SHIRT, I_NOT), (7, U_OK, I_VIS)], name="newest_overview.mp4")
    o = client.get("/api/compliance/overview").json()
    assert o["latest"]["job_id"] == jid and o["latest"]["video_id"] == vid and o["latest"]["total_people"] == 10
    assert (o["latest"]["uniform_non_compliant"], o["latest"]["id_not_detected"], o["latest"]["both_issues"]) == (3, 3, 3)
    assert any(a["job_id"] == jid for a in o["recent_alerts"]) and "pending_reviews_total" in o and "partial_analyses" in o
    assert client.get("/api/dashboard").status_code == 200 and "by_category" in client.get("/api/dashboard").json()   # old dashboard intact


# ------------------------------------------------------------------ TEST 8: notification contract (server side)
def test_8_notification_payload_comes_from_stored_numbers_and_is_stable(client):
    vid, jid = seed([(4, U_BOTH, I_NOT), (8, U_SHIRT, I_VIS), (88, U_OK, I_VIS)])
    a, b = summary(client, vid, jid), summary(client, vid, jid)
    assert a["notification"] == b["notification"] and a["finished_at"] == b["finished_at"]       # reading never creates events
    assert a["notification"]["title"] == "VIDEO ANALYSIS COMPLETED"
    assert a["notification"]["lines"][0] == "12 people have possible uniform mismatches." and a["notification"]["link_label"].startswith("Open compliance report")
    with SessionLocal() as db:   # polling the summary wrote nothing
        assert db.query(AnalysisJob).filter(AnalysisJob.video_id == vid).count() == 1


@pytest.mark.skipif(shutil.which("node") is None, reason="Node.js not installed (only needed for the front-end logic test)")
def test_8b_frontend_notification_state_machine():
    """Runs the REAL detectTransitions() from app.js: no duplicate toasts while polling, none after refresh/navigation, one after reprocess."""
    r = subprocess.run(["node", str(ROOT / "tests" / "frontend_notifications.test.js")], cwd=ROOT, capture_output=True, text=True, timeout=60)
    assert r.returncode == 0, r.stdout + r.stderr


# ------------------------------------------------------------------ TEST 9: migration + persistence
def test_9_v1_database_migrates_without_loss_and_gets_previous_status_column(tmp_path):
    db = tmp_path / "old.db"; build_v1(db)
    info = migrations.migrate(db, tmp_path / "bk")
    assert info["migrated"] and info["to"] == migrations.CURRENT_VERSION
    con = sqlite3.connect(db)
    try:
        assert con.execute("SELECT COUNT(*) FROM videos").fetchone()[0] == 2 and con.execute("SELECT COUNT(*) FROM reviews").fetchone()[0] == 1
        assert con.execute("SELECT COUNT(*) FROM tracked_people").fetchone()[0] == 3
        assert "previous_status" in {r[1] for r in con.execute("PRAGMA table_info(reviews)")}
        # the legacy people can be classified with the same rules (old vocabulary was converted by the migration)
        pairs = con.execute("SELECT uniform_overall, id_status FROM tracked_people ORDER BY id").fetchall()
        assert [cs.classify(*p) for p in pairs] == ["uniform_only", "compliant_both", "not_assessed"]
    finally:
        con.close()


def test_9b_v3_database_missing_previous_status_is_healed(tmp_path):
    db = tmp_path / "v3.db"; build_v1(db); migrations.migrate(db, tmp_path / "bk")
    con = sqlite3.connect(db)
    try:
        try:
            con.execute("ALTER TABLE reviews DROP COLUMN previous_status")
        except sqlite3.OperationalError:
            pytest.skip("SQLite build without DROP COLUMN")
        con.execute("UPDATE schema_version SET version = 3"); con.commit()      # pretend: stamped v3 but column missing
    finally:
        con.close()
    assert migrations.get_version(db) == 3
    assert migrations.migrate(db, tmp_path / "bk")["migrated"] is True
    con = sqlite3.connect(db)
    try:
        assert "previous_status" in {r[1] for r in con.execute("PRAGMA table_info(reviews)")}
        assert con.execute("SELECT COUNT(*) FROM reviews").fetchone()[0] == 1       # review history preserved
    finally:
        con.close()
    assert migrations.migrate(db, tmp_path / "bk")["migrated"] is False             # idempotent


def test_9c_summary_survives_application_restart(client):
    vid, jid = seed([(2, U_SHIRT, I_NOT), (3, U_OK, I_VIS)], name="persist.mp4")
    before = summary(client, vid)
    with TestClient(app) as c2:                                                      # new lifespan = restart
        assert c2.post("/api/auth/login", json={"username": "admin", "password": PW}).status_code == 200
        after = c2.get(f"/api/videos/{vid}/compliance-summary").json()
        assert after == before
        assert c2.get("/api/system/db").json()["foreign_key_violations"] == 0
    assert summary(client, vid)["total_people"] == 5


# ------------------------------------------------------------------ TEST 10: API security
def test_10_security(client):
    vid, jid = seed([(2, U_OK, I_VIS)])
    other, ojid = seed([(1, U_OK, I_VIS)])
    with TestClient(app) as anon:
        for path in (f"/api/videos/{vid}/compliance-summary", f"/api/videos/{vid}/compliance-people", "/api/compliance/overview",
                     "/api/reports/compliance.csv"):
            assert anon.get(path).status_code == 401, path
    assert client.get("/api/videos/999999/compliance-summary").status_code == 404
    assert client.get("/api/videos/999999/compliance-people").status_code == 404
    assert client.get(f"/api/videos/{vid}/compliance-summary?job_id=999999").status_code == 404
    assert client.get(f"/api/videos/{vid}/compliance-summary?job_id={ojid}").status_code == 404        # another video's run is not reachable
    assert client.get(f"/api/videos/{vid}/compliance-people?job_id={ojid}").status_code == 404
    assert client.get("/api/videos/abc/compliance-summary").status_code == 422
    body = json.dumps(summary(client, vid)) + json.dumps(client.get(f"/api/videos/{vid}/compliance-people").json())
    for forbidden in (str(config.DATA_DIR), "stored_name", "rel_path", "model_versions", "settings_snapshot"):
        assert forbidden not in body, forbidden
    assert client.get("/api/evidence/../../etc/passwd").status_code in (400, 404)


# ------------------------------------------------------------------ real pipeline -> stored people -> summary
def test_real_pipeline_heuristic_never_yields_card_not_detected(client, tmp_path, monkeypatch):
    from app.ml.idcard import IdCardDetector
    from app.services import jobs
    from tests.test_ml import FakeDetector, Off

    def fake_models(settings):
        return FakeDetector(), IdCardDetector(settings["idcard"]), {"fight": Off(), "smoking": Off()}
    monkeypatch.setattr(jobs.registry, "for_job", fake_models)
    p = make_video(tmp_path / "people.mp4", secs=12, fps=10, people=True)
    vid = client.post("/api/videos", files={"file": ("people.mp4", p.read_bytes(), "video/mp4")}, data={"start_analysis": "false"}).json()["id"]
    jid = client.post(f"/api/videos/{vid}/analyze").json()["id"]
    for _ in range(180):
        j = client.get(f"/api/jobs/{jid}").json()
        if j["status"] in ("completed", "completed_partial", "failed", "cancelled"):
            break
        time.sleep(0.5)
    assert j["status"] in ("completed", "completed_partial"), j
    s = summary(client, vid)
    with SessionLocal() as db:
        rows = db.query(TrackedPerson).filter(TrackedPerson.job_id == jid).all()
        assert s["total_people"] == len(rows) >= 1
        assert all(r.id_status != C.ID_NOT_DETECTED for r in rows)                  # heuristic misses are UNCERTAIN
    assert s["id_not_detected"] == 0 and s["methods"]["id_card"]["method"] == "heuristic" and s["methods"]["id_card"]["reliable"] is False
    assert any(w["code"] == "id_unreliable" for w in s["warnings"]) and exclusive_total(s) == s["total_people"]
