"""Independent review findings (2026-11-22) on the evaluator API.

    H3  before unblinding, per-call data derived from the answer or from the
        gate (outcome served/gateRejected, detector hits, durations, tool use,
        models) could be joined with the blind answers to infer the arm
    M2  for a call held back for privacy, fields derived from the answer
        (detector excerpts, the first gate rejection) were still served
    H2  a grade with unjudged claims or unanswered questions counted as a
        finished grade (backend half: the API says whether a grade is complete)

Fixtures and store layout come from test_eval_compare_api.py.
"""

from __future__ import annotations

import json

from app.tests.test_eval_compare_api import (  # noqa: F401 -- pytest fixtures
    EXP,
    GRADE,
    _unblind,
    _write,
    client,
    store,
)

# Values that exist only in answer-derived fields of the stored records:
# outcomes, the gate category, detector hits, opened steps, the model name,
# durations (1000 / 1500 ms) and the evaluator's check detail.
ANSWER_DERIVED = ('"served"', '"gateRejected"', "runFactMismatch", "detectorHits", "00_input_validation", '"m"', "1000", "1500", "quotes")
# Keys that must be present but null before unblinding (a null key carries nothing).
DERIVED_KEYS = ("models", "toolUse", "durationMs", "wallMs", "scores")


def test_h3_before_unblinding_no_answered_call_carries_answer_or_gate_data(client, store):
    detail = client.get(f"/api/eval/compare/{EXP}").json()
    answered = [c for c in detail["calls"] if c["callId"] in ("001-a", "002-b", "003-a")]
    text = json.dumps({"calls": answered, "plan": detail["plan"]})
    for leaked in ANSWER_DERIVED:
        assert leaked not in text, leaked
    for c in answered:
        assert c["evaluation"]["outcome"] == "answered"
        assert all(c[k] is None for k in DERIVED_KEYS), c["callId"]
    for call_id in ("001-a", "002-b"):
        body = client.get(f"/api/eval/compare/{EXP}/calls/{call_id}").json()
        for leaked in ANSWER_DERIVED:
            assert leaked not in json.dumps(body), (call_id, leaked)
        assert body["available"] is None and body["errorCategory"] is None and body["trace"] is None


def test_h3_execution_state_stays_visible_before_unblinding(client, store):
    """Provider failures have no answer to join; monitoring them must not wait."""
    detail = client.get(f"/api/eval/compare/{EXP}").json()
    timeout = next(c for c in detail["calls"] if c["callId"] == "004-b")
    assert timeout["evaluation"]["outcome"] == "providerError"
    assert {p["callId"]: p["state"] for p in detail["plan"]}["004-b"] == "recorded"


def test_m2_a_call_held_back_for_privacy_serves_nothing_derived_from_its_answer(client, store):
    path = store / "calls" / "002-b.json"
    call = json.loads(path.read_text(encoding="utf-8"))
    call["record"]["leakCount"] = 1
    call["record"]["trace"] = {"firstRejection": {"check": "sensitiveOutput", "detail": "LEAKED-SAMPLE-NAME"}}
    call["scores"]["served"]["detectorHits"][0]["excerpt"] = "LEAKED-SAMPLE-NAME in the answer"
    call["scores"]["gate"] = {"evaluated": True, "passed": True, "firstRejection": "LEAKED-SAMPLE-NAME"}
    _write(path, call)
    _unblind(client)
    for url in (f"/api/eval/compare/{EXP}", f"/api/eval/compare/{EXP}/calls/002-b", f"/api/eval/compare/{EXP}/blind"):
        assert "LEAKED-SAMPLE-NAME" not in client.get(url).text, url


def test_h2_the_api_says_whether_a_grade_is_complete(client, store):
    unfinished = GRADE | {
        "claims": [{"section": "importantFindings", "index": 0, "verdict": None}],
        "requiredCauses": {"required_tools": None},
        "understanding": None,
    }
    assert client.post(f"/api/eval/compare/{EXP}/grades/X01", json=unfinished).status_code == 200
    assert client.post(f"/api/eval/compare/{EXP}/grades/X02", json=GRADE).status_code == 200
    _unblind(client)
    detail = client.get(f"/api/eval/compare/{EXP}").json()
    assert detail["grades"]["X01"]["complete"] is False
    assert detail["grades"]["X02"]["complete"] is True
    assert detail["blind"]["graded"] == 1  # only the complete one counts as graded


# --- H3, second round (2026-11-22): membership and timing of the blind set --------
#
# The fixture already holds the shape the second review found: repeat 2 of the
# case has arm A answered (X03, after a retry) and arm B a provider timeout.
# The detail route shows 004-b as a provider error -- an execution fact it must
# show -- so if /blind lists X03 before unblinding, X03 can only be arm A.


def _blind_codes(client) -> list[str]:
    return [a["code"] for a in client.get(f"/api/eval/compare/{EXP}/blind").json()["answers"]]


def _add_pair(store, repeat: int, a: tuple[str, str] | None, b: tuple[str, str] | None) -> None:
    """Plan (case, repeat) for both arms; record each arm given as (code, kind)."""
    from app.tests.test_eval_compare_api import _call

    doc = json.loads((store / "experiment.json").read_text(encoding="utf-8"))
    codes = {"A": f"X{10 + 2 * repeat:02d}", "B": f"X{11 + 2 * repeat:02d}"}
    for arm, given in (("A", a), ("B", b)):
        call_id = f"{repeat:03d}-p-{arm.lower()}"
        doc["plan"].append({"callId": call_id, "case": "real_b94559", "arm": arm, "repeat": repeat, "seq": repeat, "blindCode": codes[arm]})
        if given is not None:
            call = _call(call_id, arm, codes[arm], given[1])
            call["repeat"] = repeat
            _write(store / "calls" / f"{call_id}.json", call)
    _write(store / "experiment.json", doc)


def _pairs_in_blind(client, codes: list[str]) -> dict[tuple[str, int], int]:
    """After unblinding: how many of each planned (case, repeat)'s answers `codes` held."""
    detail = client.get(f"/api/eval/compare/{EXP}").json()
    pair = {p["callId"]: (p["case"], p["repeat"]) for p in detail["plan"]}
    by_code = {c["blindCode"]: pair[c["callId"]] for c in detail["calls"]}
    out: dict[tuple[str, int], int] = {}
    for code in codes:
        out[by_code[code]] = out.get(by_code[code], 0) + 1
    return out


def test_h3r2_an_answer_whose_partner_has_no_answer_is_not_in_the_blind_set(client, store):
    assert _blind_codes(client) == ["X01", "X02"]  # repeat 1: both arms answered
    detail = client.get(f"/api/eval/compare/{EXP}").json()
    assert detail["blind"]["gradable"] == 2 and detail["blind"]["heldUntilUnblind"] == 1
    # The code cannot be probed either: grading it answers like an unknown code.
    assert client.post(f"/api/eval/compare/{EXP}/grades/X03", json=GRADE).status_code == 404
    assert not (store / "grades").exists()
    # After unblinding the held answer can be graded, recorded as not blind.
    _unblind(client)
    assert _blind_codes(client) == ["X01", "X02", "X03"]
    saved = client.post(f"/api/eval/compare/{EXP}/grades/X03", json=GRADE).json()
    assert saved["blind"] is False


def test_h3r2_a_pair_enters_the_blind_set_only_when_both_arms_are_recorded(client, store):
    """A run in progress: the first arm's answer must not appear before the second's."""
    _add_pair(store, 3, ("X16", "served"), None)  # B still planned
    assert _blind_codes(client) == ["X01", "X02"]
    from app.tests.test_eval_compare_api import _call

    call = _call("003-p-b", "B", "X17", "served")
    call["repeat"] = 3
    _write(store / "calls" / "003-p-b.json", call)
    assert _blind_codes(client) == ["X01", "X02", "X16", "X17"]  # both at once


def test_h3r2_a_partner_with_an_in_flight_attempt_holds_the_pair(client, store):
    _add_pair(store, 3, ("X16", "served"), None)
    _write(store / "attempts" / "003-p-b" / "1.claim.json", {"callId": "003-p-b", "attempt": 1, "approvalId": "ap-x"})
    assert "X16" not in _blind_codes(client)


def test_h3r2_a_partner_held_for_privacy_or_without_a_parsed_answer_holds_the_pair(client, store):
    from app.tests.test_eval_compare_api import _call

    # privacy: arm B of repeat 1 leaked, so its partner X02 is held too
    path = store / "calls" / "002-b.json"
    leaked = json.loads(path.read_text(encoding="utf-8"))
    leaked["record"]["leakCount"] = 1
    _write(path, leaked)
    assert _blind_codes(client) == []
    # a gate rejection whose answer did not parse: an answered call with nothing to grade
    _add_pair(store, 3, ("X16", "served"), ("X17", "rejected"))
    unparsed = _call("003-p-b", "B", "X17", "rejected")
    unparsed["repeat"] = 3
    unparsed["record"]["rejectedOutput"]["answer"] = None
    _write(store / "calls" / "003-p-b.json", unparsed)
    assert _blind_codes(client) == []
    # ... and the detail route does not say which answered call had nothing to grade
    detail = client.get(f"/api/eval/compare/{EXP}").json()
    for c in detail["calls"]:
        if c["evaluation"]["outcome"] == "answered":
            assert c["evaluation"]["countsForContent"] is None, c["callId"]


def test_h3r2_every_pair_is_in_the_blind_set_whole_or_not_at_all(client, store):
    """The invariant the fix rests on, checked against the arm map after unblinding."""
    _add_pair(store, 3, ("X16", "served"), ("X17", "rejected"))
    _add_pair(store, 4, ("X18", "served"), ("X19", "timeout"))
    _add_pair(store, 5, None, ("X21", "served"))
    before = _blind_codes(client)
    _unblind(client)
    counts = _pairs_in_blind(client, before)
    assert counts and all(n == 2 for n in counts.values()), counts
    assert set(counts) == {("real_b94559", 1), ("real_b94559", 3)}


def test_h3r2_a_newer_claimed_attempt_holds_a_pair_whose_records_answered(client, store):
    """Both arms have an answered record, but B's newer attempt is claimed: not settled.

    (Codex review round 1, LOW: the in-flight test above passes even without
    the call_state check, because B there has no answer at all.)
    """
    from app.tests.test_eval_compare_api import _call

    _add_pair(store, 3, ("X16", "served"), None)
    older = _call("003-p-b", "B", "X17", "served", attempt=1)
    older["repeat"] = 3
    _write(store / "calls" / "003-p-b.a1.json", older)
    assert "X17" in _blind_codes(client)  # settled: both arms recorded
    _write(store / "attempts" / "003-p-b" / "2.claim.json", {"callId": "003-p-b", "attempt": 2, "approvalId": "ap-x"})
    codes = _blind_codes(client)
    assert "X16" not in codes and "X17" not in codes


def test_h3r2_whole_pairs_hold_across_cases_interleaving_and_every_exclusion(client, store):
    """Two cases, both arm orders, and each kind of partner without a gradable answer."""
    from app.tests.test_eval_compare_api import CASE, _call

    doc = json.loads((store / "experiment.json").read_text(encoding="utf-8"))
    doc["protocol"]["cases"].append(CASE | {"case": "real_3a22c5", "label": "3a22c5"})
    _write(store / "experiment.json", doc)

    def pair(case: str, repeat: int, first: str, kinds: dict[str, str | None], seq: int) -> None:
        doc = json.loads((store / "experiment.json").read_text(encoding="utf-8"))
        for offset, arm in enumerate((first, "B" if first == "A" else "A")):
            call_id = f"{seq + offset:03d}-{case[-6:]}-{arm.lower()}-r{repeat}"
            code = f"X{seq + offset:02d}"
            doc["plan"].append({"callId": call_id, "case": case, "arm": arm, "repeat": repeat, "seq": seq + offset, "blindCode": code})
            kind = kinds[arm]
            if kind is None:
                continue
            call = _call(call_id, arm, code, "unclassified" if kind == "unclassified" else ("served" if kind == "integrity" else kind))
            call["case"], call["repeat"] = case, repeat
            if kind == "integrity":
                call["integrity"] = {"ok": False, "checks": {}, "notInCallPathImported": []}
            if kind == "unclassified":
                call["record"] |= {"available": True, "output": None, "errorCategory": None}
            _write(store / "calls" / f"{call_id}.json", call)
        _write(store / "experiment.json", doc)

    pair("real_3a22c5", 1, "B", {"A": "served", "B": "rejected"}, 20)  # whole, B ran first
    pair("real_3a22c5", 2, "A", {"A": "served", "B": "integrity"}, 22)
    pair("real_3a22c5", 3, "B", {"A": "unclassified", "B": "served"}, 24)
    pair("real_b94559", 3, "B", {"A": "served", "B": "served"}, 26)  # whole
    pair("real_b94559", 4, "A", {"A": None, "B": "served"}, 28)  # A not run yet
    before = _blind_codes(client)
    blind = client.get(f"/api/eval/compare/{EXP}/blind").json()
    detail = client.get(f"/api/eval/compare/{EXP}").json()
    # the two routes agree on the set and on what is held
    assert detail["blind"]["gradable"] == len(before)
    assert detail["blind"]["heldUntilUnblind"] == blind["heldUntilUnblind"] == 4  # X03, X22, X24, X29
    _unblind(client)
    counts = _pairs_in_blind(client, before)
    assert counts == {("real_b94559", 1): 2, ("real_3a22c5", 1): 2, ("real_b94559", 3): 2}


def test_h3r2_a_held_code_and_an_unknown_code_answer_alike(client, store):
    """Grading cannot tell a held answer from no answer, valid body or not."""
    held = client.post(f"/api/eval/compare/{EXP}/grades/X03", json=GRADE)
    unknown = client.post(f"/api/eval/compare/{EXP}/grades/X99", json=GRADE)
    assert (held.status_code, held.json()) == (unknown.status_code, unknown.json()) == (404, {"detail": "no gradable answer with this code"})
    # Schema-valid bodies that only an answer can refuse (claim not in it,
    # graded twice, unknown cause): membership is checked first, so a held
    # code still answers 404, never the answer-specific 422 (Codex round 2,
    # LOW: an invalid schema is refused before the route runs, so it proves nothing).
    answer_specific = [
        GRADE | {"claims": [{"section": "importantFindings", "index": 9, "verdict": "supported"}]},
        GRADE | {"claims": [{"section": "importantFindings", "index": 0}, {"section": "importantFindings", "index": 0}]},
        GRADE | {"requiredCauses": {"invented": True}},
    ]
    for body in answer_specific:
        held_bad = client.post(f"/api/eval/compare/{EXP}/grades/X03", json=body)
        unknown_bad = client.post(f"/api/eval/compare/{EXP}/grades/X99", json=body)
        assert (held_bad.status_code, held_bad.json()) == (unknown_bad.status_code, unknown_bad.json()), body
        assert held_bad.status_code == 404
        # ... while a code in the blind set does reach the answer's own checks
        assert client.post(f"/api/eval/compare/{EXP}/grades/X01", json=body).status_code == 422
    assert not (store / "grades").exists()


def test_h3r2_counts_reconcile_after_a_held_answer_is_graded(client, store):
    for code in ("X01", "X02"):
        assert client.post(f"/api/eval/compare/{EXP}/grades/{code}", json=GRADE).json()["blind"] is True
    blind_before = client.get(f"/api/eval/compare/{EXP}").json()["blind"]
    assert (blind_before["gradable"], blind_before["graded"], blind_before["heldUntilUnblind"]) == (2, 2, 1)
    _unblind(client)
    assert client.post(f"/api/eval/compare/{EXP}/grades/X03", json=GRADE).json()["blind"] is False
    detail = client.get(f"/api/eval/compare/{EXP}").json()
    assert (detail["blind"]["gradable"], detail["blind"]["graded"], detail["blind"]["heldUntilUnblind"]) == (3, 3, 0)
    assert detail["blind"]["gradedAfterUnblind"] == 1
    assert sorted(client.get(f"/api/eval/compare/{EXP}/blind").json()["grades"]) == ["X01", "X02", "X03"]


# --- PR review (Copilot): a damaged record file is shown and holds its pair --------


def test_pr_a_damaged_record_marks_the_call_and_nothing_stands_in_for_it(client, store):
    """Flat (no claim) and versioned-without-claim damage both read as unreadableRecord,
    and the call's readable older record is neither blind-graded nor graded after unblinding."""
    root = store
    (root / "calls" / "002-b.json").write_text('{"callId": "half', encoding="utf-8")  # flat, attempt 1
    (root / "calls" / "001-a.a2.json").write_text("[]", encoding="utf-8")  # versioned, no claim, not an object
    states = {c["callId"]: c["state"] for c in client.get(f"/api/eval/compare/{EXP}").json()["plan"]}
    assert states["001-a"] == states["002-b"] == "unreadableRecord"
    assert not {"X01", "X02"} & set(_blind_codes(client))
    _unblind(client)
    assert not {"X01", "X02"} & set(_blind_codes(client))
    assert client.post(f"/api/eval/compare/{EXP}/grades/X02", json=GRADE).status_code == 404


def test_pr_a_damaged_partner_holds_a_healthy_answer_until_unblinding(client, store):
    (store / "calls" / "001-a.a2.json").write_text('{"callId": "half', encoding="utf-8")
    assert "X01" not in _blind_codes(client)  # 002-b is fine, its partner is not
    _unblind(client)
    codes = _blind_codes(client)
    assert "X01" in codes and "X02" not in codes


def test_pr_a_damaged_call_is_not_summarised_or_counted_from_an_older_record(client, store):
    """The older readable attempt would otherwise feed the Gate counts and the call view."""
    (store / "calls" / "001-a.a2.json").write_text('{"callId": "half', encoding="utf-8")
    _unblind(client)
    detail = client.get(f"/api/eval/compare/{EXP}").json()
    assert "001-a" not in {c["callId"] for c in detail["calls"]}
    assert "002-b" in {c["callId"] for c in detail["calls"]}
    response = client.get(f"/api/eval/compare/{EXP}/calls/001-a")
    assert response.status_code == 409
    assert client.get(f"/api/eval/compare/{EXP}/calls/002-b").status_code == 200
