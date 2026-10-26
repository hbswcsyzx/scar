"""Replay operand occurrences into conditional core-reference routes.

Neither equal tokens nor static candidate signatures select a route. Actual
position, a complete dynamic instruction window and the unique direct entry
handshake supply its origin. The public report independently replays inputs.
"""
from __future__ import annotations

import ast
from bisect import bisect_left
from collections import defaultdict, deque
import dis
import inspect

from scar.ir.program.call_edges import CallLinkStatus, FrameCompletion, InvocationKey
from scar.ir.program.call_operands import (
    CALL_WINDOWS_RULE, LOAD_OCCURRENCES_RULE, CallableKind, LoadNamespace,
)
from scar.ir.program.call_operand_routes import (
    ArgumentRoute, CompletionRoute, CoreReferenceKind, CoreReferenceRoute,
    CoreReferenceTemplate, CoreReferenceValue, FrameRouteObligations,
    InvocationReturn, OperandQueryRouteKind, OperandQueryStep, OperandReferenceNode,
    OperandReferenceTrace, OperandRouteBudget, OperandRouteIssue,
    OperandRouteIssueKind as Issue, OperandRouteModel, ReferenceConsistency,
)
from scar.ir.program.functions import BodyLoweringProfile, ParameterKind
from scar.ir.program.model import (
    BlockArgument, CompletionResult, ExitKind, LiteralOrigin, OperationResult,
    ReferenceValue, StateVersionValue, TerminatorKind, UseRole,
)
from scar.ir.record_codec import encode
from scar.ir.semantics_v2 import Opcode
from scar.trace.code_snapshot import site as code_site


class _Boundary(Exception):
    def __init__(self, kind, detail):
        self.kind, self.detail = kind, detail


def _need(condition, kind, detail):
    if not condition:
        raise _Boundary(kind, detail)


def _span(node):
    return node.lineno, node.end_lineno, node.col_offset, node.end_col_offset


def _consistency(left, right):
    """Only comparable weak identities can contradict a positional rule."""
    if left is not None and right is not None and left.startswith('weak:') and right.startswith('weak:'):
        _need(left == right, Issue.REFERENCE_CONTRADICTION,
              'captured weak identities contradict the proposed positional route')
        return ReferenceConsistency.AGREES
    return ReferenceConsistency.UNKNOWN


def _layout_matches(layout, code):
    count = code.co_argcount + code.co_kwonlyargcount
    count += bool(code.co_flags & inspect.CO_VARARGS) + bool(code.co_flags & inspect.CO_VARKEYWORDS)
    return (layout.argcount == code.co_argcount and layout.posonlyargcount == code.co_posonlyargcount
            and layout.kwonlyargcount == code.co_kwonlyargcount and layout.flags == code.co_flags
            and layout.parameters == code.co_varnames[:count])


def _checked_formal_ports(body, interface, signature, values, blocks, definition):
    region = next((region for region in body.graph.regions if region.id == body.graph.root), None)
    _need(region is not None and interface.region == region.id
          and interface.definition == signature.definition == definition,
          Issue.SOURCE_CORE_BOUNDARY, 'formal interface has no matching root/definition')
    entry = blocks[region.entry]
    _need(len(signature.parameters) == len(interface.parameters)
          and tuple(parameter.slot for parameter in signature.parameters)
          == tuple(port.slot for port in interface.parameters),
          Issue.SOURCE_CORE_BOUNDARY, 'explicit formal slots do not cover the declared signature')
    for port in interface.parameters:
        value = values.get(port.value)
        _need(type(value) is ReferenceValue and isinstance(value.origin, BlockArgument)
              and value.region == region.id and value.origin.block == entry.id
              and 0 <= value.origin.index < len(entry.arguments)
              and entry.arguments[value.origin.index] == port.value,
              Issue.SOURCE_CORE_BOUNDARY, 'formal is not its exact declared entry reference port')
    if interface.profile is BodyLoweringProfile.STRUCTURED_ENV:
        environments = [environment for environment in body.graph.environments if environment.region == region.id]
        _need(len(environments) == 1, Issue.SOURCE_CORE_BOUNDARY,
              'environment body has no unique existing environment interface')
        environment, = environments
        layouts = [layout for layout in body.graph.function_entries if layout.environment == environment.id]
        _need(len(layouts) == 1 and layouts[0].parameters == interface.parameters
              and environment.code_definition == definition,
              Issue.SOURCE_CORE_BOUNDARY, 'explicit formal layout differs from the environment entry')
        expected = (tuple(member.reference for member in environment.members)
                    + tuple(port.value for port in interface.parameters) + (interface.world,))
    else:
        expected = tuple(port.value for port in interface.parameters) + (interface.world,)
    _need(entry.arguments == expected and type(values.get(interface.world)) is StateVersionValue,
          Issue.SOURCE_CORE_BOUNDARY, 'formal/environment/world partition differs from the actual entry')
    return interface.parameters



class _Core:
    def __init__(self, sources):
        self.sources = sources
        self.use_operations = {}
        self.use_sources = {}
        self.value_records = {}

    def values(self, definition):
        if definition not in self.value_records:
            self.value_records[definition] = {
                value.id: value for value in self.sources.bodies[definition].graph.values}
        return self.value_records[definition]

    def formal_ports(self, definition):
        """Check original project formals under the existing local namespace."""
        body, _, _, blocks = self.sources.core[definition]
        return _checked_formal_ports(body, self.sources.ports[definition],
            self.sources.signatures[definition], self.values(definition), blocks, definition)

    def qualified_formal_ports(self, context):
        """The same ABI guard, after an exact original qualified body lookup."""
        from scar.analysis.call_edges import _QualifiedBodyContext
        if type(context) is not _QualifiedBodyContext:
            raise TypeError('exact original qualified body context required')
        body, _, _, blocks = context.core
        return _checked_formal_ports(body, context.bundle.interface, context.signature,
            {value.id: value for value in body.graph.values}, blocks, context.reference.definition.definition)

    def return_root(self, edge):
        if (not edge.exit_verified or edge.exit is None
                or edge.exit.completion is not FrameCompletion.NORMAL or edge.entry.suspended
                or edge.target.definition not in self.sources.core):
            return None
        definition = edge.target.definition
        node = self.sources.returned_node(edge.exit, edge.target)
        if node is None:
            return None
        reference = self.sources.source(edge.target.snapshot.path, node.value)
        use_id, value_id = self.sources.return_operand(definition, node, reference)
        if use_id is None:
            return None
        body, operations, uses, _ = self.sources.core[definition]
        if definition not in self.use_operations:
            self.use_operations[definition] = {use.id: op for op in operations.values() for use in op.uses}
        operation = self.use_operations[definition].get(use_id)
        if (operation is None or operation.terminator is None
                or operation.terminator.kind is not TerminatorKind.RETURN
                or operation.terminator.values[0] != use_id or len(operation.terminator.values) != 2):
            return None
        return InvocationReturn(edge.entry.invocation, definition, body.graph.root, edge.exit.anchor,
                                reference, operation.id, use_id, value_id,
                                uses[operation.terminator.values[1]].value)

    def template(self, definition):
        sources = self.sources
        body, operations, uses, blocks = sources.core[definition]
        interface, signature = sources.ports[definition], sources.signatures[definition]
        names = {parameter.slot: parameter.name for parameter in signature.parameters}
        formal = {port.value: (port.slot, names[port.slot]) for port in self.formal_ports(definition)}
        references = {value.id: value for value in body.graph.values if type(value) is ReferenceValue}
        source_links = defaultdict(list)
        for link in body.metadata.value_links:
            source_links[link.value].append(link.source)
        call_results, completion_results, routes = set(), set(), []
        source_opcodes = {link.operation: link.opcode for link in body.metadata.operation_links}
        for operation in operations.values():
            if operation.terminator is None:
                continue
            for successor, edge in enumerate(operation.terminator.successors):
                block = blocks[edge.block]
                for port, operand in enumerate(edge.arguments):
                    destination = block.arguments[port]
                    if destination not in references:
                        continue
                    if isinstance(operand, CompletionResult):
                        if edge.kind is ExitKind.NORMAL and operand.index == 0:
                            completion_results.add(destination)
                            if (interface.profile is BodyLoweringProfile.BOUND_FRAME
                                    or source_opcodes.get(operation.id) is Opcode.CALL):
                                call_results.add(destination)
                    elif operand in uses and uses[operand].value in references:
                        routes.append(CoreReferenceRoute(destination, uses[operand].value,
                                                         operation.id, operand, successor, port))
        values = []
        for identity, value in references.items():
            candidates = tuple(dict.fromkeys(source_links[identity]))
            source = candidates[0] if len(candidates) == 1 else None
            if identity in formal:
                slot, name = formal[identity]
                parameter = next(parameter for parameter in signature.parameters if parameter.slot == slot)
                values.append(CoreReferenceValue(identity, CoreReferenceKind.FORMAL,
                                                  parameter.source, slot, name))
            else:
                kind = (CoreReferenceKind.CALL_RESULT if identity in call_results else
                        CoreReferenceKind.OPAQUE_OPERATION if identity in completion_results else
                        CoreReferenceKind.BLOCK_ARGUMENT if isinstance(value.origin, BlockArgument) else
                        CoreReferenceKind.LITERAL if isinstance(value.origin, LiteralOrigin) else
                        CoreReferenceKind.OPAQUE_OPERATION)
                values.append(CoreReferenceValue(identity, kind, source))
        return CoreReferenceTemplate(definition, body.graph.root, tuple(values), tuple(routes))


def _instruction_plan(code, site, node, rule=LOAD_OCCURRENCES_RULE, *, selection=None):
    """Build the narrow LOAD/PUSH_NULL window from exact verified bytecode."""
    from scar.trace.operand_bytecode import load_slots
    instructions = list(dis.get_instructions(code))
    positions = {item.offset: index for index, item in enumerate(instructions)}
    _need(site.offset in positions, Issue.INSTRUCTION_WINDOW, 'CALL offset has no verified instruction')
    position = positions[site.offset]
    call = instructions[position]
    _need(call.opname == 'CALL' and call.arg == len(node.args), Issue.DISPATCH_BOUNDARY,
          'only a fixed positional CALL instruction is supported')
    count, reversed_window = 0, []
    for instruction in reversed(instructions[:position]):
        slots = load_slots(code, instruction)
        _need(slots is not None, Issue.INSTRUCTION_WINDOW, 'unsupported fused or non-Name load in CALL window')
        if slots:
            count += len(slots)
        else:
            _need(instruction.opname in ('PUSH_NULL', 'NOP'), Issue.INSTRUCTION_WINDOW,
                  'CALL operands are not a contiguous explicit Name-load window')
        reversed_window.append((instruction, slots))
        if count >= len(node.args) + 1:
            break
    _need(count == len(node.args) + 1, Issue.INSTRUCTION_WINDOW,
          'CALL needs one complete callee load and one occurrence per actual')
    window = list(reversed(reversed_window))
    tokens = [(instruction, slot) for instruction, slots in window for slot in slots]
    expected_names = [node.func.id, *(argument.id for argument in node.args)]
    _need([slot[2] for _, slot in tokens] == expected_names, Issue.INSTRUCTION_WINDOW,
          'ordered bytecode load slots differ from callee and actual Name occurrences')
    _need(all(slot[1] == 'FAST_LOCAL' for _, slot in tokens[1:]), Issue.DISPATCH_BOUNDARY,
          'actuals require explicit fast-local Name loads')
    window.append((call, ()))
    if rule == CALL_WINDOWS_RULE:
        # Recompute from the exact source-verified CodeType. A sparse row
        # subsequence cannot itself prove that no skipped control transfer
        # entered the middle of this physical instruction interval.
        from scar.trace.operand_bytecode import call_window_selection
        suspended = inspect.CO_GENERATOR | inspect.CO_COROUTINE | inspect.CO_ASYNC_GENERATOR
        _need(not code.co_flags & suspended, Issue.DISPATCH_BOUNDARY,
              'suspended caller code is outside the sparse call-window rule')
        selected = selection
        if selected is None:
            selected, _ = call_window_selection(code, instructions)
        _need(selected.get(site.offset) == tuple(instruction.offset for instruction, _ in window),
              Issue.INSTRUCTION_WINDOW,
              'sparse CALL window is not one complete physical interval without internal jump or handler entry')
    else:
        _need(rule == LOAD_OCCURRENCES_RULE, Issue.CAPTURE_GAP, 'unsupported operand capture rule')
    return tuple(window), tuple(tokens)


def _has_index(indices, first, last):
    position = bisect_left(indices, first)
    return position < len(indices) and indices[position] <= last


def _load_window(attempt, node, caller_code, instructions, instruction_indices, previous_attempt,
                 local_gaps, global_epochs, read_issues, plans, rule=LOAD_OCCURRENCES_RULE):
    key = rule, attempt.site.code, attempt.site.offset
    if key not in plans:
        selection = None
        if rule == CALL_WINDOWS_RULE:
            from scar.trace.operand_bytecode import call_window_selection
            selection_key = rule, attempt.site.code
            if selection_key not in plans:
                plans[selection_key] = call_window_selection(caller_code)[0]
            selection = plans[selection_key]
        plans[key] = _instruction_plan(caller_code, attempt.site, node, rule, selection=selection)
    plan, tokens = plans[key]
    stop = bisect_left(instruction_indices, attempt.index)
    actual = instructions[max(0, stop - len(plan)):stop]
    _need(len(actual) == len(plan) and all(item.index > previous_attempt for item in actual),
          Issue.INSTRUCTION_WINDOW, 'required instruction events are missing or belong to an earlier attempt')
    _need(all(encode(item.site) == code_site(caller_code, instruction.offset)
              for item, (instruction, _) in zip(actual, plan)),
          Issue.INSTRUCTION_WINDOW, 'dynamic instruction window differs from the verified bytecode plan')
    _need(all(item.hook_epoch == attempt.hook_epoch for item in actual), Issue.CAPTURE_GAP,
          'hook epoch changed inside an operand window')
    _need(actual[-1].frame_index == attempt.frame_index, Issue.HANDSHAKE_BOUNDARY,
          'CALL instruction and attempt disagree on the original-frame watermark')
    first = actual[0].index
    global_gap = global_epochs.get((attempt.process_id, attempt.hook_epoch))
    _need(not (global_gap is not None and global_gap < attempt.index)
          and not _has_index(local_gaps.get(attempt.invocation, ()), first, attempt.index),
          Issue.CAPTURE_GAP, 'capture gap invalidates the operand window')
    _need(not _has_index(read_issues.get(attempt.invocation, ()), first, attempt.index), Issue.CAPTURE_GAP,
          'reader found contradictory or unavailable code/layout evidence inside the operand window')
    observed = []
    for event, (instruction, slots) in zip(actual, plan):
        _need(len(event.loads) == len(slots), Issue.INSTRUCTION_WINDOW,
              'captured load count differs from the verified opcode suboperands')
        for load, (suboperand, namespace, name, slot_index) in zip(event.loads, slots):
            namespace_ok = (load.namespace in (LoadNamespace.GLOBAL, LoadNamespace.BUILTIN)
                            if namespace == 'GLOBAL' else load.namespace is LoadNamespace.FAST_LOCAL)
            _need(load.suboperand == suboperand and load.slot == name
                  and load.slot_index == slot_index and namespace_ok and load.reference is not None,
                  Issue.INSTRUCTION_WINDOW, 'load observation differs from exact opcode slot/suboperand')
            observed.append((event, load))
    return tuple(observed)


def build_operand_routes(*, call_model, operand_model, inventory, sources, budget=OperandRouteBudget()):
    """Build bounded conditional routes from independently validated inputs.

    The public report supplies one fresh shared reader result and the exact
    inventory/_Sources pair used to build call_model. No target code executes.
    """
    if type(budget) is not OperandRouteBudget:
        raise ValueError('operand routing requires a typed independent budget')
    supported_profiles = (BodyLoweringProfile.BOUND_FRAME, BodyLoweringProfile.STRUCTURED_BODY,
                          BodyLoweringProfile.STRUCTURED_ENV)
    if (sources.inventory is not inventory or inventory.interfaces is None
            or inventory.profile not in supported_profiles or inventory.interfaces.profile is not inventory.profile):
        raise ValueError('operand routes require the matching explicit frame/structured inventory used by source verification')
    core = _Core(sources)
    issues, templates, obligations, returned = [], [], [], []
    issue_seen = set()
    arguments, completions = [], []
    counts = {'values': 0, 'routes': 0}

    def issue(kind, detail, invocation=None, anchor=None):
        value = OperandRouteIssue(kind, detail, invocation, anchor)
        if value not in issue_seen:
            issue_seen.add(value)
            issues.append(value)

    def charge(routes=0, values=0):
        if counts['routes'] + routes > budget.max_routes or counts['values'] + values > budget.max_template_values:
            issue(Issue.ROUTE_BUDGET, 'operand route/template budget exhausted; omitted links remain unproved')
            return False
        counts['routes'] += routes
        counts['values'] += values
        return True

    definitions = tuple(dict.fromkeys(edge.target.definition for edge in call_model.edges
                        if edge.target.status is CallLinkStatus.VERIFIED
                        and edge.target.definition in sources.core
                        and edge.target.definition in sources.ports
                        and sources.frame_rules(edge.target.definition) is not None))
    available = set()
    for definition in definitions:
        try:
            template = core.template(definition)
        except _Boundary as error:
            issue(error.kind, error.detail)
            continue
        if not charge(len(template.routes), len(template.values)):
            continue
        templates.append(template)
        available.add(definition)
        body = sources.bodies[definition]
        obligations.append(FrameRouteObligations(definition, template.region, sources.frame_rules(definition),
                           body.metadata.assumptions,
                           tuple(op.id for op in body.graph.operations if not op.effects_complete)))
    edges = {edge.entry.invocation: edge for edge in call_model.edges}
    roots = {}
    for edge in call_model.edges:
        if edge.target.definition not in available:
            continue
        root = core.return_root(edge)
        if root is not None and charge(1):
            returned.append(root)
            roots[root.invocation] = root
    instructions = defaultdict(list)
    for instruction in operand_model.instructions:
        instructions[instruction.invocation].append(instruction)
    instruction_indices = {key: [item.index for item in values] for key, values in instructions.items()}
    handshakes = defaultdict(list)
    for handshake in operand_model.handshakes:
        handshakes[handshake.process_id, handshake.attempt_index].append(handshake)
    bad_processes = {meta.process_id for meta in operand_model.metadata
                     if meta.errors or meta.io_failed or meta.dropped_events or meta.previous_profile}
    bad_processes.update(item.process_id for item in operand_model.issues
                         if item.invocation is None and item.anchor is None)
    capture_rules = {}
    for meta in operand_model.metadata:
        if meta.process_id in capture_rules:
            bad_processes.add(meta.process_id)
        capture_rules[meta.process_id] = meta.rule
    local_gaps, global_gaps, global_epochs, read_issues = defaultdict(list), defaultdict(list), {}, defaultdict(list)
    for gap in operand_model.gaps:
        if gap.invocation is None:
            global_gaps[gap.process_id].append(gap.index)
            global_epochs.setdefault((gap.process_id, gap.hook_epoch), gap.index)
        else:
            local_gaps[gap.invocation].append(gap.index)
    for item in operand_model.issues:
        if item.invocation is not None and item.anchor is not None:
            read_issues[item.invocation].append(item.anchor.index)
    for mapping in (local_gaps, global_gaps, read_issues):
        for indices in mapping.values():
            indices.sort()
    previous, plans = {}, {}
    for attempt in operand_model.attempts:
        last = previous.get(attempt.invocation, 0)
        previous[attempt.invocation] = attempt.index
        try:
            rule = capture_rules.get(attempt.process_id)
            _need(rule in (LOAD_OCCURRENCES_RULE, CALL_WINDOWS_RULE), Issue.CAPTURE_GAP,
                  'attempt process has no supported capture rule metadata')
            _need(attempt.process_id not in bad_processes, Issue.CAPTURE_GAP,
                  'collector metadata reports loss, failure or an existing profile observer')
            matches = handshakes[attempt.process_id, attempt.index]
            _need(len(matches) == 1, Issue.HANDSHAKE_BOUNDARY, 'attempt has no unique real entry handshake')
            handshake, = matches
            edge = edges.get(handshake.invocation)
            caller = edges.get(attempt.invocation)
            _need(edge is not None and caller is not None and edge.caller_identity_verified
                  and edge.entry.caller_invocation == attempt.invocation
                  and edge.entry.anchor.index == handshake.entry_index
                  and caller.entry.anchor.index <= attempt.frame_index < handshake.entry_index
                  and handshake.thread_id == attempt.thread_id
                  and handshake.hook_epoch == attempt.hook_epoch,
                  Issue.HANDSHAKE_BOUNDARY, 'handshake does not identify the active direct caller/entry interval')
            if getattr(sources, 'source_access', None) is not None:
                _need(attempt.site.code in sources.objects and edge.entry.code in sources.objects,
                      Issue.SOURCE_CORE_BOUNDARY,
                      'CODE_WITNESS_UNAVAILABLE: verified source alone cannot certify a CALL instruction window')
            _need(len(edge.path) == 1 and edge.path[0].site == attempt.site
                  and edge.path[0].status is CallLinkStatus.VERIFIED
                  and edge.path[0].core_operation is not None
                  and edge.target.status is CallLinkStatus.VERIFIED
                  and caller.target.definition in available and edge.target.definition in available,
                  Issue.SOURCE_CORE_BOUNDARY, 'attempt/entry lacks one verified direct source/core call and body')
            call = edge.path[0]
            target_code = sources.objects.get(edge.entry.code)
            _need(attempt.dispatch.kind is CallableKind.EXACT_FUNCTION
                  and attempt.dispatch.code == edge.entry.code and target_code is not None
                  and _layout_matches(attempt.dispatch.layout, target_code),
                  Issue.DISPATCH_BOUNDARY, 'CALL current function/code/layout differs from the actual entry')
            _need(not any(_has_index(indices, attempt.index, handshake.index) for indices in (
                      global_gaps.get(attempt.process_id, ()), local_gaps.get(attempt.invocation, ()),
                      local_gaps.get(handshake.invocation, ()))),
                  Issue.CAPTURE_GAP, 'capture gap occurs during entry handshake')
            root = roots.get(edge.entry.invocation)
            normal_result = sources.result(call)
            node = sources.node(call.source)
            _need(isinstance(node, ast.Call) and isinstance(node.func, ast.Name)
                  and not node.keywords and all(isinstance(argument, ast.Name) for argument in node.args),
                  Issue.DISPATCH_BOUNDARY, 'argument routing requires Name callee and explicit local Name actuals')
            layout = attempt.dispatch.layout
            unsupported = inspect.CO_VARARGS | inspect.CO_VARKEYWORDS | inspect.CO_GENERATOR | inspect.CO_COROUTINE | inspect.CO_ASYNC_GENERATOR
            _need(not layout.flags & unsupported and layout.kwonlyargcount == 0
                  and layout.argcount == len(node.args), Issue.DISPATCH_BOUNDARY,
                  'receiver/default/pack/keyword or suspended binding is outside the all-positional rule')
            _need(edge.entry.parameters_complete
                  and tuple(parameter.name for parameter in edge.entry.parameters) == layout.parameters,
                  Issue.DISPATCH_BOUNDARY, 'actual frame parameters differ from dispatch-time layout')
            observations = _load_window(attempt, node, sources.objects[attempt.site.code],
                instructions[attempt.invocation], instruction_indices.get(attempt.invocation, []),
                last, local_gaps, global_epochs, read_issues, plans, rule)
            _, loaded_callee = observations[0]
            _need(loaded_callee.callable_shape.kind is CallableKind.EXACT_FUNCTION,
                  Issue.DISPATCH_BOUNDARY, 'pre-load callable is a bound method, adapter or unavailable shape')
            _consistency(loaded_callee.reference, attempt.dispatch.reference)
            signature, ports = sources.signatures[edge.target.definition], sources.ports[edge.target.definition]
            _need(tuple(parameter.name for parameter in signature.parameters) == layout.parameters
                  and all(parameter.kind in (ParameterKind.POSITIONAL_ONLY, ParameterKind.POSITIONAL)
                          for parameter in signature.parameters), Issue.DISPATCH_BOUNDARY,
                  'verified body formal interface differs from the actual dispatch layout')
            body, operations, uses, _ = sources.core[call.execution_owner]
            operation = operations[call.core_operation]
            _need(len(operation.invoke_arguments) == len(node.args) + 2
                  and operation.invoke_arguments[0] == call.callee_use,
                  Issue.SOURCE_CORE_BOUNDARY, 'core CALL does not have one actual Use per position')
            world_use = uses[operation.invoke_arguments[-1]]
            values = core.values(call.execution_owner)
            _need(world_use.role is UseRole.STATE_CONTENT and type(values.get(world_use.value)) is StateVersionValue
                  and all(type(values.get(uses[use_id].value)) is ReferenceValue
                          for use_id in operation.invoke_arguments[:-1]),
                  Issue.SOURCE_CORE_BOUNDARY, 'core CALL actuals/world do not have their declared reference/state roles')
            if call.execution_owner not in core.use_sources:
                core.use_sources[call.execution_owner] = {
                    (link.operation, link.use): link.source for link in body.metadata.use_links}
            use_sources = core.use_sources[call.execution_owner]
            pending = []
            for index, ((instruction, observation), parameter, formal, captured) in enumerate(zip(
                    observations[1:], signature.parameters, ports.parameters, edge.entry.parameters)):
                use_id = operation.invoke_arguments[index + 1]
                source = sources.source(call.source.path, node.args[index])
                _need(use_sources.get((operation.id, use_id)) == source and parameter.slot == formal.slot,
                      Issue.SOURCE_CORE_BOUNDARY, 'actual Use source or formal slot is not the exact indexed occurrence')
                consistency = _consistency(observation.reference, captured.ref)
                if index == 0 and not attempt.arg0_missing:
                    _consistency(observation.reference, attempt.arg0)
                pending.append(ArgumentRoute(attempt.anchor, attempt.invocation, edge.entry.invocation,
                    index, instruction.anchor, observation.suboperand, call.call, call.source,
                    call.execution_owner, call.core_region, call.core_operation, source, use_id,
                    uses[use_id].value, edge.target.definition, ports.region, parameter.slot,
                    formal.value, parameter.name, consistency))
            completion = None
            if root is not None and normal_result is not None:
                completion = CompletionRoute(attempt.anchor, attempt.invocation, edge.entry.invocation,
                    call.call, call.source, call.execution_owner, call.core_region, call.core_operation,
                    normal_result, root.definition, root.region, root.exit_anchor,
                    root.payload_use, root.payload_value, root.post_world)
            # The first completion rule shares the complete narrow argument
            # admission. A known capture/load/shape contradiction cannot leave
            # a positive completion after its argument routes were rejected.
            if charge(len(pending) + (completion is not None)):
                arguments.extend(pending)
                if completion is not None:
                    completions.append(completion)
        except _Boundary as error:
            issue(error.kind, error.detail, attempt.invocation, attempt.anchor)
    return OperandRouteModel(budget, tuple(arguments), tuple(completions), tuple(templates),
                             tuple(returned), tuple(obligations), tuple(issues))


def query_operand_routes(call_model, routes, invocation, *, max_steps=4096):
    """Follow conditional SSA/argument/completion routes, never opaque inputs."""
    if type(max_steps) is not int or not 1 <= max_steps <= 100_000:
        raise ValueError('max_steps must be an exact integer in [1, 100000]')
    if type(invocation) is tuple and len(invocation) == 3:
        invocation = InvocationKey(*invocation)
    if type(invocation) is not InvocationKey or type(routes) is not OperandRouteModel:
        raise ValueError('operand query requires typed route model and invocation')
    templates = {template.definition: template for template in routes.templates}
    values = {template.definition: {value.value: value for value in template.values} for template in routes.templates}
    definitions = {edge.entry.invocation: edge.target.definition for edge in call_model.edges}
    core = defaultdict(list)
    for template in routes.templates:
        for route in template.routes:
            core[template.definition, route.destination].append(route)
    arguments = {(route.callee, route.formal_value): route for route in routes.argument_routes}
    completions = defaultdict(list)
    for route in routes.completion_routes:
        completions[route.caller, route.normal_result].append(route)

    def node(owner, value):
        definition = definitions.get(owner)
        item = values.get(definition, {}).get(value)
        if item is None:
            return None
        return OperandReferenceNode(owner, definition, templates[definition].region, value,
                                    item.kind, item.source, item.formal_slot, item.formal_name)

    roots = tuple(value for root in routes.returns if root.invocation == invocation
                  for value in (node(root.invocation, root.payload_value),) if value is not None)
    queue, visited, traversed, endpoints, issues = deque(roots), set(), [], [], []
    steps, exhausted = 0, False
    while queue:
        current = queue.popleft()
        if current in visited:
            continue
        if steps >= max_steps:
            exhausted = True
            endpoints.extend(value for value in (current, *queue) if value not in endpoints)
            issues.append(OperandRouteIssue(Issue.QUERY_BUDGET,
                          'reference query budget exhausted with pending conditional routes', current.invocation))
            break
        visited.add(current)
        steps += 1
        next_steps = []
        control_boundary = False
        if current.kind is CoreReferenceKind.FORMAL:
            argument = arguments.get((current.invocation, current.value))
            if argument is not None:
                source = node(argument.caller, argument.actual_value)
                if source is not None:
                    next_steps.append(OperandQueryStep(current, source, OperandQueryRouteKind.ARGUMENT,
                                                       argument=argument))
        elif current.kind is CoreReferenceKind.CALL_RESULT:
            matches = completions[current.invocation, current.value]
            if len(matches) == 1:
                completion, = matches
                source = node(completion.callee, completion.payload_value)
                if source is not None:
                    next_steps.append(OperandQueryStep(current, source, OperandQueryRouteKind.COMPLETION,
                                                       completion=completion))
        elif current.kind is CoreReferenceKind.BLOCK_ARGUMENT:
            incoming = core[current.definition, current.value]
            if len({route.source for route in incoming}) > 1:
                # The template records static CFG successors, not which
                # successor this invocation took. Equal runtime references
                # cannot select a predecessor. A common SSA source across
                # every predecessor is independent of that missing choice.
                control_boundary = True
                issues.append(OperandRouteIssue(Issue.CONTROL_SELECTION_UNVERIFIED,
                              'block argument has different static predecessor sources; '
                              'this invocation has no verified control-to-CFG selection', current.invocation))
            else:
                for route in incoming:
                    source = node(current.invocation, route.source)
                    if source is not None:
                        next_steps.append(OperandQueryStep(current, source, OperandQueryRouteKind.CORE_REFERENCE,
                                                           core=route))
        if not next_steps:
            endpoints.append(current)
            if current.kind is CoreReferenceKind.CALL_RESULT:
                issues.append(OperandRouteIssue(Issue.COMPLETION_BOUNDARY,
                              'normal result has no unique observed attempt/entry/completion route', current.invocation))
            elif current.kind is CoreReferenceKind.FORMAL:
                issues.append(OperandRouteIssue(Issue.ARGUMENT_ROUTING_UNVERIFIED,
                              'formal origin stops at an unavailable or unsupported caller binding', current.invocation))
            elif current.kind not in (CoreReferenceKind.LITERAL,) and not control_boundary:
                issues.append(OperandRouteIssue(Issue.OPAQUE_REFERENCE,
                              'reference origin is opaque; producer inputs are not aliases', current.invocation))
        for step in next_steps:
            traversed.append(step)
            if step.source not in visited:
                queue.append(step.source)
    if not roots:
        issues.append(OperandRouteIssue(Issue.COMPLETION_BOUNDARY,
                      'requested invocation has no verified normal source/core return root', invocation))
    if any(issue.kind is Issue.ROUTE_BUDGET for issue in routes.issues):
        issues.extend(issue for issue in routes.issues if issue.kind is Issue.ROUTE_BUDGET)
    discovered = visited | set(endpoints)
    discovered.update(step.source for step in traversed)
    discovered.update(step.destination for step in traversed)
    # Global visited-node deduplication must not turn a reference cycle into
    # an apparently complete query with no endpoint. Detect cycles in the
    # actually traversed thin graph without recursive Python calls.
    degree = {value: 0 for value in discovered}
    adjacency = defaultdict(list)
    for step in dict.fromkeys(traversed):
        adjacency[step.destination].append(step.source)
        degree[step.source] += 1
    ready = deque(value for value, count in degree.items() if count == 0)
    while ready:
        value = ready.popleft()
        for source in adjacency[value]:
            degree[source] -= 1
            if degree[source] == 0:
                ready.append(source)
    cyclic = [value for value, count in degree.items() if count]
    if cyclic:
        issues.append(OperandRouteIssue(Issue.CYCLE_BOUNDARY,
                      'traversed conditional reference graph contains a cycle', invocation))
        endpoints.extend(value for value in cyclic if value not in endpoints)
    reached = {value.definition for value in discovered}
    return OperandReferenceTrace(invocation, roots, tuple(sorted(discovered, key=lambda item: (
        item.invocation.process_id, item.invocation.thread_id, item.invocation.invocation_id, item.value.wire))),
        tuple(dict.fromkeys(traversed)), tuple(dict.fromkeys(endpoints)), tuple(dict.fromkeys(issues)),
        tuple(item for item in routes.obligations if item.definition in reached), steps, max_steps)


__all__ = ['build_operand_routes', 'query_operand_routes']
