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
from scar.ir.program.compilation import CallCompilationProfile
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
    compilation_profile: CallCompilationProfile = CallCompilationProfile.LEGACY_ZERO_FLAGS

    def __post_init__(self):
        _require(isinstance(self.model, CallSourceSeedModel), "source seeds require a typed model")
        _require(type(self.compilation_profile) is CallCompilationProfile,
                 "source seeds require a typed compilation profile")

    def summary(self):
        return self.model.summary()

    def eligible_groups(self):
        return self.model.eligible_groups()

    def eligible_code_links(self):
        return self.model.eligible_code_links()

    def to_dict(self):
        self.__post_init__()
        document = {
            "schema": "scar.call-source-seeds", "schema_version": (
                1 if self.compilation_profile is CallCompilationProfile.LEGACY_ZERO_FLAGS else 2),
            "model": self.model.to_dict(), "summary": self.summary(),
            "target_executed_by_resolver": False,
            **self.model.authority_flags(),
        }
        if self.compilation_profile is CallCompilationProfile.RECORDED_FUTURE_FLAGS:
            document["compilation_profile"] = self.compilation_profile.value
        return document

    @classmethod
    def from_dict(cls, document, *, verification_budget=CallEdgeBudget()):
        """Independently rescan raw inputs and recompile current source.

        A document can lower its budgets, but cannot raise the verifier's
        independent ceilings. No serialized seed or summary is trusted.
        """
        model = cls._decode_replay_input(document, verification_budget=verification_budget)
        profile = cls._compilation_profile(document)
        rebuilt = read_call_source_seeds(
            model.trace_directory, model.project_root, budget=model.budget,
            compilation_profile=profile,
        )
        _require(_canonical(rebuilt.to_dict()) == _canonical(document),
                 "source seeds differ from current raw trace/source replay")
        return rebuilt

    @staticmethod
    def _compilation_profile(document):
        """Decode the report policy without consulting any external input."""
        _require(type(document) is dict,
                 "source seed report must be an object")
        version = document.get("schema_version")
        _require(document.get("schema") == "scar.call-source-seeds"
                 and type(version) is int and version in (1, 2),
                 "source seed report schema/version mismatch")
        fields = {
            "schema", "schema_version", "model", "summary",
            "target_executed_by_resolver", "caller_connections_established",
            "data_connections_established", "effects_established",
            "function_environment_established", "transformation_authorized",
        }
        if version == 1:
            _require(set(document) == fields, "source seed report fields mismatch")
            return CallCompilationProfile.LEGACY_ZERO_FLAGS
        _require(set(document) == fields | {"compilation_profile"},
                 "source seed report fields mismatch")
        _require(type(document["compilation_profile"]) is str
                 and document["compilation_profile"] ==
                 CallCompilationProfile.RECORDED_FUTURE_FLAGS.value,
                 "source seed report compilation profile/version mismatch")
        return CallCompilationProfile.RECORDED_FUTURE_FLAGS

    @staticmethod
    def _decode_replay_input(document, *, verification_budget):
        """Check independent limits and structure before any raw/source I/O."""
        _require(isinstance(verification_budget, CallEdgeBudget),
                 "source seed replay requires a typed independent verifier budget")
        CallSourceSeedReport._compilation_profile(document)
        flags = {
            "target_executed_by_resolver", "caller_connections_established",
            "data_connections_established", "effects_established",
            "function_environment_established", "transformation_authorized",
        }
        _require(all(document[name] is False for name in flags),
                 "source seed reports cannot establish execution or connection authority")
        _require(type(document["model"]) is dict, "source seed model must be an object")
        # Check the small budget record before decoding the remaining model or
        # opening any raw/source file.
        budget = decode(CallEdgeBudget, document["model"].get("budget"))
        for name in budget.__dataclass_fields__:
            _require(getattr(budget, name) <= getattr(verification_budget, name),
                     "source seed report exceeds independent verifier budget: " + name)
        return CallSourceSeedModel.from_dict(document["model"])


def read_call_source_seeds(
    trace, project_root, *, budget=CallEdgeBudget(),
    compilation_profile=CallCompilationProfile.RECORDED_FUTURE_FLAGS,
):
    """Read bounded collector records and resolve only actually entered codes.

    This does not execute project code, build a full call report, or construct
    reference routes. A code fingerprint match without a unique source
    definition remains in the report but is not an eligible source seed.
    """
    return _read_call_source_seeds(
        trace, project_root, budget=budget, compilation_profile=compilation_profile,
    )


def _read_call_source_seeds(
    trace, project_root, *, budget, _source_workspace=None,
    compilation_profile=CallCompilationProfile.RECORDED_FUTURE_FLAGS,
):
    """Private composition shares locally prepared contexts, never report seeds."""
    _require(isinstance(budget, CallEdgeBudget), "source seeds require a typed replay budget")
    _require(type(compilation_profile) is CallCompilationProfile,
             "source seeds require a typed compilation profile")
    root = Path(project_root).resolve()
    _require(root.is_dir(), "project root must be a directory")
    sink = _EnteredCodeSink()
    scanned = scan_call_trace(trace, root, budget, sink=sink)
    groups = sink.groups()
    captures = {(capture.process_id, capture.code.key): capture.code for capture in scanned.captures}
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
    if _source_workspace is not None:
        _source_workspace.prime_sources(tuple(descriptors.values()))
    sources = _Sources(
        root, budget, inventory=None, _source_workspace=_source_workspace,
        compilation_profile=compilation_profile,
    )
    code_links = tuple(sources.code(descriptors[key]) for key in sorted(descriptors))
    return CallSourceSeedReport(CallSourceSeedModel(
        scanned.directory, str(root), budget, scanned.files, scanned.captures,
        groups, code_links,
        tuple(SeedCollectionMetadata.from_metadata(meta) for meta in scanned.metadata),
        tuple(issues),
    ), compilation_profile=compilation_profile)


__all__ = ["CallSourceSeedReport", "read_call_source_seeds"]
