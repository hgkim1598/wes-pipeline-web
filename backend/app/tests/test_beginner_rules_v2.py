"""The second beginner revision: what the rules ask for, and the facts they rest on.

The prompt rules and the knowledge wording changed together (prompt.py module
docstring). These tests pin the parts a later edit could quietly undo, and the
pipeline facts the new NEXT CHECKS rule depends on. They do not show that
answers got better -- only a new model run can show that.
"""

from __future__ import annotations

import re

import pytest

from .. import config
from ..services.explanation import knowledge
from ..services.explanation.llm import prompt


@pytest.fixture(scope="module")
def main_sh() -> str:
    return config.PIPELINE_SH.read_text(encoding="utf-8")


# --- the rules ---------------------------------------------------------------


def test_the_beginner_rules_carry_no_digits():
    """A number in the instructions could be copied into an answer about a run
    that does not have it, and the number gate would discard the answer."""
    assert not re.search(r"\d", prompt._TAIL)


@pytest.mark.parametrize(
    "rule",
    [
        "WARNINGS",
        "how many steps\n  ended with a warning and name each of those steps",
        "never call the number of warning steps a number of warnings",
        "Do not turn a data label into Korean word for word",
        "read에\n  덮이다",
        "what it means: each position counted one by one",
        "whether the data gives a standard to judge it by",
        "do not write that path",
        "Do not write a setting's internal key",
    ],
)
def test_the_second_revision_rules_are_in_the_shared_tail(rule):
    """In _TAIL, so the tool and no-tool variants are judged on the same rules."""
    assert rule in prompt._TAIL
    assert rule in prompt.CONSTRAINTS and rule in prompt.CONSTRAINTS_NO_TOOL
    assert rule not in prompt._HEAD


def test_the_new_rules_do_not_invite_a_verdict_on_a_measurement():
    """'Whether it can be judged' must not turn into judging it."""
    assert "instead of calling it high or low" in prompt._TAIL


# --- the knowledge the model copies from --------------------------------------

_INTERNAL_NAMES = ("resource bundle", "dbsnp_vcf", "ID column", "--dbsnp", "[NOTE]")


def test_the_dbsnp_check_action_and_scope_carry_no_internal_names():
    """Day 3 copied these into its next checks verbatim (human_review_v1 HR15).
    possibleCauses keeps the technical wording: it names what the pipeline does."""
    entry = knowledge.diagnostic("DBSNP_NOT_CONFIGURED")
    assert entry is not None and entry.grounding is not None
    reader_facing = [c.statement for c in entry.grounding.checks]
    reader_facing += [c.statement for c in entry.grounding.scope]
    reader_facing += [a.statement for a in entry.grounding.actions]
    reader_facing += [a.effect for a in entry.grounding.actions]
    for text in reader_facing:
        for name in _INTERNAL_NAMES:
            assert name not in text, (name, text)


def test_the_dbsnp_check_names_the_report_as_the_screen_lists_it(main_sh):
    """DBSNP_NOT_CONFIGURED is recorded during variant calling, so input
    validation passed -- and on that path main.sh registers the report as a
    downloadable artifact under this display name."""
    entry = knowledge.diagnostic("DBSNP_NOT_CONFIGURED")
    assert entry is not None and entry.grounding is not None
    (check,) = entry.grounding.checks
    assert check.locator.kind == "stepFile"
    assert check.locator.id == "00_input_validation/resource_validation.txt"
    assert "'Resource validation report'" in check.statement
    assert 'add_artifact validation_report "Resource validation report" "$report" 1 ' in main_sh


def test_a_failed_resource_validation_does_not_register_the_report(main_sh):
    """The failure path returns before the artifact is added, which is what the
    resource_bundle failure's check now tells the reader."""
    start = main_sh.index('local report="$RUN_DIR/00_input_validation/resource_validation.txt"')
    fail = main_sh.index('step_check_fail "resource_bundle"', start)
    returned = main_sh.index("return 1", fail)
    added = main_sh.index('add_artifact validation_report "Resource validation report"', start)
    assert fail < returned < added

    entry = knowledge.failure("resource_bundle")
    assert entry is not None and entry.grounding is not None
    step_file_checks = [c for c in entry.grounding.checks if c.locator.kind == "stepFile"]
    assert step_file_checks
    for check in step_file_checks:
        assert "산출물로 등록되지 않" in check.statement
        assert "서버 관리자" in check.statement


def test_every_step_file_locator_is_one_of_the_two_handled_above():
    """The NEXT CHECKS rule defers to the check's statement for a stepFile. A new
    stepFile locator needs the same decision -- on screen or server only."""
    seen = set()
    for entry in knowledge.all_diagnostics():
        for check in entry.grounding.checks if entry.grounding else []:
            if check.locator.kind == "stepFile":
                seen.add(("diagnostic", entry.code, check.locator.id))
    for failure in knowledge.all_failures():
        for check in failure.grounding.checks if failure.grounding else []:
            if check.locator.kind == "stepFile":
                seen.add(("failure", failure.code, check.locator.id))
    assert seen == {
        ("diagnostic", "DBSNP_NOT_CONFIGURED", "00_input_validation/resource_validation.txt"),
        ("failure", "resource_bundle", "00_input_validation/resource_validation.txt"),
    }
