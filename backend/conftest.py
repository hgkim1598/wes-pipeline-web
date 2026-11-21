"""Root conftest: covers app/tests and evals alike.

Installs the real-CLI guard before any test module is imported. No test may
start a program called `claude` or connect outside this machine, whatever PATH
says -- see app/tests/real_cli_guard.py and development log chapter 25.
"""

from app.tests import real_cli_guard

real_cli_guard.install("deny")

# The A/B comparison store holds frozen copies of backend/ (evals/ab_compare).
# Their test files are snapshots, not this tree's tests: never collect them.
collect_ignore_glob = ["evals/ab_store/*"]
