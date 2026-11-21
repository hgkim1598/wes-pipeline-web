"""Evaluator-only A/B comparison data (evals/ab_compare stores it).

  GET  /api/eval/compare                                experiments in the store
  GET  /api/eval/compare/{exp}                          protocol, arms, call states, auto scores, grades
  GET  /api/eval/compare/{exp}/calls/{call_id}          one call in full, gate-rejected answer included
  GET  /api/eval/compare/{exp}/payloads/{case}          both arms' model input for one case
  GET  /api/eval/compare/{exp}/blind                    answers by blind code, arm/gate/time hidden
  POST /api/eval/compare/{exp}/grades/{code}            append one human grade (never replaces)
  POST /api/eval/compare/{exp}/unblind                  end the blind phase (once, recorded)

Access
------

Every route answers 404 unless WES_EVAL_COMPARE=1 (config.EVAL_COMPARE) AND
the request comes from this machine (loopback peer, no non-loopback
X-Forwarded-For). The production start script binds 0.0.0.0, so the flag
alone would expose stored answers to the network. On top of that each request
must carry X-WES-Eval-Token equal to WES_EVAL_COMPARE_TOKEN: a dev server
started with `--host` proxies requests that arrive from elsewhere as
loopback, and only the token tells them apart. No token configured -> 503.

What the routes do and do not do
--------------------------------

This router never calls a model, never builds a payload and has no switch that
weakens a gate: answers are produced by the runner CLI, with the user's
approval, and this only reads what it stored. A gate-rejected answer is
readable here and nowhere else -- the product's synthesis route still serves
only an answer that passed.

States and outcomes are not decided here. They come from
evals/ab_compare/contract.py, the same module the runner uses, so the screen
cannot call something a gate rejection that the runner recorded as a provider
error. That module is imported lazily, only after the access check: a
deployment without evals/ never imports it.

Blind phase
-----------

Until someone records the end of the blind phase (POST /unblind, once),
nothing ties an answer text to its arm: the detail route omits blind codes,
grades and detector excerpts, and the call route withholds answer texts,
gate findings and evaluator details. The grade page reads /blind, which never
carries an arm. A grade saved after unblinding is stored with blind: false.

A stored call whose leak count is not zero is served without its texts.
"""

from __future__ import annotations

import json
import re
import secrets
from datetime import datetime, timezone
from pathlib import Path
from typing import Any, Literal

from fastapi import APIRouter, Depends, HTTPException, Request
from pydantic import BaseModel, Field

from .. import config

_LOOPBACK = frozenset({"127.0.0.1", "::1", "::ffff:127.0.0.1"})
TOKEN_HEADER = "x-wes-eval-token"


def _guard(request: Request) -> None:
    if not config.EVAL_COMPARE:
        raise HTTPException(status_code=404, detail="Not Found")
    peer = request.client.host if request.client else None
    forwarded = [p.strip() for p in request.headers.get("x-forwarded-for", "").split(",") if p.strip()]
    if peer not in _LOOPBACK or any(p not in _LOOPBACK for p in forwarded):
        raise HTTPException(status_code=404, detail="Not Found")
    expected = config.EVAL_COMPARE_TOKEN
    if not expected:
        raise HTTPException(status_code=503, detail="evalCompareTokenNotConfigured")
    given = request.headers.get(TOKEN_HEADER, "")
    if not secrets.compare_digest(given.encode("utf-8"), expected.encode("utf-8")):
        raise HTTPException(status_code=401, detail="evalCompareTokenRequired")


router = APIRouter(prefix="/api/eval/compare", tags=["eval-compare"], dependencies=[Depends(_guard)])

_ID = re.compile(r"^[a-z0-9][a-z0-9-]{2,63}$")
_CASE = re.compile(r"^[a-z0-9_]{3,64}$")
_CODE = re.compile(r"^X\d{2,3}$")
_SECTIONS = ("importantFindings", "limitations", "nextChecks", "uncertainties")
_ARMS = ("A", "B")


def _contract():
    from evals.ab_compare import contract  # lazy: see the module docstring

    return contract


def _store() -> Path:
    return Path(config.EVAL_AB_STORE)


def _read(path: Path) -> Any:
    return json.loads(path.read_text(encoding="utf-8"))


def _experiment(exp: str) -> tuple[Path, dict[str, Any]]:
    if not _ID.match(exp):
        raise HTTPException(status_code=400, detail="malformed experiment id")
    root = _store() / exp
    path = root / "experiment.json"
    if not path.is_file():
        raise HTTPException(status_code=404, detail="no such experiment")
    return root, _read(path)


def _unblind(root: Path) -> dict[str, Any] | None:
    path = root / "unblind.json"
    return _read(path) if path.is_file() else None


def _safe(record: dict[str, Any]) -> bool:
    return record.get("leakCount") == 0


def _rejected(record: dict[str, Any]) -> dict[str, Any] | None:
    rejected = record.get("rejectedOutput")
    if not isinstance(rejected, dict):
        return None
    return {
        "category": rejected.get("category"),
        "findings": rejected.get("findings") or [],
        "answer": rejected.get("answer"),
    }


def _answer_of(record: dict[str, Any]) -> dict[str, Any] | None:
    """What the model said: the served answer, else the one a gate discarded."""
    if isinstance(record.get("output"), dict):
        return record["output"]
    rejected = _rejected(record)
    return rejected["answer"] if rejected else None


def _claims(answer: dict[str, Any] | None) -> list[dict[str, Any]]:
    out: list[dict[str, Any]] = []
    if not isinstance(answer, dict):
        return out
    for section in _SECTIONS:
        for index, item in enumerate(answer.get(section) or []):
            if isinstance(item, dict):
                out.append(
                    {
                        "section": section,
                        "index": index,
                        "statement": str(item.get("statement") or ""),
                        "evidenceRefs": [r for r in item.get("evidenceRefs") or [] if isinstance(r, str)],
                    }
                )
    return out


def _latest_grades(root: Path) -> dict[str, dict[str, Any]]:
    folder = root / "grades"
    out: dict[str, dict[str, Any]] = {}
    if not folder.is_dir():
        return out
    for code_dir in sorted(folder.iterdir()):
        files = sorted(code_dir.glob("*.json")) if code_dir.is_dir() else []
        if files:
            out[code_dir.name] = _read(files[-1]) | {"versions": len(files)}
    return out


def _without_excerpts(scores: dict[str, Any]) -> dict[str, Any]:
    """Detector hits quote the answer; before unblinding that ties text to an arm."""
    out = dict(scores)
    for key in ("served", "rejected"):
        part = dict(out.get(key) or {})
        for field in ("detectorHits", "wrongCauseCandidates"):
            if field in part:
                part[field] = [{k: v for k, v in h.items() if k != "excerpt"} for h in part[field]]
        out[key] = part
    return out


def _call_summary(call: dict[str, Any], *, mock: bool, unblinded: bool, attempts: int) -> dict[str, Any]:
    record = call["record"]
    tool = record.get("toolUse") or {}
    trace = record.get("trace") or {}
    duration = record.get("durationMs") if record.get("durationMs") is not None else trace.get("durationMs")
    return {
        "callId": call["callId"],
        "attempt": call.get("attempt", 1),
        "attempts": attempts,
        "arm": call["arm"],
        "case": call["case"],
        "repeat": call["repeat"],
        "seq": call["seq"],
        "blindCode": call["blindCode"] if unblinded else None,
        "mock": call["mock"],
        "startedAt": call["startedAt"],
        # A rejected answer has no provenance; the trace still names the models.
        "models": record.get("models") or trace.get("models"),
        "promptHash": record.get("promptHash"),
        "knowledgeHash": record.get("knowledgeHash"),
        "payloadDigest": record.get("payloadDigest"),
        "toolUse": {
            "toolUsed": tool.get("toolUsed"),
            "openedStepIds": tool.get("openedStepIds") or [],
            "callCount": tool.get("callCount"),
        },
        "privacyOk": _safe(record),
        "evaluation": _contract().evaluation_of(call, mock=mock),
        "integrity": call.get("integrity"),
        "durationMs": duration,
        "wallMs": record.get("wallMs"),
        "scores": call["scores"] if unblinded else _without_excerpts(call["scores"]),
    }


def _gradable(root: Path, doc: dict[str, Any]) -> list[dict[str, Any]]:
    """Latest records whose answer may be graded (contract: countsForContent)."""
    contract = _contract()
    mock = bool(doc["mock"])
    return [
        call
        for call in contract.latest_records(root).values()
        if contract.evaluation_of(call, mock=mock)["countsForContent"]
    ]


@router.get("")
def list_experiments() -> dict[str, Any]:
    contract = _contract()
    store = _store()
    items = []
    if store.is_dir():
        for path in sorted(store.glob("*/experiment.json")):
            doc = _read(path)
            latest = contract.latest_records(path.parent)
            answered = sum(
                1 for c in latest.values() if contract.evaluation_of(c, mock=bool(doc["mock"]))["countsForGate"]
            )
            items.append(
                {
                    "experimentId": doc["experimentId"],
                    "title": doc["protocol"]["title"],
                    "mock": doc["mock"],
                    "createdAt": doc["createdAt"],
                    "planned": len(doc["plan"]),
                    "recorded": len(latest),
                    "answered": answered,
                }
            )
    return {"experiments": items}


@router.get("/{exp}")
def get_experiment(exp: str) -> dict[str, Any]:
    contract = _contract()
    root, doc = _experiment(exp)
    mock = bool(doc["mock"])
    unblind = _unblind(root)
    records = contract.call_records(root)
    checks_path = root / "payloads" / "checks.json"
    protocol = doc["protocol"]
    plan = []
    for c in doc["plan"]:
        state = contract.call_state(root, c["callId"], records=records.get(c["callId"], {}), mock=mock)
        history = [
            {"attempt": n, "outcome": contract.classify_outcome(r["record"])["outcome"]}
            for n, r in sorted(records.get(c["callId"], {}).items())
        ]
        plan.append(
            {k: c[k] for k in ("callId", "case", "arm", "repeat", "seq")}
            | {"state": state["state"], "outcome": state["outcome"], "attempts": state["attempts"], "history": history}
        )
    calls = [
        _call_summary(by_attempt[max(by_attempt)], mock=mock, unblinded=unblind is not None, attempts=len(by_attempt))
        for _call_id, by_attempt in sorted(records.items())
    ]
    approvals = []
    for approval_id, ap in contract.approvals(root).items():
        # The API does not probe worker locks (that could race a starting
        # worker), so an attempt it cannot prove unspent counts: an upper bound.
        spent = contract.approval_usage(root, approval_id, lock_probe=lambda _p: True)
        approvals.append(
            {
                "approvalId": approval_id,
                "mode": ap.get("mode"),
                "calls": ap.get("calls") or [],
                "maxCliCalls": ap.get("maxCliCalls"),
                "approvedAt": ap.get("approvedAt"),
                "usedAtMost": len(spent),
            }
        )
    grades = _latest_grades(root)
    gradable = _gradable(root, doc)
    graded = [grades[c["blindCode"]] for c in gradable if c["blindCode"] in grades]
    return {
        "experimentId": doc["experimentId"],
        "mock": mock,
        "createdAt": doc["createdAt"],
        "protocolSha256": doc["protocolSha256"],
        "protocol": {
            key: protocol[key]
            for key in (
                "id", "title", "fixedAt", "note", "conditions", "repeats", "order", "cases",
                "claimUnit", "metrics", "successCriteria", "intendedDifference",
            )
        }
        | {
            "protocolVersion": protocol.get("protocolVersion", 1),
            "outcomeContract": protocol.get("outcomeContract") or [],
            "evaluationRule": protocol.get("evaluationRule"),
            "modelIdentity": protocol.get("modelIdentity"),
            "detectors": [{k: d[k] for k in ("id", "metric", "label")} for d in protocol["detectors"]],
            "wrongCauseCandidates": [{k: d[k] for k in ("id", "label")} for d in protocol["wrongCauseCandidates"]],
        },
        "arms": doc["arms"],
        "armDiff": doc["armDiff"],
        "diffClassification": doc.get("diffClassification"),
        "sharedLocalInputs": sorted(doc.get("sharedLocalInputs") or {}),
        "payloadChecks": _read(checks_path)["cases"] if checks_path.is_file() else None,
        "blind": {
            "unblinded": unblind is not None,
            "unblindedAt": (unblind or {}).get("unblindedAt"),
            "gradable": len(gradable),
            "graded": len(graded),
            "gradedAfterUnblind": sum(1 for g in graded if g.get("blind") is False),
        },
        "approvals": approvals,
        "plan": plan,
        "calls": calls,
        "grades": grades if unblind is not None else {},
    }


@router.get("/{exp}/calls/{call_id}")
def get_call(exp: str, call_id: str) -> dict[str, Any]:
    contract = _contract()
    root, doc = _experiment(exp)
    if not _ID.match(call_id):
        raise HTTPException(status_code=400, detail="malformed call id")
    by_attempt = contract.call_records(root).get(call_id)
    if not by_attempt:
        raise HTTPException(status_code=404, detail="no such call")
    call = by_attempt[max(by_attempt)]
    record = call["record"]
    unblinded = _unblind(root) is not None
    safe = _safe(record)
    show = safe and unblinded
    checks = record.get("evaluation") or {}
    return _call_summary(call, mock=bool(doc["mock"]), unblinded=unblinded, attempts=len(by_attempt)) | {
        "available": record.get("available"),
        "errorCategory": record.get("errorCategory"),
        "trace": record.get("trace"),
        "evidenceUse": record.get("evidenceUse") if show else None,
        # The harness's deterministic checks; their details can quote the answer.
        "checks": {
            "deterministicPassed": checks.get("deterministicPassed"),
            "results": [
                {k: r.get(k) for k in ("name", "kind", "outcome", "detail")}
                for r in checks.get("results") or []
            ]
            if show
            else [],
        },
        "withheldForPrivacy": not safe,
        "withheldForBlind": safe and not unblinded,
        "output": record.get("output") if show else None,
        "rejected": _rejected(record) if show else None,
    }


@router.get("/{exp}/payloads/{case}")
def get_payloads(exp: str, case: str) -> dict[str, Any]:
    root, _doc = _experiment(exp)
    if not _CASE.match(case):
        raise HTTPException(status_code=400, detail="malformed case")
    out: dict[str, Any] = {}
    for arm in _ARMS:
        path = root / "payloads" / f"{case}.{arm}.json"
        if not path.is_file():
            raise HTTPException(status_code=404, detail="payloads not built")
        built = _read(path)
        safe = built.get("leakCount") == 0 and built.get("privacy") == "pass"
        out[arm] = {
            "payloadDigest": built.get("payloadDigest"),
            "constraintsDigest": built.get("constraintsDigest"),
            "promptHash": built.get("promptHash"),
            "knowledgeHash": built.get("knowledgeHash"),
            "allowedRefCount": built.get("allowedRefCount"),
            "withheldForPrivacy": not safe,
            "payload": built.get("payload") if safe else None,
        }
    return {"case": case, "arms": out}


@router.get("/{exp}/blind")
def get_blind(exp: str) -> dict[str, Any]:
    """Answers by blind code only. No arm, no gate result, no time, no model, no call id."""
    root, doc = _experiment(exp)
    labels = {c["case"]: c for c in doc["protocol"]["cases"]}
    answers = []
    for call in sorted(_gradable(root, doc), key=lambda c: c["blindCode"]):
        answer = _answer_of(call["record"])
        answers.append(
            {
                "code": call["blindCode"],
                "case": call["case"],
                "caseLabel": labels[call["case"]]["label"],
                "summary": answer.get("summary") if answer else None,
                "claims": _claims(answer),
            }
        )
    return {
        "experimentId": doc["experimentId"],
        "mock": doc["mock"],
        "unblinded": _unblind(root) is not None,
        "cases": [
            {k: c[k] for k in ("case", "label", "synthetic", "facts")} for c in doc["protocol"]["cases"]
        ],
        "answers": answers,
        "grades": _latest_grades(root),
    }


class ClaimGrade(BaseModel):
    section: Literal["importantFindings", "limitations", "nextChecks", "uncertainties"]
    index: int = Field(ge=0, le=200)
    verdict: Literal["supported", "contradicted", "undetermined"] | None = None
    source: Literal["record", "doc", "knowledge", "none"] | None = None
    nonRunClaim: bool = False
    execContradiction: bool = False
    unsupportedCause: bool = False


class GradeIn(BaseModel):
    grader: str = Field(min_length=1, max_length=40)
    claims: list[ClaimGrade] = Field(max_length=200)
    requiredCauses: dict[str, bool | None] = Field(default_factory=dict)
    understanding: int | None = Field(default=None, ge=1, le=5)
    usefulness: int | None = Field(default=None, ge=1, le=5)
    notes: str = Field(default="", max_length=2000)


def _write_new(path: Path, value: dict[str, Any]) -> None:
    path.parent.mkdir(parents=True, exist_ok=True)
    with path.open("x", encoding="utf-8", newline="\n") as handle:
        handle.write(json.dumps(value, ensure_ascii=False, indent=2) + "\n")


@router.post("/{exp}/grades/{code}")
def save_grade(exp: str, code: str, grade: GradeIn) -> dict[str, Any]:
    root, doc = _experiment(exp)
    if not _CODE.match(code):
        raise HTTPException(status_code=400, detail="malformed blind code")
    call = next((c for c in _gradable(root, doc) if c["blindCode"] == code), None)
    if call is None:
        raise HTTPException(status_code=404, detail="no gradable answer with this code")
    claims = {(c["section"], c["index"]) for c in _claims(_answer_of(call["record"]))}
    if any((c.section, c.index) not in claims for c in grade.claims):
        raise HTTPException(status_code=422, detail="a graded claim is not in this answer")
    if len({(c.section, c.index) for c in grade.claims}) != len(grade.claims):
        raise HTTPException(status_code=422, detail="a claim is graded twice")
    case = next(c for c in doc["protocol"]["cases"] if c["case"] == call["case"])
    known = {cause["id"] for cause in case["facts"]["requiredCauses"]}
    if set(grade.requiredCauses) - known:
        raise HTTPException(status_code=422, detail="unknown required cause")
    stamp = datetime.now(timezone.utc).strftime("%Y%m%dT%H%M%S%fZ")
    folder = root / "grades" / code
    saved = grade.model_dump() | {
        "code": code,
        "savedAt": stamp,
        "source": "human",
        # Graded before anyone could see which arm wrote it?
        "blind": _unblind(root) is None,
    }
    _write_new(folder / f"{stamp}-{secrets.token_hex(3)}.json", saved)
    return saved | {"versions": len(list(folder.glob("*.json")))}


class UnblindIn(BaseModel):
    confirm: Literal["unblind"]
    by: str = Field(min_length=1, max_length=40)


@router.post("/{exp}/unblind")
def unblind(exp: str, body: UnblindIn) -> dict[str, Any]:
    root, _doc = _experiment(exp)
    record = {"unblindedAt": datetime.now(timezone.utc).isoformat(timespec="seconds"), "by": body.by}
    try:
        _write_new(root / "unblind.json", record)
    except FileExistsError:
        raise HTTPException(status_code=409, detail="already unblinded") from None
    return record
