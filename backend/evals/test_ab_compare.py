"""A/B runner contract: outcomes, call states, approvals, integrity, failures.

No model and no CLI. The runner's worker process is replaced by a fake that
follows the worker's contract (claim -> model-started marker -> raw result)
and can fail at each step; the real worker's own refusals are tested
in-process, up to the point where it would import a tree. Run from backend/:

    .venv/Scripts/python.exe -m pytest evals/test_ab_compare.py
"""

from __future__ import annotations

import contextlib
import hashlib
import json
import random
import subprocess
from pathlib import Path

import pytest

from evals.ab_compare import contract, runner, scoring, worker

PROTOCOL = json.loads(runner.DEFAULT_PROTOCOL.read_text(encoding="utf-8"))
B94559 = next(c for c in PROTOCOL["cases"] if c["case"] == "real_b94559")
FAILED_04 = next(c for c in PROTOCOL["cases"] if c["case"] == "agent_failed_step")


def answer(*statements: str, summary: str = "요약") -> dict:
    return {
        "summary": summary,
        "importantFindings": [{"statement": s, "evidenceRefs": ["run:status"]} for s in statements],
        "limitations": [],
        "nextChecks": [],
        "uncertainties": [],
    }


# --- protocol ---------------------------------------------------------------


def test_protocol_fixes_everything_the_experiment_needs_before_any_call():
    for key in ("arms", "conditions", "repeats", "cases", "detectors", "metrics", "successCriteria", "claimUnit",
                "outcomeContract", "evaluationRule", "diffClassification", "modelIdentity"):
        assert PROTOCOL[key], key
    cond = PROTOCOL["conditions"]
    assert cond["repair"] is False and cond["docRag"] is False and cond["offerTools"] is True
    assert PROTOCOL["arms"]["A"]["source"] == {"kind": "git", "commit": "158cba7302e0f2096ec1f8790dc1251cb4a34a41"}
    metric_ids = {m["id"] for m in PROTOCOL["metrics"]}
    assert {c["metric"] for c in PROTOCOL["successCriteria"]} <= metric_ids
    assert any(c["synthetic"] for c in PROTOCOL["cases"]) and any(not c["synthetic"] for c in PROTOCOL["cases"])
    s8 = next(c for c in PROTOCOL["successCriteria"] if c["id"] == "S8")
    assert s8["rule"] == "B_rate <= A_rate"  # answered calls only; provider errors are not gate results
    assert {r["class"] for r in PROTOCOL["diffClassification"]} <= set(runner.DIFF_CLASSES)


def test_v2_changes_only_what_it_says_it_changes():
    v1 = json.loads((runner.PROTOCOLS / "ledger_applicability_v1.json").read_text(encoding="utf-8"))
    for key in ("conditions", "repeats", "order", "cases", "detectors", "wrongCauseCandidates", "claimUnit", "arms"):
        assert PROTOCOL[key] == v1[key], key
    same = {c["id"]: c for c in v1["successCriteria"] if c["id"] != "S8"}
    assert all(c == same[c["id"]] for c in PROTOCOL["successCriteria"] if c["id"] != "S8")


def test_v3_changes_only_the_arm_difference_it_names():
    """v3 (review H1, 2026-11-22) adds the tool channel to B's intended change; nothing measured changes."""
    v2 = json.loads((runner.PROTOCOLS / "ledger_applicability_v2.json").read_text(encoding="utf-8"))
    changed = {"protocolVersion", "id", "fixedAt", "supersedes", "note", "intendedDifference", "diffClassification"}
    assert set(PROTOCOL) == set(v2)
    assert all(PROTOCOL[k] == v2[k] for k in set(v2) - changed)
    added = [r for r in PROTOCOL["diffClassification"] if r not in v2["diffClassification"]]
    assert {r["path"] for r in added} == {"backend/app/services/agent/step_evidence.py", "backend/app/services/agent/run_scope.py"}
    assert all(r["class"] == "intended" for r in added)
    assert all(r in PROTOCOL["diffClassification"] for r in v2["diffClassification"])


def test_plan_interleaves_arms_and_gives_unique_blind_codes():
    plan = runner.build_plan(PROTOCOL, random.Random(1))
    assert len(plan) == PROTOCOL["repeats"] * len(PROTOCOL["cases"]) * 2
    first = [c["arm"] for c in plan if c["case"] == "real_b94559"]
    assert first == ["A", "B", "B", "A", "A", "B"]
    assert len({c["blindCode"] for c in plan}) == len(plan)
    assert len({c["callId"] for c in plan}) == len(plan)
    assert [c["blindCode"] for c in plan] != sorted(c["blindCode"] for c in plan)
    # the pilot's ids are fixed by the plan order, not by chance
    assert [c["callId"] for c in plan[:2]] == ["001-real-b94559-a-r1", "002-real-b94559-b-r1"]


# --- scoring ----------------------------------------------------------------

# Sentences from the two gate-passing answers recorded on 2026-11-15.
PAST = [
    "이 경고는 통합 리포트만 만들어지지 않는다는 뜻이며, 개별 FastQC 실행에는 영향이 없다고 기록되어 있습니다.",
    "심각도는 정보 수준이며, 개별 FastQC 리포트는 계속 만들어집니다.",
    "MultiQC가 없다는 것은 통합 리포트만 만들어지지 않는다는 뜻이며, 개별 FastQC 결과가 없다는 뜻은 아닙니다.",
]


def test_non_run_detector_counts_the_recorded_shapes():
    scores = scoring.score_answer(answer(*PAST), B94559, PROTOCOL)
    assert scores["nonRunClaims"] == 3
    assert {h["detector"] for h in scores["detectorHits"]} == {"NR-FASTQC"}


def test_correct_statements_are_not_counted():
    ok = answer(
        "입력 검증 단계가 실패했고, 원본 품질 검사(FastQC) 단계는 시작되지 않았습니다.",
        "분석 결과는 없습니다.",
        "변이 검출 단계는 실행되지 않았습니다.",
    )
    scores = scoring.score_answer(ok, B94559, PROTOCOL)
    assert scores["nonRunClaims"] == 0
    assert scores["execContradictions"] == 0


def test_detectors_only_apply_when_the_step_did_not_run():
    scores = scoring.score_answer(answer("개별 FastQC 리포트는 정상적으로 만들어졌습니다."), FAILED_04, PROTOCOL)
    assert scores["nonRunClaims"] == 0


def test_required_causes_and_wrong_cause_candidates():
    text = answer(
        "필수 분석 도구 여덟 개를 PATH에서 찾지 못했습니다.",
        "target BED와 coverage BED 파일이 없거나 비어 있습니다.",
        "contig 이름 불일치 때문에 실패했습니다.",
    )
    scores = scoring.score_answer(text, B94559, PROTOCOL)
    assert scores["requiredCauses"]["byCause"] == {
        "required_tools": True, "target_bed": True, "coverage_bed": True, "bcftools": False,
    }
    assert [w["candidate"] for w in scores["wrongCauseCandidates"]] == ["WC-GENERIC-RESOURCE"]


def test_no_answer_is_not_measured_not_zero():
    assert scoring.score_answer(None, B94559, PROTOCOL) == {"measured": False}


def test_rejected_answer_is_scored_separately_from_the_served_one():
    record = {
        "available": False,
        "errorCategory": "runFactMismatch",
        "output": None,
        "trace": {"firstRejection": "runFactMismatch", "durationMs": 1200},
        "rejectedOutput": {"answer": answer(PAST[1])},
    }
    scores = scoring.score_record(record, B94559, PROTOCOL)
    assert scores["outcome"]["outcome"] == "gateRejected"
    assert scores["gate"] == {"evaluated": True, "passed": False, "errorCategory": "runFactMismatch", "firstRejection": "runFactMismatch"}
    assert scores["served"] == {"measured": False}
    assert scores["rejected"]["nonRunClaims"] == 1
    assert scores["durationMs"] == 1200


@pytest.mark.parametrize("category", sorted(contract.PROVIDER_ERROR_CATEGORIES))
def test_provider_errors_are_not_gate_decisions(category):
    """H1: scoring version 1 wrote gate.passed = False for a timeout."""
    record = {"available": False, "errorCategory": category, "output": None, "rejectedOutput": None, "trace": {}}
    scores = scoring.score_record(record, B94559, PROTOCOL)
    assert scores["outcome"]["outcome"] == "providerError"
    assert scores["gate"]["evaluated"] is False and scores["gate"]["passed"] is None


def test_evidence_source_matches_the_frontend_split():
    assert scoring.evidence_source("run:status") == "record"
    assert scoring.evidence_source("fail:required_tools") == "mixed"
    assert scoring.evidence_source("manual:x#y") == "doc"
    assert scoring.evidence_source("term:read") == "knowledge"
    assert scoring.evidence_source("weird") == "other"


# --- contract: outcome and evaluation ---------------------------------------------


@pytest.mark.parametrize(
    ("record", "outcome", "produced"),
    [
        ({"available": True, "output": answer("x")}, "served", True),
        ({"available": False, "errorCategory": "runFactMismatch", "rejectedOutput": {"answer": answer("x")}}, "gateRejected", True),
        ({"available": False, "errorCategory": "invalidSynthesis", "rejectedOutput": {"answer": None}}, "gateRejected", False),
        ({"available": False, "errorCategory": "timeout"}, "providerError", False),
        # contradictions are never forced into a bucket
        ({"available": False, "errorCategory": "timeout", "rejectedOutput": {"answer": answer("x")}}, "unclassified", False),
        ({"available": False, "errorCategory": "somethingNew"}, "unclassified", False),
        ({"available": True, "output": None}, "unclassified", False),
        ({}, "unclassified", False),
    ],
)
def test_classify_outcome(record, outcome, produced):
    got = contract.classify_outcome(record)
    assert got["outcome"] == outcome and got["answerProduced"] is produced


def _stored(record: dict, *, integrity: dict | None = {"ok": True}) -> dict:
    call = {"record": {"leakCount": 0} | record}
    if integrity is not None:
        call["integrity"] = integrity
    return call


def test_evaluation_says_what_counts_and_why_not():
    served = {"available": True, "output": answer("x")}
    assert contract.evaluation_of(_stored(served), mock=False)["countsForContent"] is True
    timeout = contract.evaluation_of(_stored({"available": False, "errorCategory": "timeout"}), mock=False)
    assert (timeout["countsForGate"], timeout["exclusion"]) == (False, "providerError")
    leak = contract.evaluation_of(_stored(served | {"leakCount": 2}), mock=False)
    assert leak["exclusion"] == "privacy"
    bad = contract.evaluation_of(_stored(served, integrity={"ok": False}), mock=False)
    assert bad["exclusion"] == "integrity"
    # first-version records: never checked after the call
    assert contract.evaluation_of(_stored(served, integrity=None), mock=False)["exclusion"] == "integrityUnchecked"
    assert contract.evaluation_of(_stored(served, integrity=None), mock=True)["exclusion"] is None
    unparsed = contract.evaluation_of(_stored({"available": False, "errorCategory": "invalidSynthesis", "rejectedOutput": {"answer": None}}), mock=False)
    assert unparsed["countsForGate"] is True and unparsed["countsForContent"] is False


# --- contract: locks ------------------------------------------------------------


def test_os_lock_is_exclusive_and_probe_never_creates_files(tmp_path):
    lock = tmp_path / "x.lock"
    assert contract.is_held(lock) is False and not lock.exists()
    with contract.os_lock(lock):
        assert contract.is_held(lock) is True
        with pytest.raises(BlockingIOError):
            with contract.os_lock(lock):
                pass
    assert contract.is_held(lock) is False


# --- an experiment on disk that passes every integrity check ------------------------

PAYLOAD_FIELDS = {
    "sourceDigest": "s",
    "userPromptDigest": "u",
    "constraintsDigest": "c",
    "promptHash": "p",
    "knowledgeHash": "k",
    "privacy": "pass",
    "leakCount": 0,
}
SNAPSHOT_A = {"backend/app/services/explanation/llm/contract.py": b"old\n", "backend/app/core.py": b"same\n"}
SNAPSHOT_B = {
    "backend/app/services/explanation/llm/contract.py": b"new\n",
    "backend/app/core.py": b"same\n",
    "backend/app/tests/test_new.py": b"test\n",  # notInCallPath in v2 (prefix backend/app/tests/)
}


def _write_snapshot(folder: Path, files: dict[str, bytes]) -> dict:
    manifest = {}
    for name, content in files.items():
        target = folder / name
        target.parent.mkdir(parents=True, exist_ok=True)
        target.write_bytes(content)
        manifest[name] = {"sha256": hashlib.sha256(content).hexdigest(), "normalisedSha256": runner._normalised_sha(content)}
    return manifest


def make_experiment(store: Path, name: str, *, mock: bool) -> Path:
    root = store / name
    root.mkdir(parents=True)
    (root / "worker.py").write_bytes(runner.WORKER.read_bytes())
    manifests = {"A": _write_snapshot(root / "snapshots" / "A", SNAPSHOT_A), "B": _write_snapshot(root / "snapshots" / "B", SNAPSHOT_B)}
    for arm in runner.ARMS:
        runner.write_new(root / "manifests" / f"{arm}.json", manifests[arm])
    local = root / "local_config.json"
    runner.write_new(local, {"schemaVersion": 1, "runs": {}})
    diff = runner.arm_diff(manifests["A"], manifests["B"])
    for case in PROTOCOL["cases"]:
        for arm in runner.ARMS:
            runner.write_new(root / "payloads" / f"{case['case']}.{arm}.json", {"payloadDigest": f"{case['case']}-{arm}", **PAYLOAD_FIELDS})
    runner.write_new(
        root / "payloads" / "checks.json",
        {"cases": {c["case"]: {"constraintsEqual": True, "promptHashEqual": True, "privacy": {"A": "pass", "B": "pass"}, "leaks": {"A": 0, "B": 0}} for c in PROTOCOL["cases"]}},
    )
    runner.write_new(
        root / "experiment.json",
        {
            "experimentId": name,
            "mock": mock,
            "createdAt": "t",
            "attemptProtocol": contract.ATTEMPT_PROTOCOL,
            "protocolFile": runner.DEFAULT_PROTOCOL.name,
            "protocolSha256": runner.sha256_file(runner.DEFAULT_PROTOCOL),
            "protocol": PROTOCOL,
            "workerSha256": runner.sha256_file(root / "worker.py"),
            "localConfig": str(local),
            "localConfigSha256": runner.sha256_file(local),
            "arms": {arm: {"manifestSha256": runner._manifest_sha(manifests[arm])} for arm in runner.ARMS},
            "armDiff": diff,
            "diffClassification": runner.classify_diff(diff, PROTOCOL),
            "sharedLocalInputs": {},
            "plan": runner.build_plan(PROTOCOL, random.Random(2)),
        },
    )
    return root


class FakeWorker:
    """Follows the worker contract; `script[callId]` is a list of behaviours, one per attempt.

    served / gateRejected / timeout / usageLimit / providerUnavailable  -> a raw result
    crashAfterModel   marker written, no result, exit 1
    crashBeforeModel  no marker, no result, exit 1
    killedByTimeout   marker written, then the runner's timeout fires
    leakyImport       served, but a notInCallPath file was imported
    """

    def __init__(self, script: dict[str, list[str]] | None = None, payload_digest_override: str | None = None):
        self.script = script or {}
        self.model_calls: list[str] = []
        self.spawns: dict[str, int] = {}
        self.payload_builds = 0
        self.payload_digest_override = payload_digest_override

    def __call__(self, root: Path, arm: str, request: dict, out: Path, *, allow_real: bool) -> int:
        if request["action"] == "payload":
            self.payload_builds += 1
            locked = runner.read_json(root / "payloads" / f"{request['case']}.{arm}.json")
            if self.payload_digest_override:
                locked = locked | {"payloadDigest": self.payload_digest_override}
            out.write_text(json.dumps(locked), encoding="utf-8")
            return 0
        call_id = out.parent.name
        attempt = request["attempt"]
        # what the real worker refuses, the fake asserts the runner never asks for
        assert Path(attempt["claim"]).is_file(), "spawned without a durable claim"
        assert not Path(attempt["started"]).exists() and not out.exists(), "spawned on a used attempt"
        assert not Path(attempt["void"]).exists(), "spawned on a sealed attempt"
        locked = runner.read_json(root / "payloads" / f"{request['case']}.{arm}.json")
        assert request["locked"] == {"payloadDigest": locked["payloadDigest"], "sourceDigest": locked["sourceDigest"]}
        behaviours = self.script.get(call_id, ["served"])
        spawned = self.spawns.get(call_id, 0)
        self.spawns[call_id] = spawned + 1
        behaviour = behaviours[min(spawned, len(behaviours) - 1)]
        if behaviour == "crashBeforeModel":
            return 1
        Path(attempt["started"]).write_text("{}", encoding="utf-8")
        self.model_calls.append(call_id)
        if behaviour == "crashAfterModel":
            return 1
        if behaviour == "killedByTimeout":
            raise subprocess.TimeoutExpired(cmd="worker", timeout=1)
        locked = runner.read_json(root / "payloads" / f"{request['case']}.{arm}.json")
        record = {
            "available": behaviour in ("served", "leakyImport"),
            "errorCategory": None if behaviour in ("served", "leakyImport") else ("runFactMismatch" if behaviour == "gateRejected" else behaviour),
            "output": answer("모의 답변") if behaviour in ("served", "leakyImport") else None,
            "rejectedOutput": {"answer": answer("거부된 답변"), "category": "runFactMismatch", "findings": []} if behaviour == "gateRejected" else None,
            "durationMs": 1000,
            "trace": {"models": ["model-x"]},
            "payloadDigest": locked["payloadDigest"],
            "promptHash": locked["promptHash"],
            "knowledgeHash": locked["knowledgeHash"],
            "leakCount": 0,
            "workerAction": request["action"],
            "mock": request["action"] == "mock",
            "importedTreeFiles": ["backend/app/core.py"] + (["backend/app/tests/test_new.py"] if behaviour == "leakyImport" else []),
        }
        out.write_text(json.dumps(record), encoding="utf-8")
        return 0


PILOT = ["001-real-b94559-a-r1", "002-real-b94559-b-r1"]


@pytest.fixture
def store(tmp_path, monkeypatch):
    monkeypatch.setattr(runner.config, "EVAL_AB_STORE", tmp_path)
    return tmp_path


def _approve(name: str, ids: list[str], n: int) -> str:
    return runner.approve(name, ids, n, confirm=lambda _prompt: str(n))


def _states(root: Path) -> dict[str, str]:
    return {c: contract.call_state(root, c, lock_probe=contract.is_held)["state"] for c in PILOT}


# --- storage, ids, prepare -------------------------------------------------------


def test_write_new_never_replaces(tmp_path):
    target = tmp_path / "a.json"
    runner.write_new(target, {"v": 1})
    with pytest.raises(FileExistsError):
        runner.write_new(target, {"v": 2})
    assert json.loads(target.read_text(encoding="utf-8")) == {"v": 1}


def test_experiment_ids_are_checked_and_mock_ids_are_marked(store):
    for bad in ("../x", "A-B", "x", "a/b"):
        with pytest.raises(runner.AbError):
            runner.experiment_dir(bad)
    with pytest.raises(runner.AbError, match="mock"):
        runner.prepare("ledger-real", runner.DEFAULT_PROTOCOL, mock=True)
    with pytest.raises(runner.AbError, match="mock"):
        runner.prepare("mock-x", runner.DEFAULT_PROTOCOL, mock=False)
    assert not any(store.iterdir())


def test_every_arm_difference_must_be_classified():
    same = {"sha256": "1", "normalisedSha256": "n"}
    diff = runner.arm_diff({"backend/app/core.py": same}, {"backend/app/core.py": same, "backend/app/surprise.py": same, "backend/app/tests/test_x.py": same})
    classified = runner.classify_diff(diff, PROTOCOL)
    assert classified["unclassified"] == ["backend/app/surprise.py"]
    assert classified["byPath"]["backend/app/tests/test_x.py"]["class"] == "notInCallPath"


def test_the_current_working_tree_difference_is_fully_classified():
    """The protocol explains every file that differs from the A commit today
    (the same check `prepare` makes, computed in memory, nothing written)."""
    diff = runner.dry_diff(PROTOCOL)
    assert runner.classify_diff(diff, PROTOCOL)["unclassified"] == []


def test_arm_diff_ignores_line_endings_and_names_gate_files():
    same = {"sha256": "1", "normalisedSha256": "n"}
    a = {"backend/app/x.py": same, "backend/evals/run_eval.py": same}
    b = {"backend/app/x.py": {"sha256": "2", "normalisedSha256": "n"}, "backend/evals/run_eval.py": same}
    diff = runner.arm_diff(a, b)
    assert diff["changed"] == [] and diff["harnessIdentical"] and diff["gateAndPromptCodeIdentical"]
    b["backend/app/services/explanation/llm/prompt.py"] = same
    assert runner.arm_diff(a, b)["gateAndPromptCodeIdentical"] is False


# --- integrity --------------------------------------------------------------------


def test_a_prepared_experiment_passes_integrity(store):
    root = make_experiment(store, "ledger-ok", mock=False)
    fp = runner.verify_integrity(root, runner.read_json(root / "experiment.json"))
    assert fp["notInCallPath"] == ["backend/app/tests/test_new.py"]


@pytest.mark.parametrize(
    "tamper",
    [
        lambda root: (root / "snapshots" / "B" / "backend" / "app" / "core.py").write_bytes(b"changed\n"),
        lambda root: (root / "snapshots" / "B" / "backend" / "app" / "evil.py").write_bytes(b"x = 1\n"),
        lambda root: (root / "snapshots" / "A" / "backend" / "app" / "core.py").unlink(),
        lambda root: (root / "worker.py").write_text("# edited\n", encoding="utf-8"),
        lambda root: (root / "local_config.json").write_text("{}", encoding="utf-8"),
        lambda root: (root / "manifests" / "A.json").write_text("{}", encoding="utf-8"),
    ],
    ids=["changed-file", "extra-file", "missing-file", "worker", "local-config", "manifest"],
)
def test_tampering_stops_everything_before_a_claim(store, monkeypatch, tamper):
    """M2: the snapshots were only checked at prepare time."""
    root = make_experiment(store, "ledger-tamper", mock=False)
    approval = _approve("ledger-tamper", PILOT, 2)
    tamper(root)
    fake = FakeWorker()
    monkeypatch.setattr(runner, "_spawn_worker", fake)
    with pytest.raises(runner.AbError, match="integrity"):
        runner.run("ledger-tamper", approval=approval, mock=False, allow_real=True)
    assert fake.model_calls == [] and fake.payload_builds == 0
    assert not (root / "attempts").exists()


def test_bytecode_caches_in_a_snapshot_are_not_tampering(store):
    root = make_experiment(store, "ledger-pyc", mock=False)
    cache = root / "snapshots" / "B" / "backend" / "app" / "__pycache__"
    cache.mkdir()
    (cache / "core.cpython-312.pyc").write_bytes(b"\0")
    runner.verify_integrity(root, runner.read_json(root / "experiment.json"))


def test_a_changed_model_input_stops_the_call_before_it_is_claimed(store, monkeypatch):
    make_experiment(store, "ledger-input", mock=False)
    approval = _approve("ledger-input", PILOT, 2)
    fake = FakeWorker(payload_digest_override="different")
    monkeypatch.setattr(runner, "_spawn_worker", fake)
    with pytest.raises(runner.AbError, match="model input differs"):
        runner.run("ledger-input", approval=approval, mock=False, allow_real=True)
    assert fake.model_calls == []
    assert contract.claimed_attempts(store / "ledger-input", PILOT[0]) == []


def test_importing_a_file_outside_the_call_path_excludes_the_call(store, monkeypatch):
    root = make_experiment(store, "ledger-imports", mock=False)
    approval = _approve("ledger-imports", PILOT[:1], 1)
    monkeypatch.setattr(runner, "_spawn_worker", FakeWorker({PILOT[0]: ["leakyImport"]}))
    assert runner.run("ledger-imports", approval=approval, mock=False, allow_real=True) == 0
    stored = runner.read_json(root / "calls" / f"{PILOT[0]}.a1.json")
    assert stored["integrity"]["ok"] is False
    assert stored["integrity"]["notInCallPathImported"] == ["backend/app/tests/test_new.py"]
    assert contract.evaluation_of(stored, mock=False)["exclusion"] == "integrity"


# --- approval scope -----------------------------------------------------------------


def test_real_calls_need_the_flag_an_approval_and_passing_checks(store, monkeypatch):
    root = make_experiment(store, "ledger-gates", mock=False)
    monkeypatch.setattr(runner, "_spawn_worker", FakeWorker())
    with pytest.raises(runner.AbError, match="allow-real-claude"):
        runner.run("ledger-gates", approval=None, mock=False, allow_real=False)
    with pytest.raises(runner.AbError, match="--approval"):
        runner.run("ledger-gates", approval=None, mock=False, allow_real=True)
    with pytest.raises(runner.AbError, match="--mock"):
        runner.run("ledger-gates", approval=None, mock=True, allow_real=False)
    with pytest.raises(runner.AbError, match="no such approval"):
        runner.run("ledger-gates", approval="ap-20261121T000000Z-abcd", mock=False, allow_real=True)
    (root / "payloads" / "checks.json").unlink()
    with pytest.raises(runner.AbError, match="payloads"):
        _approve("ledger-gates", PILOT, 2)


def test_approval_needs_the_number_retyped_and_exact_known_ids(store):
    root = make_experiment(store, "ledger-approve", mock=False)
    with pytest.raises(runner.AbError, match="not approved"):
        runner.approve("ledger-approve", PILOT, 2, confirm=lambda _p: "yes")
    with pytest.raises(runner.AbError, match="not in this experiment"):
        _approve("ledger-approve", ["999-nope-a-r1"], 1)
    with pytest.raises(runner.AbError, match="once"):
        _approve("ledger-approve", [PILOT[0], PILOT[0]], 2)
    with pytest.raises(runner.AbError, match="at least 1"):
        _approve("ledger-approve", PILOT, 0)
    assert not (root / "approvals").exists()


def test_pilot_runs_exactly_the_two_approved_calls_and_never_again(store, monkeypatch):
    """M1: `--limit 2` picked whatever was left; the approval names the calls."""
    root = make_experiment(store, "ledger-pilot", mock=False)
    approval = _approve("ledger-pilot", PILOT, 2)
    fake = FakeWorker()
    monkeypatch.setattr(runner, "_spawn_worker", fake)
    assert runner.run("ledger-pilot", approval=approval, mock=False, allow_real=True) == 0
    assert fake.model_calls == PILOT
    assert runner.run("ledger-pilot", approval=approval, mock=False, allow_real=True) == 0
    assert fake.model_calls == PILOT  # nothing repeated, nothing else started
    assert sorted(p.name for p in (root / "calls").iterdir()) == [f"{c}.a1.json" for c in PILOT]
    with pytest.raises(runner.AbError, match="already has an answer"):
        _approve("ledger-pilot", PILOT[:1], 1)


def test_partial_pilot_resumes_with_only_the_remaining_approved_call(store, monkeypatch):
    make_experiment(store, "ledger-resume", mock=False)
    approval = _approve("ledger-resume", PILOT, 2)
    fake = FakeWorker({PILOT[1]: ["crashBeforeModel", "served"]})
    monkeypatch.setattr(runner, "_spawn_worker", fake)
    assert runner.run("ledger-resume", approval=approval, mock=False, allow_real=True) == 3
    assert _states(store / "ledger-resume") == {PILOT[0]: "recorded", PILOT[1]: "notInvoked"}
    # provably not invoked -> may start again, and it did not use the approval
    assert runner.run("ledger-resume", approval=approval, mock=False, allow_real=True) == 0
    assert fake.model_calls == PILOT


def test_provider_error_is_recorded_and_not_retried_without_a_person(store, monkeypatch):
    root = make_experiment(store, "ledger-timeout", mock=False)
    approval = _approve("ledger-timeout", PILOT, 2)
    fake = FakeWorker({PILOT[0]: ["timeout", "served"]})
    monkeypatch.setattr(runner, "_spawn_worker", fake)
    assert runner.run("ledger-timeout", approval=approval, mock=False, allow_real=True) == 0
    stored = runner.read_json(root / "calls" / f"{PILOT[0]}.a1.json")
    assert stored["scores"]["outcome"]["outcome"] == "providerError"
    assert stored["scores"]["gate"]["passed"] is None
    # rerun: no retry without --retry
    assert runner.run("ledger-timeout", approval=approval, mock=False, allow_real=True) == 3
    # with --retry, but both approved CLI calls are spent -> refused, no call
    assert runner.run("ledger-timeout", approval=approval, mock=False, allow_real=True, retry=[PILOT[0]]) == 3
    assert fake.model_calls == PILOT
    # a new approval for one more call, then the retry runs as attempt 2
    second = _approve("ledger-timeout", PILOT[:1], 1)
    assert runner.run("ledger-timeout", approval=second, mock=False, allow_real=True, retry=[PILOT[0]]) == 0
    assert runner.read_json(root / "calls" / f"{PILOT[0]}.a2.json")["scores"]["outcome"]["outcome"] == "served"
    assert contract.call_state(root, PILOT[0])["attempts"] == 2


def test_retry_outside_the_approval_is_refused(store, monkeypatch):
    make_experiment(store, "ledger-retry-scope", mock=False)
    approval = _approve("ledger-retry-scope", PILOT[:1], 1)
    monkeypatch.setattr(runner, "_spawn_worker", FakeWorker())
    with pytest.raises(runner.AbError, match="outside the approval"):
        runner.run("ledger-retry-scope", approval=approval, mock=False, allow_real=True, retry=[PILOT[1]])


@pytest.mark.parametrize("failure", ["crashAfterModel", "killedByTimeout"])
def test_a_call_that_may_have_reached_the_model_is_never_repeated_automatically(store, monkeypatch, failure):
    """H2: a crash after the model call left no record and the next run called again."""
    root = make_experiment(store, "ledger-crash", mock=False)
    approval = _approve("ledger-crash", PILOT, 3)
    fake = FakeWorker({PILOT[0]: [failure, "served"]})
    monkeypatch.setattr(runner, "_spawn_worker", fake)
    assert runner.run("ledger-crash", approval=approval, mock=False, allow_real=True) == 3
    assert fake.model_calls == [PILOT[0]]
    assert _states(root)[PILOT[0]] == "uncertain"
    assert runner.read_json(contract.attempt_paths(root, PILOT[0], 1)["exit"])["timedOut"] is (failure == "killedByTimeout")
    for _ in range(2):
        assert runner.run("ledger-crash", approval=approval, mock=False, allow_real=True) == 3
    assert fake.model_calls == [PILOT[0], PILOT[1]]  # B ran; A was not called again
    # an explicit retry inside the approval: attempt 2, and the uncertain one stays counted
    assert runner.run("ledger-crash", approval=approval, mock=False, allow_real=True, retry=[PILOT[0]]) == 0
    assert fake.model_calls == [PILOT[0], PILOT[1], PILOT[0]]
    used = contract.approval_usage(root, approval)
    assert len(used) == 3


def test_a_saved_raw_result_is_recorded_without_calling_again(store, monkeypatch):
    root = make_experiment(store, "ledger-recover", mock=False)
    approval = _approve("ledger-recover", PILOT[:1], 1)
    fake = FakeWorker()
    monkeypatch.setattr(runner, "_spawn_worker", fake)
    real_score = scoring.score_record

    def broken(*_a, **_k):
        raise RuntimeError("scoring crashed after the call")

    monkeypatch.setattr(runner.scoring, "score_record", broken)
    with pytest.raises(RuntimeError):
        runner.run("ledger-recover", approval=approval, mock=False, allow_real=True)
    assert _states(root)[PILOT[0]] == "recoverable"
    monkeypatch.setattr(runner.scoring, "score_record", real_score)
    assert runner.run("ledger-recover", approval=approval, mock=False, allow_real=True) == 0
    assert fake.model_calls == [PILOT[0]]
    assert runner.read_json(root / "calls" / f"{PILOT[0]}.a1.json")["scores"]["outcome"]["outcome"] == "served"


def test_two_runners_cannot_work_on_one_experiment(store, monkeypatch):
    root = make_experiment(store, "ledger-lock", mock=False)
    approval = _approve("ledger-lock", PILOT, 2)
    fake = FakeWorker()
    monkeypatch.setattr(runner, "_spawn_worker", fake)
    with contract.os_lock(root / "run.lock"):
        with pytest.raises(runner.AbError, match="another runner"):
            runner.run("ledger-lock", approval=approval, mock=False, allow_real=True)
        with pytest.raises(runner.AbError, match="another runner"):
            _approve("ledger-lock", PILOT, 2)
    assert fake.model_calls == []


def test_an_orphaned_worker_still_holding_its_attempt_stops_the_run(store, monkeypatch):
    root = make_experiment(store, "ledger-orphan", mock=False)
    approval = _approve("ledger-orphan", PILOT, 2)
    paths = contract.attempt_paths(root, PILOT[0], 1)
    runner.write_new(paths["claim"], {"callId": PILOT[0], "attempt": 1, "approvalId": approval})
    fake = FakeWorker()
    monkeypatch.setattr(runner, "_spawn_worker", fake)
    with contract.os_lock(paths["lock"]):  # a worker from a killed runner
        assert _states(root)[PILOT[0]] == "running"
        with pytest.raises(runner.AbError, match="running in another process"):
            runner.run("ledger-orphan", approval=approval, mock=False, allow_real=True)
        assert len(contract.approval_usage(root, approval)) == 1
        assert not paths["void"].exists()  # a live attempt is never sealed
    assert fake.model_calls == []
    # It died before the model, but until a runner seals it that is not a fact.
    assert _states(root)[PILOT[0]] == "inFlightOrNotInvoked"
    assert len(contract.approval_usage(root, approval)) == 1
    # The next run seals it (lock free, no marker), and it no longer counts.
    assert runner.run("ledger-orphan", approval=approval, mock=False, allow_real=True) == 0
    assert paths["void"].is_file()
    assert fake.model_calls == PILOT


def test_an_approval_is_bound_to_the_experiment_it_approved(store, monkeypatch):
    root = make_experiment(store, "ledger-bound", mock=False)
    approval = _approve("ledger-bound", PILOT, 2)
    path = root / "payloads" / "real_b94559.A.json"
    path.unlink()
    runner.write_new(path, {"payloadDigest": "rebuilt-later", **PAYLOAD_FIELDS})
    monkeypatch.setattr(runner, "_spawn_worker", FakeWorker())
    with pytest.raises(runner.AbError, match="approve again"):
        runner.run("ledger-bound", approval=approval, mock=False, allow_real=True)


def test_mock_runs_use_the_same_path_and_say_they_are_mock(store, monkeypatch):
    root = make_experiment(store, "mock-flow", mock=True)
    fake = FakeWorker({PILOT[0]: ["timeout"], PILOT[1]: ["gateRejected"]})
    monkeypatch.setattr(runner, "_spawn_worker", fake)
    assert runner.run("mock-flow", approval=None, mock=True, allow_real=False) == 0
    assert len(fake.model_calls) == len(PROTOCOL["cases"]) * PROTOCOL["repeats"] * 2
    first = runner.read_json(root / "calls" / f"{PILOT[0]}.a1.json")
    assert first["mock"] is True and first["record"]["workerAction"] == "mock"
    status = runner.status("mock-flow")
    by_id = {c["callId"]: c for c in status["calls"]}
    assert by_id[PILOT[0]]["outcome"] == "providerError" and by_id[PILOT[1]]["outcome"] == "gateRejected"
    assert status["integrity"] == "ok"


# --- the real worker's own refusals (in-process, nothing imported or spawned) -----


def _request(tmp_path: Path, action: str, allow: bool, **extra) -> Path:
    path = tmp_path / f"req-{action}-{allow}.json"
    path.write_text(json.dumps({"action": action, "allowRealClaude": allow} | extra), encoding="utf-8")
    return path


def _worker_args(tmp_path: Path, request: Path, out: Path) -> list[str]:
    return ["--tree", str(tmp_path), "--request", str(request), "--out", str(out)]


def test_worker_refuses_a_real_call_without_both_opt_ins(tmp_path, monkeypatch):
    monkeypatch.delenv("WES_AB_ALLOW_REAL_CLAUDE", raising=False)
    for allow in (False, True):
        with pytest.raises(SystemExit, match="refused"):
            worker.main(_worker_args(tmp_path, _request(tmp_path, "real", allow), tmp_path / "o.json"))
    monkeypatch.setenv("WES_AB_ALLOW_REAL_CLAUDE", "1")
    with pytest.raises(SystemExit, match="refused"):
        worker.main(_worker_args(tmp_path, _request(tmp_path, "real", False), tmp_path / "o.json"))
    assert not (tmp_path / "o.json").exists()


def test_worker_rejects_unknown_actions(tmp_path):
    with pytest.raises(SystemExit, match="unknown action"):
        worker.main(_worker_args(tmp_path, _request(tmp_path, "both", False), tmp_path / "o.json"))


def _attempt(tmp_path: Path, *, claim: bool = True, started: bool = False) -> dict:
    paths = {k: tmp_path / f"1.{k}" for k in ("claim", "lock", "started", "void")}
    if claim:
        paths["claim"].write_text("{}", encoding="utf-8")
    if started:
        paths["started"].write_text("{}", encoding="utf-8")
    return {k: str(v) for k, v in paths.items()}


@pytest.fixture
def no_import(monkeypatch):
    """The worker must refuse before it gets this far; reaching _run fails the test."""
    reached = []
    monkeypatch.setattr(worker, "_run", lambda *a, **k: reached.append(a))
    return reached


def test_worker_refuses_a_model_action_without_a_durable_claim(tmp_path, no_import):
    req = _request(tmp_path, "mock", False, attempt=_attempt(tmp_path, claim=False))
    with pytest.raises(SystemExit, match="no durable claim"):
        worker.main(_worker_args(tmp_path, req, tmp_path / "o.json"))
    req = _request(tmp_path, "mock", False)
    with pytest.raises(SystemExit, match="attempt"):
        worker.main(_worker_args(tmp_path, req, tmp_path / "o.json"))
    assert no_import == []


def test_worker_refuses_an_attempt_that_already_reached_the_model(tmp_path, no_import):
    req = _request(tmp_path, "mock", False, attempt=_attempt(tmp_path, started=True))
    with pytest.raises(SystemExit, match="already reached the model"):
        worker.main(_worker_args(tmp_path, req, tmp_path / "o.json"))
    (tmp_path / "o.json").write_text("{}", encoding="utf-8")
    with pytest.raises(SystemExit, match="already exists"):
        worker.main(_worker_args(tmp_path, req, tmp_path / "o.json"))
    assert no_import == []


def test_worker_refuses_an_attempt_a_runner_sealed_as_not_invoked(tmp_path, no_import):
    """B1: the seal is written under the attempt lock; the worker checks it under the same lock."""
    attempt = _attempt(tmp_path)
    Path(attempt["void"]).write_text("{}", encoding="utf-8")
    req = _request(tmp_path, "mock", False, attempt=attempt)
    with pytest.raises(SystemExit, match="sealed as not invoked"):
        worker.main(_worker_args(tmp_path, req, tmp_path / "o.json"))
    assert no_import == [] and not Path(attempt["started"]).exists()


def test_worker_refuses_an_attempt_held_by_another_process(tmp_path, no_import):
    attempt = _attempt(tmp_path)
    req = _request(tmp_path, "mock", False, attempt=attempt)
    with contract.os_lock(Path(attempt["lock"])):
        with pytest.raises(SystemExit, match="held by another process"):
            worker.main(_worker_args(tmp_path, req, tmp_path / "o.json"))
    assert no_import == []
    worker.main(_worker_args(tmp_path, req, tmp_path / "o.json"))  # free again -> proceeds
    assert len(no_import) == 1


def test_worker_writes_the_marker_before_the_model_call(tmp_path, monkeypatch):
    from evals import run_eval

    marker = tmp_path / "1.started"
    seen = []

    def evaluate(name, materialised, *, variant, privacy):
        with materialised:  # the harness enters it right before the provider call
            seen.append(marker.exists())
        return {"available": True}, {"p": 1}

    locked = {"payloadDigest": "pd", "sourceDigest": "sd"}
    monkeypatch.setattr(run_eval, "apply_variant_settings", lambda _v: None)
    monkeypatch.setattr(run_eval, "_evaluate_run", evaluate)
    monkeypatch.setattr(worker, "_case", lambda _re, _req: (lambda: contextlib.nullcontext("run"), None, lambda _v: 0))
    monkeypatch.setattr(worker, "_inputs_now", lambda _explanation: dict(locked))
    request = {"case": "c", "conditions": {"variant": "v3"}, "locked": locked}
    record = worker.call_model(request, marker)
    assert seen == [True] and record["payloadDigest"] == worker.canonical_sha256({"p": 1})
    with pytest.raises(FileExistsError):  # a second call through the same marker is impossible
        worker.call_model(request, marker)
    with pytest.raises(SystemExit, match="digests"):  # no approved digests, no call
        worker.call_model({"case": "c", "conditions": {"variant": "v3"}}, tmp_path / "2.started")
    assert not (tmp_path / "2.started").exists()


def test_worker_publishes_atomically_and_never_replaces(tmp_path):
    out = tmp_path / "raw.json"
    worker._publish(out, {"v": 1})
    with pytest.raises(FileExistsError):
        worker._publish(out, {"v": 2})
    assert json.loads(out.read_text(encoding="utf-8")) == {"v": 1}
    assert [p.name for p in tmp_path.iterdir()] == ["raw.json"]  # no temp file left


def test_worker_lists_imports_relative_to_the_snapshot():
    tree = Path(worker.__file__).resolve().parents[2]  # .../backend
    files = worker._tree_imports(tree)
    assert "backend/evals/ab_compare/worker.py" in files
    assert all(not f.startswith("/") and ":" not in f for f in files)


def test_mock_answer_marks_every_sentence_and_is_the_same_for_both_arms():
    for scenario in ("plain", "detector", "rejected"):
        a = worker._mock_answer(scenario)
        texts = [a["summary"]] + [i["statement"] for s in scoring.SECTIONS for i in a[s]]
        assert all(t.startswith(worker.MOCK_MARK) for t in texts)
        assert worker._mock_answer(scenario) == a
