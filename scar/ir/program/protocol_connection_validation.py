"""Independent input and consumer inventories over canonical program ports.

Missing attachments remain obligations. Supplied targets or successful input
subsets cannot choose the denominator or grant transformation permission.
"""
from .model import BlockArgument, StateVersionValue, TerminatorKind
from .structured import ControlEdgeReference
from .protocol_connections import (
    InitialAdvance, InjectedPacketTrigger, ProtocolOperationRef, RawRequestTrigger,
)
from .protocols import (AdmissionPredicate, HostTerminal, NativeExit, OutcomeAdapter, OwnedUse,
                        ProtocolCall, RequestProcessing, StaticProtocolGap)
from .resumption import SuspendTerminator


def _site(row):
    return ProtocolOperationRef(row.scope, row.clause, row.operation, row.slot)


def _joint_routes(ctx, reports):
    """Join whole tuples on caller and CFG choices, retaining route support."""
    joined = [(None, {}, ())]
    for report in reports:
        next_rows = []
        for route in report["routes"]:
            if route.get("match") is not True:
                continue
            context = route.get("context")
            choices = dict(route.get("choices", {}))
            for old_context, old_choices, support in joined:
                if not ctx.spend("connection_tuple_joins"):
                    return (), ("protocol_connection_budget_exhausted",)
                if old_context is not None and context is not None and old_context != context:
                    continue
                if any(key in old_choices and old_choices[key] != value for key, value in choices.items()):
                    continue
                next_rows.append((old_context if context is None else context,
                                  {**old_choices, **choices}, (*support, route)))
        joined = next_rows
        if not joined:
            return (), ("whole_input_tuple_context_unresolved",)
    return tuple({"context": context, "choices": choices, "support": support}
                 for context, choices, support in joined), ()


def _guard_inventory(ctx, row, attachment):
    cases, issues, gaps = attachment.cases, [], []
    if len(cases) == 1 and cases[0].guard is None:
        return (), (), ()
    if any(case.guard is None for case in cases):
        return (("protocol_input_guard", str(row.operation),
                 "multiple cases require exact nonempty incoming guards"),), (), ()
    guards = tuple(case.guard for case in cases)
    targets = []
    for guard in guards:
        operation = ctx.operations.get(guard.operation)
        if (operation is None or operation.terminator is None or
                guard.successor_index >= len(operation.terminator.successors) or
                ctx.region_of[operation.id] != ctx.region_of[row.operation]):
            issues.append(("protocol_input_guard", str(row.operation),
                           "guard must select an original incoming edge in this region"))
        else:
            targets.append(operation.terminator.successors[guard.successor_index].block)
    if issues:
        return tuple(issues), (), ()
    if len(set(targets)) != 1 or len(set(guards)) != len(guards):
        return (("protocol_input_guard", str(row.operation),
                 "case guards must be unique incoming edges of the same canonical merge"),), (), ()
    merge = targets[0]
    _, _, incoming, reached, _ = ctx._edges(ctx.region_of[row.operation])
    expected = {(edge[0], edge[1]) for parent, edge in incoming[merge] if parent in reached}
    declared = {(guard.operation, guard.successor_index) for guard in guards}
    if declared - expected:
        issues.append(("protocol_input_guard", str(row.operation),
                       "case includes a nonapplicable merge predecessor"))
    missing = tuple(sorted(expected - declared, key=lambda item: (item[0].wire, item[1])))
    if missing:
        gaps.append({"code": "protocol_input_case_missing", "merge": merge, "incoming": missing})
    # A shared early branch is insufficient. Some actual role must be a copy
    # of a canonical formal from this merge, possibly through later JUMPs.
    from .model import BlockArgument
    actuals = tuple(OwnedUse(row.operation, use) for use in
                    (row.contract.receiver_use, *row.contract.argument_uses))
    carries, unknown = False, False
    for index in range(len(ctx.blocks[merge].arguments)):
        for actual in actuals:
            if isinstance(ctx.values[ctx.owned_use(actual.operation, actual.use).value], StateVersionValue):
                continue
            result = ctx.bind(BlockArgument(merge, index), actual)
            carries |= result["match"] is True
            unknown |= result["match"] is None
    if not carries:
        if unknown:
            gaps.append("protocol_input_merge_support_unresolved")
        else:
            issues.append(("protocol_input_guard", str(row.operation),
                           "guard merge does not carry any actual input role"))
    return tuple(issues), tuple(gaps), missing


def _call_inputs(ctx, row, attachment):
    site, issues, gaps, cases = _site(row), [], [], []
    if attachment is None:
        return {"site": site, "status": "MISSING", "cases": (),
                "gaps": ("protocol_call_inputs_missing",), "issues": ()}
    guard_issues, guard_gaps, missing = _guard_inventory(ctx, row, attachment)
    issues.extend(guard_issues)
    gaps.extend(guard_gaps)
    for case in attachment.cases:
        if not ctx.spend("connection_input_cases"):
            gaps.append("protocol_connection_budget_exhausted")
            break
        if len(case.arguments) != len(row.contract.argument_uses):
            issues.append(("protocol_input_arity", str(row.operation),
                           "expected argument tuple must match the actual ordered call arguments"))
            continue
        try:
            reports = tuple(ctx.bind(expected, OwnedUse(row.operation, actual),
                                    guard=case.guard, path="protocol_call_inputs")
                            for expected, actual in zip((case.receiver, *case.arguments),
                                (row.contract.receiver_use, *row.contract.argument_uses)))
            trigger = case.trigger
            if type(trigger) is RawRequestTrigger:
                ctx.owned_use(trigger.raw.operation, trigger.raw.use)
                reports += (ctx.available(trigger.raw, row.operation, guard=case.guard),)
            elif type(trigger) is InjectedPacketTrigger:
                reports += (ctx.available(trigger.packet, row.operation, guard=case.guard),)
            elif type(trigger) is InitialAdvance:
                reports += (ctx.available(trigger.iterator, row.operation, guard=case.guard),)
            elif type(trigger) is StaticProtocolGap:
                gaps.append(trigger)
            for report in reports:
                gaps.extend(report["gaps"] if report["match"] is None else ())
                if report["match"] is False:
                    issues.append(("protocol_input_source", str(row.operation),
                                   "actual input or trigger does not come from its independent expected source"))
            correlation = ctx.correlate(*reports)
            gaps.extend(correlation["gaps"])
            if correlation["match"] is False and all(report["match"] is True for report in reports):
                issues.append(("protocol_input_context", str(row.operation),
                               "input roles belong to incompatible caller/CFG contexts"))
            cases.append({"case": case, "inputs": reports, "joint": correlation["routes"],
                          "correlation": correlation})
        except (KeyError, TypeError, ValueError) as exc:
            issues.append(("protocol_input_reference", str(row.operation), str(exc)))
    return {"site": site, "status": "REJECTED" if issues else "PARTIAL" if gaps else "DECLARED",
            "cases": tuple(cases), "missing_incoming": missing,
            "issues": tuple(issues), "gaps": tuple(gaps)}


def _consumer_role(operation, use):
    """Keep actual consumers, excluding mere original edge forwarding Uses."""
    term = operation.terminator
    if term is None:
        return operation.callee is None or use in operation.call_arguments
    if term.kind is TerminatorKind.INVOKE:
        return use in operation.invoke_arguments
    if type(term) is SuspendTerminator:
        return use == term.exported or use in term.handoff or any(use == slot.use for slot in term.saved)
    if term.kind in (TerminatorKind.RETURN, TerminatorKind.RAISE):
        return use in term.values
    if term.kind is TerminatorKind.BRANCH:
        return use == term.condition
    # Special structured terminators have their own canonical payload Uses;
    # retain these rather than silently classifying them as dead forwarding.
    return term.kind is not TerminatorKind.JUMP


def consumer_ledger(ctx, row=None, *, source=None, site=None, source_operation=None):
    """Derive known exact targets before inspecting any targets attachment."""
    if row is not None:
        site, source_operation = _site(row), row.operation
    targets, support, gaps = [], [], []
    try:
        if row is not None:
            source = row.contract.output if type(row.contract) is OutcomeAdapter else ctx.row_result(row)
        if type(source) in (HostTerminal, NativeExit):
            return {"site": site, "source": source, "targets": (source,),
                    "support": (), "direct_terminal": True, "gaps": (),
                    "known_inventory_complete": True, "source_inventory_complete": False}
        port = ctx.port(source)
    except (KeyError, TypeError, ValueError) as exc:
        return {"site": site, "source": None, "targets": (), "support": (),
                "gaps": ({"code": "consumer_source_unresolved", "message": str(exc)},),
                "known_inventory_complete": False, "source_inventory_complete": False}
    if port is None or port.gap is not None:
        return {"site": site, "source": source, "targets": (), "support": (),
                "gaps": ("consumer_source_unresolved",), "known_inventory_complete": False,
                "source_inventory_complete": False}
    for operation in ctx.graph.operations:
        for use in operation.uses:
            if not ctx.spend("connection_consumer_inventory"):
                gaps.append("protocol_connection_budget_exhausted")
                break
            if (isinstance(ctx.values[use.value], StateVersionValue)
                    or not _consumer_role(operation, use.id)):
                continue
            actual = OwnedUse(operation.id, use.id)
            report = ctx.bind(source, actual)
            conditional = []
            if report["match"] is not True and type(ctx.values[use.value].origin) is BlockArgument:
                original = ctx.origins(actual)
                guards = []
                for recipe in original["recipes"]:
                    if recipe["leaf"].id not in port.values:
                        continue
                    for step in recipe["path"]:
                        if step.get("kind") == "CFG_COPY" and ctx.region_of[step["operation"].id] == ctx.region_of[operation.id]:
                            guard = ControlEdgeReference(step["operation"].id, step["successor_index"])
                            if guard not in guards:
                                guards.append(guard)
                for guard in guards:
                    binding = ctx.bind(source, actual, guard=guard)
                    conditional.append({"guard": guard, "binding": binding})
            copied = report["match"] is True or any(item["binding"]["match"] is True for item in conditional)
            possible_route = any(route.get("match") is True for route in report["routes"])
            possible = True if copied or possible_route else ctx.may_forwards(source, actual)
            if copied or possible is True:
                terminal = operation.terminator
                target = (HostTerminal(operation.id) if terminal is not None and terminal.kind
                          in (TerminatorKind.RETURN, TerminatorKind.RAISE) else actual)
                if target not in targets:
                    targets.append(target)
                support.append({"target": target, "use": actual, "binding": report,
                                "conditional": tuple(conditional), "possible_copy": possible})
                if not copied:
                    gaps.append({"code": "consumer_condition_correlation_unresolved", "target": target})
                if not operation.effects_complete:
                    gaps.append({"code": "consumer_escape_or_effects_unresolved", "target": target})
            elif report["match"] is None and ctx.region_of[operation.id] != ctx.region_of[source_operation]:
                # A possible cross-region route must not be silently erased.
                gaps.append({"code": "consumer_cross_region_inventory_unresolved", "use": actual})
        if ctx.budget.truncated:
            break
    if not targets:
        gaps.append("consumer_absence_is_not_dead_work")
    return {"site": site, "source": source, "targets": tuple(targets), "support": tuple(support),
            "gaps": tuple(gaps), "direct_terminal": False,
            "known_inventory_complete": not ctx.budget.truncated,
            "source_inventory_complete": False}


def _result_consumers(ctx, row, attachment):
    ledger = consumer_ledger(ctx, row)
    known = ledger["targets"]
    supplied = () if attachment is None else attachment.targets
    gaps, issues = list(ledger["gaps"]), []
    missing = tuple(target for target in known if target not in supplied)
    if ledger.get("direct_terminal"):
        missing = ()
    if attachment is None and not ledger.get("direct_terminal"):
        gaps.append("protocol_result_consumers_missing")
    for target in supplied:
        if type(target) is StaticProtocolGap:
            gaps.append(target)
        elif target not in known:
            # A legal FK without a proven connection cannot fill this ledger.
            try:
                if type(target) is OwnedUse:
                    report = ctx.bind(ledger["source"], target)
                    if report["match"] is False:
                        issues.append(("protocol_result_consumer", str(row.operation),
                                       "listed target does not consume this exact result"))
                    else:
                        gaps.append({"code": "consumer_target_role_unresolved", "target": target})
                else:
                    ctx.port(target)
                    matches = (tuple(ctx.bind(ledger["source"], actual)["match"]
                               for actual in ctx.terminal_uses(target))
                               if type(target) is HostTerminal else ())
                    if matches and all(match is False for match in matches):
                        issues.append(("protocol_result_consumer", str(row.operation),
                                       "listed host target does not consume this exact result"))
                    else:
                        gaps.append({"code": "consumer_target_route_unresolved", "target": target})
            except (KeyError, TypeError, ValueError) as exc:
                issues.append(("protocol_result_reference", str(row.operation), str(exc)))
    if missing:
        gaps.append({"code": "protocol_result_consumer_missing", "targets": missing})
    return {**ledger, "declared": supplied, "missing": missing, "issues": tuple(issues),
            "gaps": tuple(gaps), "status": "REJECTED" if issues else "PARTIAL" if gaps else "DECLARED"}


def common_connections(ctx):
    if "common" in ctx._connection_reports:
        return ctx._connection_reports["common"]
    from .protocol_await_records import (AwaitAcquisition, AwaitIteratorQualification,
                                         CoroutineAwaitWrapper)
    result_contracts = (AdmissionPredicate, RequestProcessing, ProtocolCall, OutcomeAdapter,
                        AwaitAcquisition, AwaitIteratorQualification, CoroutineAwaitWrapper)
    issues, gaps, inputs, consumers = [], [], [], []
    for site, attachment in (*ctx.call_inputs.items(), *ctx.result_consumers.items()):
        try:
            row = ctx.row(site)
            if site in ctx.call_inputs and type(row.contract) is not ProtocolCall:
                raise ValueError("call input attachment requires an existing ProtocolCall row")
            if site in ctx.result_consumers and type(row.contract) not in result_contracts:
                raise ValueError("result consumer attachment requires a row with its own exact result/output")
        except (KeyError, TypeError, ValueError) as exc:
            issues.append(("protocol_connection_site", str(site), str(exc)))
    for row in ctx.graph.protocol_operations:
        if type(row.contract) is ProtocolCall:
            report = _call_inputs(ctx, row, ctx.call_inputs.get(_site(row)))
            inputs.append(report)
            issues.extend(report["issues"])
            gaps.extend(report["gaps"])
        if type(row.contract) in result_contracts:
            report = _result_consumers(ctx, row, ctx.result_consumers.get(_site(row)))
            consumers.append(report)
            issues.extend(report["issues"])
            gaps.extend(report["gaps"])
    result = {"issues": tuple(issues), "gaps": tuple(gaps), "inputs": tuple(inputs),
              "consumers": tuple(consumers), "obligations": (*inputs, *consumers),
              "cursor": {"phase": "connections"} if ctx.budget.truncated else None,
              "source_runtime_verified": False, "transformation_authorized": False}
    ctx._connection_reports["common"] = result
    return result


def connection_reports(ctx):
    """All fixed families share one immutable index, flow and accounting."""
    from .protocol_async import async_connections, request_state_errors
    from .protocol_continuations import continuation_connections
    from .protocol_await import await_connections
    from .protocol_connections import RequestStateCondition
    from .protocols import AdmissionPredicate
    reports = {"common": common_connections(ctx),
               "continuations": continuation_connections(ctx),
               "async": async_connections(ctx),
               "await": await_connections(ctx)}
    if ctx.graph.exception_matches:
        from .exception_match_query import exception_match_reports
        reports['exception_matches'] = exception_match_reports(ctx)
    predicate_issues = []
    for row in ctx.graph.protocol_operations:
        if type(row.contract) is AdmissionPredicate and type(row.contract.subject) is RequestStateCondition:
            predicate_issues.extend(request_state_errors(ctx, row))
    return {"families": reports,
            "issues": (*predicate_issues, *(issue for report in reports.values() for issue in report["issues"])),
            "gaps": tuple(gap for report in reports.values() for gap in report["gaps"]),
            "cursor": tuple(report["cursor"] for report in reports.values() if report["cursor"]),
            "source_runtime_verified": False, "transformation_authorized": False}


__all__ = ["common_connections", "consumer_ledger", "connection_reports"]
