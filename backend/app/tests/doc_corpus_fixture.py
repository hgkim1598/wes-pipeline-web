"""Shared synthetic corpus fixture; no downloaded text is a test dependency."""

from pathlib import Path

import pytest

from app import config
from app.services.agent import doc_retrieval

SYNTHETIC_CORPUS = Path(__file__).with_name("fixtures") / "doc_passages.synthetic.json"


def clear_store() -> None:
    # Close only an index this cache has already created; clearing must not
    # itself load the real corpus or allocate a new connection.
    if doc_retrieval._index.cache_info().currsize:
        doc_retrieval._index().close()
    doc_retrieval._index.cache_clear()
    doc_retrieval._store.cache_clear()


@pytest.fixture
def synthetic_passages(monkeypatch):
    clear_store()
    monkeypatch.setattr(config, "DOC_PASSAGE_KNOWLEDGE", SYNTHETIC_CORPUS)
    yield
    clear_store()
