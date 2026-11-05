"""Every recorded real answer still passes gates 6 and 7.

These are answers a real model wrote: the baselines and the 2026-11-04 A/B
records. None of them states a wrong value, warning count or topic citation
(each was read by a person or checked against the run record), so a finding
here would be the new gates blocking a correct answer. The records are read,
never written.

The real-run answers need the restored capture for their payload and are
skipped without it, like test_real_runs.py.
"""

from __future__ import annotations

import json
from pathlib import Path
from typing import Any

import pytest

from app.services.explanation.llm import claims

from . import real_runs
from .explanation_quality import _payload_for_case

HERE = Path(__file__).resolve().parent
RECORDS = sorted((HERE / "baselines").glob("*.json")) + sorted(
    (HERE / "experiments" / "ab_2026-11-04").glob("[AB]_r*.json")
)


def _ids(node: Any, out: set[str]) -> set[str]:
    if isinstance(node, dict):
        ref = node.get("evidenceId")
        if isinstance(ref, str):
            out.add(ref)
        for value in node.values():
            _ids(value, out)
    elif isinstance(node, list):
        for value in node:
            _ids(value, out)
    return out


def _answered(path: Path) -> dict[str, Any] | None:
    record = json.loads(path.read_text(encoding="utf-8"))
    return record if record.get("output") else None


@pytest.mark.parametrize("path", RECORDS, ids=lambda p: p.name[:48])
def test_a_recorded_answer_passes_gates_6_and_7(path: Path):
    record = _answered(path)
    if record is None:
        pytest.skip("the record has no answer (the model was not available)")
    case = record["case"]
    if case in real_runs.REAL_RUNS and not real_runs.capture_available(real_runs.REAL_RUNS[case]):
        pytest.skip("capture not available")
    payload = _payload_for_case(case)
    assert payload is not None
    allowed = _ids(payload, set()) | set((record.get("toolUse") or {}).get("toolEvidenceIds") or [])

    answer = record["output"]
    assert claims.find_run_fact_mismatches(answer, payload) == []
    assert claims.find_evidence_mismatches(answer, payload, allowed) == []


def test_the_records_are_there():
    assert len([p for p in RECORDS if _answered(p)]) >= 17
