"""Error-message hygiene (stdlib only)."""
from __future__ import annotations
from .. import config


def sanitize_error(msg: str) -> str:
    """Never leak local filesystem paths or long stack text to the UI."""
    msg = str(msg)
    for p in sorted({str(config.BASE_DIR), str(config.DATA_DIR), str(config.MODELS_DIR)}, key=len, reverse=True):
        msg = msg.replace(p, "<app>").replace(p.replace("\\", "/"), "<app>")
    return msg.replace("\n", " ")[:400]
