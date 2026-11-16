"""Database integrity tests (need SQLAlchemy: run via run_tests.ps1). They use a temporary database
(see conftest.py) and never touch data/campus_safety.db."""
import json
import os
import subprocess
import sys
from pathlib import Path
import pytest
from sqlalchemy.exc import IntegrityError
from app import config, migrations
from app.database import SessionLocal, get_engine, init_db
from app.models import AnalysisJob, Event, Evidence, JobModule, Review, TrackedPerson, TrackObservation, Video

ROOT = Path(__file__).resolve().parent.parent
_n = {"i": 0}


@pytest.fixture(scope="module", autouse=True)
def ready():
    get_engine(); init_db()


def video(db, status="uploaded"):
    _n["i"] += 1
    v = Video(original_filename="t.mp4", stored_name=f"t{_n['i']}_{os.getpid()}.mp4", size_bytes=1, duration_s=10, fps=25,
              width=64, height=48, status=status)
    db.add(v); db.commit(); return v


def event(vid, **kw):
    base = dict(video_id=vid, category="possible_smoking", start_s=1, end_s=3, model_name="m", model_version="1")
    base.update(kw); return Event(**base)


def test_schema_created_and_stamped_with_current_version():
    assert migrations.get_version(config.DB_PATH) == migrations.CURRENT_VERSION
    assert init_db()["migrated"] is False            # second call is a no-op


def test_foreign_keys_are_enforced():
    with SessionLocal() as db:
        db.add(event(987654)); 
        with pytest.raises(IntegrityError):
            db.commit()


def test_invalid_status_values_rejected_by_database():
    with SessionLocal() as db:
        v = video(db)
        db.add(event(v.id, review_status="guilty"))
        with pytest.raises(IntegrityError):
            db.commit()
        db.rollback()
        v2 = Video(original_filename="x", stored_name="bogus_status.mp4", size_bytes=1, duration_s=1, fps=1, width=1, height=1, status="PROCESSING-ish")
        db.add(v2)
        with pytest.raises(IntegrityError):
            db.commit()


def test_event_interval_must_be_ordered():
    with SessionLocal() as db:
        v = video(db); db.add(event(v.id, start_s=9, end_s=2))
        with pytest.raises(IntegrityError):
            db.commit()


def test_duplicate_finding_is_blocked_by_unique_key():
    with SessionLocal() as db:
        v = video(db)
        db.add(event(v.id, dedupe_key=f"k{v.id}")); db.commit()
        db.add(event(v.id, dedupe_key=f"k{v.id}"))
        with pytest.raises(IntegrityError):
            db.commit()


def test_deleting_video_cascades_without_orphans():
    with SessionLocal() as db:
        v = video(db)
        job = AnalysisJob(video_id=v.id, status="completed"); db.add(job); db.flush()
        e = event(v.id, job_id=job.id, dedupe_key=f"c{v.id}"); db.add(e); db.flush()
        db.add(Evidence(video_id=v.id, event_id=e.id, kind="frame", rel_path="x.jpg"))
        db.add(Review(event_id=e.id, reviewer="a", decision="confirmed"))
        db.add(TrackedPerson(video_id=v.id, job_id=job.id, track_ref="T1", first_seen_s=0, last_seen_s=1))
        db.commit(); vid = v.id
        db.delete(v); db.commit()
        for M in (Event, Evidence, TrackedPerson, AnalysisJob):
            assert db.query(M).filter(M.video_id == vid).count() == 0
        assert db.query(Review).filter(Review.event_id == e.id).count() == 0


def test_failed_transaction_leaves_nothing_behind():
    with SessionLocal() as db:
        v = video(db)
        db.add(event(v.id, dedupe_key=f"t{v.id}a"))
        db.add(event(v.id, dedupe_key=None, review_status="nonsense"))
        with pytest.raises(IntegrityError):
            db.commit()
        db.rollback()
        assert db.query(Event).filter(Event.video_id == v.id).count() == 0   # all-or-nothing


def test_legacy_database_migrates_and_reads_through_orm(tmp_path):
    """Build the old v1 schema + data, then open it the way the app does (init_db) in a fresh process."""
    from tests.legacy_schema import build_v1
    d = tmp_path / "d"; d.mkdir(); build_v1(d / "campus_safety.db")
    code = ("import json;from app.database import init_db, SessionLocal;from app.models import Event, Video, TrackedPerson;"
            "i=init_db();s=SessionLocal();"
            "print(json.dumps({'info':i,'vids':[(v.id,v.status) for v in s.query(Video)],"
            "'ev':[(e.id,e.review_status,e.predicted_class,e.reviewed_by) for e in s.query(Event)],"
            "'ppl':[(p.track_ref,p.uniform_overall,p.id_status) for p in s.query(TrackedPerson)]}))")
    env = {**os.environ, "CAMPUS_DATA_DIR": str(d), "CAMPUS_DATABASE_URL": ""}
    env.pop("CAMPUS_DATABASE_URL")
    r = subprocess.run([sys.executable, "-c", code], cwd=ROOT, env=env, capture_output=True, text=True)
    assert r.returncode == 0, r.stderr
    out = json.loads(r.stdout.strip().splitlines()[-1])
    assert out["info"]["migrated"] is True and (d / "backups" / out["info"]["backup"]).exists()
    assert sorted(out["vids"]) == [[1, "completed_partial"], [2, "failed"]]
    assert [e[1] for e in out["ev"]] == ["confirmed", "pending_review"] and out["ev"][0][3] == "admin"
    assert ["T2", "COMPLIANT", "CARD_VISIBLE"] in out["ppl"]


def test_job_module_unique_per_job_and_cascades_with_job():
    with SessionLocal() as db:
        v = video(db); job = AnalysisJob(video_id=v.id, status="completed"); db.add(job); db.flush()
        db.add(JobModule(job_id=job.id, module="fight", requested=True, ran=False, state="FILE_MISSING", result="NOT_ASSESSED"))
        db.add(TrackObservation(video_id=v.id, job_id=job.id, track_ref="T1", t_s=1, x1=0, y1=0, x2=1, y2=1, conf=.5))
        db.commit()
        db.add(JobModule(job_id=job.id, module="fight", requested=True, ran=True, state="LOADED"))
        with pytest.raises(IntegrityError):
            db.commit()
        db.rollback()
        jid = job.id
        db.delete(db.get(AnalysisJob, jid)); db.commit()
        assert db.query(JobModule).filter(JobModule.job_id == jid).count() == 0
        assert db.query(TrackObservation).filter(TrackObservation.job_id == jid).count() == 0


def test_review_checks_and_previous_status_column():
    with SessionLocal() as db:
        v = video(db); e = event(v.id, dedupe_key=f"r{v.id}"); db.add(e); db.commit()
        db.add(Review(event_id=e.id, reviewer="a", decision="confirmed", previous_status="pending_review")); db.commit()
        db.add(Review(event_id=e.id, reviewer="a", decision="pending_review"))
        with pytest.raises(IntegrityError):
            db.commit()
