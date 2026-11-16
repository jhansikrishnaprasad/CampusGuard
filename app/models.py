from __future__ import annotations
from datetime import datetime, timezone
from typing import Optional
from sqlalchemy import (Boolean, CheckConstraint, DateTime, Float, ForeignKey, Index, Integer,
                        String, Text, UniqueConstraint)
from .constants import (AUTOMATED_STATES, ID_STATES, JOB_STATES, REVIEW_STATES, UNIFORM_STATES,
                        VIDEO_STATES, in_clause)
from sqlalchemy.orm import DeclarativeBase, Mapped, mapped_column, relationship


def utcnow() -> datetime:
    return datetime.now(timezone.utc).replace(tzinfo=None)


class Base(DeclarativeBase):
    pass


class User(Base):
    __tablename__ = "users"
    id: Mapped[int] = mapped_column(primary_key=True)
    username: Mapped[str] = mapped_column(String(64), unique=True)
    password_hash: Mapped[str] = mapped_column(String(256))
    role: Mapped[str] = mapped_column(String(16), default="reviewer")  # admin | reviewer
    active: Mapped[bool] = mapped_column(Boolean, default=True)
    created_at: Mapped[datetime] = mapped_column(DateTime, default=utcnow)


class SessionToken(Base):
    __tablename__ = "session_tokens"
    id: Mapped[int] = mapped_column(primary_key=True)
    token_hash: Mapped[str] = mapped_column(String(64), unique=True, index=True)
    user_id: Mapped[int] = mapped_column(ForeignKey("users.id", ondelete="CASCADE"))
    expires_at: Mapped[datetime] = mapped_column(DateTime)


class Video(Base):
    __tablename__ = "videos"
    __table_args__ = (CheckConstraint(in_clause("status", VIDEO_STATES), name="ck_video_status"),)
    id: Mapped[int] = mapped_column(primary_key=True)
    original_filename: Mapped[str] = mapped_column(String(255), index=True)
    stored_name: Mapped[str] = mapped_column(String(128), unique=True)
    preview_name: Mapped[Optional[str]] = mapped_column(String(128))
    size_bytes: Mapped[int] = mapped_column(Integer)
    duration_s: Mapped[float] = mapped_column(Float)
    fps: Mapped[float] = mapped_column(Float)
    width: Mapped[int] = mapped_column(Integer)
    height: Mapped[int] = mapped_column(Integer)
    uploaded_at: Mapped[datetime] = mapped_column(DateTime, default=utcnow, index=True)
    uploaded_by: Mapped[Optional[str]] = mapped_column(String(64))
    # uploaded | queued | processing | completed | failed | cancelled
    status: Mapped[str] = mapped_column(String(20), default="uploaded", index=True)
    error: Mapped[Optional[str]] = mapped_column(Text)
    sha256: Mapped[Optional[str]] = mapped_column(String(64), index=True)  # content hash (duplicate warning)
    processing_started_at: Mapped[Optional[datetime]] = mapped_column(DateTime)
    processing_completed_at: Mapped[Optional[datetime]] = mapped_column(DateTime)
    jobs = relationship("AnalysisJob", back_populates="video", cascade="all, delete")
    events = relationship("Event", back_populates="video", cascade="all, delete")
    people = relationship("TrackedPerson", back_populates="video", cascade="all, delete")


class AnalysisJob(Base):
    __tablename__ = "analysis_jobs"
    __table_args__ = (CheckConstraint(in_clause("status", JOB_STATES), name="ck_job_status"),)
    id: Mapped[int] = mapped_column(primary_key=True)
    video_id: Mapped[int] = mapped_column(ForeignKey("videos.id", ondelete="CASCADE"), index=True)
    status: Mapped[str] = mapped_column(String(20), default="queued", index=True)
    attempt: Mapped[int] = mapped_column(Integer, default=1, server_default="1")  # 1 = first run, 2+ = retries/reprocessing
    is_current: Mapped[bool] = mapped_column(Boolean, default=True, server_default="1", index=True)  # latest successful run of the video
    partial: Mapped[bool] = mapped_column(Boolean, default=False, server_default="0")
    coverage: Mapped[Optional[str]] = mapped_column(Text)  # JSON: which modules ran / were skipped and why
    progress: Mapped[float] = mapped_column(Float, default=0.0)
    model_versions: Mapped[Optional[str]] = mapped_column(Text)  # JSON
    settings_snapshot: Mapped[Optional[str]] = mapped_column(Text)  # JSON
    warnings: Mapped[Optional[str]] = mapped_column(Text)  # JSON list
    cancel_requested: Mapped[bool] = mapped_column(Boolean, default=False)
    created_at: Mapped[datetime] = mapped_column(DateTime, default=utcnow)
    started_at: Mapped[Optional[datetime]] = mapped_column(DateTime)
    finished_at: Mapped[Optional[datetime]] = mapped_column(DateTime)
    processing_seconds: Mapped[Optional[float]] = mapped_column(Float)
    error: Mapped[Optional[str]] = mapped_column(Text)
    video = relationship("Video", back_populates="jobs")
    modules = relationship("JobModule", back_populates="job", cascade="all, delete")


class TrackedPerson(Base):
    """Temporary tracking reference - NOT a verified identity."""
    __tablename__ = "tracked_people"
    __table_args__ = (Index("ix_people_video_track", "video_id", "track_ref"),
                      CheckConstraint(in_clause("uniform_overall", UNIFORM_STATES), name="ck_person_uniform"),
                      CheckConstraint(in_clause("id_status", ID_STATES), name="ck_person_id"))
    id: Mapped[int] = mapped_column(primary_key=True)
    video_id: Mapped[int] = mapped_column(ForeignKey("videos.id", ondelete="CASCADE"), index=True)
    job_id: Mapped[Optional[int]] = mapped_column(ForeignKey("analysis_jobs.id", ondelete="SET NULL"))
    track_ref: Mapped[str] = mapped_column(String(32))
    first_seen_s: Mapped[float] = mapped_column(Float)
    last_seen_s: Mapped[float] = mapped_column(Float)
    detections: Mapped[int] = mapped_column(Integer, default=0)
    shirt_status: Mapped[str] = mapped_column(String(32), default="unable_to_verify")
    trouser_status: Mapped[str] = mapped_column(String(32), default="unable_to_verify")
    uniform_overall: Mapped[str] = mapped_column(String(32), default="NOT_ASSESSED")
    id_status: Mapped[str] = mapped_column(String(32), default="NOT_ASSESSED")
    uniform_samples: Mapped[int] = mapped_column(Integer, default=0)
    id_samples: Mapped[int] = mapped_column(Integer, default=0)
    shirt_fraction: Mapped[Optional[float]] = mapped_column(Float)
    trouser_fraction: Mapped[Optional[float]] = mapped_column(Float)
    uniform_score: Mapped[Optional[float]] = mapped_column(Float)      # 0..1 closeness to the configured colour ranges (not a probability)
    uniform_method: Mapped[Optional[str]] = mapped_column(String(48))
    uniform_version: Mapped[Optional[str]] = mapped_column(String(32))
    id_confidence: Mapped[Optional[float]] = mapped_column(Float)
    id_method: Mapped[Optional[str]] = mapped_column(String(48))
    id_version: Mapped[Optional[str]] = mapped_column(String(32))
    id_association: Mapped[Optional[str]] = mapped_column(String(32))  # how the card was tied to this person
    notes: Mapped[Optional[str]] = mapped_column(Text)
    membership_status: Mapped[str] = mapped_column(String(32), default="membership_unverified")
    video = relationship("Video", back_populates="people")
    evidence = relationship("Evidence", back_populates="person", cascade="all, delete")


class Event(Base):
    __tablename__ = "events"
    __table_args__ = (
        Index("ix_events_video_start", "video_id", "start_s"),
        Index("ux_events_dedupe", "dedupe_key", unique=True),
        CheckConstraint("end_s >= start_s", name="ck_event_interval"),
        CheckConstraint(in_clause("review_status", REVIEW_STATES), name="ck_event_review"),
        CheckConstraint(in_clause("automated_status", AUTOMATED_STATES), name="ck_event_auto"),
    )
    id: Mapped[int] = mapped_column(primary_key=True)
    video_id: Mapped[int] = mapped_column(ForeignKey("videos.id", ondelete="CASCADE"), index=True)
    job_id: Mapped[Optional[int]] = mapped_column(ForeignKey("analysis_jobs.id", ondelete="SET NULL"))
    track_ref: Mapped[Optional[str]] = mapped_column(String(32))
    category: Mapped[str] = mapped_column(String(48), index=True)
    start_s: Mapped[float] = mapped_column(Float)
    end_s: Mapped[float] = mapped_column(Float)
    confidence: Mapped[Optional[float]] = mapped_column(Float)
    model_name: Mapped[str] = mapped_column(String(96))
    model_version: Mapped[str] = mapped_column(String(64))
    automated_status: Mapped[str] = mapped_column(String(16), default="predicted")  # predicted | uncertain
    review_status: Mapped[str] = mapped_column(String(16), default="pending_review", index=True)
    review_notes: Mapped[Optional[str]] = mapped_column(Text)
    reviewed_at: Mapped[Optional[datetime]] = mapped_column(DateTime)
    reviewed_by: Mapped[Optional[str]] = mapped_column(String(64))
    predicted_class: Mapped[Optional[str]] = mapped_column(String(48))  # original model/rule output, never overwritten
    dedupe_key: Mapped[Optional[str]] = mapped_column(String(160))
    summary: Mapped[Optional[str]] = mapped_column(Text)
    created_at: Mapped[datetime] = mapped_column(DateTime, default=utcnow, index=True)
    video = relationship("Video", back_populates="events")
    evidence = relationship("Evidence", back_populates="event", cascade="all, delete")
    reviews = relationship("Review", back_populates="event", cascade="all, delete")


class Evidence(Base):
    __tablename__ = "evidence"
    __table_args__ = (CheckConstraint("kind IN ('frame', 'clip')", name="ck_evidence_kind"),)
    id: Mapped[int] = mapped_column(primary_key=True)
    video_id: Mapped[int] = mapped_column(ForeignKey("videos.id", ondelete="CASCADE"), index=True)
    event_id: Mapped[Optional[int]] = mapped_column(ForeignKey("events.id", ondelete="CASCADE"), index=True)
    person_id: Mapped[Optional[int]] = mapped_column(ForeignKey("tracked_people.id", ondelete="CASCADE"))
    kind: Mapped[str] = mapped_column(String(16))  # frame | clip
    rel_path: Mapped[str] = mapped_column(String(300))  # relative to EVIDENCE_DIR
    timestamp_s: Mapped[Optional[float]] = mapped_column(Float)
    created_at: Mapped[datetime] = mapped_column(DateTime, default=utcnow)
    event = relationship("Event", back_populates="evidence")
    person = relationship("TrackedPerson", back_populates="evidence")


class Review(Base):
    __tablename__ = "reviews"
    __table_args__ = (CheckConstraint("decision IN ('confirmed', 'dismissed', 'inconclusive')", name="ck_review_decision"),)
    id: Mapped[int] = mapped_column(primary_key=True)
    event_id: Mapped[int] = mapped_column(ForeignKey("events.id", ondelete="CASCADE"), index=True)
    reviewer: Mapped[str] = mapped_column(String(64))
    decision: Mapped[str] = mapped_column(String(16))  # confirmed | dismissed | inconclusive
    notes: Mapped[Optional[str]] = mapped_column(Text)
    previous_status: Mapped[Optional[str]] = mapped_column(String(16))  # review status before this decision
    created_at: Mapped[datetime] = mapped_column(DateTime, default=utcnow)
    event = relationship("Event", back_populates="reviews")


class ModelEvaluation(Base):
    __tablename__ = "model_evaluations"
    id: Mapped[int] = mapped_column(primary_key=True)
    model_name: Mapped[str] = mapped_column(String(96))
    model_version: Mapped[str] = mapped_column(String(64))
    dataset_name: Mapped[str] = mapped_column(String(128))
    dataset_version: Mapped[str] = mapped_column(String(64))
    evaluated_at: Mapped[datetime] = mapped_column(DateTime, default=utcnow)
    precision: Mapped[Optional[float]] = mapped_column(Float)
    recall: Mapped[Optional[float]] = mapped_column(Float)
    f1: Mapped[Optional[float]] = mapped_column(Float)
    false_positive_rate: Mapped[Optional[float]] = mapped_column(Float)
    seconds_per_minute_footage: Mapped[Optional[float]] = mapped_column(Float)
    sample_count: Mapped[Optional[int]] = mapped_column(Integer)
    positive_count: Mapped[Optional[int]] = mapped_column(Integer)
    thresholds: Mapped[Optional[str]] = mapped_column(Text)  # JSON
    status: Mapped[str] = mapped_column(String(16), default="completed", server_default="completed")
    notes: Mapped[Optional[str]] = mapped_column(Text)


class Setting(Base):
    __tablename__ = "settings"
    key: Mapped[str] = mapped_column(String(64), primary_key=True)
    value: Mapped[str] = mapped_column(Text)  # JSON


class AuditLog(Base):
    __tablename__ = "audit_log"
    id: Mapped[int] = mapped_column(primary_key=True)
    username: Mapped[str] = mapped_column(String(64))
    action: Mapped[str] = mapped_column(String(48), index=True)
    target: Mapped[Optional[str]] = mapped_column(String(96))
    detail: Mapped[Optional[str]] = mapped_column(Text)
    created_at: Mapped[datetime] = mapped_column(DateTime, default=utcnow, index=True)


class JobModule(Base):
    """Per-module outcome of ONE processing run. A finished job with an unavailable module is visible here."""
    __tablename__ = "job_modules"
    __table_args__ = (UniqueConstraint("job_id", "module", name="uq_job_module"),)
    id: Mapped[int] = mapped_column(primary_key=True)
    job_id: Mapped[int] = mapped_column(ForeignKey("analysis_jobs.id", ondelete="CASCADE"), index=True)
    module: Mapped[str] = mapped_column(String(32))  # person_detection | tracking | uniform | id_card | fight | smoking
    requested: Mapped[bool] = mapped_column(Boolean, default=True)
    ran: Mapped[bool] = mapped_column(Boolean, default=False)
    state: Mapped[str] = mapped_column(String(24))   # registry state: LOADED / FILE_MISSING / ...
    result: Mapped[Optional[str]] = mapped_column(String(32))  # NOT_ASSESSED / NOT_DETECTED / UNCERTAIN / POSSIBLE_* / summary
    model_name: Mapped[Optional[str]] = mapped_column(String(96))
    model_version: Mapped[Optional[str]] = mapped_column(String(64))
    evaluation_state: Mapped[Optional[str]] = mapped_column(String(16))
    detail: Mapped[Optional[str]] = mapped_column(Text)
    job = relationship("AnalysisJob", back_populates="modules")


class TrackObservation(Base):
    """Sampled person detections (temporary track ids, NOT identities)."""
    __tablename__ = "track_observations"
    __table_args__ = (Index("ix_obs_job_track", "job_id", "track_ref"),)
    id: Mapped[int] = mapped_column(primary_key=True)
    video_id: Mapped[int] = mapped_column(ForeignKey("videos.id", ondelete="CASCADE"), index=True)
    job_id: Mapped[int] = mapped_column(ForeignKey("analysis_jobs.id", ondelete="CASCADE"))
    track_ref: Mapped[str] = mapped_column(String(32))
    t_s: Mapped[float] = mapped_column(Float)
    x1: Mapped[float] = mapped_column(Float)
    y1: Mapped[float] = mapped_column(Float)
    x2: Mapped[float] = mapped_column(Float)
    y2: Mapped[float] = mapped_column(Float)
    conf: Mapped[Optional[float]] = mapped_column(Float)


class ModelRegistryEntry(Base):
    """Last known state of every module (updated at start-up and at each job)."""
    __tablename__ = "model_registry"
    module: Mapped[str] = mapped_column(String(32), primary_key=True)
    model_name: Mapped[Optional[str]] = mapped_column(String(96))
    model_version: Mapped[Optional[str]] = mapped_column(String(64))
    weight_file: Mapped[Optional[str]] = mapped_column(String(160))
    state: Mapped[str] = mapped_column(String(24))
    detail: Mapped[Optional[str]] = mapped_column(Text)
    evaluation_state: Mapped[str] = mapped_column(String(16), default="NOT_EVALUATED")
    updated_at: Mapped[datetime] = mapped_column(DateTime, default=utcnow)
