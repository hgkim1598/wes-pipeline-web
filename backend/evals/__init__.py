"""Offline evaluation of the WES LLM synthesis.

Not collected by a bare `pytest`: pytest.ini sets `testpaths = app/tests`, so
nothing here runs unless it is named explicitly. That is the cost boundary --
`run_eval.py` is the only code in this repository that can spend subscription
usage outside a deliberate request.
"""
