"""Turn a run's recorded failures into document searches. No model, no process.

    recorded facts ----------------------------> SearchInput (one per distinct failure)
      resource cause: kind, tool, rule -> command (commands.py), redacted sentence
      failed/warned step check with a known command: family, command
                         |
             +-----------+------------------------------+
             | curated excerpts                         | full manual (optional)
             | key: cause kind (exact, as the agent's   | only when the input's tool is the
             | tool does; doc_retrieval.retrieve)       | manual's tool and a subcommand is known
             |                                          |   1. option lookup in that command's section
             |                                          |   2. FTS5 bm25 over every chunk, the
             |                                          |      command's own section first
             +-----------+------------------------------+
                         v
            hits with a STRUCTURAL relation (filed under the kind / same command
            section / other command section / general section) -- never a score

Nothing here decides which document "explains" the failure. A hit is a
candidate the user can read; how it relates to the run is stated from the
document's structure and the recorded command only.

A corpus that does not apply is skipped with a recorded reason, and a
recorded observation that cannot become a query is listed as excluded with
its reason, so the trace says what was NOT searched as well as what was.
"""

from __future__ import annotations

import hashlib
import re
import time
from dataclasses import dataclass, field
from pathlib import Path
from typing import Any, Protocol

from pydantic import ValidationError

from app import config, db
from app.services import resource_bundle_diagnosis, step_reader
from app.services.agent import doc_retrieval
from app.services.agent.privacy import Redactor
from app.services.agent.run_scope import redactor_for_row

from . import commands, manual_corpus
from .models import CorpusInfo, CorpusSkip, ExcludedObservation, ObservedCommand, SearchInput

METHOD = "curated: cause-kind key, FTS5 order | manual: option lookup + FTS5 bm25 (same command section first)"
MAX_MANUAL_HITS = 5
MAX_QUERY_TERMS = 24

_WORD = re.compile(r"[A-Za-z][A-Za-z0-9]+")
_PLACEHOLDER = re.compile(r"<[a-z_]+>")
_SAFE_NAME = re.compile(r"^[A-Za-z][A-Za-z0-9_]{0,63}$")
_STOP = frozenset(
    "a an and are as at be by for from has have in is it its of on or that the this to was "
    "with not no but".split()
)

REASON_NOT_SEARCHABLE = "이 검사에 연결된 도구 명령이 파이프라인 코드에 없어 검색 질의를 만들지 않았습니다."
REASON_BUNDLE_UNPARSED = "리소스 검사 원인 문장을 분류하지 못해 검색 질의를 만들지 않았습니다."
REASON_CURATED_NOT_FILED = "이 종류에 등록된 공식 문서 발췌가 없습니다."
REASON_CURATED_CHECK = "등록 발췌는 리소스 검사 원인 종류로만 분류되어 있습니다."
REASON_MANUAL_OFF = "전체 매뉴얼 자료가 이 서버에 설정되어 있지 않습니다."
REASON_MANUAL_ERROR = "전체 매뉴얼 자료를 읽지 못했습니다."
REASON_MANUAL_NO_TOOL = "기록된 도구가 없어 매뉴얼을 검색하지 않았습니다(자유 검색은 기록되지 않은 원인을 제시할 수 있음)."
REASON_MANUAL_OTHER_TOOL = "기록된 도구({tool})가 이 매뉴얼의 도구({manual})와 달라 검색하지 않았습니다."
REASON_MANUAL_NO_SUB = "기록된 하위 명령이 없어 매뉴얼의 명령 절과 관계를 정할 수 없어 검색하지 않았습니다."


class Retriever(Protocol):
    """The seam for a different engine (vector, hybrid). Returns chunk ids, best first."""

    def search(self, terms: list[str], limit: int) -> list[str]: ...


@dataclass
class _Input:
    model: SearchInput
    evidence_text: str


@dataclass
class HitRecord:
    input_id: str
    corpus: str
    rank: int
    evidence_id: str
    relation: str
    matched_by: list[str]
    source_title: str
    source_url: str | None
    location: str
    version: str | None
    checked_on: str | None
    item_sha256: str


@dataclass
class SearchRecord:
    method: str
    duration_ms: int
    corpora: list[CorpusInfo]
    inputs: list[SearchInput]
    excluded: list[ExcludedObservation]
    hits: list[HitRecord] = field(default_factory=list)
    error_category: str | None = None


class RunRecordUnreadable(RuntimeError):
    pass


# --- inputs ------------------------------------------------------------------


def _terms(text: str, redactor: Redactor) -> list[str]:
    out: list[str] = []
    for word in _WORD.findall(_PLACEHOLDER.sub(" ", text).lower()):
        if word in _STOP or word in out or redactor.contains_literal(word):
            continue
        out.append(word)
    return out


def _command_model(cmd: commands.Command) -> ObservedCommand:
    return ObservedCommand(
        tool=cmd.tool,
        subcommand=cmd.subcommand,
        options=list(cmd.options),
        display=cmd.display(),
        recordedBy=cmd.recordedBy,
    )


def _query_terms(kind: str, cmd: commands.Command | None, tool: str | None,
                 evidence: list[str]) -> list[str]:
    seed: list[str] = []
    for word in [tool, cmd.subcommand if cmd else None, *kind.lower().split("_"), *evidence]:
        if word and len(word) >= 2 and word not in _STOP and word not in seed:
            seed.append(word)
    return seed[:MAX_QUERY_TERMS]


def collect_inputs(row: Any) -> tuple[list[_Input], list[ExcludedObservation]]:
    """Every distinct recorded failure that can become a query, plus the rest with reasons."""
    redactor = redactor_for_row(dict(row))
    run_dir = Path(row["run_dir"])
    planned: list[str] = db.loads(row["planned_steps"], [])
    inputs: list[_Input] = []
    excluded: list[ExcludedObservation] = []
    seen: dict[tuple, _Input] = {}

    def add(key: tuple, build) -> None:
        if key in seen:
            seen[key].model.occurrences += 1
            return
        item = build(f"in-{len(inputs) + 1}")
        seen[key] = item
        inputs.append(item)

    for step_id in planned:
        try:
            payload = step_reader.read(run_dir, planned, row["run_mode"], step_id)
        except step_reader.StepNotPlanned:
            continue
        except (OSError, ValueError) as exc:
            raise RunRecordUnreadable(type(exc).__name__) from exc
        if payload.get("status") not in ("failed", "warning"):
            continue
        checks = (payload.get("validation") or {}).get("results") or []

        diagnosis = resource_bundle_diagnosis.diagnose(run_dir, step_id, checks, redactor)
        if diagnosis is not None and diagnosis.state == "parsed":
            for cause in diagnosis.causes:
                cmd = commands.for_rule(cause.ruleId)
                tool = cause.tool or (cmd.tool if cmd else None)
                evidence = _terms(cause.evidenceText or "", redactor)

                def build(iid, cause=cause, cmd=cmd, tool=tool, evidence=evidence):
                    return _Input(
                        SearchInput(
                            inputId=iid, origin="resourceBundleCause", stepId=step_id,
                            kind=cause.kind, tool=tool, ruleId=cause.ruleId,
                            command=_command_model(cmd) if cmd else None,
                            queryTerms=_query_terms(cause.kind, cmd, tool, evidence),
                        ),
                        evidence_text=cause.evidenceText or "",
                    )

                add(("cause", step_id, cause.kind, tool, cause.ruleId, tuple(evidence)), build)

        for check in checks:
            status, name = check.get("status"), str(check.get("name") or "")
            if status not in ("FAIL", "WARN"):
                continue
            if name == "resource_bundle":
                if diagnosis is None or diagnosis.state != "parsed":
                    excluded.append(ExcludedObservation(
                        stepId=step_id, kind="resource_bundle", reason=REASON_BUNDLE_UNPARSED))
                continue
            mapped = commands.for_check(name)
            if mapped is None:
                safe = name if _SAFE_NAME.match(name) and not redactor.contains_literal(name) else "<withheld>"
                excluded.append(ExcludedObservation(stepId=step_id, kind=safe, reason=REASON_NOT_SEARCHABLE))
                continue
            family, cmd = mapped

            def build_check(iid, family=family, cmd=cmd):
                # The check's detail sentence is NOT used: it can name a file
                # or the sample. The family and the command are enough.
                return _Input(
                    SearchInput(
                        inputId=iid, origin="stepCheck", stepId=step_id, kind=family,
                        tool=cmd.tool, command=_command_model(cmd),
                        queryTerms=_query_terms(family, cmd, cmd.tool, []),
                    ),
                    evidence_text="",
                )

            add(("check", step_id, family), build_check)
    return inputs, excluded


# --- corpora -----------------------------------------------------------------


def _curated_info() -> tuple[CorpusInfo, bool]:
    try:
        items = doc_retrieval.all_passages()
    except (OSError, ValueError, ValidationError):
        return CorpusInfo(
            corpusId="curated", title="등록된 공식 문서 발췌", available=False,
            officialStatus="공식 문서에서 사람이 고른 발췌(wes_doc_passages.json)",
            note="발췌 파일을 읽지 못했습니다.",
        ), False
    note = None if items else "이 서버에는 발췌가 없습니다(공개 저장소에는 제3자 발췌를 넣지 않음)."
    return CorpusInfo(
        corpusId="curated", title="등록된 공식 문서 발췌", available=True, itemCount=len(items),
        officialStatus="공식 문서 원문 인용, 출처·확인일은 발췌마다 기록(wes_sources.json)",
        note=note,
    ), True


def _manual_path() -> Path | None:
    raw = config.DOC_MANUAL_CHUNKS
    if not raw:
        return None
    path = Path(raw)
    return path if path.is_absolute() else config.ROOT / path


def _manual_info() -> tuple[CorpusInfo, manual_corpus.ManualCorpus | None, str | None]:
    try:
        corpus = manual_corpus.load(_manual_path())
    except manual_corpus.ManualCorpusError:
        return CorpusInfo(
            corpusId="manual", title="전체 도구 매뉴얼", available=False,
            officialStatus="공식 매뉴얼 스냅샷(로컬 전용)", note=REASON_MANUAL_ERROR,
        ), None, REASON_MANUAL_ERROR
    if corpus is None:
        return CorpusInfo(
            corpusId="manual", title="전체 도구 매뉴얼", available=False,
            officialStatus="공식 매뉴얼 스냅샷(로컬 전용)", note=REASON_MANUAL_OFF,
        ), None, REASON_MANUAL_OFF
    return CorpusInfo(
        corpusId="manual", title=corpus.title, available=True, itemCount=len(corpus.order),
        excludedItems=corpus.excluded, version=corpus.version,
        snapshot=corpus.source_sha256[:12] or None,
        officialStatus="공식 매뉴얼 페이지를 받은 스냅샷. 재배포 허가가 없어 로컬에만 둠",
    ), corpus, None


# --- search --------------------------------------------------------------------


def _relation(chunk: manual_corpus.ManualChunk, subcommand: str) -> str:
    if chunk.section_command == subcommand:
        return "sameCommandSection"
    if chunk.section_command is not None:
        return "otherCommandSection"
    return "generalSection"


def _search_manual(item: SearchInput, corpus: manual_corpus.ManualCorpus,
                   retriever: Retriever | None = None) -> list[HitRecord]:
    cmd = item.command
    assert cmd is not None and cmd.subcommand
    found: dict[str, list[str]] = {}
    for cid in corpus.option_lookup(cmd.subcommand, tuple(cmd.options)):
        found.setdefault(cid, []).append("optionLookup")
    engine = retriever or corpus
    # FTS candidates from the recorded command's own section are taken before
    # those of other commands (log 27). Measured on the lab questions that match
    # this service's input (command known): chosen on dev, confirmed on test,
    # not significant at that size. bm25 order is kept within each group, and
    # nothing is dropped -- the others still fill the remaining places.
    ranked = engine.search(item.queryTerms, MAX_MANUAL_HITS * 4)
    same = [cid for cid in ranked if corpus.chunks[cid].section_command == cmd.subcommand]
    for cid in same + [cid for cid in ranked if cid not in same]:
        found.setdefault(cid, []).append("fts5")
    hits = []
    for rank, (cid, how) in enumerate(list(found.items())[:MAX_MANUAL_HITS], start=1):
        chunk = corpus.chunks[cid]
        hits.append(HitRecord(
            input_id=item.inputId, corpus="manual", rank=rank, evidence_id=f"manual:{cid}",
            relation=_relation(chunk, cmd.subcommand), matched_by=how,
            source_title=corpus.title, source_url=chunk.url or corpus.source_url,
            location=chunk.context or chunk.anchor, version=corpus.version, checked_on=None,
            item_sha256=chunk.body_sha256,
        ))
    return hits


def _search_curated(item: SearchInput, evidence_text: str) -> list[HitRecord]:
    hits = []
    for rank, p in enumerate(doc_retrieval.retrieve(item.kind, evidence_text), start=1):
        hits.append(HitRecord(
            input_id=item.inputId, corpus="curated", rank=rank, evidence_id=p.evidence_id,
            relation="filedUnderCauseKind", matched_by=["causeKindKey"],
            source_title=doc_retrieval.source_title(p), source_url=doc_retrieval.source_url(p),
            location=p.heading, version=p.toolVersion, checked_on=p.checkedOn,
            item_sha256=hashlib.sha256(p.quote.encode("utf-8")).hexdigest(),
        ))
    return hits


def run_search(row: Any) -> SearchRecord:
    started = time.monotonic()
    curated_info, curated_ok = _curated_info()
    manual_info, manual, manual_skip = _manual_info()
    corpora = [curated_info, manual_info]
    try:
        inputs, excluded = collect_inputs(row)
    except RunRecordUnreadable:
        return SearchRecord(METHOD, int((time.monotonic() - started) * 1000), corpora, [], [],
                            error_category="runRecordUnreadable")

    hits: list[HitRecord] = []
    for item in inputs:
        m = item.model
        if not curated_ok:
            m.skipped.append(CorpusSkip(corpus="curated", reason=curated_info.note or ""))
        elif m.origin != "resourceBundleCause":
            m.skipped.append(CorpusSkip(corpus="curated", reason=REASON_CURATED_CHECK))
        else:
            found = _search_curated(m, item.evidence_text)
            if not found:
                m.skipped.append(CorpusSkip(corpus="curated", reason=REASON_CURATED_NOT_FILED))
            hits += found

        if manual is None:
            m.skipped.append(CorpusSkip(corpus="manual", reason=manual_skip or REASON_MANUAL_OFF))
        elif not m.tool:
            m.skipped.append(CorpusSkip(corpus="manual", reason=REASON_MANUAL_NO_TOOL))
        elif m.tool != manual.tool:
            m.skipped.append(CorpusSkip(
                corpus="manual", reason=REASON_MANUAL_OTHER_TOOL.format(tool=m.tool, manual=manual.tool)))
        elif not (m.command and m.command.subcommand):
            m.skipped.append(CorpusSkip(corpus="manual", reason=REASON_MANUAL_NO_SUB))
        else:
            hits += _search_manual(m, manual)

    error = None
    if not curated_ok and manual is None:
        error = "noCorpusAvailable"
    return SearchRecord(
        method=METHOD,
        duration_ms=int((time.monotonic() - started) * 1000),
        corpora=corpora,
        inputs=[i.model for i in inputs],
        excluded=excluded,
        hits=hits,
        error_category=error,
    )


__all__ = ["METHOD", "HitRecord", "Retriever", "SearchRecord", "collect_inputs", "run_search"]
