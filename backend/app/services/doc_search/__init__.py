"""Official-document search for a run's recorded failures (development log 26).

Deterministic and model-free: nothing in this package imports the LLM
provider, spawns a process, or touches the network. It turns what the run
RECORDED (a classified resource cause, a failed step check, and the command
that check is known to run) into a search over two local corpora, keeps the
result as a search trace, and reads it back for the run page.

The four facts it keeps apart (and why most of them are null here):

    returnedBySearch   this search returned the item              -- recorded
    inAgentInput       the item was in an agent's input           -- not recorded
    readByModel        a model actually read it                   -- not recorded
    citedInAnswer      an answer cited it                         -- not recorded

No model runs on this path, so the last three are null ("not recorded"), never
false and never guessed.
"""
