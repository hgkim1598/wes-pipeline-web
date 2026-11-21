"""The A/B experiment's state contract: one definition, read by the runner and the API.

Why this module exists
----------------------

The first version had no explicit states. Each reader inferred them from
whatever it had at hand:

    runner   "done"       = a file calls/<id>.json exists
    scoring  "gate"       = record["available"]
    UI       "Gate 거부"  = not scores.gate.passed
    UI       "미호출"     = no calls/<id>.json

Four different facts were folded into those two signals: whether a model call
was STARTED, whether the PROVIDER returned, whether the GATE passed, and
whether the result was RECORDED. So a provider timeout read as a gate
rejection, a call that spent usage but crashed before its record was written
read as "not called yet" and was called again, and the approval ("these two
calls") existed only as a `--limit` count relative to whatever was left.

This module names those facts separately and says how each is decided.

Outcome of one finished attempt (decided from the harness record alone)
-----------------------------------------------------------------------

    served         the provider answered and every gate passed
    gateRejected   the provider answered and a gate discarded the answer
                   (the harness kept it in rejectedOutput)
    providerError  the provider never produced an answer: timeout, usage
                   limit, CLI missing or failed, unreadable response.
                   No gate ran. Not a gate result.
    unclassified   the record contradicts itself or uses a category this
                   contract does not know. Counted nowhere until a person
                   looks at it.

The decision is structural, not a category lookup alone: a gate rejection is
exactly an answer the gate observer received (synthesis.build_run_synthesis
calls on_rejection only after the provider returned), and a provider error is
exactly an unavailable result with no such answer and a provider category.

Life of one planned call (decided from durable files, in this order)
--------------------------------------------------------------------

    attempts/<callId>/<n>.claim.json     written (create-only) by the runner
                                          BEFORE the worker process starts
    attempts/<callId>/<n>.lock            held (OS lock) by the worker for its
                                          whole life; released by the OS when it dies
    attempts/<callId>/<n>.model-started   written and fsynced by the worker
                                          immediately BEFORE the model call
    attempts/<callId>/<n>.raw.json        the worker's result, published atomically
    calls/<callId>.a<n>.json              the runner's record of that attempt
    calls/<callId>.json                   (first version: attempt 1, no claim)

    planned      no claim, no record
    recorded     a record exists for the latest attempt -> it has an outcome
    recoverable  a raw result exists but no record: finish it WITHOUT a new call
    running      the latest attempt's lock is held by a live process
    uncertain    claimed, model-started written, no result, nobody holds the
                 lock: the model may or may not have been called. Never
                 assumed "not called"; never called again automatically.
    notInvoked   claimed, no model-started, no result, nobody holds the lock:
                 the worker never reached the model (it writes model-started
                 first), so no usage was spent and a new attempt may start.

The API cannot probe locks without racing a starting worker, so it reports
the last two as `inFlightOrUncertain` / `inFlightOrNotInvoked` instead.

Approval
--------

`approvals/<id>.json` names exact call ids and a maximum number of CLI calls.
An attempt counts against it unless it is provably notInvoked. The runner
holds the experiment lock while it counts and claims, so two runners cannot
both spend the last unit.
"""

from __future__ import annotations

import json
import os
import re
from contextlib import contextmanager
from pathlib import Path
from typing import Any, Callable, Iterator

CALL_ID = re.compile(r"^[a-z0-9][a-z0-9-]{2,63}$")
APPROVAL_ID = re.compile(r"^ap-\d{8}T\d{6}Z-[0-9a-f]{4}$")
_RECORD_FILE = re.compile(r"^(?P<call>[a-z0-9][a-z0-9-]{2,63})(?:\.a(?P<attempt>[1-9]\d{0,2}))?\.json$")
_CLAIM_FILE = re.compile(r"^(?P<n>[1-9]\d{0,2})\.claim\.json$")

# ProviderError categories (app/services/explanation/llm/provider.py): the
# provider produced no answer, so no gate ran.
PROVIDER_ERROR_CATEGORIES = frozenset(
    {
        "providerUnavailable",
        "notAuthenticated",
        "meteredAuthPresent",
        "usageLimit",
        "timeout",
        "providerFailed",
        "malformedProviderResponse",
    }
)
OUTCOMES = ("served", "gateRejected", "providerError", "unclassified")
ANSWER_OUTCOMES = ("served", "gateRejected")
CALL_STATES = (
    "planned",
    "recorded",
    "recoverable",
    "running",
    "uncertain",
    "notInvoked",
    "inFlightOrUncertain",
    "inFlightOrNotInvoked",
)
# Modules the worker itself imports from the tree in the no-model modes (the
# real-CLI guard). They are not part of the call path under test.
WORKER_OWN_IMPORTS = frozenset({"backend/app/tests/__init__.py", "backend/app/tests/real_cli_guard.py"})


def read_json(path: Path) -> Any:
    return json.loads(path.read_text(encoding="utf-8"))


# --- outcome -----------------------------------------------------------------


def classify_outcome(record: dict[str, Any]) -> dict[str, Any]:
    """Outcome of one finished attempt, from the harness record only."""
    available = record.get("available")
    category = record.get("errorCategory")
    rejected = record.get("rejectedOutput")
    output = record.get("output")
    if available is True and isinstance(output, dict) and not rejected:
        return {"outcome": "served", "category": None, "answerProduced": True, "reason": None}
    if available is False and isinstance(rejected, dict):
        if category in PROVIDER_ERROR_CATEGORIES:
            return _unclassified(category, "gate answer with a provider category")
        return {
            "outcome": "gateRejected",
            "category": category,
            # invalidSynthesis can discard an answer that did not even parse.
            "answerProduced": isinstance(rejected.get("answer"), dict),
            "reason": None,
        }
    if available is False and not rejected and output is None and category in PROVIDER_ERROR_CATEGORIES:
        return {"outcome": "providerError", "category": category, "answerProduced": False, "reason": None}
    return _unclassified(category, "record does not match any outcome")


def _unclassified(category: Any, reason: str) -> dict[str, Any]:
    return {"outcome": "unclassified", "category": category, "answerProduced": False, "reason": reason}


def evaluation_of(call: dict[str, Any], *, mock: bool) -> dict[str, Any]:
    """What one recorded attempt may count towards, and if nothing, why.

    countsForGate     served or gateRejected, with nothing excluding it
    countsForContent  the same, and there is an answer text to score/grade
    exclusion         privacy | integrity | integrityUnchecked |
                      providerError | unclassified | None
    """
    record = call.get("record") or {}
    outcome = classify_outcome(record)
    integrity = call.get("integrity")
    exclusion: str | None = None
    if record.get("leakCount") != 0:
        exclusion = "privacy"
    elif isinstance(integrity, dict) and integrity.get("ok") is not True:
        exclusion = "integrity"
    elif integrity is None and not mock:
        # First-version records were never checked after the call.
        exclusion = "integrityUnchecked"
    elif outcome["outcome"] not in ANSWER_OUTCOMES:
        exclusion = outcome["outcome"]
    counts = exclusion is None
    return {
        **outcome,
        "exclusion": exclusion,
        "countsForGate": counts,
        "countsForContent": counts and outcome["answerProduced"],
        "integrityChecked": isinstance(integrity, dict),
    }


# --- store layout --------------------------------------------------------------


def attempt_dir(root: Path, call_id: str) -> Path:
    if not CALL_ID.match(call_id):
        raise ValueError("malformed call id")
    return root / "attempts" / call_id


def attempt_paths(root: Path, call_id: str, n: int) -> dict[str, Path]:
    folder = attempt_dir(root, call_id)
    return {
        "claim": folder / f"{n}.claim.json",
        "lock": folder / f"{n}.lock",
        "started": folder / f"{n}.model-started",
        "raw": folder / f"{n}.raw.json",
        "exit": folder / f"{n}.worker-exit.json",
        "record": root / "calls" / f"{call_id}.a{n}.json",
    }


def claimed_attempts(root: Path, call_id: str) -> list[int]:
    folder = attempt_dir(root, call_id)
    if not folder.is_dir():
        return []
    return sorted(int(m["n"]) for p in folder.iterdir() if (m := _CLAIM_FILE.match(p.name)))


def call_records(root: Path) -> dict[str, dict[int, dict[str, Any]]]:
    """{callId: {attempt: stored record}}. A first-version flat file is attempt 1."""
    folder = root / "calls"
    out: dict[str, dict[int, dict[str, Any]]] = {}
    if not folder.is_dir():
        return out
    for path in sorted(folder.iterdir()):
        match = _RECORD_FILE.match(path.name)
        if not match or not path.is_file():
            continue
        attempt = int(match["attempt"] or 1)
        call = read_json(path)
        call.setdefault("attempt", attempt)
        out.setdefault(match["call"], {})[attempt] = call
    return out


def latest_records(root: Path) -> dict[str, dict[str, Any]]:
    return {call_id: by_attempt[max(by_attempt)] for call_id, by_attempt in call_records(root).items()}


# --- call state ----------------------------------------------------------------

LockProbe = Callable[[Path], bool]


def call_state(
    root: Path,
    call_id: str,
    *,
    records: dict[int, dict[str, Any]] | None = None,
    lock_probe: LockProbe | None = None,
    mock: bool = False,
) -> dict[str, Any]:
    """State of one planned call (see the module docstring)."""
    if records is None:
        records = call_records(root).get(call_id, {})
    claimed = claimed_attempts(root, call_id)
    attempts = sorted(set(claimed) | set(records))
    base = {"callId": call_id, "attempts": len(attempts), "attempt": attempts[-1] if attempts else None}
    if not attempts:
        return base | {"state": "planned", "outcome": None, "evaluation": None}
    latest = attempts[-1]
    if latest in records:
        evaluation = evaluation_of(records[latest], mock=mock)
        return base | {"state": "recorded", "outcome": evaluation["outcome"], "evaluation": evaluation}
    paths = attempt_paths(root, call_id, latest)
    if paths["raw"].is_file():
        state = "recoverable"
    elif lock_probe is None:
        state = "inFlightOrUncertain" if paths["started"].exists() else "inFlightOrNotInvoked"
    elif lock_probe(paths["lock"]):
        state = "running"
    else:
        state = "uncertain" if paths["started"].exists() else "notInvoked"
    return base | {"state": state, "outcome": None, "evaluation": None}


def attempt_spent(root: Path, call_id: str, n: int, *, lock_probe: LockProbe) -> bool:
    """Could attempt `n` have used a CLI call? Only a provable no is False."""
    paths = attempt_paths(root, call_id, n)
    if paths["record"].is_file() or paths["raw"].is_file() or paths["started"].exists():
        return True
    return lock_probe(paths["lock"])  # a live worker may be about to call


# --- approvals -------------------------------------------------------------------


def approvals(root: Path) -> dict[str, dict[str, Any]]:
    folder = root / "approvals"
    if not folder.is_dir():
        return {}
    return {p.stem: read_json(p) for p in sorted(folder.glob("ap-*.json")) if APPROVAL_ID.match(p.stem)}


def approval_usage(root: Path, approval_id: str, *, lock_probe: LockProbe) -> list[dict[str, Any]]:
    """Every attempt claimed under this approval that may have spent a call."""
    used = []
    folder = root / "attempts"
    if not folder.is_dir():
        return used
    for call_dir in sorted(folder.iterdir()):
        if not call_dir.is_dir() or not CALL_ID.match(call_dir.name):
            continue
        for n in claimed_attempts(root, call_dir.name):
            claim = read_json(attempt_paths(root, call_dir.name, n)["claim"])
            if claim.get("approvalId") == approval_id and attempt_spent(root, call_dir.name, n, lock_probe=lock_probe):
                used.append({"callId": call_dir.name, "attempt": n})
    return used


# --- OS file locks (released by the OS when the holder dies) ----------------------


@contextmanager
def os_lock(path: Path) -> Iterator[None]:
    """Hold an exclusive, non-blocking lock on `path`; raise BlockingIOError if held.

    An OS lock rather than a lock FILE: a crashed holder cannot leave a stale
    lock behind, so nobody is ever tempted to delete one by hand.
    """
    path.parent.mkdir(parents=True, exist_ok=True)
    handle = open(path, "a+b")  # noqa: SIM115 -- closed in finally
    try:
        _lock(handle)
        try:
            yield
        finally:
            _unlock(handle)
    finally:
        handle.close()


def is_held(path: Path) -> bool:
    """True if another handle holds the lock. Never creates the file."""
    if not path.exists():
        return False
    try:
        handle = open(path, "r+b")  # noqa: SIM115
    except OSError:
        return True
    try:
        try:
            _lock(handle)
        except BlockingIOError:
            return True
        _unlock(handle)
        return False
    finally:
        handle.close()


def _lock(handle) -> None:
    if os.name == "nt":
        import msvcrt

        handle.seek(0)
        try:
            msvcrt.locking(handle.fileno(), msvcrt.LK_NBLCK, 1)
        except OSError as exc:
            raise BlockingIOError(str(exc)) from exc
    else:
        import fcntl

        try:
            fcntl.flock(handle.fileno(), fcntl.LOCK_EX | fcntl.LOCK_NB)
        except OSError as exc:
            raise BlockingIOError(str(exc)) from exc


def _unlock(handle) -> None:
    if os.name == "nt":
        import msvcrt

        handle.seek(0)
        try:
            msvcrt.locking(handle.fileno(), msvcrt.LK_UNLCK, 1)
        except OSError:
            pass
    else:
        import fcntl

        fcntl.flock(handle.fileno(), fcntl.LOCK_UN)
