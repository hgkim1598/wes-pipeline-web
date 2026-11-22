"""Independent review findings (2026-11-22) on the A/B runner and worker.

Each test reproduces one finding as behaviour, not as an implementation
detail, so the same test fails on the code the review read and passes on the
fix. No model and no CLI: the runner's worker is the contract-following fake
from test_ab_compare.py, and the real worker is exercised in-process with
everything past its refusals replaced.

    B1  a worker that had not yet taken its lock read as "not invoked", so a
        restarted runner could start another attempt and exceed the approval
    H4  data the tool reads during the call (the restored run) could change
        after approval; only the initial payload was compared
    M1  a crash while the final record was written left a partial file that
        blocked recovering the saved raw result
"""

from __future__ import annotations

import json
import pathlib
from contextlib import contextmanager
from pathlib import Path

import pytest

from evals.ab_compare import contract, runner, worker
from evals.test_ab_compare import (
    PILOT,
    FakeWorker,
    _approve,
    _request,
    _worker_args,
    make_experiment,
)


@pytest.fixture
def store(tmp_path, monkeypatch):
    monkeypatch.setattr(runner.config, "EVAL_AB_STORE", tmp_path / "store")
    return tmp_path / "store"


def _attempt_request_paths(root: Path, call_id: str, n: int) -> dict[str, str]:
    paths = contract.attempt_paths(root, call_id, n)
    return {k: str(v) for k, v in paths.items() if k in ("claim", "lock", "started", "void")}


# --- B1 ---------------------------------------------------------------------------


def test_b1_a_worker_still_starting_cannot_spend_beyond_the_approval(store, tmp_path, monkeypatch):
    """A runner claimed attempt 1, spawned its worker and was killed. The worker
    is still starting (no lock yet, no marker). A new runner must not let both
    that worker and a new attempt reach the model under a one-call approval."""
    root = make_experiment(store, "ledger-b1", mock=False)
    approval = _approve("ledger-b1", PILOT[:1], 1)
    paths = contract.attempt_paths(root, PILOT[0], 1)
    runner.write_new(paths["claim"], {"callId": PILOT[0], "attempt": 1, "approvalId": approval, "mode": "real"})

    fake = FakeWorker()
    monkeypatch.setattr(runner, "_spawn_worker", fake)
    runner.run("ledger-b1", approval=approval, mock=False, allow_real=True)

    # the orphaned worker now gets its lock and carries on
    reached: list[int] = []
    monkeypatch.setattr(worker, "_run", lambda *a, **k: reached.append(1))
    request = _request(tmp_path, "mock", False, attempt=_attempt_request_paths(root, PILOT[0], 1))
    try:
        worker.main(_worker_args(tmp_path, request, paths["raw"]))
    except SystemExit:
        pass
    assert len(fake.model_calls) + len(reached) <= 1, "two model calls under a one-call approval"


def test_b1_an_unsealed_attempt_counts_against_the_approval(store):
    """Nothing durable proves a claimed attempt without a marker was not about to
    call; until it is sealed it must count."""
    root = make_experiment(store, "ledger-b1-count", mock=False)
    approval = _approve("ledger-b1-count", PILOT[:1], 1)
    paths = contract.attempt_paths(root, PILOT[0], 1)
    runner.write_new(paths["claim"], {"callId": PILOT[0], "attempt": 1, "approvalId": approval})
    assert len(contract.approval_usage(root, approval)) == 1


# --- H4 ---------------------------------------------------------------------------


class _SourceChangedAfterApproval(FakeWorker):
    """The pre-call payload build sees the same model input, but the restored
    run the tool would read is different."""

    def __call__(self, root: Path, arm: str, request: dict, out: Path, *, allow_real: bool) -> int:
        if request["action"] == "payload":
            self.payload_builds += 1
            locked = runner.read_json(root / "payloads" / f"{request['case']}.{arm}.json")
            out.write_text(json.dumps(locked | {"sourceDigest": "changed-after-approval"}), encoding="utf-8")
            return 0
        return super().__call__(root, arm, request, out, allow_real=allow_real)


def test_h4_a_changed_run_source_stops_the_call_before_it_is_claimed(store, monkeypatch):
    make_experiment(store, "ledger-h4", mock=False)
    approval = _approve("ledger-h4", PILOT[:1], 1)
    fake = _SourceChangedAfterApproval()
    monkeypatch.setattr(runner, "_spawn_worker", fake)
    with pytest.raises(runner.AbError):
        runner.run("ledger-h4", approval=approval, mock=False, allow_real=True)
    assert fake.model_calls == []
    assert contract.claimed_attempts(store / "ledger-h4", PILOT[0]) == []


def test_h4_the_worker_checks_the_run_source_where_it_is_used(tmp_path, monkeypatch):
    """Between the runner's check and the call, the source can still change. The
    worker compares what it restored with the locked digests before the marker."""
    from evals import run_eval

    marker = tmp_path / "1.started"
    called: list[int] = []

    @contextmanager
    def restored():
        yield object()

    def evaluate(name, materialised, *, variant, privacy):
        with materialised:
            called.append(1)
        return {"available": True}, {"p": 1}

    monkeypatch.setattr(run_eval, "apply_variant_settings", lambda _v: None)
    monkeypatch.setattr(run_eval, "_evaluate_run", evaluate)
    monkeypatch.setattr(worker, "_case", lambda _re, _req: (restored, None, lambda _v: 0))
    monkeypatch.setattr(
        worker, "_inputs_now", lambda _explanation: {"payloadDigest": "p", "sourceDigest": "changed"}, raising=False
    )
    request = {"case": "c", "conditions": {"variant": "v3"}, "locked": {"payloadDigest": "p", "sourceDigest": "approved"}}
    with pytest.raises((SystemExit, RuntimeError)):
        worker.call_model(request, marker)
    assert called == [] and not marker.exists()


# --- M1 ---------------------------------------------------------------------------


def test_m1_a_crash_while_writing_the_record_does_not_block_recovery(store, monkeypatch):
    root = make_experiment(store, "ledger-m1", mock=False)
    approval = _approve("ledger-m1", PILOT[:1], 1)
    fake = FakeWorker()
    monkeypatch.setattr(runner, "_spawn_worker", fake)

    real_open = pathlib.Path.open
    calls_dir = root / "calls"

    def crashing_open(self, mode="r", *args, **kwargs):
        handle = real_open(self, mode, *args, **kwargs)
        if "x" in mode and self.parent == calls_dir:
            handle.write('{"callId": "half')  # the process dies mid-write
            handle.close()
            raise OSError("simulated crash while writing the record")
        return handle

    monkeypatch.setattr(pathlib.Path, "open", crashing_open)
    with pytest.raises(OSError):
        runner.run("ledger-m1", approval=approval, mock=False, allow_real=True)
    monkeypatch.setattr(pathlib.Path, "open", real_open)

    assert runner.run("ledger-m1", approval=approval, mock=False, allow_real=True) == 0
    assert fake.model_calls == [PILOT[0]]  # recovered from the raw result, no second call
    stored = contract.latest_records(root)[PILOT[0]]
    assert stored["scores"]["outcome"]["outcome"] == "served"


# --- PR review (Copilot): a damaged record file must not read as "planned" ---------
#
# call_records skips a record file it cannot parse, and call_state used to find
# such a file only at the latest CLAIMED attempt's versioned path. A first-version
# flat calls/<id>.json has no claim, and a versioned file can outlive its claim, so
# a damaged one vanished: the call read as planned, the runner claimed attempt 1
# again and called the model for a call that may already have an answer.


def _damage(root: Path, name: str) -> None:
    (root / "calls").mkdir(parents=True, exist_ok=True)
    (root / "calls" / name).write_text('{"callId": "half', encoding="utf-8")


@pytest.mark.parametrize("name", [f"{PILOT[0]}.json", f"{PILOT[0]}.a1.json", f"{PILOT[0]}.a3.json"])
def test_pr_a_damaged_record_without_a_claim_is_unreadable_not_planned(store, name):
    root = make_experiment(store, "ledger-pr-flat", mock=False)
    _damage(root, name)
    for records in (None, contract.call_records(root).get(PILOT[0], {})):
        state = contract.call_state(root, PILOT[0], records=records, lock_probe=contract.is_held)
        assert state["state"] == "unreadableRecord"
        assert state["attempt"] is not None and state["attempts"] >= 1


def test_pr_a_damaged_older_record_holds_the_call_even_when_a_newer_one_reads(store):
    """The damaged attempt may have been the answer; a person decides, not the newest file."""
    root = make_experiment(store, "ledger-pr-older", mock=False)
    _damage(root, f"{PILOT[0]}.json")
    newer = contract.attempt_paths(root, PILOT[0], 2)
    runner.write_new(newer["claim"], {"callId": PILOT[0], "attempt": 2, "approvalId": "ap-x"})
    runner.write_new(newer["record"], {"callId": PILOT[0], "record": {"available": False, "errorCategory": "timeout", "leakCount": 0}})
    assert contract.call_state(root, PILOT[0], lock_probe=contract.is_held)["state"] == "unreadableRecord"
    assert PILOT[0] not in contract.latest_records(root)


@pytest.mark.parametrize("name", [f"{PILOT[0]}.json", f"{PILOT[0]}.a1.json"])
def test_pr_the_runner_never_calls_a_call_whose_record_is_damaged(store, monkeypatch, name):
    root = make_experiment(store, "ledger-pr-run", mock=False)
    approval = _approve("ledger-pr-run", PILOT[:1], 1)
    _damage(root, name)
    fake = FakeWorker()
    monkeypatch.setattr(runner, "_spawn_worker", fake)
    assert runner.run("ledger-pr-run", approval=approval, mock=False, allow_real=True) == 3
    assert fake.model_calls == []
    assert contract.claimed_attempts(root, PILOT[0]) == []
    assert (root / "calls" / name).read_text(encoding="utf-8") == '{"callId": "half'  # never overwritten
    assert runner.status("ledger-pr-run")["calls"][0]["state"] == "unreadableRecord"


def test_pr_a_claimed_damaged_attempt_is_never_retried(store, monkeypatch):
    """Attempt 1 timed out, attempt 2 was claimed and its record is damaged; --retry does not reach the model."""
    root = make_experiment(store, "ledger-pr-retry", mock=False)
    approval = _approve("ledger-pr-retry", PILOT[:1], 3)
    first = contract.attempt_paths(root, PILOT[0], 1)
    runner.write_new(first["claim"], {"callId": PILOT[0], "attempt": 1, "approvalId": approval})
    runner.write_new(first["record"], {"callId": PILOT[0], "record": {"available": False, "errorCategory": "timeout", "leakCount": 0}})
    second = contract.attempt_paths(root, PILOT[0], 2)
    runner.write_new(second["claim"], {"callId": PILOT[0], "attempt": 2, "approvalId": approval})
    _damage(root, second["record"].name)
    fake = FakeWorker()
    monkeypatch.setattr(runner, "_spawn_worker", fake)
    assert runner.run("ledger-pr-retry", approval=approval, mock=False, allow_real=True, retry=[PILOT[0]]) == 3
    assert fake.model_calls == [] and contract.claimed_attempts(root, PILOT[0]) == [1, 2]


@pytest.mark.parametrize("claimed", [True, False])
def test_pr_a_record_published_after_the_callers_snapshot_is_not_called_damaged(store, claimed):
    """A caller's records snapshot can be older than the disk; a readable new file is a record."""
    root = make_experiment(store, "ledger-pr-snapshot", mock=True)
    snapshot = contract.call_records(root).get(PILOT[0], {})
    paths = contract.attempt_paths(root, PILOT[0], 1)
    if claimed:
        runner.write_new(paths["claim"], {"callId": PILOT[0], "attempt": 1, "approvalId": "ap-x"})
        target = paths["record"]
    else:
        target = root / "calls" / f"{PILOT[0]}.json"
    runner.write_new(target, {"callId": PILOT[0], "record": {"available": False, "errorCategory": "timeout", "leakCount": 0}})
    state = contract.call_state(root, PILOT[0], records=snapshot, mock=True)
    assert (state["state"], state["outcome"]) == ("recorded", "providerError")
