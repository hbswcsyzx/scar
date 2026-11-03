"""Observed Python entries selecting existing static call interfaces.

Each record keeps its own captured caller/callee activation. The interface
ports are declarations over shared canonical bodies, not globally installed
unconditional reference edges. Unobserved exception routes stay possible.
"""
from __future__ import annotations

import ast
from dataclasses import dataclass
import inspect

from scar.analysis.observed_call_bindings import ObservedCallBinding, _locate_body
from scar.analysis.program_dependency_export import _Tables
from scar.ir.program.call_edges import CallRecordAnchor, CapturedSite, FrameCompletion, FrameExit
from scar.ir.program.contextual_calls import StaticCallInterface
from scar.ir.program.functions import BindingOrigin, CallBindingStatus, ParameterKind
from scar.ir.program.python_call_targets import PythonEntryBinding, PythonTargetKind
from scar.ir.program.source_returns import SourceReturnSite
from scar.ir.record_codec import decode
from scar.trace.code_snapshot import site as code_site


@dataclass(frozen=True, slots=True)
class ObservedFunctionInterface:
    binding: ObservedCallBinding
    entry: PythonEntryBinding
    entry_anchor: CallRecordAnchor
    frame_entry: CallRecordAnchor
    interface: StaticCallInterface
    observed_exit: FrameExit | None = None
    selected_return: SourceReturnSite | None = None

    def __post_init__(self):
        for value, kind in ((self.binding, ObservedCallBinding), (self.entry, PythonEntryBinding),
                (self.entry_anchor, CallRecordAnchor), (self.frame_entry, CallRecordAnchor),
                (self.interface, StaticCallInterface)):
            if type(value) is not kind:
                raise TypeError('observed function interface requires exact ' + kind.__name__)
            value.__post_init__()
        target = self.binding.target
        if (target.kind is not PythonTargetKind.FUNCTION or target.receiver is not None
                or self.entry.caller != target.caller or self.entry.attempt_index != target.attempt_index
                or self.entry.code != target.code or self.frame_entry.index != self.entry.entry_index
                or self.interface.body is None):
            raise ValueError('observed interface changed actual function/entry or lacks an original body')
        if self.observed_exit is not None:
            if (type(self.observed_exit) is not FrameExit
                    or self.observed_exit.invocation != self.entry.callee
                    or self.observed_exit.code != self.entry.code):
                raise ValueError('observed exit must belong to this exact callee activation/code')
        if self.selected_return is not None:
            if (type(self.selected_return) is not SourceReturnSite
                    or self.selected_return not in self.interface.normal_returns
                    or self.observed_exit is None
                    or self.observed_exit.completion is not FrameCompletion.NORMAL):
                raise ValueError('selected return requires this observed normal exit and original terminal')
            self.selected_return.__post_init__()


def _positions(value):
    if isinstance(value, ast.AST):
        return value.lineno, value.end_lineno, value.col_offset, value.end_col_offset
    return value.start_line, value.end_line, value.start_column, value.end_column


def _return_site(body, code, exit_, interface):
    if (exit_.completion is not FrameCompletion.NORMAL
            or exit_.return_site.opname not in ('RETURN_VALUE', 'RETURN_CONST')):
        return None
    if decode(CapturedSite, code_site(code, exit_.return_site.offset)) != exit_.return_site:
        raise ValueError('observed return offset/opcode/span differs from original code')
    nodes = [node for node in ast.walk(body.context.tree) if type(node) is ast.Return
        and (exit_.return_site.position == _positions(node)
             or node.value is not None and exit_.return_site.position == _positions(node.value))]
    if len(nodes) != 1:
        return None
    node, = nodes
    positions = {_positions(node)}
    if node.value is not None:
        positions.add(_positions(node.value))
    selected = []
    for terminal in interface.normal_returns:
        links = [link for link in body.operation_links if link.operation == terminal.operation]
        uses = [link for link in body.use_links
                if link.operation == terminal.operation and link.use == terminal.use]
        if any(_positions(link.source) in positions for link in (*links, *uses)):
            selected.append(terminal)
    return selected[0] if len(selected) == 1 else None


def derive_observed_function_interfaces(owner, trace, observed, bindings, cache):
    """Reuse one live static owner and original raw entry evidence, no lowering."""
    entries = {(item.caller.process_id, item.attempt_index): (item, anchor)
               for item, anchor in zip(observed.entries, observed.entry_anchors)}
    frames = {item.invocation: item for item in trace.entries}
    exits = {}
    for item in trace.exits:
        exits.setdefault(item.invocation, []).append(item)
    captures = {(item.process_id, item.code.key): item.code for item in trace.frame_scan.captures}
    records, issues = [], []
    unsupported = (inspect.CO_GENERATOR | inspect.CO_COROUTINE | inspect.CO_ASYNC_GENERATOR
                   | inspect.CO_VARARGS | inspect.CO_VARKEYWORDS)
    for binding in bindings:
        target = binding.target
        key = target.caller.process_id, target.attempt_index

        def issue(kind, detail):
            issues.append({'kind': kind, 'process_id': key[0], 'attempt_index': key[1], 'detail': detail})

        # A class invocation's nested __init__ is not its direct callee.
        if target.kind is not PythonTargetKind.FUNCTION or target.receiver is not None:
            issue('OBSERVED_FUNCTION_INTERFACE_KIND_OPEN',
                  'Only exact ordinary Python functions are supported; class/method/native dispatch retains its own boundary.')
            continue
        try:
            owner._check()
            if key not in entries:
                raise LookupError('ACTUAL_PYTHON_ENTRY_UNAVAILABLE')
            entry, entry_anchor = entries[key]
            frame = frames[entry.callee]
            if (frame.caller_invocation != target.caller or frame.code != target.code
                    or frame.anchor.index != entry.entry_index or len(frame.path) != 1
                    or frame.path[0] != binding.captured_site or frame.suspended):
                raise ValueError('actual entry is not this direct synchronous CALL/code')
            caller, _ = _locate_body(owner, binding.captured_code, issues, cache)
            captured = captures.get((entry.callee.process_id, entry.code))
            if captured is None:
                raise LookupError('CALLEE_CAPTURED_CODE_UNAVAILABLE')
            callee, code = _locate_body(owner, captured, issues, cache)
            if callee.interface is None:
                raise LookupError('CALLEE_FUNCTION_INTERFACE_UNAVAILABLE')
            layout = target.layout
            if (layout is None or layout.flags & unsupported or layout.kwonlyargcount
                    or tuple(code.co_varnames[:code.co_argcount]) != layout.parameters
                    or code.co_argcount != layout.argcount):
                raise LookupError('VARIADIC_KEYWORD_ONLY_OR_SUSPENDED_LAYOUT_OPEN')
            qualified, signature, _, _ = callee.context.definitions[callee.namespace.definition]
            if (signature is None or tuple(item.name for item in signature.parameters) != layout.parameters
                    or any(item.kind not in (ParameterKind.POSITIONAL, ParameterKind.POSITIONAL_ONLY)
                           for item in signature.parameters)):
                raise LookupError('SOURCE_SIGNATURE_LAYOUT_OPEN')
            operation = caller.index.operations[binding.call.node]
            links = [link for link in caller.operation_links if link.operation == operation.id
                     and link.source == binding.source]
            if len(links) != 1:
                raise LookupError('ORIGINAL_CALL_SOURCE_LINK_NOT_UNIQUE')
            link, = links
            node = caller.context.call_nodes.get(binding.source.atom_id)
            if (type(node) is not ast.Call or any(type(arg) is ast.Starred for arg in node.args)
                    or any(keyword.arg is None for keyword in node.keywords)):
                raise LookupError('EXPANDED_ARGUMENT_LAYOUT_OPEN')
            actuals, actual_issues = owner._actuals(caller, operation, node)
            if actual_issues or len(actuals) != layout.argcount:
                raise LookupError('FULLY_SUPPLIED_ARGUMENT_PORTS_UNAVAILABLE')
            interface = owner._target(caller, operation, binding.source, link.semantic_operation,
                actuals, callee.context.number, qualified.definition,
                ('OBSERVED_ENTRY_CODE_INTERFACE',), interface_only=True)
            plan = interface.binding
            if (plan is None or plan.status is not CallBindingStatus.CONDITIONAL
                    or any(route.origin is not BindingOrigin.ARGUMENT for route in plan.routes)
                    or len(interface.arguments) != layout.argcount
                    or interface.body != callee.namespace):
                raise LookupError('FULLY_SUPPLIED_PARAMETER_PLAN_UNAVAILABLE')
            observed_exits = exits.get(entry.callee, ())
            exit_ = observed_exits[0] if len(observed_exits) == 1 else None
            selected_return = None
            if exit_ is not None:
                selected_return = _return_site(callee, code, exit_, interface)
                if exit_.completion is FrameCompletion.NORMAL and selected_return is None:
                    issue('OBSERVED_NORMAL_RETURN_SITE_OPEN',
                          'A normal exit was observed but no unique original return terminal matches its source position.')
            else:
                issue('OBSERVED_FUNCTION_EXIT_UNAVAILABLE', 'No unique retained exit for this callee activation.')
            records.append(ObservedFunctionInterface(binding, entry, entry_anchor, frame.anchor,
                interface, exit_, selected_return))
        except (LookupError, ValueError, TypeError, OverflowError, TimeoutError) as error:
            issue('OBSERVED_FUNCTION_INTERFACE_UNBOUND', type(error).__name__ + ': ' + str(error))
            if isinstance(error, (OverflowError, TimeoutError)):
                break
    return tuple(records), tuple(issues)


def export_observed_function_interfaces(interfaces):
    table = _Tables()
    result = {'schema': 'scar.observed-function-interfaces', 'schema_version': 1,
        'interfaces': [table.pack(item) for item in interfaces],
        'observation_only': True, 'target_set_closed': False,
        'ports_are_conditional_declarations': True, 'transformation_authorized': False}
    result.update(table.tables)
    return result


def read_observed_function_interfaces(document):
    """Strong DTO readback only; no replay or execution of original inputs."""
    from scar.analysis.contextual_call_export import _MAX_BYTES, _Reader, _TABLES, _preflight
    from scar.ir.record_codec import loads
    if type(document) in (str, bytes):
        if len(document.encode() if type(document) is str else document) > _MAX_BYTES:
            raise ValueError('observed function interface document byte budget exceeded')
        document = loads(document)
    _preflight(document)
    fields = {'schema', 'schema_version', 'interfaces', 'observation_only', 'target_set_closed',
              'ports_are_conditional_declarations', 'transformation_authorized'}
    if (type(document) is not dict or set(document) != fields | set(_TABLES)
            or document['schema'] != 'scar.observed-function-interfaces'
            or type(document['schema_version']) is not int or document['schema_version'] != 1
            or document['observation_only'] is not True
            or document['ports_are_conditional_declarations'] is not True
            or document['target_set_closed'] is not False
            or document['transformation_authorized'] is not False):
        raise ValueError('invalid observed function interface schema/fields/claims')
    reader = _Reader(document)
    result = reader.unpack(tuple[ObservedFunctionInterface, ...], document['interfaces'])
    reader.validate_tables()
    return result


__all__ = ['ObservedFunctionInterface', 'derive_observed_function_interfaces',
           'export_observed_function_interfaces', 'read_observed_function_interfaces']
