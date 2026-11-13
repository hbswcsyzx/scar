"""Observed Python entries selecting existing static call interfaces.

Each record keeps its own captured caller/callee activation. The interface
ports are declarations over shared canonical bodies, not globally installed
unconditional reference edges. Unobserved exception routes stay possible.
"""
from __future__ import annotations

import ast
from dataclasses import dataclass
import dis
import inspect

from scar.analysis.observed_call_bindings import (
    ObservedCallBinding, _check_owner, _dependency_session, _locate_body,
)
from scar.analysis.program_dependency_export import _Tables
from scar.ir.program.call_edges import CallRecordAnchor, CapturedSite, FrameCompletion, FrameExit
from scar.ir.program.contextual_calls import StaticCallInterface
from scar.ir.program.functions import (
    ArgumentKind, BindingOrigin, CallArgument, FormalPort, ParameterBinding, ParameterKind,
)
from scar.ir.program.model import LiteralOrigin, OperationResult, ReferenceValue, StateVersionValue, UseRole
from scar.ir.program.python_call_targets import PythonEntryBinding, PythonTargetKind
from scar.ir.program.source_call_bindings import SourceArgumentPort
from scar.ir.program.source_returns import SourceReturnSite
from scar.ir.program.static_calls import StaticCallFrontier, StaticStateEntryRoute
from scar.ir.program.structured import PythonProtocolKind, StructuredBodyModel
from scar.ir.record_codec import decode
from scar.trace.code_snapshot import code_key, code_parameters, site as code_site


_UNKNOWN_DEFAULT = object()
_IMPLICIT_ARGUMENT = object()
_PYTHON_TARGETS = (PythonTargetKind.FUNCTION, PythonTargetKind.BOUND_METHOD,
    PythonTargetKind.NORMALIZED_RECEIVER_FUNCTION)


def _known_receiver(target, entry):
    """Check the retained receiver ABI without guessing from parameter names."""
    if target.kind not in _PYTHON_TARGETS:
        raise ValueError('observed function interface requires a supported Python callable')
    known = target.kind is not PythonTargetKind.FUNCTION
    if known:
        if (target.receiver is None or target.layout.argcount < 1
                or entry.receiver_parameter_index != 0
                or entry.receiver_reference != target.receiver.reference):
            raise ValueError('observed receiver differs from its actual first-formal entry witness')
    elif (target.receiver is not None or entry.receiver_parameter_index is not None
            or entry.receiver_reference is not None):
        raise ValueError('an ordinary function cannot acquire an invented receiver witness')
    return known


@dataclass(frozen=True, slots=True)
class ObservedArgumentPack:
    formal: FormalPort
    origin: BindingOrigin
    actuals: tuple[CallArgument, ...]
    implicit: bool


@dataclass(frozen=True, slots=True)
class ObservedArgumentLayout:
    """Derived ABI alternative, never a serialized target/default verdict."""
    implicit_prefix: int
    arguments: tuple[SourceArgumentPort, ...]
    packs: tuple[ObservedArgumentPack, ...]
    missing: tuple[FormalPort, ...]
    implicit_formals: tuple[FormalPort, ...]


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
        _known_receiver(target, self.entry)
        if (self.entry.caller != target.caller or self.entry.attempt_index != target.attempt_index
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


def _own_nodes(root):
    """Only this execution scope, excluding nested callable/class bodies."""
    yield root
    for child in ast.iter_child_nodes(root):
        if isinstance(child, (ast.FunctionDef, ast.AsyncFunctionDef, ast.Lambda, ast.ClassDef)):
            continue
        yield from _own_nodes(child)


def _cleanup_returns(root, protected=False):
    """Returns whose lexical exit crosses cleanup, not sibling cleanups."""
    protected = (protected or isinstance(root, (ast.With, ast.AsyncWith, ast.ExceptHandler))
        or isinstance(root, (ast.Try, ast.TryStar)) and bool(root.finalbody))
    if type(root) is ast.Return and protected:
        yield root
    for child in ast.iter_child_nodes(root):
        if isinstance(child, (ast.FunctionDef, ast.AsyncFunctionDef, ast.Lambda, ast.ClassDef)):
            continue
        yield from _cleanup_returns(child, protected)


def _frame_terminal(body, terminal, structured, source):
    if (not any(link.operation == terminal.operation and link.source == source
                for link in body.operation_links)
            or not any(link.operation == terminal.operation and link.use == terminal.use
                and link.source == source and link.role == 'result' for link in body.use_links)):
        return False
    block, = (block for region in body.graph.regions for block in region.blocks if block.id == terminal.block)
    position = block.operations.index(terminal.operation)
    if position == 0:
        return False
    frame = block.operations[position - 1]
    if not any(protocol.operation == frame and protocol.kind is PythonProtocolKind.FRAME_EXIT
            and protocol.source == source for protocol in structured.protocols):
        return False
    if not any(link.operation == frame and link.source == source and link.role == 'held-payload'
            and body.index.use_site(link.use).use.value == terminal.value for link in body.use_links):
        return False
    operation = body.index.operations[terminal.operation]
    world = body.index.values[body.index.use_site(operation.terminator.values[1]).use.value]
    return type(world.origin) is OperationResult and world.origin.operation == frame


def _implicit_terminal(body, terminal, structured):
    value = body.index.values[terminal.value]
    return (type(value) is ReferenceValue and type(value.origin) is LiteralOrigin
        and value.origin.value is None
        and _frame_terminal(body, terminal, structured, body.namespace.source))


def _protected_return_site(body, code, exit_, returns, protected, interface):
    from scar.analysis.observed_return_routes import compiler_return_producer, cleanup_continuation
    producer = compiler_return_producer(code, exit_.return_site.offset)
    if producer is None or body.document.get('structured') is None:
        return None
    nodes = [node for node in returns if node in protected
        and tuple(producer.positions) == _positions(node.value if node.value is not None else node)]
    if len(nodes) != 1:
        return None
    source = body.context.refs.get(('Return', *_positions(nodes[0])))
    if source is None:
        return None
    structured = decode(StructuredBodyModel, body.document['structured'])
    if (structured.definition != body.namespace.definition or structured.region != body.namespace.region
            or structured.source != body.namespace.source):
        raise ValueError('protected return changed its original structured body identity')
    selected = [terminal for terminal in interface.normal_returns
        if cleanup_continuation(body, terminal, source) and _frame_terminal(body, terminal, structured, source)]
    return selected[0] if len(selected) == 1 else None


def _return_site(body, code, exit_, interface, *, issue=None):
    def opened(kind, detail):
        if issue is not None:
            issue(kind, detail)
        return None
    if (exit_.completion is not FrameCompletion.NORMAL
            or exit_.return_site.opname not in ('RETURN_VALUE', 'RETURN_CONST')):
        return None
    if code_key(code) != exit_.code or decode(CapturedSite, code_site(code, exit_.return_site.offset)) != exit_.return_site:
        raise ValueError('observed return offset/opcode/span differs from original code')
    roots = [node for node in ast.walk(body.context.tree) if isinstance(node, (ast.FunctionDef, ast.AsyncFunctionDef))
        and body.namespace.source is not None and _positions(node) == _positions(body.namespace.source)]
    if len(roots) != 1:
        return opened('OBSERVED_RETURN_FUNCTION_SCOPE_OPEN', 'No unique original function scope owns this compiler return.')
    owned = tuple(_own_nodes(roots[0]))
    returns = tuple(node for node in owned if type(node) is ast.Return)
    protected = tuple(_cleanup_returns(roots[0]))
    nodes = [node for node in returns
        if (exit_.return_site.position == _positions(node)
             or node.value is not None and exit_.return_site.position == _positions(node.value))]
    if nodes:
        if len(nodes) != 1:
            return None
        node, = nodes
        if node in protected:
            selected = _protected_return_site(body, code, exit_, returns, protected, interface)
            return selected if selected is not None else opened('OBSERVED_RETURN_CONTROL_PATH_OPEN',
                'The compiler stack slice or original typed cleanup continuation does not uniquely select this return.')
        positions = {_positions(node)}
        if node.value is not None:
            positions.add(_positions(node.value))
        selected = [terminal for terminal in interface.normal_returns
            if any(_positions(link.source) in positions
                for link in (*body.operation_links, *body.use_links)
                if link.operation == terminal.operation)]
        return selected[0] if len(selected) == 1 else None
    if protected:
        selected = _protected_return_site(body, code, exit_, returns, protected, interface)
        return selected if selected is not None else opened('OBSERVED_RETURN_CONTROL_PATH_OPEN',
            'The compiler value/cleanup route remains ambiguous; fallthrough is not selected from None or source position.')
    instructions = tuple(dis.get_instructions(code))
    number, = (number for number, instruction in enumerate(instructions)
               if instruction.offset == exit_.return_site.offset)
    current = instructions[number]
    previous = instructions[number - 1] if number else None
    constant_none = (current.opname == 'RETURN_CONST' and current.argval is None
        or current.opname == 'RETURN_VALUE' and not current.is_jump_target and previous is not None
        and previous.opname == 'LOAD_CONST' and previous.argval is None)
    if not constant_none or body.document.get('structured') is None:
        return opened('OBSERVED_IMPLICIT_RETURN_COMPILER_OPEN',
            'No direct compiler None return and recorded structured frame-exit source establish fallthrough.')
    structured = decode(StructuredBodyModel, body.document['structured'])
    if (structured.definition != body.namespace.definition or structured.region != body.namespace.region
            or structured.source != body.namespace.source):
        raise ValueError('implicit return changed its original structured body identity')
    selected = [terminal for terminal in interface.normal_returns if _implicit_terminal(body, terminal, structured)]
    if len(selected) != 1:
        return opened('OBSERVED_IMPLICIT_RETURN_TERMINAL_OPEN',
            'The original function-source literal/frame-exit terminal is missing or ambiguous; all normal alternatives remain.')
    return selected[0] if len(selected) == 1 else None


def _definition(owner, callee):
    if not _dependency_session(owner):
        qualified, signature, _, _ = callee.context.definitions[callee.namespace.definition]
        return qualified, signature
    qualified = owner.source_definition_reference(callee.namespace)
    signature = owner.signature_for(qualified, callee)
    from scar.analysis.function_interfaces import validate_body_interface
    validate_body_interface(callee, callee.interface, signature)
    return qualified, signature


def _code_layout(signature, layout, code):
    if (layout is None or (layout.argcount, layout.posonlyargcount, layout.kwonlyargcount, layout.flags)
            != (code.co_argcount, code.co_posonlyargcount, code.co_kwonlyargcount, code.co_flags)
            or layout.parameters != code_parameters(code)):
        raise LookupError('OBSERVED_CODE_LAYOUT_MISMATCH')
    kinds = ([ParameterKind.POSITIONAL_ONLY] * layout.posonlyargcount
        + [ParameterKind.POSITIONAL] * (layout.argcount - layout.posonlyargcount)
        + [ParameterKind.KEYWORD_ONLY] * layout.kwonlyargcount
        + ([ParameterKind.VAR_POSITIONAL] if layout.flags & inspect.CO_VARARGS else [])
        + ([ParameterKind.VAR_KEYWORD] if layout.flags & inspect.CO_VARKEYWORDS else []))
    # co_varnames orders keyword-only names before variadics; the source
    # signature orders *args before keyword-only declarations. Compare roles.
    if (signature is None or len(signature.parameters) != len(kinds)
            or any(tuple(parameter.name for parameter in signature.parameters if parameter.kind is kind)
                != tuple(name for role, name in zip(kinds, layout.parameters) if role is kind)
                for kind in ParameterKind)):
        raise LookupError('SOURCE_SIGNATURE_CODE_ROLES_OPEN')


def _argument_port(caller, operation, actual, callee, formal, name):
    if actual.use is None:
        return None
    use = caller.index.use_site(actual.use)
    if use.operation != operation.id or actual.use not in operation.invoke_arguments:
        raise ValueError('observed argument is not an original owned CALL Use')
    route = ParameterBinding(formal.slot, BindingOrigin.ARGUMENT, (actual.index,))
    return SourceArgumentPort(actual.index, caller.namespace, operation.id,
        actual.source, actual.use, use.use.value, callee.namespace,
        formal.slot, formal.value, name, route)


def _argument_layouts(caller, operation, source, actuals, callee, signature, arg0_missing, *, receiver_known=False):
    formals = {formal.slot: formal for formal in callee.interface.parameters}
    notes = {}
    def note(kind, detail, reference=source):
        notes[StaticCallFrontier(kind, detail, reference)] = None
    def port(parameter, actual):
        result = _argument_port(caller, operation, actual, callee, formals[parameter.slot], parameter.name)
        if result is None:
            note('OBSERVED_ARGUMENT_USE_OPEN', 'A source actual has no recovered owned CALL Use.', actual.source)
        return result
    expanded = any(actual.kind in (ArgumentKind.STARRED, ArgumentKind.DOUBLE_STARRED) for actual in actuals)
    if expanded:
        # An explicit keyword keeps its name through successful binding, but
        # unknown expansion gives no complete positional/packing alternative.
        known = []
        named = {parameter.name: parameter for parameter in signature.parameters
            if parameter.kind in (ParameterKind.POSITIONAL, ParameterKind.KEYWORD_ONLY)}
        for actual in actuals:
            if actual.kind is ArgumentKind.KEYWORD and actual.keyword in named:
                candidate = port(named[actual.keyword], actual)
                if candidate is not None:
                    known.append(candidate)
        note('OBSERVED_ARGUMENT_EXPANSION_OPEN',
            'Only recovered explicit keyword routes are retained; positional/packing and implicit receiver remain open.')
        return (), tuple(known), tuple(notes)
    kinds = {ParameterKind.POSITIONAL_ONLY: inspect.Parameter.POSITIONAL_ONLY,
        ParameterKind.POSITIONAL: inspect.Parameter.POSITIONAL_OR_KEYWORD,
        ParameterKind.VAR_POSITIONAL: inspect.Parameter.VAR_POSITIONAL,
        ParameterKind.KEYWORD_ONLY: inspect.Parameter.KEYWORD_ONLY,
        ParameterKind.VAR_KEYWORD: inspect.Parameter.VAR_KEYWORD}
    simulated = inspect.Signature(tuple(inspect.Parameter(parameter.name, kinds[parameter.kind],
        default=inspect.Parameter.empty if parameter.kind in (ParameterKind.VAR_POSITIONAL, ParameterKind.VAR_KEYWORD)
            else _UNKNOWN_DEFAULT) for parameter in signature.parameters))
    positional = tuple(actual for actual in actuals if actual.kind is ArgumentKind.POSITIONAL)
    keywords = {}
    for actual in actuals:
        if actual.kind is ArgumentKind.KEYWORD:
            if actual.keyword in keywords:
                raise ValueError('duplicate explicit keyword in original source arguments')
            keywords[actual.keyword] = actual
    layouts = []
    prefixes = (1,) if receiver_known else (0,) if arg0_missing else (0, 1)
    for prefix in prefixes:
        try:
            bound = simulated.bind(*((_IMPLICIT_ARGUMENT,) if prefix else ()), *positional, **keywords)
        except TypeError:
            continue  # Explicit ABI conflict only; missing defaults never refute.
        arguments, packs, missing, implicit = [], [], [], []
        for parameter in signature.parameters:
            formal = formals[parameter.slot]
            if parameter.kind in (ParameterKind.VAR_POSITIONAL, ParameterKind.VAR_KEYWORD):
                values = bound.arguments.get(parameter.name, () if parameter.kind is ParameterKind.VAR_POSITIONAL else {})
                values = tuple(values.values()) if parameter.kind is ParameterKind.VAR_KEYWORD else values
                packs.append(ObservedArgumentPack(formal,
                    BindingOrigin.VAR_POSITIONAL_PACK if parameter.kind is ParameterKind.VAR_POSITIONAL else BindingOrigin.VAR_KEYWORD_PACK,
                    tuple(value for value in values if value is not _IMPLICIT_ARGUMENT),
                    any(value is _IMPLICIT_ARGUMENT for value in values)))
            elif parameter.name not in bound.arguments:
                missing.append(formal)
            elif bound.arguments[parameter.name] is _IMPLICIT_ARGUMENT:
                implicit.append(formal)
            else:
                candidate = port(parameter, bound.arguments[parameter.name])
                if candidate is not None:
                    arguments.append(candidate)
        layouts.append(ObservedArgumentLayout(prefix, tuple(arguments), tuple(packs), tuple(missing), tuple(implicit)))
    common = tuple(argument for argument in layouts[0].arguments
        if all(argument in alternative.arguments for alternative in layouts[1:])) if layouts else ()
    if not receiver_known and (len(layouts) != 1 or layouts and layouts[0].implicit_prefix):
        note('OBSERVED_IMPLICIT_RECEIVER_LAYOUT_OPEN',
            'FUNCTION/receiver=None does not prove receiver absence; only common argument routes are unconditional.')
    if receiver_known:
        note('OBSERVED_BOUND_RECEIVER_SOURCE_OPEN',
            'The actual receiver/first-formal ABI is retained; its source receiver or descriptor provenance is not an explicit argument Use.')
    if not layouts:
        note('OBSERVED_ARGUMENT_LAYOUT_CONFLICT',
            'No supported zero/one-prefix ABI matches; observed entry/state/return remain separate facts.')
    parameters = {parameter.slot: parameter for parameter in signature.parameters}
    for alternative in layouts:
        for formal in alternative.missing:
            note('OBSERVED_CURRENT_DEFAULT_STATE_OPEN',
                'A viable ABI omits this formal; current defaults are not the source declaration value.', parameters[formal.slot].source)
        for pack in alternative.packs:
            note('OBSERVED_PARAMETER_PACK_OPEN',
                'Variadic tuple/dict packing retains dependencies, never identity with a source element.', parameters[pack.formal.slot].source)
        for formal in alternative.implicit_formals:
            note('OBSERVED_IMPLICIT_FORMAL_OPEN',
                'A viable ABI supplies this formal implicitly; no explicit source Use is invented.', parameters[formal.slot].source)
    return tuple(layouts), common, tuple(notes)


def _observed_interface(owner, caller, operation, source, semantic_call, actuals,
                        callee, qualified, signature, layouts, arguments, argument_frontiers):
    """Port assembly over the same original bodies, without _target.

    The two reused StaticCallSession routines below are pure algorithms over
    their supplied bodies/AST; they read no owner fields. No StaticCallSession
    instance, constructor state, source basis or duplicate body is manufactured.
    """
    from scar.analysis.static_calls import StaticCallSession
    from scar.analysis.function_binding import bind_call
    binding = (bind_call(signature, call=semantic_call, target=qualified.definition,
        source=source, arguments=actuals) if semantic_call is not None and len(layouts) == 1
        and layouts[0].implicit_prefix == 0 else None)
    completions, returns, frontiers = StaticCallSession._completion_routes(owner, caller, operation, callee)
    frontiers.extend(argument_frontiers)
    if binding is None:
        frontiers.append(StaticCallFrontier('OBSERVED_SOURCE_BINDING_PARTIAL',
            'No unique zero-prefix source plan is asserted; known parameter routes remain independent.', source))
    else:
        frontiers.extend(StaticCallFrontier('OBSERVED_SOURCE_PLAN_' + issue.kind.value,
            issue.detail, source) for issue in binding.issues)
    before, issue = StaticCallSession._caller_world(caller)
    state = None
    if issue is None:
        worlds = [use for use in operation.uses if use.id in operation.invoke_arguments
            and use.role is UseRole.STATE_CONTENT
            and type(caller.index.values[use.value]) is StateVersionValue
            and caller.index.values[use.value].location == before.location]
        if len(worlds) == 1:
            after = callee.index.values[callee.interface.world]
            state = StaticStateEntryRoute(worlds[0].id, worlds[0].value, before.location,
                after.id, after.location)
        else:
            issue = 'CALL_STATE_ENTRY_OPEN'
    if issue is not None:
        frontiers.append(StaticCallFrontier(issue, 'Original coarse CALL world interface remains unresolved.', source))
    frontiers.extend((StaticCallFrontier('OBSERVED_FUNCTION_ENVIRONMENT_OPEN',
        'Observed code/entry selects this interface only; function environment fields and their contents remain open.', source),
        StaticCallFrontier('FINE_EFFECTS_OPEN',
            'Parameter/return/state port correspondence does not close mod/ref, alias, escape or readiness.', source)))
    return StaticCallInterface(qualified, callee.namespace, ('OBSERVED_ENTRY_CODE_INTERFACE',),
        binding, arguments, returns, completions, state, tuple(frontiers))


def derive_observed_function_interfaces(owner, trace, observed, bindings, cache, *, argument_layouts=None):
    """Reuse one live static owner and original raw entry evidence, no lowering."""
    # A batch shares these original rows; rebuilding them would rescan the
    # complete trace once per batch. Strong owners prevent identity reuse.
    index = cache.get('observed-function-frame-index')
    if index is None:
        entries = {(item.caller.process_id, item.attempt_index): (item, anchor)
                   for item, anchor in zip(observed.entries, observed.entry_anchors)}
        frames = {item.invocation: item for item in trace.entries}
        exits = {}
        for item in trace.exits:
            exits.setdefault(item.invocation, []).append(item)
        captures = {(item.process_id, item.code.key): item for item in trace.frame_scan.captures}
        attempts = {(item.process_id, item.index): item for item in trace.attempts}
        index = trace, observed, entries, frames, exits, captures, attempts
        cache['observed-function-frame-index'] = index
    if index[0] is not trace or index[1] is not observed:
        raise ValueError('observed interface frame index belongs to another original trace')
    entries, frames, exits, captures, attempts = index[2:]
    records, issues = [], []
    if argument_layouts is not None and (type(argument_layouts) is not dict or argument_layouts):
        raise ValueError('argument_layouts must be an empty output dictionary')
    deferred = inspect.CO_GENERATOR | inspect.CO_COROUTINE | inspect.CO_ASYNC_GENERATOR
    for binding in bindings:
        target = binding.target
        key = target.caller.process_id, target.attempt_index

        def issue(kind, detail):
            issues.append({'kind': kind, 'process_id': key[0], 'attempt_index': key[1], 'detail': detail})

        # A class invocation's nested __init__ is not its direct callee.
        if target.kind not in _PYTHON_TARGETS:
            issue('OBSERVED_FUNCTION_INTERFACE_KIND_OPEN',
                  'Only observed Python functions and witnessed bound/normalized receivers are supported; class/native dispatch retains its boundary.')
            continue
        try:
            _check_owner(owner)
            if key not in entries:
                raise LookupError('ACTUAL_PYTHON_ENTRY_UNAVAILABLE')
            entry, entry_anchor = entries[key]
            receiver_known = _known_receiver(target, entry)
            frame = frames[entry.callee]
            if (frame.caller_invocation != target.caller or frame.code != target.code
                    or frame.anchor.index != entry.entry_index or len(frame.path) != 1
                    or frame.path[0] != binding.captured_site):
                raise ValueError('actual entry is not this direct synchronous CALL/code')
            if receiver_known:
                if not frame.parameters_complete or not frame.parameters:
                    raise LookupError('OBSERVED_RECEIVER_FIRST_FORMAL_UNAVAILABLE')
                if (entry.receiver_reference.startswith('weak:')
                        and frame.parameters[0].ref != entry.receiver_reference):
                    raise ValueError('observed receiver weak identity differs from the actual first formal')
            if frame.suspended or target.layout is not None and target.layout.flags & deferred:
                issue('OBSERVED_DEFERRED_ENTRY_OPEN',
                    'Suspended/deferred execution needs its own creation/resumption interface; none is synthesized.')
                continue
            caller_capture = captures.get((target.caller.process_id, binding.captured_code.key))
            if caller_capture is None:
                raise LookupError('CALLER_CAPTURED_CODE_UNAVAILABLE')
            caller, _ = _locate_body(owner, caller_capture, issues, cache)
            captured = captures.get((entry.callee.process_id, entry.code))
            if captured is None:
                raise LookupError('CALLEE_CAPTURED_CODE_UNAVAILABLE')
            callee, code = _locate_body(owner, captured, issues, cache)
            if callee.interface is None:
                raise LookupError('CALLEE_FUNCTION_INTERFACE_UNAVAILABLE')
            qualified, signature = _definition(owner, callee)
            _code_layout(signature, target.layout, code)
            operation = caller.index.operations[binding.call.node]
            links = [link for link in caller.operation_links if link.operation == operation.id
                     and link.source == binding.source]
            if len(links) != 1:
                raise LookupError('ORIGINAL_CALL_SOURCE_LINK_NOT_UNIQUE')
            link, = links
            node = caller.context.call_nodes.get(binding.source.atom_id)
            if type(node) is not ast.Call:
                raise LookupError('ORIGINAL_CALL_AST_UNAVAILABLE')
            if _dependency_session(owner):
                from scar.analysis.static_calls import StaticCallSession
                actuals, actual_issues = StaticCallSession._actuals(owner, caller, operation, node)
            else:
                actuals, actual_issues = owner._actuals(caller, operation, node)
            layouts, arguments, argument_frontiers = _argument_layouts(caller, operation, binding.source,
                actuals, callee, signature, attempts[key].arg0_missing, receiver_known=receiver_known)
            interface = _observed_interface(owner, caller, operation, binding.source,
                link.semantic_operation, actuals, callee, qualified, signature,
                layouts, arguments, (*actual_issues, *argument_frontiers))
            observed_exits = exits.get(entry.callee, ())
            exit_ = observed_exits[0] if len(observed_exits) == 1 else None
            selected_return = None
            if exit_ is not None:
                issue_count = len(issues)
                selected_return = _return_site(callee, code, exit_, interface, issue=issue)
                if exit_.completion is FrameCompletion.NORMAL and selected_return is None and len(issues) == issue_count:
                    issue('OBSERVED_NORMAL_RETURN_SITE_OPEN',
                          'A normal exit was observed but no unique original return terminal matches its source position.')
            else:
                issue('OBSERVED_FUNCTION_EXIT_UNAVAILABLE', 'No unique retained exit for this callee activation.')
            records.append(ObservedFunctionInterface(binding, entry, entry_anchor, frame.anchor,
                interface, exit_, selected_return))
            cache['observed-argument-layouts', binding.run_scope, target.caller, target.attempt_index] = layouts
            if argument_layouts is not None:
                argument_layouts[target.caller, target.attempt_index] = layouts
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


__all__ = ['ObservedFunctionInterface', 'ObservedArgumentLayout', 'ObservedArgumentPack', 'derive_observed_function_interfaces',
           'export_observed_function_interfaces', 'read_observed_function_interfaces']
