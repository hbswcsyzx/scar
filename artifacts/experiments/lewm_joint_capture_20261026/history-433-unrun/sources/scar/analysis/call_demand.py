"""Private raw-call/source/inventory composition for inventory v6.

Only this coordinator shares contexts created during the current invocation.
Public replay starts from raw collector files and current source, never from
serialized claims about source matches or queue admission.
"""
from __future__ import annotations

from collections import Counter
from copy import copy
import hashlib
import pickle
from pathlib import Path

from scar.analysis.program_context_store import PreparedContextStore, ContextStoreLimit
from scar.analysis.program_lowering import prepare_source
from scar.ir.program.compilation import CallCompilationProfile
from scar.ir.program.functions import BodyLoweringProfile


def _fresh_failure(error):
    """Keep exception fields without retaining or reattaching a heavy frame."""
    result = copy(error)
    result.__traceback__ = result.__context__ = result.__cause__ = None
    return result


class _SourceWorkspace:
    """One preparation per source, backed by the bounded private context store."""

    def __init__(self, project_root, budget, *, entry=None, source_roots=(), inventory_budget=None):
        self.root = Path(project_root).resolve()
        self.store = PreparedContextStore(budget)
        self.preparations = Counter()
        self._errors = {}
        self._source_errors = {}
        self._projection_errors = {}
        self._sealed = set()
        self._projections = {}
        self._observed_paths = set()
        self.entry, self.source_roots, self.inventory_budget = entry, source_roots, inventory_budget
        self.entry_frontier = None

    def prime_sources(self, descriptors):
        """Give the entry closure first claim on the private context budget.

        Source-match budget order remains the original code-hash order. Light
        source projections survive a full-context spool failure, so lack of
        scratch space does not turn an otherwise verifiable code into a match.
        """
        if self.entry is None:
            return
        from scar.analysis.program_inventory import _ordered_files
        from scar.analysis.source_discovery import _discover_sources_from_call_sources
        self._observed_paths = {code.filename for code in descriptors}
        budget = self.inventory_budget
        self.entry_frontier = _discover_sources_from_call_sources(self.entry,
            project_root=self.root, source_roots=self.source_roots, source_witnesses=(),
            max_files=budget.max_files, max_bytes=budget.max_bytes,
            max_directories=budget.max_directories)
        for file in _ordered_files(self.entry_frontier):
            try:
                context = self.prepare(file.snapshot.path)
                if context.semantics.sources[file.snapshot.path].fingerprint != file.snapshot.fingerprint:
                    raise ValueError("source changed between entry discovery and preparation")
            except (OSError, ValueError, TypeError, KeyError, SyntaxError, RecursionError):
                # The normal inventory path publishes the concrete boundary.
                pass

    @staticmethod
    def _current_fingerprint(path):
        from scar.analysis.source_discovery import _read_source
        try:
            text, _, _ = _read_source(Path(path), 4_000_000)
        except OverflowError as error:
            raise ValueError("source exceeds the existing 4 MB control-model input budget") from error
        return "sha256:" + hashlib.sha256(text.encode()).hexdigest()

    def source_projection(self, path):
        key = str(path)
        self._observed_paths.add(key)
        if key not in self._projections and key not in self._projection_errors:
            context = self.prepare(path)
            if key not in self._projections:
                self._publish_projection(context)
        if key in self._projection_errors:
            raise _fresh_failure(self._projection_errors[key]) from None
        projection = self._projections[key]
        if self._current_fingerprint(path) != projection[0].snapshot.fingerprint:
            raise ValueError("source changed since private source-witness preparation")
        return projection

    def _publish_projection(self, context):
        from scar.analysis.call_edges import _source_witness_projection
        key = str(context.path)
        try:
            self._projections[key] = _source_witness_projection(context)
        except (ValueError, TypeError, KeyError, SyntaxError, RecursionError) as error:
            self._projection_errors[key] = _fresh_failure(error)

    def __enter__(self):
        return self

    def __exit__(self, *exc):
        self.store.close()

    def prepare(self, path):
        path = Path(path)
        if not path.is_absolute() or path != path.resolve() or not path.is_relative_to(self.root):
            raise ValueError("source workspace path must be canonical and within project root")
        key = str(path)
        if key in self._source_errors:
            raise _fresh_failure(self._source_errors[key]) from None
        if key in self._errors:
            raise ValueError(self._errors[key])
        if key in self._sealed:
            fingerprint = self._current_fingerprint(path)
            context = self.store.get(key)
            if context.semantics.sources[key].fingerprint != fingerprint:
                raise ValueError("source changed since private context preparation")
            return context
        self.preparations[key] += 1
        try:
            context = prepare_source(path, project_root=self.root)
        except (OSError, ValueError, TypeError, KeyError, SyntaxError, RecursionError) as error:
            self._source_errors[key] = _fresh_failure(error)
            raise
        if key in self._observed_paths:
            self._publish_projection(context)
        try:
            self.store.put(context)
        except (OSError, ValueError, TypeError, KeyError, RecursionError, pickle.PickleError) as error:
            # A scratch budget must not invalidate a code/source match that
            # can be checked using this first context. Later consumers retain
            # an explicit unavailable boundary instead of preparing it again.
            self._errors[key] = (str(error) if isinstance(error, ContextStoreLimit)
                                 else "private context unavailable: " + type(error).__name__)
        else:
            self._sealed.add(key)
        return context

    def measurements(self):
        return {"source_prepare_attempts": sum(self.preparations.values()),
                "distinct_source_prepare_paths": len(self.preparations),
                "source_prepare_max_per_path": max(self.preparations.values(), default=0),
                "source_workspace_failures": len(self._errors) + len(self._source_errors),
                "source_witness_projection_failures": len(self._projection_errors),
                "source_discovery_passes": 2 if self.entry_frontier is not None else 1}


def inventory_from_calls(entry, *, project_root, source_roots, budget, call_trace,
                         call_budget, context_budget, expected_call_sources=None,
                         compilation_profile=CallCompilationProfile.RECORDED_FUTURE_FLAGS,
                         body_profile=BodyLoweringProfile.BOUND_FRAME):
    from scar.analysis.call_seeds import _read_call_source_seeds
    from scar.analysis.program_expansion import expand_inventory
    from scar.analysis.program_inventory import ProgramInventory, _canonical
    from scar.analysis.source_discovery import _discover_sources_from_call_sources
    from scar.ir.program.functions import BodyLoweringProfile

    if type(body_profile) is not BodyLoweringProfile or body_profile not in (
            BodyLoweringProfile.BOUND_FRAME, BodyLoweringProfile.STRUCTURED_BODY, BodyLoweringProfile.STRUCTURED_ENV):
        raise ValueError("call-source inventory requires a frame or structured body profile")

    root = Path(project_root).resolve() if project_root is not None else Path(entry).absolute().parent.resolve()
    with _SourceWorkspace(root, context_budget, entry=entry, source_roots=source_roots,
                          inventory_budget=budget) as workspace:
        report = _read_call_source_seeds(call_trace, root, budget=call_budget,
            _source_workspace=workspace, compilation_profile=compilation_profile)
        if expected_call_sources is not None and _canonical(report.to_dict()) != _canonical(expected_call_sources):
            raise ValueError("call seeds differ from current raw trace/source replay")
        discovery = _discover_sources_from_call_sources(entry, project_root=root,
            source_roots=source_roots, source_witnesses=report.eligible_code_links(),
            max_files=budget.max_files, max_bytes=budget.max_bytes,
            max_directories=budget.max_directories)
        files, schedule, measurements, interfaces, frames, structured = expand_inventory(
            discovery, None, budget, context_budget, discovery.files, interface_model=True,
            body_profile=body_profile, call_source_report=report,
            source_workspace=workspace)
        scope = _call_source_scope(report, files)
        result = ProgramInventory(discovery, files, budget, expansion=schedule,
            analysis_measurements=measurements, interfaces=interfaces,
            profile=body_profile, frames=frames, structured=structured,
            call_sources=report, call_source_scope=scope,
            source_analysis_measurements=workspace.measurements())
        result._check_profile()
        return result


def derive_call_source_admission(origin, code_source_link, *, source_snapshot,
                                 indexed_definitions, body=None, source_unavailable=False):
    """Derive one static source/body association using the full original join.

    ``body`` is the existing BodyInventory produced/read through the public
    body pipeline, not a caller success flag or standalone region claim.
    This correspondence does not prove effects or any current invocation.
    """
    from scar.ir.program.call_demand import (
        CallSourceAdmission, CallSourceAdmissionStatus as Status, EnteredCallCode,
    )
    from scar.ir.program.call_edges import CodeSourceLink, CallLinkStatus
    from scar.ir.program.inventory import BodyInventory, BodyStatus, DefinitionInventory
    from scar.ir.semantics_v2 import SourceSnapshot
    if (type(origin) is not EnteredCallCode or type(code_source_link) is not CodeSourceLink
            or code_source_link.status is not CallLinkStatus.VERIFIED
            or origin.code != code_source_link.code or type(indexed_definitions) is not tuple
            or any(type(item) is not DefinitionInventory for item in indexed_definitions)
            or type(source_unavailable) is not bool):
        raise TypeError("static admission needs exact original origin/link/definition records")
    if source_snapshot is None:
        return CallSourceAdmission(origin, Status.UNAVAILABLE,
            reason="source not admitted by discovery budgets or source boundary")
    if type(source_snapshot) is not SourceSnapshot:
        raise TypeError("static admission source snapshot must be exact")
    link = code_source_link
    if source_snapshot.path != link.snapshot.path or source_snapshot.fingerprint != link.snapshot.fingerprint:
        return CallSourceAdmission(origin, Status.MISMATCH,
            reason="discovered source content differs from the verified code/source snapshot")
    matches = [definition for definition in indexed_definitions
               if definition.id == link.definition and definition.source == link.source]
    if len(matches) != 1:
        status = Status.UNAVAILABLE if not indexed_definitions and source_unavailable else Status.MISMATCH
        return CallSourceAdmission(origin, status,
            reason="verified unique definition was not indexed in the admitted source")
    definition = matches[0]
    if body is not None and (type(body) is not BodyInventory or body.definition != definition.id):
        raise ValueError("static admission body differs from its unique original definition")
    if body is not None and body.graph is not None:
        if (body.status is not BodyStatus.LOWERED_WITH_GAPS or body.metadata is None
                or body.metadata.source != source_snapshot):
            raise ValueError("canonical body status/source contradicts its static admission")
        return CallSourceAdmission(origin, Status.CORE_LINKED,
            source_snapshot, definition.id, definition.source, body.graph.root)
    reason = body.reason if body is not None and body.reason else "indexed source has no supported body interface"
    return CallSourceAdmission(origin, Status.INDEXED_WITHOUT_BODY,
        source_snapshot, definition.id, definition.source, reason=reason)


def derive_entry_source_admission(origin, code_source_link, *, catalog, entry, body):
    """Associate one checked original entry/body, without project inventory slots.

    This is static membership only. Current frame/process membership is checked
    independently by the invocation binder; no callable/environment is inferred.
    """
    from scar.analysis.source_entry_catalog import SourceEntryCatalog, ResolvedSourceEntry
    from scar.ir.program.call_demand import EnteredCallCode, CallSourceAdmission, CallSourceAdmissionStatus
    from scar.ir.program.call_edges import CodeSourceLink, CallLinkStatus
    from scar.ir.program.inventory import BodyInventory, BodyStatus
    if (type(catalog) is not SourceEntryCatalog or type(entry) is not ResolvedSourceEntry
            or type(origin) is not EnteredCallCode or type(code_source_link) is not CodeSourceLink
            or type(body) is not BodyInventory):
        raise TypeError("qualified admission requires exact catalog/entry/origin/link/body")
    owner = catalog.require_entry(entry)
    owner.resolve_definition(entry.reference)
    link, reference = entry.source_link, entry.reference
    if (code_source_link != link or link.status is not CallLinkStatus.VERIFIED
            or origin.code != entry.captured.key or link.code != origin.code
            or link.snapshot != reference.snapshot or link.definition != reference.definition
            or link.source != reference.source or body.definition != reference.definition
            or body.status is not BodyStatus.LOWERED_WITH_GAPS or body.graph is None
            or body.metadata is None or body.metadata.source != reference.snapshot
            or body.construction_operations is not None):
        raise ValueError("qualified body admission contradicts its original code/source/body")
    groups = [row for row in catalog.metadata()["groups"]
              if row["process_id"] == origin.process_id and row["code"] == origin.code
              and row.get("entry_key") == entry.key]
    if len(groups) != 1:
        raise ValueError("qualified admission origin is not one original catalog group")
    return CallSourceAdmission(origin, CallSourceAdmissionStatus.CORE_LINKED,
        reference.snapshot, reference.definition, reference.source, body.graph.root)


def _call_source_scope(report, files):
    """Link only final bodies, after every preparation/interface failure."""
    from scar.ir.program.call_demand import CallSourceScope, EnteredCallCode
    by_path = {file.snapshot.path: file for file in files}
    links = {link.code: link for link in report.eligible_code_links()}
    admissions = []
    for group in report.eligible_groups():
        link = links[group.code]
        file = by_path.get(link.snapshot.path)
        definitions = () if file is None else file.definitions
        body = (next((body for body in file.bodies if body.definition == link.definition), None)
                if file is not None else None)
        admissions.append(derive_call_source_admission(EnteredCallCode(group.process_id, group.code), link,
            source_snapshot=None if file is None else file.snapshot, indexed_definitions=definitions,
            body=body, source_unavailable=file is not None and bool(file.gaps)))
    return CallSourceScope(tuple(admissions))


def replay_inventory_from_calls(document, *, discovery, roots, budget, context_ceiling, call_ceiling):
    from scar.analysis.call_seeds import CallSourceSeedReport
    from scar.analysis.program_inventory import _check_context_budget
    from scar.ir.program.call_demand import CallSourceScope, ExpansionScheduleV6
    from scar.ir.program.frames import FrameModel
    from scar.ir.program.functions import BodyLoweringProfile, FunctionInterfaces
    from scar.ir.record_codec import decode

    if document["runtime_scope"] is not None:
        raise ValueError("inventory v6 cannot silently combine legacy observations and call-source groups")
    schedule = decode(ExpansionScheduleV6, document["expansion"])
    _check_context_budget(schedule.budget, context_ceiling)
    interfaces = decode(FunctionInterfaces, document["interfaces"])
    expected_profile = (BodyLoweringProfile.STRUCTURED_ENV if document["schema_version"] == 8 else
                        BodyLoweringProfile.STRUCTURED_BODY if document["schema_version"] == 7
                        else BodyLoweringProfile.BOUND_FRAME)
    if (decode(BodyLoweringProfile, document["profile"]) is not expected_profile
            or interfaces.profile is not expected_profile):
        raise ValueError("inventory version differs from its call-source body profile")
    if expected_profile is BodyLoweringProfile.BOUND_FRAME:
        decode(tuple[FrameModel, ...], document["frames"])
    else:
        from scar.ir.program.structured import StructuredBodyModel
        decode(tuple[StructuredBodyModel, ...], document["structured"])
    decode(CallSourceScope, document["call_source_scope"])
    model = CallSourceSeedReport._decode_replay_input(document["call_sources"],
        verification_budget=call_ceiling)
    compilation_profile = CallSourceSeedReport._compilation_profile(document["call_sources"])
    if model.project_root != discovery.project_root:
        raise ValueError("call-source project root differs from source discovery")
    return inventory_from_calls(discovery.entry, project_root=discovery.project_root,
        source_roots=roots, budget=budget, call_trace=model.trace_directory,
        call_budget=model.budget, context_budget=schedule.budget,
        expected_call_sources=document["call_sources"], compilation_profile=compilation_profile,
        body_profile=expected_profile)
