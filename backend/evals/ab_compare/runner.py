"""Same run, two code paths, fresh Claude answers from each -- the A/B runner.

    cd backend
    python -m evals.ab_compare prepare  --experiment ledger-ab-2026-11-22
    python -m evals.ab_compare payloads --experiment ledger-ab-2026-11-22
    python -m evals.ab_compare approve  --experiment ledger-ab-2026-11-22 \\
        --calls 001-real-b94559-a-r1,002-real-b94559-b-r1 --max-cli-calls 2
    python -m evals.ab_compare run      --experiment ledger-ab-2026-11-22 \\
        --approval ap-... --allow-real-claude
    python -m evals.ab_compare status   --experiment ledger-ab-2026-11-22

    # UI check without any model: an experiment whose id starts with "mock-"
    python -m evals.ab_compare prepare  --experiment mock-ui-check --mock
    python -m evals.ab_compare payloads --experiment mock-ui-check
    python -m evals.ab_compare run      --experiment mock-ui-check --mock

How the two arms are kept apart
-------------------------------

    A  `git archive <commit>` of the protocol's paths, verified blob by blob
       against `git ls-tree`. The code exactly as it was before the change.
    B  the working tree's tracked + untracked-not-ignored files under the same
       paths, copied at prepare time. Later edits to the repository do not
       reach an experiment already prepared.

Both arms run through the SAME frozen worker (worker.py, copied into the
experiment) in separate child processes; each child imports only its own tree.
There is no switch in product code that turns the change off: arm A is the
old code, not the new code told to behave like it.

Every file that differs between the arms must be classified by the protocol
(`diffClassification`: intended / inertInCallPath / notInCallPath). An
unexplained difference stops `prepare` and `run`.

States, approval and integrity
------------------------------

The call states, outcomes and the approval budget are defined once in
contract.py and read by this runner and by the API alike. In short:

* `approve` records exact call ids and a maximum number of CLI calls, after
  the user retypes that number. `run` executes only those ids and never more
  CLI calls than that, across any number of interrupted runs.
* Before each call the runner claims the attempt in a create-only file; the
  worker refuses to reach the model without that claim and writes a
  model-started marker first. An attempt that ended without a marker is
  SEALED as not invoked under its own lock before anything else may start
  (the worker refuses a sealed attempt), so a worker that was still starting
  when its runner died can never add a call (review B1). Until it is sealed,
  an attempt counts against the approval. A marker without a result is
  "uncertain": never retried without --retry and remaining approval. A raw
  result without a record is finished without a new call.
* One runner per experiment (an OS lock, released if the runner dies).
* Before each call: protocol, worker, local config, both snapshots file by
  file, the arm difference and its classification, and a fresh no-model
  build of this call's payload compared with the locked one -- the payload
  digest and the digest of the restored run the step tool reads (review
  H4). The worker repeats that comparison on the copy it is about to use,
  right before its marker. After each call: the payload, prompt and
  knowledge hashes the call actually used, and that no file classified as
  outside the call path was imported.
* Records are published atomically (review M1): a crash while one is written
  leaves nothing a reader mistakes for a record, and the raw result is still
  recovered.

Storage
-------

Everything goes under one experiment directory in the eval store (default
backend/evals/ab_store/, git-ignored). Files are created with mode "x": a
rerun never overwrites a stored call, payload, approval or grade.
"""

from __future__ import annotations

import argparse
import hashlib
import io
import json
import os
import random
import re
import secrets
import shutil
import subprocess
import sys
import tarfile
from contextlib import ExitStack, contextmanager
from datetime import datetime, timezone
from pathlib import Path, PurePosixPath
from typing import Any, Callable, Iterator, Sequence

from app import config

from . import contract, scoring

HERE = Path(__file__).resolve().parent
WORKER = HERE / "worker.py"
PROTOCOLS = HERE / "protocols"
DEFAULT_PROTOCOL = PROTOCOLS / "ledger_applicability_v3.json"
EXPERIMENT_ID = re.compile(r"^[a-z0-9][a-z0-9-]{2,63}$")
ARMS = ("A", "B")
# Not part of either arm's call path: the store itself, this package (the
# frozen worker is copied separately) and earlier experiments' records.
STORE_EXCLUDE = ("backend/evals/ab_store/", "backend/evals/ab_compare/", "backend/evals/experiments/")
DIFF_CLASSES = ("intended", "inertInCallPath", "notInCallPath")


class AbError(RuntimeError):
    pass


def store_root() -> Path:
    return Path(config.EVAL_AB_STORE)


def experiment_dir(experiment: str) -> Path:
    if not EXPERIMENT_ID.match(experiment):
        raise AbError("experiment id: lower-case letters, digits and '-' only (3-64)")
    return store_root() / experiment


def now() -> str:
    return datetime.now(timezone.utc).isoformat(timespec="seconds")


def sha256_bytes(data: bytes) -> str:
    return hashlib.sha256(data).hexdigest()


def sha256_file(path: Path) -> str:
    return sha256_bytes(path.read_bytes())


def write_new(path: Path, value: Any) -> None:
    """Create `path`; never replace an existing file."""
    path.parent.mkdir(parents=True, exist_ok=True)
    with path.open("x", encoding="utf-8", newline="\n") as handle:
        handle.write(json.dumps(value, ensure_ascii=False, indent=2) + "\n")
        handle.flush()
        os.fsync(handle.fileno())


def read_json(path: Path) -> Any:
    return json.loads(path.read_text(encoding="utf-8"))


def _manifest_sha(manifest: dict[str, Any]) -> str:
    return sha256_bytes(json.dumps(manifest, sort_keys=True).encode())


def _git(*args: str, binary: bool = False) -> Any:
    done = subprocess.run(
        ["git", *args], cwd=config.ROOT, capture_output=True, check=True, timeout=120
    )
    return done.stdout if binary else done.stdout.decode("utf-8")


def _git_blob_sha(data: bytes) -> str:
    return hashlib.sha1(b"blob %d\0" % len(data) + data).hexdigest()


def _normalised_sha(data: bytes) -> str:
    """Content hash that ignores CRLF vs LF, so a checkout's line endings are
    not reported as a code difference between the arms."""
    return sha256_bytes(data.replace(b"\r\n", b"\n"))


def _safe_relative(name: str) -> PurePosixPath:
    path = PurePosixPath(name)
    if path.is_absolute() or ".." in path.parts or not path.parts:
        raise AbError(f"unsafe path in snapshot: {name!r}")
    return path


def _excluded(rel: str) -> bool:
    return any(rel.startswith(prefix) for prefix in STORE_EXCLUDE) or "/__pycache__/" in f"/{rel}"


# --- snapshots ---------------------------------------------------------------


def snapshot_git(commit: str, paths: list[str], dest: Path) -> dict[str, dict[str, str]]:
    """Extract `paths` at `commit` into `dest`; verify every blob."""
    expected: dict[str, str] = {}
    for line in _git("ls-tree", "-r", commit, "--", *paths).splitlines():
        meta, name = line.split("\t", 1)
        mode, kind, sha = meta.split()
        if kind == "blob" and mode != "120000" and not _excluded(name):
            expected[name] = sha
    data = _git("archive", "--format=tar", commit, "--", *paths, binary=True)
    manifest: dict[str, dict[str, str]] = {}
    with tarfile.open(fileobj=io.BytesIO(data)) as tar:
        for member in tar.getmembers():
            if not member.isfile() or member.name not in expected:
                continue
            rel = _safe_relative(member.name)
            handle = tar.extractfile(member)
            assert handle is not None
            content = handle.read()
            target = dest.joinpath(*rel.parts)
            target.parent.mkdir(parents=True, exist_ok=True)
            target.write_bytes(content)
            manifest[member.name] = {
                "sha256": sha256_bytes(content),
                "normalisedSha256": _normalised_sha(content),
                "gitBlob": _git_blob_sha(content),
            }
    missing = sorted(set(expected) - set(manifest))
    # git archive may convert line endings; the blob check is on the
    # normalised content then. A file whose content differs in any other way
    # stops the snapshot.
    mismatched = []
    for name, sha in expected.items():
        if name in manifest and manifest[name]["gitBlob"] != sha:
            raw = _git("cat-file", "blob", sha, binary=True)
            if _normalised_sha(raw) != manifest[name]["normalisedSha256"]:
                mismatched.append(name)
    if missing or mismatched:
        raise AbError(f"snapshot verification failed: missing {len(missing)}, mismatched {len(mismatched)}")
    return manifest


def snapshot_working_tree(paths: list[str], dest: Path) -> dict[str, dict[str, str]]:
    """Copy tracked + untracked-not-ignored files under `paths` into `dest`."""
    listed = _git("ls-files", "-z", "-co", "--exclude-standard", "--", *paths)
    manifest: dict[str, dict[str, str]] = {}
    for name in sorted(set(filter(None, listed.split("\0")))):
        if _excluded(name):
            continue
        source = config.ROOT / name
        if not source.is_file() or source.is_symlink():
            continue  # deleted in the working tree
        rel = _safe_relative(name)
        content = source.read_bytes()
        target = dest.joinpath(*rel.parts)
        target.parent.mkdir(parents=True, exist_ok=True)
        target.write_bytes(content)
        manifest[name] = {"sha256": sha256_bytes(content), "normalisedSha256": _normalised_sha(content)}
    return manifest


def dry_diff(protocol: dict[str, Any]) -> dict[str, Any]:
    """The arm difference `prepare` would find now, computed in memory (no files written)."""
    paths = list(protocol["snapshotPaths"])
    commit = protocol["arms"]["A"]["source"]["commit"]
    a: dict[str, dict[str, str]] = {}
    with tarfile.open(fileobj=io.BytesIO(_git("archive", "--format=tar", commit, "--", *paths, binary=True))) as tar:
        for member in tar.getmembers():
            if member.isfile() and not member.issym() and not _excluded(member.name):
                handle = tar.extractfile(member)
                assert handle is not None
                content = handle.read()
                a[member.name] = {"sha256": sha256_bytes(content), "normalisedSha256": _normalised_sha(content)}
    b: dict[str, dict[str, str]] = {}
    for name in sorted(set(filter(None, _git("ls-files", "-z", "-co", "--exclude-standard", "--", *paths).split("\0")))):
        source = config.ROOT / name
        if _excluded(name) or not source.is_file() or source.is_symlink():
            continue
        content = source.read_bytes()
        b[name] = {"sha256": sha256_bytes(content), "normalisedSha256": _normalised_sha(content)}
    return arm_diff(a, b)


# Local, git-ignored inputs the harness reads (answer keys of the real runs).
# Neither git nor `--exclude-standard` carries them, so the SAME bytes are copied
# into both arms and their hashes recorded. They are scoring inputs only; the
# agent path never reads them (run_eval.preflight_archive checks that).
SHARED_LOCAL_GLOBS = ("backend/evals/expectations/real_*.json",)


def copy_shared_local(dests: list[Path]) -> dict[str, str]:
    copied: dict[str, str] = {}
    for pattern in SHARED_LOCAL_GLOBS:
        for source in sorted(config.ROOT.glob(pattern)):
            rel = source.relative_to(config.ROOT).as_posix()
            content = source.read_bytes()
            for dest in dests:
                target = dest / rel
                target.parent.mkdir(parents=True, exist_ok=True)
                target.write_bytes(content)
            copied[rel] = sha256_bytes(content)
    return copied


_HARNESS = (
    "backend/evals/run_eval.py",
    "backend/evals/evaluators.py",
    "backend/evals/archive_runs.py",
    "backend/evals/agent_cases.py",
    "backend/evals/explanation_quality.py",
)
_GATE = (
    "backend/app/services/explanation/llm/synthesis.py",
    "backend/app/services/explanation/llm/validation.py",
    "backend/app/services/explanation/llm/claims.py",
    "backend/app/services/explanation/llm/prompt.py",
    "backend/app/services/explanation/llm/provider.py",
    "backend/app/services/explanation/llm/tools.py",
)


def arm_diff(a: dict[str, dict[str, str]], b: dict[str, dict[str, str]]) -> dict[str, Any]:
    changed = sorted(n for n in set(a) & set(b) if a[n]["normalisedSha256"] != b[n]["normalisedSha256"])
    added = sorted(set(b) - set(a))
    removed = sorted(set(a) - set(b))
    differing = set(changed) | set(added) | set(removed)
    return {
        "changed": changed,
        "added": added,
        "removed": removed,
        # Informational: named files only. The binding check is the protocol's
        # classification of EVERY differing file (classify_diff).
        "harnessIdentical": not differing & set(_HARNESS),
        "gateAndPromptCodeIdentical": not differing & set(_GATE),
        "frontendIncluded": False,
        "productAppChanged": any(n.startswith("backend/app/") for n in differing),
    }


def classify_diff(diff: dict[str, Any], protocol: dict[str, Any]) -> dict[str, Any]:
    """Every differing file -> its protocol class and reason; the rest unclassified."""
    rules = protocol.get("diffClassification") or []
    by_path: dict[str, dict[str, str]] = {}
    unclassified: list[str] = []
    for name in sorted(set(diff["changed"]) | set(diff["added"]) | set(diff["removed"])):
        rule = next(
            (
                r
                for r in rules
                if r.get("class") in DIFF_CLASSES
                and ((r.get("match") == "exact" and r.get("path") == name) or (r.get("match") == "prefix" and name.startswith(r.get("path", "\0"))))
            ),
            None,
        )
        if rule is None:
            unclassified.append(name)
        else:
            by_path[name] = {"class": rule["class"], "reason": rule.get("reason", "")}
    return {"byPath": by_path, "unclassified": unclassified}


# --- plan --------------------------------------------------------------------


def build_plan(protocol: dict[str, Any], rng: random.Random) -> list[dict[str, Any]]:
    calls: list[dict[str, Any]] = []
    for repeat in range(1, int(protocol["repeats"]) + 1):
        arms = ARMS if repeat % 2 == 1 or protocol.get("order") != "interleaved" else tuple(reversed(ARMS))
        for case in protocol["cases"]:
            for arm in arms:
                calls.append({"case": case["case"], "arm": arm, "repeat": repeat})
    codes = [f"X{n:02d}" for n in range(1, len(calls) + 1)]
    rng.shuffle(codes)
    for seq, (call, code) in enumerate(zip(calls, codes), start=1):
        call["seq"] = seq
        call["callId"] = f"{seq:03d}-{call['case'].replace('_', '-')}-{call['arm'].lower()}-r{call['repeat']}"
        call["blindCode"] = code
    return calls


def _local_config(target: Path) -> str:
    """The local eval registry with absolute paths, for a tree that lives elsewhere."""
    raw = os.environ.get("WES_EVAL_LOCAL_CONFIG", "").strip()
    source = Path(raw) if raw else config.ROOT / "config/local/wes_eval_runs.json"
    if not source.is_absolute():
        source = config.ROOT / source
    doc = read_json(source) if source.is_file() else {"schemaVersion": 1, "runs": {}}
    if isinstance(doc.get("archive"), str) and not Path(doc["archive"]).is_absolute():
        doc["archive"] = str((config.ROOT / doc["archive"]).resolve())
    for row in (doc.get("runs") or {}).values():
        if isinstance(row.get("captureDir"), str) and not Path(row["captureDir"]).is_absolute():
            row["captureDir"] = str((config.ROOT / row["captureDir"]).resolve())
    write_new(target, doc)
    return str(target)


def prepare(experiment: str, protocol_path: Path, *, mock: bool) -> Path:
    if mock != experiment.startswith("mock-"):
        raise AbError("a mock experiment id must start with 'mock-', and only a mock one may")
    root = experiment_dir(experiment)
    if root.exists():
        raise AbError("experiment already exists; choose a new id (stored results are never replaced)")
    protocol_bytes = protocol_path.read_bytes()
    protocol = json.loads(protocol_bytes.decode("utf-8"))
    if not protocol.get("diffClassification"):
        raise AbError("the protocol has no diffClassification; every arm difference must be explained")
    root.mkdir(parents=True)
    try:
        paths = list(protocol["snapshotPaths"])
        commit = protocol["arms"]["A"]["source"]["commit"]
        manifests = {
            "A": snapshot_git(commit, paths, root / "snapshots" / "A"),
            "B": snapshot_working_tree(paths, root / "snapshots" / "B"),
        }
        diff = arm_diff(manifests["A"], manifests["B"])
        classified = classify_diff(diff, protocol)
        if classified["unclassified"]:
            raise AbError(
                "files differ between the arms without a protocol classification: "
                + ", ".join(classified["unclassified"][:10])
            )
    except BaseException:
        # Nothing has been recorded yet; leave no half-built experiment behind.
        shutil.rmtree(root, ignore_errors=True)
        raise
    shared = copy_shared_local([root / "snapshots" / "A", root / "snapshots" / "B"])
    shutil.copyfile(WORKER, root / "worker.py")
    local = _local_config(root / "local_config.json")
    plan = build_plan(protocol, random.Random(secrets.randbits(64)))
    head = _git("rev-parse", "HEAD").strip()
    experiment_doc = {
        "experimentId": experiment,
        "mock": mock,
        "createdAt": now(),
        "attemptProtocol": contract.ATTEMPT_PROTOCOL,
        "protocolFile": protocol_path.name,
        "protocolSha256": sha256_bytes(protocol_bytes),
        "protocol": protocol,
        "workerSha256": sha256_file(root / "worker.py"),
        "localConfig": local,
        "localConfigSha256": sha256_file(Path(local)),
        "arms": {
            "A": {**protocol["arms"]["A"], "fileCount": len(manifests["A"]), "manifestSha256": _manifest_sha(manifests["A"])},
            "B": {
                **protocol["arms"]["B"],
                "headAtSnapshot": head,
                "fileCount": len(manifests["B"]),
                "manifestSha256": _manifest_sha(manifests["B"]),
            },
        },
        "armDiff": diff,
        "diffClassification": classified,
        "sharedLocalInputs": shared,
        "plan": plan,
    }
    write_new(root / "manifests" / "A.json", manifests["A"])
    write_new(root / "manifests" / "B.json", manifests["B"])
    write_new(root / "experiment.json", experiment_doc)
    return root


# --- loading, locking, integrity ------------------------------------------------


def _load(experiment: str) -> tuple[Path, dict[str, Any]]:
    root = experiment_dir(experiment)
    doc_path = root / "experiment.json"
    if not doc_path.is_file():
        raise AbError("no such experiment; run prepare first")
    return root, read_json(doc_path)


@contextmanager
def experiment_lock(root: Path) -> Iterator[None]:
    """One runner (payloads / approve / run) per experiment at a time."""
    with ExitStack() as stack:
        try:
            stack.enter_context(contract.os_lock(root / "run.lock"))
        except BlockingIOError:
            raise AbError("another runner is working on this experiment; wait for it to finish") from None
        yield


def _snapshot_problems(folder: Path, manifest: dict[str, Any], shared: dict[str, str]) -> list[str]:
    actual: dict[str, Path] = {}
    if folder.is_dir():
        for path in folder.rglob("*"):
            if path.is_file() and "__pycache__" not in path.parts:
                actual[path.relative_to(folder).as_posix()] = path
    expected = {name: entry["sha256"] for name, entry in manifest.items()} | dict(shared)
    problems = []
    missing = sorted(set(expected) - set(actual))
    extra = sorted(set(actual) - set(expected))
    changed = sorted(n for n in set(expected) & set(actual) if sha256_file(actual[n]) != expected[n])
    if missing:
        problems.append(f"{len(missing)} missing ({missing[0]})")
    if extra:
        problems.append(f"{len(extra)} unexpected ({extra[0]})")
    if changed:
        problems.append(f"{len(changed)} changed ({changed[0]})")
    return problems


def verify_integrity(root: Path, doc: dict[str, Any]) -> dict[str, Any]:
    """Everything the calls depend on, checked again now. Returns the fingerprint.

    Raises AbError naming every problem; nothing is spawned or claimed then.
    """
    problems: list[str] = []
    protocol_path = PROTOCOLS / doc.get("protocolFile", "")
    if not protocol_path.is_file() or sha256_file(protocol_path) != doc.get("protocolSha256"):
        problems.append("protocol file changed after it was locked")
    elif read_json(protocol_path) != doc.get("protocol"):
        problems.append("the protocol recorded in experiment.json differs from the locked file")
    if not (root / "worker.py").is_file() or sha256_file(root / "worker.py") != doc.get("workerSha256"):
        problems.append("frozen worker changed")
    local = root / "local_config.json"
    if "localConfigSha256" not in doc:
        problems.append("experiment has no local config hash (first-version experiment; prepare a new one)")
    elif not local.is_file() or sha256_file(local) != doc["localConfigSha256"]:
        problems.append("local run registry copy changed")
    manifests: dict[str, dict[str, Any]] = {}
    shared = doc.get("sharedLocalInputs") or {}
    for arm in ARMS:
        path = root / "manifests" / f"{arm}.json"
        if not path.is_file():
            problems.append(f"manifest {arm} missing")
            continue
        manifest = read_json(path)
        if _manifest_sha(manifest) != (doc.get("arms") or {}).get(arm, {}).get("manifestSha256"):
            problems.append(f"manifest {arm} changed")
            continue
        manifests[arm] = manifest
        problems += [f"snapshot {arm}: {p}" for p in _snapshot_problems(root / "snapshots" / arm, manifest, shared)]
    classification: dict[str, Any] = {"byPath": {}, "unclassified": []}
    if len(manifests) == 2:
        diff = arm_diff(manifests["A"], manifests["B"])
        recorded = doc.get("armDiff") or {}
        if any(diff[k] != recorded.get(k, []) for k in ("changed", "added", "removed")):
            problems.append("arm difference no longer matches the one recorded at prepare")
        classification = classify_diff(diff, doc.get("protocol") or {})
        if classification["unclassified"]:
            problems.append(
                f"{len(classification['unclassified'])} arm difference(s) not classified by the protocol "
                f"({classification['unclassified'][0]})"
            )
    if problems:
        raise AbError("integrity check failed: " + "; ".join(problems))
    payload_digests = {}
    source_digests = {}
    for path in sorted((root / "payloads").glob("*.*.json")) if (root / "payloads").is_dir() else []:
        if path.name != "checks.json":
            built = read_json(path)
            payload_digests[path.stem] = built.get("payloadDigest")
            source_digests[path.stem] = built.get("sourceDigest")
    return {
        "protocolSha256": doc["protocolSha256"],
        "workerSha256": doc["workerSha256"],
        "localConfigSha256": doc["localConfigSha256"],
        "manifestSha256": {arm: doc["arms"][arm]["manifestSha256"] for arm in ARMS},
        "payloadDigests": payload_digests,
        "sourceDigests": source_digests,
        "notInCallPath": sorted(n for n, c in classification["byPath"].items() if c["class"] == "notInCallPath"),
    }


# --- worker ------------------------------------------------------------------


def _worker_timeout(conditions: dict[str, Any]) -> int:
    return int(conditions["timeoutSeconds"]) * 2 + 120


def _spawn_worker(root: Path, arm: str, request: dict[str, Any], out: Path, *, allow_real: bool) -> int:
    """Run the frozen worker against one arm's tree. Returns its exit code.

    Raises subprocess.TimeoutExpired (the child is killed). Replaced in tests.
    """
    request_path = out.with_name(out.name + ".request.json")
    write_new(request_path, request)
    env = dict(os.environ)
    env.pop("WES_AB_ALLOW_REAL_CLAUDE", None)
    if allow_real:
        env["WES_AB_ALLOW_REAL_CLAUDE"] = "1"
    tree = root / "snapshots" / arm / "backend"
    try:
        done = subprocess.run(
            # -I: ignore PYTHON* env and the user site; -B: write no bytecode
            # into the snapshot (it is verified file by file).
            [sys.executable, "-I", "-B", str(root / "worker.py"), "--tree", str(tree), "--request", str(request_path), "--out", str(out)],
            cwd=tree,
            env=env,
            capture_output=True,
            timeout=_worker_timeout(request["conditions"]),
        )
    finally:
        request_path.unlink(missing_ok=True)
    if done.returncode != 0:
        # The last line only: the worker's own SystemExit message. Not stored.
        tail = done.stderr.decode("utf-8", "replace").strip().splitlines()[-1:]
        print(f"  worker exit {done.returncode}: {' | '.join(tail)}", file=sys.stderr)
    return done.returncode


def _case_spec(protocol: dict[str, Any], name: str) -> dict[str, Any]:
    return next(c for c in protocol["cases"] if c["case"] == name)


def _payload_request(doc: dict[str, Any], case: dict[str, Any]) -> dict[str, Any]:
    return {
        "action": "payload",
        "case": case["case"],
        "kind": case["kind"],
        "conditions": doc["protocol"]["conditions"],
        "localConfig": doc["localConfig"],
    }


# sourceDigest: the restored run the step tool reads during the call, which the
# payload digest does not cover (review H4, 2026-11-22).
_PAYLOAD_KEYS = ("payloadDigest", "sourceDigest", "userPromptDigest", "constraintsDigest", "promptHash", "knowledgeHash")


def payloads(experiment: str) -> dict[str, Any]:
    """Build each case's payload in both arms (no model) and compare them."""
    root, doc = _load(experiment)
    with experiment_lock(root):
        verify_integrity(root, doc)
        protocol = doc["protocol"]
        summary: dict[str, Any] = {}
        for case in protocol["cases"]:
            built = {}
            for arm in ARMS:
                out = root / "payloads" / f"{case['case']}.{arm}.json"
                if not out.is_file():
                    out.parent.mkdir(parents=True, exist_ok=True)
                    code = _spawn_worker(root, arm, _payload_request(doc, case), out, allow_real=False)
                    if code != 0 or not out.is_file():
                        raise AbError(f"payload build failed for {case['case']} arm {arm}")
                built[arm] = read_json(out)
            summary[case["case"]] = {
                "payloadEqual": built["A"]["payloadDigest"] == built["B"]["payloadDigest"],
                "constraintsEqual": built["A"]["constraintsDigest"] == built["B"]["constraintsDigest"],
                "promptHashEqual": built["A"]["promptHash"] == built["B"]["promptHash"],
                "privacy": {arm: built[arm]["privacy"] for arm in ARMS},
                "leaks": {arm: built[arm]["leakCount"] for arm in ARMS},
            }
        checks_path = root / "payloads" / "checks.json"
        if not checks_path.is_file():
            write_new(checks_path, {"checkedAt": now(), "cases": summary})
        return summary


def payload_checks_ok(root: Path) -> bool:
    path = root / "payloads" / "checks.json"
    if not path.is_file():
        return False
    cases = read_json(path)["cases"]
    return all(
        c["constraintsEqual"] and c["promptHashEqual"] and set(c["privacy"].values()) == {"pass"}
        and not any(c["leaks"].values())
        for c in cases.values()
    )


def _require_current_attempt_protocol(root: Path, doc: dict[str, Any]) -> None:
    """Approve and run only what the current worker contract can protect.

    An experiment frozen with an older worker has no seal and no at-use
    digest check (reviews B1, H4); its locked payloads carry no run-source
    digest. It stays readable, but no call is approved or made for it.
    """
    if doc.get("attemptProtocol") != contract.ATTEMPT_PROTOCOL:
        raise AbError("this experiment was prepared with an older worker contract; prepare a new experiment")
    for path in sorted((root / "payloads").glob("*.*.json")):
        if path.name != "checks.json" and not isinstance(read_json(path).get("sourceDigest"), str):
            raise AbError(f"locked payload {path.name} has no run-source digest; prepare a new experiment")


def _fresh_payload_matches(root: Path, doc: dict[str, Any], call: dict[str, Any]) -> None:
    """Rebuild this call's payload now (no model) and compare it with the locked one.

    This is what ties the call to the Run source, the knowledge files and the
    harness as they were when the payloads were checked.
    """
    case = _case_spec(doc["protocol"], call["case"])
    locked = read_json(root / "payloads" / f"{call['case']}.{call['arm']}.json")
    out = root / "work" / f"precheck-{call['callId']}-{secrets.token_hex(4)}.json"
    out.parent.mkdir(parents=True, exist_ok=True)
    try:
        code = _spawn_worker(root, call["arm"], _payload_request(doc, case), out, allow_real=False)
        if code != 0 or not out.is_file():
            raise AbError(f"{call['callId']}: the pre-call payload build failed; nothing was claimed")
        fresh = read_json(out)
    finally:
        out.unlink(missing_ok=True)
    differing = [k for k in _PAYLOAD_KEYS if fresh.get(k) != locked.get(k)]
    if fresh.get("privacy") != "pass" or fresh.get("leakCount") != 0:
        differing.append("privacy")
    if differing:
        raise AbError(f"{call['callId']}: the model input differs from the locked payload ({', '.join(differing)}); nothing was claimed")


def _post_call_integrity(root: Path, call: dict[str, Any], record: dict[str, Any], fingerprint: dict[str, Any], *, mock: bool) -> dict[str, Any]:
    locked = read_json(root / "payloads" / f"{call['case']}.{call['arm']}.json")
    imported = set(record.get("importedTreeFiles") or [])
    outside = sorted((imported & set(fingerprint["notInCallPath"])) - contract.WORKER_OWN_IMPORTS)
    checks = {
        "payloadDigest": record.get("payloadDigest") == locked.get("payloadDigest"),
        "promptHash": record.get("promptHash") == locked.get("promptHash"),
        "knowledgeHash": record.get("knowledgeHash") == locked.get("knowledgeHash"),
        "importsListed": bool(imported),
        "noNotInCallPathImport": not outside,
        "mode": record.get("workerAction") == ("mock" if mock else "real") and bool(record.get("mock")) == mock,
    }
    return {"ok": all(checks.values()), "checks": checks, "notInCallPathImported": outside}


# --- approvals ---------------------------------------------------------------------


def _approval_fingerprint(fp: dict[str, Any]) -> dict[str, Any]:
    return {
        k: fp[k]
        for k in ("protocolSha256", "workerSha256", "localConfigSha256", "manifestSha256", "payloadDigests", "sourceDigests")
    }


def approve(
    experiment: str,
    call_ids: Sequence[str],
    max_cli_calls: int,
    *,
    confirm: Callable[[str], str] = input,
) -> str:
    """Record which calls may run and how many CLI calls they may use in total."""
    root, doc = _load(experiment)
    mock = bool(doc["mock"])
    with experiment_lock(root):
        fingerprint = verify_integrity(root, doc)
        if not payload_checks_ok(root):
            raise AbError("run `payloads` first; its checks must pass (same constraints, no leaks)")
        _require_current_attempt_protocol(root, doc)
        plan = {c["callId"]: c for c in doc["plan"]}
        ids = list(dict.fromkeys(call_ids))
        if not ids or len(ids) != len(call_ids):
            raise AbError("name each call id once")
        unknown = [i for i in ids if i not in plan]
        if unknown:
            raise AbError(f"not in this experiment's plan: {', '.join(unknown)}")
        if not isinstance(max_cli_calls, int) or max_cli_calls < 1:
            raise AbError("--max-cli-calls must be at least 1")
        records = contract.call_records(root)
        for call_id in ids:
            state = contract.call_state(root, call_id, records=records.get(call_id, {}), lock_probe=contract.is_held, mock=mock)
            if state["state"] == "running":
                raise AbError(f"{call_id} is running in another process")
            if state["state"] == "recorded" and state["outcome"] in contract.ANSWER_OUTCOMES:
                raise AbError(f"{call_id} already has an answer ({state['outcome']}); answered calls are never repeated")
        kind = "모의(mock) — 모델 호출 없음" if mock else "실제 Claude CLI"
        print(f"{kind} 승인 요청: 호출 {len(ids)}개, CLI 호출 최대 {max_cli_calls}회")
        for call_id in ids:
            c = plan[call_id]
            print(f"  {call_id}  ({c['case']} · arm {c['arm']} · 반복 {c['repeat']})")
        if not mock:
            typed = confirm(f"승인하려면 최대 CLI 호출 수({max_cli_calls})를 숫자로 다시 입력: ").strip()
            if typed != str(max_cli_calls):
                raise AbError("not approved (the number did not match)")
        approval_id = f"ap-{datetime.now(timezone.utc).strftime('%Y%m%dT%H%M%SZ')}-{secrets.token_hex(2)}"
        write_new(
            root / "approvals" / f"{approval_id}.json",
            {
                "approvalId": approval_id,
                "experimentId": doc["experimentId"],
                "mode": "mock" if mock else "real",
                "calls": ids,
                "maxCliCalls": max_cli_calls,
                "approvedAt": now(),
                "fingerprint": _approval_fingerprint(fingerprint),
            },
        )
        print(f"승인 기록: {approval_id}")
        return approval_id


# --- run ---------------------------------------------------------------------------

# Mock calls cycle through these by plan order, so a mock run shows every
# outcome: served, a detector hit, a gate rejection and a provider error.
MOCK_SCENARIOS = ("plain", "detector", "rejected", "timeout")
_OUTCOME_TEXT = {
    "served": "Gate 통과",
    "gateRejected": "Gate 거부",
    "providerError": "호출 실패 — Gate 판정 없음",
    "unclassified": "분류 불가",
}


def _finalize(root: Path, doc: dict[str, Any], call: dict[str, Any], n: int, fingerprint: dict[str, Any], claim: dict[str, Any]) -> dict[str, Any]:
    """Turn attempt n's raw worker result into the stored record. No model call."""
    mock = bool(doc["mock"])
    paths = contract.attempt_paths(root, call["callId"], n)
    record = read_json(paths["raw"])
    case = _case_spec(doc["protocol"], call["case"])
    stored = {
        "callId": call["callId"],
        "attempt": n,
        "approvalId": claim.get("approvalId"),
        "experimentId": doc["experimentId"],
        "arm": call["arm"],
        "case": call["case"],
        "repeat": call["repeat"],
        "seq": call["seq"],
        "blindCode": call["blindCode"],
        "mock": mock,
        "startedAt": claim.get("claimedAt"),
        "finishedAt": now(),
        "protocolSha256": doc["protocolSha256"],
        "armManifestSha256": doc["arms"][call["arm"]]["manifestSha256"],
        "integrity": _post_call_integrity(root, call, record, fingerprint, mock=mock),
        "scores": scoring.score_record(record, case, doc["protocol"]),
        "record": record,
    }
    contract.publish_new(paths["record"], stored)
    return stored


def _report(call_id: str, stored: dict[str, Any]) -> None:
    outcome = stored["scores"]["outcome"]
    text = _OUTCOME_TEXT[outcome["outcome"]]
    category = f" ({outcome['category']})" if outcome.get("category") else ""
    integrity = "" if stored["integrity"]["ok"] else " · 사후 무결성 확인 실패 — 평가 제외"
    print(f"  {call_id}: {text}{category}, {stored['scores'].get('durationMs')} ms{integrity}")


def _mock_approval(root: Path, doc: dict[str, Any]) -> str:
    """A mock experiment needs no person to approve: every call not yet answered."""
    records = contract.call_records(root)
    ids = []
    for c in doc["plan"]:
        state = contract.call_state(root, c["callId"], records=records.get(c["callId"], {}), lock_probe=contract.is_held, mock=True)
        if not (state["state"] == "recorded" and state["outcome"] in contract.ANSWER_OUTCOMES):
            ids.append(c["callId"])
    if not ids:
        return ""
    fingerprint = verify_integrity(root, doc)
    approval_id = f"ap-{datetime.now(timezone.utc).strftime('%Y%m%dT%H%M%SZ')}-{secrets.token_hex(2)}"
    write_new(
        root / "approvals" / f"{approval_id}.json",
        {
            "approvalId": approval_id,
            "experimentId": doc["experimentId"],
            "mode": "mock",
            "calls": ids,
            "maxCliCalls": len(ids),
            "approvedAt": now(),
            "fingerprint": _approval_fingerprint(fingerprint),
        },
    )
    return approval_id


def run(
    experiment: str,
    *,
    approval: str | None,
    mock: bool,
    allow_real: bool,
    retry: Sequence[str] = (),
) -> int:
    """Execute the approved calls that still need one. Returns a process exit code.

    0  every approved call is answered or was left as intended
    3  stopped: a call is uncertain / not invoked after a worker failure, the
       approval is used up, or a call needs --retry. Nothing is retried
       without a person.
    """
    root, doc = _load(experiment)
    if mock != bool(doc["mock"]):
        raise AbError("--mock must match how the experiment was prepared")
    if not mock and not allow_real:
        raise AbError("real Claude calls need --allow-real-claude")
    with experiment_lock(root):
        fingerprint = verify_integrity(root, doc)
        if not payload_checks_ok(root):
            raise AbError("run `payloads` first; its checks must pass (same constraints, no leaks)")
        _require_current_attempt_protocol(root, doc)
        if approval is None:
            if not mock:
                raise AbError("real calls need --approval (see `approve`)")
            approval = _mock_approval(root, doc)
            if not approval:
                print("모든 호출에 답변이 있습니다.")
                return 0
        if not contract.APPROVAL_ID.match(approval):
            raise AbError("malformed approval id")
        approval_path = root / "approvals" / f"{approval}.json"
        if not approval_path.is_file():
            raise AbError("no such approval")
        ap = read_json(approval_path)
        if ap.get("mode") != ("mock" if mock else "real"):
            raise AbError("the approval was given for a different mode")
        if ap.get("fingerprint") != _approval_fingerprint(fingerprint):
            raise AbError("the experiment changed after this approval; approve again")
        unknown_retry = [i for i in retry if i not in ap["calls"]]
        if unknown_retry:
            raise AbError(f"--retry names calls outside the approval: {', '.join(unknown_retry)}")

        plan = {c["callId"]: c for c in doc["plan"]}
        exit_code = 0
        kind = "모의(mock) — 모델 호출 없음" if mock else "실제 Claude CLI"
        # Seal every attempt of these calls that provably never reached the model
        # (no marker, lock free -- taken by the seal itself). Unsealed ones keep
        # counting against the approval; a live one stays live.
        for call_id in ap["calls"]:
            for n in contract.claimed_attempts(root, call_id):
                contract.seal_not_invoked(root, call_id, n)
        used = len(contract.approval_usage(root, approval))
        print(f"{kind} · 승인 {approval}: 호출 {len(ap['calls'])}개, CLI 호출 {used}/{ap['maxCliCalls']}회 사용")
        for call_id in ap["calls"]:
            call = plan[call_id]
            state = contract.call_state(root, call_id, lock_probe=contract.is_held, mock=mock)
            name = state["state"]
            if name == "inFlightOrNotInvoked":
                # Not sealed above, so its lock was taken in between: a worker is starting.
                name = "notInvoked" if contract.seal_not_invoked(root, call_id, state["attempt"]) else "running"
            if name == "running":
                raise AbError(f"{call_id} is running in another process; stopping")
            if name == "unreadableRecord":
                print(f"  {call_id}: 기록 파일을 읽을 수 없습니다. 사람이 확인해야 합니다 — 호출하지 않습니다.")
                exit_code = 3
                continue
            if name == "recoverable":
                n = state["attempt"]
                claim = read_json(contract.attempt_paths(root, call_id, n)["claim"])
                print(f"  {call_id}: 저장 전 결과가 있어 모델 호출 없이 기록합니다 (시도 {n})")
                _report(call_id, _finalize(root, doc, call, n, fingerprint, claim))
                continue
            if name == "recorded" and state["outcome"] in contract.ANSWER_OUTCOMES:
                continue  # answered; never repeated
            if name in ("recorded", "uncertain") and call_id not in retry:
                why = "호출 시작 후 결과 없음 — 호출됐는지 알 수 없음" if name == "uncertain" else f"{state['outcome']}"
                print(f"  {call_id}: {why}. 다시 부르려면 --retry {call_id} (승인 범위 안에서만)")
                exit_code = 3
                continue
            # planned / notInvoked / (uncertain|providerError|unclassified with --retry)
            used = len(contract.approval_usage(root, approval))
            if used >= ap["maxCliCalls"]:
                print(f"  {call_id}: 승인된 CLI 호출 수({ap['maxCliCalls']})를 모두 썼습니다. 멈춥니다.")
                return 3
            fingerprint = verify_integrity(root, doc)
            if ap.get("fingerprint") != _approval_fingerprint(fingerprint):
                raise AbError("the experiment changed during the run; stopping")
            _fresh_payload_matches(root, doc, call)
            n = max(contract.claimed_attempts(root, call_id) + [0] + list(contract.call_records(root).get(call_id, {}))) + 1
            paths = contract.attempt_paths(root, call_id, n)
            claim = {
                "callId": call_id,
                "attempt": n,
                "approvalId": approval,
                "mode": "mock" if mock else "real",
                "claimedAt": now(),
                "runnerPid": os.getpid(),
            }
            write_new(paths["claim"], claim)
            locked = read_json(root / "payloads" / f"{call['case']}.{call['arm']}.json")
            request = {
                "action": "mock" if mock else "real",
                "allowRealClaude": not mock,
                "case": call["case"],
                "kind": _case_spec(doc["protocol"], call["case"])["kind"],
                "conditions": doc["protocol"]["conditions"],
                "localConfig": doc["localConfig"],
                "mockScenario": MOCK_SCENARIOS[(call["seq"] - 1) % len(MOCK_SCENARIOS)] if mock else None,
                "attempt": {k: str(paths[k]) for k in ("claim", "lock", "started", "void")},
                # The worker compares the run it restores with these before its marker.
                "locked": {"payloadDigest": locked["payloadDigest"], "sourceDigest": locked["sourceDigest"]},
            }
            timed_out = False
            code: int | None = None
            try:
                code = _spawn_worker(root, call["arm"], request, paths["raw"], allow_real=allow_real and not mock)
            except subprocess.TimeoutExpired:
                timed_out = True
            if paths["raw"].is_file():
                _report(call_id, _finalize(root, doc, call, n, fingerprint, claim))
                continue
            write_new(paths["exit"], {"exitCode": code, "timedOut": timed_out, "at": now()})
            # The worker has exited (or was killed). Seal the attempt if it never
            # wrote its marker; otherwise it stays uncertain.
            contract.seal_not_invoked(root, call_id, n)
            after = contract.call_state(root, call_id, lock_probe=contract.is_held, mock=mock)["state"]
            if after == "notInvoked":
                print(f"  {call_id}: worker가 모델 호출 전에 멈췄습니다 (호출 안 됨). 원인을 확인한 뒤 다시 실행하세요.")
            else:
                print(f"  {call_id}: worker가 결과 없이 끝났습니다 — 상태 {after}. 자동으로 다시 부르지 않습니다.")
            return 3
        return exit_code


def status(experiment: str) -> dict[str, Any]:
    root, doc = _load(experiment)
    mock = bool(doc["mock"])
    records = contract.call_records(root)
    calls = []
    for c in doc["plan"]:
        state = contract.call_state(root, c["callId"], records=records.get(c["callId"], {}), lock_probe=contract.is_held, mock=mock)
        calls.append({"callId": c["callId"], "state": state["state"], "outcome": state["outcome"], "attempts": state["attempts"]})
    approvals = []
    for approval_id, ap in contract.approvals(root).items():
        used = contract.approval_usage(root, approval_id)
        approvals.append({"approvalId": approval_id, "mode": ap.get("mode"), "calls": ap.get("calls"), "maxCliCalls": ap.get("maxCliCalls"), "used": len(used)})
    try:
        verify_integrity(root, doc)
        integrity = "ok"
    except AbError as exc:
        integrity = str(exc)
    return {
        "experimentId": doc["experimentId"],
        "mock": mock,
        "planned": len(doc["plan"]),
        "payloadChecks": payload_checks_ok(root),
        "integrity": integrity,
        "calls": calls,
        "approvals": approvals,
    }


def main(argv: list[str] | None = None) -> int:
    parser = argparse.ArgumentParser(prog="python -m evals.ab_compare", description=__doc__.split("\n")[0])
    sub = parser.add_subparsers(dest="command", required=True)
    p = sub.add_parser("prepare")
    p.add_argument("--experiment", required=True)
    p.add_argument("--protocol", type=Path, default=DEFAULT_PROTOCOL)
    p.add_argument("--mock", action="store_true")
    p = sub.add_parser("payloads")
    p.add_argument("--experiment", required=True)
    p = sub.add_parser("approve")
    p.add_argument("--experiment", required=True)
    p.add_argument("--calls", required=True, help="comma-separated exact call ids")
    p.add_argument("--max-cli-calls", required=True, type=int)
    p = sub.add_parser("run")
    p.add_argument("--experiment", required=True)
    p.add_argument("--approval")
    p.add_argument("--mock", action="store_true")
    p.add_argument("--allow-real-claude", action="store_true")
    p.add_argument("--retry", default="", help="comma-separated call ids to call again (within the approval)")
    p = sub.add_parser("status")
    p.add_argument("--experiment", required=True)
    args = parser.parse_args(argv)
    # Korean status lines on a cp949 Windows console.
    for stream in (sys.stdout, sys.stderr):
        if hasattr(stream, "reconfigure"):
            stream.reconfigure(encoding="utf-8", errors="replace")
    split = lambda raw: [x.strip() for x in raw.split(",") if x.strip()]  # noqa: E731
    try:
        if args.command == "prepare":
            protocol = args.protocol if args.protocol.is_absolute() else Path.cwd() / args.protocol
            if protocol.parent.resolve() != PROTOCOLS.resolve():
                raise AbError("protocols must live in evals/ab_compare/protocols/ (so their lock can be checked)")
            root = prepare(args.experiment, protocol, mock=args.mock)
            print(f"prepared {args.experiment}: {len(read_json(root / 'experiment.json')['plan'])} calls planned")
        elif args.command == "payloads":
            print(json.dumps(payloads(args.experiment), ensure_ascii=False, indent=2))
        elif args.command == "approve":
            approve(args.experiment, split(args.calls), args.max_cli_calls)
        elif args.command == "run":
            return run(
                args.experiment,
                approval=args.approval,
                mock=args.mock,
                allow_real=args.allow_real_claude,
                retry=split(args.retry),
            )
        else:
            print(json.dumps(status(args.experiment), ensure_ascii=False, indent=2))
    except AbError as exc:
        print(f"error: {exc}", file=sys.stderr)
        return 2
    return 0
