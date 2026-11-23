"""Run one or more eval cases against the real model, then score them.

    python -m evals.run_eval --case full
    python -m evals.run_eval --case all --record-baseline --yes
    python -m evals.run_eval --case agent            # tool-selection cases
    python -m evals.run_eval --case agent --variant v1   # same, tool withheld
    python -m evals.run_eval --case real --variant v1    # preserved real run (dev)

The only code in this repository that can spend subscription usage outside a
user's own request. `pytest` never reaches it: pytest.ini sets
`testpaths = app/tests`, and this file is not there.

What it does per case
---------------------

    fixture (RunExplanation)  ->  build_payload  ->  provider  ->  evaluators

`build_payload` runs *here*, not at fixture time. That is deliberate: the
privacy allowlist and the concept selection execute on every eval, so a
regression in either shows up as an eval failure rather than being frozen into
a stored payload.

Cost safety
-----------

Nothing new is invented. The provider's own gates still apply -- an API key in
the environment refuses the call, a non-subscription auth method refuses it,
`--bare` is never used, there is no API fallback and no automatic retry. This
script adds one thing on top: it says out loud how many calls it is about to
make and asks first.
"""

from __future__ import annotations

import argparse
import contextlib
import dataclasses
import hashlib
import io
import json
import re
from pathlib import PurePosixPath, PureWindowsPath
import sys
from collections.abc import Iterable, Iterator
from datetime import datetime, timezone
from pathlib import Path
from typing import Any

from app import config
from app.services.agent import run_scope
from app.services.agent.step_evidence import read_step_evidence
from app.services.explanation.deterministic import RunExplanation
from app.services.explanation.llm import contract, prompt, synthesis

from . import agent_cases, archive_runs, evaluators, explanation_quality, real_runs

HERE = Path(__file__).resolve().parent
FIXTURES = HERE / "fixtures"
EXPECTATIONS = HERE / "expectations"
BASELINES = HERE / "baselines"

CASES = {
    "full": "full_completed_with_warnings",
    "precheck": "precheck_failed",
    "execfailed": "execution_failed",
    "inprogress": "in_progress",
}

# Agent cases. Same harness, same report, same baseline format -- the only
# difference is where the case comes from and what extra question it asks.
#
#     the four above   a frozen RunExplanation   "was the answer grounded?"
#     these three      a run built on the spot   "did it fetch the right thing?"
#
# They are built rather than frozen because the tool reads a real run: see
# agent_cases.py. `--case agent` runs exactly these.
AGENT_CASES = {
    "agentfail": "agent_failed_step",
    "agentwarn": "agent_warning_step",
    "agentnotool": "agent_no_tool_needed",
    # Synthetic held-out case for P1 (cause kinds absent from the dev runs).
    "agentheldout": "agent_resource_heldout",
}

# Synthetic resource_bundle cases written in Cycle 3 (log 17.4). Their own
# group (`--case synth`), out of `agent`, so the existing `--case agent` command
# does not start calling the model more often. Same builder path as the agent
# cases above; synthetic, held out from the dev runs, not independent.
SYNTH_CASES = {
    "agentunclassified": "agent_resource_unclassified",
    "agentindexpair": "agent_resource_index_pair",
}

# Preserved real runs (dev), restored from a capture: see real_runs.py. Not in
# `all` or `agent` -- `--case real` or the alias runs them, and only them.
REAL_CASES = {
    "realcba73e": "real_cba73e",
}

# Real FAILED runs, restored from the evidence archive: see archive_runs.py.
# Their own group (`--case failruns`), kept out of `all`, `agent` and `real`
# so that no existing command starts calling the model more often.
FAILRUN_CASES = {
    "real3a22c5": "real_3a22c5",
    "realb94559": "real_b94559",
}

# Variant -> whether the step detail tool is offered.
#
#     v1      no tool: no MCP channel and no tool instructions in the prompt
#     v3      the production agent, unchanged -- the default
#     v3rag   v3 with the official-document excerpts switched on (log 18):
#             same prompt (same hash), same model, same payload; the ONLY
#             difference is `officialDocs` in the step tool's result
#
# Everything else is held equal: model, initial payload, the rest of the rules,
# output schema, runtime gates. See prompt.py and synthesis.py.
VARIANTS = {"v1": False, "v3": True, "v3rag": True}
DOC_RAG_VARIANTS = frozenset({"v3rag"})
DEFAULT_VARIANT = "v3"


def apply_variant_settings(variant: str) -> None:
    """Process-wide switches a variant implies. Called once, before anything is
    built, so preflight, the in-process tool reads and the MCP server (through
    launch.py's env) all see the same setting."""
    config.DOC_RAG = variant in DOC_RAG_VARIANTS

# fixture가 검체 이름 자리에 넣어 둔 값. payload에 나타나면 allowlist가 뚫린
# 것이다 -- 단 조립 failure code 안은 예외다(privacy_check 참고).
CANARY = "EVAL_SAMPLE_CANARY"

# 모델을 부르지 않기로 한 case와 그 이유. provider 실패와 구분해서 기록한다.
SKIP_MODEL = {
    "in_progress": (
        "제품 UI가 미완료 실행의 synthesis를 막는다(§32). 모델에 가는 사실이 "
        "3개뿐이고, 이 Run은 stale/orphan이라 model baseline 기준으로 적합하지 "
        "않다. in_progress 계약 회귀는 deterministic 검사로 충분하다."
    ),
}


def _hash(text: str) -> str:
    return hashlib.sha256(text.encode("utf-8")).hexdigest()[:16]


def _prompt_hash(variant: str) -> str:
    """Hash of the rules this variant actually sends, not of a fixed constant."""
    return _hash(prompt.constraints_for(offer_tools=VARIANTS[variant]))


def _knowledge_hash() -> str:
    """All four canonical knowledge files, so a knowledge edit is visible."""
    parts = []
    for path in sorted(config.KNOWLEDGE_DIR.glob("*.json")):
        parts.append(path.name)
        parts.append(path.read_text(encoding="utf-8"))
    return _hash("".join(parts))


def privacy_check(fixture: dict[str, Any]) -> evaluators.CheckResult:
    """Does the payload derived from this fixture leak the sample canary?

    Free -- no model call -- so both the live path and `--rescore` run it.
    The fixture keeps a fake sample name precisely so this can be observed;
    if it ever appears in the payload, the allowlist regressed.

    One occurrence is legitimate `[설계판단]`
    ---------------------------------------

    main.sh composes some failure codes from run values, and the sample name
    ends up *inside the code*: `sort_order_DEMO_WES.L001`. That code is the
    failure's identity and its evidence id -- the model has to cite
    `fail:sort_order_EVAL_SAMPLE_CANARY.L001`, so the canary must reach the
    payload there.

    That is not the same thing as leaking `variantCalling.sample`. So the
    codes that carry it are subtracted first, and the canary is then forbidden
    everywhere else. A blanket substring check would fail Case C for doing
    exactly what it is supposed to do.
    """
    payload, _allowed = contract.build_payload(RunExplanation.model_validate(fixture))
    blob = json.dumps(payload, ensure_ascii=False)

    # 조립 failure code 안의 canary는 정당하다. 그 자리만 지우고 나머지를 본다.
    allowed_here = [
        row.get("code", "")
        for row in payload.get("failures", [])
        if CANARY in row.get("code", "")
    ]
    remainder = blob
    for code in allowed_here:
        remainder = remainder.replace(code, "")

    leaked = [n for n in (CANARY, "EVAL_SAMPLE") if n in remainder]
    if leaked:
        return evaluators.CheckResult(
            name="payload-privacy",
            outcome="fail",
            detail=f"fixture canary가 payload에 유입: {leaked}",
        )
    detail = "검체 식별자가 payload에 없음"
    if allowed_here:
        detail += f" (조립 code {len(allowed_here)}건은 evidence id로 허용)"
    return evaluators.CheckResult(
        name="payload-privacy", outcome="pass", detail=detail
    )


class Observation:
    """What one call reported through the two observer seams.

    `build_run_synthesis` already hands both out -- the tool observation and
    the execution trace production stores -- on every exit path. This only
    keeps them for the record, so the eval reuses the runtime's own record
    instead of re-deriving one. `fetched` is the returned evidence, held in
    memory for the number check and never written to the record.
    """

    def __init__(self) -> None:
        self.tool_use: dict[str, Any] | None = None
        self.fetched: list[Any] = []
        self.trace: dict[str, Any] | None = None
        # The answer a gate discarded, with the gate's findings. Never served;
        # kept in the record so a rejection can be read instead of guessed at.
        self.rejected: dict[str, Any] | None = None

    def on_tool_use(self, use) -> None:
        self.tool_use = use.to_json()
        # What came back, for the number check: a measurement the agent
        # fetched is not a measurement it invented.
        self.fetched = list(use.evidence)

    def on_trace(self, trace) -> None:
        # The same fields synthesis_traces stores, as JSON. Tuples become
        # lists; nothing is added. Records made before the repair fields
        # existed simply lack them. `inputSha256` (log 66) is left out: it
        # links a stored answer to its request, an eval record has no stored
        # answer, and a digest-shaped string is exactly what the archive leak
        # check refuses -- so records keep the shape they had.
        self.trace = {
            key: list(value) if isinstance(value, tuple) else value
            for key, value in dataclasses.asdict(trace).items()
            if key != "inputSha256"
        }

    def on_rejection(self, rejected: dict[str, Any]) -> None:
        self.rejected = rejected


def load_expectations(name: str) -> dict[str, Any]:
    return json.loads((EXPECTATIONS / f"{name}.json").read_text(encoding="utf-8"))


def evaluate_agent(name: str, *, variant: str = DEFAULT_VARIANT) -> dict[str, Any]:
    """One agent case: build the run, call the model once, score what it did.

    The extra thing this path does is pass an observer. `build_run_synthesis`
    hands it what the MCP server recorded answering during the call, which is
    the only honest source for "did the agent open a step, and which one" --
    the model's own text is the thing under examination, not a witness to it.

    Under v1 the observer still fires and reports that nothing was opened; the
    tool checks are reported `not_run` rather than scored against that.
    """
    case = agent_cases.CASES[name]
    record, _payload = _evaluate_run(
        name,
        agent_cases.materialise(case),
        variant=variant,
        privacy=lambda fixture, _payload: privacy_check(fixture),
    )
    return _after_case(record, {"caseKind": "agent", "caseIntent": case.intent})


def _after_case(record: dict[str, Any], fields: dict[str, Any]) -> dict[str, Any]:
    """`record` with `fields` placed right after "case", as records always were."""
    ordered: dict[str, Any] = {}
    for key, value in record.items():
        ordered[key] = value
        if key == "case":
            ordered.update(fields)
    return ordered


def _evaluate_run(
    name: str,
    materialised,
    *,
    variant: str,
    privacy,
) -> tuple[dict[str, Any], dict[str, Any]]:
    """Call the model once on a restored run and score it. Shared by agent cases.

    `materialised` is the context manager that builds or restores the run;
    `privacy(fixture, payload)` is the case's own leak check. Returns the record
    without `caseKind`/`caseIntent`, which the caller places first, and the
    payload the model was given.
    """
    offer_tools = VARIANTS[variant]
    expectations = load_expectations(name)
    seen = Observation()

    with materialised as explanation:
        payload, allowed = contract.build_payload(explanation)
        result = synthesis.build_run_synthesis(
            explanation,
            on_tool_use=seen.on_tool_use,
            on_trace=seen.on_trace,
            on_rejection=seen.on_rejection,
            offer_tools=offer_tools,
            # One generation per record, as every baseline was measured.
            # WES_SYNTHESIS_REPAIR configures the server, not the eval.
            repair=False,
        ).model_dump()

    fixture = explanation.model_dump()
    report = evaluators.run_expectations(
        expectations,
        fixture,
        result,
        payload,
        tool_use=seen.tool_use,
        fetched_facts=seen.fetched,
        tools_offered=offer_tools,
    )
    report.results.insert(0, privacy(fixture, payload))

    provenance = result.get("provenance") or {}
    record = {
        "invocationStatus": "invoked",
        "invocationSkippedReason": None,
        "case": name,
        "variant": variant,
        "toolsOffered": offer_tools,
        "recordedAt": datetime.now(timezone.utc).isoformat(timespec="seconds"),
        "provider": provenance.get("provider"),
        "models": provenance.get("models"),
        "durationMs": provenance.get("durationMs"),
        "configuredModel": config.SYNTHESIS_MODEL,
        "promptHash": _prompt_hash(variant),
        "knowledgeHash": _knowledge_hash(),
        "schemaHash": _hash(json.dumps(contract.SYNTHESIS_JSON_SCHEMA, sort_keys=True)),
        "allowedRefCount": len(allowed),
        # What the agent actually did. Transient at runtime -- it is recorded in
        # this eval record and nowhere else.
        "toolUse": seen.tool_use,
        # The runtime's execution record, failures included.
        "trace": seen.trace,
        # Auxiliary: which returned evidence the answer cited. Not a score.
        "evidenceUse": evaluators.evidence_use(seen.tool_use, result),
        "expectedToolUse": expectations.get("expectedToolUse"),
        "expectedStepIds": expectations.get("expectedStepIds"),
        "acceptableStepSets": expectations.get("acceptableStepSets"),
        "evaluation": report.to_json(),
        "humanReview": {
            "reviewedBy": None,
            "verdict": None,
            "notes": None,
            "items": [
                {"name": r.name, "question": r.detail, "verdict": None}
                for r in report.results
                if r.kind == "human"
            ],
        },
        "available": result.get("available"),
        "errorCategory": result.get("errorCategory"),
        "output": result.get("synthesis"),
        # 개발·평가용 설명 품질 검사. evaluation과 별개이며 deterministicPassed에
        # 영향을 주지 않는다(explanation_quality.py).
        "explanationQuality": explanation_quality.evaluate_record(
            expectations, payload, result.get("synthesis")
        ),
        # 덧붙임(삽입 아님). 게이트가 폐기한 답. 사용자에게 제공되지 않았고 채점하지 않는다. 오탐인지
        # 사람이 읽고 재현하기 위해서만 남긴다. 기록 전체와 같은 누출 검사를 받는다.
        "rejectedOutput": seen.rejected,
    }
    return record, payload


# --- real runs (dev) ---------------------------------------------------------
#
# A preserved real run, restored into a temporary copy by real_runs.py. Kept
# apart from the agent cases above: not part of `--case agent` or `all`, and
# recorded with where it came from. The run is a DEV run -- it was seen while
# the agent was developed -- so its result says nothing general on its own.

_RUN_DATA_OPEN = "\n<run_data>\n"


def real_privacy_check(run: real_runs.RealRun, payload: dict[str, Any]) -> evaluators.CheckResult:
    """The real run's sample name, paths and capture must not reach the payload.

    The synthetic check looks for a canary; a real run has a real sample name,
    so this counts the capture's own forbidden literals instead -- and reports
    a count, never what matched.
    """
    leaks = real_runs.count_leaks(json.dumps(payload, ensure_ascii=False), run)
    if leaks:
        return evaluators.CheckResult(
            name="payload-privacy",
            outcome="fail",
            detail=f"검체 식별자·경로가 payload에 {leaks}건 유입",
        )
    return evaluators.CheckResult(
        name="payload-privacy", outcome="pass", detail="검체 식별자·경로가 payload에 없음"
    )


def _code_version() -> dict[str, Any]:
    """The commit the record was made from, and whether tracked files differed."""
    import subprocess

    def git(*args: str) -> str | None:
        try:
            done = subprocess.run(
                ["git", *args],
                cwd=config.ROOT,
                capture_output=True,
                text=True,
                timeout=10,
                check=True,
            )
        except (OSError, subprocess.SubprocessError):
            return None
        return done.stdout.strip()

    commit = git("rev-parse", "HEAD")
    status = git("status", "--porcelain", "--untracked-files=no")
    return {
        "commit": commit,
        # Tracked files only: untracked eval records must not mark every run dirty.
        "trackedChanges": None if status is None else bool(status),
    }


def preflight_real(name: str) -> dict[str, Any]:
    """Everything that can be checked about a real case without calling a model.

    Restores the run twice, so the payload is shown to be a function of the
    capture alone; builds both variants' prompts and compares their run data;
    checks the payload for leaks; and confirms the capture is unchanged.
    """
    run = real_runs.REAL_RUNS[name]
    before = real_runs.capture_manifest(run.capture_dir)

    payloads = []
    for _ in range(2):
        with real_runs.materialise(run) as explanation:
            payloads.append(contract.build_payload(explanation)[0])

    v1, v3 = (
        prompt.build_user_prompt(payloads[0], offer_tools=offered).split(_RUN_DATA_OPEN, 1)[1]
        for offered in (False, True)
    )
    privacy = real_privacy_check(run, payloads[0])
    after = real_runs.capture_manifest(run.capture_dir)

    return {
        "payloadHash": real_runs.payload_hash(payloads[0]),
        "restorationsMatch": payloads[0] == payloads[1],
        "variantRunDataMatch": v1 == v3,
        "privacy": privacy.outcome,
        "privacyDetail": privacy.detail,
        "captureManifest": before,
        "captureUnchanged": before == after,
    }


def preflight_ok(check: dict[str, Any]) -> bool:
    return bool(
        check["restorationsMatch"]
        and check["variantRunDataMatch"]
        and check["privacy"] == "pass"
        and check["captureUnchanged"]
    )


def evaluate_real(name: str, *, variant: str = DEFAULT_VARIANT) -> dict[str, Any]:
    """One real run: restore it, call the model once, score it, say where it came from.

    The capture is hashed before and after. It is never written -- the run is a
    temporary copy -- and the record says whether that held.
    """
    run = real_runs.REAL_RUNS[name]
    before = real_runs.capture_manifest(run.capture_dir)
    record, payload = _evaluate_run(
        name,
        real_runs.materialise(run),
        variant=variant,
        privacy=lambda _fixture, payload: real_privacy_check(run, payload),
    )
    after = real_runs.capture_manifest(run.capture_dir)
    return _after_case(
        record,
        {
            "caseKind": "real",
            "caseIntent": run.intent,
            "source": "capture",
            "split": run.split,
            "runId": run.run_id,
            # The directory's name, not its path: the path says where it sits here.
            "captureDir": run.capture_dir.name,
            "captureManifest": before,
            "captureUnchanged": before == after,
            "payloadHash": real_runs.payload_hash(payload),
            "codeVersion": _code_version(),
        },
    )


# --- real failed runs from the evidence archive (dev) ---------------------------
#
# Same scoring path as the capture above; what differs is where the run comes
# from (archive_runs.py) and two extra preflight checks: the step tool must
# hand back the diagnosis the case was built on, and nothing from the answer
# key may appear in what the model would see.

_HEX64 = re.compile(r"\b[0-9a-f]{64}\b")


def _archive_leaks(text: str, run: archive_runs.ArchiveRun, extra=(), loaded=None) -> int:
    """Sample, ids, locations and 64-hex digests in `text`. A count only."""
    return archive_runs.count_leaks(text, run, extra, loaded=loaded) + len(_HEX64.findall(text))


# Fields of a saved archive record that name the source on purpose. Everything
# else in the record (output, trace, evaluation, ...) is scanned.
_RECORD_SOURCE_FIELDS = ("runId", "archive")


def archive_record_leaks(run: archive_runs.ArchiveRun, record: dict[str, Any], loaded=None) -> int:
    """Run id, sample, a path or a 64-hex digest anywhere in the record but
    its source fields.

    The record's own top-level `...Hash` / `...Digest` fields (archiveDigest,
    payloadHash, promptHash, ...) are digests by design and are left out of the
    64-hex count only; everything else -- output, trace, evaluation -- is held
    to the same rules as the payload. A count only -- matches are never printed.
    """
    exempt = {"runId": run.run_id, "archive": run.archive.name}
    rest = {k: v for k, v in record.items() if not (k in exempt and v == exempt[k])}
    text = json.dumps(rest, ensure_ascii=False)
    undigested = {k: v for k, v in rest.items() if not k.endswith(("Hash", "Digest"))}
    hexes = len(_HEX64.findall(json.dumps(undigested, ensure_ascii=False)))
    return archive_runs.count_leaks(text, run, loaded=loaded) + hexes


# A capture record names its source in these two fields on purpose (the run id
# and the capture folder's name). They are exempt only while they hold exactly
# that -- a source field carrying anything else is checked like the rest
# (Codex review, log 17.3).
def _real_source_values(run: real_runs.RealRun) -> dict[str, str]:
    return {"runId": run.run_id, "captureDir": run.capture_dir.name}


def real_record_leaks(run: real_runs.RealRun, record: dict[str, Any]) -> int:
    """Sample name, capture paths or a path in a capture record, outside its
    two source fields. A count only -- matches are never printed.

    "A path" is what real_runs.count_paths recognises -- not every string a
    reader would call a path (a one-segment "/etc" is not counted). The run's
    own paths are also refused as exact literals. The archive twin is
    archive_record_leaks. Before this existed a capture record went to
    baselines/ (tracked by git) unchecked (log 17.2).
    """
    exempt = _real_source_values(run)
    rest = {k: v for k, v in record.items() if not (k in exempt and v == exempt[k])}
    ancestors = sorted({a for lit in real_runs.forbidden_literals(run) for a in path_ancestors(lit)})
    return real_runs.count_leaks(json.dumps(rest, ensure_ascii=False), run, extra=ancestors)


def path_ancestors(literal: str) -> list[str]:
    """The directories above a forbidden path, root excluded.

    Codex round 2 (log 17.3): "/ClinicSecret/runs/job42" was refused whole but
    "/ClinicSecret" alone passed -- a one-segment path the shared detector does
    not count. Only this write boundary adds them; the shared detector used by
    the payload checks is unchanged. Fails closed: a mention of a real
    ancestor refuses the save, it never lets one through.
    """
    if literal.startswith("/"):
        path = PurePosixPath(literal)
    elif re.match(r"^[A-Za-z]:[\\/]", literal) or literal.startswith("\\\\"):
        path = PureWindowsPath(literal)
    else:
        return []
    return [str(parent) for parent in path.parents if str(parent) != path.anchor]


def mask_record(value: Any, literals: Iterable[str]) -> Any:
    """A copy of `value` with every string masked: literals, then paths.

    Applied to a record BEFORE print_report truncates its strings -- a sample
    name cut in half at the 60-character limit would no longer match.
    """
    literals = list(literals)
    if isinstance(value, str):
        return real_runs.mask_paths(real_runs.mask_literals(value, literals))
    if isinstance(value, dict):
        return {k: mask_record(v, literals) for k, v in value.items()}
    if isinstance(value, list):
        return [mask_record(v, literals) for v in value]
    return value


@contextlib.contextmanager
def masked_output(literals: Iterable[str]) -> Iterator[None]:
    """Collect what is printed inside, mask it, then write it to the terminal.

    The second line of defence after mask_record: it also covers anything a
    report helper prints that is not a string inside the record.
    """
    literals = list(literals)
    buffer = io.StringIO()
    try:
        # stderr too: Python-level writes from anything run inside. Output a
        # child process writes straight to the file descriptor is not seen.
        with contextlib.redirect_stdout(buffer), contextlib.redirect_stderr(buffer):
            yield
    finally:
        sys.stdout.write(
            real_runs.mask_paths(real_runs.mask_literals(buffer.getvalue(), literals))
        )


def archive_privacy_check(
    run: archive_runs.ArchiveRun, payload: dict[str, Any], loaded=None
) -> evaluators.CheckResult:
    leaks = _archive_leaks(json.dumps(payload, ensure_ascii=False), run, loaded=loaded)
    if leaks:
        return evaluators.CheckResult(
            name="payload-privacy",
            outcome="fail",
            detail=f"검체 식별자·경로·해시가 payload에 {leaks}건 유입",
        )
    return evaluators.CheckResult(
        name="payload-privacy", outcome="pass", detail="검체 식별자·경로·해시가 payload에 없음"
    )


def answer_key_strings(expectations: dict[str, Any]) -> list[str]:
    """Sentences that exist only in the answer key, never in run evidence."""
    out = [line for line in expectations.get("_comment") or [] if len(line) > 20]
    out += [h["question"] for h in expectations.get("humanReview") or []]
    out += [e["what"] for e in expectations.get("confirmedErrors") or []]
    out += [c["why"] for c in expectations.get("mustCite") or []]
    for key in ("allowedUncertainty", "forbiddenClaims", "unsafeRemediations"):
        out += list(expectations.get(key) or [])
    return out


def preflight_archive(name: str) -> dict[str, Any]:
    """Everything checkable about an archived failed run, without a model.

    Reads the archive once, restores it twice from that read (the payload and
    the step tool's result must each be a function of the archive alone),
    reads the step the case needs through the agent's own reader, and checks
    what the model would be sent -- the v3 prompt plus that step's evidence --
    for leaks and for the answer key's own sentences.

    `answerKeyIsolated` is a narrow check: none of the answer key's free-text
    sentences (and not the case name) occur verbatim in what the model would
    see. It cannot show the key had no influence in other ways; that the key
    is never read by the agent path is a property of the code (only run_eval
    and the evaluators open evals/expectations).
    """
    run = archive_runs.ARCHIVE_RUNS[name]
    expectations = load_expectations(name)
    step_id = expectations["expectedDiagnosis"]["stepId"]
    loaded = archive_runs.load(run)
    before = archive_runs.archive_digest(run.archive)

    payloads: list[dict[str, Any]] = []
    evidences: list[dict[str, Any]] = []
    work_dirs: list[str] = []
    for _ in range(2):
        with archive_runs.materialise(run, loaded=loaded) as explanation:
            work_dirs.append(str(Path(config.RUNS_ROOT).parent))
            payloads.append(contract.build_payload(explanation)[0])
            evidences.append(
                read_step_evidence(run_scope.for_job(run.run_id), step_id).model_dump()
            )
    evidence = evidences[0]

    v1, v3 = (
        prompt.build_user_prompt(payloads[0], offer_tools=offered).split(_RUN_DATA_OPEN, 1)[1]
        for offered in (False, True)
    )
    model_bound = prompt.build_user_prompt(payloads[0], offer_tools=True) + json.dumps(
        evidence, ensure_ascii=False
    )
    leaks = _archive_leaks(model_bound, run, extra=work_dirs, loaded=loaded)
    leaked_key = [s for s in answer_key_strings(expectations) if s in model_bound]
    diagnosis = evaluators.check_tool_diagnosis(expectations, [evidence])
    after = archive_runs.archive_digest(run.archive)

    return {
        "payloadHash": real_runs.payload_hash(payloads[0]),
        "restorationsMatch": payloads[0] == payloads[1],
        "variantRunDataMatch": v1 == v3,
        "privacy": "pass" if leaks == 0 else "fail",
        "privacyDetail": f"prompt+도구 결과의 식별자·경로·해시 {leaks}건 (정의한 검사 범위)",
        "toolEvidenceMatches": evidences[0] == evidences[1],
        "toolDiagnosisMatches": diagnosis.outcome == "pass",
        "toolDiagnosisDetail": diagnosis.detail,
        "answerKeyIsolated": not leaked_key and name not in model_bound,
        "archiveDigest": before,
        "parsedDigestMatchesFile": loaded.digest == before,
        "archiveUnchanged": before == after,
    }


def preflight_archive_ok(check: dict[str, Any]) -> bool:
    return bool(
        check["restorationsMatch"]
        and check["variantRunDataMatch"]
        and check["privacy"] == "pass"
        and check["toolEvidenceMatches"]
        and check["toolDiagnosisMatches"]
        and check["answerKeyIsolated"]
        and check["archiveUnchanged"]
        and check["parsedDigestMatchesFile"]
    )


def evaluate_archive(
    name: str, *, variant: str = DEFAULT_VARIANT, loaded: archive_runs.LoadedRun | None = None
) -> dict[str, Any]:
    """One archived failed run: restore, call the model once, score, say where from.

    `loaded` is the read main() checked against the preflight digest; the
    model then sees exactly the bytes preflight validated.
    """
    run = archive_runs.ARCHIVE_RUNS[name]
    if loaded is None:
        loaded = archive_runs.load(run)
    before = loaded.digest  # the digest of exactly the bytes restored
    record, payload = _evaluate_run(
        name,
        archive_runs.materialise(run, loaded=loaded),
        variant=variant,
        privacy=lambda _fixture, payload: archive_privacy_check(run, payload, loaded=loaded),
    )
    after = archive_runs.archive_digest(run.archive)
    return _after_case(
        record,
        {
            "caseKind": "real",
            "caseIntent": run.intent,
            "source": "archive",
            "split": run.split,
            "runId": run.run_id,
            # The file's name, not its path.
            "archive": run.archive.name,
            "archiveDigest": before,
            "archiveUnchanged": before == after,
            "jobRowAssumptions": list(run.assumptions),
            "payloadHash": real_runs.payload_hash(payload),
            "codeVersion": _code_version(),
        },
    )


def load_case(name: str) -> tuple[dict[str, Any], dict[str, Any]]:
    fixture = json.loads((FIXTURES / f"{name}.json").read_text(encoding="utf-8"))
    expectations = json.loads(
        (EXPECTATIONS / f"{name}.json").read_text(encoding="utf-8")
    )
    return fixture, expectations


def evaluate(name: str, *, variant: str = DEFAULT_VARIANT) -> dict[str, Any]:
    """One case: build payload, call the model once, score the result.

    A case listed in SKIP_MODEL is evaluated without calling anything. Its
    record says `invocationStatus: skipped` with a reason -- deliberately not
    running is not the same state as a provider failing, and a report that
    conflated them would make a decision look like an outage.
    """
    offer_tools = VARIANTS[variant]
    fixture, expectations = load_case(name)
    explanation = RunExplanation.model_validate(fixture)

    payload, allowed = contract.build_payload(explanation)
    skipped = SKIP_MODEL.get(name)
    # Recorded, not scored: these cases declare no tool expectation, and their
    # fact source stays the fixture -- `seen.fetched` is deliberately unused.
    seen = Observation()

    if skipped:
        result = {"available": False, "errorCategory": None, "synthesis": None}
        report = evaluators.run_expectations(
            expectations, fixture, result, payload, model_invoked=False
        )
    else:
        result = synthesis.build_run_synthesis(
            explanation,
            on_tool_use=seen.on_tool_use,
            on_trace=seen.on_trace,
            on_rejection=seen.on_rejection,
            offer_tools=offer_tools,
            # One generation per record, as every baseline was measured.
            # WES_SYNTHESIS_REPAIR configures the server, not the eval.
            repair=False,
        ).model_dump()
        report = evaluators.run_expectations(
            expectations, fixture, result, payload, tools_offered=offer_tools
        )
    report.results.insert(0, privacy_check(fixture))

    provenance = result.get("provenance") or {}
    return {
        "invocationStatus": "skipped" if skipped else "invoked",
        "invocationSkippedReason": skipped,
        "case": name,
        "variant": variant,
        "toolsOffered": offer_tools,
        "recordedAt": datetime.now(timezone.utc).isoformat(timespec="seconds"),
        "provider": provenance.get("provider"),
        "models": provenance.get("models"),
        "durationMs": provenance.get("durationMs"),
        "configuredModel": config.SYNTHESIS_MODEL,
        "promptHash": _prompt_hash(variant),
        "knowledgeHash": _knowledge_hash(),
        "schemaHash": _hash(json.dumps(contract.SYNTHESIS_JSON_SCHEMA, sort_keys=True)),
        "allowedRefCount": len(allowed),
        # None when skipped: nothing was called, so there is nothing observed.
        "toolUse": seen.tool_use,
        "trace": seen.trace,
        "evidenceUse": None if skipped else evaluators.evidence_use(seen.tool_use, result),
        "evaluation": report.to_json(),
        # 사람이 채운다. 자동으로 pass를 넣지 않는다.
        "humanReview": {
            "reviewedBy": None,
            "verdict": None,
            "notes": None,
            "items": [
                {"name": r.name, "question": r.detail, "verdict": None}
                for r in report.results
                if r.kind == "human"
            ],
        },
        "available": result.get("available"),
        "errorCategory": result.get("errorCategory"),
        "output": result.get("synthesis"),
        # 개발·평가용 설명 품질 검사. evaluation과 별개이며 deterministicPassed에
        # 영향을 주지 않는다(explanation_quality.py).
        "explanationQuality": explanation_quality.evaluate_record(
            expectations, payload, result.get("synthesis")
        ),
        # 덧붙임(삽입 아님). 게이트가 폐기한 답. 사용자에게 제공되지 않았고 채점하지 않는다. 오탐인지
        # 사람이 읽고 재현하기 위해서만 남긴다. 기록 전체와 같은 누출 검사를 받는다.
        "rejectedOutput": seen.rejected,
    }


def print_report(record: dict[str, Any]) -> None:
    print(f"\n=== {record['case']} ===")
    if "variant" in record:
        # 기록 이전의 baseline에는 이 필드가 없다. 없는 것을 v3라고 추정하지 않는다.
        offered = "Tool 제공" if record.get("toolsOffered") else "Tool 미제공"
        print(f"  variant    {record['variant']} ({offered})")
    if record.get("caseKind") == "real" and record.get("source") == "archive":
        print(f"  source     실제 실패 Run 압축 파일 ({record['split']}) · payload {record['payloadHash'][:16]}")
        if not record.get("archiveUnchanged"):
            print("  경고       압축 파일이 평가 전후로 다릅니다. 압축 파일을 확인하세요.")
    elif record.get("caseKind") == "real":
        print(f"  source     실제 Run capture ({record['split']}) · payload {record['payloadHash'][:16]}")
        if not record.get("captureUnchanged"):
            print("  경고       capture manifest가 평가 전후로 다릅니다. capture를 확인하세요.")
    if record.get("invocationStatus") == "skipped":
        # 실패가 아니라 의도적 미실행이다. 헤더에서부터 구분한다.
        print("  model      호출하지 않음 (skipped)")
        print(f"  이유       {record.get('invocationSkippedReason')}")
    else:
        print(f"  model      {record.get('models')}")
        print(f"  duration   {record.get('durationMs')} ms")
        print(
            f"  available  {record.get('available')} "
            f"{record.get('errorCategory') or ''}"
        )
    for row in record["evaluation"]["results"]:
        mark = {
            "pass": "PASS",
            "fail": "FAIL",
            "needs_review": "REVIEW",
            "not_run": "SKIP",
        }[row["outcome"]]
        print(f"  [{mark:6}] {row['name']:44} {row['detail'][:60]}")
    if record.get("invocationStatus") == "skipped":
        # "PASSED"라고 쓰면 출력을 채점해서 통과한 것처럼 읽힌다. 실제로는
        # 계약 검사만 돌았다.
        checked = [
            r for r in record["evaluation"]["results"] if r["outcome"] != "not_run"
        ]
        print(
            f"  계약 검사만 수행: {len(checked)}건 통과 · "
            f"출력 채점 {len(record['evaluation']['results']) - len(checked)}건 미실행"
        )
    else:
        print(
            f"  deterministic: "
            f"{'PASSED' if record['evaluation']['deterministicPassed'] else 'FAILED'}"
            f" · human items: {len(record['humanReview']['items'])}"
        )
    rejected = record.get("rejectedOutput")
    if rejected:
        print_rejected(rejected)
    if "explanationQuality" in record:
        # 기록 이전의 baseline에는 이 키가 없다. 없는 것을 검사하지 않는다.
        explanation_quality.print_quality(record["case"], record["explanationQuality"])


_REJECTED_LOCATION = re.compile(
    r"(summary|importantFindings|limitations|nextChecks|uncertainties)(?:\.([0-9]{1,6}))?",
    re.ASCII,
)


def rejected_statement(answer: Any, location: Any) -> str | None:
    """The sentence at a gate location like "importantFindings.5" or "summary".

    None for anything that is not exactly such a location, or not a sentence.
    """
    if not isinstance(answer, dict) or not isinstance(location, str):
        return None
    match = _REJECTED_LOCATION.fullmatch(location)
    if match is None:
        return None
    group, index = match.groups()
    value = answer.get(group)
    if group == "summary":
        return value if index is None and isinstance(value, str) else None
    if index is None or not isinstance(value, list) or int(index) >= len(value):
        return None
    item = value[int(index)]
    statement = item.get("statement") if isinstance(item, dict) else None
    return statement if isinstance(statement, str) else None


def _as_list(value: Any) -> list[Any]:
    """A list as is; anything else -- a bare string included -- as nothing."""
    return value if isinstance(value, list) else []


def print_rejected(rejected: dict[str, Any]) -> None:
    """What the gate discarded and where. Not served; printed for diagnosis."""
    print(
        f"  폐기된 답 (시도 {rejected.get('attempt')}, {rejected.get('category')}) "
        "-- 사용자에게 제공되지 않음, 오탐 여부 진단용"
    )
    for finding in _as_list(rejected.get("findings")):
        if not isinstance(finding, dict):
            continue
        for location in _as_list(finding.get("locations")):
            text = rejected_statement(rejected.get("answer"), location)
            print(f"    {location}: {text if text is not None else '(위치를 찾지 못함)'}")
        for problem in _as_list(finding.get("values")):
            print(f"      - {problem}")


def rescore(names: list[str], *, record: bool) -> int:
    """Re-evaluate stored baselines. No model call."""
    failed = 0
    for name in names:
        if (
            name in agent_cases.CASES
            or name in real_runs.REAL_RUNS
            or name in archive_runs.ARCHIVE_RUNS
        ):
            # An agent case has no frozen fixture: its run is built on the spot
            # and its tool-use observation only exists during the call. Scoring
            # a stored output again would answer the grounding questions and
            # silently skip the two that case exists for. A real run is restored
            # the same way, and is refused for the same reason.
            print(f"{name}: agent/실제 Run case는 rescore를 지원하지 않습니다 (실행이 필요).")
            continue
        matches = sorted(BASELINES.glob(f"*_{name}_*.json"))
        if not matches:
            print(f"{name}: baseline이 없습니다.")
            continue
        path = matches[-1]
        stored = json.loads(path.read_text(encoding="utf-8"))
        fixture, expectations = load_case(name)
        result = {
            "available": stored.get("available"),
            "errorCategory": stored.get("errorCategory"),
            "synthesis": stored.get("output"),
        }
        payload, _ = contract.build_payload(RunExplanation.model_validate(fixture))
        # A baseline recorded as `skipped` has no model output, and rescoring it
        # as if it did turns "we never called" into "the provider failed" -- the
        # one distinction this record exists to keep. Carry the status forward.
        invoked = stored.get("invocationStatus") != "skipped"
        report = evaluators.run_expectations(
            expectations, fixture, result, payload, model_invoked=invoked
        )
        report.results.insert(0, privacy_check(fixture))
        stored["evaluation"] = report.to_json()
        stored["rescoredAt"] = datetime.now(timezone.utc).isoformat(timespec="seconds")
        print_report(stored)
        # 출력만 한다. --record가 baseline에 새 키를 끼워 넣지 않게 stored에는 넣지 않는다.
        explanation_quality.print_quality(
            name,
            explanation_quality.evaluate_record(expectations, payload, stored.get("output")),
        )
        if record:
            path.write_text(
                json.dumps(stored, ensure_ascii=False, indent=2) + "\n",
                encoding="utf-8",
            )
            print(f"  baseline 갱신 -> {path.name} (모델 호출 없음)")
        if not report.ok:
            failed += 1
    return 1 if failed else 0


def baseline_path(name: str, variant: str, stamp: str) -> Path:
    """Where a new record for this case and variant is written.

    promptHash를 파일명에 넣는다. 같은 날 같은 모델로 prompt만 바꿔 다시 돌리면
    이전 baseline을 덮어쓰게 되는데, 그 파일이 바로 비교 기준이다. 무엇이 이
    결과를 만들었는지가 이름에 있어야 한다. variant도 같은 이유로 들어간다 --
    v1과 v3는 prompt hash도 다르지만, 이름만 보고 구분할 수 있어야 한다.

    variant 필드가 생기기 전의 baseline 이름은 바꾸지 않는다.
    """
    model = (config.SYNTHESIS_MODEL or "default").replace("/", "-")
    return BASELINES / f"{stamp}_{name}_{variant}_{model}_{_prompt_hash(variant)}.json"


def write_baseline(path: Path, record: dict[str, Any]) -> None:
    """Create `path`, never replace it.

    Mode "x" fails if the file exists, so a stored baseline cannot be
    overwritten even when the pre-check in main() was passed earlier -- e.g.
    the date rolled over during a long run onto an existing name.
    """
    with path.open("x", encoding="utf-8") as handle:
        handle.write(json.dumps(record, ensure_ascii=False, indent=2) + "\n")


def main() -> int:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument(
        "--case",
        choices=[
            *sorted(CASES),
            *sorted(AGENT_CASES),
            *sorted(REAL_CASES),
            *sorted(FAILRUN_CASES),
            *sorted(SYNTH_CASES),
            "all",
            "agent",
            "real",
            "failruns",
            "synth",
        ],
        required=True,
    )
    parser.add_argument(
        "--preflight-only",
        action="store_true",
        help="실제 Run 사전 검증만 하고 모델을 호출하지 않고 종료한다",
    )
    parser.add_argument(
        "--record-baseline",
        action="store_true",
        help="결과를 evals/baselines/ 에 저장한다",
    )
    parser.add_argument(
        "--rescore",
        action="store_true",
        help="저장된 baseline의 출력을 다시 채점한다. 모델을 호출하지 않는다",
    )
    parser.add_argument(
        "--yes",
        action="store_true",
        help="비대화형 실행. 이 플래그 없이는 확인을 요구한다",
    )
    parser.add_argument(
        "--variant",
        choices=sorted(VARIANTS),
        default=DEFAULT_VARIANT,
        help="v1 = Tool 미제공(MCP·Tool 지시문 없음), v3 = 운영 Agent (기본값), v3rag = v3 + 공식 문서 발췌",
    )
    args = parser.parse_args()
    apply_variant_settings(args.variant)

    if args.case == "all":
        names = list(CASES.values())
    elif args.case == "agent":
        names = list(AGENT_CASES.values())
    elif args.case == "real":
        names = list(REAL_CASES.values())
    elif args.case == "failruns":
        names = list(FAILRUN_CASES.values())
    elif args.case == "synth":
        names = list(SYNTH_CASES.values())
    elif args.case in SYNTH_CASES:
        names = [SYNTH_CASES[args.case]]
    elif args.case in AGENT_CASES:
        names = [AGENT_CASES[args.case]]
    elif args.case in REAL_CASES:
        names = [REAL_CASES[args.case]]
    elif args.case in FAILRUN_CASES:
        names = [FAILRUN_CASES[args.case]]
    else:
        names = [CASES[args.case]]

    if args.rescore:
        # evaluator를 고쳤을 때 쓴다. 모델 출력은 그대로 두고 채점만 다시 한다 --
        # 내 채점 버그 때문에 구독 사용량을 또 쓸 이유가 없다.
        return rescore(names, record=args.record_baseline)

    real = [n for n in names if n in real_runs.REAL_RUNS]
    missing = [n for n in real if not real_runs.capture_available(real_runs.REAL_RUNS[n])]
    if missing:
        # capture는 git에 없다. 없는 환경에서 조용히 넘어가지 않고 멈춘다.
        print("오류: 실제 Run capture가 이 환경에 없어 중단합니다. 호출하지 않았습니다.")
        for n in missing:
            print(f"  {n}: {real_runs.REAL_RUNS[n].capture_dir.name}/ 가 저장소 루트에 필요합니다")
        return 2

    for n in real:
        # 모델을 부르기 전에 확인할 수 있는 것은 전부 확인한다.
        check = preflight_real(n)
        print(f"사전 검증 ({n}, 모델 호출 없음)")
        print(f"  payload hash      {check['payloadHash'][:16]}")
        print(f"  복원 2회 payload 일치   {check['restorationsMatch']}")
        print(f"  V1/V3 run data 일치    {check['variantRunDataMatch']}")
        print(f"  개인정보 검사      {check['privacy']} ({check['privacyDetail']})")
        print(f"  capture manifest  {check['captureManifest'][:16]} · 불변 {check['captureUnchanged']}")
        if not preflight_ok(check):
            print("오류: 사전 검증 실패로 중단합니다. 호출하지 않았습니다.")
            return 2

    archived = [n for n in names if n in archive_runs.ARCHIVE_RUNS]
    if args.preflight_only and not (real or archived):
        # 성공(0)으로 끝나면 아무것도 확인하지 않았는데 확인한 것처럼 보인다.
        print("오류: 이 case 묶음에는 사전 검증 대상이 없습니다 (real / failruns 전용). 호출하지 않았습니다.")
        return 2
    absent = [
        n for n in archived if not archive_runs.archive_available(archive_runs.ARCHIVE_RUNS[n])
    ]
    if absent:
        # 압축 파일은 git에 없다. 없는 환경에서 조용히 넘어가지 않고 멈춘다.
        print("오류: 실제 실패 Run 압축 파일이 이 환경에 없어 중단합니다. 호출하지 않았습니다.")
        for n in absent:
            print(f"  {n}: {archive_runs.ARCHIVE_RUNS[n].archive.name} 이(가) 저장소 루트에 필요합니다")
        return 2

    preflight_digests: dict[str, str] = {}
    for n in archived:
        try:
            check = preflight_archive(n)
        except archive_runs.ArchiveError as exc:
            print(f"오류: {n} 복원 실패로 중단합니다. 호출하지 않았습니다. ({exc})")
            return 2
        except Exception as exc:  # noqa: BLE001 -- the text may quote a path; the type is enough
            print(f"오류: {n} 사전 검증 중 예외로 중단합니다. 호출하지 않았습니다. ({type(exc).__name__})")
            return 2
        print(f"사전 검증 ({n}, 모델 호출 없음)")
        print(f"  payload hash          {check['payloadHash'][:16]}")
        print(f"  복원 2회 payload 일치   {check['restorationsMatch']}")
        print(f"  V1/V3 run data 일치    {check['variantRunDataMatch']}")
        print(f"  개인정보 검사          {check['privacy']} ({check['privacyDetail']})")
        print(f"  복원 2회 도구 결과 일치 {check['toolEvidenceMatches']}")
        print(f"  도구 진단 일치         {check['toolDiagnosisMatches']} ({check['toolDiagnosisDetail']})")
        print(f"  정답 문장 미포함        {check['answerKeyIsolated']} (정답 문장의 문자열 일치 검사)")
        print(f"  압축 파일 불변         {check['archiveUnchanged']} · {check['archiveDigest'][:16]}")
        print(f"  읽은 바이트 = 파일      {check['parsedDigestMatchesFile']}")
        print("  job 행 가정 (원본에 없는 값):")
        for assumption in archive_runs.ARCHIVE_RUNS[n].assumptions:
            print(f"    - {assumption}")
        if not preflight_archive_ok(check):
            print("오류: 사전 검증 실패로 중단합니다. 호출하지 않았습니다.")
            return 2
        preflight_digests[n] = check["archiveDigest"]

    if args.preflight_only:
        print("--preflight-only: 사전 검증만 하고 모델을 호출하지 않고 종료합니다.")
        return 0

    stamp = datetime.now(timezone.utc).strftime("%Y-%m-%d")
    if args.record_baseline:
        # 모델을 부르기 전에 확인한다. 사용량을 쓰고 나서 저장할 곳이 없다는 것을
        # 알게 되면 안 된다. 기존 파일은 건드리지 않고 멈춘다.
        taken = [
            path
            for path in (baseline_path(n, args.variant, stamp) for n in names)
            if path.exists()
        ]
        if taken:
            print("오류: 같은 이름의 baseline이 이미 있어 중단합니다. 호출하지 않았습니다.")
            for path in taken:
                print(f"  {path.name}")
            print("  기존 파일은 그대로 두었습니다. 옮기거나 이름을 바꾼 뒤 다시 실행하세요.")
            return 2

    calling = [n for n in names if n not in SKIP_MODEL]
    print("이 명령은 Claude Max 구독 사용량을 소비합니다.")
    print(f"  variant: {args.variant}")
    print(
        f"  case {len(names)}개 중 {len(calling)}개 호출 · 총 {len(calling)}회"
    )
    for n in names:
        if n in SKIP_MODEL:
            print(f"  (skip) {n} : 모델을 호출하지 않습니다")
        if n in real_runs.REAL_RUNS:
            print(f"  (real) {n} : 실제 Run capture · {real_runs.REAL_RUNS[n].split} · 일반 성능 근거 아님")
        if n in archive_runs.ARCHIVE_RUNS:
            print(f"  (real) {n} : 실제 실패 Run 압축 파일 · {archive_runs.ARCHIVE_RUNS[n].split} · 일반 성능 근거 아님")
    print(f"  model: {config.SYNTHESIS_MODEL or 'CLI 기본값'}")
    print("  자동 재시도 없음. 실패하면 그대로 보고합니다.")
    if not calling:
        print("  호출할 case가 없습니다. 확인 없이 진행합니다.")
    if calling and not args.yes:
        answer = input("계속할까요? [y/N] ").strip().lower()
        if answer not in ("y", "yes"):
            print("취소했습니다. 호출하지 않았습니다.")
            return 1

    records = []
    for name in names:
        loaded = None
        if name in archive_runs.ARCHIVE_RUNS:
            # 사전 검증한 바이트와 모델이 볼 바이트가 같아야 한다.
            try:
                loaded = archive_runs.load(archive_runs.ARCHIVE_RUNS[name])
            except archive_runs.ArchiveError as exc:
                print(f"오류: {name} 압축 파일을 다시 읽지 못해 중단합니다. 호출하지 않았습니다. ({exc})")
                return 2
            if loaded.digest != preflight_digests.get(name):
                print(f"오류: {name} 사전 검증 뒤 압축 파일이 바뀌어 중단합니다. 호출하지 않았습니다.")
                return 2
            # 터미널도 기록과 같은 규칙으로 가린다. 평가 실행 중 출력도 포함한다.
            literals = archive_runs.forbidden_literals(archive_runs.ARCHIVE_RUNS[name], loaded)
            try:
                with masked_output(literals):
                    record = evaluate_archive(name, variant=args.variant, loaded=loaded)
            except Exception as exc:  # noqa: BLE001 -- its text may quote a path or the sample
                print(f"오류: {name} 평가 중 예외로 중단합니다. ({type(exc).__name__}; 내용은 출력하지 않음)")
                return 2
            with masked_output(literals):
                print_report(mask_record(record, literals))
            records.append(record)
        elif name in real_runs.REAL_RUNS:
            record = evaluate_real(name, variant=args.variant)
            # A real capture's report is masked like an archive's: the record
            # can carry answer text (rejectedOutput is printed in full).
            print_report(
                mask_record(record, real_runs.forbidden_literals(real_runs.REAL_RUNS[name]))
            )
            records.append(record)
        elif name in agent_cases.CASES:
            record = evaluate_agent(name, variant=args.variant)
        else:
            record = evaluate(name, variant=args.variant)
        if name not in archive_runs.ARCHIVE_RUNS and name not in real_runs.REAL_RUNS:
            print_report(record)
            records.append(record)

        if args.record_baseline:
            if name in archive_runs.ARCHIVE_RUNS:
                leaks = archive_record_leaks(archive_runs.ARCHIVE_RUNS[name], record, loaded=loaded)
                if leaks:
                    # baselines/는 git 추적 대상이다. 식별자가 섞인 기록은 쓰지 않는다.
                    print(f"오류: {name} 기록에 식별자·경로 {leaks}건이 있어 저장하지 않고 중단합니다.")
                    return 2
            elif name in real_runs.REAL_RUNS:
                leaks = real_record_leaks(real_runs.REAL_RUNS[name], record)
                if leaks:
                    # archive와 같은 규칙. 이전에는 capture 기록이 검사 없이 저장됐다.
                    print(f"오류: {name} 기록에 식별자·경로 {leaks}건이 있어 저장하지 않고 중단합니다.")
                    return 2
            BASELINES.mkdir(parents=True, exist_ok=True)
            target = baseline_path(name, args.variant, stamp)
            try:
                write_baseline(target, record)
            except FileExistsError:
                print(f"오류: {target.name} 이(가) 이미 있어 저장하지 않고 중단합니다.")
                print("  기존 파일은 그대로 두었습니다.")
                return 2
            print(f"  baseline -> {target.name}")

    failed = [r for r in records if not r["evaluation"]["deterministicPassed"]]
    print(
        f"\n{len(records)}개 case · deterministic 실패 {len(failed)}개 · "
        "human 항목은 사람이 검토해야 합니다."
    )
    return 1 if failed else 0


if __name__ == "__main__":
    sys.exit(main())
