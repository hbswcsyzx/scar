"""Explain why candidate decisions did not become transformations.

The regular candidate reports intentionally keep discovery separate from
selection.  That makes a report with many ``REJECT`` records hard to read,
though: a proven intervening write, an incomplete effect contract and a
missing cost measurement are materially different outcomes.  This module is
an audit projection over an existing report.  It does not change a decision
and it never treats an unknown obligation as a proven negative.
"""
from __future__ import annotations

from collections import Counter
from pathlib import Path
from typing import Any, Iterable, Mapping
import json


_UNKNOWN = "UNKNOWN"
_DISPROVEN = "DISPROVEN"
_PROVEN = "PROVEN"


def _obligations(candidate: Mapping[str, Any]) -> list[Mapping[str, Any]]:
    return [item for item in candidate.get("proof_obligations", [])
            if item.get("required", True)]


def _root_cause(obligation: Mapping[str, Any]) -> str:
    """Map one proof obligation to a stable, generic audit category."""
    name = str(obligation.get("name", "")).lower()
    text = " ".join(str(obligation.get(key, ""))
                     for key in ("reason", "claim", "details")).lower()
    if name in {"same_input_versions", "same_read_versions"}:
        return ("input_evidence_missing" if obligation.get("status") == _UNKNOWN
                else "input_versions_changed")
    if "effect" in name or "effect" in text:
        return "effect_completeness_missing" if obligation.get("status") == _UNKNOWN else "visible_effect"
    if "intervening" in name or "write" in name:
        if obligation.get("status") == _DISPROVEN:
            return "intervening_write_observed"
        return "intervening_write_evidence_missing"
    if any(token in name or token in text
           for token in ("consumer", "ordering", "happens_before", "wait")):
        return "consumer_or_ordering_evidence_missing"
    if any(token in name or token in text
           for token in ("allocation", "alias", "lifetime", "buffer")):
        return "allocation_alias_lifetime_evidence_missing"
    if "cost" in name or "profitable" in name or "cost" in text:
        return "cost_measurement_missing" if obligation.get("status") == _UNKNOWN else "unprofitable"
    if "backend" in name or "backend" in text:
        return "backend_or_selection_policy"
    if obligation.get("status") == _UNKNOWN:
        return "other_evidence_gap"
    if obligation.get("status") == _DISPROVEN:
        return "other_proven_blocker"
    return "other"


def _classify(candidate: Mapping[str, Any]) -> tuple[str, list[str]]:
    obligations = _obligations(candidate)
    causes = sorted({_root_cause(item) for item in obligations
                     if item.get("status") in {_UNKNOWN, _DISPROVEN}})
    if any(item.get("status") == _DISPROVEN for item in obligations):
        return "PROVEN_BLOCKER", causes
    if any(item.get("status") == _UNKNOWN for item in obligations):
        return "EVIDENCE_GAP", causes
    if str(candidate.get("decision", "")).lower() == "accepted":
        return "ACCEPTED", causes
    return "POLICY_OR_UNCLASSIFIED", causes


def audit_candidates(candidates: Iterable[Mapping[str, Any]]) -> dict[str, Any]:
    """Return a machine-readable rejection audit for candidate dictionaries.

    The returned counts intentionally preserve the event-level and graph-level
    candidate views when the caller supplies both.  A candidate can have more
    than one root cause; ``root_causes`` therefore is not expected to sum to
    ``candidates``.
    """
    records: list[dict[str, Any]] = []
    disposition = Counter()
    kinds = Counter()
    root_causes = Counter()
    obligations = Counter()
    for index, candidate in enumerate(candidates):
        disposition_name, causes = _classify(candidate)
        disposition[disposition_name] += 1
        kind = str(candidate.get("kind", "UNKNOWN"))
        kinds[kind] += 1
        root_causes.update(causes)
        required = _obligations(candidate)
        for item in required:
            obligations[(str(item.get("category", "UNKNOWN")),
                         str(item.get("name", "UNKNOWN")),
                         str(item.get("status", "UNKNOWN")))] += 1
        records.append({
            "candidate_index": index,
            "kind": kind,
            "code_id": candidate.get("code_id"),
            "decision": candidate.get("decision"),
            "disposition": disposition_name,
            "root_causes": causes,
            "supporting_events": list(candidate.get("supporting_events", [])),
            "expected_savings_ns": candidate.get("expected_savings_ns"),
            "proof_obligations": [dict(item) for item in required],
        })
    return {
        "schema": "scar.rejection_audit",
        "schema_version": 1,
        "candidates": len(records),
        "disposition": dict(sorted(disposition.items())),
        "candidate_kinds": dict(sorted(kinds.items())),
        "root_causes": dict(sorted(root_causes.items())),
        "obligations": [
            {"category": category, "name": name, "status": status,
             "count": count}
            for (category, name, status), count in sorted(obligations.items())
        ],
        "records": records,
    }


def audit_report(report: Mapping[str, Any]) -> dict[str, Any]:
    """Audit an ``analyze`` JSON report, retaining event/graph view labels."""
    views: list[dict[str, Any]] = []
    all_candidates: list[Mapping[str, Any]] = []
    for view_name in ("opportunities", "graph_opportunities"):
        candidates = list(report.get(view_name, []))
        view = audit_candidates(candidates)
        view["view"] = view_name
        views.append(view)
        all_candidates.extend(candidates)
    result = audit_candidates(all_candidates)
    result["views"] = views
    result["source_status"] = report.get("status", "UNKNOWN")
    result["warning"] = (
        "An evidence gap is not proof that the candidate is illegal; a proven "
        "blocker is a different result."
    )
    return result


def audit_path(path: str | Path) -> dict[str, Any]:
    """Load and audit an analysis report from disk."""
    with Path(path).open(encoding="utf-8") as handle:
        return audit_report(json.load(handle))


__all__ = ["audit_candidates", "audit_report", "audit_path"]
