"""Gate 8: a statement about this run must not rest on a document alone (log 27).

Gate 3 already decides WHICH document ids are citable: an id is allowed only if
this request's payload carried it (officialDocs, services/doc_search/
agent_input.py) or the step tool returned it (causeGuidance.officialDocs,
tools.credit). A document that was returned by a search but not selected, or
selected for some other request, fails gate 3 like any invented id.

What gate 3 cannot see is a valid document id used for the wrong kind of
statement. An excerpt is general knowledge about a tool; it cannot show that
something happened in THIS run. Two groups are, by contract, about this run:

    importantFindings  "only things present in the supplied diagnostics,
                       failures or checkSummary"
    limitations        "what this run's output does not establish", based on
                       the supplied limitations and grounding scope entries
                       (contract.SYNTHESIS_JSON_SCHEMA)

so an item there that cites a document must also cite a record of the run
(limitations added in log 29: a document-only limitation passed before). A
document may stand alone in nextChecks or uncertainties ("the manual
describes -h as ..."), where a general statement is the point.

Measured before the change (log 29): in the 24 recorded real answers, 67 of 76
limitations items already cite a run record and none cites a document, so no
recorded answer is newly rejected. `summary` carries no ids at all; whether it
presents an excerpt as a fact of the run is a human review item, not this gate.

Run records are the ids the payload mints from what the pipeline recorded
(`run:`, `dx:`, `fail:`, `lim:`) and the step tool's `step:` results. `src:`,
`concept:` and `term:` are this project's knowledge and do not count: a
finding resting on a document and a glossary entry still rests on no record.

The gate looks at ids only, never at wording: whether the sentence matches the
excerpt is not decided here (gate 7 and the eval cover what can be covered).
"""

from __future__ import annotations

from typing import Any

DOC_PREFIXES = ("doc:", "manual:")
RUN_RECORD_PREFIXES = ("run:", "dx:", "fail:", "lim:", "step:")


def is_doc_ref(ref: str) -> bool:
    return ref.startswith(DOC_PREFIXES)


def is_run_record(ref: str) -> bool:
    return ref.startswith(RUN_RECORD_PREFIXES)


# The groups whose items are statements about this run (see above).
RUN_BOUND_GROUPS = ("importantFindings", "limitations")


def find_doc_only_findings(answer: dict[str, Any]) -> list[dict[str, Any]]:
    """Items of RUN_BOUND_GROUPS citing a document and no run record."""
    out = []
    for group in RUN_BOUND_GROUPS:
        for index, item in enumerate(answer.get(group) or []):
            refs = list(item.get("evidenceRefs") or [])
            docs = [r for r in refs if is_doc_ref(r)]
            if docs and not any(is_run_record(r) for r in refs):
                out.append({"location": f"{group}.{index}", "refs": docs})
    return out


def cited_doc_refs(answer: dict[str, Any], groups: tuple[str, ...]) -> tuple[str, ...]:
    """Document ids an answer cites, in order of first appearance."""
    seen: list[str] = []
    for group in groups:
        for item in answer.get(group) or []:
            for ref in item.get("evidenceRefs") or []:
                if is_doc_ref(ref) and ref not in seen:
                    seen.append(ref)
    return tuple(seen)


__all__ = ["DOC_PREFIXES", "RUN_BOUND_GROUPS", "RUN_RECORD_PREFIXES", "cited_doc_refs",
           "find_doc_only_findings", "is_doc_ref", "is_run_record"]
