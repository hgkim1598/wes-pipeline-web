"""wes_statement_kinds.json: every explanatory sentence is classified, for its words.

The classification is policy kept apart from the text (applicability.py). These
tests keep the two from drifting: a sentence edited without re-deciding its entry,
a new sentence nobody classified, or a main.sh impact line nobody registered all
fail here rather than reaching a run's explanation as `unknown`.
"""

from __future__ import annotations

import re
from pathlib import Path

import pytest

from ..services.explanation import applicability
from ..services.explanation.run_ledger import build_ledger

REPO = Path(__file__).resolve().parents[3]


def test_every_inventory_sentence_is_classified_for_its_current_words():
    missing, stale = [], []
    for target, text in applicability.inventory():
        entry = applicability.statement_kind(target)
        if entry is None:
            missing.append(target)
        elif entry.sha != applicability.sha12(text):
            stale.append(target)
    assert not missing, f"unclassified: {missing[:5]}"
    assert not stale, f"edited without re-deciding: {stale[:5]}"


def test_no_classification_for_a_sentence_that_no_longer_exists():
    targets = {target for target, _ in applicability.inventory()}
    orphans = [e.target for e in applicability.all_statement_kinds() if e.target not in targets]
    assert not orphans


def test_conditions_only_where_a_run_claim_is_made():
    """A condition on a general sentence would hide true text for no reason."""
    for entry in applicability.all_statement_kinds():
        if entry.appliesWhen is not None:
            assert entry.target.startswith(("diagnostics/", "failures/")), entry.target
            assert applicability.validate_rule(entry.appliesWhen) == []


def _main_sh_warnings() -> set[tuple[str, str]]:
    sh = (REPO / "script" / "main.sh").read_text(encoding="utf-8")
    sh = re.sub(r"\\\n[ \t]*", " ", sh)
    out = set()
    for code, rest in re.findall(r'step_warning\s+"([A-Z_]+)"\s+((?:"[^"]*"\s*){3})', sh):
        parts = re.findall(r'"([^"]*)"', rest)
        out.add((code, parts[1]))
    return out


def test_every_fixed_impact_line_in_main_sh_is_registered_as_current():
    found = _main_sh_warnings()
    assert found, "the parser found no step_warning call"
    current = {(t.code, t.text) for t in applicability.all_pipeline_texts() if t.status == "current"}
    assert found - current == set(), "main.sh writes an impact line nobody classified"
    assert current - found == set(), "registered as current but main.sh no longer writes it"


@pytest.mark.parametrize(
    "rule, problem",
    [
        ({"stepRan": "01_raw_qc"}, "unsupported operator"),
        ({"stepExecution": {"step": "01_raw_qc", "in": ["done"]}}, "unknown state"),
        ({"stepExecution": {"step": "09_nowhere", "in": ["ranCompleted"]}}, "unknown step"),
        ({"all": []}, "non-empty"),
        ({"not": {"runStatus": {"in": ["exploded"]}}}, "unknown status"),
    ],
)
def test_unsupported_conditions_are_rejected(rule, problem):
    errors = applicability.validate_rule(rule)
    assert errors and problem in errors[0]


def test_unknown_never_decides_applicable():
    unknown = build_ledger("failed", None, [("00_input_validation", "pending"), ("01_raw_qc", "pending")])
    rule = {"stepExecution": {"step": "01_raw_qc", "in": ["ranCompleted"]}}
    decision, reason = applicability.decide(rule, unknown, "00_input_validation")
    assert decision == "unknown" and reason
    # Nor does an unsupported operator that slipped past validation.
    decision, _ = applicability.decide({"stepRan": "01_raw_qc"}, unknown, None)
    assert decision == "unknown"


def test_three_valued_logic_lets_a_settled_operand_win():
    ledger = build_ledger(
        "failed", "failed",
        [("00_input_validation", "failed"), ("01_raw_qc", "pending")],
    )
    ran_01 = {"stepExecution": {"step": "01_raw_qc", "in": ["ranCompleted"]}}
    at_01 = {"occurredAt": ["01_raw_qc"]}
    # occurrence unknown, 01 settled false -> any() is not true; all() is false.
    assert applicability.decide({"all": [at_01, ran_01]}, ledger, None)[0] == "notApplicable"
    assert applicability.decide({"any": [at_01, ran_01]}, ledger, None)[0] == "unknown"
    assert applicability.decide({"any": [at_01, ran_01]}, ledger, "01_raw_qc")[0] == "applicable"
