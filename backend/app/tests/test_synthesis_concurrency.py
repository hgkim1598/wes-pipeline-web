"""POST /synthesis: one model call per run at a time, and a bounded number overall.

A call can take minutes (WES_SYNTHESIS_TIMEOUT_SECONDS, twice with repair) and
counts against the subscription. The button is disabled while a request is
pending, but a second tab, a reload or a direct call is not: without a guard
the same run could be explained twice concurrently, paying twice for one answer
(log 61).

No real process: provider.run_structured is replaced by a fake that blocks
until the test releases it.
"""

from __future__ import annotations

import threading

import pytest

from .. import config
from ..services.explanation.llm import provider
from ..services.explanation.llm import synthesis as llm_synthesis


class BlockingProvider:
    def __init__(self) -> None:
        self.entered = threading.Event()
        self.release = threading.Event()
        self.calls = 0

    def __call__(self, **_ignored):
        self.calls += 1
        self.entered.set()
        assert self.release.wait(10), "test never released the provider"
        raise provider.ProviderError("timeout", "fake provider, released by the test")


@pytest.fixture
def blocking(monkeypatch):
    fake = BlockingProvider()
    monkeypatch.setattr(llm_synthesis.provider, "run_structured", fake)
    yield fake
    fake.release.set()


def _finished_job(make_job, run, run_id):
    job = make_job(run_id)
    run(job).as_completed_full()
    return job


def _post_in_background(client, job):
    box = {}

    def go():
        box["response"] = client.post(f"/api/jobs/{job}/synthesis")

    thread = threading.Thread(target=go)
    thread.start()
    return thread, box


def test_a_second_request_for_the_same_run_is_refused_while_one_runs(client, make_job, run, blocking):
    job = _finished_job(make_job, run, "wes-20261123-000001-aaaaaa")
    thread, first = _post_in_background(client, job)
    assert blocking.entered.wait(10)

    second = client.post(f"/api/jobs/{job}/synthesis")
    assert second.status_code == 409
    assert second.json()["detail"]["code"] == "synthesisInProgress"

    blocking.release.set()
    thread.join(10)
    assert first["response"].status_code == 200
    assert blocking.calls == 1  # the refused request never reached the provider


def test_the_overall_limit_refuses_another_run_while_full(client, make_job, run, blocking, monkeypatch):
    monkeypatch.setattr(config, "SYNTHESIS_MAX_CONCURRENT", 1)
    a = _finished_job(make_job, run, "wes-20261123-000002-bbbbbb")
    b = _finished_job(make_job, run, "wes-20261123-000003-cccccc")
    thread, _ = _post_in_background(client, a)
    assert blocking.entered.wait(10)

    other = client.post(f"/api/jobs/{b}/synthesis")
    assert other.status_code == 429
    assert other.json()["detail"]["code"] == "synthesisBusy"

    blocking.release.set()
    thread.join(10)
    assert blocking.calls == 1


def test_the_slot_is_freed_after_a_failure(client, make_job, run, monkeypatch):
    job = _finished_job(make_job, run, "wes-20261123-000004-dddddd")

    def fail(**_ignored):
        raise provider.ProviderError("usageLimit", "fake")

    monkeypatch.setattr(llm_synthesis.provider, "run_structured", fail)
    assert client.post(f"/api/jobs/{job}/synthesis").json()["available"] is False
    # Not 409: the failed request released its slot.
    assert client.post(f"/api/jobs/{job}/synthesis").status_code == 200


def test_the_slot_is_freed_after_an_unexpected_error(client, make_job, run, monkeypatch):
    job = _finished_job(make_job, run, "wes-20261123-000005-eeeeee")

    def boom(*_a, **_k):
        raise RuntimeError("unexpected")

    monkeypatch.setattr(llm_synthesis, "build_run_synthesis", boom)
    assert client.post(f"/api/jobs/{job}/synthesis").status_code == 500

    def fail(**_ignored):
        raise provider.ProviderError("usageLimit", "fake")

    monkeypatch.undo()
    monkeypatch.setattr(llm_synthesis.provider, "run_structured", fail)
    assert client.post(f"/api/jobs/{job}/synthesis").status_code == 200


def test_a_refused_early_request_takes_no_slot(client, make_job, run, blocking):
    # The not-finished refusal happens before the guard: it must not leave a slot taken.
    from ..services import worker
    job = make_job("wes-20261123-000006-ffffff", status=worker.RUNNING, run_mode="full")
    assert client.post(f"/api/jobs/{job}/synthesis").status_code == 409
    assert blocking.calls == 0


@pytest.mark.parametrize("raw", ["0", "-1", "two"])
def test_an_invalid_limit_is_a_configuration_error(raw):
    with pytest.raises(config.ConfigError):
        config.resolve_synthesis_max_concurrent(raw)


def test_the_default_limit_is_one():
    assert config.resolve_synthesis_max_concurrent(None) == 1
    assert config.resolve_synthesis_max_concurrent("3") == 3
