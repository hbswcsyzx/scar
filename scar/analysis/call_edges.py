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

from scar.analysis.function_interfaces import extract_signature
from scar.analysis.program_inventory import _Inventory
from scar.analysis.program_lowering import prepare_source
from scar.analysis.runtime_sources import _json_object
from scar.ir.program.call_edges import (
    CallEdgeBudget, CallEdgeCondition, CallEdgeIssue, CallEdgeIssueKind,
    CallEdgeModel, CallLinkStatus, CallRecordAnchor, CallSiteLink, CallTraceFile,
    CapturedCode, CapturedSite, CodeCapture, CodeSourceLink, CoreCallObservation,
    FrameCallEdge, FrameCompletion, FrameEntry, FrameExit, InvocationKey,
    NamedReference, ReferenceIdentityGroup, ReferenceIdentityRoute,
    ReferenceOccurrence, ReferenceRole, ReferenceRouteKind, ReferenceTrace,
)
from scar.ir.program.model import CompletionResult, ExitKind
from scar.ir.program.source import SourceRole
from scar.ir.record_codec import decode, encode
from scar.ir.semantics_v2 import Opcode
from scar.trace.code_snapshot import describe_code, site
from scar.trace.files import open_binary


_ENTER_FIELDS = {"index", "kind", "process_id", "thread_id", "invocation_id", "code", "parameters",
                 "parameters_complete", "caller", "caller_invocation_id", "ancestor_invocation_id",
                 "path", "path_complete", "caller_locals", "caller_locals_complete", "suspended"}
_EXIT_FIELDS = {"index", "kind", "process_id", "thread_id", "invocation_id", "code", "return_site",
                "completion", "return_ref", "locals", "locals_complete"}


def _canonical(value):
    return json.dumps(value, sort_keys=True, ensure_ascii=False, separators=(",", ":"), allow_nan=False)


def _sha(value):
    return hashlib.sha256(_canonical(value).encode()).hexdigest()


def _require(condition, detail):
    if not condition:
        raise ValueError(detail)


def _exact_int(value, name, minimum=0):
    _require(type(value) is int and value >= minimum, name + " must be an exact integer")
    return value


def _boolean(value, name):
    _require(type(value) is bool, name + " must be an exact boolean")
    return value


def _issue(kind, detail, anchor=None):
    return CallEdgeIssue(kind, detail, anchor)


def _span(node):
    return node.lineno, node.end_lineno, node.col_offset, node.end_col_offset


def _reference(reference, process, index):
    NamedReference("capture", reference)
    parts = reference.split(":")
    _require(int(parts[1]) == process, "reference token belongs to another process")
    if parts[0] == "snapshot":
        _require(int(parts[2]) == index, "snapshot token belongs to another event")
    return reference


def _bindings(value, process, index):
    result = decode(tuple[NamedReference, ...], value)
    _require(len({item.name for item in result}) == len(result), "captured names must be unique")
    for item in result:
        _reference(item.ref, process, index)
    return result


def _read_trace(trace, root, budget):
    trace = Path(trace).resolve()
    _require(trace.is_dir(), "call trace must be a directory")
    families = {}
    pattern = re.compile(r"call-(codes|events|meta)\.([1-9][0-9]*)\.(jsonl|json)(?:\.gz)?$")
    for path in sorted(trace.iterdir()):
        match = pattern.fullmatch(path.name)
        if not match:
            continue
        family, process, suffix = match.groups()
        _require((family == "meta") == (suffix == "json"), "call trace family has the wrong suffix")
        key = int(process), family
        _require(key not in families, "plain and gzip call trace files are ambiguous")
        _require(path.is_file() and not path.is_symlink(), "call trace files must be ordinary retained files")
        families[key] = path
    processes = sorted({process for process, family in families})
    _require(processes, "call trace has no call-codes/events/meta families")
    _require(len(processes) <= budget.max_processes, "call trace process budget exceeded")
    _require(all((process, family) in families for process in processes for family in ("codes", "events", "meta")),
             "each process requires codes, events and metadata")
    files, captures, entries, exits, metadata, issues = [], [], [], [], [], []
    codes, total_bytes, total_lines, references = {}, 0, 0, 0
    for process in processes:
        entries_start, exits_start = len(entries), len(exits)
        process_rows, code_count = [], 0
        for family in ("codes", "events", "meta"):
            path = families[process, family]
            logical = str(path.with_suffix("")) if path.suffix == ".gz" else str(path)
            digest, file_bytes, line_number, pieces = hashlib.sha256(), 0, 0, []
            with open_binary(path) as stream:
                while raw := stream.readline(budget.max_line_bytes + 1):
                    _require(len(raw) <= budget.max_line_bytes, "call trace line byte budget exceeded")
                    line_number += 1
                    total_lines += 1
                    file_bytes += len(raw)
                    total_bytes += len(raw)
                    _require(total_lines <= budget.max_lines and total_bytes <= budget.max_raw_bytes,
                             "call trace decompressed byte/line budget exceeded")
                    digest.update(raw)
                    if family == "meta":
                        pieces.append(raw)
                        continue
                    if not raw.strip():
                        continue
                    row = _json_object(raw, path=logical, line_number=line_number)
                    anchor = CallRecordAnchor(logical, line_number, hashlib.sha256(raw).hexdigest(), row.get("index"))
                    if family == "codes":
                        code = decode(CapturedCode, row)
                        _require(code.key not in codes or codes[code.key] == code, "one fingerprint has conflicting code descriptors")
                        codes[code.key] = code
                        captures.append(CodeCapture(code, anchor, process))
                        code_count += 1
                        _require(len(captures) <= budget.max_codes, "call trace code budget exceeded")
                    else:
                        process_rows.append((row, anchor))
                        _require(len(entries) + len(exits) + len(process_rows) <= budget.max_events,
                                 "call trace event budget exceeded")
            files.append(CallTraceFile(logical, family, process, digest.hexdigest(), file_bytes, line_number))
            if family == "meta":
                meta = _json_object(b"".join(pieces), path=logical, line_number=1)
                _require(meta.get("schema") == "scar.call-edge-trace" and type(meta.get("schema_version")) is int
                         and meta["schema_version"] == 1, "call collector schema/version mismatch")
                _require(type(meta.get("process_id")) is int and meta["process_id"] == process,
                         "collector metadata process disagrees with its filename")
                _require(meta.get("project_root") == str(root), "collector project root differs from replay")
                _require(meta.get("reference_contents_observed") is False
                         and meta.get("callable_environment_established") is False,
                         "collector metadata cannot certify contents or callable environments")
                for name in ("events", "invocations", "codes", "bytes", "dropped_events", "dropped_codes",
                             "unknown_exits", "suspended_exits", "open_invocations"):
                    _exact_int(meta.get(name), "collector " + name)
                _require(type(meta.get("errors")) is list and all(type(item) is str for item in meta["errors"]),
                         "collector errors must be a text array")
                _require(type(meta.get("limits")) is dict and all(type(value) is int and value > 0
                                                                 for value in meta["limits"].values()),
                         "collector limits must be positive integers")
                _require(meta["codes"] == code_count, "collector code count differs from retained records")
                _require(meta["events"] == len(process_rows), "collector event count differs from retained records")
                if "event_attempts" in meta:
                    attempts = _exact_int(meta["event_attempts"], "collector event_attempts")
                else:
                    attempts = meta["events"]
                if any(meta[name] for name in ("dropped_events", "dropped_codes", "open_invocations")) or meta["errors"]:
                    issues.append(_issue(CallEdgeIssueKind.TRACE_COLLECTION_GAP,
                                         "collector reports dropped, failed or still-open frame observations"))
                metadata.append(meta)
        previous = -1
        for row, anchor in process_rows:
            kind = row.get("kind")
            _require(kind in ("call_enter", "call_exit"), "unknown call edge event kind")
            _require(set(row) == (_ENTER_FIELDS if kind == "call_enter" else _EXIT_FIELDS),
                     "call edge event fields mismatch")
            index = _exact_int(row["index"], "event index")
            _require(previous < index <= attempts, "event indices must be increasing within collector attempts")
            previous = index
            _require(type(row["process_id"]) is int and row["process_id"] == process,
                     "event process disagrees with its file")
            identity = InvocationKey(process, row["thread_id"], row["invocation_id"])
            _require(type(row["code"]) is str and re.fullmatch(r"pycode-v2:[0-9a-f]{64}", row["code"]),
                     "event needs a stable captured code key")
            if kind == "call_enter":
                def related(value):
                    return InvocationKey(process, identity.thread_id, value) if value is not None else None
                path = decode(tuple[CapturedSite, ...], row["path"])
                caller = decode(CapturedSite | None, row["caller"])
                _require(len(path) <= budget.max_path, "captured frame path exceeds replay budget")
                _require(caller == (path[0] if path else None), "caller differs from the immediate path site")
                caller_id, ancestor = related(row["caller_invocation_id"]), related(row["ancestor_invocation_id"])
                _require(caller_id is None or len(path) == 1 and caller_id == ancestor
                         or not path and not row["path_complete"] and ancestor is None,
                         "a tracked immediate caller cannot skip intervening frames")
                parameters = _bindings(row["parameters"], process, index)
                caller_locals = _bindings(row["caller_locals"], process, index)
                references += len(parameters) + len(caller_locals)
                entry = FrameEntry(anchor, identity, row["code"], parameters,
                                   _boolean(row["parameters_complete"], "parameters_complete"), caller,
                                   caller_id, ancestor, path, _boolean(row["path_complete"], "path_complete"),
                                   caller_locals, _boolean(row["caller_locals_complete"], "caller_locals_complete"),
                                   _boolean(row["suspended"], "suspended"))
                if entry.parameters_complete and entry.code in codes:
                    _require(tuple(item.name for item in entry.parameters) == codes[entry.code].parameters,
                             "complete captured formals differ from the code descriptor")
                entries.append(entry)
            else:
                values = _bindings(row["locals"], process, index)
                references += len(values) + 1
                exits.append(FrameExit(anchor, identity, row["code"], decode(CapturedSite, row["return_site"]),
                                       FrameCompletion(row["completion"]), _reference(row["return_ref"], process, index),
                                       values, _boolean(row["locals_complete"], "locals_complete")))
            _require(references <= budget.max_references, "captured reference budget exceeded")
        meta = metadata[-1]
        process_entries, process_exits = entries[entries_start:], exits[exits_start:]
        entered = {entry.invocation for entry in process_entries}
        exited = {exit.invocation for exit in process_exits}
        _require(exited <= entered, "retained frame exit has no retained entry")
        _require(meta["invocations"] == len(process_entries), "collector invocation count differs from retained entries")
        _require(meta["open_invocations"] == len(entered - exited), "collector open count differs from unmatched entries")
        _require(meta["unknown_exits"] == sum(exit.completion is FrameCompletion.UNKNOWN for exit in process_exits),
                 "collector unknown completion count differs from retained exits")
        _require(meta["suspended_exits"] == sum(exit.completion is FrameCompletion.SUSPENDED for exit in process_exits),
                 "collector suspension count differs from retained exits")
        actual_bytes = sum(file.raw_bytes for file in files if file.process_id == process and file.family != "meta")
        _require(meta["bytes"] == actual_bytes, "collector byte count differs from retained code/events")
        _require(len(process_rows) <= attempts and attempts - len(process_rows) <= meta["dropped_events"],
                 "collector attempt gaps have no declared dropped events")
        if "invocation_attempts" in meta:
            invocations = _exact_int(meta["invocation_attempts"], "collector invocation_attempts")
            _require(len(process_entries) <= invocations <= len(process_entries) + meta["dropped_events"],
                     "collector invocation attempt count is inconsistent")
            _require(all(entry.invocation.invocation_id <= invocations for entry in process_entries),
                     "retained invocation exceeds attempted invocation IDs")
        if "active_frames" in meta:
            active = _exact_int(meta["active_frames"], "collector active_frames")
            _require(active <= meta["open_invocations"], "active frame count exceeds unmatched retained entries")
            if not meta["dropped_events"] and not meta["errors"]:
                _require(active == meta["open_invocations"], "complete collector active/open counts disagree")
        limits = meta["limits"]
        _require(all(name in limits for name in ("max_events", "max_bytes", "max_codes", "max_values", "max_path")),
                 "collector metadata is missing required collection limits")
        _require(attempts <= limits["max_events"] and actual_bytes <= limits["max_bytes"]
                 and code_count <= limits["max_codes"], "retained collection exceeds its declared limits")
        _require(all(len(entry.parameters) <= limits["max_values"] and len(entry.caller_locals) <= limits["max_values"]
                     and len(entry.path) <= limits["max_path"] for entry in process_entries)
                 and all(len(exit.locals) <= limits["max_values"] for exit in process_exits),
                 "retained capture vectors exceed collection limits")
        if "path_gaps" in meta:
            gaps = _exact_int(meta["path_gaps"], "collector path_gaps")
            _require(gaps <= len(process_entries) + meta["dropped_events"], "collector path gap count is inconsistent")
            _require(gaps or all(entry.path_complete or len(entry.path) == limits["max_path"] for entry in process_entries),
                     "short incomplete frame path has no declared capture gap")
        if "io_failed" in meta:
            _boolean(meta["io_failed"], "collector io_failed")
            if meta["io_failed"]:
                issues.append(_issue(CallEdgeIssueKind.TRACE_COLLECTION_GAP, "collector reports an I/O failure"))
    _require(len({entry.invocation for entry in entries}) == len(entries), "duplicate process/thread/invocation entry")
    _require(len({exit.invocation for exit in exits}) == len(exits), "duplicate process/thread/invocation exit")
    return str(trace), tuple(files), tuple(captures), tuple(entries), tuple(exits), tuple(metadata), tuple(issues)


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


class _Sources:
    def __init__(self, root, budget, inventory):
        self.root, self.budget, self.inventory = root, budget, inventory
        self.contexts, self.indexes, self.compiled, self.links, self.objects = {}, {}, {}, {}, {}
        self.context_errors = {}
        self.site_links, self.operand_links = {}, {}
        self.total_source_bytes = 0
        self.inventory_files = {file.snapshot.path: file for file in inventory.files} if inventory else {}
        self.bodies = {body.definition: body for file in inventory.files for body in file.bodies} if inventory else {}
        self.signatures = {signature.definition: signature for signature in inventory.interfaces.signatures} if inventory else {}
        self.ports = {body.definition: body for body in inventory.interfaces.bodies} if inventory else {}
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
            prepared = prepare_source(path, project_root=self.root)
            indexed = _Inventory(prepared, 0, 0).index()
            text, tree = prepared.text, prepared.tree
            for definition in indexed.definitions:
                node = next((node for node in ast.walk(tree) if hasattr(node, "args")
                             and hasattr(node, "end_lineno") and _span(node) == (
                                 definition.source.start_line, definition.source.end_line,
                                 definition.source.start_column, definition.source.end_column)), None)
                if node is not None and definition.id not in self.signatures:
                    self.signatures[definition.id] = extract_signature(prepared, definition, node=node)
            del prepared
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
            context = self.context(captured.filename)
        except (OSError, ValueError, SyntaxError, TypeError, KeyError, RecursionError) as error:
            self.context_errors[captured.filename] = str(error)
            result = CodeSourceLink(captured.key, CallLinkStatus.INCOMPLETE,
                                    issues=(_issue(CallEdgeIssueKind.SOURCE_BOUNDARY, str(error)),))
            self.links[captured.key] = result
            return result
        if captured.filename not in self.compiled:
            trials = []
            for optimize in (0, 1, 2):
                code = compile(context.text, captured.filename, "exec", dont_inherit=True, optimize=optimize)
                for child in _nested_codes(code):
                    try:
                        description = describe_code(child)
                    except ValueError:
                        continue  # A finite encoder boundary cannot certify this object.
                    trials.append((optimize, child, description))
            self.compiled[captured.filename] = trials
        matches = [(optimize, code) for optimize, code, description in self.compiled[captured.filename]
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
        if signature and ports:
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
            use, value = sources.operand(target.definition, reference, "return") if reference else (None, None)
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
            use, value = sources.operand(target.definition, reference, "return")
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


def link_calls(trace, project_root, inventory=None, budget=CallEdgeBudget()):
    """Read a collector directory and replay exact source/core relationships.

    The public CLI independently replays a supplied v4 inventory before calling
    here. Its complete canonical document is bound into this report as well.
    """
    _require(isinstance(budget, CallEdgeBudget), "link_calls requires a typed replay budget")
    root = Path(project_root).resolve()
    _require(root.is_dir(), "project root must be a directory")
    if inventory is not None:
        _require(inventory.to_dict()["schema_version"] == 4 and inventory.interfaces is not None,
                 "call/core linking requires the bound-formal v4 inventory")
        _require(inventory.discovery.project_root == str(root), "inventory project root differs from call replay")
    trace_path, files, captures, entries, exits, metadata, trace_issues = _read_trace(trace, root, budget)
    descriptors = {capture.code.key: capture.code for capture in captures}
    sources = _Sources(root, budget, inventory)
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
    references, routes = _references(tuple(edges), sources, metadata)
    model = CallEdgeModel(trace_path, str(root), budget, files, captures, tuple(edges), exits,
                          tuple(sources.links.values()), references, routes, tuple(issues), metadata,
                          _sha(inventory.to_dict()) if inventory is not None else None)
    return CallEdgeReport(model)


__all__ = ["CallEdgeReport", "link_calls"]
