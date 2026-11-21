"""Evaluation-only A/B comparison of two code paths on the same run (see runner.py).

backend/app imports exactly one module of this package: `contract` (the state
and outcome rules), lazily, from api/eval_compare.py and only after that
router's access check. Nothing else in backend/app imports it; the app reads
only what the runner stored, and only when WES_EVAL_COMPARE=1.
"""
