"""`python -m app.agent_mcp` -- the stdio entry point. See server.main()."""

from __future__ import annotations

import sys

from .server import main

if __name__ == "__main__":
    sys.exit(main())
