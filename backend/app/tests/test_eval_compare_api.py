"""Evaluator-only A/B comparison routes (api/eval_compare.py).

The store is built by hand in tmp_path in the shape evals/ab_compare writes.
Nothing here calls a model: the provider is replaced by a function that fails
the test if anything reaches it.
"""

from __future__ import annotations

import json

import pytest
from fastapi.testclient import TestClient

from app import config
from app.main import app
from app.services.explanation.llm import provider

EXP = "mock-api-check"
TOKEN = "test-token-123"
CASE = {
    "case": "real_b94559",
    "kind": "archive",
    "label": "b94559",
    "synthetic": False,
    "role": "효과 측정",
    "facts": {"steps": [], "requiredCauses": [{"id": "required_tools", "label": "x", "source": "record", "pattern": "x"}], "notes": []},
}
PROTOCOL = {
    "id": "p",
    "title": "t",
    "fixedAt": "2026-11-21",
    "note": [],
    "conditions": {"model": "sonnet"},
    "repeats": 1,
    "order": "interleaved",
    "cases": [CASE],
    "claimUnit": "statement",
    "metrics": [],
    "successCriteria": [],
    "intendedDifference": [],
    "detectors": [{"id": "D", "metric": "nonRunClaims", "label": "l", "pattern": "SECRET-PATTERN"}],
    "wrongCauseCandidates": [{"id": "W", "label": "l", "pattern": "SECRET-PATTERN"}],
}


def _answer(text: str) -> dict:
    return {
        "summary": "s",
        "importantFindings": [{"statement": text, "evidenceRefs": ["run:status"]}],
        "limitations": [],
        "nextChecks": [],
        "uncertainties": [],
    }


def _record(kind: str, arm: str, *, leak: int = 0) -> dict:
    base = {
        "durationMs": 1000,
        "wallMs": 1500,
        "models": ["m"],
        "toolUse": {"toolUsed": True, "openedStepIds": ["00_input_validation"], "callCount": 1},
        "trace": {},
        "evaluation": {"deterministicPassed": True, "results": [{"name": "n", "kind": "k", "outcome": "pass", "detail": f"quotes {arm}"}]},
        "leakCount": leak,
    }
    if kind == "served":
        return base | {"available": True, "errorCategory": None, "output": _answer(f"served {arm}"), "rejectedOutput": None}
    if kind == "rejected":
        return base | {
            "available": False,
            "errorCategory": "runFactMismatch",
            "output": None,
            "rejectedOutput": {"attempt": 1, "category": "runFactMismatch", "findings": ["f"], "answer": _answer(f"rejected {arm}")},
        }
    return base | {"available": False, "errorCategory": kind, "output": None, "rejectedOutput": None, "durationMs": 300000}


def _call(call_id: str, arm: str, code: str, kind: str, *, leak: int = 0, attempt: int | None = None, mock: bool = True) -> dict:
    call = {
        "callId": call_id, "arm": arm, "case": "real_b94559", "repeat": 1, "seq": 1,
        "blindCode": code, "mock": mock, "startedAt": "t",
        "scores": {"served": {"measured": kind == "served", "detectorHits": [{"detector": "D", "metric": "m", "where": "w", "excerpt": f"text of {arm}"}]}, "rejected": {"measured": False}},
        "record": _record(kind, arm, leak=leak),
    }
    if attempt is not None:
        call["attempt"] = attempt
        call["integrity"] = {"ok": True, "checks": {}, "notInCallPathImported": []}
    return call


def _write(path, value) -> None:
    path.parent.mkdir(parents=True, exist_ok=True)
    path.write_text(json.dumps(value), encoding="utf-8")


@pytest.fixture
def store(tmp_path, monkeypatch):
    def refuse(**_kwargs):
        raise AssertionError("a model call was attempted")

    monkeypatch.setattr(provider, "run_structured", refuse)
    monkeypatch.setattr(config, "EVAL_AB_STORE", tmp_path)
    monkeypatch.setattr(config, "EVAL_COMPARE", True)
    monkeypatch.setattr(config, "EVAL_COMPARE_TOKEN", TOKEN)
    root = tmp_path / EXP
    plan = [
        {"callId": "001-a", "case": "real_b94559", "arm": "A", "repeat": 1, "seq": 1, "blindCode": "X02"},
        {"callId": "002-b", "case": "real_b94559", "arm": "B", "repeat": 1, "seq": 2, "blindCode": "X01"},
        {"callId": "003-a", "case": "real_b94559", "arm": "A", "repeat": 2, "seq": 3, "blindCode": "X03"},
        {"callId": "004-b", "case": "real_b94559", "arm": "B", "repeat": 2, "seq": 4, "blindCode": "X04"},
    ]
    doc = {
        "experimentId": EXP, "mock": True, "createdAt": "t", "protocolSha256": "h", "protocol": PROTOCOL,
        "arms": {"A": {"label": "Without"}, "B": {"label": "With"}},
        "armDiff": {"changed": [], "added": []}, "sharedLocalInputs": {}, "plan": plan,
    }
    _write(root / "experiment.json", doc)
    # first-version flat records (attempt 1, no claim) ...
    _write(root / "calls" / "001-a.json", _call("001-a", "A", "X02", "rejected"))
    _write(root / "calls" / "002-b.json", _call("002-b", "B", "X01", "served"))
    # ... and the current layout: a provider timeout, then a retry that answered
    _write(root / "calls" / "003-a.a1.json", _call("003-a", "A", "X03", "timeout", attempt=1))
    _write(root / "calls" / "003-a.a2.json", _call("003-a", "A", "X03", "served", attempt=2))
    _write(root / "calls" / "004-b.a1.json", _call("004-b", "B", "X04", "timeout", attempt=1))
    for arm in "AB":
        _write(
            root / "payloads" / f"real_b94559.{arm}.json",
            {"payload": {"arm": arm}, "payloadDigest": arm, "privacy": "pass", "leakCount": 0},
        )
    return root


@pytest.fixture
def client(env):
    """A client on this machine that carries the evaluator token."""
    return TestClient(app, raise_server_exceptions=False, client=("127.0.0.1", 50000), headers={"X-WES-Eval-Token": TOKEN})


def _unblind(client) -> None:
    assert client.post(f"/api/eval/compare/{EXP}/unblind", json={"confirm": "unblind", "by": "u"}).status_code == 200


PATHS = ("", f"/{EXP}", f"/{EXP}/calls/001-a", f"/{EXP}/payloads/real_b94559", f"/{EXP}/blind")


# --- access ---------------------------------------------------------------------


def test_every_route_is_404_when_the_flag_is_off(client, store, monkeypatch):
    monkeypatch.setattr(config, "EVAL_COMPARE", False)
    for path in PATHS:
        assert client.get(f"/api/eval/compare{path}").status_code == 404, path
    assert client.post(f"/api/eval/compare/{EXP}/grades/X01", json={"grader": "u", "claims": []}).status_code == 404
    assert not (store / "grades").exists()


def test_other_machines_get_404_even_with_the_flag_and_token(env, store):
    remote = TestClient(app, raise_server_exceptions=False, client=("192.168.0.20", 50000), headers={"X-WES-Eval-Token": TOKEN})
    for path in PATHS:
        assert remote.get(f"/api/eval/compare{path}").status_code == 404, path
    # a proxy that says the request came from elsewhere
    proxied = TestClient(app, raise_server_exceptions=False, client=("127.0.0.1", 50000))
    headers = {"X-WES-Eval-Token": TOKEN, "X-Forwarded-For": "10.0.0.7"}
    assert proxied.get("/api/eval/compare", headers=headers).status_code == 404
    assert remote.post(f"/api/eval/compare/{EXP}/unblind", json={"confirm": "unblind", "by": "u"}).status_code == 404
    assert not (store / "unblind.json").exists()


def test_the_token_is_required_and_its_absence_fails_closed(env, store, monkeypatch):
    local = TestClient(app, raise_server_exceptions=False, client=("127.0.0.1", 50000))
    assert local.get("/api/eval/compare").status_code == 401
    assert local.get("/api/eval/compare", headers={"X-WES-Eval-Token": "wrong"}).status_code == 401
    assert local.post(f"/api/eval/compare/{EXP}/grades/X01", json={"grader": "u", "claims": []}).status_code == 401
    monkeypatch.setattr(config, "EVAL_COMPARE_TOKEN", "")
    assert local.get("/api/eval/compare", headers={"X-WES-Eval-Token": ""}).status_code == 503
    assert not (store / "grades").exists()


# --- states and outcomes come from the shared contract ---------------------------


def test_list_and_detail(client, store):
    listed = client.get("/api/eval/compare").json()["experiments"]
    assert listed == [{"experimentId": EXP, "title": "t", "mock": True, "createdAt": "t", "planned": 4, "recorded": 4, "answered": 3}]
    detail = client.get(f"/api/eval/compare/{EXP}").json()
    assert [c["arm"] for c in detail["calls"]] == ["A", "B", "A", "B"]
    assert {p["callId"]: p["state"] for p in detail["plan"]} == {"001-a": "recorded", "002-b": "recorded", "003-a": "recorded", "004-b": "recorded"}
    assert "SECRET-PATTERN" not in json.dumps(detail)


def test_a_provider_error_is_not_a_gate_rejection(client, store):
    detail = client.get(f"/api/eval/compare/{EXP}").json()
    outcomes = {c["callId"]: c["evaluation"]["outcome"] for c in detail["calls"]}
    assert outcomes == {"001-a": "gateRejected", "002-b": "served", "003-a": "served", "004-b": "providerError"}
    timeout = next(c for c in detail["calls"] if c["callId"] == "004-b")
    assert timeout["evaluation"]["countsForGate"] is False and timeout["evaluation"]["exclusion"] == "providerError"
    # the retried call shows its latest attempt and keeps the history
    retried = next(p for p in detail["plan"] if p["callId"] == "003-a")
    assert retried["history"] == [{"attempt": 1, "outcome": "providerError"}, {"attempt": 2, "outcome": "served"}]
    assert next(c for c in detail["calls"] if c["callId"] == "003-a")["attempt"] == 2


def test_claimed_attempts_without_a_result_are_reported_not_guessed(client, store):
    folder = store / "attempts" / "005-a"
    _write(folder / "1.claim.json", {"callId": "005-a", "attempt": 1, "approvalId": "ap-20261121T000000Z-abcd"})
    doc = json.loads((store / "experiment.json").read_text(encoding="utf-8"))
    doc["plan"].append({"callId": "005-a", "case": "real_b94559", "arm": "A", "repeat": 3, "seq": 5, "blindCode": "X05"})
    _write(store / "experiment.json", doc)
    plan = {p["callId"]: p["state"] for p in client.get(f"/api/eval/compare/{EXP}").json()["plan"]}
    assert plan["005-a"] == "inFlightOrNotInvoked"
    (folder / "1.model-started").write_text("{}", encoding="utf-8")
    plan = {p["callId"]: p["state"] for p in client.get(f"/api/eval/compare/{EXP}").json()["plan"]}
    assert plan["005-a"] == "inFlightOrUncertain"


# --- blind phase -------------------------------------------------------------------


def test_before_unblinding_nothing_ties_an_answer_to_its_arm(client, store):
    detail = client.get(f"/api/eval/compare/{EXP}").json()
    assert detail["blind"]["unblinded"] is False
    assert all(c["blindCode"] is None for c in detail["calls"])
    assert detail["grades"] == {}
    assert "text of" not in json.dumps(detail)  # detector excerpts quote the answer
    call = client.get(f"/api/eval/compare/{EXP}/calls/002-b").json()
    assert call["withheldForBlind"] is True and call["output"] is None and call["rejected"] is None
    assert call["checks"]["results"] == []
    assert "served B" not in json.dumps(call) and "quotes B" not in json.dumps(call)


def test_unblinding_is_recorded_once_and_then_shows_answers(client, store):
    _unblind(client)
    assert client.post(f"/api/eval/compare/{EXP}/unblind", json={"confirm": "unblind", "by": "u"}).status_code == 409
    assert client.post(f"/api/eval/compare/{EXP}/unblind", json={"confirm": "yes", "by": "u"}).status_code == 422
    detail = client.get(f"/api/eval/compare/{EXP}").json()
    assert detail["blind"]["unblinded"] is True
    assert {c["callId"]: c["blindCode"] for c in detail["calls"]}["002-b"] == "X01"
    call = client.get(f"/api/eval/compare/{EXP}/calls/001-a").json()
    assert call["available"] is False and call["output"] is None
    assert call["rejected"]["category"] == "runFactMismatch"
    assert call["rejected"]["answer"]["importantFindings"][0]["statement"] == "rejected A"


def test_a_call_with_a_leak_is_served_without_texts(client, store):
    path = store / "calls" / "002-b.json"
    call = json.loads(path.read_text(encoding="utf-8"))
    call["record"]["leakCount"] = 1
    path.write_text(json.dumps(call), encoding="utf-8")
    _unblind(client)
    served = client.get(f"/api/eval/compare/{EXP}/calls/002-b").json()
    assert served["withheldForPrivacy"] is True and served["output"] is None
    blind = client.get(f"/api/eval/compare/{EXP}/blind").json()
    assert "X01" not in [a["code"] for a in blind["answers"]]


def test_blind_view_has_only_gradable_answers_and_no_arm_gate_time_or_model(client, store):
    blind = client.get(f"/api/eval/compare/{EXP}/blind").json()
    # the provider timeout has no answer; the retried call shows its answer once
    assert [a["code"] for a in blind["answers"]] == ["X01", "X02", "X03"]
    text = json.dumps(blind["answers"])
    for leaked in ('"arm"', "runFactMismatch", "durationMs", '"models"', "available", "001-a", "timeout"):
        assert leaked not in text, leaked


def test_payloads_of_both_arms(client, store):
    body = client.get(f"/api/eval/compare/{EXP}/payloads/real_b94559").json()
    assert body["arms"]["A"]["payload"] == {"arm": "A"} and body["arms"]["B"]["payload"] == {"arm": "B"}
    assert client.get(f"/api/eval/compare/{EXP}/payloads/missing_case").status_code == 404


# --- grades -------------------------------------------------------------------------

GRADE = {
    "grader": "user",
    "claims": [{"section": "importantFindings", "index": 0, "verdict": "supported", "source": "record"}],
    "requiredCauses": {"required_tools": True},
    "understanding": 4,
    "usefulness": 3,
}


def test_grades_are_appended_never_replaced_and_say_whether_they_were_blind(client, store):
    first = client.post(f"/api/eval/compare/{EXP}/grades/X01", json=GRADE)
    assert first.status_code == 200 and first.json()["versions"] == 1 and first.json()["blind"] is True
    _unblind(client)
    second = client.post(f"/api/eval/compare/{EXP}/grades/X01", json=GRADE | {"understanding": 5})
    assert second.json()["versions"] == 2 and second.json()["blind"] is False
    files = sorted((store / "grades" / "X01").glob("*.json"))
    assert len(files) == 2
    assert json.loads(files[0].read_text(encoding="utf-8"))["understanding"] == 4
    detail = client.get(f"/api/eval/compare/{EXP}").json()
    assert detail["grades"]["X01"]["understanding"] == 5 and detail["grades"]["X01"]["versions"] == 2
    assert detail["blind"]["graded"] == 1 and detail["blind"]["gradedAfterUnblind"] == 1


def test_an_answer_that_cannot_be_counted_cannot_be_graded(client, store):
    assert client.post(f"/api/eval/compare/{EXP}/grades/X04", json=GRADE).status_code == 404  # provider timeout
    assert not (store / "grades").exists()


@pytest.mark.parametrize(
    "body",
    [
        {"grader": "u", "claims": [{"section": "importantFindings", "index": 5}]},
        {"grader": "u", "claims": [{"section": "importantFindings", "index": 0}, {"section": "importantFindings", "index": 0}]},
        {"grader": "u", "claims": [], "requiredCauses": {"invented": True}},
        {"grader": "u", "claims": [], "understanding": 6},
        {"grader": "", "claims": []},
    ],
)
def test_invalid_grades_are_refused(client, store, body):
    assert client.post(f"/api/eval/compare/{EXP}/grades/X01", json=body).status_code == 422
    assert not (store / "grades").exists()


def test_ids_are_validated(client, store):
    assert client.get("/api/eval/compare/..%2Fx").status_code in (400, 404)
    assert client.get("/api/eval/compare/BAD_ID").status_code == 400
    # (a bare ".." segment is collapsed by the client into the experiment URL itself)
    assert client.get(f"/api/eval/compare/{EXP}/calls/a..b").status_code == 400
    assert client.get(f"/api/eval/compare/{EXP}/calls/%2E%2E%5Cexperiment").status_code == 400
    assert client.get(f"/api/eval/compare/{EXP}/payloads/..%5Cx").status_code == 400
    assert client.post(f"/api/eval/compare/{EXP}/grades/../x", json={"grader": "u", "claims": []}).status_code in (400, 404, 405)
    assert client.post(f"/api/eval/compare/{EXP}/grades/X99", json={"grader": "u", "claims": []}).status_code == 404
