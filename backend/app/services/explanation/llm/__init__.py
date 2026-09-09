"""Model-backed synthesis, kept behind one thin provider seam.

    contract.py   what the model is given, what it may return, what it may cite
    prompt.py     the constant system instruction and the delimited data block
    provider.py   the only file that knows a subprocess exists
    synthesis.py  build input -> call provider -> validate -> result

Nothing outside this package imports `provider`. The route calls
`build_run_synthesis` and gets back a result that either has a synthesis or
says why it does not.
"""

from .synthesis import SynthesisResult, build_run_synthesis

__all__ = ["SynthesisResult", "build_run_synthesis"]
