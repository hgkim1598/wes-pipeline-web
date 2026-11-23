"""Does a code change alter what the A/B call path derives? Checked, not argued.

    cd backend
    python -m evals.ab_compare.equivalence --base <commit> [--head <commit>]

Builds the protocol's snapshot paths at `--base` (git) and at `--head` (a commit,
or the working tree when omitted) in a temporary directory, then, in a separate
interpreter per tree, materialises every synthetic agent case
(evals/agent_cases.py) and digests what the call path derives from it:

    payload        contract.build_payload -- the model's initial input
    allowed        the evidence ids the gates accept
    explanation    the deterministic explanation the payload is built from
    context        run_context, the run facts behind it
    tools          get_step_detail's result for every planned step

Identical digests for a case mean the change cannot alter that case's model
input or tool results. That is the evidence a classification needs when a file
is executed during the call but should not change it (protocols/README.md).
A difference is printed per case and field.

Limits, on purpose:
* Synthetic cases only. The preserved real runs need local, private archives;
  their equivalence is the `payloads` step of a real experiment (no model).
* No model, no process: the provider entry points raise, and the test suite's
  real-CLI guard runs in "deny" mode inside each probe.
* It compares derived values, not answers. Equal inputs are what it proves.
"""

from __future__ import annotations

import argparse
import hashlib
import json
import os
import shutil
import subprocess
import sys
import tempfile
from pathlib import Path
from typing import Any

FIELDS = ("outcomeStatus", "payload", "allowed", "explanation", "context", "tools")


def digest(value: Any) -> str:
    text = json.dumps(value, ensure_ascii=False, sort_keys=True, separators=(",", ":"), default=str)
    return hashlib.sha256(text.encode("utf-8")).hexdigest()


def compare(base: dict[str, Any], head: dict[str, Any]) -> dict[str, list[str]]:
    """case -> the fields that differ ([] when identical). A case on one side only differs in 'case'."""
    out: dict[str, list[str]] = {}
    for case in sorted(set(base) | set(head)):
        if case not in base or case not in head:
            out[case] = ["case"]
            continue
        out[case] = [f for f in FIELDS if base[case].get(f) != head[case].get(f)]
    return out


# --- inside one tree (a separate interpreter) ----------------------------------------


def probe(tree: Path) -> dict[str, Any]:
    scratch = Path(tempfile.mkdtemp(prefix="wes-equivalence-"))
    try:
        for key in list(os.environ):
            if key.startswith("WES_"):
                del os.environ[key]
        os.environ.update(
            WES_DB_PATH=str(scratch / "app.db"),
            WES_RUNS_ROOT=str(scratch / "runs"),
            WES_UPLOAD_ROOT=str(scratch / "uploads"),
            WES_SYNTHESIS_MODEL="sonnet",
            WES_DOC_RAG="0",
            WES_AGENT_DOC_EVIDENCE="0",
            WES_SYNTHESIS_REPAIR="off",
        )
        backend = tree / "backend"
        sys.path.insert(0, str(backend))
        from app.tests import real_cli_guard

        real_cli_guard.install("deny")

        import app

        if backend.resolve() not in Path(app.__file__).resolve().parents:
            raise SystemExit("equivalence: app was not imported from the requested tree")
        from app.services.explanation.llm import provider

        def refuse(*_a: Any, **_k: Any) -> Any:
            raise RuntimeError("model call attempted during an equivalence probe")

        provider.run_structured = refuse
        provider._preflight = refuse

        from app.services.agent import run_scope, step_evidence
        from app.services.explanation import run_context
        from app.services.explanation.llm import contract
        from evals import agent_cases, run_eval

        # The agent variant the protocol's arms run (v3 = agent loop on).
        run_eval.apply_variant_settings("v3")

        result: dict[str, Any] = {}
        for name, case in sorted(agent_cases.CASES.items()):
            with agent_cases.materialise(case) as explanation:
                payload, allowed = contract.build_payload(explanation)
                context = run_context.build_run_diagnostic_context(agent_cases.RUN_ID)
                scope = run_scope.for_job(agent_cases.RUN_ID)
                tools: dict[str, str] = {}
                for step_id in scope.planned_steps:
                    try:
                        tools[step_id] = digest(step_evidence.read_step_evidence(scope, step_id).model_dump())
                    except Exception as exc:  # noqa: BLE001 -- the outcome is what is compared
                        tools[step_id] = f"error:{type(exc).__name__}"
                result[name] = {
                    "outcomeStatus": context.outcome.status,
                    "payload": digest(payload),
                    "allowed": digest(sorted(allowed)),
                    "explanation": digest(explanation.model_dump()),
                    "context": digest(context.model_dump()),
                    "tools": tools,
                }
        return result
    finally:
        shutil.rmtree(scratch, ignore_errors=True)


# --- driver -------------------------------------------------------------------------------


def _build_tree(source: dict[str, str], paths: list[str], dest: Path) -> None:
    from . import runner

    if source["kind"] == "git":
        runner.snapshot_git(source["commit"], paths, dest)
    else:
        runner.snapshot_working_tree(paths, dest)


def _run_probe(tree: Path, out: Path) -> dict[str, Any]:
    # -I: the tree's own directory is not put on sys.path by the interpreter;
    # probe() inserts exactly tree/backend.
    subprocess.run(
        [sys.executable, "-I", str(Path(__file__).resolve()), "--probe", str(tree), str(out)],
        check=True,
    )
    return json.loads(out.read_text(encoding="utf-8"))


def main(argv: list[str] | None = None) -> int:
    parser = argparse.ArgumentParser(description=__doc__.splitlines()[0])
    parser.add_argument("--base", help="git commit of the 'before' tree")
    parser.add_argument("--head", help="git commit of the 'after' tree (default: the working tree)")
    parser.add_argument("--probe", nargs=2, metavar=("TREE", "OUT"), help=argparse.SUPPRESS)
    args = parser.parse_args(argv)

    if args.probe:
        tree, out = (Path(p).resolve() for p in args.probe)
        out.write_text(json.dumps(probe(tree), indent=1, sort_keys=True), encoding="utf-8")
        return 0
    if not args.base:
        parser.error("--base is required")

    from . import runner

    protocol = json.loads(runner.DEFAULT_PROTOCOL.read_text(encoding="utf-8"))
    paths = list(protocol["snapshotPaths"])
    work = Path(tempfile.mkdtemp(prefix="wes-equivalence-trees-"))
    try:
        results = {}
        for label, source in (
            ("base", {"kind": "git", "commit": args.base}),
            ("head", {"kind": "git", "commit": args.head} if args.head else {"kind": "workingTree"}),
        ):
            _build_tree(source, paths, work / label)
            results[label] = _run_probe(work / label, work / f"{label}.json")
        differences = compare(results["base"], results["head"])
    finally:
        shutil.rmtree(work, ignore_errors=True)

    for case, fields in differences.items():
        print(f"{case}: {'IDENTICAL' if not fields else 'DIFFERS in ' + ', '.join(fields)}")
    return 0 if not any(differences.values()) else 1


if __name__ == "__main__":
    raise SystemExit(main())
