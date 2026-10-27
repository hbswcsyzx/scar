"""Resolve compact, observed Python code entries to current source seeds.

The scanner checks every raw record, including reference tokens, but this
consumer retains only one count and two anchors per entered (process, code).
Source matches identify possible source seeds; they establish neither the
actual function environment nor caller, data or effect relationships.
"""
from __future__ import annotations

from dataclasses import dataclass, field
import json
import hashlib
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
from scar.ir.record_codec import decode, encode


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
    _captured_session: object = field(default=None,repr=False,compare=False)

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


def _captured_source_budget(call_budget, explicit=None):
    """Bound archive membership separately from selected project analysis."""
    from scar.analysis.captured_source_owner import CapturedSourceBudget
    _require(type(call_budget) is CallEdgeBudget, 'typed normal frame budget required')
    call_budget.__post_init__()
    ceilings = {
        'max_metadata_bytes': call_budget.max_raw_bytes,
        'max_rows_bytes': call_budget.max_raw_bytes,
        'max_row_bytes': min(call_budget.max_line_bytes, call_budget.max_raw_bytes),
        # Each captured filename has a code member. max_source_files instead
        # limits selected project contexts, not all observed archived files.
        'max_files': call_budget.max_codes,
        'max_source_bytes': call_budget.max_raw_bytes,
        'max_codes': call_budget.max_codes,
        'max_code_bytes': call_budget.max_raw_bytes,
    }
    if explicit is None:
        return CapturedSourceBudget(**{
            **ceilings,
            'max_metadata_bytes': min(CapturedSourceBudget().max_metadata_bytes,
                                      call_budget.max_raw_bytes),
        })
    _require(type(explicit) is CapturedSourceBudget, 'typed captured-source budget required')
    explicit.__post_init__()
    _require(all(getattr(explicit, name) <= limit for name, limit in ceilings.items()),
             'captured-source budget exceeds independent frame reader ceilings')
    return explicit


class _CapturedSourceSession:
    """Live normal readers shared by one automatic source construction."""
    def __init__(self, scanned, root, budget, coordinates=None, *, captured_source_budget=None):
        from scar.analysis.captured_source_owner import CapturedSourceOwner
        from scar.analysis.source_discovery import _root_has_initializer
        from scar.ir.program.providers import ProviderArtifact
        from scar.trace.capture_coordinates import CaptureCoordinates
        from scar.trace.captured_sources import PROGRAM_PORTS_PROFILES
        candidates=[meta for meta in scanned.metadata if meta.get('capture_profile') in PROGRAM_PORTS_PROFILES]
        _require(candidates,'captured session needs an original program-ports process')
        if coordinates is not None:
            _require(type(coordinates) is CaptureCoordinates,'source membership needs normal coordinates')
            membership=coordinates.report.get('captured_python_source_membership')
            _require(type(membership) is dict,'captured Python source coordinate membership is absent')
            candidates=[meta for meta in candidates if meta.get('captured_sources')==membership.get('manifest')]
            _require(len(candidates)==1,'coordinate source membership does not select one original process')
            self.membership=membership
        else:
            _require(len(candidates)==1,'multiple source owners require exact coordinate membership')
            self.membership=None
        metadata=decode(ProviderArtifact,candidates[0]['captured_sources'])
        self.owner=CapturedSourceOwner(scanned.directory,project_root=str(root),metadata=metadata,
                                      budget=_captured_source_budget(budget,captured_source_budget),
                                      frame_scan=scanned,frame_budget=budget)
        self.root=Path(root);self.scanned=scanned;self.static_versions={};self.records={};self.codes={}
        _require(self.root.is_dir(),'CAPTURED_NAMESPACE_POLICY_UNAVAILABLE: namespace directory unavailable')
        self.policy={'root':str(root),'root_is_package':_root_has_initializer(self.root),
            'basis':'CURRENT_STATIC_NAMESPACE_INPUT','selector':'source_discovery._root_has_initializer',
            'initializer':str(self.root/'__init__.py'),'loaded_module_established':False}
        for code in self.owner.captured_codes():
            if Path(code.filename).is_absolute():
                self.codes.setdefault(code.filename,code)
                try:self.records[code.filename]=self.owner.archived_source(self.owner.snapshot(code))
                except LookupError:pass

    def has_path(self,path):return str(path) in self.codes

    def archived(self,path):
        code=self.codes.get(str(path))
        if code is None:raise LookupError('source filename has no original capture observation')
        return self.owner.archived_source(self.owner.snapshot(code))

    def prepare(self,path,namespace_root=None):
        from scar.analysis.program_lowering import prepare_captured_source
        namespace=Path(namespace_root) if namespace_root is not None else self.root
        _require(namespace==self.root,'captured source namespace changed without an admission adapter')
        self.require_unchanged()
        return prepare_captured_source(self.owner,self.codes[str(path)],project_root=namespace,
                                      root_is_package=self.policy['root_is_package'])

    def record_static(self,path,text,encoding,raw_bytes):
        self.static_versions[str(path)]={'path':str(path),'fingerprint':'sha256:'+hashlib.sha256(text.encode()).hexdigest(),
            'encoding':encoding,'raw_bytes':raw_bytes,'basis':'CURRENT_STATIC_UNEXECUTED_SOURCE_VERSION',
            'same_capture_source_bytes_established':False,'execution_established':False}

    def require_unchanged(self):
        from scar.analysis.source_discovery import _root_has_initializer
        self.owner.require_unchanged()
        _require(self.root.is_dir() and _root_has_initializer(self.root)==self.policy['root_is_package'],
                 'static source namespace policy changed during construction')

    def report(self):
        self.require_unchanged()
        return {'namespace_policy':dict(self.policy),'owner':self.owner.receipts(),
            'coordinate_membership':self.membership,
            'captured_files':[{'snapshot':encode(r.snapshot),'source':encode(r.source),
                'original_encoding':r.original_encoding,'compiler_match':'NOT_CHECKED','loader_bytes_observed':False}
                for path,r in sorted(self.records.items())if Path(path).is_relative_to(self.root)],
            'current_static_files':[dict(r)for _,r in sorted(self.static_versions.items())],
            'frontiers':self.owner.frontiers(),'whole_model_established':False}

    def close(self):
        try:
            self.require_unchanged()
        except BaseException:
            try:
                self.owner.close()
            except BaseException:
                pass  # Preserve the first detected input/namespace failure.
            raise
        else:
            self.owner.close()


def read_call_source_seeds(
    trace, project_root, *, budget=CallEdgeBudget(),
    compilation_profile=CallCompilationProfile.RECORDED_FUTURE_FLAGS, coordinates=None,
    captured_source_budget=None,
):
    """Read bounded collector records and resolve only actually entered codes.

    This does not execute project code, build a full call report, or construct
    reference routes. A code fingerprint match without a unique source
    definition remains in the report but is not an eligible source seed.
    """
    return _read_call_source_seeds(
        trace, project_root, budget=budget, compilation_profile=compilation_profile,coordinates=coordinates,
        captured_source_budget=captured_source_budget,
    )


def _read_call_source_seeds(
    trace, project_root, *, budget, _source_workspace=None,
    compilation_profile=CallCompilationProfile.RECORDED_FUTURE_FLAGS,coordinates=None,
    captured_source_budget=None,
):
    """Private composition shares locally prepared contexts, never report seeds."""
    _require(isinstance(budget, CallEdgeBudget), "source seeds require a typed replay budget")
    _require(type(compilation_profile) is CallCompilationProfile,
             "source seeds require a typed compilation profile")
    captured_source_budget = _captured_source_budget(budget, captured_source_budget)
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
    from scar.trace.captured_sources import PROGRAM_PORTS_PROFILES
    captured_session=(_CapturedSourceSession(scanned,root,budget,coordinates,
                                           captured_source_budget=captured_source_budget)
        if any(meta.get('capture_profile')in PROGRAM_PORTS_PROFILES for meta in scanned.metadata)else None)
    if _source_workspace is not None:
        if captured_session is not None:_source_workspace.bind_captured_session(captured_session)
        _source_workspace.prime_sources(tuple(descriptors.values()))
    sources = _Sources(root,budget,inventory=None,_source_workspace=_source_workspace,
        compilation_profile=compilation_profile,
        captured_source_owner=captured_session.owner if captured_session is not None else None,
        captured_source_root_is_package=captured_session.policy['root_is_package']if captured_session is not None else None)
    code_links = tuple(sources.code(descriptors[key]) for key in sorted(descriptors))
    return CallSourceSeedReport(CallSourceSeedModel(
        scanned.directory, str(root), budget, scanned.files, scanned.captures,
        groups, code_links,
        tuple(SeedCollectionMetadata.from_metadata(meta) for meta in scanned.metadata),
        tuple(issues),
    ), compilation_profile=compilation_profile,_captured_session=captured_session)


__all__ = ["CallSourceSeedReport", "read_call_source_seeds"]
