"""MCP transport for this backend's agent tools.

A sibling of ``app/api`` rather than a part of it: both are adapters that
expose the same services to a different caller. ``api/`` speaks HTTP to a
browser; ``agent_mcp/`` speaks the Model Context Protocol to a model client.
Neither contains WES logic -- the reasoning about what a step means, and about
what may be said about it, lives in ``app/services``.

Nothing in the running FastAPI application imports this package. The synthesis
provider still runs with no tools at all; wiring this server to it is a
separate, later decision.
"""
