"""API / integration tests (need the packages from requirements.txt: run with .\\run_tests.ps1)."""
import time
import pytest
from fastapi.testclient import TestClient
from app.main import app
from app.database import SessionLocal
from app.models import AnalysisJob, Event, Evidence, Video
from tests.helpers import make_video

PW = "test-password-123"


@pytest.fixture(scope="module")
def client():
    with TestClient(app) as c:
        r = c.post("/api/auth/login", json={"username": "admin", "password": PW})
        assert r.status_code == 200
        yield c


@pytest.fixture(scope="module")
def video_id(client, tmp_path_factory):
    p = make_video(tmp_path_factory.mktemp("v") / "ok.mp4", secs=8)
    with open(p, "rb") as f:
        r = client.post("/api/videos", files={"file": ("ok.mp4", f, "video/mp4")}, data={"start_analysis": "false"})
    assert r.status_code == 201, r.text
    return r.json()["id"]


def test_requires_auth():
    with TestClient(app) as anon:
        for path in ("/api/videos", "/api/events", "/api/dashboard", "/api/settings", "/api/evidence/1/file", "/api/reports/report.pdf"):
            assert anon.get(path).status_code == 401, path


def test_bad_login_rejected():
    with TestClient(app) as c:
        assert c.post("/api/auth/login", json={"username": "admin", "password": "wrong"}).status_code == 401


def test_upload_rejects_wrong_extension(client, tmp_path):
    f = tmp_path / "x.txt"; f.write_text("hello")
    assert client.post("/api/videos", files={"file": ("x.txt", f.read_bytes())}).status_code == 415


def test_upload_rejects_corrupt_video(client):
    r = client.post("/api/videos", files={"file": ("bad.mp4", b"\x00" * 64 + b"garbage" * 100)})
    assert r.status_code == 422


def test_upload_rejects_too_short(client, tmp_path):
    p = make_video(tmp_path / "s.mp4", secs=2)
    assert client.post("/api/videos", files={"file": ("s.mp4", p.read_bytes())}).status_code == 422


def test_upload_saved_with_metadata(client, video_id):
    v = client.get(f"/api/videos/{video_id}").json()
    assert v["status"] == "uploaded" and v["width"] == 320 and abs(v["duration_s"] - 8) < 1
    assert "path" not in v and "stored_name" not in v  # no filesystem paths exposed
    assert client.get(f"/api/videos/{video_id}/stream").status_code == 200


def test_analysis_job_completes_and_honest_without_models(client, video_id):
    r = client.post(f"/api/videos/{video_id}/analyze")
    assert r.status_code == 202
    jid = r.json()["id"]
    for _ in range(120):
        j = client.get(f"/api/jobs/{jid}").json()
        if j["status"] in ("completed", "failed"):
            break
        time.sleep(0.5)
    # fight/smoking models are not installed -> the job must say it is PARTIAL, never plain "completed"
    assert j["status"] == "completed_partial" and j["partial"] is True, j
    assert j["coverage"]["fight"]["ran"] is False and j["coverage"]["smoking"]["ran"] is False
    assert any("fight recognition not run" in w for w in j["warnings"])   # missing models are reported
    assert client.get(f"/api/videos/{video_id}/events").json() == []      # and nothing is invented
    assert client.get(f"/api/videos/{video_id}").json()["status"] == "completed_partial"
    assert client.get(f"/api/videos/{video_id}").json()["processing_completed_at"]


def test_duplicate_job_blocked(client, video_id):
    with SessionLocal() as db:
        db.add(AnalysisJob(video_id=video_id, status="running")); db.commit()
    assert client.post(f"/api/videos/{video_id}/analyze").status_code == 409
    with SessionLocal() as db:
        db.query(AnalysisJob).filter(AnalysisJob.status == "running").delete(); db.commit()


@pytest.fixture()
def event_id(video_id):
    with SessionLocal() as db:
        e = Event(video_id=video_id, category="possible_smoking", start_s=1, end_s=4, confidence=.8,
                  model_name="test", model_version="1", automated_status="predicted")
        db.add(e); db.commit(); return e.id


def test_review_flow_and_persistence(client, event_id):
    assert client.get(f"/api/events/{event_id}").json()["review_status"] == "pending_review"
    r = client.post(f"/api/events/{event_id}/review", json={"decision": "confirmed", "notes": "seen on footage"})
    assert r.status_code == 200 and r.json()["review_status"] == "confirmed"
    assert r.json()["reviews"][0]["reviewer"] == "admin" and r.json()["reviewed_at"]
    # review never overwrites the original model output
    assert r.json()["automated_status"] == "predicted" and r.json()["confidence"] == 0.8 and r.json()["model"].startswith("test")
    assert client.post(f"/api/events/{event_id}/review", json={"decision": "guilty"}).status_code == 422
    assert any(a["action"] == "event_review" for a in client.get("/api/audit").json())


def test_dashboard_matches_database(client, event_id):
    d = client.get("/api/dashboard").json()
    with SessionLocal() as db:
        assert d["videos_total"] == db.query(Video).count()
        assert d["pending_review"] == db.query(Event).filter(Event.review_status == "pending_review").count()
        assert d["confirmed"] == db.query(Event).filter(Event.review_status == "confirmed").count()


def test_csv_pdf_and_confirmed_counting(client, event_id):
    csv = client.get("/api/reports/events.csv?review_status=pending_review")
    assert csv.status_code == 200 and "event_id" in csv.text
    pdf = client.get("/api/reports/report.pdf")
    assert pdf.status_code == 200 and pdf.content.startswith(b"%PDF")
    s = client.get("/api/reports/summary").json()
    assert s["confirmed"] == s["by_review_status"]["confirmed"] <= s["total_events"]


def test_evidence_path_traversal_blocked(client, video_id):
    with SessionLocal() as db:
        ev = Evidence(video_id=video_id, kind="frame", rel_path="../../campus_safety.db"); db.add(ev); db.commit(); eid = ev.id
    assert client.get(f"/api/evidence/{eid}/file").status_code == 400


def test_settings_validation_and_persistence(client):
    assert client.put("/api/settings", json={"activity": {"fight": {"threshold": 0.1, "uncertain_low": 0.9}}}).status_code == 422
    assert client.put("/api/settings", json={"nonsense": 1}).status_code == 422
    r = client.put("/api/settings", json={"activity": {"fight": {"threshold": 0.8}}})
    assert r.status_code == 200 and client.get("/api/settings").json()["activity"]["fight"]["threshold"] == 0.8


def test_system_status_reports_missing_models(client):
    s = client.get("/api/system/status").json()
    by = {m["key"]: m for m in s["models"]}
    assert by["fight"]["state"] in ("FILE_MISSING", "DEPENDENCY_MISSING", "NOT_CONFIGURED", "LOAD_FAILED")
    assert by["fight"]["evaluation"]["state"] == "NOT_EVALUATED"          # no invented evaluation
    assert s["model_warnings"] and s["schema_version"] >= 2
    assert s["membership_verification"]["displayed_as"] == "Membership unverified"


def test_backup_created(client):
    assert client.post("/api/system/backup").json()["file"].endswith(".db")


def test_restart_recovers_interrupted_job_and_keeps_data(video_id):
    with SessionLocal() as db:
        db.add(AnalysisJob(video_id=video_id, status="running")); db.commit()
    with TestClient(app) as c2:  # new lifespan = application restart
        c2.post("/api/auth/login", json={"username": "admin", "password": PW})
        assert c2.get(f"/api/videos/{video_id}").status_code == 200
        with SessionLocal() as db:
            assert db.query(AnalysisJob).filter(AnalysisJob.status == "running").count() == 0


def test_models_endpoint_and_dashboard_warn_about_missing_models(client):
    m = client.get("/api/system/models").json()
    assert any("Fighting" in w for w in m["warnings"])
    d = client.get("/api/dashboard").json()
    assert d["model_warnings"] and "analyses_partial" in d


def test_incident_filters(client, video_id):
    with SessionLocal() as db:
        db.add(Event(video_id=video_id, category="possible_physical_fighting", start_s=2, end_s=6, model_name="m",
                     model_version="1", dedupe_key="flt-1", review_status="dismissed"))
        db.commit()
    r = client.get("/api/events?category=possible_physical_fighting&review_status=dismissed").json()
    assert r["total"] >= 1 and all(e["category"] == "possible_physical_fighting" and e["review_status"] == "dismissed" for e in r["items"])
    assert client.get("/api/events?date_from=2999-01-01").json()["total"] == 0
    assert client.get(f"/api/events?video_id={video_id}&q=ok.mp4").json()["total"] >= 1


def test_csv_matches_active_filters(client):
    rows = client.get("/api/reports/events.csv?category=possible_physical_fighting").text.strip().splitlines()
    assert len(rows) >= 2 and all("Possible physical fighting" in r for r in rows[1:])
    assert "Possible smoking" not in "\n".join(rows[1:])


def test_missing_video_file_fails_job_and_never_sticks_in_processing(client, tmp_path):
    from app import config
    p = make_video(tmp_path / "gone.mp4", secs=6)
    vid = client.post("/api/videos", files={"file": ("gone.mp4", p.read_bytes())}).json()["id"]
    with SessionLocal() as db:
        name = db.get(Video, vid).stored_name
    (config.VIDEO_DIR / name).unlink()
    r = client.post(f"/api/videos/{vid}/analyze")
    assert r.status_code == 410                                    # refused up front
    (config.VIDEO_DIR / name).write_bytes(b"\x00" * 64 + b"ftypmp42" + b"x" * 200)
    jid = client.post(f"/api/videos/{vid}/analyze").json()["id"]
    for _ in range(60):
        j = client.get(f"/api/jobs/{jid}").json()
        if j["status"] in ("failed", "completed", "completed_partial"):
            break
        time.sleep(0.5)
    assert j["status"] == "failed" and j["error"]
    v = client.get(f"/api/videos/{vid}").json()
    assert v["status"] == "failed" and v["status"] != "processing"
    assert str(config.DATA_DIR) not in j["error"]                       # no local paths in user-facing errors


def test_errors_do_not_leak_paths(client):
    r = client.get("/api/evidence/999999/file")
    assert r.status_code == 404 and "home" not in r.text and ":\\" not in r.text


def test_backup_validation_endpoint_and_traversal_guard(client):
    name = client.post("/api/system/backup").json()["file"]
    v = client.post("/api/system/backups/validate", json={"name": name}).json()
    assert v["ok"] is True and v["counts"]["videos"] >= 1
    assert client.post("/api/system/backups/validate", json={"name": "../../campus_safety.db"}).status_code == 400


def test_retention_keeps_footage_with_pending_findings(client, video_id):
    client.put("/api/settings", json={"retention": {"video_days": 0, "evidence_days": 0}})
    with SessionLocal() as db:
        db.add(Event(video_id=video_id, category="possible_smoking", start_s=1, end_s=2, model_name="m", model_version="1",
                     dedupe_key="ret-1", review_status="pending_review")); db.commit()
    client.post("/api/system/retention/run")
    assert client.get(f"/api/videos/{video_id}/stream").status_code == 200      # protected: has a pending finding
    client.put("/api/settings", json={"retention": {"video_days": 90, "evidence_days": 180}})


def test_duplicate_upload_is_flagged_by_content_hash(client, video_id, tmp_path):
    with SessionLocal() as db:
        name = db.get(Video, video_id).stored_name
    from app import config
    data = (config.VIDEO_DIR / name).read_bytes()
    r = client.post("/api/videos", files={"file": ("copy.mp4", data, "video/mp4")})
    assert r.status_code == 201 and video_id in r.json()["duplicate_of"]


def test_db_info_reports_file_in_use_and_no_second_database(client):
    from app import config
    from pathlib import Path
    i = client.get("/api/system/db").json()
    assert Path(i["path"]).resolve() == config.DB_PATH.resolve() and i["tables"]["videos"] >= 1
    assert i["other_database_files"] == [] and i["foreign_key_violations"] == 0
