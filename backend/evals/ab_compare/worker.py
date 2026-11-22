"""One arm, one case, one action -- run inside a child process against ONE code tree.

    python -I worker.py --tree <snapshot>/backend --request req.json --out out.json

Why a child process per arm
---------------------------

The two arms are two versions of the same packages (`app`, `evals`). They
cannot share one interpreter: whichever was imported first would win. Each
call therefore starts a fresh interpreter whose import path begins with that
arm's frozen tree, and the worker refuses to continue unless `app` really was
imported from there.

This file is the same bytes for both arms (the runner records its hash). It
does nothing but call the arm's OWN harness functions (`evals.run_eval`), so the
measurement path -- payload, provider call, gates, evaluators -- is the code of
the arm under test, not a re-implementation.

Model calls
-----------

    payload   never calls a model. The provider and process spawning are
              replaced by functions that raise, before the run is built.
    mock      never calls a model. The provider is replaced by a fixed answer
              marked as mock in every sentence; spawning still raises.
    real      calls the CLI through the arm's own provider. Refused unless the
              request says so AND the parent set WES_AB_ALLOW_REAL_CLAUDE=1.

One attempt, at most one model call (mock and real)
----------------------------------------------------

The runner claims the attempt in a durable file before starting this process
(evals/ab_compare/contract.py has the whole contract). This worker then:

    1. takes the attempt's OS lock for its whole life, so another runner can
       see that it is alive (the OS releases the lock if it dies);
    2. refuses unless the claim exists, and refuses -- before importing
       anything that could call a model -- if this attempt was sealed as not
       invoked, or already has a model-started marker or a result. The seal is
       written by a runner under this same lock, so a worker that started
       late (its runner was killed and a new one sealed the attempt) stops
       here instead of calling the model (review B1, 2026-11-22);
    3. restores the run, then compares what the call is about to use with
       what was approved: the payload digest AND the digest of the restored
       run the step tool will read (review H4, 2026-11-22). A difference stops
       it before step 4;
    4. writes and fsyncs the model-started marker immediately before the
       model call. No marker therefore PROVES no call was made;
    5. publishes its result atomically (written aside, then hard-linked into
       place), so a reader sees either no result or a complete one.

It also lists every module it imported from the tree, so the runner can show
that files classified as outside the call path were not loaded.
"""

from __future__ import annotations

import argparse
import hashlib
import json
import os
import shutil
import sys
import tempfile
import time
from contextlib import contextmanager
from pathlib import Path
from typing import Any

MOCK_MODEL = "mock-no-model"
MOCK_MARK = "[모의 응답 — 실제 Claude 답변이 아님]"
# Must equal evals/ab_compare/contract.ATTEMPT_PROTOCOL (this file is frozen into
# each experiment and cannot import it).
ATTEMPT_PROTOCOL = 2


class InputsChanged(RuntimeError):
    """What the call would use differs from what was approved. No model call."""


def canonical_sha256(value: Any) -> str:
    text = json.dumps(value, ensure_ascii=False, sort_keys=True, separators=(",", ":"))
    return hashlib.sha256(text.encode("utf-8")).hexdigest()


def _prepare_environment(request: dict[str, Any], scratch: Path) -> None:
    """Every WES_* setting comes from the request; nothing leaks in from the shell."""
    for key in list(os.environ):
        if key.startswith("WES_") and key != "WES_AB_ALLOW_REAL_CLAUDE":
            del os.environ[key]
    cond = request["conditions"]
    os.environ["WES_SYNTHESIS_MODEL"] = cond["model"]
    os.environ["WES_DOC_RAG"] = "1" if cond["docRag"] else "0"
    os.environ["WES_AGENT_DOC_EVIDENCE"] = "1" if cond["agentDocEvidence"] else "0"
    os.environ["WES_SYNTHESIS_REPAIR"] = "on" if cond["repair"] else "off"
    os.environ["WES_SYNTHESIS_TIMEOUT_SECONDS"] = str(cond["timeoutSeconds"])
    os.environ["WES_EVAL_LOCAL_CONFIG"] = request["localConfig"]
    # Nothing should touch these before isolated_environment() swaps them, but
    # if anything does it lands in this throwaway directory, not in a real DB.
    os.environ["WES_DB_PATH"] = str(scratch / "app.db")
    os.environ["WES_RUNS_ROOT"] = str(scratch / "runs")
    os.environ["WES_UPLOAD_ROOT"] = str(scratch / "uploads")


def _import_tree(tree: Path):
    sys.path.insert(0, str(tree))
    import app  # noqa: F401  (imported for the location check)

    location = Path(app.__file__).resolve()
    if tree.resolve() not in location.parents:
        raise SystemExit("worker: app was not imported from the requested tree")
    from app.services.explanation.llm import provider

    return provider


class _NoProcess:
    def __init__(self, *_a: Any, **_k: Any) -> None:
        raise RuntimeError("process spawning is disabled in this worker mode")


def _refuse(*_a: Any, **_k: Any) -> Any:
    raise RuntimeError("model call attempted in a worker mode that forbids it")


def _guard_processes() -> None:
    """No-model modes: no child process at all, and the test suite's audit-hook
    guard on top (it refuses a `claude` process whatever PATH says, and any
    non-loopback connection; app/tests/real_cli_guard.py)."""
    import subprocess

    from app.tests import real_cli_guard

    real_cli_guard.install("deny")

    subprocess.Popen = _NoProcess  # type: ignore[assignment,misc]
    subprocess.run = _refuse  # type: ignore[assignment]


def _mock_answer(scenario: str) -> dict[str, Any]:
    """A fixed answer. Every sentence says it is mock; the same for both arms."""
    good = ["run:status"]
    refs = ["run:not-a-real-evidence-id"] if scenario == "rejected" else good
    findings = [
        {"statement": f"{MOCK_MARK} 화면 검증용 고정 문장입니다. 이 실행의 상태 기록을 가리킵니다.", "evidenceRefs": refs},
    ]
    if scenario == "detector":
        findings.append(
            {
                "statement": f"{MOCK_MARK} 검출기 표시 확인용 문장: 개별 FastQC 결과는 그대로 있습니다.",
                "evidenceRefs": good,
            }
        )
    return {
        "summary": f"{MOCK_MARK} 비교 화면과 저장 경로를 검증하기 위한 모의 답변입니다.",
        "importantFindings": findings,
        "limitations": [{"statement": f"{MOCK_MARK} 모델이 만든 문장이 아닙니다.", "evidenceRefs": good}],
        "nextChecks": [{"statement": f"{MOCK_MARK} 실제 비교는 승인 후 실제 호출로 합니다.", "evidenceRefs": good}],
        "uncertainties": [{"statement": f"{MOCK_MARK} 이 답변으로 품질을 판단할 수 없습니다.", "evidenceRefs": good}],
    }


def _install_mock(provider, scenario: str) -> None:
    def run_structured(**_kwargs: Any):
        if scenario == "timeout":
            # The arm's own synthesis code turns this into its provider-error
            # result, so the stored record has exactly the shape a real
            # timeout would have -- the outcome classification is exercised
            # on the real record, not on a hand-made one.
            raise provider.ProviderError("timeout", "mock provider timeout (no model)")
        return provider.ProviderResult(
            payload=_mock_answer(scenario), models=[MOCK_MODEL], durationMs=0, numTurns=1
        )

    provider.run_structured = run_structured  # type: ignore[assignment]
    provider._preflight = _refuse  # type: ignore[attr-defined]


def _case(run_eval, request: dict[str, Any]):
    """(materialised context manager, privacy callable, leak counter) for the case."""
    from evals import agent_cases, archive_runs

    name = request["case"]
    if request["kind"] == "archive":
        run = archive_runs.ARCHIVE_RUNS[name]
        loaded = archive_runs.load(run)

        def materialised():
            return archive_runs.materialise(run, loaded=loaded)

        def privacy(_fixture, payload):
            return run_eval.archive_privacy_check(run, payload, loaded=loaded)

        def leaks(value: Any) -> int:
            # The harness's own record check: top-level ...Hash / ...Digest
            # fields are digests by design; everything else is scanned.
            return run_eval.archive_record_leaks(run, value, loaded=loaded)

        return materialised, privacy, leaks
    if request["kind"] == "agent":
        case = agent_cases.CASES[name]

        def materialised():
            return agent_cases.materialise(case)

        def privacy(fixture, _payload):
            return run_eval.privacy_check(fixture)

        def leaks(value: Any) -> int:
            return json.dumps(value, ensure_ascii=False).count(run_eval.CANARY)

        return materialised, privacy, leaks
    raise SystemExit(f"worker: unknown case kind {request['kind']!r}")


def _run_source_digest() -> str:
    """Everything the step tool can read about the restored run, as one digest.

    Called inside the materialised block, where the isolated DB and runs root
    hold exactly the restored copy the tool server will open: the job rows it
    scopes itself with (plan, mode, the identifiers its redactor hides) and
    every file under each job's run directory, by relative path and content.
    The payload digest alone covers only what the model is handed up front;
    the tool reads step documents, metrics and checks the payload never
    carried (review H4, 2026-11-22).
    """
    from app import db

    digest = hashlib.sha256()
    for row in db.query_all("SELECT * FROM jobs ORDER BY job_id"):
        fields = dict(row)
        scope = {k: fields.get(k) for k in ("job_id", "run_id", "sample_id", "run_mode", "planned_steps", "status")}
        digest.update(json.dumps(scope, sort_keys=True, default=str).encode("utf-8"))
        run_dir = Path(str(fields.get("run_dir") or ""))
        if not run_dir.is_dir():
            digest.update(b"\0no-run-dir\0")
            continue
        for path in sorted(p for p in run_dir.rglob("*") if p.is_file()):
            digest.update(path.relative_to(run_dir).as_posix().encode("utf-8") + b"\0")
            digest.update(hashlib.sha256(path.read_bytes()).hexdigest().encode("ascii") + b"\n")
    return digest.hexdigest()


def _inputs_now(explanation: Any) -> dict[str, str]:
    """The two digests the approval locked, computed from the run restored now."""
    from app.services.explanation.llm import contract

    payload, _allowed = contract.build_payload(explanation)
    return {"payloadDigest": canonical_sha256(payload), "sourceDigest": _run_source_digest()}


def build_payload(request: dict[str, Any]) -> dict[str, Any]:
    from app.services.explanation.llm import contract, prompt
    from evals import run_eval

    run_eval.apply_variant_settings(request["conditions"]["variant"])
    materialised, privacy, leaks = _case(run_eval, request)
    with materialised() as explanation:
        payload, allowed = contract.build_payload(explanation)
        fixture = explanation.model_dump()
        source_digest = _run_source_digest()
    offer = run_eval.VARIANTS[request["conditions"]["variant"]]
    user_prompt = prompt.build_user_prompt(payload, offer_tools=offer)
    check = privacy(fixture, payload)
    return {
        "payload": payload,
        "payloadDigest": canonical_sha256(payload),
        "sourceDigest": source_digest,
        "userPromptDigest": hashlib.sha256(user_prompt.encode("utf-8")).hexdigest(),
        "constraintsDigest": hashlib.sha256(
            prompt.constraints_for(offer_tools=offer).encode("utf-8")
        ).hexdigest(),
        "promptHash": run_eval._prompt_hash(request["conditions"]["variant"]),
        "knowledgeHash": run_eval._knowledge_hash(),
        "allowedRefCount": len(allowed),
        "allowedRefs": sorted(allowed),
        "privacy": check.outcome,
        "leakCount": leaks({"payload": payload}),
    }


def call_model(request: dict[str, Any], started_marker: Path) -> dict[str, Any]:
    from evals import run_eval

    variant = request["conditions"]["variant"]
    locked = request.get("locked") or {}
    if not (isinstance(locked.get("payloadDigest"), str) and isinstance(locked.get("sourceDigest"), str)):
        raise SystemExit("worker: a model action needs the approved payload and run-source digests")
    run_eval.apply_variant_settings(variant)
    materialised, privacy, leaks = _case(run_eval, request)

    @contextmanager
    def checked_then_marked():
        # The harness enters this right before it builds the payload and calls
        # the provider. The run is restored, compared with what was approved,
        # and only then is the marker written -- so the comparison is of the
        # very copy the call (and its step tool) will read.
        with materialised() as explanation:
            now = _inputs_now(explanation)
            changed = sorted(k for k in ("payloadDigest", "sourceDigest") if now.get(k) != locked[k])
            if changed:
                raise InputsChanged(f"worker: {', '.join(changed)} differ from the approved inputs; no model call")
            # Durable BEFORE the call: its absence proves the model was never reached.
            _write_durable(started_marker, {"at": time.time(), "pid": os.getpid()})
            yield explanation

    started = time.perf_counter()
    record, payload = run_eval._evaluate_run(
        request["case"], checked_then_marked(), variant=variant, privacy=privacy
    )
    wall_ms = round((time.perf_counter() - started) * 1000)
    record = dict(record)
    record["wallMs"] = wall_ms
    record["payload"] = payload
    record["payloadDigest"] = canonical_sha256(payload)
    record["leakCount"] = leaks(record)
    return record


def _write_durable(path: Path, value: Any) -> None:
    with path.open("x", encoding="utf-8") as handle:
        handle.write(json.dumps(value, ensure_ascii=False) + "\n")
        handle.flush()
        os.fsync(handle.fileno())


def _publish(out: Path, value: Any) -> None:
    """Make `out` appear complete or not at all; never replace an existing one."""
    tmp = out.with_name(f"{out.name}.tmp-{os.getpid()}")
    with tmp.open("x", encoding="utf-8") as handle:
        handle.write(json.dumps(value, ensure_ascii=False, indent=2) + "\n")
        handle.flush()
        os.fsync(handle.fileno())
    try:
        os.link(tmp, out)  # fails if `out` exists, on Windows and POSIX alike
    finally:
        tmp.unlink(missing_ok=True)


@contextmanager
def _attempt_lock(path: Path):
    """The attempt's OS lock (same scheme as contract.os_lock; this file is
    standalone because it runs inside a frozen tree that does not contain
    evals/ab_compare)."""
    handle = open(path, "a+b")  # noqa: SIM115
    try:
        try:
            if os.name == "nt":
                import msvcrt

                handle.seek(0)
                msvcrt.locking(handle.fileno(), msvcrt.LK_NBLCK, 1)
            else:
                import fcntl

                fcntl.flock(handle.fileno(), fcntl.LOCK_EX | fcntl.LOCK_NB)
        except OSError:
            raise SystemExit("worker: this attempt is already held by another process") from None
        try:
            yield
        finally:
            if os.name == "nt":
                import msvcrt

                handle.seek(0)
                msvcrt.locking(handle.fileno(), msvcrt.LK_UNLCK, 1)
            else:
                import fcntl

                fcntl.flock(handle.fileno(), fcntl.LOCK_UN)
    finally:
        handle.close()


def _tree_imports(tree: Path) -> list[str]:
    """Repository-relative paths of the modules imported from the arm's tree."""
    snapshot = tree.resolve().parent  # <snapshot>/backend -> <snapshot>
    found = set()
    for module in list(sys.modules.values()):
        name = getattr(module, "__file__", None)
        if not name:
            continue
        try:
            found.add(Path(name).resolve().relative_to(snapshot).as_posix())
        except ValueError:
            continue
    return sorted(found)


def main(argv: list[str] | None = None) -> int:
    parser = argparse.ArgumentParser()
    parser.add_argument("--tree", required=True, type=Path)
    parser.add_argument("--request", required=True, type=Path)
    parser.add_argument("--out", required=True, type=Path)
    args = parser.parse_args(argv)

    request = json.loads(args.request.read_text(encoding="utf-8"))
    action = request["action"]
    if action not in ("payload", "mock", "real"):
        raise SystemExit(f"worker: unknown action {action!r}")
    if action == "real" and not (
        request.get("allowRealClaude") is True
        and os.environ.get("WES_AB_ALLOW_REAL_CLAUDE") == "1"
    ):
        raise SystemExit("worker: real Claude call refused (two explicit opt-ins required)")
    if args.out.exists():
        raise SystemExit("worker: a result for this request already exists; refusing before any work")
    if action == "payload":
        _run(action, request, args)
        return 0

    attempt = request.get("attempt") or {}
    if not all(isinstance(attempt.get(k), str) for k in ("claim", "lock", "started", "void")):
        raise SystemExit("worker: a model action needs the attempt's claim, lock, seal and marker paths")
    with _attempt_lock(Path(attempt["lock"])):
        if not Path(attempt["claim"]).is_file():
            raise SystemExit("worker: no durable claim for this attempt; refusing before any model call")
        if Path(attempt["void"]).exists():
            raise SystemExit("worker: this attempt was sealed as not invoked; refusing before any model call")
        if Path(attempt["started"]).exists() or args.out.exists():
            raise SystemExit("worker: this attempt already reached the model once; refusing to call again")
        _run(action, request, args, started_marker=Path(attempt["started"]))
    return 0


def _run(action: str, request: dict[str, Any], args: argparse.Namespace, started_marker: Path | None = None) -> None:
    scratch = Path(tempfile.mkdtemp(prefix="wes-ab-worker-"))
    try:
        _prepare_environment(request, scratch)
        provider = _import_tree(args.tree)
        if action == "payload":
            provider.run_structured = _refuse  # type: ignore[assignment]
            provider._preflight = _refuse  # type: ignore[attr-defined]
            _guard_processes()
            result = build_payload(request)
        else:
            assert started_marker is not None
            if action == "mock":
                _install_mock(provider, request.get("mockScenario") or "plain")
                _guard_processes()
            result = call_model(request, started_marker)
        result["workerAction"] = action
        result["mock"] = action == "mock"
        result["importedTreeFiles"] = _tree_imports(args.tree)
        _publish(args.out, result)
    finally:
        shutil.rmtree(scratch, ignore_errors=True)


if __name__ == "__main__":
    raise SystemExit(main())
