"""Replay captured frame entries into source/core and reference identity routes.

Only the collector executes application code.  This module reads bounded raw
records and compiles current source without executing it.  Source/core links
and captured reference identities leave function environments and effects open.
"""
from __future__ import annotations

import ast
from collections import Counter, defaultdict, deque
from dataclasses import dataclass
import hashlib
import json
import os
from pathlib import Path
import re
import tokenize
from types import CodeType

from scar.analysis.call_trace_reader import CollectingCallSink, scan_call_trace
from scar.analysis.call_compilation import (
    UnsupportedCompilationFlags, compile_cache_key, future_flags_for,
)
from scar.analysis.function_interfaces import extract_signature
from scar.analysis.program_inventory import _Inventory
from scar.analysis.program_lowering import prepare_source
from scar.ir.program.call_edges import (
    CallEdgeBudget, CallEdgeCondition, CallEdgeIssue, CallEdgeIssueKind,
    CallEdgeModel, CallLinkStatus, CallRecordAnchor, CallSiteLink,
    CapturedCode, CapturedSite, CodeSourceLink, CoreCallObservation,
    FrameCallEdge, FrameCompletion, FrameEntry, FrameExit, InvocationKey,
    ReferenceIdentityGroup, ReferenceIdentityRoute,
    ReferenceOccurrence, ReferenceRole, ReferenceRouteKind, ReferenceTrace,
)
from scar.ir.program.frames import FrameExit as SourceFrameExit
from scar.ir.program.functions import BodyLoweringProfile
from scar.ir.program.structured import PythonProtocolKind
from scar.ir.program.compilation import CallCompilationProfile
from scar.ir.program.model import CompletionResult, ExitKind, TerminatorKind
from scar.ir.program.source import SourceRole
from scar.ir.record_codec import decode, encode
from scar.ir.semantics_v2 import Opcode
from scar.trace.code_snapshot import describe_code, site


def _canonical(value):
    return json.dumps(value, sort_keys=True, ensure_ascii=False, separators=(",", ":"), allow_nan=False)


def _sha(value):
    return hashlib.sha256(_canonical(value).encode()).hexdigest()


def _require(condition, detail):
    if not condition:
        raise ValueError(detail)


def _issue(kind, detail, anchor=None):
    return CallEdgeIssue(kind, detail, anchor)


def _span(node):
    return node.lineno, node.end_lineno, node.col_offset, node.end_col_offset


def _read_trace(trace, root, budget):
    """Compatibility adapter over the shared strict streaming decoder."""
    sink = CollectingCallSink()
    scanned = scan_call_trace(trace, root, budget, sink=sink)
    return (scanned.directory, scanned.files, scanned.captures, tuple(sink.entries),
            tuple(sink.exits), scanned.metadata, scanned.issues)


def _nested_codes(code):
    yield code
    for constant in code.co_consts:
        if isinstance(constant, CodeType):
            yield from _nested_codes(constant)


@dataclass(frozen=True)
class _LightSource:
    path: Path
    text: str
    tree: ast.Module
    snapshot: object
    references: dict
    nodes: dict
    return_nodes_by_position: dict


def _source_witness_projection(prepared):
    """Publish only the source/signature records consumed by this matcher."""
    indexed = _Inventory(prepared, 0, 0).source_witness_index()
    signatures = {}
    for definition in indexed.definitions:
        node = next((node for node in ast.walk(prepared.tree) if hasattr(node, "args")
                     and hasattr(node, "end_lineno") and _span(node) == (
                         definition.source.start_line, definition.source.end_line,
                         definition.source.start_column, definition.source.end_column)), None)
        if node is not None:
            signatures[definition.id] = extract_signature(prepared, definition, node=node)
    return indexed, prepared.text, prepared.tree, signatures


class _Sources:
    def __init__(
        self, root, budget, inventory, *, _source_workspace=None,
        compilation_profile=CallCompilationProfile.LEGACY_ZERO_FLAGS,
    ):
        if type(compilation_profile) is not CallCompilationProfile:
            raise ValueError("compilation profile must be a CallCompilationProfile")
        self.root, self.budget, self.inventory = root, budget, inventory
        self._source_workspace = _source_workspace
        self.compilation_profile = compilation_profile
        self.contexts, self.indexes, self.compiled, self.links, self.objects = {}, {}, {}, {}, {}
        self.context_errors = {}
        self.site_links, self.operand_links = {}, {}
        self.total_source_bytes = 0
        self.inventory_files = {file.snapshot.path: file for file in inventory.files} if inventory else {}
        self.bodies = {body.definition: body for file in inventory.files for body in file.bodies} if inventory else {}
        self.signatures = {signature.definition: signature for signature in inventory.interfaces.signatures} if inventory else {}
        self.ports = {body.definition: body for body in inventory.interfaces.bodies} if inventory else {}
        self.frames = {frame.definition: frame for frame in inventory.frames} if inventory else {}
        self.structured = {body.definition: body for body in inventory.structured} if inventory else {}
        self.core = {}
        for body in self.bodies.values():
            if body.graph is None:
                continue
            operations = {operation.id: operation for operation in body.graph.operations}
            uses = {use.id: use for operation in body.graph.operations for use in operation.uses}
            blocks = {block.id: block for region in body.graph.regions for block in region.blocks}
            self.core[body.definition] = body, operations, uses, blocks

    def context(self, filename):
        if filename in self.contexts:
            return self.contexts[filename]
        if filename in self.context_errors:
            raise ValueError(self.context_errors[filename])
        path = Path(filename)
        _require(path.is_absolute() and path.resolve().is_relative_to(self.root), "code filename is outside project root")
        _require(path == path.resolve() and path.is_file(), "code filename is missing or noncanonical")
        _require(len(self.contexts) < self.budget.max_source_files, "source file budget exceeded")
        size = path.stat().st_size
        _require(self.total_source_bytes + size <= self.budget.max_source_bytes, "source byte budget exceeded")
        self.total_source_bytes += size
        if filename in self.inventory_files:
            indexed = self.inventory_files[filename]
            with tokenize.open(path) as stream:
                text = stream.read()
            _require(indexed.snapshot.fingerprint == "sha256:" + hashlib.sha256(text.encode()).hexdigest(),
                     "inventory source snapshot differs from current code verification")
            tree = ast.parse(text, filename=filename)
        else:
            # The optional-inventory path builds source records once, then
            # drops the heavyweight semantic/opcode/control overlays.
            if self._source_workspace is not None:
                indexed, text, tree, signatures = self._source_workspace.source_projection(path)
            else:
                prepared = prepare_source(path, project_root=self.root)
                indexed, text, tree, signatures = _source_witness_projection(prepared)
                del prepared
            self.signatures.update((key, value) for key, value in signatures.items()
                                   if key not in self.signatures)
        references = {(item.ast_kind, item.source.start_line, item.source.end_line,
                       item.source.start_column, item.source.end_column): item.source for item in indexed.coverage}
        nodes = defaultdict(list)
        return_nodes_by_position = defaultdict(list)
        for node in ast.walk(tree):
            if hasattr(node, "end_lineno"):
                nodes[_span(node)].append(node)
            if isinstance(node, ast.Return) and node.value is not None:
                return_span, value_span = _span(node), _span(node.value)
                return_nodes_by_position[return_span].append(node)
                if value_span != return_span:
                    return_nodes_by_position[value_span].append(node)
        context = _LightSource(path, text, tree, indexed.snapshot, references, dict(nodes),
                               {position: tuple(matches)
                                for position, matches in return_nodes_by_position.items()})
        self.contexts[filename], self.indexes[filename] = context, indexed
        return context

    def code(self, captured):
        if captured.key in self.links:
            return self.links[captured.key]
        try:
            future_flags = future_flags_for(captured.flags, self.compilation_profile)
        except UnsupportedCompilationFlags as error:
            # A malformed/unknown code flag is local to this descriptor. It
            # must not poison the filename-wide source context cache.
            result = CodeSourceLink(
                captured.key, CallLinkStatus.INCOMPLETE,
                issues=(_issue(CallEdgeIssueKind.SOURCE_BOUNDARY, str(error)),),
            )
            self.links[captured.key] = result
            return result
        try:
            context = self.context(captured.filename)
        except (OSError, ValueError, SyntaxError, TypeError, KeyError, RecursionError) as error:
            self.context_errors[captured.filename] = str(error)
            result = CodeSourceLink(captured.key, CallLinkStatus.INCOMPLETE,
                                    issues=(_issue(CallEdgeIssueKind.SOURCE_BOUNDARY, str(error)),))
            self.links[captured.key] = result
            return result
        trials = []
        for optimize in (0, 1, 2):
            cache_key = compile_cache_key(
                context.path, context.snapshot.fingerprint,
                self.compilation_profile, captured.flags, optimize,
                compile_filename=captured.filename,
            )
            if cache_key not in self.compiled:
                try:
                    module_code = compile(
                        context.text, captured.filename, "exec",
                        flags=future_flags, dont_inherit=True, optimize=optimize,
                    )
                except (SyntaxError, ValueError, TypeError, OverflowError, RecursionError) as error:
                    if self.compilation_profile is CallCompilationProfile.LEGACY_ZERO_FLAGS:
                        raise
                    # Some future modes can be accepted by compile while the
                    # source frontend cannot describe that syntax. Preserve a
                    # concrete boundary instead of claiming a mismatch.
                    result = CodeSourceLink(
                        captured.key, CallLinkStatus.INCOMPLETE, context.snapshot,
                        issues=(_issue(
                            CallEdgeIssueKind.SOURCE_BOUNDARY,
                            "recorded compiler context is unsupported by source matching: "
                            + str(error),
                        ),),
                    )
                    self.links[captured.key] = result
                    return result
                compiled_trials = []
                for child in _nested_codes(module_code):
                    try:
                        description = describe_code(child)
                    except ValueError:
                        continue  # A finite encoder boundary cannot certify this object.
                    compiled_trials.append((child, description))
                self.compiled[cache_key] = tuple(compiled_trials)
            trials.extend((optimize, code, description)
                          for code, description in self.compiled[cache_key])
        matches = [(optimize, code) for optimize, code, description in trials
                   if description == encode(captured)]
        snapshot = context.snapshot
        if not matches:
            result = CodeSourceLink(captured.key, CallLinkStatus.MISMATCH, snapshot,
                                    issues=(_issue(CallEdgeIssueKind.CODE_MISMATCH,
                                                   "current source does not reproduce the complete captured code descriptor"),))
        else:
            self.objects[captured.key] = matches[0][1]
            indexed = self.indexes[captured.filename]
            candidates = [definition for definition in indexed.definitions
                          if definition.qualname == captured.qualname.replace(".<locals>.", ".")
                          and (definition.source.start_line == captured.first_line or any(
                              item.role.value == "DECORATOR" and item.source.start_line == captured.first_line
                              for item in definition.definition_inputs))]
            definition = candidates[0] if len(candidates) == 1 else None
            issues = () if definition else (_issue(CallEdgeIssueKind.TARGET_DEFINITION_MISSING,
                                                   "verified code has no unique inventoried function/class definition"),)
            result = CodeSourceLink(captured.key, CallLinkStatus.VERIFIED, snapshot,
                                    definition.id if definition else None, definition.source if definition else None,
                                    tuple(optimize for optimize, code in matches), issues)
        self.links[captured.key] = result
        return result

    def node(self, source):
        context = self.contexts[source.path]
        matches = context.nodes.get((source.start_line, source.end_line, source.start_column, source.end_column), ())
        # An Expr and its Call can share a span; callers need the expression.
        return next((node for node in matches if isinstance(node, ast.Call)), matches[0] if matches else None)

    def source(self, filename, node):
        context = self.contexts[filename]
        return context.references[(type(node).__name__, *_span(node))]

    def call_site(self, captured, descriptors):
        if captured not in self.site_links:
            self.site_links[captured] = self._call_site(captured, descriptors)
        return self.site_links[captured]

    def _call_site(self, captured, descriptors):
        description = descriptors.get(captured.code)
        if description is None:
            return CallSiteLink(captured, CallLinkStatus.INCOMPLETE,
                                issues=(_issue(CallEdgeIssueKind.MISSING_CODE, "caller code descriptor is missing"),))
        code_link = self.code(description)
        if code_link.status is not CallLinkStatus.VERIFIED:
            return CallSiteLink(captured, code_link.status, issues=code_link.issues)
        actual = decode(CapturedSite, site(self.objects[captured.code], captured.offset))
        if actual != captured or captured.position is None:
            return CallSiteLink(captured, CallLinkStatus.MISMATCH,
                                issues=(_issue(CallEdgeIssueKind.POSITION_MISMATCH,
                                               "captured opcode/complete span differs from the verified code offset"),))
        if captured.opname is None or not captured.opname.startswith("CALL"):
            return CallSiteLink(captured, CallLinkStatus.INCOMPLETE,
                                issues=(_issue(CallEdgeIssueKind.NO_SOURCE_CALL, "frame entry is not located at a source CALL instruction"),))
        indexed = self.indexes[description.filename]
        matches = [call for call in indexed.calls if
                   (call.source.start_line, call.source.end_line, call.source.start_column, call.source.end_column) == captured.position
                   and (code_link.definition is None or call.execution_owner == code_link.definition)]
        if len(matches) != 1:
            return CallSiteLink(captured, CallLinkStatus.INCOMPLETE,
                                issues=(_issue(CallEdgeIssueKind.NO_SOURCE_CALL, "instruction span does not identify one call in its verified owner"),))
        call, = matches
        core_matches = []
        if call.execution_owner in self.core:
            body, operations, uses, blocks = self.core[call.execution_owner]
            for link in body.metadata.operation_links:
                if link.source == call.source and link.opcode is Opcode.CALL and link.semantic_operation == call.semantic_operation:
                    operation = operations[link.operation]
                    callee_links = [item for item in body.metadata.use_links
                                    if item.operation == operation.id and item.role == "callee"]
                    if len(callee_links) == 1 and operation.invoke_arguments and callee_links[0].use == operation.invoke_arguments[0]:
                        use = uses[callee_links[0].use]
                        core_matches.append((body.graph.root, operation.id, use.id, use.value))
        core = core_matches[0] if len(core_matches) == 1 else (None, None, None, None)
        issues = () if len(core_matches) == 1 else (_issue(CallEdgeIssueKind.CORE_CALL_MISSING,
                                                          "source call has no unique emitted core CALL/callee operand"),)
        return CallSiteLink(captured, CallLinkStatus.VERIFIED, call.source, call.operation,
                            call.execution_owner, *core, issues)

    def operand(self, owner, source, role, operation=None):
        key = owner, source, role, operation
        if key not in self.operand_links:
            self.operand_links[key] = self._operand(owner, source, role, operation)
        return self.operand_links[key]

    def _operand(self, owner, source, role, operation=None):
        if owner not in self.core:
            return None, None
        body, operations, uses, blocks = self.core[owner]
        matches = [link for link in body.metadata.use_links if link.source == source and link.role == role
                   and (operation is None or link.operation == operation)]
        return (matches[0].use, uses[matches[0].use].value) if len(matches) == 1 else (None, None)

    def return_operand(self, owner, node, reference):
        interface = self.ports.get(owner)
        if interface is None or interface.profile not in (
                BodyLoweringProfile.BOUND_FRAME, BodyLoweringProfile.STRUCTURED_BODY,
                BodyLoweringProfile.STRUCTURED_ENV):
            # Preserve the v4 opaque-return correspondence, including its wire
            # UseID and ValueID, for complete historical report replay.
            return self.operand(owner, reference, "return")
        key = owner, reference, "frame-return-payload", None
        if key not in self.operand_links:
            self.operand_links[key] = self._frame_return_operand(owner, node, reference)
        return self.operand_links[key]

    def frame_rules(self, owner):
        """Use each source profile's actual frame model without fabricating one."""
        interface = self.ports.get(owner)
        if interface is None or owner not in self.core:
            return None
        body = self.bodies[owner]
        if interface.profile is BodyLoweringProfile.BOUND_FRAME:
            frame = self.frames.get(owner)
            return frame.rules if frame is not None and frame.region == body.graph.root else None
        if interface.profile in (BodyLoweringProfile.STRUCTURED_BODY, BodyLoweringProfile.STRUCTURED_ENV):
            model = self.structured.get(owner)
            return model.frame_rules if model is not None and model.region == body.graph.root else None
        return None

    def _structured_frame_exits(self, owner):
        """Project the validated FRAME_EXIT/terminal pair into its existing view.

        StructuredBodyModel owns its protocols and frame_rules.  It is not a
        FrameModel; this projection only names the original operations/Uses.
        """
        body, operations, uses, _ = self.core[owner]
        model = self.structured.get(owner)
        if model is None or model.region != body.graph.root:
            return ()
        operation_blocks = {operation: block for region in body.graph.regions
                            for block in region.blocks for operation in block.operations}
        links = {link.operation: link for link in body.metadata.operation_links}
        transitions = []
        for protocol in model.protocols:
            if protocol.kind is not PythonProtocolKind.FRAME_EXIT:
                continue
            block = operation_blocks.get(protocol.operation)
            held = operations.get(protocol.operation)
            if (block is None or len(block.operations) < 2 or block.operations[-2] != protocol.operation
                    or held is None or not held.uses):
                continue
            completion = operations.get(block.operations[-1])
            if (completion is None or completion.terminator is None
                    or completion.terminator.kind not in (TerminatorKind.RETURN, TerminatorKind.RAISE)
                    or len(completion.terminator.values) != 2):
                continue
            held_link, completion_link = links.get(held.id), links.get(completion.id)
            payload = uses.get(completion.terminator.values[0])
            if (held_link is None or completion_link is None
                    or held_link.source != protocol.source or completion_link.source != protocol.source
                    or payload is None or payload.value != held.uses[0].value):
                continue
            transitions.append(SourceFrameExit(held.id, protocol.source, completion.id, held.uses[0].id))
        return tuple(transitions)

    def _frame_return_operand(self, owner, node, reference):
        if owner not in self.core or self.frame_rules(owner) is None:
            return None, None
        body, operations, uses, blocks = self.core[owner]
        interface = self.ports[owner]
        transitions = (self.frames[owner].transitions
            if interface.profile is BodyLoweringProfile.BOUND_FRAME else self._structured_frame_exits(owner))
        returned_source = self.source(reference.path, node)
        matches = []
        for transition in transitions:
            if not isinstance(transition, SourceFrameExit) or transition.source != returned_source:
                continue
            operation = operations.get(transition.completion)
            held = operations.get(transition.operation)
            if (operation is None or held is None or operation.terminator is None
                    or operation.terminator.kind is not TerminatorKind.RETURN
                    or len(operation.terminator.values) != 2):
                continue
            payload = uses.get(operation.terminator.values[0])
            held_payload = next((use for use in held.uses if use.id == transition.payload), None)
            if payload is None or held_payload is None or payload.value != held_payload.value:
                continue
            links = [link for link in body.metadata.use_links
                     if link.operation == operation.id and link.use == payload.id
                     and link.source == returned_source and link.role == "result"]
            if len(links) == 1:
                matches.append((payload.id, payload.value))
        return matches[0] if len(matches) == 1 else (None, None)

    def result(self, call_site):
        if call_site.core_operation is None:
            return None
        body, operations, uses, blocks = self.core[call_site.execution_owner]
        operation = operations[call_site.core_operation]
        normal = [edge for edge in operation.terminator.successors if edge.kind is ExitKind.NORMAL]
        if len(normal) != 1:
            return None
        edge, = normal
        values = [blocks[edge.block].arguments[index] for index, argument in enumerate(edge.arguments)
                  if isinstance(argument, CompletionResult) and argument.index == 0]
        return values[0] if len(values) == 1 else None

    def parameter_port(self, definition, name):
        signature, ports = self.signatures.get(definition), self.ports.get(definition)
        if (signature and ports and len(signature.parameters) == len(ports.parameters)
                and tuple(parameter.slot for parameter in signature.parameters)
                == tuple(port.slot for port in ports.parameters)):
            return next(((parameter.source, port.value) for parameter, port in zip(signature.parameters, ports.parameters)
                         if parameter.name == name), (None, None))
        return None, None

    def returned_node(self, exit, code_link):
        if code_link.status is not CallLinkStatus.VERIFIED or exit.code not in self.objects:
            return None
        actual = decode(CapturedSite, site(self.objects[exit.code], exit.return_site.offset))
        if actual != exit.return_site or exit.return_site.code != exit.code or exit.completion is not FrameCompletion.NORMAL:
            return None
        if actual.opname not in ("RETURN_VALUE", "RETURN_CONST") or actual.position is None:
            return None
        context = self.contexts[code_link.snapshot.path]
        matches = context.return_nodes_by_position.get(actual.position, ())
        return matches[0] if len(matches) == 1 else None


def _identity(value):
    if isinstance(value, (FrameEntry, FrameExit)):
        return value.invocation
    if isinstance(value, InvocationKey):
        return value
    if type(value) is tuple and len(value) == 3:
        return InvocationKey(*value)
    raise ValueError("query needs a process/thread/invocation identity")


def _references(edges, sources, collection_metadata):
    occurrences, routes = [], []
    parameters, returned = {}, {}
    children_by_result = defaultdict(list)
    for edge in edges:
        if edge.caller_identity_verified:
            if edge.path:
                value = sources.result(edge.path[0])
                if value is not None:
                    children_by_result[edge.entry.caller_invocation, value].append(edge)
    incomplete_processes = {meta["process_id"] for meta in collection_metadata
                            if meta["dropped_events"] or meta["dropped_codes"] or meta["errors"]}
    parameters_by_frame = defaultdict(list)
    pending_locals = []

    def occurrence(edge, anchor, role, name, reference, owner=None, source=None, use=None, value=None):
        result = ReferenceOccurrence(anchor, edge.entry.invocation, owner or edge.entry.invocation,
                                     role, name, reference, source, use, value)
        occurrences.append(result)
        return result

    def route(destination, origin, kind, source=None, use=None):
        if destination.ref != origin.ref:
            return
        if destination.anchor != origin.anchor and not destination.ref.startswith("weak:"):
            return
        routes.append(ReferenceIdentityRoute(destination, origin, kind, source, use))

    for edge in edges:
        entry, target = edge.entry, edge.target
        for parameter in entry.parameters:
            source, value = sources.parameter_port(target.definition, parameter.name)
            parameters[entry.invocation, parameter.name] = occurrence(
                edge, entry.anchor, ReferenceRole.PARAMETER, parameter.name, parameter.ref,
                source=source, value=value,
            )
            parameters_by_frame[entry.invocation].append(parameters[entry.invocation, parameter.name])
        if edge.exit is not None:
            node = sources.returned_node(edge.exit, target) if edge.exit_verified else None
            reference = sources.source(target.snapshot.path, node.value) if node is not None else None
            use, value = sources.return_operand(target.definition, node, reference) if reference else (None, None)
            returned[entry.invocation] = occurrence(edge, edge.exit.anchor, ReferenceRole.RETURN,
                                                    "return", edge.exit.return_ref,
                                                    source=reference, use=use, value=value)

    def caller_parameter(destination, owner_edge):
        if destination.core_value is not None:
            matches = [value for value in parameters_by_frame[owner_edge.entry.invocation]
                       if value.core_value == destination.core_value]
        else:
            # Without a core, retain only the source's single `return formal`
            # rule. Arbitrary assignments or repeated calls are not inferred.
            definition_node = sources.node(owner_edge.target.source) if owner_edge.target.source else None
            simple = (isinstance(definition_node, (ast.FunctionDef, ast.AsyncFunctionDef))
                      and len(definition_node.body) == 1 and isinstance(definition_node.body[0], ast.Return)
                      and isinstance(definition_node.body[0].value, ast.Name)
                      and definition_node.body[0].value.id == destination.name)
            matches = [parameters[owner_edge.entry.invocation, destination.name]] if simple and (
                owner_edge.entry.invocation, destination.name) in parameters else []
        if len(matches) == 1:
            route(destination, matches[0], ReferenceRouteKind.SAME_FRAME_PARAMETER,
                  destination.source_reference, destination.core_use)

    def producer(destination, owner_edge, kind):
        if (destination.core_value is None or not destination.ref.startswith("weak:")
                or owner_edge.entry.invocation.process_id in incomplete_processes):
            return
        matches = []
        for child in children_by_result[owner_edge.entry.invocation, destination.core_value]:
            if (not child.caller_identity_verified or child.entry.caller_invocation != owner_edge.entry.invocation
                    or child.exit is None or not child.exit_verified or child.exit.completion is not FrameCompletion.NORMAL
                    or child.exit.anchor.index >= destination.anchor.index or not child.path
                    or child.target.status is not CallLinkStatus.VERIFIED):
                continue
            immediate = child.path[0]
            if child.exit.return_ref == destination.ref:
                matches.append(child)
        # Repeated executions/rebinding that do not select one producer remain
        # a query boundary, even when an object token happens to be shared.
        if len(matches) != 1:
            return
        child, = matches
        result = occurrence(child, child.exit.anchor, ReferenceRole.CALL_RESULT,
                            child.path[0].call.wire, child.exit.return_ref,
                            owner=owner_edge.entry.invocation, source=child.path[0].source,
                            value=destination.core_value)
        route(destination, result, kind, destination.source_reference, destination.core_use)
        route(result, returned[child.entry.invocation], ReferenceRouteKind.OBSERVED_CALL_RETURN,
              child.path[0].source)

    for edge in edges:
        entry, target = edge.entry, edge.target
        if entry.suspended:
            continue
        # A raw signature plus equal object tokens does not reveal receiver,
        # partial, descriptor or default-state adaptation.  Frame parameter
        # captures are observable; their caller-operand origins need a further
        # binding-evidence gate and are deliberately not routed here.
        if edge.exit is not None and edge.exit_verified:
            node = sources.returned_node(edge.exit, target)
            if node is None:
                continue
            reference = sources.source(target.snapshot.path, node.value)
            use, value = sources.return_operand(target.definition, node, reference)
            result = returned[entry.invocation]
            if isinstance(node.value, ast.Name):
                local_values = {item.name: item for item in edge.exit.locals}
                local_value = local_values.get(node.value.id)
                if local_value is not None and local_value.ref == edge.exit.return_ref:
                    local = occurrence(edge, edge.exit.anchor, ReferenceRole.EXIT_LOCAL, node.value.id,
                                       local_value.ref, source=reference, use=use, value=value)
                    route(result, local, ReferenceRouteKind.SOURCE_RETURN_LOCAL, reference, use)
                    pending_locals.append((local, edge))
            elif isinstance(node.value, ast.Call):
                producer(result, edge, ReferenceRouteKind.RETURN_CALL)
    for local, owner_edge in pending_locals:
        caller_parameter(local, owner_edge)
        producer(local, owner_edge, ReferenceRouteKind.CORE_CALL_RESULT)
    return tuple(dict.fromkeys(occurrences)), tuple(dict.fromkeys(routes))


@dataclass(frozen=True)
class CallEdgeReport:
    model: CallEdgeModel

    def summary(self):
        edges = self.model.edges
        return {
            "frame_entries": len(edges), "frame_exits": len(self.model.exits),
            "code_source_statuses": dict(sorted(Counter(link.status.value for link in self.model.code_links).items())),
            "verified_source_call_sites": sum(link.status is CallLinkStatus.VERIFIED for edge in edges for link in edge.path),
            "core_call_observations": sum(link.core_operation is not None for edge in edges for link in edge.path),
            "direct_core_call_observations": sum(bool(edge.path and edge.path[0].core_operation is not None) for edge in edges),
            "target_body_observations": sum(edge.target_body is not None for edge in edges),
            "tracked_immediate_callers": sum(edge.caller_identity_verified for edge in edges),
            "tracked_ancestors_through_intervening_frames": sum(edge.ancestor_identity_verified and len(edge.path) > 1 for edge in edges),
            "verified_normal_frame_exits": sum(edge.exit_verified for edge in edges),
            "reference_occurrences": len(self.model.references), "reference_routes": len(self.model.reference_routes),
            "issues": len(self.model.issues) + sum(len(edge.issues) for edge in edges),
            "target_executed_by_linker": False, "function_environment_established": False,
            "contents_or_effects_established": False, "transformation_authorized": False,
        }

    def to_dict(self):
        return {"schema": "scar.call-edge-links", "schema_version": 1, "model": encode(self.model),
                "summary": self.summary(), "target_executed_by_linker": False,
                "function_environment_established": False, "contents_or_effects_established": False,
                "transformation_authorized": False}

    @classmethod
    def from_dict(cls, document, *, inventory=None, verification_budget=CallEdgeBudget()):
        _require(isinstance(verification_budget, CallEdgeBudget), "call replay requires a typed independent verifier budget")
        _require(type(document) is dict and set(document) == {
            "schema", "schema_version", "model", "summary", "target_executed_by_linker",
            "function_environment_established", "contents_or_effects_established", "transformation_authorized"},
            "call link report fields mismatch")
        _require(document["schema"] == "scar.call-edge-links" and type(document["schema_version"]) is int
                 and document["schema_version"] == 1, "call link report schema/version mismatch")
        model = decode(CallEdgeModel, document["model"])
        for name in model.budget.__dataclass_fields__:
            _require(getattr(model.budget, name) <= getattr(verification_budget, name),
                     "call report exceeds independent verifier budget: " + name)
        rebuilt = link_calls(model.trace, model.project_root, inventory=inventory, budget=model.budget)
        _require(_canonical(rebuilt.to_dict()) == _canonical(document),
                 "call links differ from current raw trace/source/inventory replay")
        return rebuilt

    def parents(self, invocation, *, include_ancestors=False):
        identity = _identity(invocation)
        return tuple(edge for edge in self.model.edges if edge.entry.invocation == identity
                     and (edge.caller_identity_verified or include_ancestors and edge.ancestor_identity_verified))

    def children(self, invocation, *, include_ancestors=False):
        identity = _identity(invocation)
        return tuple(edge for edge in self.model.edges
                     if edge.caller_identity_verified and edge.entry.caller_invocation == identity
                     or include_ancestors and edge.ancestor_identity_verified and edge.entry.ancestor_invocation == identity)

    def by_core_call(self, operation, *, include_intervening_frames=True):
        key = operation.wire if hasattr(operation, "wire") else operation
        return tuple(CoreCallObservation(edge.entry.invocation, edge.entry.anchor, index, link, edge.target,
                                         edge.target_body, index > 0)
                     for edge in self.model.edges for index, link in enumerate(edge.path)
                     if link.core_operation is not None and link.core_operation.wire == key
                     and (include_intervening_frames or index == 0))

    def trace_reference(self, invocation, *, role=ReferenceRole.RETURN, name=None):
        identity = _identity(invocation)
        if not isinstance(role, ReferenceRole):
            role = ReferenceRole(role)
        roots = [occurrence for occurrence in self.model.references
                 if occurrence.owner == identity and occurrence.role is role
                 and (name is None or occurrence.name == name)]
        # Prefer the source/core-refined return occurrence over its raw copy.
        if role is ReferenceRole.RETURN:
            refined = [occurrence for occurrence in roots if occurrence.source_reference is not None]
            roots = refined or roots
        adjacency = defaultdict(list)
        for route in self.model.reference_routes:
            adjacency[route.destination].append(route)
        visited, traversed, queue = set(), [], deque(roots)
        while queue:
            occurrence = queue.popleft()
            if occurrence in visited:
                continue
            visited.add(occurrence)
            for route in adjacency[occurrence]:
                traversed.append(route)
                queue.append(route.source)
        grouped = defaultdict(list)
        for occurrence in self.model.references:
            if occurrence in visited:
                grouped[occurrence.ref].append(occurrence)
        groups = tuple(ReferenceIdentityGroup(reference, tuple(values), len({item.anchor for item in values}) > 1)
                       for reference, values in sorted(grouped.items()))
        issues = []
        if not roots:
            issues.append(_issue(CallEdgeIssueKind.REFERENCE_FLOW_GAP, "requested invocation/reference capture is missing"))
        for occurrence in visited:
            if not adjacency[occurrence] and occurrence.role is ReferenceRole.PARAMETER:
                edge = next((edge for edge in self.model.edges if edge.entry.invocation == occurrence.owner), None)
                if edge is not None and (edge.entry.caller_invocation is not None
                                         or edge.entry.ancestor_invocation is not None
                                         or edge.path and edge.path[0].status is CallLinkStatus.VERIFIED):
                    issues.append(_issue(CallEdgeIssueKind.ARGUMENT_ROUTING_UNVERIFIED,
                                         "actual-to-formal origin requires callable/receiver/partial/default-state binding evidence",
                                         occurrence.anchor))
            elif not adjacency[occurrence]:
                issues.append(_issue(CallEdgeIssueKind.REFERENCE_FLOW_GAP,
                                     "identity route stops at an unverified, non-Name, ambiguous or unavailable source/core flow",
                                     occurrence.anchor))
        return ReferenceTrace(identity, groups, tuple(dict.fromkeys(traversed)), tuple(dict.fromkeys(issues)))


def _link_call_model(trace, project_root, inventory=None, budget=CallEdgeBudget(), *,
                     compilation_profile=CallCompilationProfile.LEGACY_ZERO_FLAGS,
                     frame_scan=None, entries=None, exits=None, allow_v6=False,
                     include_identity_routes=True):
    """Compose frame/source links from a local scan, keeping report policy separate.

    Only in-process readers supply ``frame_scan``. Public report decoders always
    rescan their original raw input; serialized models never enter this path as
    a substitute for scanning. The legacy wrapper retains its v4/v5 policy.
    """
    _require(isinstance(budget, CallEdgeBudget), "link_calls requires a typed replay budget")
    root = Path(project_root).resolve()
    _require(root.is_dir(), "project root must be a directory")
    if inventory is not None:
        versions = (5, 6, 7, 8) if allow_v6 else (4, 5)
        _require(inventory.to_dict()["schema_version"] in versions and inventory.interfaces is not None,
                 "operand/core linking requires an explicit frame/structured v5-v8 inventory" if allow_v6 else
                 "call/core linking requires a bound-formal v4 or bound-frame v5 inventory")
        _require(inventory.discovery.project_root == str(root), "inventory project root differs from call replay")
    if frame_scan is None:
        trace_path, files, captures, entries, exits, metadata, trace_issues = _read_trace(trace, root, budget)
    else:
        _require(frame_scan.directory == str(Path(trace).resolve())
                 and type(entries) is tuple and type(exits) is tuple,
                 "local frame scan must bind its original trace and observations")
        trace_path, files, captures = frame_scan.directory, frame_scan.files, frame_scan.captures
        metadata, trace_issues = frame_scan.metadata, frame_scan.issues
    descriptors = {capture.code.key: capture.code for capture in captures}
    sources = (_Sources(root, budget, inventory)
               if compilation_profile is CallCompilationProfile.LEGACY_ZERO_FLAGS else
               _Sources(root, budget, inventory, compilation_profile=compilation_profile))
    for descriptor in descriptors.values():
        sources.code(descriptor)
    entry_index = {entry.invocation: entry for entry in entries}
    exit_index = {exit.invocation: exit for exit in exits}
    expected_ancestors, invalid_intervals, active = {}, set(), defaultdict(list)
    ordered = sorted([(entry.anchor.index, entry.invocation.process_id, True, entry) for entry in entries]
                     + [(exit.anchor.index, exit.invocation.process_id, False, exit) for exit in exits],
                     key=lambda item: (item[1], item[0]))
    for index, process, entering, observation in ordered:
        key = process, observation.invocation.thread_id
        stack = active[key]
        if entering:
            expected_ancestors[observation.invocation] = stack[-1] if stack else None
            stack.append(observation.invocation)
        elif stack and stack[-1] == observation.invocation:
            stack.pop()
        elif observation.invocation in stack:
            position = stack.index(observation.invocation)
            invalid_intervals.update(stack[position:])
            stack.pop(position)
    incomplete_processes = {meta["process_id"] for meta in metadata
                            if meta["dropped_events"] or meta["dropped_codes"] or meta["errors"] or meta.get("io_failed")}
    issues, edges = list(trace_issues), []
    for entry in entries:
        descriptor = descriptors.get(entry.code)
        target = sources.code(descriptor) if descriptor else CodeSourceLink(
            entry.code, CallLinkStatus.INCOMPLETE,
            issues=(_issue(CallEdgeIssueKind.MISSING_CODE, "callee code descriptor is missing", entry.anchor),))
        path = tuple(sources.call_site(captured, descriptors) for captured in entry.path)
        edge_issues = []
        if not entry.path:
            edge_issues.append(_issue(CallEdgeIssueKind.NO_CALLER, "frame has no captured immediate caller", entry.anchor))
        if not entry.path_complete:
            edge_issues.append(_issue(CallEdgeIssueKind.INCOMPLETE_PATH, "collector stopped before a tracked ancestor", entry.anchor))
        if entry.suspended:
            edge_issues.append(_issue(CallEdgeIssueKind.SUSPENDED_FRAME,
                                      "generator/async resume and suspension are not synchronous body calls", entry.anchor))

        def related(identity, expected_code):
            if identity is None:
                return False
            if entry.invocation.process_id in incomplete_processes:
                edge_issues.append(_issue(CallEdgeIssueKind.TRACE_COLLECTION_GAP,
                                          "incomplete collection cannot certify the active parent frame", entry.anchor))
                return False
            other = entry_index.get(identity)
            if other is None:
                edge_issues.append(_issue(CallEdgeIssueKind.INVOCATION_MISSING,
                                          "captured parent invocation has no retained frame entry", entry.anchor))
                return False
            parent_exit, child_exit = exit_index.get(identity), exit_index.get(entry.invocation)
            valid = (other.code == expected_code and other.anchor.index < entry.anchor.index
                     and identity != entry.invocation and identity == expected_ancestors.get(entry.invocation)
                     and identity not in invalid_intervals and entry.invocation not in invalid_intervals)
            if parent_exit is not None:
                valid = valid and parent_exit.code == other.code and entry.anchor.index < parent_exit.anchor.index
                if child_exit is not None:
                    valid = valid and child_exit.anchor.index < parent_exit.anchor.index
            if not valid:
                edge_issues.append(_issue(CallEdgeIssueKind.INVOCATION_MISMATCH,
                                          "captured parent identity/code/order disagree", entry.anchor))
                return False
            if parent_exit is None or child_exit is None:
                edge_issues.append(_issue(CallEdgeIssueKind.INVOCATION_MISSING,
                                          "missing frame exit leaves the parent/child lifetime interval incomplete", entry.anchor))
                return False
            return True

        caller_verified = related(entry.caller_invocation, entry.caller.code if entry.caller else None)
        ancestor_verified = related(entry.ancestor_invocation, entry.path[-1].code if entry.path else None)
        if (entry.invocation.process_id not in incomplete_processes and entry.path_complete
                and expected_ancestors.get(entry.invocation) is not None and entry.ancestor_invocation is None):
            edge_issues.append(_issue(CallEdgeIssueKind.INVOCATION_MISMATCH,
                                      "complete captured path omits the currently active tracked ancestor", entry.anchor))
        if any(issue.kind is CallEdgeIssueKind.INVOCATION_MISMATCH for issue in edge_issues):
            path = tuple(CallSiteLink(link.site, CallLinkStatus.INCOMPLETE,
                                      issues=(_issue(CallEdgeIssueKind.INVOCATION_MISMATCH,
                                                     "inconsistent frame ancestry cannot anchor this caller/source/core observation",
                                                     entry.anchor),)) for link in path)
            caller_verified = ancestor_verified = False
        exit = exit_index.get(entry.invocation)
        exit_verified = False
        if exit is not None:
            if exit.code != entry.code or exit.return_site.code != entry.code or exit.anchor.index <= entry.anchor.index:
                edge_issues.append(_issue(CallEdgeIssueKind.INVOCATION_MISMATCH,
                                          "frame exit code/order differs from its entry", exit.anchor))
            elif target.status is CallLinkStatus.VERIFIED:
                replay_site = decode(CapturedSite, site(sources.objects[entry.code], exit.return_site.offset))
                exit_verified = (replay_site == exit.return_site and not entry.suspended
                                 and exit.completion is FrameCompletion.NORMAL
                                 and replay_site.opname in ("RETURN_VALUE", "RETURN_CONST"))
                if replay_site != exit.return_site:
                    edge_issues.append(_issue(CallEdgeIssueKind.POSITION_MISMATCH,
                                              "frame return site differs from verified current code", exit.anchor))
        target_body = sources.bodies.get(target.definition)
        region = target_body.graph.root if (target.status is CallLinkStatus.VERIFIED
                                           and target_body and target_body.graph and not entry.suspended) else None
        if region is None:
            edge_issues.append(_issue(CallEdgeIssueKind.TARGET_BODY_MISSING,
                                      "verified callee has no emitted synchronous body port", entry.anchor))
        edges.append(FrameCallEdge(entry, target, path, region, caller_verified, ancestor_verified,
                                   exit, exit_verified, tuple(edge_issues)))
    for exit in exits:
        if exit.invocation not in entry_index:
            issues.append(_issue(CallEdgeIssueKind.INVOCATION_MISSING,
                                 "frame exit has no retained entry in the same process/thread", exit.anchor))
    references, routes = (_references(tuple(edges), sources, metadata)
                          if include_identity_routes else ((), ()))
    model = CallEdgeModel(trace_path, str(root), budget, files, captures, tuple(edges), exits,
                          tuple(sources.links.values()), references, routes, tuple(issues), metadata,
                          _sha(inventory.to_dict()) if inventory is not None else None)
    return model, sources


def link_calls(trace, project_root, inventory=None, budget=CallEdgeBudget()):
    """Replay historical v1 frame/source/core links with their original policy."""
    model, _ = _link_call_model(trace, project_root, inventory, budget)
    return CallEdgeReport(model)


__all__ = ["CallEdgeReport", "link_calls"]
