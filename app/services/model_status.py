from __future__ import annotations
from sqlalchemy.orm import Session
from ..ml.registry import registry
from ..models import ModelEvaluation, ModelRegistryEntry, utcnow
from .settings_service import get_settings


def evaluations(db: Session) -> list[dict]:
    return [{"id": e.id, "model_name": e.model_name, "model": e.model_name, "model_version": e.model_version,
             "dataset_name": e.dataset_name, "dataset": e.dataset_name, "dataset_version": e.dataset_version,
             "status": e.status, "evaluated_at": e.evaluated_at.isoformat() if e.evaluated_at else None,
             "precision": e.precision, "recall": e.recall, "f1": e.f1, "false_positive_rate": e.false_positive_rate,
             "seconds_per_minute_footage": e.seconds_per_minute_footage, "sample_count": e.sample_count,
             "positive_count": e.positive_count, "thresholds": e.thresholds, "notes": e.notes}
            for e in db.query(ModelEvaluation).order_by(ModelEvaluation.id.desc()).all()]


def snapshot(db: Session) -> list[dict]:
    return registry.snapshot(get_settings(db), evaluations(db))


def warnings(models: list[dict]) -> list[str]:
    out = []
    for m in models:
        if m["requested"] and m["state"] != "LOADED":
            out.append(f"{m['title']}: {m['state']} - {m['detail']}")
        elif m["state"] == "LOADED" and m["key"] in ("fight", "smoking") and m["evaluation"]["state"] == "NOT_EVALUATED":
            out.append(f"{m['title']} is loaded but has no recorded evaluation (unvalidated predictions)")
    return out


def persist_registry(db: Session, models: list[dict]) -> None:
    """Remember the last known state of every module (survives restarts; shown in diagnostics)."""
    for m in models:
        row = db.get(ModelRegistryEntry, m["key"]) or ModelRegistryEntry(module=m["key"], state=m["state"])
        row.model_name, row.model_version, row.weight_file = m.get("name"), m.get("version"), m.get("weight_file")
        row.state, row.detail, row.evaluation_state, row.updated_at = m["state"], (m.get("detail") or "")[:500], m["evaluation"]["state"], utcnow()
        db.add(row)
    db.commit()
