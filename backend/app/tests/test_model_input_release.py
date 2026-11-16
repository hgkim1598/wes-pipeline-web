"""What the agent's step tool may hand an external model (fail-closed release).

`Redactor.text` replaces what its patterns recognise. `Redactor.release` is
what the model path uses: the same text, then a check for anything that still
looks like part of a path. A word that fails the check is replaced as a whole;
a string that still fails after that is not sent at all.

Every value here is synthetic. The private names are long and distinctive, and
the leak checks look for ANY 4-character piece of them, so a test cannot pass
because only part of a name was left (the weakness Codex review r4 found in an
earlier truncation test).
"""

from __future__ import annotations

import json
import time

import anyio
import pytest
from mcp import Client

from app.agent_mcp import server as mcp_server
from app.services.agent import privacy, run_scope
from app.services.agent.privacy import WITHHELD, Redactor
from app.services.agent.step_evidence import read_step_evidence

PRIVATE = "SYNTHPRIVATEQX"  # stands in for a folder or sample name
FAMILY = "SYNFAMILYZK"
RUN_ID = "wes-20261115-101010-abc123"
SAMPLE = "SYNSAMPLE_S7"


def _pieces(secret: str, size: int = 4) -> set[str]:
    return {secret[i : i + size] for i in range(len(secret) - size + 1)}


def assert_no_piece(text: str, *secrets: str) -> None:
    lowered = text.lower()
    for secret in secrets:
        left = sorted(p for p in _pieces(secret.lower()) if p in lowered)
        assert not left, f"fragment of a private value survived: {left}"


def test_the_fragment_check_itself_catches_a_partial_name():
    """Guard: the helper must fail on a 4-character remnant."""
    with pytest.raises(AssertionError):
        assert_no_piece("<path>VATE", PRIVATE)
    assert_no_piece("<path> ENOENT", PRIVATE)


# --- the four known routes, exact output ---------------------------------------


@pytest.mark.parametrize(
    ("raw", "expected"),
    [
        # a space inside a folder name: the part after the space is the same path
        (f"/data/{PRIVATE} {FAMILY}/x", "<path>"),
        (f"/data/{PRIVATE} {FAMILY}/x.bed: ENOENT", "<path> <path>: ENOENT"),
        # one rooted segment
        (f"/{PRIVATE}", "<path>"),
        (f"missing /{PRIVATE}: ENOENT", "missing <path>: ENOENT"),
        (f"C:\\tmp\\x /{PRIVATE}", "<path> <path>"),
        (f"<path>/{PRIVATE}", "<path>"),
        # a name glued in front of a relative path by ")"
        (f"{PRIVATE})family/x.bed", "<path>"),
        # URL-encoded separators
        (f"{PRIVATE}%2Ffamily%2Fx.bed", "<path>"),
        (f"/srv%2F{PRIVATE}%2Fx", "<path>"),
        (f"{PRIVATE}%5c{FAMILY}%5cx.bed", "<path>"),
        # encoded twice: not decoded; the check refuses "%252F" itself, with or
        # without a filename after it (Codex review r5)
        (f"{PRIVATE}%252F{FAMILY}%252Fx.bed not found", "<path> not found"),
        (f"{PRIVATE}%252F{FAMILY} not found", "<path> not found"),
        # look-alike separators (Codex review r5)
        (f"{PRIVATE}∕{FAMILY}∕x.bed", "<path>"),
        (f"{PRIVATE}／{FAMILY} failed", "<path> failed"),
        (f"/srv＼{PRIVATE}＼x", "<path>"),
        # a name glued in front of a URL (Codex review r5)
        (f"{PRIVATE})https://h.example/a", "<path>"),
        # a combining mark ends the name class; the word is still refused
        (f"lab\u0301{PRIVATE}/x.bed missing (ENOENT)", "<path> missing (ENOENT)"),
        # a refused word keeps the error the tool wrote after it
        (f"open lab\u0301{PRIVATE}/x.bed:ENOENT", "open <path>:ENOENT"),
        (f"(lab\u0301{PRIVATE}/x.bam:12:34)", "(<path>:12:34)"),
        # URLs
        (f"see https://{PRIVATE}.example/a/b)", "see <url>)"),
        # a digest welded to a name
        (f"{PRIVATE}_{'ab' * 20}", "<path>"),
    ],
)
def test_known_routes_are_closed(raw, expected):
    out = Redactor().release(raw)
    assert out == expected
    assert_no_piece(out, PRIVATE, FAMILY)


# --- what must still reach the model --------------------------------------------


@pytest.mark.parametrize(
    "kept",
    [
        "chr1:12345-67890",
        "glucose 5 mg/dL",
        "3/4 lanes passed",
        "+/- 2 reads",
        "PASS / FAIL",
        "PASS/WARN",
        "reads/sec=1.5",
        "exit code 127",
        "samtools: command not found",
        "No such file or directory (ENOENT)",
        "BAM, VCF and BED inputs are present",
        "00_input_validation failed at resource_bundle",
        "필수 도구 gatk 가 PATH 에 없습니다",
        "<path> was not readable",
    ],
)
def test_ordinary_diagnostic_text_is_released_unchanged(kept):
    assert Redactor().release(kept) == kept


@pytest.mark.parametrize(
    ("raw", "expected"),
    [
        # the error after the path is the useful part and stays
        ("/srv/a/b.bam:12:34 truncated file", "<path>:12:34 truncated file"),
        ("failed /srv/a/b:ENOENT", "failed <path>:ENOENT"),
        # an option name before "=" is the tool's vocabulary and stays
        ("INPUT=/srv/a/b.bam", "INPUT=<path>"),
        # a known sample is replaced, the code around it kept
        (f"sort_order_{SAMPLE}.L001 WARN", "sort_order_<sample>.L001 WARN"),
    ],
)
def test_the_error_around_a_path_survives(raw, expected):
    redactor = Redactor(literals=((SAMPLE, "<sample>"),))
    assert redactor.release(raw) == expected


# --- a known identifier is never split or altered by a rule (Codex review r5) -----


@pytest.mark.parametrize(
    ("literal", "raw", "expected"),
    [
        # An identifier that interacts with a shape rule: the literals-first
        # and literals-last results disagree, so the string is not sent.
        # decoding "%2F" changed the literal before it was matched (r5 F1)
        ("SYNTH%2FPRIVATEQX", "SYNTH%2FPRIVATEQX failed", WITHHELD),
        # the filename rule cut the literal in two (r5 F2)
        (f"{PRIVATE}.bam-{FAMILY}", f"{PRIVATE}.bam-{FAMILY} failed", WITHHELD),
        # a mark hid the "/" that made the enclosing path a path (r6)
        ("SYNTH/", f"SYNTH/{PRIVATE}/{FAMILY}", WITHHELD),
        # a mark broke a digest into a too-short hex run (r6)
        ("a" * 32, "a" * 32 + "b" * 31, WITHHELD),
        # a literal holding a separator, written encoded
        ("SYNTH/PRIVATEQX", "SYNTH%2FPRIVATEQX failed", "<sample> failed"),
        # inside a path the literal goes with the path, as before
        (PRIVATE, f"/srv/runs/{PRIVATE}/x.bam missing", "<path> missing"),
        (PRIVATE, f"sort_order_{PRIVATE}.L001", "sort_order_<sample>.L001"),
    ],
)
def test_a_known_literal_survives_no_rule(literal, raw, expected):
    out = Redactor(literals=((literal, "<sample>"),)).release(raw)
    assert out == expected
    assert_no_piece(out, PRIVATE, FAMILY)


def test_the_scan_cut_does_not_split_a_literal_after_case_expanding_text():
    """"İ".lower() is two characters, so offsets in a lower-cased copy are not
    offsets in the string. The literal sat across MAX_SCAN in the original."""
    head = "/" + "İ" * 1990 + "/" + "b" * 1990 + "|" + "x" * 12
    assert len(head) < privacy.MAX_SCAN < len(head) + len(PRIVATE)
    out = Redactor(literals=((PRIVATE, "<sample>"),)).release(head + PRIVATE + " tail")
    assert_no_piece(out, PRIVATE)
    assert out.endswith(" ...(truncated)")


def test_a_mark_shaped_string_from_the_producer_is_left_alone():
    """The mark tag is chosen per call to be absent from the input (r6): a
    producer-written "QZLIT0QZ" must not become a fabricated <sample>."""
    redactor = Redactor(literals=((SAMPLE, "<sample>"),))
    assert redactor.release("QZLIT7QZ and QZLIT0QZ failed") == "QZLIT7QZ and QZLIT0QZ failed"
    assert redactor.release(f"QZLIT0QZ {SAMPLE} failed") == "QZLIT0QZ <sample> failed"


def test_a_literal_that_looks_like_a_mark_tag_cannot_rewrite_marks():
    redactor = Redactor(literals=((SAMPLE, "<sample>"), ("QZLIT", "<run>")))
    assert redactor.release(f"{SAMPLE} QZLIT") == "<sample> <run>"


def test_metric_keys_use_the_same_case_rule_as_replacement():
    """"SYNTHİD".lower() is not what re.IGNORECASE matches (r6)."""
    kept, withheld = Redactor(literals=(("SYNTHİD", "<sample>"),)).metrics({"synthid": 1})
    assert kept == {} and withheld == 1


def test_an_empty_literal_is_ignored():
    assert Redactor(literals=(("", "<sample>"),)).release("exit code 1") == "exit code 1"


# --- fail-closed: what the rules miss is not sent ---------------------------------


def test_a_string_still_unsafe_after_word_masking_is_withheld(monkeypatch):
    """If the pattern stage misses everything, the check must still hold.

    The pattern stage (`_render`, both literal orders) is replaced by the
    identity, so nothing is masked by pattern; the release must then refuse
    the path-shaped word and, because the known sample is still present as a
    separate word, the string as a whole.
    """
    monkeypatch.setattr(Redactor, "_render", lambda self, value: (str(value), str(value)))
    redactor = Redactor(literals=((SAMPLE, "<sample>"),))

    assert redactor.release(f"/srv/{PRIVATE} failed") == "<path> failed"
    assert redactor.release(f"/srv/x for {SAMPLE}") == WITHHELD


def test_metric_strings_go_through_the_same_release():
    kept, withheld = Redactor().metrics(
        {"assembly": "GRCh38", "bundle_id": f"/{PRIVATE}", "filter_preset": "lab\u0301/x"}
    )
    assert kept == {"assembly": "GRCh38"}
    assert withheld == 2


# --- the tool path: the release is what the model actually receives ---------------


def _nasty_run(builder):
    builder.step(
        "00_input_validation",
        status="failed",
        elapsed_seconds=3,
        checks=[
            {
                "name": "resource_bundle",
                "status": "FAIL",
                "detail": f"reference /data/{PRIVATE} {FAMILY}/genome.fa: ENOENT",
            },
            {"name": "target_bed", "status": "FAIL", "detail": f"missing /{PRIVATE}"},
            {
                "name": "samplesheet",
                "status": "PASS",
                "detail": "chr1:12345-67890 within target; 5 mg/dL",
            },
        ],
        warnings=[
            {
                "code": "SAMPLESHEET_INSIDE_RUN",
                "message": f"see {PRIVATE}%2F{FAMILY}%2Fsheet.csv",
                "impact": f"lab\u0301{PRIVATE}/x.bed was skipped",
                "can_continue": True,
            }
        ],
        failures=[
            {
                "code": "resource_bundle",
                "message": f"reference /data/{PRIVATE} {FAMILY}/genome.fa: ENOENT",
            }
        ],
    )
    builder.run_status(
        "failed",
        current_step="00_input_validation",
        steps=[
            {
                "step_id": "00_input_validation",
                "status": "failed",
                "exit_code": 1,
                "elapsed_seconds": 3,
                "warnings": 1,
                "failures": 2,
                "next_step_ready": False,
            }
        ],
    )


@pytest.fixture
def nasty_scope(make_job, run):
    _nasty_run(run(RUN_ID))
    job_id = make_job(
        RUN_ID, run_mode="full", planned=["00_input_validation"], sample_id=SAMPLE
    )
    return run_scope.for_job(job_id)


def test_the_mcp_tool_returns_no_fragment_and_keeps_the_errors(nasty_scope):
    server = mcp_server.build_server(nasty_scope)

    async def go():
        async with Client(server) as client:
            return await client.call_tool("get_step_detail", {"stepId": "00_input_validation"})

    result = anyio.run(go)
    body = json.dumps(result.structured_content, ensure_ascii=False)
    text_blocks = "\n".join(b.text for b in result.content if getattr(b, "text", None))

    for said in (body, text_blocks):
        assert_no_piece(said, PRIVATE, FAMILY)
        assert "\u0301" not in said
        assert "%2F" not in said
    # the diagnostic content is still there
    assert "ENOENT" in body
    assert "chr1:12345-67890" in body
    assert "mg/dL" in body
    assert "SAMPLESHEET_INSIDE_RUN" in body


def test_read_step_evidence_uses_the_release(nasty_scope):
    evidence = read_step_evidence(nasty_scope, "00_input_validation")
    assert [c.detail for c in evidence.checks] == [
        "reference <path> <path>: ENOENT",
        "missing <path>",
        "chr1:12345-67890 within target; 5 mg/dL",
    ]
    assert evidence.warnings[0].message == "see <path>"
    assert evidence.warnings[0].impact == "<path> was skipped"


# --- long inputs stay fast ------------------------------------------------------


@pytest.mark.parametrize(
    "raw",
    [
        "<path> " + "a" * 30000,
        "<path> a/" * 6000,
        "%2F" * 20000,
        "/a " * 15000,
        "x" + "/" * 30000,
        "https://" * 6000,
        ("<path>" + "a" * 50 + " ") * 800,
        "a" * 40000 + "<path>",
        "\\" + ":1" * 1990 + "X",
    ],
    ids=["word", "path-slash", "encoded", "rooted", "slashes", "urls", "glued", "tail", "colon-suffix"],
)
def test_release_is_fast_on_adversarial_input(raw):
    # Runtime and length only; what each shape becomes is pinned elsewhere.
    start = time.perf_counter()
    out = Redactor(literals=((SAMPLE, "<sample>"),)).release(raw)
    assert time.perf_counter() - start < 1.0
    assert len(out) <= privacy.MAX_TEXT + len(" ...(truncated)")
