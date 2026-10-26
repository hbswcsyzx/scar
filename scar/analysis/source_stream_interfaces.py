"""Reference-only joins from retained builtin stream calls to source/core calls.

The result is a view over original CALL attempts, CallSiteLinks and
canonical source-body ProgramGraph ports. It does not emit another operation, state graph, resource
identity, or readiness/content claim.
"""
from __future__ import annotations

from dataclasses import dataclass
from enum import Enum
from pathlib import Path

from scar.analysis.call_edges import _Sources
from scar.analysis.call_operand_reader import CallOperandTrace
from scar.ir.program.call_edges import (
    CallEdgeBudget, CallLinkStatus, CallRecordAnchor, CallSiteLink,
    CapturedSite, CodeSourceLink, InvocationKey,
)
from scar.ir.program.ids import LocationID, OperationID, RegionID, UseID
from scar.ir.program.model import (
    CompletionResult, CompletionSuccessor, ExitKind, StateVersionValue,
    TerminatorKind, UseRole,
)
from scar.ir.program.queries import ProgramIndex
from scar.ir.v2.common import SourceReference
from scar.ir.record_codec import decode
from scar.trace.stream_interfaces import StreamContract, read_stream_interfaces


class SourceStreamStatus(str, Enum):
    SOURCE_ONLY = "SOURCE_ONLY"
    CORE_CONNECTED = "CORE_CONNECTED"
    SOURCE_BOUNDARY = "SOURCE_BOUNDARY"


class SourceStreamBodyOrigin(str, Enum):
    ADMITTED_BODY = "ADMITTED_BODY"
    SOURCE_REPLAY_LOCAL_BODY = "SOURCE_REPLAY_LOCAL_BODY"


@dataclass(frozen=True, slots=True)
class StreamResourceInterface:
    """Observed receiver token plus the original declared interface roles."""

    receiver_reference: str
    receiver_kind: str
    receiver_type: str
    identity_qualified: bool
    contract: StreamContract

    def __post_init__(self):
        if type(self.receiver_reference) is not str or not self.receiver_reference:
            raise TypeError("stream receiver needs its original reference token")
        if type(self.receiver_kind) is not str or not self.receiver_kind:
            raise TypeError("stream receiver kind is required")
        if type(self.receiver_type) is not str or not self.receiver_type:
            raise TypeError("stream receiver type is required")
        if type(self.identity_qualified) is not bool or type(self.contract) is not StreamContract:
            raise TypeError("stream receiver qualification and contract must be typed")
        if (type(self.contract.method) is not str or not self.contract.method
                or type(self.contract.reads) is not tuple
                or type(self.contract.may_write) is not tuple
                or type(self.contract.effects_complete) is not bool
                or self.contract.effects_complete):
            raise ValueError("stream contract must retain its incomplete declared-effects status")


@dataclass(frozen=True, slots=True)
class SourceCompletionPort:
    """Canonical source-body INVOKE completion edge and its result ordinals."""

    successor_index: int
    kind: ExitKind
    results: tuple[CompletionResult, ...]
    state_result: CompletionResult | None

    def __post_init__(self):
        if type(self.successor_index) is not int or self.successor_index < 0:
            raise TypeError("completion successor index must be nonnegative")
        if type(self.kind) is not ExitKind:
            raise TypeError("completion kind must be typed")
        if type(self.results) is not tuple or any(type(item) is not CompletionResult for item in self.results):
            raise TypeError("completion results must be existing CompletionResult references")
        if self.state_result is not None and type(self.state_result) is not CompletionResult:
            raise TypeError("world result must be an existing CompletionResult reference")
        if self.state_result is not None and self.state_result not in self.results:
            raise ValueError("world result is not on this completion edge")


@dataclass(frozen=True, slots=True)
class SourceStreamOperationPorts:
    """References into one canonical source-body Operation, without copying it."""

    region: RegionID
    operation: OperationID
    callee_use: UseID
    actual_uses: tuple[UseID, ...]
    world_use: UseID
    world_location: LocationID
    completions: tuple[SourceCompletionPort, ...]
    body_origin: SourceStreamBodyOrigin

    def __post_init__(self):
        if any(type(value) is not kind for value, kind in (
                (self.region, RegionID), (self.operation, OperationID),
                (self.callee_use, UseID), (self.world_use, UseID),
                (self.world_location, LocationID))):
            raise TypeError("source stream ports need typed canonical source-body references")
        if type(self.actual_uses) is not tuple or any(type(value) is not UseID for value in self.actual_uses):
            raise TypeError("actual Uses must be an ordered tuple of source-body UseIDs")
        if type(self.completions) is not tuple or any(type(value) is not SourceCompletionPort for value in self.completions):
            raise TypeError("completion ports must be typed source-body references")
        if type(self.body_origin) is not SourceStreamBodyOrigin:
            raise TypeError("source stream ports must identify their canonical body origin")


@dataclass(frozen=True, slots=True)
class SourceStreamCall:
    """One original stream observation routed to its exact source call site."""

    attempt: CallRecordAnchor
    invocation: InvocationKey
    site: CapturedSite
    caller_code: CodeSourceLink
    call_site: CallSiteLink
    source: SourceReference | None
    resource: StreamResourceInterface
    observed_completion: str
    observed_exit_kind: ExitKind | None
    status: SourceStreamStatus
    ports: SourceStreamOperationPorts | None
    issues: tuple[str, ...] = ()

    def __post_init__(self):
        for value, kind in ((self.attempt, CallRecordAnchor), (self.invocation, InvocationKey),
                            (self.site, CapturedSite), (self.caller_code, CodeSourceLink),
                            (self.call_site, CallSiteLink), (self.resource, StreamResourceInterface),
                            (self.status, SourceStreamStatus)):
            if type(value) is not kind:
                raise TypeError("source stream call reference has the wrong typed record")
        if self.source is not None and type(self.source) is not SourceReference:
            raise TypeError("source call must retain its original SourceReference")
        if self.observed_completion not in ("C_RETURN", "C_RAISE", "UNOBSERVED"):
            raise ValueError("unknown original C-call completion event")
        expected = {"C_RETURN": ExitKind.NORMAL, "C_RAISE": ExitKind.RAISE, "UNOBSERVED": None}[self.observed_completion]
        if self.observed_exit_kind is not expected:
            raise ValueError("observed completion kind differs from its original event")
        if (self.status is SourceStreamStatus.CORE_CONNECTED) != (self.ports is not None):
            raise ValueError("core connection status differs from canonical source-body references")
        if self.ports is not None and self.call_site.core_operation != self.ports.operation:
            raise ValueError("port view operation differs from the original CallSiteLink")


@dataclass(frozen=True, slots=True)
class SourceStreamInterfaceView:
    metadata_uri: str
    metadata_sha256: str
    calls: tuple[SourceStreamCall, ...]
    source_body_operations_available: bool
    whole_model_established: bool = False
    effects_complete: bool = False
    receiver_bound_to_source_value: bool = False
    content_or_readiness_proved: bool = False
    conditions: tuple[str, ...] = (
        "receiver tokens remain observation references; they are not joined to a source Value or ResourceDefinition",
        "C_RETURN/C_RAISE identifies the captured C-call outcome only; it is not a byte count, readiness, or persistence claim",
        "stream read/write roles are declared and incomplete; selected source-body coarse world ports remain the only state carrier",
        "a missing original or validated source-replay body stays a source boundary; no operation or completion port is fabricated",
    )

    def __post_init__(self):
        if type(self.calls) is not tuple or any(type(item) is not SourceStreamCall for item in self.calls):
            raise TypeError("stream source view requires immutable call rows")
        if any(type(getattr(self, name)) is not bool for name in (
                "source_body_operations_available", "whole_model_established", "effects_complete",
                "receiver_bound_to_source_value", "content_or_readiness_proved")):
            raise TypeError("stream source view nonclaims must be exact booleans")
        if type(self.conditions) is not tuple or any(type(item) is not str or not item for item in self.conditions):
            raise TypeError("stream source view conditions must be explicit text")
        if any((self.whole_model_established, self.effects_complete,
                self.receiver_bound_to_source_value, self.content_or_readiness_proved)):
            raise ValueError("stream source interface cannot overstate its evidence")


def _core_ports(index: ProgramIndex, link: CallSiteLink,
                body_origin=SourceStreamBodyOrigin.ADMITTED_BODY) -> SourceStreamOperationPorts:
    operation = index.operations[link.core_operation]
    if (operation.terminator is None or operation.terminator.kind is not TerminatorKind.INVOKE
            or not operation.invoke_arguments or operation.invoke_arguments[0] != link.callee_use):
        raise ValueError("source CALL does not retain its exact canonical INVOKE/callee Use")
    uses = {use.id: use for use in operation.uses}
    if any(identity not in uses for identity in operation.invoke_arguments):
        raise ValueError("source CALL invocation vector contains a foreign Use")
    state_uses = [identity for identity in operation.invoke_arguments
                  if uses[identity].role is UseRole.STATE_CONTENT
                  and type(index.values[uses[identity].value]) is StateVersionValue]
    if len(state_uses) != 1 or operation.invoke_arguments[-1] != state_uses[0]:
        raise ValueError("source CALL needs one trailing source-body world/state Use")
    world_use = uses[state_uses[0]]
    world_value = index.values[world_use.value]
    actuals = operation.invoke_arguments[1:-1]
    if any(uses[identity].role is UseRole.STATE_CONTENT for identity in actuals):
        raise ValueError("source CALL actual vector unexpectedly contains a world Use")
    regions = [region for region in index.graph.regions if region.id == link.core_region]
    if len(regions) != 1:
        raise ValueError("CallSiteLink region is not in the selected canonical source graph")
    blocks = {block.id: block for region in index.graph.regions for block in region.blocks}
    completions = []
    for ordinal, edge in enumerate(operation.terminator.successors):
        if type(edge) is not CompletionSuccessor:
            raise ValueError("canonical CALL completion does not use CompletionSuccessor")
        signature = next((row for row in operation.completions if row.kind is edge.kind), None)
        target = blocks.get(edge.block)
        if signature is None or target is None or len(signature.types) != len(edge.arguments) or len(target.arguments) != len(edge.arguments):
            raise ValueError("canonical CALL completion signature/landing layout differs")
        world_slots = [slot for slot, value_id in enumerate(target.arguments)
                       if type(index.values[value_id]) is StateVersionValue
                       and index.values[value_id].location == world_value.location]
        if len(world_slots) != 1:
            raise ValueError("completion does not have one matching source-body world result slot")
        results = tuple(item for item in edge.arguments if type(item) is CompletionResult)
        state_result = edge.arguments[world_slots[0]]
        if type(state_result) is not CompletionResult:
            raise ValueError("world result is not a source-body CompletionResult")
        completions.append(SourceCompletionPort(ordinal, edge.kind, results, state_result))
    return SourceStreamOperationPorts(link.core_region, operation.id, link.callee_use,
        tuple(actuals), world_use.id, world_value.location, tuple(completions), body_origin)


def _qualified_source_replay(source_model, source_program, language_options, trace):
    """Validate one temporary source-body input against the original namespace."""
    from scar.analysis.program_inventory import ProgramInventory
    from scar.analysis.program_lowering import SourceProgram, validate_source_program
    from scar.analysis.source_language import SourceCodeEvidence, SourceLanguageOptions
    from scar.ir.program.functions import BodyLoweringProfile

    if type(source_model) is not ProgramInventory:
        raise TypeError("source replay body input requires the exact typed ProgramInventory namespace")
    if (type(source_program) is not SourceProgram
            or source_program.profile is not BodyLoweringProfile.STRUCTURED_ENV
            or source_program.graph is None or source_program.structured is None
            or source_program.language is None):
        raise ValueError("source replay input must be a complete SourceProgram5 body")
    if type(language_options) is not SourceLanguageOptions:
        raise TypeError("source replay body input requires its explicit typed language options")
    evidence = language_options.code_evidence
    if type(evidence) is not SourceCodeEvidence:
        raise ValueError("source replay body input requires the independent CodeWitness evidence")

    root = Path(trace.project_root).resolve()
    if (Path(source_model.discovery.project_root).resolve() != root
            or source_program.language.namespace_root != str(root)):
        raise ValueError("source replay body namespace differs from the original call/source namespace")
    matches = [(file, definition) for file in source_model.files
               if file.snapshot.path == source_program.metadata.source.path
               and file.snapshot.fingerprint == source_program.metadata.source.fingerprint
               for definition in file.definitions
               if definition.id == source_program.structured.definition]
    if len(matches) != 1:
        raise ValueError("source replay body has no unique exact original inventory definition")
    original_file, definition = matches[0]
    if (original_file.snapshot != source_program.metadata.source
            or definition.source != source_program.structured.source
            or definition.name != source_program.metadata.entry
            or definition.kind.value != "FUNCTION"):
        raise ValueError("source replay body definition/source differs from the original inventory namespace")
    evidence.require_definition(original_file.snapshot, definition.id, definition.source)
    captured = [item.code for item in trace.frame_scan.captures
                if item.code.key == evidence.captured.key]
    if not captured or any(item != evidence.captured for item in captured):
        raise ValueError("source replay CodeWitness differs from the complete captured caller descriptor")

    report = validate_source_program(source_program, language_options=language_options,
        verification="SOURCE_REPLAY")
    if report.get("valid") is not True:
        raise ValueError("source replay body failed its normal SOURCE_REPLAY validation: "
                         + "; ".join(report.get("errors", ())))
    operations = {operation.id: operation for operation in source_program.graph.operations}
    uses = {use.id: use for operation in source_program.graph.operations for use in operation.uses}
    blocks = {block.id: block for region in source_program.graph.regions for block in region.blocks}
    return original_file, definition, (source_program, operations, uses, blocks)


def _source_replay_call_site(sources, captured, base_link, descriptors,
                             original_file, definition, body_core):
    """Use the existing exact source CALL mapper with one validated local body."""
    if (base_link.status is not CallLinkStatus.VERIFIED or base_link.core_operation is not None
            or base_link.execution_owner != definition.id):
        return None
    description = descriptors.get(captured.code)
    code = sources.links.get(captured.code)
    indexed = sources.indexes.get(description.filename) if description is not None else None
    if code is None or indexed is None:
        raise ValueError("verified source call has no current code/source projection")
    link = _Sources._call_site_body(captured, indexed, code, {definition.id: body_core})
    if (link.status is not CallLinkStatus.VERIFIED or link.core_operation is None
            or link.source != base_link.source or link.call != base_link.call
            or link.execution_owner != base_link.execution_owner):
        return None
    original_calls = [call for call in original_file.calls
                      if call.source == link.source and call.execution_owner == definition.id
                      and call.operation == link.call]
    if len(original_calls) != 1:
        raise ValueError("source replay CALL does not resolve to one exact original inventory CallInventory")
    return link


def read_source_stream_interfaces(*, trace: CallOperandTrace, source_model,
                                  metadata, expected_sha256: str,
                                  source_budget: CallEdgeBudget = CallEdgeBudget(),
                                  source_program=None, language_options=None):
    """Join original stream events through CodeWitness to original source/core.

    ``source_model`` is an ordinary ProgramInventory or the bound
    SourceBodyAccess produced by the source pipeline. An optional, fully
    SOURCE_REPLAY-validated SourceProgram5 can supply one local source body
    when the original inventory records that body as unsupported. The local
    body is checked against the exact original definition and CALL inventory;
    it does not modify or upgrade the inventory record.
    """
    if type(trace) is not CallOperandTrace:
        raise TypeError("source stream join requires the normal original operand/frame reader result")
    if type(source_budget) is not CallEdgeBudget:
        raise TypeError("source stream join requires a typed source-link budget")
    source_budget.__post_init__()
    metadata_path = Path(metadata).absolute()
    observed = read_stream_interfaces(metadata_path, expected_sha256=expected_sha256)
    if str(Path(trace.directory).resolve()) != str(metadata_path.parent.resolve()):
        raise ValueError("stream metadata belongs to another original call trace directory")
    model_root = (getattr(getattr(source_model, "discovery", None), "project_root", None)
                  or getattr(source_model, "root", None))
    if model_root is None or Path(model_root).resolve() != Path(trace.project_root).resolve():
        raise ValueError("source model is not in the exact captured project-root namespace")
    attempts = {(row.process_id, row.index): row for row in trace.attempts}
    descriptors = {row.code.key: row.code for row in trace.frame_scan.captures}
    local_body = None
    if source_program is not None:
        original_file, definition, body_core = _qualified_source_replay(
            source_model, source_program, language_options, trace)
        local_body = (original_file, definition, body_core)
    elif language_options is not None:
        raise ValueError("source language options require an explicit source replay body")
    sources = _Sources(trace.project_root, source_budget, source_model)
    indexes = {}
    calls = []
    for row in observed["calls"]:
        invocation = decode(InvocationKey, row["invocation"])
        captured = decode(CapturedSite, row["site"])
        key = invocation.process_id, row["attempt_index"]
        attempt = attempts.get(key)
        if (attempt is None or attempt.invocation != invocation or attempt.site != captured
                or row["attempt_source"] != {
                    "path": attempt.anchor.path, "line_number": attempt.anchor.line_number,
                    "line_sha256": attempt.anchor.line_sha256, "index": attempt.index}):
            raise ValueError("stream call differs from its exact original CALL_ATTEMPT anchor")
        code = sources.links.get(captured.code)
        if code is None:
            descriptor = descriptors.get(captured.code)
            if descriptor is None:
                raise ValueError("original stream caller code descriptor is missing")
            code = sources.code(descriptor)
        link = sources.call_site(captured, descriptors)
        body_origin = SourceStreamBodyOrigin.ADMITTED_BODY
        if (local_body is not None and link.status is CallLinkStatus.VERIFIED
                and link.core_operation is None):
            local_file, local_definition, local_core = local_body
            replay_link = _source_replay_call_site(sources, captured, link, descriptors,
                local_file, local_definition, local_core)
            if replay_link is not None:
                link = replay_link
                body_origin = SourceStreamBodyOrigin.SOURCE_REPLAY_LOCAL_BODY
        source = link.source
        ports, issues = None, []
        if link.status is not CallLinkStatus.VERIFIED:
            issues.extend(issue.detail for issue in link.issues)
        else:
            local_match = (local_body is not None
                and body_origin is SourceStreamBodyOrigin.SOURCE_REPLAY_LOCAL_BODY
                and link.execution_owner == local_body[1].id)
            if link.core_operation is None or (link.execution_owner not in sources.core and not local_match):
                issues.extend(issue.detail for issue in link.issues)
                if not issues:
                    issues.append("verified source call has no admitted or SOURCE_REPLAY-local ProgramGraph operation")
            else:
                try:
                    body = (local_body[2][0] if local_match else sources.core[link.execution_owner][0])
                    index = indexes.get(link.execution_owner)
                    if index is None:
                        index = ProgramIndex(body.graph)
                        indexes[link.execution_owner] = index
                    ports = _core_ports(index, link, body_origin)
                except (KeyError, TypeError, ValueError) as error:
                    issues.append("canonical ProgramGraph port boundary: " + str(error))
        completion = row["completion"]
        exit_kind = {"C_RETURN": ExitKind.NORMAL, "C_RAISE": ExitKind.RAISE,
                     "UNOBSERVED": None}.get(completion)
        if completion not in ("C_RETURN", "C_RAISE", "UNOBSERVED"):
            raise ValueError("unknown original stream completion kind")
        contract = decode(StreamContract, row["contract"])
        resource = StreamResourceInterface(row["receiver_reference"], row["receiver_kind"],
            row["receiver_type"], row["reference_identity_qualified"], contract)
        status = (SourceStreamStatus.CORE_CONNECTED if ports is not None else
                  SourceStreamStatus.SOURCE_ONLY if link.status is CallLinkStatus.VERIFIED else
                  SourceStreamStatus.SOURCE_BOUNDARY)
        calls.append(SourceStreamCall(attempt.anchor, invocation, captured, code, link,
            source, resource, completion, exit_kind, status, ports, tuple(issues)))
    return SourceStreamInterfaceView(observed["metadata"]["uri"], expected_sha256,
        tuple(calls), any(call.ports is not None for call in calls))


build_source_stream_interface_view = read_source_stream_interfaces


__all__ = [
    "SourceCompletionPort", "SourceStreamCall", "SourceStreamInterfaceView",
    "SourceStreamBodyOrigin", "SourceStreamOperationPorts", "SourceStreamStatus", "StreamResourceInterface",
    "build_source_stream_interface_view", "read_source_stream_interfaces",
]
