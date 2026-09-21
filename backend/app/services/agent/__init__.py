"""Agent-facing projections of this backend's own readers.

Nothing in here reads the filesystem on its own. Every fact still comes from
the readers the HTTP API uses, so an agent and the screen can never disagree
about a run. What this package adds is the second decision the readers
deliberately do not make:

    a reader may read it        ->  services/step_reader.py
    a model may be told it      ->  services/agent/

Those are different questions. ``step_reader.read()`` returns run-relative
artifact paths and the pipeline's own metric strings because the frontend needs
them and the browser session already knows whose run it is looking at. A model
prompt is a different destination: it is quoted back to a user, may be logged
by the provider, and has no need to know the sample's name to explain what
happened to it. So this package re-states what leaves the building as an
explicit allowlist, the way explanation/llm/contract.py already does for the
synthesis payload.

The transport lives elsewhere (``app/agent_mcp``). Everything here is plain
Python and is tested by calling it.
"""
