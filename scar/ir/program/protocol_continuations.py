"""Fixed await/delegation obligations over original operations and ports.

The shared connection context owns copy, caller, guard and tuple analysis.
This module assigns the closed protocol meanings to those existing ports. It
does not infer a native method from an operation label or construct another
producer, state or scheduling graph.
"""
from .control import ProtocolValueKind as P
from .driver_flow import body_drive_target
from .drivers import BodyResume, RawRequestKind
from .model import (AccessMode, BlockArgument, ExitKind, InvokeLiteralResult, LiteralOrigin,
                    OperationResult, ProtocolValue, ReferenceValue,
                    StateVersionValue, TerminatorKind)
from .protocol_connections import (
    InitialAdvance, InjectedPacketTrigger, ProtocolOperationRef,
    RawOperandSource, RawRequestTrigger, ResumeSourceBinding,
)
from .protocols import (
    ContractResult, DriverSubject, HostTerminal, OutcomeAdapter,
    OutcomeAdapterRule as AR, OwnedUse, ProtocolCall, ProtocolCallRule as CR,
    ProtocolClause as C, StaticProtocolGap,
)
from .resumption import ResumeSlotKind, SuspendTerminator
from .structured import ControlEdgeReference


_METHOD_LOOKUP = {
    CR.DELEGATE_NEXT: CR.DELEGATE_NEXT_LOOKUP,
    CR.DELEGATE_SEND: CR.DELEGATE_SEND_LOOKUP,
    CR.DELEGATE_THROW: CR.DELEGATE_THROW_LOOKUP,
    CR.DELEGATE_CLOSE: CR.DELEGATE_CLOSE_LOOKUP,
}
_METHOD_LOOKUPS = tuple(_METHOD_LOOKUP.values())
_LOOKUPS = (CR.AWAIT_LOOKUP, CR.DELEGATE_ITER, *_METHOD_LOOKUPS)
_ADVANCES = (CR.DELEGATE_NEXT, CR.DELEGATE_SEND, CR.DELEGATE_THROW, CR.DELEGATE_CLOSE)
_CONTINUATION_RULES = (*_LOOKUPS, CR.AWAIT_CALL, *_ADVANCES)
_ADAPTERS = (AR.AWAIT_STOPITER_TO_EXPRESSION, AR.DELEGATE_ITEM_TO_PARENT_YIELD,
             AR.DELEGATE_STOPITER_TO_PARENT_VALUE, AR.DELEGATE_ONLY_HOST_ITEM,
             AR.DELEGATE_ONLY_HOST_EXCEPTION)


def _site(row):
    return ProtocolOperationRef(row.scope, row.clause, row.operation, row.slot)


def _selected_kind(ctx, source):
    if type(source) is ContractResult:
        source = source.result_port
    if type(source) is InvokeLiteralResult:
        operation = ctx.operations.get(source.edge.operation)
        if (operation is None or operation.terminator is None
                or source.edge.successor_index >= len(operation.terminator.successors)):
            return None
        return operation.terminator.successors[source.edge.successor_index].kind
    if type(source) is OperationResult:
        return ExitKind.NORMAL
    return None


def _source_row(ctx, source):
    if type(source) is not ContractResult:
        return None
    row = ctx.rows.get((source.scope, source.clause, source.operation, source.slot))
    # The shared original-port resolver checks the selected own result too.
    ctx.port(source)
    return row


def _formal_producer(ctx, source, candidates):
    """Use the independently named formal, never the actual receiver, as anchor.

    A direct completion landing already identifies its original result. For a
    later copy/merge, retain the existing unique semantic inventory rule; more
    than one candidate needs explicit per-case sources instead of guessing.
    """
    port = ctx.port(source)
    if port is None or port.gap is not None:
        return None
    direct = []
    for candidate in candidates:
        if not ctx.spend("continuation_formal_candidates"):
            return None
        produced = ctx.port(candidate.contract.result)
        if produced is not None and produced.gap is None and produced.values == port.values:
            direct.append(candidate)
    if len(direct) == 1:
        return direct[0]
    return candidates[0] if not direct and len(candidates) == 1 else None


def _iterator_use(ctx, row, case):
    """The original iterator operand for an atomic or expanded advance."""
    producer = _source_row(ctx, case.receiver)
    if type(case.receiver) is BlockArgument:
        producer = _formal_producer(ctx, case.receiver,
                                   getattr(ctx, "_continuation_normal_sources", ()))
    if (producer is not None and type(producer.contract) is ProtocolCall
            and producer.contract.rule in _METHOD_LOOKUPS):
        return OwnedUse(producer.operation, producer.contract.receiver_use)
    return OwnedUse(row.operation, row.contract.receiver_use)


def _declared_none(ctx, raw):
    """Exact declared payload only; not runtime None identity/source proof."""
    from scar.ir.literals import LiteralKind, PythonLiteral
    from .literal_sources import ExactLiteralOrigin
    if len(raw.operands) != 1:
        return False
    producer = ctx.values[raw.value].origin.operation
    actual = OwnedUse(producer, raw.operands[0])
    value = ctx.values[ctx.owned_use(actual.operation, actual.use).value]
    if type(value.origin) is LiteralOrigin:
        return value.origin.value is None
    if type(value.origin) is ExactLiteralOrigin:
        return value.origin.literal.kind is LiteralKind.NONE
    known = []
    for declaration in ctx.graph.literal_evaluations:
        if not ctx.spend("continuation_none_literals"):
            return None
        if type(declaration.literal) is PythonLiteral and ctx.bind(declaration.site, actual)["match"] is True:
            known.append(declaration.literal.kind is LiteralKind.NONE)
    return known[0] if known and all(item == known[0] for item in known) else None


def _payload_role(ctx, source):
    port = ctx.port(source)
    if port is None or port.gap is not None or not port.values:
        return None
    values = tuple(ctx.values[value] for value in port.values)
    if all(isinstance(value, ReferenceValue) for value in values):
        return "reference"
    if all(isinstance(value, ProtocolValue) and value.protocol is P.EXCEPTION_PACKET for value in values):
        return "packet"
    return "other"


def _first_advance(ctx, iterator, row, guard, advance_operations):
    """No prior advance since this exact iterator evaluation, including loops.

    The finite worklist is over original operation positions and one Boolean.
    A re-evaluation ends the old iterator's interval; its next evaluation is
    checked by the same source-relative obligation. No path/configuration list
    is retained. Every visit and edge is charged to the shared context.
    """
    port = ctx.port(iterator)
    if port is None or port.operation is None or port.gap is not None:
        return None
    if ctx.region_of[port.operation] != ctx.region_of[row.operation]:
        return None
    if port.phase == "edge":
        start = (ctx.operations[port.operation].terminator.successors[port.edge].block, 0, False)
    else:
        start = (ctx.block_of[port.operation], ctx.positions[port.operation] + 1, False)
    pending, seen, reached, unknown = [start], set(), False, False
    while pending:
        if not ctx.spend("continuation_initial_positions"):
            return None
        block_id, position, advanced = pending.pop()
        key = block_id, position, advanced
        if key in seen:
            continue
        seen.add(key)
        block = ctx.blocks[block_id]
        if position >= len(block.operations):
            continue
        identity = block.operations[position]
        if identity == port.operation:
            continue  # This evaluation's iterator is replaced here.
        if identity == row.operation:
            reached = True
            if advanced:
                return False
        other = advance_operations.get(identity)
        if other is not None:
            declaration = ctx.call_inputs.get(_site(other))
            matches = []
            for case in (() if declaration is None else declaration.cases):
                choices = ctx.selected_edges(guard)
                if case.guard is not None:
                    if any(edge.operation == case.guard.operation and edge != case.guard for edge in choices):
                        # Different visits cannot be identified by two mutually
                        # exclusive static choices. Keep the occurrence gap.
                        matches.append(None)
                        continue
                    choices = (*choices, case.guard)
                actual = _iterator_use(ctx, other, case)
                match = ctx.bind(iterator, actual, guard=choices)["match"]
                if match is False and ctx.may_forwards(iterator, actual) is not False:
                    # must-copy false does not prove absence on each incoming
                    # route of an atomic receiver phi.
                    unknown = True
                matches.append(match)
            if declaration is None:
                actual = OwnedUse(identity, other.contract.receiver_use)
                matches.append(ctx.bind(iterator, actual, guard=guard)["match"])
                unknown = True
            if not matches or any(match is None for match in matches) or len(set(matches)) > 1:
                unknown = True
            advanced = advanced or bool(matches) and all(match is True for match in matches)
        operation = ctx.operations[identity]
        if (identity != row.operation and other is None and (
                operation.callee is not None or operation.terminator is not None
                and operation.terminator.kind is TerminatorKind.INVOKE
                or not operation.effects_complete
                or any(access.mode is not AccessMode.READ for access in operation.accesses))):
            # A callback can advance an aliased iterator without a typed local
            # step. Keep that source-applicability condition, never certify an
            # InitialAdvance from the marker alone.
            # An unresolved path must not hide a known repeated advance on
            # another path. Continue with only the advances already proved;
            # unknown paths prevent success but cannot erase a counterexample.
            unknown = True
        if operation.terminator is None:
            pending.append((block_id, position + 1, advanced))
        else:
            for index, edge in reversed(tuple(enumerate(operation.terminator.successors))):
                if not ctx.spend("continuation_initial_edges"):
                    return None
                if guard is None or guard.operation != identity or guard.successor_index == index:
                    pending.append((edge.block, 0, advanced))
    return True if reached and not unknown else None


def _close_frontier(ctx, row, case, pending_by_operation, check, issue, missing):
    """Selected close completion -> the next original packet consumer.

    NORMAL continues the independent injected packet; RAISE overrides it with
    this call's own packet. A native close's normal None is never an item or a
    replacement exception. Opaque interposition remains a precise boundary.
    """
    selected = _selected_kind(ctx, row.contract.result)
    if selected is ExitKind.NORMAL:
        if type(case.trigger) is not InjectedPacketTrigger:
            missing("delegate_close_normal_injected_source_unresolved", _site(row))
            return {"status": "MISSING", "targets": ()}
        source = case.trigger.packet
    else:
        source = row.contract.result
    choices = (ControlEdgeReference(row.operation, row.slot),)
    def packet_match(target):
        report = ctx.bind(source, target, guard=case.guard, choices=choices)
        if report["match"] is False and ctx.may_forwards(source, target) is True:
            # The selected completion and an earlier input case can meet at a
            # later C1 merge. A possible copy is not a must proof, but neither
            # is the unconditioned must-failure an exact wrong-route proof.
            missing("delegate_close_c1_guard_correlation_unresolved", target.operation)
            return None
        return report["match"]
    port = ctx.port(row.contract.result)
    if port is None or port.gap is not None or port.phase != "edge":
        missing("delegate_close_completion_unresolved", _site(row))
        return {"status": "MISSING", "targets": ()}
    edge = ctx.operations[row.operation].terminator.successors[port.edge]
    pending, seen, targets, unknown = [(edge.block, 0)], set(), [], False
    region = ctx.region_of[row.operation]
    rank_cache = getattr(ctx, "_continuation_ranks", None)
    if rank_cache is None:
        rank_cache = ctx._continuation_ranks = {}
    if region not in rank_cache:
        _, _, _, _, order = ctx._edges(region)
        rank_cache[region] = {block: index for index, block in enumerate(order)}
    ranks = rank_cache[region]
    while pending:
        if not ctx.spend("continuation_close_positions"):
            missing("delegate_close_route_truncated", _site(row))
            return {"status": "NOT_CHECKED", "targets": tuple(targets)}
        block_id, position = pending.pop()
        if (block_id, position) in seen:
            continue
        seen.add((block_id, position))
        block = ctx.blocks[block_id]
        identity = block.operations[position]
        operation = ctx.operations[identity]
        if identity in ctx.drives:
            drive = ctx.drives[identity]
            if type(drive.target) is not BodyResume:
                issue("protocol_close_continuation", _site(row), "delegate close cannot invent a parent Start ingress")
            else:
                _, _, successor = body_drive_target(ctx.graph, drive)
                payloads = tuple(actual for actual in drive.resume_inputs
                    if successor.inputs[actual.slot].kind is not ResumeSlotKind.STATE)
                for actual in payloads:
                    target = OwnedUse(identity, actual.source)
                    if successor.inputs[actual.slot].kind not in (ResumeSlotKind.THROWN_PACKET, ResumeSlotKind.DELEGATE_PACKET):
                        issue("protocol_close_continuation", _site(row), "close continuation requires the parent's packet slot")
                    match = packet_match(target)
                    unknown |= match is None
                    check(match, _site(row),
                          "parent close continuation lost the selected current packet", "protocol_close_continuation")
                    targets.append(target)
            continue
        # Constructors are not the active handoff by themselves. Only the
        # actual C1 token below selects its possible original payload sources;
        # an unused good or bad pack cannot change this frontier's verdict.
        action = ctx.index.cleanup_action(identity)
        from .cleanup import CleanupEnter, CleanupReplace, CleanupResume
        if type(action) in (CleanupEnter, CleanupReplace, CleanupResume):
            actual = OwnedUse(identity, action.replacement if type(action) is CleanupReplace else action.pending)
            verdicts, support = [], []
            for producer, candidates in pending_by_operation.items():
                if ctx.region_of[producer] != ctx.region_of[identity]:
                    continue
                for definition in candidates:
                    if not ctx.spend("continuation_close_pending_sources"):
                        missing("delegate_close_route_truncated", _site(row))
                        return {"status": "NOT_CHECKED", "targets": tuple(targets)}
                    token = ctx.bind(ctx.values[definition.value].origin, actual,
                                     guard=case.guard, choices=choices)
                    if token["match"] is not True:
                        if token["match"] is None or ctx.may_forwards(ctx.values[definition.value].origin, actual) is True:
                            missing("delegate_close_c1_guard_correlation_unresolved", identity)
                            unknown = True
                        continue
                    packet = None if definition.payload is None else packet_match(OwnedUse(producer, definition.payload))
                    verdicts.append(packet)
                    support.append({"definition": definition, "token_binding": token, "packet_match": packet})
            if verdicts and all(value is True for value in verdicts):
                targets.append(actual)
            elif False in verdicts:
                issue("protocol_close_continuation", _site(row), "active C1 pending uses another packet after close")
            else:
                missing("delegate_close_pending_source_unresolved", identity)
                unknown = True
            targets.append({"action": action, "actual": actual, "sources": tuple(support)})
            continue
        term = operation.terminator
        if type(term) is SuspendTerminator:
            missing("delegate_close_parent_suspend_unresolved", identity)
            unknown = True
            continue
        if term is not None and term.kind in (TerminatorKind.RETURN, TerminatorKind.RAISE):
            if term.kind is not TerminatorKind.RAISE:
                issue("protocol_close_continuation", _site(row), "delegate close continues/overrides a packet, not its None result")
            for target in ctx.terminal_uses(HostTerminal(identity)):
                match = packet_match(target)
                unknown |= match is None
                check(match, _site(row),
                      "host close continuation is not this selected current packet", "protocol_close_continuation")
                targets.append(target)
            continue
        if operation.callee is not None or term is not None and term.kind is TerminatorKind.INVOKE:
            missing("delegate_close_intervening_call_unresolved", identity)
            unknown = True
            continue
        if term is None:
            pending.append((block_id, position + 1))
        else:
            for successor in reversed(term.successors):
                if not ctx.spend("continuation_close_edges"):
                    missing("delegate_close_route_truncated", _site(row))
                    return {"status": "NOT_CHECKED", "targets": tuple(targets)}
                if ranks.get(successor.block, 0) <= ranks.get(block_id, 0):
                    unknown = True
                pending.append((successor.block, 0))
    if unknown or not targets:
        missing("delegate_close_consumer_inventory_unresolved", _site(row))
    return {"status": "PARTIAL" if unknown or not targets else "DECLARED", "source": source, "targets": tuple(targets)}


def _close_route(ctx, row, case, pending_by_operation, check, issue, missing):
    """Keep the first-handoff receipt and check its actual later consumers."""
    from .protocol_packet_routes import packet_continuations

    frontier = _close_frontier(ctx, row, case, pending_by_operation, check, issue, missing)
    frontier = {**frontier, 'frontier_only': True,
                'source_runtime_verified': False, 'runtime_identity_verified': False,
                'transformation_authorized': False}
    if 'source' not in frontier:
        return {**frontier, 'first_frontier': frontier, 'known_inventory_complete': False,
                'source_inventory_complete': False, 'frontier_only': False}
    port = ctx.port(row.contract.result)
    if port is None or port.gap is not None or port.phase != 'edge':
        return {**frontier, 'status': 'PARTIAL', 'first_frontier': frontier,
                'known_inventory_complete': False, 'source_inventory_complete': False,
                'frontier_only': False}
    choices = ctx.selected_edges((ControlEdgeReference(row.operation, row.slot),
                                 *((case.guard,) if case.guard is not None else ())))
    edge = ctx.operations[row.operation].terminator.successors[port.edge]
    result = packet_continuations(ctx, frontier['source'], start=(edge.block, 0),
                                  choices=choices, cuts=(row.operation,))
    for item in result['checks']:
        check(item['binding']['match'], _site(row),
              "close continuation does not preserve its independently selected packet at the actual consumer",
              "protocol_close_continuation")
    for gap in result['gaps']:
        missing(gap, _site(row))
    return {**result, 'first_frontier': frontier}


def continuation_connections(ctx):
    """Return fixed-rule checks plus a denominator retained on truncation.

    Call only on the canonical-valid graph with its shared ConnectionContext.
    Missing declarations and source applicability remain explicit obligations;
    known port/role contradictions are issue triples.
    """
    cached = getattr(ctx, "_continuation_connections", None)
    if cached is not None:
        return cached
    issues, obligations, gaps, cursor, resume_rows = [], [], [], None, []
    advance_operations = {item.operation: item for item in ctx.rows.values()
        if type(item.contract) is ProtocolCall and item.contract.rule in _ADVANCES}
    ctx.preparation["continuation_rows"] = len(ctx.graph.protocol_operations)
    ctx.preparation["continuation_advance_operations"] = len(advance_operations)
    lookup_inventory = {}
    normal_sources = []
    pending_by_operation = {}
    for definition in ctx.graph.pending_completions:
        origin = ctx.values[definition.value].origin
        if type(origin) is OperationResult:
            pending_by_operation.setdefault(origin.operation, []).append(definition)
    for item in ctx.graph.protocol_operations:
        if (type(item.contract) is ProtocolCall and item.contract.rule in (*_LOOKUPS, CR.AWAIT_CALL)
                and _selected_kind(ctx, item.contract.result) is ExitKind.NORMAL):
            lookup_inventory.setdefault((item.scope, item.contract.rule), []).append(item)
            normal_sources.append(item)
    ctx._continuation_normal_sources = tuple(normal_sources)
    method_consumers = {}
    if any(type(row.contract) is ProtocolCall and row.contract.rule in _METHOD_LOOKUPS
           for row in ctx.graph.protocol_operations):
        # Reuse the independent fixed-output inventory and its already charged
        # shared report, rather than inventing a lookup-to-call relation table.
        from .protocol_connection_validation import common_connections
        method_consumers = {report["site"]: report
                            for report in common_connections(ctx)["consumers"]}

    def issue(code, path, message):
        issues.append((code, str(path), message))

    def missing(code, path):
        gaps.append({"code": code, "path": str(path)})

    def check(match, path, message, code="protocol_continuation_source"):
        if match is False:
            issue(code, path, message)
        elif match is None:
            missing("continuation_source_unresolved", path)

    def role(source, expected, path):
        actual = _payload_role(ctx, source)
        check(None if actual is None else actual == expected, path,
              "fixed continuation port has the wrong payload role", "protocol_continuation_role")

    from .protocol_lookup_fallbacks import fallback_binding_issues, lookup_fallbacks
    issues.extend(fallback_binding_issues(ctx))

    # Supplied metadata outside the canonical slot inventory is a contradiction,
    # not an absent obligation that can disappear from the derived traversal.
    for row in ctx.graph.protocol_operations:
        if type(row.contract) is not ResumeSourceBinding:
            continue
        identity = _site(row)
        view = {"site": identity, "row": row, "status": "NOT_CHECKED"}
        resume_rows.append(view)
        if not ctx.spend("continuation_resume_rows"):
            if cursor is None:
                cursor = {"site": identity, "phase": "continuation_resume_rows"}
            continue
        drive = ctx.drives.get(row.operation)
        scope = ctx.scopes.get(row.scope)
        if (row.clause is not C.BODY_INGRESS or drive is None or type(drive.target) is not BodyResume
                or scope is None or type(scope.subject) is not DriverSubject
                or scope.subject.interface_region != ctx.region_of.get(row.operation)):
            issue("protocol_resume_site", identity, "resume source requires this scope's exact existing BodyResume Drive")
            view["status"] = "CONTRADICTED"
            continue
        try:
            _, _, successor = body_drive_target(ctx.graph, drive)
            if (row.slot >= len(successor.inputs) or successor.inputs[row.slot].kind is ResumeSlotKind.STATE
                    or not any(actual.slot == row.slot for actual in drive.resume_inputs)):
                raise ValueError("resume source slot must be an actual non-STATE delivery slot")
        except (IndexError, KeyError, TypeError, ValueError) as exc:
            issue("protocol_resume_site", identity, str(exc))
            view["status"] = "CONTRADICTED"
        else:
            view["status"] = "DECLARED"

    for row in ctx.graph.protocol_operations:
        contract = row.contract
        selected = ((type(contract) is ProtocolCall and contract.rule in _CONTINUATION_RULES)
                    or (type(contract) is OutcomeAdapter and contract.rule in _ADAPTERS))
        if not selected:
            continue
        identity = _site(row)
        entry = {"site": identity, "row": row, "status": "NOT_CHECKED", "checks": ()}
        obligations.append(entry)
        if not ctx.spend("continuation_sites"):
            if cursor is None:
                cursor = {"site": identity, "phase": "continuation_sites"}
            continue
        before_issues, before_gaps = len(issues), len(gaps)
        try:
            if type(contract) is ProtocolCall:
                role(contract.result, "reference" if _selected_kind(ctx, contract.result) is ExitKind.NORMAL else "packet", identity)
                if contract.rule in _METHOD_LOOKUPS and contract.argument_uses:
                    issue("protocol_continuation_arguments", identity,
                          "method lookup names its iterator but has no request arguments")
                declaration = ctx.call_inputs.get(identity)
                if declaration is None:
                    missing("continuation_call_inputs_missing", identity)
                else:
                    for number, case in enumerate(declaration.cases):
                        if not ctx.spend("continuation_cases"):
                            missing("continuation_case_not_checked", identity)
                            if cursor is None:
                                cursor = {"site": identity, "case": number}
                            break
                        rule = contract.rule
                        producer = _source_row(ctx, case.receiver)
                        if type(case.receiver) is BlockArgument and rule in (CR.AWAIT_CALL, *_ADVANCES, *_METHOD_LOOKUPS):
                            required = ((CR.AWAIT_LOOKUP,) if rule is CR.AWAIT_CALL else
                                        (CR.DELEGATE_ITER, CR.AWAIT_CALL, _METHOD_LOOKUP[rule])
                                        if rule in _ADVANCES else (CR.DELEGATE_ITER, CR.AWAIT_CALL))
                            candidates = tuple(candidate for kind in required
                                for candidate in lookup_inventory.get((row.scope, kind), ()))
                            direct = _formal_producer(ctx, case.receiver, tuple(normal_sources))
                            original = direct if direct is not None else _formal_producer(ctx, case.receiver, candidates)
                            if original is not None:
                                expected = ContractResult(original.scope, original.clause, original.operation,
                                                          original.slot, original.contract.result)
                                check(ctx.bind(expected, OwnedUse(row.operation, contract.receiver_use),
                                    guard=case.guard)["match"], identity,
                                    "merge formal is not the independently required lookup evaluation")
                                producer = original
                            else:
                                missing("continuation_formal_lookup_inventory_unresolved", identity)
                        if rule is CR.AWAIT_CALL:
                            valid = (producer is not None and type(producer.contract) is ProtocolCall
                                     and producer.contract.rule is CR.AWAIT_LOOKUP
                                     and producer.scope == row.scope
                                     and _selected_kind(ctx, producer.contract.result) is ExitKind.NORMAL)
                            # A formal remains representable, but its lookup
                            # provenance needs independent incoming inventory.
                            check(None if producer is None and type(case.receiver) in (BlockArgument, StaticProtocolGap) else valid,
                                  identity, "await call receiver must be its exact NORMAL lookup result")
                        elif rule in (*_ADVANCES, *_METHOD_LOOKUPS):
                            allowed = ((CR.DELEGATE_ITER, CR.AWAIT_CALL, _METHOD_LOOKUP[rule])
                                       if rule in _ADVANCES else (CR.DELEGATE_ITER, CR.AWAIT_CALL))
                            valid = (producer is not None and type(producer.contract) is ProtocolCall
                                     and producer.contract.rule in allowed
                                     and _selected_kind(ctx, producer.contract.result) is ExitKind.NORMAL)
                            check(None if producer is None and type(case.receiver) in (BlockArgument, StaticProtocolGap) else valid,
                                  identity, "receiver must be this iterator evaluation or the matching own NORMAL method lookup")
                        else:
                            role(case.receiver, "reference", identity)
                        if rule in _LOOKUPS or rule is CR.AWAIT_CALL:
                            if case.trigger is not None or case.arguments:
                                issue("protocol_continuation_arguments", identity,
                                      "lookup and zero-argument await calls have no request trigger/arguments")
                        else:
                            _check_trigger(ctx, row, case, identity, check, issue, missing)
                        if rule is CR.DELEGATE_CLOSE:
                            entry.setdefault("close_routes", []).append(
                                _close_route(ctx, row, case, pending_by_operation, check, issue, missing))
                        if type(case.trigger) is InitialAdvance:
                            if rule is not CR.DELEGATE_NEXT or case.arguments:
                                issue("protocol_continuation_trigger", identity, "InitialAdvance is only a zero-argument NEXT")
                            expanded = (producer is not None and type(producer.contract) is ProtocolCall
                                        and producer.contract.rule in _METHOD_LOOKUPS)
                            if (not expanded and type(case.receiver) is not BlockArgument
                                    and case.receiver != case.trigger.iterator):
                                issue("protocol_continuation_trigger", identity, "initial marker must select the independently expected iterator")
                            marker = _source_row(ctx, case.trigger.iterator)
                            if (marker is None or type(marker.contract) is not ProtocolCall
                                    or marker.contract.rule not in (CR.DELEGATE_ITER, CR.AWAIT_CALL)
                                    or _selected_kind(ctx, marker.contract.result) is not ExitKind.NORMAL):
                                issue("protocol_continuation_trigger", identity,
                                      "initial marker requires the exact own NORMAL iterator evaluation")
                            check(ctx.bind(case.trigger.iterator, _iterator_use(ctx, row, case),
                                guard=case.guard)["match"], identity,
                                "initial marker does not name this call's actual iterator evaluation",
                                "protocol_initial_advance")
                            check(_first_advance(ctx, case.trigger.iterator, row, case.guard, advance_operations), identity,
                                  "initial marker is reused after an advance without a new iterator evaluation",
                                  "protocol_initial_advance")
                if contract.rule in _METHOD_LOOKUPS:
                    if _selected_kind(ctx, contract.result) is ExitKind.RAISE:
                        entry['method_exception_matches'] = _method_exception_matches(
                            ctx, row, method_consumers.get(identity), missing)
                        entry['lookup_fallbacks'] = lookup_fallbacks(
                            ctx, row, entry['method_exception_matches'], issue, missing)
                        missing("method_lookup_exception_category_unproved", identity)
                    else:
                        ledger = method_consumers.get(identity)
                        entry["method_call_consumers"] = _method_call_consumers(
                            ctx, row, ledger, advance_operations, check, issue, missing)
            else:
                _check_adapter(ctx, row, identity, check, issue, missing, role)
        except (AttributeError, IndexError, KeyError, TypeError, ValueError) as exc:
            issue("protocol_continuation_port", identity, str(exc))
        entry["status"] = ("CONTRADICTED" if len(issues) != before_issues else
                           "PARTIAL" if len(gaps) != before_gaps else "DECLARED")
    # The canonical slots establish the denominator before optional new rows.
    for drive in ctx.graph.body_drives:
        if type(drive.target) is not BodyResume:
            continue
        region = ctx.region_of[drive.operation]
        scopes = tuple(scope for scope in ctx.scopes.values()
            if type(scope.subject) is DriverSubject and scope.subject.interface_region == region)
        if not scopes:
            continue
        _, _, successor = body_drive_target(ctx.graph, drive)
        for actual in drive.resume_inputs:
            kind = successor.inputs[actual.slot].kind
            if kind is ResumeSlotKind.STATE:
                continue
            for scope in scopes:
                identity = ProtocolOperationRef(scope.id, C.BODY_INGRESS, drive.operation, actual.slot)
                row = ctx.rows.get((scope.id, C.BODY_INGRESS, drive.operation, actual.slot))
                entry = {"site": identity, "row": row, "kind": kind,
                         "actual": OwnedUse(drive.operation, actual.source), "status": "NOT_CHECKED"}
                obligations.append(entry)
                if not ctx.spend("continuation_resume_slots"):
                    if cursor is None:
                        cursor = {"site": identity, "phase": "continuation_resume_slots"}
                    continue
                if row is None or type(row.contract) is not ResumeSourceBinding:
                    entry["status"] = "MISSING"
                    missing("continuation_resume_source_missing", identity)
                    continue
                before_issues, before_gaps = len(issues), len(gaps)
                try:
                    role(row.contract.source, "packet" if kind in (
                        ResumeSlotKind.THROWN_PACKET, ResumeSlotKind.DELEGATE_PACKET) else "reference", identity)
                    report = ctx.bind(row.contract.source, entry["actual"], path=str(identity))
                    entry["binding"] = report
                    check(report["match"], identity, "resume slot does not consume its independent current source",
                          "protocol_resume_source")
                except (AttributeError, IndexError, KeyError, TypeError, ValueError) as exc:
                    issue("protocol_resume_source", identity, str(exc))
                entry["status"] = ("CONTRADICTED" if len(issues) != before_issues else
                                   "PARTIAL" if len(gaps) != before_gaps else "DECLARED")
    if ctx.budget.truncated and cursor is None:
        cursor = {"phase": "continuation_derivation"}
    result = {"issues": tuple(issues), "obligations": tuple(obligations), "resume_rows": tuple(resume_rows), "gaps": tuple(gaps),
              "cursor": cursor, "source_runtime_verified": False, "transformation_authorized": False,
              "conditions": ("native lookup, exception-category and iterator interpretation unproved",)}
    ctx._continuation_connections = result
    return result


def _method_exception_matches(ctx, row, ledger, missing):
    """Connect actual lookup-packet consumers without granting fallback.

    A matching operation's own RAISE packet is a different source. The native
    class test and the handler's packet/control action remain separate duties.
    """
    from .exception_match_query import matcher_view
    source = ContractResult(row.scope, row.clause, row.operation, row.slot, row.contract.result)
    matches = []
    if ledger is None:
        missing('method_lookup_exception_consumer_inventory_unresolved', _site(row))
        return ()
    for support in ledger.get('support', ()):
        if not ctx.spend('continuation_exception_matches'):
            missing('method_lookup_exception_match_inventory_truncated', _site(row))
            break
        actual = support['use']
        matcher = ctx.index._exception_matches.get(actual.operation)
        if matcher is None or matcher.input_use != actual.use:
            continue
        binding = ctx.bind(source, actual)
        report = matcher_view(ctx, matcher)
        matches.append({'matcher': matcher, 'input_binding': binding, 'report': report})
        if binding['match'] is not True:
            missing('method_lookup_exception_match_source_unresolved', _site(row))
    if not matches:
        missing('method_lookup_exception_matcher_unresolved', _site(row))
    return tuple(matches)


def _method_call_consumers(ctx, row, ledger, advances, check, issue, missing):
    """Check fixed lookup output consumers before any target declarations.

    The source is already the independently named lookup result. Discovering
    its original Uses cannot select a different expected receiver for a call.
    Atomic helpers on unrelated paths do not become expanded lookup consumers.
    """
    identity = _site(row)
    if ledger is None:
        missing("method_lookup_consumer_inventory_unresolved", identity)
        return ()
    source = ContractResult(row.scope, row.clause, row.operation, row.slot, row.contract.result)
    consumers = []
    for support in ledger.get("support", ()):
        if not ctx.spend("continuation_method_consumers"):
            missing("method_lookup_consumer_inventory_truncated", identity)
            break
        actual = support["use"]
        call = advances.get(actual.operation)
        if call is None:
            continue
        if actual.use != call.contract.receiver_use:
            missing("method_lookup_not_callable_receiver", actual.operation)
            continue
        consumer = {"call": _site(call), "actual": actual, "source": source, "cases": ()}
        consumers.append(consumer)
        if _METHOD_LOOKUP[call.contract.rule] is not row.contract.rule:
            issue("protocol_method_lookup_kind", identity,
                  "bound method is consumed by a different fixed delegation request")
            continue
        declaration = ctx.call_inputs.get(_site(call))
        if declaration is None:
            missing("method_lookup_call_inputs_missing", _site(call))
            continue
        cases = []
        for case in declaration.cases:
            report = ctx.bind(source, actual, guard=case.guard)
            if report["match"] is not True:
                if report["match"] is None:
                    missing("method_lookup_consumer_case_unresolved", _site(call))
                continue
            expected = _source_row(ctx, case.receiver)
            if type(case.receiver) is BlockArgument:
                expected = _formal_producer(ctx, case.receiver,
                    getattr(ctx, "_continuation_normal_sources", ()))
            match = (None if expected is None and type(case.receiver) in (BlockArgument, StaticProtocolGap)
                     else expected == row)
            check(match, _site(call), "call's independent expected receiver is not this lookup evaluation",
                  "protocol_method_lookup_consumer")
            cases.append({"guard": case.guard, "binding": report, "expected": case.receiver,
                          "match": match})
        consumer["cases"] = tuple(cases)
        if not cases:
            missing("method_lookup_consumer_case_unresolved", _site(call))
    if not consumers:
        missing("method_lookup_call_consumer_missing", identity)
    if not ledger.get("known_inventory_complete", False):
        missing("method_lookup_consumer_inventory_unresolved", identity)
    return tuple(consumers)


def _check_trigger(ctx, row, case, path, check, issue, missing):
    from .protocol_validation import raw_definition
    rule, trigger = row.contract.rule, case.trigger
    expected_count = {CR.DELEGATE_NEXT: 0, CR.DELEGATE_SEND: 1, CR.DELEGATE_CLOSE: 0}.get(rule)
    if expected_count is not None and len(case.arguments) != expected_count:
        issue("protocol_continuation_arguments", path, "fixed request uses a different argument count")
    if rule is CR.DELEGATE_THROW and not 1 <= len(case.arguments) <= 3:
        issue("protocol_continuation_arguments", path, "delegate.throw preserves one to three raw operands")
    if type(trigger) in (InitialAdvance, StaticProtocolGap):
        if type(trigger) is StaticProtocolGap:
            missing("continuation_trigger_unresolved", path)
        return
    if type(trigger) is InjectedPacketTrigger:
        if rule is not CR.DELEGATE_CLOSE:
            issue("protocol_continuation_trigger", path, "an injected close packet cannot trigger NEXT/SEND/THROW")
        actual = _payload_role(ctx, trigger.packet)
        check(None if actual is None else actual == "packet", path,
              "close injection must name the current whole exception packet", "protocol_continuation_trigger")
        missing("generator_exit_category_unproved", path)
        return
    if type(trigger) is not RawRequestTrigger:
        issue("protocol_continuation_trigger", path, "this request needs an exact raw/packet/initial trigger")
        return
    raw_use = ctx.owned_use(trigger.raw.operation, trigger.raw.use)
    value = ctx.values[raw_use.value]
    if not isinstance(value, ProtocolValue) or value.protocol is not P.RAW_DRIVER_REQUEST:
        issue("protocol_continuation_trigger", path, "raw trigger has the wrong canonical role")
        return
    raw = raw_definition(ctx, trigger.raw)
    if raw is None:
        missing("continuation_external_raw_unresolved", path)
        return
    permitted = {CR.DELEGATE_NEXT: (RawRequestKind.NEXT, RawRequestKind.SEND),
                 CR.DELEGATE_SEND: (RawRequestKind.SEND,), CR.DELEGATE_THROW: (RawRequestKind.THROW,),
                 CR.DELEGATE_CLOSE: (RawRequestKind.CLOSE, RawRequestKind.THROW)}[rule]
    if raw.kind not in permitted:
        issue("protocol_continuation_trigger", path, "known raw request contradicts the selected delegation rule")
    if rule is CR.DELEGATE_NEXT and raw.kind is RawRequestKind.SEND:
        known = _declared_none(ctx, raw)
        if known is False:
            issue("protocol_continuation_trigger", path, "NEXT cannot discard a known non-None SEND operand")
        elif known is None:
            missing("delegate_next_send_none_unproved", path)
    if rule is CR.DELEGATE_CLOSE and raw.kind is RawRequestKind.THROW:
        missing("generator_exit_category_unproved", path)
    if rule in (CR.DELEGATE_SEND, CR.DELEGATE_THROW):
        if len(case.arguments) != len(raw.operands):
            issue("protocol_continuation_arguments", path, "delegate call omits or adds original raw operands")
        for ordinal, argument in enumerate(case.arguments):
            if type(argument) is not RawOperandSource or argument.raw != trigger.raw or argument.ordinal != ordinal:
                issue("protocol_continuation_arguments", path, "raw operands must retain the same trigger and exact order")


def _check_adapter(ctx, row, path, check, issue, missing, role):
    contract = row.contract
    if type(contract.input) is ContractResult:
        producer = _source_row(ctx, contract.input)
        selected = _selected_kind(ctx, contract.input)
        if producer is not None and type(producer.contract) is ProtocolCall:
            expected = (ExitKind.NORMAL if contract.rule in (
                AR.DELEGATE_ITEM_TO_PARENT_YIELD, AR.DELEGATE_ONLY_HOST_ITEM) else ExitKind.RAISE)
            if selected is not expected:
                issue("protocol_continuation_outcome", path, "item and exhaustion/failure consume different actual completions")
    if contract.rule in (AR.DELEGATE_ITEM_TO_PARENT_YIELD, AR.DELEGATE_ONLY_HOST_ITEM):
        role(contract.input, "reference", path)
    else:
        role(contract.input, "packet", path)
        if contract.rule in (AR.AWAIT_STOPITER_TO_EXPRESSION, AR.DELEGATE_STOPITER_TO_PARENT_VALUE):
            missing("stop_iteration_category_unproved", path)
    output = contract.output
    if type(output) is HostTerminal:
        terminal = ctx.operations[output.operation]
        expected = (TerminatorKind.RAISE if contract.rule is AR.DELEGATE_ONLY_HOST_EXCEPTION
                    else TerminatorKind.RETURN)
        if terminal.terminator.kind is not expected:
            issue("protocol_continuation_outcome", path, "fixed host adapter consumes a different terminal kind")
        # A terminal row has no own result: its input is an exact copy. Native
        # conversion helpers retain their own result producer in other rows.
        if output.operation == row.operation:
            payload = ctx.terminal_uses(output)
            for actual in payload:
                check(ctx.bind(contract.input, actual)["match"], path,
                      "host output is not the selected current whole payload", "protocol_copy")
    else:
        selected = _selected_kind(ctx, output)
        role(output, "packet" if selected is ExitKind.RAISE else "reference", path)
        if type(output) is StaticProtocolGap:
            missing("continuation_adapter_output_unresolved", path)


def continuation_errors(ctx):
    return continuation_connections(ctx)["issues"]


__all__ = ["continuation_connections", "continuation_errors"]
