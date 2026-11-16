"""Private evaluation locations, separate from publishable evaluation code.

No source is discovered or guessed. Missing configuration disables real-data
integration; it never substitutes a synthetic run for a real measurement.
Existing case aliases remain stable so local answer keys and baselines retain
their meaning. The JSON and every referenced source remain local.
"""

from __future__ import annotations

import json
import os
from pathlib import Path

from app import config


class LocalDataError(ValueError):
    """Invalid local configuration; messages deliberately omit its values."""


def settings() -> dict:
    raw = os.environ.get("WES_EVAL_LOCAL_CONFIG", "").strip()
    path = Path(raw) if raw else config.ROOT / "config/local/wes_eval_runs.json"
    if not path.is_absolute():
        path = config.ROOT / path
    if not path.is_file():
        if raw:
            raise LocalDataError("Explicit local evaluation configuration is missing")
        return {"schemaVersion": 1, "runs": {}}
    try:
        doc = json.loads(path.read_text(encoding="utf-8"))
        if not isinstance(doc, dict) or doc.get("schemaVersion") != 1:
            raise ValueError
        runs = doc.get("runs")
        if not isinstance(runs, dict):
            raise ValueError
        for name, row in runs.items():
            if not isinstance(name, str) or not isinstance(row, dict):
                raise ValueError
            if not isinstance(row.get("runId"), str) or not row["runId"].strip():
                raise ValueError
            if "captureDir" in row and not isinstance(row["captureDir"], str):
                raise ValueError
        if "archive" in doc and not isinstance(doc["archive"], str):
            raise ValueError
        return doc
    except (ValueError, OSError, UnicodeError):
        raise LocalDataError("Invalid local evaluation configuration") from None


def run_id(case: str) -> str:
    return settings()["runs"].get(case, {}).get("runId", "")


def source_path(key: str, *, case: str | None = None) -> Path:
    doc = settings()
    row = doc if case is None else doc["runs"].get(case, {})
    raw = row.get(key, "")
    if not raw:
        # A nonexistent sentinel, never an accidental search of the repository.
        return config.ROOT / "config/local/unconfigured" / key
    path = Path(raw)
    return path if path.is_absolute() else config.ROOT / path
