"""MANDATORY acceptance test (needs the full requirements): UPLOAD -> PROCESS -> STORE -> REVIEW -> REPORT ->
RESTART -> VERIFY PERSISTENCE, on a temporary database (see conftest.py).

The AI models are replaced by small deterministic test doubles (a fixed person box and a scripted fight score) so that
the REAL pipeline, worker, database writes, evidence files, review workflow and reports are exercised end to end.
This proves the plumbing and persistence - it says nothing about real-world model accuracy."""
import sqlite3
import time
from pathlib import Path
import pytest
from fastapi.testclient import TestClient
from app import config
from app.database import SessionLocal
from app.main import app
from app.ml.idcard import IdCardDetector
from app.models import (AnalysisJob, AuditLog, Event, Evidence, JobModule, Review, TrackedPerson, TrackObservation, Video)
from app.services import jobs
from tests.helpers import make_video
from tests.test_ml import FakeDetector, FakeFight, Off

PW = "test-password-123"


def login(c):
    assert c.post("/api/auth/login", json={"username": "admin", "password": PW}).status_code == 200


def wait_job(c, jid, secs=90):
    for _ in range(int(secs / 0.5)):
        j = c.get(f"/api/jobs/{jid}").json()
        if j["status"] in ("completed", "completed_partial", "failed", "cancelled"):
            return j
        time.sleep(0.5)
    raise AssertionError("job did not finish")


def counts():
    with SessionLocal() as db:
        return {m.__tablename__: db.query(m).count() for m in (Video, AnalysisJob, JobModule, TrackedPerson, TrackObservation, Event, Evidence, Review, AuditLog)}


def test_upload_to_report_survives_restart(tmp_path, monkeypatch):
    # scripted models: person box fixed, fight probability jumps after the 2nd window
    def fake_models(settings):
        fight, n = FakeFight(), {"i": 0}
        def predict(frames):
            n["i"] += 1
            return 0.95 if n["i"] >= 2 else 0.1
        fight.predict = predict
        return FakeDetector(), IdCardDetector(settings["idcard"]), {"fight": fight, "smoking": Off()}
    monkeypatch.setattr(jobs.registry, "for_job", fake_models)

    db_file = config.DB_PATH.resolve()
    with TestClient(app) as c:
        login(c)
        # --- which physical database file is in use? ---
        info = c.get("/api/system/db").json()
        assert Path(info["path"]).resolve() == db_file and db_file.exists()
        assert info["other_database_files"] == [] and info["schema_version"] >= 3
        c.put("/api/settings", json={"uniform": {"min_person_height_px": 50},
                                     "activity": {"fight": {"stride_s": 1.0, "window_s": 2.0, "min_duration_s": 1.0}}})

        # --- upload -> video row ---
        p = make_video(tmp_path / "campus.mp4", secs=12, fps=10, people=True)
        r = c.post("/api/videos", files={"file": ("campus.mp4", p.read_bytes(), "video/mp4")}, data={"start_analysis": "false"})
        assert r.status_code == 201, r.text
        vid = r.json()["id"]
        with SessionLocal() as db:
            v = db.get(Video, vid)
            assert v.original_filename == "campus.mp4" and v.size_bytes == p.stat().st_size and v.sha256 and v.status == "uploaded"
            assert (config.VIDEO_DIR / v.stored_name).is_file() and abs(v.duration_s - 12) < 1

        # --- run 1: persistent job + real pipeline ---
        jid1 = c.post(f"/api/videos/{vid}/analyze").json()["id"]
        j1 = wait_job(c, jid1)
        assert j1["status"] == "completed_partial", j1                      # smoking model absent -> NOT a plain "completed"
        with SessionLocal() as db:
            job = db.get(AnalysisJob, jid1)
            assert job.video_id == vid and job.attempt == 1 and job.is_current and job.partial
            mods = {m.module: m for m in db.query(JobModule).filter(JobModule.job_id == jid1)}
            assert mods["fight"].ran and mods["fight"].result == "POSSIBLE_FIGHTING"
            assert not mods["smoking"].ran and mods["smoking"].result == "NOT_ASSESSED"
            tp = db.query(TrackedPerson).filter(TrackedPerson.job_id == jid1).one()
            assert tp.video_id == vid and tp.track_ref == "T1" and tp.uniform_method == "hsv-colour-baseline"
            assert db.query(TrackObservation).filter(TrackObservation.job_id == jid1, TrackObservation.track_ref == "T1").count() > 0
            ev = db.query(Event).filter(Event.job_id == jid1, Event.category == config.CATEGORY_FIGHT).one()
            assert ev.video_id == vid and ev.confidence == pytest.approx(0.95) and ev.review_status == "pending_review"
            ev1_id, conf = ev.id, ev.confidence
            eids = db.query(Evidence).filter(Evidence.event_id == ev.id).all()
            assert {e.kind for e in eids} >= {"frame", "clip"} and all((config.EVIDENCE_DIR / e.rel_path).is_file() for e in eids)
            assert all(e.video_id == vid for e in eids)

        # --- human review ---
        assert c.post(f"/api/events/{ev1_id}/review", json={"decision": "confirmed", "notes": "verified on footage"}).status_code == 200
        assert c.post(f"/api/events/{ev1_id}/review", json={"decision": "confirmed", "notes": "verified on footage"}).status_code == 409
        with SessionLocal() as db:
            rv = db.query(Review).filter(Review.event_id == ev1_id).one()
            assert rv.reviewer == "admin" and rv.previous_status == "pending_review" and rv.decision == "confirmed"
            e = db.get(Event, ev1_id)
            assert e.review_status == "confirmed" and e.confidence == conf and e.automated_status == "predicted"   # prediction kept
            assert db.query(AuditLog).filter(AuditLog.action == "event_review", AuditLog.target == f"event {ev1_id}").count() == 1

        # --- reports from stored data ---
        csv = c.get("/api/reports/events.csv").text
        assert "Possible physical fighting" in csv and "Confirmed" in csv
        s = c.get("/api/reports/summary").json()
        assert s["total_events"] == 1 and s["confirmed"] == 1
        assert "smoking did not run" in (s["coverage_warning"] or "")      # zero smoking findings must not imply "none happened"
        assert c.get("/api/reports/report.pdf").content.startswith(b"%PDF")

        # --- run 2 (reprocess): history is preserved, only the newest run is current ---
        jid2 = c.post(f"/api/jobs/{jid1}/retry").json()["id"]
        assert wait_job(c, jid2)["status"] == "completed_partial"
        with SessionLocal() as db:
            assert db.get(AnalysisJob, jid1).is_current is False and db.get(AnalysisJob, jid2).is_current is True
            assert db.get(AnalysisJob, jid2).attempt == 2
            assert db.query(Event).filter(Event.job_id == jid1).count() == 1               # run-1 finding and its review kept
        cur = c.get("/api/events").json()["items"]
        assert [e["job_id"] for e in cur] == [jid2]
        both = c.get("/api/events?include_history=true").json()["items"]
        assert {e["job_id"] for e in both} == {jid1, jid2}
        assert c.get(f"/api/events/{ev1_id}").json()["review_status"] == "confirmed"

        before = counts()
        ev_ids = sorted(e["id"] for e in both)

    # ===================== APPLICATION RESTART =====================
    with TestClient(app) as c2:
        assert counts() == before                                                           # nothing lost, nothing duplicated
        login(c2)
        info = c2.get("/api/system/db").json()
        assert Path(info["path"]).resolve() == db_file and info["foreign_key_violations"] == 0 and info["other_database_files"] == []
        top_level_dbs = sorted(p.name for p in config.DATA_DIR.glob("*.db"))
        assert top_level_dbs == [db_file.name], top_level_dbs                               # no accidental second database
        assert c2.get(f"/api/videos/{vid}").json()["status"] == "completed_partial"
        assert sorted(e["id"] for e in c2.get("/api/events?include_history=true").json()["items"]) == ev_ids
        d = c2.get(f"/api/events/{ev1_id}").json()
        assert d["review_status"] == "confirmed" and d["reviews"][0]["reviewer"] == "admin" and d["confidence"] == conf
        assert all(x["file_available"] for x in d["evidence"])
        assert "Possible physical fighting" in c2.get("/api/reports/events.csv?include_history=true").text
        assert c2.get("/api/reports/report.pdf").content.startswith(b"%PDF")
        assert c2.get("/api/dashboard").json()["videos_total"] >= 1
    con = sqlite3.connect(db_file)
    try:
        assert con.execute("PRAGMA foreign_key_check").fetchall() == [] and con.execute("PRAGMA integrity_check").fetchone()[0] == "ok"
    finally:
        con.close()
