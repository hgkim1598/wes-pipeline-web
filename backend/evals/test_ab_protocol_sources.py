"""Where each arm's code comes from, and what a protocol file may never become.

A protocol names each arm's source (`arms.<arm>.source`). Until 2026-11-23 the
runner read only arm A's commit and always copied arm B from the working tree,
whatever arm B's source said. A protocol that pinned arm B to a commit would
have been prepared from the working tree without a word. These tests hold the
runner to the protocol's own words, keep the fixed protocol files byte-for-byte
what experiments locked, and keep a draft protocol from preparing anything.

No model, no CLI, no experiment store outside tmp_path.
"""

from __future__ import annotations

import copy
import hashlib
import json

import pytest

from evals.ab_compare import runner

V3 = json.loads((runner.PROTOCOLS / "ledger_applicability_v3.json").read_text(encoding="utf-8"))
V4_PATH = runner.PROTOCOLS / "ledger_applicability_v4.json"
# main after PR #3: the last commit whose tree v3's classification was checked
# against in CI (GitHub Actions, green), i.e. arm B as v3 describes it.
V3_REVIEWED_B = "91ffab6d0dc18c3784bb19eca94ed0e5193a2b12"

# sha256 of each fixed protocol file. Experiments record this hash at prepare and
# refuse to run if the file changes (runner.verify_integrity), so editing a fixed
# protocol breaks every experiment made with it. A new version is a new file.
FIXED_PROTOCOL_SHA256 = {
    "ledger_applicability_v1.json": "c530f5a1c02cfabb38aeabedd9927547bcb32122c74d7ee3dd1543b3f0a43964",
    "ledger_applicability_v2.json": "8fad60f5045c16b5a988a40211c4ec2d4f39cc9371d299ec48bee170973ccdeb",
    "ledger_applicability_v3.json": "ff426cfbaa101058fc1c334146d0e7915d5e8778ad197110f1921201cf0437b1",
    # Fixed 2026-11-23 (approved): arm B pinned to V3_REVIEWED_B.
    "ledger_applicability_v4.json": "6b9b2c9baf8b5bfc70f6099cc533376465a6ed9a3538bb40154b6d073bf9b67f",
}


@pytest.mark.parametrize("name, sha", sorted(FIXED_PROTOCOL_SHA256.items()))
def test_a_fixed_protocol_file_is_never_edited(name, sha):
    data = (runner.PROTOCOLS / name).read_bytes()
    assert hashlib.sha256(data).hexdigest() == sha, (
        f"{name} changed. Experiments prepared with it lock this hash and will refuse to run. "
        "Restore it and write the change as a new protocol version "
        "(evals/ab_compare/protocols/README.md)."
    )


def _with_b(source: dict) -> dict:
    protocol = copy.deepcopy(V3)
    protocol["arms"]["B"]["source"] = source
    return protocol


@pytest.mark.parametrize(
    "source",
    [
        {"kind": "git"},                      # no commit
        {"kind": "git", "commit": ""},
        {"kind": "svn", "commit": "abc"},     # a kind the runner does not implement
        {},
    ],
)
def test_an_arm_source_the_runner_does_not_implement_is_refused(source):
    with pytest.raises(runner.AbError, match="arm B"):
        runner.dry_diff(_with_b(source))


def test_arm_a_must_be_a_commit():
    protocol = copy.deepcopy(V3)
    protocol["arms"]["A"]["source"] = {"kind": "workingTree"}
    with pytest.raises(runner.AbError, match="arm A"):
        runner.dry_diff(protocol)


def test_an_arm_b_pinned_to_a_commit_is_read_from_that_commit():
    pinned = runner.dry_diff(_with_b({"kind": "git", "commit": V3_REVIEWED_B}))
    differing = set(pinned["changed"]) | set(pinned["added"]) | set(pinned["removed"])
    # Files that exist only after that commit cannot be part of an arm pinned to it.
    assert "backend/app/services/job_state.py" not in differing
    # And what v3 already classified is still there.
    assert "backend/app/services/explanation/run_ledger.py" in differing
    assert runner.classify_diff(pinned, V3)["unclassified"] == []


# --- v4: v3 with arm B pinned (fixed 2026-11-23) --------------------------------------


def _v4() -> dict:
    return json.loads(V4_PATH.read_text(encoding="utf-8"))


def test_v4_is_fixed_and_the_default():
    v4 = _v4()
    assert "draft" not in v4 and "draftNote" not in v4
    assert v4["fixedAt"] == "2026-11-23"
    assert runner.DEFAULT_PROTOCOL == V4_PATH


def test_v4_changes_only_what_it_says_it_changes():
    v4 = _v4()
    assert v4["supersedes"]["id"] == V3["id"]
    assert v4["arms"]["B"]["source"] == {"kind": "git", "commit": V3_REVIEWED_B}
    metadata = {"protocolVersion", "id", "title", "fixedAt", "supersedes", "note", "arms"}
    for key in set(V3) | set(v4):
        if key not in metadata:
            assert v4.get(key) == V3.get(key), key
    assert v4["arms"]["A"] == V3["arms"]["A"]
    assert {k: v for k, v in v4["arms"]["B"].items() if k != "source"} == {
        k: v for k, v in V3["arms"]["B"].items() if k != "source"
    }


def test_v4_explains_every_arm_difference_whatever_the_working_tree_holds():
    diff = runner.dry_diff(_v4())
    assert runner.classify_diff(diff, _v4())["unclassified"] == []


def test_a_draft_protocol_prepares_nothing(tmp_path, monkeypatch):
    store = tmp_path / "store"
    monkeypatch.setattr(runner.config, "EVAL_AB_STORE", store)
    draft = tmp_path / "draft_protocol.json"
    draft.write_text(json.dumps({**_v4(), "draft": True, "fixedAt": None}), encoding="utf-8")
    with pytest.raises(runner.AbError, match="draft"):
        runner.prepare("draft-check", draft, mock=False)
    assert not (store / "draft-check").exists()


# --- the equivalence tool's verdict (pure; the probe itself needs two trees) ----------


def test_equivalence_reports_every_differing_field_and_missing_case():
    from evals.ab_compare import equivalence

    same = {"outcomeStatus": "failed", "payload": "p", "allowed": "a", "explanation": "e", "context": "c", "tools": {"s": "t"}}
    changed = {**same, "outcomeStatus": "running", "tools": {"s": "u"}}
    result = equivalence.compare({"x": same, "y": same, "z": same}, {"x": same, "y": changed})
    assert result == {"x": [], "y": ["outcomeStatus", "tools"], "z": ["case"]}
