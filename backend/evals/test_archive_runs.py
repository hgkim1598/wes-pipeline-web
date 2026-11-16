"""Real failed runs from the evidence archive: restored safely, read, left untouched.

No model is called and no pipeline is run. The provider, where a test needs
one, is a fake; the step tool is exercised through the same reader -- and once
through a real MCP child process -- that the agent uses.

Two kinds of input, kept apart:

    synthetic   tiny tar.gz archives built in tmp_path. Every archive-safety
                test (traversal, links, sizes, corruption) uses these, so they
                always run.
    real        wes_failure_evidence_20261112.tar.gz, which is NOT in git. On a
                machine without it those tests are skipped with a reason.

Assertions about leaks compare counts and booleans, never the matched strings,
so a failing test cannot print a sample name or a path into the log.
"""

from __future__ import annotations

import io
import json
import re
import tarfile
from pathlib import Path

import pytest

from app import config
from app.services import resource_bundle_causes, step_reader
from app.services.agent import run_scope
from app.services.agent.step_evidence import read_step_evidence
from app.services.explanation.llm import contract, prompt, provider

from . import agent_cases, archive_runs, evaluators

STEP = "00_input_validation"
EXPECTATIONS_DIR = Path(__file__).resolve().parent / "expectations"
CASE_NAMES = ("real_3a22c5", "real_b94559")
HEX64 = re.compile(r"\b[0-9a-f]{64}\b")

needs_archive = pytest.mark.skipif(
    not archive_runs.ARCHIVE.is_file(),
    reason=(
        f"실제 실패 Run 압축 파일({archive_runs.ARCHIVE.name})이 이 환경에 없음 -- "
        "이 파일은 git에 포함되지 않는다"
    ),
)


def _expectations(name: str) -> dict:
    return json.loads((EXPECTATIONS_DIR / f"{name}.json").read_text(encoding="utf-8"))


# --- synthetic archives -------------------------------------------------------

SYN_RUN = "wes-20990101-000000-abcdef"


def _member(name: str, data: bytes = b"", kind: bytes = tarfile.REGTYPE, link: str = ""):
    info = tarfile.TarInfo(name)
    info.type = kind
    info.size = len(data) if kind == tarfile.REGTYPE else 0
    info.linkname = link
    info.mode = 0o644
    return info, (io.BytesIO(data) if kind == tarfile.REGTYPE else None)


def _valid_files(run_id: str = SYN_RUN, *, sample: str | None = "SYN_SAMPLE") -> list:
    metrics = {"schema_version": "1", "run_id": run_id, "step_id": STEP, "metrics": {}}
    if sample is not None:
        metrics["metrics"]["sample"] = sample
    return [
        _member(f"{run_id}/status/run_status.json", json.dumps({"status": "failed"}).encode()),
        _member(f"{run_id}/status/steps/{STEP}.json", json.dumps({"status": "failed"}).encode()),
        _member(f"{run_id}/metrics/{STEP}.json", json.dumps(metrics).encode()),
        _member(f"{run_id}/logs/pipeline.log", b"[INFO] synthetic log\n"),
    ]


def _write_archive(path: Path, members: list) -> Path:
    with tarfile.open(path, "w:gz") as tar:
        for info, data in members:
            tar.addfile(info, data)
    return path


def _syn_run(archive: Path, run_id: str = SYN_RUN) -> archive_runs.ArchiveRun:
    return archive_runs.ArchiveRun(
        name="synthetic", intent="합성 압축 파일", run_id=run_id, archive=archive
    )


def _files_under(root: Path) -> list[Path]:
    return sorted(p for p in root.rglob("*") if p.is_file()) if root.exists() else []


# --- 1. minimal extraction (synthetic) -----------------------------------------


def test_only_the_allowed_files_of_the_named_run_are_extracted(tmp_path):
    other = "wes-20990101-000000-fedcba"
    archive = _write_archive(
        tmp_path / "a.tar.gz",
        [
            _member(f"{SYN_RUN}/", kind=tarfile.DIRTYPE),
            *_valid_files(),
            _member(f"{SYN_RUN}/config/run_config.snapshot.json", b"{}"),
            _member(f"{SYN_RUN}/00_input_validation/manifest.tsv", b"x"),
            *_valid_files(other),
        ],
    )
    dest = tmp_path / "out"
    run_dir = archive_runs.extract_run(_syn_run(archive), dest)

    assert run_dir == dest / SYN_RUN
    got = sorted(p.relative_to(run_dir).as_posix() for p in _files_under(dest))
    assert got == sorted(archive_runs.REQUIRED_FILES)


def test_the_optional_report_is_extracted_when_present(tmp_path):
    archive = _write_archive(
        tmp_path / "a.tar.gz",
        [*_valid_files(), _member(f"{SYN_RUN}/{STEP}/resource_validation.txt", b"r")],
    )
    run_dir = archive_runs.extract_run(_syn_run(archive), tmp_path / "out")
    assert (run_dir / STEP / "resource_validation.txt").read_bytes() == b"r"


# --- 2. missing and corrupt archives (synthetic) --------------------------------


def test_a_missing_archive_is_refused_before_anything_is_created(tmp_path, monkeypatch):
    made: list[str] = []
    monkeypatch.setattr(agent_cases.tempfile, "mkdtemp", lambda *a, **k: made.append("x") or "")
    run = _syn_run(tmp_path / "no_such.tar.gz")

    assert archive_runs.archive_available(run) is False
    with pytest.raises(archive_runs.ArchiveMissing):
        with archive_runs.materialise(run):
            pass
    with pytest.raises(archive_runs.ArchiveMissing):
        archive_runs.extract_run(run, tmp_path / "out")
    assert made == []
    assert not (tmp_path / "out").exists()


def test_a_file_that_is_not_a_gzip_tar_is_refused(tmp_path):
    bad = tmp_path / "bad.tar.gz"
    bad.write_bytes(b"this is not an archive" * 10)
    with pytest.raises(archive_runs.ArchiveError):
        archive_runs.extract_run(_syn_run(bad), tmp_path / "out")
    assert _files_under(tmp_path / "out") == []


def test_a_truncated_archive_is_refused(tmp_path):
    good = _write_archive(tmp_path / "good.tar.gz", _valid_files())
    cut = tmp_path / "cut.tar.gz"
    cut.write_bytes(good.read_bytes()[: len(good.read_bytes()) // 2])
    with pytest.raises(archive_runs.ArchiveError):
        archive_runs.extract_run(_syn_run(cut), tmp_path / "out")
    assert _files_under(tmp_path / "out") == []


# --- 3. unsafe member names and types (synthetic) -------------------------------


@pytest.mark.parametrize(
    "name",
    [
        "../escape.txt",
        f"{SYN_RUN}/../../escape.txt",
        "/abs/escape.txt",
        "C:/escape.txt",
        f"{SYN_RUN}\\..\\escape.txt",
        f"{SYN_RUN}/logs/./pipeline.log",
        "",
    ],
)
def test_an_unsafe_member_name_rejects_the_whole_archive(tmp_path, name):
    archive = _write_archive(tmp_path / "a.tar.gz", [*_valid_files(), _member(name, b"x")])
    with pytest.raises(archive_runs.ArchiveError):
        archive_runs.extract_run(_syn_run(archive), tmp_path / "out")
    assert _files_under(tmp_path / "out") == []
    assert not (tmp_path / "escape.txt").exists()


@pytest.mark.parametrize(
    ("kind", "link"),
    [
        (tarfile.SYMTYPE, "/etc/passwd"),
        (tarfile.SYMTYPE, "../../outside"),
        (tarfile.LNKTYPE, f"{SYN_RUN}/logs/pipeline.log"),
        (tarfile.FIFOTYPE, ""),
        (tarfile.CHRTYPE, ""),
    ],
)
def test_links_and_special_files_reject_the_whole_archive(tmp_path, kind, link):
    archive = _write_archive(
        tmp_path / "a.tar.gz",
        [*_valid_files(), _member(f"{SYN_RUN}/logs/extra", kind=kind, link=link)],
    )
    with pytest.raises(archive_runs.ArchiveError):
        archive_runs.extract_run(_syn_run(archive), tmp_path / "out")
    assert _files_under(tmp_path / "out") == []


def test_a_link_in_place_of_a_required_file_is_refused(tmp_path):
    files = _valid_files()[:-1]  # drop the real pipeline.log
    files.append(_member(f"{SYN_RUN}/logs/pipeline.log", kind=tarfile.SYMTYPE, link="/etc/hosts"))
    archive = _write_archive(tmp_path / "a.tar.gz", files)
    with pytest.raises(archive_runs.ArchiveError):
        archive_runs.extract_run(_syn_run(archive), tmp_path / "out")


def test_a_duplicate_member_path_is_refused(tmp_path):
    archive = _write_archive(
        tmp_path / "a.tar.gz",
        [*_valid_files(), _member(f"{SYN_RUN}/logs/pipeline.log", b"second copy")],
    )
    with pytest.raises(archive_runs.ArchiveError):
        archive_runs.extract_run(_syn_run(archive), tmp_path / "out")


# --- 4. size limits (synthetic) -------------------------------------------------


def test_an_oversized_member_is_refused(tmp_path, monkeypatch):
    # The limit sits just above every other member, so only the log is over it
    # (Codex review r2: with 64 the metrics JSON was refused first).
    others = _valid_files()[:-1]
    limit = max(info.size for info, _ in others)
    monkeypatch.setattr(archive_runs, "MAX_MEMBER_BYTES", limit)
    files = others + [_member(f"{SYN_RUN}/logs/pipeline.log", b"x" * (limit + 1))]
    archive = _write_archive(tmp_path / "a.tar.gz", files)
    with pytest.raises(archive_runs.ArchiveError):
        archive_runs.extract_run(_syn_run(archive), tmp_path / "out")
    assert _files_under(tmp_path / "out") == []


def test_an_oversized_total_is_refused(tmp_path, monkeypatch):
    monkeypatch.setattr(archive_runs, "MAX_TOTAL_BYTES", 100)
    files = _valid_files()[:-1] + [_member(f"{SYN_RUN}/logs/pipeline.log", b"x" * 90)]
    archive = _write_archive(tmp_path / "a.tar.gz", files)
    with pytest.raises(archive_runs.ArchiveError):
        archive_runs.extract_run(_syn_run(archive), tmp_path / "out")


def test_too_many_members_are_refused(tmp_path, monkeypatch):
    monkeypatch.setattr(archive_runs, "MAX_MEMBERS", 3)
    archive = _write_archive(tmp_path / "a.tar.gz", _valid_files())
    with pytest.raises(archive_runs.ArchiveError):
        archive_runs.extract_run(_syn_run(archive), tmp_path / "out")


def test_a_member_over_the_size_limit_is_refused_after_bounded_inflation(tmp_path, monkeypatch):
    """A tiny .tar.gz holding a member larger than MAX_MEMBER_BYTES is refused.

    The stream is inflated first (bounded by MAX_STREAM_BYTES, see the stream
    cap tests) and the member is refused by its header size during selection;
    this test does not show refusal before inflation."""
    monkeypatch.setattr(archive_runs, "MAX_MEMBER_BYTES", 1024)
    files = _valid_files()[:-1] + [_member(f"{SYN_RUN}/logs/pipeline.log", b"\0" * 2_000_000)]
    archive = _write_archive(tmp_path / "a.tar.gz", files)
    assert archive.stat().st_size < 50_000  # compresses to almost nothing
    with pytest.raises(archive_runs.ArchiveError):
        archive_runs.extract_run(_syn_run(archive), tmp_path / "out")


# --- 5. run identifiers and required data (synthetic) ---------------------------


@pytest.mark.parametrize("run_id", ["../wes-20990101-000000-abcdef", "not-a-run", "wes-2099", ""])
def test_a_malformed_run_id_is_refused(tmp_path, run_id):
    archive = _write_archive(tmp_path / "a.tar.gz", _valid_files())
    with pytest.raises(archive_runs.ArchiveError):
        archive_runs.extract_run(_syn_run(archive, run_id), tmp_path / "out")


def test_a_run_that_is_not_in_the_archive_is_refused(tmp_path):
    archive = _write_archive(tmp_path / "a.tar.gz", _valid_files())
    with pytest.raises(archive_runs.ArchiveError):
        archive_runs.extract_run(
            _syn_run(archive, "wes-20990101-000000-000000"), tmp_path / "out"
        )


def test_a_missing_required_file_is_refused(tmp_path):
    archive = _write_archive(tmp_path / "a.tar.gz", _valid_files()[:-1])
    with pytest.raises(archive_runs.ArchiveError):
        archive_runs.extract_run(_syn_run(archive), tmp_path / "out")
    assert _files_under(tmp_path / "out") == []


def test_a_run_without_a_recorded_sample_is_refused_and_cleaned_up(tmp_path, monkeypatch):
    """No guessed sample id: without one the redactor could not hide the real one."""
    archive = _write_archive(tmp_path / "a.tar.gz", _valid_files(sample=None))
    made: list[Path] = []
    real_mkdtemp = agent_cases.tempfile.mkdtemp

    def recording(*args, **kwargs):
        path = real_mkdtemp(*args, **kwargs)
        made.append(Path(path))
        return path

    monkeypatch.setattr(agent_cases.tempfile, "mkdtemp", recording)
    previous = (config.RUNS_ROOT, config.JOBS_ROOT, config.UPLOAD_ROOT, config.DB_PATH)

    with pytest.raises(archive_runs.ArchiveError):
        with archive_runs.materialise(_syn_run(archive)):
            pass

    # Since the review fix the sample is checked by load(), BEFORE the
    # throwaway environment exists, so normally no directory is made at all.
    # Either way nothing may be left behind. (Cleanup of a directory that
    # WAS made is covered by test_the_temporary_copy_is_removed_and_config_restored_even_on_error.)
    assert made == []
    assert (config.RUNS_ROOT, config.JOBS_ROOT, config.UPLOAD_ROOT, config.DB_PATH) == previous


def test_extraction_leaves_a_synthetic_archive_unchanged(tmp_path):
    archive = _write_archive(tmp_path / "a.tar.gz", _valid_files())
    before = archive_runs.archive_digest(archive)
    archive_runs.extract_run(_syn_run(archive), tmp_path / "out")
    assert archive_runs.archive_digest(archive) == before


# --- 6. the evaluator check (synthetic) -----------------------------------------


def _diag_expectations() -> dict:
    return {
        "expectedToolUse": "required",
        "expectedDiagnosis": {
            "stepId": STEP,
            "state": "parsed",
            "source": "pipeline_log",
            "truncated": False,
            "causes": [
                {"kind": "k1", "resourceRole": "r1", "tool": None, "ruleId": "R1"},
                {"kind": "k2", "resourceRole": "unknown", "tool": "t", "ruleId": "R2"},
            ],
        },
    }


def _fetched(causes: list[dict], **diag) -> list[dict]:
    return [
        {
            "stepId": STEP,
            "evidenceId": f"step:{STEP}",
            "resourceBundleDiagnosis": {
                "state": "parsed",
                "source": "pipeline_log",
                "truncated": False,
                "causes": causes,
                **diag,
            },
        }
    ]


def test_tool_diagnosis_check_passes_on_the_same_causes_in_any_order():
    causes = list(reversed(_diag_expectations()["expectedDiagnosis"]["causes"]))
    fetched = _fetched([{**c, "evidenceText": "x"} for c in causes])
    result = evaluators.check_tool_diagnosis(_diag_expectations(), fetched)
    assert result.outcome == "pass"


def test_tool_diagnosis_check_fails_on_a_missing_cause():
    fetched = _fetched(_diag_expectations()["expectedDiagnosis"]["causes"][:1])
    assert evaluators.check_tool_diagnosis(_diag_expectations(), fetched).outcome == "fail"


def test_tool_diagnosis_check_fails_on_a_different_state():
    fetched = _fetched(_diag_expectations()["expectedDiagnosis"]["causes"], state="segment_unresolved")
    assert evaluators.check_tool_diagnosis(_diag_expectations(), fetched).outcome == "fail"


def test_tool_diagnosis_check_is_not_run_when_the_step_was_not_opened():
    assert evaluators.check_tool_diagnosis(_diag_expectations(), []).outcome == "not_run"


def test_run_expectations_adds_the_diagnosis_check_only_when_declared():
    result = {"available": False, "errorCategory": "providerUnavailable"}
    with_it = evaluators.run_expectations(_diag_expectations(), {}, result, fetched_facts=[])
    without = evaluators.run_expectations({"expectedToolUse": "required"}, {}, result)
    assert "tool-evidence-diagnosis" in [r.name for r in with_it.results]
    assert "tool-evidence-diagnosis" not in [r.name for r in without.results]
    no_tool = evaluators.run_expectations(
        _diag_expectations(), {}, result, fetched_facts=[], tools_offered=False
    )
    rows = {r.name: r.outcome for r in no_tool.results}
    assert rows["tool-evidence-diagnosis"] == "not_run"


# --- 7. registry and answer keys (no archive needed) ----------------------------


def test_the_two_failed_runs_are_registered_apart_from_every_other_group():
    from . import run_eval

    assert set(archive_runs.ARCHIVE_RUNS) == set(CASE_NAMES)
    assert set(run_eval.FAILRUN_CASES.values()) == set(CASE_NAMES)
    others = (
        set(run_eval.CASES.values())
        | set(run_eval.AGENT_CASES.values())
        | set(run_eval.REAL_CASES.values())
    )
    assert not set(CASE_NAMES) & others


@pytest.mark.parametrize("name", CASE_NAMES)
def test_each_answer_key_matches_its_case_definition(name):
    if not (EXPECTATIONS_DIR / f"{name}.json").is_file():
        pytest.skip("private real-run answer key is absent")
    run = archive_runs.ARCHIVE_RUNS[name]
    exp = _expectations(name)
    assert exp["case"] == name
    assert exp["runId"] == run.run_id
    assert exp["source"] == "archive" and exp["split"] == run.split == "dev"
    assert exp["expectedToolUse"] == "required"
    assert exp["acceptableStepSets"] == [[STEP]]
    assert all(set(s) <= set(run.planned) for s in exp["acceptableStepSets"])
    assert exp["mustMention"] == []  # meaning is judged by humans, not by word match
    assert {"all-causes-reported", "causes-not-merged", "no-unsafe-remediation"} <= {
        h["name"] for h in exp["humanReview"]
    }


@pytest.mark.parametrize("name", CASE_NAMES)
def test_job_row_assumptions_are_declared_not_hidden(name):
    run = archive_runs.ARCHIVE_RUNS[name]
    assert run.run_mode in {"full", "check_only"}
    assert run.planned[0] == STEP
    assert run.assumptions and all(isinstance(a, str) and a for a in run.assumptions)


# --- 8. the real archive ----------------------------------------------------------


def _answer_key_strings(name: str) -> list[str]:
    """Sentences that exist only in the answer key, never in run evidence."""
    exp = _expectations(name)
    out = [line for line in exp["_comment"] if len(line) > 20]
    out += [h["question"] for h in exp["humanReview"]]
    out += [e["what"] for e in exp["confirmedErrors"]]
    out += exp["allowedUncertainty"] + exp["forbiddenClaims"] + exp["unsafeRemediations"]
    return out


def _vocab(diag: dict) -> dict:
    return {
        "state": diag["state"],
        "source": diag["source"],
        "truncated": diag["truncated"],
        "causes": sorted(
            (c["kind"], c["resourceRole"], c["tool"], c["ruleId"]) for c in diag["causes"]
        ),
    }


@needs_archive
@pytest.mark.parametrize("name", CASE_NAMES)
def test_the_run_is_restored_into_a_temporary_copy(name):
    run = archive_runs.ARCHIVE_RUNS[name]
    with archive_runs.materialise(run) as explanation:
        work = Path(config.RUNS_ROOT).parent
        row = run_scope.db.query_one("SELECT * FROM jobs WHERE job_id = ?", (run.run_id,))
        run_dir = Path(row["run_dir"])
        assert run_dir == Path(config.RUNS_ROOT) / run.run_id
        assert archive_runs.ARCHIVE.parent not in run_dir.parents
        assert work in run_dir.parents
        assert row["run_mode"] == run.run_mode
        assert json.loads(row["planned_steps"]) == list(run.planned)
        assert row["status"] == "DONE"
        assert row["capture_kit_id"] is None
        # The sample is the one the run itself recorded -- compared, never printed.
        same_sample = row["sample_id"] == archive_runs.read_sample(run)
        assert same_sample, "sample_id differs from the recorded sample (values withheld)"
        # Exactly the required files plus the optional ones the run has: here
        # the artifact registry (no resource report was recorded).
        assert sorted(p.relative_to(run_dir).as_posix() for p in _files_under(run_dir)) == sorted(
            [*archive_runs.REQUIRED_FILES, f"artifacts/{STEP}.json"]
        )
        assert explanation.status == "failed"


@needs_archive
@pytest.mark.parametrize(
    ("name", "codes"),
    [("real_3a22c5", ["resource_bundle"]), ("real_b94559", ["required_tools", "resource_bundle"])],
)
def test_the_recorded_failures_reach_the_payload(name, codes):
    run = archive_runs.ARCHIVE_RUNS[name]
    with archive_runs.materialise(run) as explanation:
        payload, allowed = contract.build_payload(explanation)
    assert sorted(f["code"] for f in payload["failures"]) == codes
    for code in codes:
        assert f"fail:{code}" in allowed


@needs_archive
@pytest.mark.parametrize("name", CASE_NAMES)
def test_the_answer_key_diagnosis_is_what_the_code_reads_from_the_archive(name, tmp_path):
    """The expected causes are re-derived from the original evidence, not copied."""
    run = archive_runs.ARCHIVE_RUNS[name]
    run_dir = archive_runs.extract_run(run, tmp_path / "x")
    checks = step_reader.read(run_dir, [STEP], "full", STEP)["validation"]["results"]
    analysis = resource_bundle_causes.analyze(run_dir, STEP, checks)
    got = {
        "state": analysis.state,
        "source": analysis.source,
        "truncated": analysis.truncated,
        "causes": sorted((c.kind, c.resource_role, c.tool, c.rule_id) for c in analysis.causes),
    }
    assert got == _vocab(_expectations(name)["expectedDiagnosis"])


@needs_archive
@pytest.mark.parametrize("name", CASE_NAMES)
def test_the_agent_tool_reads_the_diagnosis_without_leaks(name):
    run = archive_runs.ARCHIVE_RUNS[name]
    with archive_runs.materialise(run):
        work = Path(config.RUNS_ROOT).parent
        evidence = read_step_evidence(run_scope.for_job(run.run_id), STEP).model_dump()
    diag = evidence["resourceBundleDiagnosis"]
    assert _vocab(diag) == _vocab(_expectations(name)["expectedDiagnosis"])
    assert diag["withheldTextCount"] == 0  # a sample was known, so text could be released
    said = json.dumps(evidence, ensure_ascii=False)
    assert archive_runs.count_leaks(said, run, extra=[str(work)]) == 0
    assert not HEX64.search(said)


@needs_archive
@pytest.mark.parametrize("name", CASE_NAMES)
def test_two_restorations_give_the_same_payload_and_both_variants_the_same_run_data(name):
    run = archive_runs.ARCHIVE_RUNS[name]
    payloads = []
    for _ in range(2):
        with archive_runs.materialise(run) as explanation:
            payloads.append(contract.build_payload(explanation)[0])
    assert payloads[0] == payloads[1]
    block = "\n<run_data>\n"
    v1, v3 = (
        prompt.build_user_prompt(payloads[0], offer_tools=o).split(block, 1)[1]
        for o in (False, True)
    )
    assert v1 == v3


@needs_archive
@pytest.mark.parametrize("name", CASE_NAMES)
def test_payload_and_prompt_carry_no_sample_path_hash_or_answer_key(name):
    run = archive_runs.ARCHIVE_RUNS[name]
    with archive_runs.materialise(run) as explanation:
        work = Path(config.RUNS_ROOT).parent
        payload, _ = contract.build_payload(explanation)
        evidence = read_step_evidence(run_scope.for_job(run.run_id), STEP).model_dump()
    user_prompt = prompt.build_user_prompt(payload, offer_tools=True)
    model_bound = user_prompt + json.dumps(evidence, ensure_ascii=False)

    assert archive_runs.count_leaks(model_bound, run, extra=[str(work)]) == 0
    assert not HEX64.search(model_bound)
    leaked = [s for s in _answer_key_strings(name) if s in model_bound]
    assert leaked == []
    assert name not in model_bound  # the case name itself is answer-key side


@needs_archive
def test_restoring_and_reading_leaves_the_archive_unchanged():
    before = archive_runs.archive_digest(archive_runs.ARCHIVE)
    for name in CASE_NAMES:
        run = archive_runs.ARCHIVE_RUNS[name]
        with archive_runs.materialise(run):
            read_step_evidence(run_scope.for_job(run.run_id), STEP)
    assert archive_runs.archive_digest(archive_runs.ARCHIVE) == before


@needs_archive
def test_the_temporary_copy_is_removed_and_config_restored_even_on_error(monkeypatch):
    made: list[Path] = []
    real_mkdtemp = agent_cases.tempfile.mkdtemp

    def recording(*args, **kwargs):
        path = real_mkdtemp(*args, **kwargs)
        made.append(Path(path))
        return path

    monkeypatch.setattr(agent_cases.tempfile, "mkdtemp", recording)
    previous = (config.RUNS_ROOT, config.JOBS_ROOT, config.UPLOAD_ROOT, config.DB_PATH)
    run = archive_runs.ARCHIVE_RUNS["real_3a22c5"]

    with archive_runs.materialise(run):
        assert made[0].is_dir()
    with pytest.raises(RuntimeError):
        with archive_runs.materialise(run):
            raise RuntimeError("boom")

    assert len(made) == 2 and not any(p.exists() for p in made)
    assert (config.RUNS_ROOT, config.JOBS_ROOT, config.UPLOAD_ROOT, config.DB_PATH) == previous


@needs_archive
@pytest.mark.parametrize("name", CASE_NAMES)
def test_a_spawned_mcp_server_returns_the_diagnosis(monkeypatch, name):
    """The production launch config and a real child process -- no model."""
    from app.services.explanation.llm import tools

    from .test_real_runs import _call_over_stdio, _server_config, _spawned

    run = archive_runs.ARCHIVE_RUNS[name]
    started = _spawned(monkeypatch)
    with archive_runs.materialise(run):
        work = Path(config.RUNS_ROOT).parent
        with tools.step_detail_toolset(run.run_id) as toolset:
            server = _server_config(toolset)
            assert Path(server["env"]["WES_DB_PATH"]) == Path(config.DB_PATH)
            assert Path(server["env"]["WES_RUNS_ROOT"]) == Path(config.RUNS_ROOT)
            listed, (result,) = _call_over_stdio(server, [STEP])

    assert [t.name for t in listed] == ["get_step_detail"]
    assert result.is_error is False
    diag = result.structured_content["resourceBundleDiagnosis"]
    assert _vocab(diag) == _vocab(_expectations(name)["expectedDiagnosis"])
    said = json.dumps(result.structured_content, ensure_ascii=False)
    assert archive_runs.count_leaks(said, run, extra=[str(work)]) == 0
    assert started and all(p.returncode is not None for p in started)


# --- 9. the runner, without a model ---------------------------------------------


def _forbid_model(monkeypatch, run_eval):
    def must_not_call(*_a, **_k):
        raise AssertionError("the model path was reached")

    monkeypatch.setattr(run_eval.synthesis, "build_run_synthesis", must_not_call)
    monkeypatch.setattr(provider, "run_structured", must_not_call)
    monkeypatch.setattr(provider.subprocess, "run", must_not_call)
    monkeypatch.setattr("builtins.input", must_not_call)


@needs_archive
@pytest.mark.parametrize("name", CASE_NAMES)
def test_preflight_checks_everything_without_a_model(monkeypatch, name):
    from . import run_eval

    _forbid_model(monkeypatch, run_eval)
    check = run_eval.preflight_archive(name)

    assert check["restorationsMatch"] is True
    assert check["variantRunDataMatch"] is True
    assert check["privacy"] == "pass"
    assert check["archiveUnchanged"] is True
    assert check["toolDiagnosisMatches"] is True
    assert check["answerKeyIsolated"] is True
    assert run_eval.preflight_archive_ok(check) is True


@needs_archive
def test_preflight_only_stops_before_any_model_call(monkeypatch, capsys):
    from . import run_eval

    _forbid_model(monkeypatch, run_eval)
    monkeypatch.setattr("sys.argv", ["run_eval", "--case", "failruns", "--preflight-only"])

    assert run_eval.main() == 0
    out = capsys.readouterr().out
    assert "모델을 호출하지 않고 종료" in out
    assert out.count("사전 검증 (") == 2


def test_the_runner_stops_before_calling_when_the_archive_is_missing(
    monkeypatch, capsys, tmp_path
):
    from . import run_eval

    for name in CASE_NAMES:
        monkeypatch.setitem(
            archive_runs.ARCHIVE_RUNS,
            name,
            archive_runs.ArchiveRun(
                name=name,
                intent="",
                run_id=archive_runs.ARCHIVE_RUNS[name].run_id,
                archive=tmp_path / "missing.tar.gz",
            ),
        )
    _forbid_model(monkeypatch, run_eval)
    monkeypatch.setattr("sys.argv", ["run_eval", "--case", "failruns", "--yes"])

    assert run_eval.main() == 2
    assert "압축 파일이 이 환경에 없어 중단" in capsys.readouterr().out


def _recording_provider():
    def fake(**_kwargs):
        return provider.ProviderResult(
            payload={
                "summary": "실행을 확인했습니다.",
                "importantFindings": [
                    {"statement": "실행이 실패했습니다.", "evidenceRefs": ["run:status"]}
                ],
                "limitations": [],
                "nextChecks": [],
                "uncertainties": [],
            },
            models=["test-model"],
        )

    return fake


@needs_archive
def test_an_archive_record_says_where_it_came_from(monkeypatch):
    from . import run_eval

    real_build = run_eval.synthesis.build_run_synthesis

    def build(explanation, **kwargs):
        return real_build(explanation, run_provider=_recording_provider(), **kwargs)

    monkeypatch.setattr(run_eval.synthesis, "build_run_synthesis", build)
    run = archive_runs.ARCHIVE_RUNS["real_b94559"]
    before = archive_runs.archive_digest(run.archive)

    record = run_eval.evaluate_archive("real_b94559", variant="v3")

    assert record["caseKind"] == "real"
    assert record["source"] == "archive"
    assert record["split"] == "dev"
    assert record["runId"] == run.run_id
    assert record["archive"] == run.archive.name
    assert record["archiveDigest"] == before
    assert record["archiveUnchanged"] is True
    assert record["jobRowAssumptions"] == list(run.assumptions)
    rows = {r["name"]: r["outcome"] for r in record["evaluation"]["results"]}
    assert rows["payload-privacy"] == "pass"
    # The fake opened nothing: the required tool use is a failure, and the
    # diagnosis check is not scored on top of it.
    assert rows["tool-use"] == "fail"
    assert rows["tool-evidence-diagnosis"] == "not_run"
    # runId and archive name the source on purpose (as captureDir does for the
    # capture record). Everything else -- output, trace, evaluation -- must
    # carry neither the run id nor the sample nor a path.
    rest = {k: v for k, v in record.items() if k not in ("runId", "archive")}
    assert archive_runs.count_leaks(json.dumps(rest, ensure_ascii=False), run) == 0
    # The same record passes the save-time scan, digest fields included.
    assert run_eval.archive_record_leaks(run, record) == 0
    assert archive_runs.archive_digest(run.archive) == before


# --- 10. hardening after the independent review (2026-11-15) -------------------


def _bomb_archive(path: Path, fmt: int, inflated: int) -> Path:
    """A tiny .tar.gz whose HEADER data (pax record / GNU long name) is huge."""
    info = tarfile.TarInfo(f"{SYN_RUN}/logs/pipeline.log")
    if fmt == tarfile.PAX_FORMAT:
        info.pax_headers = {"comment": "0" * inflated}
    else:
        info.name = f"{SYN_RUN}/" + "a" * inflated
    data = b"x"
    info.size = len(data)
    buf = io.BytesIO()
    with tarfile.open(fileobj=buf, mode="w", format=fmt) as tar:
        tar.addfile(info, io.BytesIO(data))
    import gzip

    path.write_bytes(gzip.compress(buf.getvalue(), compresslevel=9))
    return path


@pytest.mark.parametrize("fmt", [tarfile.PAX_FORMAT, tarfile.GNU_FORMAT])
def test_a_header_bomb_is_refused_with_bounded_memory(tmp_path, fmt):
    """pax / GNU long-name data is read by tarfile before any member is seen.

    The review measured a 204 KB archive reaching a 400 MiB peak. The stream
    must be capped before tarfile parses it, so memory stays near the cap.
    """
    import tracemalloc

    inflated = 64 * 1024 * 1024
    archive = _bomb_archive(tmp_path / "bomb.tar.gz", fmt, inflated)
    assert archive.stat().st_size < 1024 * 1024

    tracemalloc.start()
    try:
        with pytest.raises(archive_runs.ArchiveError):
            archive_runs.extract_run(_syn_run(archive), tmp_path / "out")
        _, peak = tracemalloc.get_traced_memory()
    finally:
        tracemalloc.stop()
    assert peak < 32 * 1024 * 1024
    assert _files_under(tmp_path / "out") == []


def _negative_size_archive(path: Path) -> Path:
    """A member whose size field is a base-256 negative number (-256)."""
    buf = io.BytesIO()
    with tarfile.open(fileobj=buf, mode="w", format=tarfile.GNU_FORMAT) as tar:
        for info, data in _valid_files():
            tar.addfile(info, data)
    raw = bytearray(buf.getvalue())
    header = raw[:512]  # the first member's header
    header[124:136] = b"\xff" * 11 + b"\x00"  # size = -256 in base-256
    header[148:156] = b" " * 8
    header[148:156] = ("%06o\0 " % sum(header)).encode("ascii")
    raw[:512] = header
    import gzip

    path.write_bytes(gzip.compress(bytes(raw)))
    return path


def test_a_negative_member_size_is_refused(tmp_path):
    archive = _negative_size_archive(tmp_path / "neg.tar.gz")
    with pytest.raises(archive_runs.ArchiveError):
        archive_runs.extract_run(_syn_run(archive), tmp_path / "out")
    assert _files_under(tmp_path / "out") == []


def test_an_oversized_compressed_file_is_refused_before_reading(tmp_path, monkeypatch):
    monkeypatch.setattr(archive_runs, "MAX_ARCHIVE_BYTES", 16)
    archive = _write_archive(tmp_path / "a.tar.gz", _valid_files())
    with pytest.raises(archive_runs.ArchiveError):
        archive_runs.extract_run(_syn_run(archive), tmp_path / "out")


def test_an_oversized_decompressed_stream_is_refused(tmp_path, monkeypatch):
    monkeypatch.setattr(archive_runs, "MAX_STREAM_BYTES", 1024)
    files = _valid_files()[:-1] + [_member(f"{SYN_RUN}/logs/pipeline.log", b"x" * 900)]
    archive = _write_archive(tmp_path / "a.tar.gz", files)
    with pytest.raises(archive_runs.ArchiveError):
        archive_runs.extract_run(_syn_run(archive), tmp_path / "out")


def test_one_load_supplies_the_files_the_sample_and_the_digest(tmp_path):
    """Everything a restore uses comes from ONE read of the archive bytes."""
    archive = _write_archive(tmp_path / "a.tar.gz", _valid_files())
    loaded = archive_runs.load(_syn_run(archive))
    assert loaded.digest == archive_runs.archive_digest(archive)
    assert loaded.sample == "SYN_SAMPLE"
    assert sorted(loaded.files) == sorted(archive_runs.REQUIRED_FILES)

    run_dir = archive_runs.extract_run(_syn_run(archive), tmp_path / "out", loaded=loaded)
    for rel, data in loaded.files.items():
        assert (run_dir / rel).read_bytes() == data


@needs_archive
@pytest.mark.parametrize("name", CASE_NAMES)
def test_the_tool_reports_the_artifacts_the_run_registered(name):
    """The review found artifactCount 0 where the run registered 3."""
    run = archive_runs.ARCHIVE_RUNS[name]
    loaded = archive_runs.load(run)
    registered = len(json.loads(loaded.files[f"artifacts/{STEP}.json"])["artifacts"])
    with archive_runs.materialise(run, loaded=loaded):
        evidence = read_step_evidence(run_scope.for_job(run.run_id), STEP).model_dump()
    assert registered > 0
    assert evidence["artifactCount"] == registered


@needs_archive
@pytest.mark.parametrize("name", CASE_NAMES)
def test_preflight_also_compares_the_tool_result_across_restorations(monkeypatch, name):
    from . import run_eval

    _forbid_model(monkeypatch, run_eval)
    check = run_eval.preflight_archive(name)
    assert check["toolEvidenceMatches"] is True
    assert check["parsedDigestMatchesFile"] is True


@needs_archive
def test_a_leaking_record_is_detected_before_it_could_be_saved():
    from . import run_eval

    run = archive_runs.ARCHIVE_RUNS["real_3a22c5"]
    clean = {"runId": run.run_id, "archive": run.archive.name, "output": {"summary": "ok"}}
    leaky = {**clean, "output": {"summary": archive_runs.read_sample(run)}}
    assert run_eval.archive_record_leaks(run, clean) == 0
    assert run_eval.archive_record_leaks(run, leaky) > 0


def test_preflight_only_refuses_a_group_that_has_nothing_to_preflight(monkeypatch, capsys):
    from . import run_eval

    _forbid_model(monkeypatch, run_eval)
    monkeypatch.setattr("sys.argv", ["run_eval", "--case", "agent", "--preflight-only"])
    assert run_eval.main() == 2
    assert "사전 검증 대상이 없습니다" in capsys.readouterr().out


# --- 11. second review (2026-11-15): L-a, L-b ---------------------------------


@needs_archive
def test_a_record_carrying_a_digest_outside_its_digest_fields_is_a_leak():
    from . import run_eval

    run = archive_runs.ARCHIVE_RUNS["real_3a22c5"]
    digest = "a" * 64
    clean = {"runId": run.run_id, "archiveDigest": digest, "payloadHash": digest, "output": {}}
    leaky = {**clean, "output": {"summary": f"checksum {digest}"}}
    assert run_eval.archive_record_leaks(run, clean) == 0
    assert run_eval.archive_record_leaks(run, leaky) == 1


@needs_archive
def test_the_runner_refuses_when_the_archive_changed_after_preflight(monkeypatch, capsys):
    """The model must see the bytes preflight checked, not a later file."""
    from . import run_eval

    _forbid_model(monkeypatch, run_eval)
    real_preflight = run_eval.preflight_archive

    def preflight_then_pretend_changed(name):
        check = real_preflight(name)
        return {**check, "archiveDigest": "0" * 64}

    monkeypatch.setattr(run_eval, "preflight_archive", preflight_then_pretend_changed)
    monkeypatch.setattr("sys.argv", ["run_eval", "--case", "real3a22c5", "--yes"])
    assert run_eval.main() == 2
    assert "사전 검증 뒤 압축 파일이 바뀌어" in capsys.readouterr().out


# --- 12. LOW risks L-d / L-e / L-f and the run-mode assumption (2026-11-15) ------
#
# Synthetic sample names and synthetic paths only. Nothing here prints, or
# asserts against, the real archive's sample.

def count_paths(text: str) -> int:
    from .real_runs import count_paths as real_count_paths

    return real_count_paths(text)

_PATHS_THAT_MUST_COUNT = [
    r"C:\Users\someone\x.bed",
    json.dumps(r"C:\Users\someone\x.bed"),
    "D:/data/x.bed",
    r"\\fileserver\share\x.bed",
    json.dumps(r"\\fileserver\share\x.bed"),
    "/home/lab/run/x.bed",
    "/work/lab/run/x.bed",
    "/scratch/proj/x.bed",
    "/nfs/seq/run/x.bed",
    "/Volumes/disk/x.bed",
    "/private/var/folders/x",
    "~/runs/x.bed",
    "file:///home/lab/x.bed",
    '"\\/home\\/lab\\/x.bed"',  # JSON with escaped slashes (not produced by json.dumps)
    "/lab+private/run",  # Codex review r1: punctuation in a segment
    "/srv/a@b/c",
    "/lab+private<path>",  # Codex review r2: fragment the app redactor leaves
]

_TEXT_THAT_MUST_NOT_COUNT = [
    "see https://docs.example.org/page/sub",
    "PASS/FAIL",
    "<path>/x.bed",
    "00_input_validation/resource_validation.txt",
    "ratio 3:1 and a/b",
    "2026/11/15",
    "n/a",
    "step:00_input_validation",
    "+/- 5%",
    "A/B/C test",
    "Compare /(A+B)/(C+D) with the reference ratio",  # Codex review r2
    "/**PASS**/**FAIL**",
    "missing or empty: <path>",
    "mg/dL/day",
]


@pytest.mark.parametrize("text", _PATHS_THAT_MUST_COUNT)
def test_an_absolute_path_in_any_common_form_is_counted(text):
    assert count_paths(text) >= 1


@pytest.mark.parametrize("text", _TEXT_THAT_MUST_NOT_COUNT)
def test_ordinary_text_and_urls_are_not_counted_as_paths(text):
    assert count_paths(text) == 0


def test_a_listed_literal_is_found_also_in_its_json_escaped_form(tmp_path):
    archive = _write_archive(tmp_path / "a.tar.gz", _valid_files())
    run = _syn_run(archive)
    loaded = archive_runs.load(run)
    literal = r"lab\SYN_WORKDIR"  # no drive letter: only the literal list can catch it
    text = json.dumps({"detail": f"left in {literal}"})
    assert literal not in text  # JSON doubled the backslash
    assert archive_runs.count_leaks(text, run, extra=[literal], loaded=loaded) >= 1


# L-e: terminal output


def _synthetic_record(detail: str) -> dict:
    return {
        "case": "synthetic",
        "invocationStatus": "invoked",
        "models": ["m"],
        "durationMs": 1,
        "available": True,
        "evaluation": {
            "results": [{"name": "synthetic-check", "outcome": "fail", "detail": detail}],
            "deterministicPassed": False,
        },
        "humanReview": {"items": []},
    }


def test_masked_output_hides_the_sample_and_paths_on_the_terminal(capsys):
    from . import run_eval

    record = _synthetic_record("SYN_SAMPLE at C:\\data\\x.bam and /work/lab/y")
    with run_eval.masked_output(["SYN_SAMPLE"]):
        run_eval.print_report(record)
    out = capsys.readouterr().out
    assert "SYN_SAMPLE" not in out
    assert "C:\\data" not in out and "/work/lab" not in out
    assert "<redacted>" in out and "<path>" in out
    assert "synthetic-check" in out  # the report itself is still there


def _synthetic_failrun(monkeypatch, tmp_path, run_eval):
    """Swap the registered failed run for a synthetic one; skip preflight."""
    archive = _write_archive(tmp_path / "a.tar.gz", _valid_files())
    run = archive_runs.ArchiveRun(
        name="real_3a22c5", intent="합성", run_id=SYN_RUN, archive=archive
    )
    monkeypatch.setitem(archive_runs.ARCHIVE_RUNS, "real_3a22c5", run)
    digest = archive_runs.archive_digest(archive)
    fake_check = {
        "payloadHash": "0" * 64, "restorationsMatch": True, "variantRunDataMatch": True,
        "privacy": "pass", "privacyDetail": "-", "toolEvidenceMatches": True,
        "toolDiagnosisMatches": True, "toolDiagnosisDetail": "-", "answerKeyIsolated": True,
        "archiveDigest": digest, "parsedDigestMatchesFile": True, "archiveUnchanged": True,
    }
    monkeypatch.setattr(run_eval, "preflight_archive", lambda name: fake_check)
    monkeypatch.setattr("sys.argv", ["run_eval", "--case", "real3a22c5", "--yes"])
    return run


def test_the_runner_masks_an_archive_report_before_it_reaches_the_terminal(
    monkeypatch, tmp_path, capsys
):
    from . import run_eval

    _forbid_model(monkeypatch, run_eval)
    _synthetic_failrun(monkeypatch, tmp_path, run_eval)
    leaky = _synthetic_record("model wrote SYN_SAMPLE and /work/lab/SYN_SAMPLE.bam")
    monkeypatch.setattr(run_eval, "evaluate_archive", lambda name, **kw: leaky)

    assert run_eval.main() == 1  # deterministic failure, reported
    out = capsys.readouterr().out
    assert "SYN_SAMPLE" not in out
    assert "/work/lab" not in out
    assert "<redacted>" in out


def test_an_exception_during_an_archive_eval_prints_only_its_type(monkeypatch, tmp_path, capsys):
    from . import run_eval

    _forbid_model(monkeypatch, run_eval)
    _synthetic_failrun(monkeypatch, tmp_path, run_eval)

    def boom(name, **kw):
        raise RuntimeError("failed reading C:\\data\\SYN_SAMPLE.bam")

    monkeypatch.setattr(run_eval, "evaluate_archive", boom)
    assert run_eval.main() == 2
    out = capsys.readouterr().out
    assert "RuntimeError" in out
    assert "SYN_SAMPLE" not in out and "C:\\data" not in out


# L-f: restoring only inside the throwaway environment


def _point_config_at(monkeypatch, root: Path) -> None:
    monkeypatch.setattr(config, "RUNS_ROOT", root / "runs")
    monkeypatch.setattr(config, "JOBS_ROOT", root / "runs" / "_jobs")
    monkeypatch.setattr(config, "UPLOAD_ROOT", root / "uploads")
    monkeypatch.setattr(config, "DB_PATH", root / "app.db")
    monkeypatch.setattr(archive_runs.db, "_conn", None)


def _restorable_archive(tmp_path: Path) -> Path:
    """A synthetic run whose plan check PASSES, so a refusal comes from the
    isolation guard and not from an earlier check (Codex review r1)."""
    return _write_archive(
        tmp_path / "a.tar.gz",
        _files_with(b"[INFO] RUN FAILED at 00_input_validation\n", "failed", _NO_OPTIONAL),
    )


_GUARD = "격리된 임시 환경"  # every refusal message of _require_isolation()


def test_the_restorable_archive_really_restores_inside_isolation(tmp_path):
    """Positive control: without it the refusal tests below could pass for an
    unrelated reason."""
    archive = _restorable_archive(tmp_path)
    with archive_runs.materialise(_syn_run(archive)):
        row = run_scope.db.query_one("SELECT status FROM jobs WHERE job_id = ?", (SYN_RUN,))
        assert row["status"] == "DONE"


def test_restoring_outside_the_isolated_environment_is_refused(tmp_path, monkeypatch):
    """A direct call writes nothing -- not even into a harmless tmp dir."""
    archive = _restorable_archive(tmp_path)
    target = tmp_path / "not_isolated"
    _point_config_at(monkeypatch, target)
    with pytest.raises(archive_runs.ArchiveError, match=_GUARD):
        archive_runs.restore_into_current_config(_syn_run(archive))
    assert _files_under(target) == []


def test_config_repointed_inside_the_isolated_environment_is_refused(tmp_path, monkeypatch):
    archive = _restorable_archive(tmp_path)
    elsewhere = tmp_path / "elsewhere"
    with agent_cases.isolated_environment():
        _point_config_at(monkeypatch, elsewhere)
        with pytest.raises(archive_runs.ArchiveError, match=_GUARD):
            archive_runs.restore_into_current_config(_syn_run(archive))
        monkeypatch.undo()
    assert _files_under(elsewhere) == []


def test_a_stale_database_connection_is_refused(tmp_path, monkeypatch):
    """config can point at the temp dir while db._conn still holds another file."""
    import sqlite3

    archive = _restorable_archive(tmp_path)
    stale_path = tmp_path / "stale.db"
    stale = sqlite3.connect(stale_path)
    try:
        with agent_cases.isolated_environment():
            monkeypatch.setattr(archive_runs.db, "_conn", stale)
            with pytest.raises(archive_runs.ArchiveError, match=_GUARD):
                archive_runs.restore_into_current_config(_syn_run(archive))
            monkeypatch.undo()
        tables = stale.execute("SELECT name FROM sqlite_master").fetchall()
        assert tables == []
    finally:
        stale.close()


# The run-mode / plan assumption, checked against the run's own record


def _files_with(log: bytes, status: str, snapshot: dict | None) -> list:
    files = [m for m in _valid_files() if not m[0].name.endswith(("pipeline.log", "run_status.json"))]
    files.append(_member(f"{SYN_RUN}/status/run_status.json", json.dumps({"status": status}).encode()))
    files.append(_member(f"{SYN_RUN}/logs/pipeline.log", log))
    if snapshot is not None:
        files.append(
            _member(f"{SYN_RUN}/config/run_config.snapshot.json", json.dumps(snapshot).encode())
        )
    return files


_NO_OPTIONAL = {"optional_steps": {"filtering": False, "annotation": False, "intervar": False}}


def test_a_full_run_is_recognised_from_its_record(tmp_path):
    archive = _write_archive(
        tmp_path / "a.tar.gz",
        _files_with(b"[INFO] RUN FAILED at 00_input_validation\n", "failed", _NO_OPTIONAL),
    )
    loaded = archive_runs.load(_syn_run(archive))
    assert archive_runs.recorded_plan(loaded) == ("full", tuple(agent_cases.FULL_PLAN))
    # The snapshot is read to decide the plan, never written out.
    assert "config/run_config.snapshot.json" not in loaded.files


def test_a_check_only_run_is_recognised_and_a_full_declaration_refused(tmp_path):
    archive = _write_archive(
        tmp_path / "a.tar.gz",
        _files_with(b"[INFO] PRECHECK FAILED - see status\n", "check_only", None),
    )
    run = _syn_run(archive)  # declares run_mode="full" by default
    loaded = archive_runs.load(run)
    assert archive_runs.recorded_plan(loaded) == ("check_only", (STEP,))
    with pytest.raises(archive_runs.ArchiveError):
        with archive_runs.materialise(run, loaded=loaded):
            pass


def test_a_record_that_does_not_say_its_mode_is_refused(tmp_path):
    archive = _write_archive(tmp_path / "a.tar.gz", _files_with(b"[INFO] x\n", "failed", _NO_OPTIONAL))
    loaded = archive_runs.load(_syn_run(archive))
    with pytest.raises(archive_runs.ArchiveError):
        archive_runs.recorded_plan(loaded)


@needs_archive
@pytest.mark.parametrize("name", CASE_NAMES)
def test_the_declared_mode_and_plan_match_what_the_run_recorded(name):
    run = archive_runs.ARCHIVE_RUNS[name]
    assert archive_runs.recorded_plan(archive_runs.load(run)) == (run.run_mode, run.planned)


# --- 13. answer keys re-checked against the record (2026-11-15) ----------------
# Characterisation tests: they pin facts the answer keys rely on. Nothing about
# the record's text is printed; only counts and equalities are asserted.


@needs_archive
@pytest.mark.parametrize("name", CASE_NAMES)
def test_every_must_cite_ref_is_citable_once_the_step_is_opened(name):
    """mustCite refs must be ids the agent can actually cite: the payload's
    own refs, plus the evidenceId the step tool returns."""
    run = archive_runs.ARCHIVE_RUNS[name]
    expectations = json.loads(
        (Path(__file__).parent / "expectations" / f"{name}.json").read_text(encoding="utf-8")
    )
    with archive_runs.materialise(run) as explanation:
        _, allowed = contract.build_payload(explanation)
        evidence = read_step_evidence(run_scope.for_job(run.run_id), STEP).model_dump()
    citable = set(allowed) | {evidence["evidenceId"]}
    for spec in expectations["mustCite"]:
        assert spec["ref"] in citable, spec["name"]


@needs_archive
def test_b94559_records_one_bcftools_problem_at_two_vcf_checks():
    """Two different raw lines (two reference VCFs), identical once redacted,
    and one confirmed error in the key -- not two independent problems."""
    run = archive_runs.ARCHIVE_RUNS["real_b94559"]
    loaded = archive_runs.load(run)
    raw = [
        line
        for line in loaded.files["logs/pipeline.log"].decode("utf-8", "replace").splitlines()
        if "bcftools unavailable for" in line
    ]
    assert len(raw) == 2 and len(set(raw)) == 2
    with archive_runs.materialise(run, loaded=loaded):
        causes = read_step_evidence(run_scope.for_job(run.run_id), STEP).model_dump()[
            "resourceBundleDiagnosis"
        ]["causes"]
    texts = [c["evidenceText"] for c in causes if c["tool"] == "bcftools"]
    assert len(texts) == 2 and texts[0] == texts[1]  # the agent cannot tell them apart

    expectations = json.loads(
        (Path(__file__).parent / "expectations" / "real_b94559.json").read_text(encoding="utf-8")
    )
    bcftools_errors = [e for e in expectations["confirmedErrors"] if "bcftools" in e["what"]]
    assert len(bcftools_errors) == 1
    assert "duplicate-not-inflated" in {h["name"] for h in expectations["humanReview"]}


@needs_archive
def test_b94559_both_records_say_bcftools_was_not_found():
    """The basis for allowing the required_tools <-> bcftools link."""
    run = archive_runs.ARCHIVE_RUNS["real_b94559"]
    step = json.loads(archive_runs.load(run).files[f"status/steps/{STEP}.json"])
    tools_failure = [f for f in step["failures"] if f["code"] == "required_tools"]
    assert len(tools_failure) == 1 and "bcftools" in tools_failure[0]["message"]
    with archive_runs.materialise(run):
        causes = read_step_evidence(run_scope.for_job(run.run_id), STEP).model_dump()[
            "resourceBundleDiagnosis"
        ]["causes"]
    bcftools_causes = [c for c in causes if c["tool"] == "bcftools"]
    assert bcftools_causes  # all() over an empty list would pass vacuously
    assert all("'bcftools'" in c["evidenceText"] for c in bcftools_causes)


# --- 14. Codex review r1 (2026-11-15): guard leaves no trace outside --------------


def test_an_upload_root_outside_isolation_is_refused_and_not_created(tmp_path, monkeypatch):
    """db.connect() -> ensure_dirs() would mkdir UPLOAD_ROOT; the guard must
    refuse before anything is created there."""
    archive = _restorable_archive(tmp_path)
    outside = tmp_path / "outside_uploads"
    with agent_cases.isolated_environment():
        monkeypatch.setattr(config, "UPLOAD_ROOT", outside)
        with pytest.raises(archive_runs.ArchiveError, match=_GUARD):
            archive_runs.restore_into_current_config(_syn_run(archive))
        monkeypatch.undo()
    assert not outside.exists()


def test_a_path_with_a_space_is_masked_only_up_to_the_space():
    """Documented limit, pinned so it is not mistaken for coverage: a space ends
    the path token, so the part after it stays visible."""
    from .real_runs import mask_paths

    assert mask_paths("/data/my lab/x") == "<path> lab/x"


# --- 15. Codex review r2 (2026-11-15) -------------------------------------------


def test_an_oversized_member_test_limit_is_above_every_other_member():
    """Guards the fix above: the other synthetic members fit under the limit."""
    others = _valid_files()[:-1]
    limit = max(info.size for info, _ in others)
    assert all(info.size <= limit for info, _ in others)


def test_what_an_archive_eval_prints_while_running_is_masked(monkeypatch, tmp_path, capsys):
    """Item 7: output written during evaluate_archive (stdout or stderr) goes
    through the same masking as the report."""
    import sys as _sys

    from . import run_eval

    _forbid_model(monkeypatch, run_eval)
    _synthetic_failrun(monkeypatch, tmp_path, run_eval)

    def chatty(name, **kw):
        print("progress for SYN_SAMPLE at /work/lab/run")
        print("warning about SYN_SAMPLE", file=_sys.stderr)
        return _synthetic_record("ok")

    monkeypatch.setattr(run_eval, "evaluate_archive", chatty)
    run_eval.main()
    captured = capsys.readouterr()
    assert "SYN_SAMPLE" not in captured.out and "SYN_SAMPLE" not in captured.err
    assert "/work/lab" not in captured.out
    assert "<redacted>" in captured.out


def test_an_archive_record_is_labelled_as_archive_not_capture(capsys):
    """F3: no false 'capture manifest changed' warning for an archive record."""
    from . import run_eval

    record = {
        **_synthetic_record("ok"),
        "caseKind": "real",
        "source": "archive",
        "split": "dev",
        "payloadHash": "0" * 64,
        "archiveUnchanged": True,
    }
    run_eval.print_report(record)
    out = capsys.readouterr().out
    assert "capture" not in out
    assert "압축 파일" in out and "경고" not in out
