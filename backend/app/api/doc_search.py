"""Official-document search for a run (development log 26).

  GET  /api/jobs/{job_id}/doc-search   stored searches, newest first (max 10)
  POST /api/jobs/{job_id}/doc-search   run one search now, store it, return it

Model-free by construction: this router imports services/doc_search only,
which reads the run's own records and two local corpora. Nothing here reaches
services/explanation/llm or spawns a process, so it costs no Claude usage and
can be called freely (unlike POST /synthesis).

Status codes:
  400  malformed job id                (via jobs._load_job)
  404  no such job
  200  every search outcome, including "nothing searchable", "no corpus" and
       "run records unreadable" -- a search that found nothing is a result.
  500  the search could not be stored: the API serves stored searches only, so
       an unstored one is not returned as if it were.
"""

from __future__ import annotations

import logging
import sqlite3

from fastapi import APIRouter, HTTPException

from ..services.doc_search import engine, store
from ..services.doc_search.models import DocSearchList, DocSearchRun
from .jobs import _load_job

router = APIRouter(prefix="/api/jobs", tags=["doc-search"])
log = logging.getLogger(__name__)


@router.get("/{job_id}/doc-search", response_model=DocSearchList)
def list_doc_searches(job_id: str) -> DocSearchList:
    row = _load_job(job_id)
    return DocSearchList(runs=store.list_runs(row["job_id"]))


@router.post("/{job_id}/doc-search", response_model=DocSearchRun)
def create_doc_search(job_id: str) -> DocSearchRun:
    row = _load_job(job_id)
    record = engine.run_search(row)
    try:
        search_id = store.save(row["job_id"], record)
    except sqlite3.Error as exc:
        # The job id is not logged: operator logs elsewhere already tie errors
        # to jobs, and this message needs only the failure kind.
        log.warning("could not store document search: %s", type(exc).__name__)
        raise HTTPException(
            status_code=500,
            detail={"code": "searchNotRecorded", "message": "검색 기록을 저장하지 못했습니다."},
        ) from exc
    saved = store.get_run(search_id)
    assert saved is not None
    return saved
