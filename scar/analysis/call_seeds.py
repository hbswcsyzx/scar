"""Resolve compact, observed Python code entries to current source seeds.

The scanner checks every raw record, including reference tokens, but this
consumer retains only one count and two anchors per entered (process, code).
Source matches identify possible source seeds; they establish neither the
actual function environment nor caller, data or effect relationships.
"""
from __future__ import annotations

from dataclasses import dataclass
import json
from pathlib import Path

from scar.analysis.call_edges import _Sources
from scar.analysis.call_trace_reader import scan_call_trace
from scar.ir.program.call_edges import (
    CallEdgeBudget, CallEdgeIssue, CallEdgeIssueKind, FrameEntry, FrameExit,
)
from scar.ir.program.call_seeds import (
    CallSourceSeedModel, EnteredCodeGroup, SeedCollectionMetadata,
)
from scar.ir.record_codec import decode


def _require(condition, detail):
    if not condition:
        raise ValueError(detail)


def _canonical(value):
    return json.dumps(value, sort_keys=True, ensure_ascii=False,
                      separators=(",", ":"), allow_nan=False)


class _EnteredCodeSink:
    """Keep no event, local, argument, path or reference vectors."""

    def __init__(self):
        self._groups = {}

    def entry(self, value: FrameEntry) -> None:
        key = value.invocation.process_id, value.code
        old = self._groups.get(key)
        self._groups[key] = EnteredCodeGroup(
            *key, 1 if old is None else old.count + 1,
            value.invocation if old is None else old.first_invocation,
            value.invocation,
            value.anchor if old is None else old.first_anchor,
            value.anchor,
        )

    def exit(self, value: FrameExit) -> None:
        pass

    def abort(self) -> None:
        self._groups.clear()

    def groups(self):
        return tuple(group for key, group in sorted(self._groups.items()))


@dataclass(frozen=True)
class CallSourceSeedReport:
    model: CallSourceSeedModel

    def __post_init__(self):
        _require(isinstance(self.model, CallSourceSeedModel), "source seeds require a typed model")

    def summary(self):
        return self.model.summary()

    def eligible_groups(self):
        return self.model.eligible_groups()

    def eligible_code_links(self):
        return self.model.eligible_code_links()

    def to_dict(self):
        return {
            "schema": "scar.call-source-seeds", "schema_version": 1,
            "model": self.model.to_dict(), "summary": self.summary(),
            "target_executed_by_resolver": False,
            **self.model.authority_flags(),
        }

    @classmethod
    def from_dict(cls, document, *, verification_budget=CallEdgeBudget()):
        """Independently rescan raw inputs and recompile current source.

        A document can lower its budgets, but cannot raise the verifier's
        independent ceilings. No serialized seed or summary is trusted.
        """
        _require(isinstance(verification_budget, CallEdgeBudget),
                 "source seed replay requires a typed independent verifier budget")
        flags = {
            "target_executed_by_resolver", "caller_connections_established",
            "data_connections_established", "effects_established",
            "function_environment_established", "transformation_authorized",
        }
        _require(type(document) is dict and set(document) == {
            "schema", "schema_version", "model", "summary", *flags},
            "source seed report fields mismatch")
        _require(document["schema"] == "scar.call-source-seeds"
                 and type(document["schema_version"]) is int
                 and document["schema_version"] == 1,
                 "source seed report schema/version mismatch")
        _require(all(document[name] is False for name in flags),
                 "source seed reports cannot establish execution or connection authority")
        _require(type(document["model"]) is dict, "source seed model must be an object")
        # Check the small budget record before decoding the remaining model or
        # opening any raw/source file.
        budget = decode(CallEdgeBudget, document["model"].get("budget"))
        for name in budget.__dataclass_fields__:
            _require(getattr(budget, name) <= getattr(verification_budget, name),
                     "source seed report exceeds independent verifier budget: " + name)
        model = CallSourceSeedModel.from_dict(document["model"])
        rebuilt = read_call_source_seeds(model.trace_directory, model.project_root, budget=budget)
        _require(_canonical(rebuilt.to_dict()) == _canonical(document),
                 "source seeds differ from current raw trace/source replay")
        return rebuilt


def read_call_source_seeds(trace, project_root, *, budget=CallEdgeBudget()):
    """Read bounded collector records and resolve only actually entered codes.

    This does not execute project code, build a full call report, or construct
    reference routes. A code fingerprint match without a unique source
    definition remains in the report but is not an eligible source seed.
    """
    _require(isinstance(budget, CallEdgeBudget), "source seeds require a typed replay budget")
    root = Path(project_root).resolve()
    _require(root.is_dir(), "project root must be a directory")
    sink = _EnteredCodeSink()
    scanned = scan_call_trace(trace, root, budget, sink=sink)
    groups = sink.groups()
    captures = {(capture.process_id, capture.code.key): capture.code for capture in scanned.captures}
    sources = _Sources(root, budget, inventory=None)
    issues = list(scanned.issues)
    descriptors = {}
    for group in groups:
        captured = captures.get((group.process_id, group.code))
        if captured is None:
            issues.append(CallEdgeIssue(
                CallEdgeIssueKind.MISSING_CODE,
                "entered code has no captured descriptor in its process",
                group.first_anchor,
            ))
        else:
            descriptors[group.code] = captured
    code_links = tuple(sources.code(descriptors[key]) for key in sorted(descriptors))
    return CallSourceSeedReport(CallSourceSeedModel(
        scanned.directory, str(root), budget, scanned.files, scanned.captures,
        groups, code_links,
        tuple(SeedCollectionMetadata.from_metadata(meta) for meta in scanned.metadata),
        tuple(issues),
    ))


__all__ = ["CallSourceSeedReport", "read_call_source_seeds"]
