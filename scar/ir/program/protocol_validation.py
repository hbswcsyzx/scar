"""Mechanical protocol joins on the canonical CFG and its original ports.

Known contradictions are issues; missing source/ports stay query gaps.  Nothing
here proves the native implementation, purity, runtime identity or a rewrite.
"""
from .control import ProtocolValueKind
from .driver_flow import body_outcome_uses
from .drivers import RawRequestKind
from .model import (AccessMode, CompletionResult, DataValue, ExitKind, InvokeLiteralResult, OperationResult,
                    ProtocolValue, ReferenceValue, StateVersionValue, TerminatorKind)
from .lifecycle import DriveOutcomeRef
from .protocol_flow import ProtocolFlow, ProtocolReferenceError
from .protocol_rules import PROFILE_FAMILY, contract_allowed, profile_subject, required_clauses
from .protocols import (
    AdmissionPredicate, ContractResult, DriverSubject, DriveResult, HostTerminal, NativeExit,
    NoEntryOutcome, OperationSiteSubject, OutcomeAdapter, OutcomeAdapterRule,
    OwnedUse, PacketConstruction, PacketRule, ProtocolCall, ProtocolClause,
    ProtocolCallRule, ProtocolProfile, RequestProcessing, RequestProcessingRule, StaticProtocolGap,
)
from .resumption import SuspendTerminator
from .resumption import ResumeSlotKind, SuspensionFlavor
from .drivers import BodyResume
from .driver_flow import body_drive_target
from .state_addresses import ExistingAccess, InvokeStateOperand
from .structured import ControlEdgeReference


_RAW_KINDS = {
    RequestProcessingRule.CHECK_NEXT: RawRequestKind.NEXT,
    RequestProcessingRule.CHECK_SEND: RawRequestKind.SEND,
    RequestProcessingRule.CHECK_THROW: RawRequestKind.THROW,
    RequestProcessingRule.CHECK_CLOSE: RawRequestKind.CLOSE,
    RequestProcessingRule.NORMALIZE_THROW_INSTANCE: RawRequestKind.THROW,
    RequestProcessingRule.NORMALIZE_THROW_CLASS: RawRequestKind.THROW,
    RequestProcessingRule.NORMALIZE_GENERATOR_EXIT: RawRequestKind.CLOSE,
    RequestProcessingRule.NORMALIZE_ASYNC_THROW: RawRequestKind.THROW,
}

_EXCEPTION_ADAPTER_RULES = (
    OutcomeAdapterRule.GENERATOR_RETURN_TO_STOP_ITERATION,
    OutcomeAdapterRule.COROUTINE_RETURN_TO_STOP_ITERATION,
    OutcomeAdapterRule.GENERATOR_ESCAPE_STOPITER_TO_RUNTIME_ERROR,
    OutcomeAdapterRule.ASYNCGEN_RETURN_TO_STOP_ASYNC_ITERATION,
)
_CLOSE_ERROR_RULES = (
    OutcomeAdapterRule.CLOSE_IGNORED_EXIT_TO_RUNTIME_ERROR,
    OutcomeAdapterRule.ASYNCGEN_CLOSE_YIELD_ERROR,
)
_CLOSE_RULES = (OutcomeAdapterRule.CLOSE_RETURN_VALUE, *_CLOSE_ERROR_RULES)
_ERROR_ADAPTER_RULES = (*_EXCEPTION_ADAPTER_RULES, *_CLOSE_ERROR_RULES)


def host_output_copy(ctx, source, terminal):
    """Exact whole-payload copy or explicit packet of this exception result.

    PacketConstruction is not mandatory: use the existing PacketDefinition and
    original component Uses.  Equal types and reachable RAISEs are insufficient.
    """
    info = ctx.port(source)
    if info is None or info.gap is not None:
        return None
    matches = []
    for target in ctx.terminal_uses(terminal):
        direct = ctx.forwards(source, target)
        if direct is True:
            matches.append(True)
            continue
        unknown, found = direct is None, False
        if info.values and all(isinstance(ctx.values[value], ReferenceValue) for value in info.values):
            for packet in ctx.packets.values():
                if not ctx.spend("adapter_packets"):
                    return None
                origin = ctx.values[packet.value].origin
                if type(origin) is not OperationResult:
                    continue
                if ctx.region_of[origin.operation] != ctx.region_of[target.operation]:
                    continue
                delivered = ctx.forwards(origin, target)
                component = ctx.forwards(source, OwnedUse(origin.operation, packet.exception))
                if delivered is True and component is True:
                    found = True
                    break
                if delivered is not False and component is not False:
                    unknown = True
        matches.append(True if found else None if unknown else False)
    return False if False in matches else None if not matches or None in matches else True


def adapter_host_output(ctx, row):
    """Resolve a terminal output through the adapter's selected own results."""
    contract, operation = row.contract, ctx.operations[row.operation]
    terminal = contract.output
    if ctx.region_of[terminal.operation] != ctx.region_of[operation.id]:
        return False
    direct = (host_output_copy(ctx, contract.input, terminal)
              if contract.rule is OutcomeAdapterRule.CLOSE_RETURN_VALUE else None)
    if direct is True:
        return True
    ports = []
    if operation.terminator is not None and operation.terminator.kind is TerminatorKind.INVOKE:
        if row.slot >= len(operation.terminator.successors):
            return False
        edge = operation.terminator.successors[row.slot]
        signature = next(item for item in operation.completions if item.kind is edge.kind)
        ports = [InvokeLiteralResult(ControlEdgeReference(operation.id, row.slot), CompletionResult(index))
                 for index, value_type in enumerate(signature.types)
                 if getattr(value_type, 'location', None) is None]
    else:
        if row.slot != 0:
            return False
        ports = [OperationResult(operation.id, index) for index, value in enumerate(operation.results)
                 if not isinstance(ctx.values[value], StateVersionValue)]
    matches = [host_output_copy(ctx, source, terminal) for source in ports]
    return (True if True in matches else None if None in matches
            else direct if not matches and contract.rule is OutcomeAdapterRule.CLOSE_RETURN_VALUE
            else None if not matches else False)


class ProtocolOperandRoleError(ValueError):
    """An owned edge-forward Use is not an actual call operand."""


def _actual_protocol_use(ctx, operation, identity):
    use = ctx.owned_use(operation.id, identity)
    if (operation.terminator is not None and operation.terminator.kind is TerminatorKind.INVOKE
            and identity not in operation.invoke_arguments):
        raise ProtocolOperandRoleError("protocol operand must be a real invoke argument, not an edge-only forward")
    return use


def raw_definition(ctx, raw_use):
    """Resolve only exact canonical pack/copy routes, never a name or shape."""
    use = ctx.owned_use(raw_use.operation, raw_use.use)
    if use.value in ctx.raw:
        return ctx.raw[use.value]
    matches = []
    for value, definition in ctx.raw.items():
        original = ctx.values[value]
        if ctx.region_of.get(getattr(original.origin, 'operation', None)) != ctx.region_of[raw_use.operation]:
            continue
        if type(original.origin) is OperationResult and ctx.forwards(original.origin, raw_use) is True:
            matches.append(definition)
    return matches[0] if len(matches) == 1 else None


def _state_sites(ctx, row):
    operation = ctx.operations[row.operation]
    for site in getattr(row.contract, 'state_sites', ()):
        if site.operation != operation.id:
            raise ValueError("protocol state site belongs to another operation")
        if type(site) is ExistingAccess:
            if site.index >= len(operation.accesses):
                raise ValueError("protocol state access index is outside original effects")
        elif type(site) is InvokeStateOperand:
            if operation.terminator is None or operation.terminator.kind is not TerminatorKind.INVOKE:
                raise ValueError("protocol invoke state requires original INVOKE")
            use = ctx.owned_use(operation.id, site.state_use)
            if site.state_use not in operation.invoke_arguments or not isinstance(ctx.values[use.value], StateVersionValue):
                raise ValueError("protocol state operand must be its real state input")


def _own_result(ctx, row, port):
    resolved = ctx.port(port, referring=row)
    if resolved is not None and resolved.operation is not None and resolved.operation != row.operation:
        raise ValueError("protocol result must be produced by this exact operation")
    if type(port) is InvokeLiteralResult and row.slot != port.edge.successor_index:
        raise ValueError("protocol row slot must equal its exact completion edge")
    if type(port) is OperationResult and row.slot != 0:
        raise ValueError("ordinary protocol result row uses slot zero")
    return resolved


def _producer_row(ctx, source):
    if type(source) is not ContractResult:
        return None
    ctx.port(source)
    return ctx.rows[source.scope, source.clause, source.operation, source.slot]


def no_entry_route(ctx, row, *, check_payload=True):
    """The original selected path and payload, not a terminal-by-kind shortcut."""
    contract = row.contract
    operation = ctx.operations[row.operation]
    edge = contract.selected_edge
    block = ctx.blocks[ctx.block_of[operation.id]]
    terminator = ctx.operations[block.operations[-1]]
    if operation.id in ctx.drives or terminator.id in ctx.drives:
        raise ValueError("a real BodyDrive cannot be a no-entry transition")
    _state_sites(ctx, row)  # Invalid known sites must not turn into IndexError below.
    is_invoke = operation.terminator is not None and operation.terminator.kind is TerminatorKind.INVOKE
    if is_invoke and edge is None:
        raise ValueError("INVOKE no-entry transition must select its exact edge")
    if edge is not None:
        if edge.operation != terminator.id or edge.successor_index >= len(terminator.terminator.successors):
            raise ValueError("no-entry selected edge must be the transition block's real successor")
        if row.slot != edge.successor_index:
            raise ValueError("no-entry slot and selected edge differ")
        start = terminator.terminator.successors[edge.successor_index].block
    else:
        if len(terminator.terminator.successors) > 1:
            raise ValueError("branched no-entry transition needs an exact selected edge")
        start = block.id
    source = contract.selected_input
    source_port = ctx.port(source, referring=row)
    if type(source) is InvokeLiteralResult and source.edge.operation == operation.id:
        if edge != source.edge:
            raise ValueError("no-entry input and transition select different completion edges")
    terminal = ctx.port(contract.terminal)
    if terminal is None or terminal.operation is None:
        return {"complete": False, "gaps": ("native_terminal_route_unproved",)}
    if ctx.region_of[terminal.operation] != ctx.region_of[operation.id]:
        raise ValueError("no-entry host terminal belongs to another region")
    destination = ctx.block_of[terminal.operation]
    seen, pending, reached, alternatives = set(), [start], False, False
    routes = {}
    while pending:
        if not ctx.spend("no_entry_path"):
            return {"complete": False, "gaps": ("protocol_budget_exhausted",)}
        identity = pending.pop()
        if identity in seen:
            continue
        seen.add(identity)
        current = ctx.blocks[identity]
        if identity == destination:
            reached = True
            routes[identity] = ()
            continue
        if any(item in ctx.drives for item in current.operations):
            raise ValueError("no-entry path cannot execute a BodyDrive")
        last = ctx.operations[current.operations[-1]]
        if not last.terminator.successors:
            alternatives = True
        routes[identity] = tuple(item.block for item in last.terminator.successors)
        pending.extend(routes[identity])
    if not reached:
        raise ValueError("no-entry terminal is not on its selected original CFG route")
    payloads = ctx.terminal_uses(contract.terminal)
    copies = (tuple(ctx.forwards(source, target, referring=row) for target in payloads)
              if check_payload else tuple(None for _ in payloads))
    if copies and any(match is False for match in copies):
        raise ValueError("no-entry terminal payload is not the selected original result")
    gaps = []
    if source_port is None or source_port.gap is not None or not payloads or any(x is None for x in copies):
        gaps.append("no_entry_input_unresolved")
    if alternatives:
        gaps.append("no_entry_terminal_route_partial")
    # A reachable exit is insufficient when another possible path cycles.  Do
    # not infer termination from a visited-set traversal.  The real CFG remains
    # canonical; this finite topological check adds no new control relation.
    indegree = dict.fromkeys(routes, 0)
    for targets in routes.values():
        for target in targets:
            indegree[target] += 1
    ready = [identity for identity, count in indegree.items() if count == 0]
    removed = 0
    while ready:
        if not ctx.spend("no_entry_cycles"):
            return {"complete": False, "gaps": ("protocol_budget_exhausted",)}
        identity = ready.pop()
        removed += 1
        for target in routes[identity]:
            indegree[target] -= 1
            if indegree[target] == 0:
                ready.append(target)
    if removed != len(routes) and "no_entry_terminal_route_partial" not in gaps:
        gaps.append("no_entry_terminal_route_partial")
    interface = ctx.interfaces.get(ctx.region_of[operation.id])
    required = set(interface.lifecycle) if interface is not None else set()
    covered = {operation.accesses[site.index].location if type(site) is ExistingAccess
               else ctx.values[ctx.owned_use(operation.id, site.state_use).value].location
               for site in contract.state_sites}
    if not required:
        gaps.append("no_entry_lifecycle_domain_unresolved")
    if not required.issubset(covered) or not contract.state_sites:
        gaps.append("no_entry_state_post_unresolved")
    if is_invoke:
        selected = operation.terminator.successors[edge.successor_index]
        produced = {ctx.values[formal].location
                    for actual, formal in zip(selected.arguments, ctx.blocks[selected.block].arguments)
                    if type(actual) is CompletionResult and isinstance(ctx.values[formal], StateVersionValue)}
        if not produced.intersection(required):
            gaps.append("no_entry_transition_effect_unproved")
    if not is_invoke and not any(type(site) is ExistingAccess
            and operation.accesses[site.index].location in required
            and operation.accesses[site.index].mode in (AccessMode.WRITE, AccessMode.READ_WRITE)
            and operation.accesses[site.index].after is not None for site in contract.state_sites):
        gaps.append("no_entry_transition_effect_unproved")
    return {"complete": not gaps, "gaps": tuple(gaps), "source": source_port,
            "terminal": terminal, "selected_edge": edge}


def _no_entry_contract(ctx, row, *, check_payload=True):
    contract, operation = row.contract, ctx.operations[row.operation]
    owner = ctx.owned_use(operation.id, contract.instance_use)
    raw = ctx.owned_use(operation.id, contract.effective_request_use)
    if not isinstance(ctx.values[owner.value], ReferenceValue):
        raise ValueError("no-entry instance must be an original Reference Use")
    if (not isinstance(ctx.values[raw.value], ProtocolValue)
            or ctx.values[raw.value].protocol is not ProtocolValueKind.RAW_DRIVER_REQUEST):
        raise ValueError("no-entry effective request must have the original raw type")
    return no_entry_route(ctx, row, check_payload=check_payload)


def no_entry_preconditions(graph):
    """Check seed-consumer foreign keys/routes before lifecycle derivation.

    This structural admission grants no payload copy or lifecycle seed. Full
    semantic checks still run with the prepared return-aware context later.
    """
    rows = tuple((number, row) for number, row in enumerate(graph.protocol_operations)
                 if type(row.contract) is NoEntryOutcome)
    if not rows:
        return ()
    ctx, errors = ProtocolFlow(graph), []
    for number, row in rows:
        try:
            _no_entry_contract(ctx, row, check_payload=False)
        except (KeyError, AttributeError, TypeError, ValueError) as exc:
            errors.append(('protocol_no_entry_edge', f'protocol_operations[{number}]', str(exc)))
    return tuple(errors)


def protocol_errors(graph, *, context=None):
    if not graph.protocol_scopes and not graph.protocol_operations:
        return ()
    ctx = ProtocolFlow(graph) if context is None else context
    issues = []

    def error(code, path, message):
        issues.append((code, str(path), str(message)))

    for scope in graph.protocol_scopes:
        subject = scope.subject
        if type(subject) is not profile_subject(scope.profile):
            error("protocol_scope", scope.id, "profile and exact subject kind differ")
            continue
        if type(subject) is DriverSubject:
            interface = ctx.interfaces.get(subject.interface_region)
            body = None if interface is None else next((b for b in graph.resumable_bodies if b.region == interface.body), None)
            if interface is None or body is None or (body.kind, interface.receiver_kind) != PROFILE_FAMILY[scope.profile]:
                error("protocol_scope", scope.id, "driver profile requires its exact existing family/receiver")
        elif (subject.region not in ctx.regions or subject.operation not in ctx.operations
              or ctx.region_of.get(subject.operation) != subject.region):
            error("protocol_scope", scope.id, "operation site must belong to its exact region")
        elif scope.profile is ProtocolProfile.CREATED_CLOSE_V1 and not any(
                row.operation == subject.operation for row in graph.created_close_tests):
            error("protocol_created_close_site", scope.id, "created-close scope must bind its exact CreatedCloseTest operation")
    for number, row in enumerate(graph.protocol_operations):
        path = f"protocol_operations[{number}]"
        scope = ctx.scopes.get(row.scope)
        operation = ctx.operations.get(row.operation)
        if scope is None:
            error("protocol_scope", path, "protocol row refers to a missing scope")
        if operation is None:
            error("protocol_operation", path, "protocol row refers to a missing operation")
        if scope is None or operation is None:
            continue
        region = (scope.subject.interface_region if type(scope.subject) is DriverSubject
                  else scope.subject.region)
        if ctx.region_of[operation.id] != region:
            error("protocol_scope", path, "protocol operation belongs to another region")
        if not contract_allowed(scope.profile, row.clause, row.contract):
            error("protocol_rule", path, "contract/rule is not allowed in this fixed profile/clause")
        contract = row.contract
        from .protocol_await import await_contract_errors
        issues.extend(await_contract_errors(ctx, row))
        try:
            _state_sites(ctx, row)
        except ValueError as exc:
            error("protocol_state_site", path, exc)
        if type(contract) is AdmissionPredicate:
            from .protocol_connections import RequestStateCondition
            if type(contract.subject) is not RequestStateCondition:
                from .admission import admission_errors
                issues.extend(admission_errors(ctx, row))
            # Request predicates need the prepared original request/association
            # index. The connection stage checks them after core validation.
        elif type(contract) is RequestProcessing:
            try:
                raw_use = _actual_protocol_use(ctx, operation, contract.raw_use)
                raw_value = ctx.values[raw_use.value]
                if (contract.rule is not RequestProcessingRule.CHECK_ASYNC_REQUEST
                        and (not isinstance(raw_value, ProtocolValue)
                             or raw_value.protocol is not ProtocolValueKind.RAW_DRIVER_REQUEST)):
                    error("protocol_raw_kind", path, "request input must carry the original RAW_DRIVER_REQUEST type")
                raw = raw_definition(ctx, OwnedUse(operation.id, raw_use.id))
                expected = _RAW_KINDS.get(contract.rule)
                if raw is not None and expected is not None and raw.kind is not expected:
                    error("protocol_raw_kind", path, "known raw request kind contradicts the fixed rule")
                for binding in contract.operand_bindings:
                    target = OwnedUse(operation.id, binding.operation_use)
                    try:
                        _actual_protocol_use(ctx, operation, binding.operation_use)
                    except ValueError as exc:
                        error("protocol_raw_operand", path, exc)
                        continue
                    if raw is not None:
                        if binding.request_ordinal >= len(raw.operands):
                            error("protocol_raw_operand", path, "request ordinal exceeds the actual raw pack")
                            continue
                        producer = ctx.values[raw.value].origin.operation
                        if ctx.forwards(OwnedUse(producer, raw.operands[binding.request_ordinal]), target) is False:
                            error("protocol_raw_operand", path, "expanded operand is not that original raw ordinal")
                _own_result(ctx, row, contract.result)
            except ProtocolOperandRoleError as exc:
                error("protocol_operand_role", path, exc)
            except (TypeError, ValueError) as exc:
                error("protocol_result_owner", path, exc)
        elif type(contract) is ProtocolCall:
            try:
                if operation.callee is None and (operation.terminator is None
                        or operation.terminator.kind is not TerminatorKind.INVOKE):
                    error("protocol_call_shape", path, "protocol call requires its original CALL or INVOKE")
                for identity in (contract.receiver_use, *contract.argument_uses):
                    _actual_protocol_use(ctx, operation, identity)
                _own_result(ctx, row, contract.result)
            except ProtocolOperandRoleError as exc:
                error("protocol_operand_role", path, exc)
            except (TypeError, ValueError) as exc:
                error("protocol_result_owner", path, exc)
        elif type(contract) is PacketConstruction:
            try:
                packet = ctx.packets.get(contract.packet)
                value = ctx.values.get(contract.packet)
                if packet is None or value is None or value.origin.operation != operation.id:
                    raise ValueError("packet must be the exact existing PacketDefinition owned by this operation")
                predecessor = _producer_row(ctx, contract.exception_source)
                rule = contract.rule
                if rule in (PacketRule.THROW_PACKET_FROM_NORMALIZED, PacketRule.GENERATOR_EXIT_PACKET):
                    permitted = ((RequestProcessingRule.NORMALIZE_THROW_INSTANCE, RequestProcessingRule.NORMALIZE_THROW_CLASS)
                                 if rule is PacketRule.THROW_PACKET_FROM_NORMALIZED
                                 else (RequestProcessingRule.NORMALIZE_GENERATOR_EXIT,))
                    if (predecessor is None or type(predecessor.contract) not in (RequestProcessing, ProtocolCall)
                            or getattr(predecessor.contract, 'rule', None) not in (*permitted, ProtocolCallRule.EXCEPTION_CONSTRUCTOR)):
                        raise ValueError("packet exception source must be its fixed normalization/constructor result")
                    info = ctx.port(contract.exception_source, referring=row)
                    if info is not None and any(not isinstance(ctx.values[value], ReferenceValue) for value in info.values):
                        raise ValueError("packet exception component requires Reference, not a whole packet")
                elif rule is PacketRule.FORWARD_EXISTING_PACKET:
                    candidates = [item for item in ctx.packets.values() if item.value != packet.value
                                  and type(contract.exception_source) is OwnedUse
                                  and type(contract.traceback_source) is OwnedUse
                                  and item.exception == contract.exception_source.use
                                  and item.traceback == contract.traceback_source.use]
                    if len(candidates) != 1:
                        raise ValueError("forward packet must name both components of one other exact packet")
                for source, use in ((contract.exception_source, packet.exception), (contract.traceback_source, packet.traceback)):
                    if type(source) is OwnedUse and source.operation == operation.id:
                        raise ValueError("packet cannot justify its own component sources")
                    if ctx.forwards(source, OwnedUse(operation.id, use), referring=row) is False:
                        error("protocol_copy", path, "packet component differs from its fixed original source")
                if predecessor is not None and type(predecessor.contract) is RequestProcessing:
                    raw = raw_definition(ctx, OwnedUse(predecessor.operation, predecessor.contract.raw_use))
                    if raw is not None and len(raw.operands) == 3:
                        producer = ctx.values[raw.value].origin.operation
                        if ctx.forwards(OwnedUse(producer, raw.operands[2]), OwnedUse(operation.id, packet.traceback)) is False:
                            error("protocol_packet_source", path, "traceback is not the exact raw THROW ordinal 2")
            except (AttributeError, TypeError, ValueError) as exc:
                error("protocol_contract_result" if isinstance(exc, ProtocolReferenceError)
                      else "protocol_packet_source", path, exc)
        elif type(contract) is OutcomeAdapter:
            try:
                _actual_protocol_use(ctx, operation, contract.input_use)
                body_rules = (*_EXCEPTION_ADAPTER_RULES, *_CLOSE_RULES,
                              OutcomeAdapterRule.ASYNCGEN_YIELD_TO_REQUEST_ITEM)
                if contract.rule in body_rules and type(contract.input) is not DriveResult:
                    error("protocol_adapter_source", path, "this adapter requires its exact body DriveResult")
                if type(contract.input) is DriveResult and contract.rule in body_rules:
                    if ctx.region_of.get(contract.input.outcome.drive) != ctx.region_of[operation.id]:
                        error("protocol_adapter_source", path, "body adapter source belongs to another driver region")
                if ctx.forwards(contract.input, OwnedUse(operation.id, contract.input_use), referring=row) is False:
                    error("protocol_copy", path, "adapter input is not the selected source result")
                if type(contract.input) is DriveResult:
                    body = ctx.operations[contract.input.outcome.source]
                    if contract.rule in body_rules:
                        body_values = body_outcome_uses(body)
                        if contract.input.index != 0 or not body_values:
                            error("protocol_adapter_source", path, "adapter requires the exact public payload slot zero")
                        else:
                            payload = ctx.values[ctx.owned_use(body.id, body_values[0]).value]
                            if (contract.rule is OutcomeAdapterRule.GENERATOR_ESCAPE_STOPITER_TO_RUNTIME_ERROR
                                    or (contract.rule is OutcomeAdapterRule.CLOSE_RETURN_VALUE
                                        and body.terminator.kind is TerminatorKind.RAISE)):
                                valid_payload = isinstance(payload, ProtocolValue) and payload.protocol is ProtocolValueKind.EXCEPTION_PACKET
                            else:
                                valid_payload = isinstance(payload, (ReferenceValue, DataValue))
                            if not valid_payload:
                                error("protocol_adapter_source", path, "body adapter payload has a different value role")
                    expected = {
                        OutcomeAdapterRule.GENERATOR_RETURN_TO_STOP_ITERATION: TerminatorKind.RETURN,
                        OutcomeAdapterRule.COROUTINE_RETURN_TO_STOP_ITERATION: TerminatorKind.RETURN,
                        OutcomeAdapterRule.GENERATOR_ESCAPE_STOPITER_TO_RUNTIME_ERROR: TerminatorKind.RAISE,
                        OutcomeAdapterRule.ASYNCGEN_RETURN_TO_STOP_ASYNC_ITERATION: TerminatorKind.RETURN,
                    }.get(contract.rule)
                    if expected is not None and body.terminator.kind is not expected:
                        error("protocol_adapter_source", path, "adapter rule takes a different body outcome kind")
                    if contract.rule is OutcomeAdapterRule.ASYNCGEN_YIELD_TO_REQUEST_ITEM and (
                            type(body.terminator) is not SuspendTerminator
                            or body.terminator.flavor is not SuspensionFlavor.ASYNC_YIELD):
                        error("protocol_adapter_source", path, "async item adapter requires its exact ASYNC_YIELD")
                    if contract.rule is OutcomeAdapterRule.CLOSE_RETURN_VALUE and body.terminator.kind not in (
                            TerminatorKind.RETURN, TerminatorKind.RAISE):
                        error("protocol_adapter_source", path, "close value adapter requires a terminal body outcome")
                    if contract.rule in _CLOSE_ERROR_RULES:
                        expected_flavor = (SuspensionFlavor.ASYNC_YIELD
                            if contract.rule is OutcomeAdapterRule.ASYNCGEN_CLOSE_YIELD_ERROR else SuspensionFlavor.YIELD)
                        if type(body.terminator) is not SuspendTerminator or body.terminator.flavor is not expected_flavor:
                            error("protocol_adapter_source", path, "ignored-close adapter requires the exact illegal YIELD outcome")
                if type(contract.output) in (OperationResult, InvokeLiteralResult, StaticProtocolGap):
                    produced = _own_result(ctx, row, contract.output)
                    if contract.rule in _ERROR_ADAPTER_RULES and produced is not None:
                        for value in produced.values:
                            if not isinstance(ctx.values[value], (ReferenceValue, ProtocolValue)):
                                error("protocol_adapter_source", path, "exception adapter output cannot be a state/data slot")
                            if type(contract.output) is InvokeLiteralResult:
                                kind = operation.terminator.successors[produced.edge].kind
                                if kind is ExitKind.RAISE and (not isinstance(ctx.values[value], ProtocolValue)
                                        or ctx.values[value].protocol is not ProtocolValueKind.EXCEPTION_PACKET):
                                    error("protocol_adapter_source", path, "RAISE adapter output must be its exception packet")
                    if contract.rule is OutcomeAdapterRule.CLOSE_RETURN_VALUE and produced is not None:
                        for value in produced.values:
                            actual = ctx.values[value]
                            raised = (type(contract.output) is InvokeLiteralResult
                                      and operation.terminator.successors[produced.edge].kind is ExitKind.RAISE)
                            if (raised and (not isinstance(actual, ProtocolValue)
                                    or actual.protocol is not ProtocolValueKind.EXCEPTION_PACKET)) or (
                                    not raised and not isinstance(actual, (ReferenceValue, DataValue))):
                                error("protocol_adapter_source", path, "close adapter output has a different payload role")
                else:
                    terminal = ctx.port(contract.output)
                    if contract.rule in _ERROR_ADAPTER_RULES and type(contract.output) is HostTerminal:
                        if ctx.operations[terminal.operation].terminator.kind is not TerminatorKind.RAISE:
                            error("protocol_adapter_source", path, "Python completion adapter host terminal must RAISE")
                    if type(contract.output) is HostTerminal and adapter_host_output(ctx, row) is False:
                        error("protocol_copy", path, "host output is not this adapter's selected current result")
            except ProtocolOperandRoleError as exc:
                error("protocol_operand_role", path, exc)
            except (KeyError, TypeError, ValueError) as exc:
                error("protocol_contract_result", path, exc)
        elif type(contract) is NoEntryOutcome:
            try:
                _no_entry_contract(ctx, row)
            except (TypeError, ValueError) as exc:
                error("protocol_no_entry_edge", path, exc)
    if not issues:
        issues.extend(connection_errors(ctx))
    return tuple(issues)


def host_terminals(ctx, source):
    """Original host outcomes reached before another drive/evaluation cut."""
    port = ctx.port(source)
    if port is None or port.operation is None or port.gap is not None:
        return ()
    operation = ctx.operations[port.operation]
    if port.phase == 'edge':
        start = operation.terminator.successors[port.edge].block
    else:
        start = ctx.block_of[operation.id]
    pending, seen, found = [start], set(), []
    while pending:
        if not ctx.spend('host_routes'):
            break
        identity = pending.pop()
        if identity in seen:
            continue
        seen.add(identity)
        block = ctx.blocks[identity]
        if any(item in ctx.drives for item in block.operations):
            continue
        last = ctx.operations[block.operations[-1]]
        if last.terminator.kind in (TerminatorKind.RETURN, TerminatorKind.RAISE):
            found.append(HostTerminal(last.id))
        else:
            pending.extend(edge.block for edge in last.terminator.successors)
    return tuple(found)


def _close_reaches_terminal(ctx, row, terminal):
    output = row.contract.output
    if type(output) is HostTerminal:
        return output == terminal and adapter_host_output(ctx, row) is True
    if type(output) in (OperationResult, InvokeLiteralResult):
        return host_output_copy(ctx, output, terminal) is True
    return False


def _adapter_route_copy(ctx, row, terminal):
    """This adapter's selected output, without treating a gap as a mismatch."""
    output = row.contract.output
    if type(output) is HostTerminal:
        return adapter_host_output(ctx, row) if output == terminal else False
    if type(output) in (OperationResult, InvokeLiteralResult):
        return host_output_copy(ctx, output, terminal)
    return None


def connection_errors(ctx):
    """Consumer obligations are derived from core markers, not row count."""
    errors = []
    if hasattr(ctx, 'index'):
        from .protocol_await import await_connections
        errors.extend(await_connections(ctx)['issues'])
    # AWAIT handoffs need their own selected source/incoming paths. Treating
    # two legal sources merged at one host as an unguarded must-copy would
    # reject the other incoming instead of checking this source's consumer.
    from .async_session_sources import handoff_consumers
    errors.extend(handoff_consumers(ctx)['issues'])
    for scope in ctx.scopes.values():
        if scope.profile is ProtocolProfile.CREATED_CLOSE_V1:
            from .created_close import created_close_view
            for route in created_close_view(ctx, scope)['routes']:
                if route['declared_none_result'] is False:
                    errors.append(('protocol_close_result', str(route['terminal'].operation),
                                   'created generator close must return None, not another known value or its receiver'))
        if type(scope.subject) is not DriverSubject:
            continue
        region = scope.subject.interface_region
        rows = [row for row in ctx.rows.values() if row.scope == scope.id]
        processors = [row for row in rows if type(row.contract) is RequestProcessing]
        adapters = [row for row in rows if type(row.contract) is OutcomeAdapter]
        for drive in ctx.graph.body_drives:
            if ctx.region_of[drive.operation] != region:
                continue
            if type(drive.target) is BodyResume:
                _, _, ingress = body_drive_target(ctx.graph, drive)
                for actual in drive.resume_inputs:
                    slot = ingress.inputs[actual.slot]
                    if slot.kind not in (ResumeSlotKind.SENT_VALUE, ResumeSlotKind.THROWN_PACKET):
                        continue
                    expected = ((RequestProcessingRule.CHECK_NEXT, RequestProcessingRule.CHECK_SEND)
                                if slot.kind is ResumeSlotKind.SENT_VALUE else
                                (RequestProcessingRule.NORMALIZE_THROW_INSTANCE,
                                 RequestProcessingRule.NORMALIZE_THROW_CLASS,
                                 RequestProcessingRule.NORMALIZE_GENERATOR_EXIT,
                                 RequestProcessingRule.NORMALIZE_ASYNC_THROW))
                    candidates = [row for row in processors if row.contract.rule in expected
                                  and ctx.reaches(row.contract.result, drive.operation) is not False]
                    matches = [ctx.forwards(row.contract.result, OwnedUse(drive.operation, actual.source))
                               for row in candidates]
                    if matches and all(match is False for match in matches):
                        errors.append(('protocol_copy', str(drive.operation),
                                       'body delivery is not the selected current processing result'))
            operation = ctx.operations[drive.operation]
            for edge in operation.terminator.successors:
                body = ctx.operations[edge.source]
                public = body_outcome_uses(body)
                if not public:
                    continue
                source = DriveResult(DriveOutcomeRef(drive.operation, body.id), 0)
                if type(body.terminator) is SuspendTerminator and body.terminator.flavor is SuspensionFlavor.YIELD:
                    for terminal in host_terminals(ctx, source):
                        original = ctx.operations[terminal.operation]
                        if original.terminator.kind is TerminatorKind.RETURN:
                            for target in ctx.terminal_uses(terminal):
                                if ctx.forwards(source, target) is False:
                                    errors.append(('protocol_copy', str(original.id),
                                                   'host item is not this exact YIELD export'))
                if body.terminator.kind is TerminatorKind.RETURN:
                    # Generic D1 may pass this through; the Python profile may not.
                    for terminal in host_terminals(ctx, source):
                        if ctx.operations[terminal.operation].terminator.kind is not TerminatorKind.RETURN:
                            continue
                        close_routes = [row for row in adapters
                            if row.contract.rule is OutcomeAdapterRule.CLOSE_RETURN_VALUE
                            and type(row.contract.input) is DriveResult
                            and row.contract.input.outcome == source.outcome]
                        if not any(_close_reaches_terminal(ctx, row, terminal) for row in close_routes):
                            errors.append(('protocol_host_adapter', str(drive.operation),
                                           'body Return needs its explicit Python completion adapter'))
                if body.terminator.kind is TerminatorKind.RAISE:
                    # The native profile may propagate the current whole packet
                    # or explicitly adapt this exact body outcome. Merely having
                    # some same-typed packet at the host is not propagation.
                    routes = [row for row in adapters
                              if type(row.contract.input) is DriveResult
                              and row.contract.input.outcome == source.outcome]
                    for terminal in host_terminals(ctx, source):
                        kind = ctx.operations[terminal.operation].terminator.kind
                        selected = [row for row in routes
                                    if kind is TerminatorKind.RAISE
                                    or row.contract.rule is OutcomeAdapterRule.CLOSE_RETURN_VALUE]
                        matches = [_adapter_route_copy(ctx, row, terminal) for row in selected]
                        if kind is TerminatorKind.RAISE:
                            matches.append(host_output_copy(ctx, source, terminal))
                        if not matches or all(match is False for match in matches):
                            errors.append(('protocol_copy', str(terminal.operation),
                                           'host outcome is neither this body RAISE packet nor its selected adapter result'))
        for row in adapters:
            if (row.contract.rule not in (*_ERROR_ADAPTER_RULES, OutcomeAdapterRule.CLOSE_RETURN_VALUE)
                    or type(row.contract.output) not in (OperationResult, InvokeLiteralResult)):
                continue
            for terminal in host_terminals(ctx, row.contract.output):
                expected = TerminatorKind.RAISE
                if row.contract.rule is OutcomeAdapterRule.CLOSE_RETURN_VALUE:
                    port = ctx.port(row.contract.output)
                    if port.phase != 'edge' or ctx.operations[port.operation].terminator.successors[port.edge].kind is not ExitKind.RAISE:
                        expected = TerminatorKind.RETURN
                if ctx.operations[terminal.operation].terminator.kind is not expected:
                    errors.append(('protocol_host_adapter', str(terminal.operation),
                                   'host terminal kind differs from this adapter completion'))
                if host_output_copy(ctx, row.contract.output, terminal) is False:
                    errors.append(('protocol_copy', str(terminal.operation),
                                   'host exception is not this adapter result or its explicit packet'))
        for row in processors:
            if row.clause is not ProtocolClause.RAW_ADMISSION:
                continue
            info = ctx.port(row.contract.result)
            if info is None or info.gap is not None:
                continue
            if info.values and not all(isinstance(ctx.values[value], (ReferenceValue, ProtocolValue)) for value in info.values):
                continue  # Admission booleans are control predicates, not host payloads.
            for terminal in host_terminals(ctx, row.contract.result):
                for target in ctx.terminal_uses(terminal):
                    if ctx.forwards(row.contract.result, target) is False:
                        errors.append(('protocol_copy', str(terminal.operation),
                                       'host rejection/closed output is not this helper result'))
    return tuple(errors)


def no_entry_seeds(graph, region):
    """Conditional E/F/T sources, only on the exact validated transition edge.

    Structural admission precedes this analysis. Full return-aware protocol
    validation follows core preparation. A locally unresolved/invalid payload
    cannot grant a seed here; the later validator reports its contradiction.
    """
    rows = [row for row in graph.protocol_operations if type(row.contract) is NoEntryOutcome
            and row.clause in (ProtocolClause.INITIAL_THROW_DELIVERED,
                               ProtocolClause.INITIAL_THROW_CONSTRUCTOR_FAILURE)]
    if not rows:
        return {}
    ctx, result = ProtocolFlow(graph), {}
    for row in rows:
        if ctx.region_of[row.operation] != region:
            continue
        try:
            if not _no_entry_contract(ctx, row)["complete"]:
                continue
            edge = row.contract.selected_edge
            key = (row.operation, None if edge is None else edge.successor_index)
            result[key] = ctx.owned_use(row.operation, row.contract.instance_use).value
        except (TypeError, ValueError):
            continue
    return result


__all__ = ["protocol_errors", "raw_definition", "no_entry_route", "no_entry_seeds",
           "connection_errors", "host_terminals"]
