from __future__ import annotations
import json
from sqlalchemy.orm import Session
from .. import config
from ..models import Setting


def get_settings(db: Session) -> dict:
    row = db.get(Setting, "app")
    stored = json.loads(row.value) if row else {}
    return config.deep_merge(config.DEFAULT_SETTINGS, stored)


def _validate(default, new, path=""):
    if isinstance(default, dict):
        if not isinstance(new, dict):
            raise ValueError(f"{path or 'settings'} must be an object")
        out = {}
        for k, v in new.items():
            if k not in default:
                raise ValueError(f"Unknown setting: {path}{k}")
            out[k] = _validate(default[k], v, f"{path}{k}.")
        return out
    if isinstance(default, bool):
        if not isinstance(new, bool):
            raise ValueError(f"{path[:-1]} must be true/false")
        return new
    if isinstance(default, (int, float)):
        if isinstance(new, bool) or not isinstance(new, (int, float)):
            raise ValueError(f"{path[:-1]} must be a number")
        if new < 0:
            raise ValueError(f"{path[:-1]} must not be negative")
        return type(default)(new) if isinstance(default, int) else float(new)
    if isinstance(default, str):
        if not isinstance(new, str) or len(new) > 300 or ".." in new.replace("\\", "/").split("/"):
            raise ValueError(f"{path[:-1]} must be a plain string (no '..')")
        return new
    raise ValueError(f"Unsupported setting {path}")


def update_settings(db: Session, patch: dict) -> dict:
    clean = _validate(config.DEFAULT_SETTINGS, patch)
    row = db.get(Setting, "app")
    merged = config.deep_merge(json.loads(row.value) if row else {}, clean)
    full = config.deep_merge(config.DEFAULT_SETTINGS, merged)
    for r in ("beige", "navy"):
        c = full["uniform"][r]
        if c["h_min"] > c["h_max"] or c["s_min"] > c["s_max"] or c["v_min"] > c["v_max"] or c["h_max"] > 179 or c["s_max"] > 255 or c["v_max"] > 255:
            raise ValueError(f"Invalid {r} HSV range (H 0-179, S/V 0-255, min <= max)")
    for k in ("fight", "smoking"):
        a = full["activity"][k]
        if not (0 <= a["uncertain_low"] <= a["threshold"] <= 1):
            raise ValueError(f"{k}: need 0 <= uncertain_low <= threshold <= 1")
    if row:
        row.value = json.dumps(merged)
    else:
        db.add(Setting(key="app", value=json.dumps(merged)))
    db.commit()
    return full
