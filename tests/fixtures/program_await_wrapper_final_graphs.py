"""One native coroutine source, persistent body, and real final child chain.

W is constructed before the first advance. Every advance enters its own
wrapper region, reads the held B, and calls its exact driver. The supplied
native contracts remain conditional; W-to-B is never an ordinary copy.
"""
from dataclasses import replace

from scar.ir.program.control import ControlScope, ControlScopeKind
from scar.ir.program.drivers import RawRequestDefinition, RawRequestKind
from scar.ir.program.ids import BlockID, ControlScopeID, OperationID, ProtocolScopeID
from scar.ir.program.model import (
    AccessMode, Behavior, CompletionResult, CompletionSignature,
    CompletionSuccessor, ExitKind, InvokeLiteralResult, OperationResult,
    StateAccess, StateVersionValue, Terminator, TerminatorKind, ValueKind,
    ValueType,
)
from scar.ir.program.protocol_await_records import (
    AwaitBodyLink, CoroutineAwaitWrapper, WrapperHeldBody,
)
from scar.ir.program.protocol_connections import (
    InitialAdvance, ProtocolCallInputCase, ProtocolCallInputs,
    ProtocolOperationRef, ProtocolResultConsumers, RawOperandSource,
    RawRequestTrigger,
)
from scar.ir.program.protocols import (
    ContractResult, HostTerminal, OperationSiteSubject, OutcomeAdapter,
    OutcomeAdapterRule, OwnedUse, ProtocolCall, ProtocolCallRule, ProtocolClause,
    ProtocolOperation, ProtocolProfile, ProtocolScope,
)
from scar.ir.program.resumption import ResumableKind, SuspendTerminator, SuspensionFlavor
from scar.ir.program.state_addresses import ExistingAccess, InvokeStateOperand
from scar.ir.program.structured import ControlEdgeReference
from tests.fixtures.program_async_pipeline_graphs import _selected_path
from tests.fixtures.program_await_final_region_graphs import await_final_region_program
from tests.fixtures.program_control_graphs import _source
from tests.fixtures.program_driver_graphs import PACKET, RAW, REFERENCE, _Builder, _use
from tests.fixtures.program_protocol_graphs import _source_gap


def _site(row):
    return ProtocolOperationRef(row.scope, row.clause, row.operation, row.slot)


def await_wrapper_final_program(*, zero_cut=True, depth=1, attach_link=True,
                                final_adapters=True, stale_child_state=False):
    """Return one graph with native W/B and the original E/(G)/F interface.

    Both real Create sites remain independent. The constructor's original B
    operand fixes expected B before any drive exists. Zero cut terminates on
    the first start; two cut resumes from each immediately preceding Suspend.
    """
    if any(type(flag) is not bool for flag in
           (zero_cut, attach_link, final_adapters, stale_child_state)):
        raise TypeError("wrapper-final switches require exact bools")
    graph, old = await_final_region_program(
        zero_cut=zero_cut, depth=depth, final_adapters=final_adapters)
    if stale_child_state:
        leaf = old["stage_records"][-1]
        changed = {terminal.id: replace(terminal, uses=tuple(
            replace(use, value=leaf["formals"][1].id)
            if use.id == terminal.terminator.values[1] else use
            for use in terminal.uses)) for terminal in leaf["terminals"].values()}
        graph = replace(graph, operations=tuple(changed.get(operation.id, operation)
                                               for operation in graph.operations))
        leaf = {**leaf, "terminals": {kind: changed[terminal.id]
            for kind, terminal in leaf["terminals"].items()}}
        old = {**old, "stage_records": (*old["stage_records"][:-1], leaf)}
    old_values = {value.id: value for value in graph.values}
    old_operations = {operation.id: operation for operation in graph.operations}
    domains = tuple(location.id for location in graph.locations)
    states = tuple(ValueType(ValueKind.STATE, location=location) for location in domains)
    body_definition, = graph.resumable_bodies
    world_index = next(number for number, location in enumerate(domains)
                       if location != body_definition.context_location)
    b = _Builder(old["caller"].id.value, domains)
    entry_name = "await.resume.entry"
    capture_count = len(old["capture_formals"])
    entry = b.formals(entry_name, (*(REFERENCE for _ in range(capture_count + 1)), *states))
    captures, sent = entry[:capture_count], entry[capture_count]
    current_name, current_args, current_states = entry_name, entry, entry[-len(states):]
    create_operations = []
    main_body = None
    for ordinal, template in enumerate(old["create_operations"]):
        name = template.id.value
        normal_name, failure_name = name + ".normal", name + ".failure"
        normal = b.formals(normal_name,
            (*((REFERENCE,) if ordinal else ()), REFERENCE, *states))
        failure = b.formals(failure_name, (PACKET, *states))
        original_actuals = {use.id: use for use in template.uses}
        actuals = tuple(replace(original_actuals[identity], value=value)
            for identity, value in zip(template.invoke_arguments,
                                       (*captures, *current_states), strict=True))
        forwards = () if ordinal == 0 else (_use(name + ".forward.body", main_body),)
        creation = replace(template, uses=(*actuals, *forwards),
            terminator=Terminator(TerminatorKind.INVOKE, (
                CompletionSuccessor(ExitKind.NORMAL, BlockID(normal_name),
                    (*(use.id for use in forwards),
                     *(CompletionResult(slot) for slot in range(1 + len(states))))),
                CompletionSuccessor(ExitKind.RAISE, BlockID(failure_name),
                    tuple(CompletionResult(slot) for slot in range(1 + len(states)))),
            )))
        b.operations.append(creation)
        b.block(current_name, current_args, (creation,))
        b.block(failure_name, failure,
                (b.terminal(failure_name + ".exit", failure, fail=True),))
        create_operations.append(creation)
        current_name, current_args = normal_name, normal
        main_body = normal[0]
        current_states = normal[2 if ordinal else 1:]
    decoy = current_args[1]

    scope = old["acquisition_scope"]
    constructor_name = old["get"].id.value
    acquired_name, construction_failure_name = "await.resume.acquired", "await.resume.acquire.failure"
    acquired = b.formals(acquired_name, (REFERENCE, REFERENCE, REFERENCE, *states))
    construction_failure = b.formals(construction_failure_name, (PACKET, *states))
    construction_inputs = (_use(constructor_name + ".body", main_body),
        *(_use(constructor_name + f".state.{slot}", state, state=True)
          for slot, state in enumerate(current_states)))
    retained = tuple(_use(constructor_name + f".forward.{slot}", value)
                     for slot, value in enumerate((main_body, decoy)))
    constructor = b.add(constructor_name, (*construction_inputs, *retained),
        effects_complete=False,
        invoke_arguments=tuple(use.id for use in construction_inputs),
        completions=(CompletionSignature(ExitKind.NORMAL, (REFERENCE, *states)),
                     CompletionSignature(ExitKind.RAISE, (PACKET, *states))),
        terminator=Terminator(TerminatorKind.INVOKE, (
            CompletionSuccessor(ExitKind.NORMAL, BlockID(acquired_name),
                (CompletionResult(0), *(use.id for use in retained),
                 *(CompletionResult(slot + 1) for slot in range(len(states))))),
            CompletionSuccessor(ExitKind.RAISE, BlockID(construction_failure_name),
                tuple(CompletionResult(slot) for slot in range(1 + len(states)))),
        )))
    constructor_failure = b.terminal(construction_failure_name + ".exit",
                                     construction_failure, fail=True)
    b.block(current_name, current_args, (constructor,))
    b.block(construction_failure_name, construction_failure, (constructor_failure,))
    expected_body = next(value.origin for value in b.values if value.id == main_body)
    constructor_rows = tuple(ProtocolOperation(scope, ProtocolClause.WRAPPER_CONSTRUCTION,
        constructor.id, slot, CoroutineAwaitWrapper(construction_inputs[0].id,
            expected_body, InvokeLiteralResult(ControlEdgeReference(constructor.id, slot),
                CompletionResult(0)), tuple(InvokeStateOperand(constructor.id, use.id)
                    for use in construction_inputs[1:])), _source_gap()) for slot in range(2))
    source = _site(constructor_rows[0])
    iterator_source = ContractResult(source.scope, source.clause, source.operation,
                                     source.slot, constructor_rows[0].contract.result)
    current_name, current_args = acquired_name, acquired
    wrapper, main_body, decoy = acquired[:3]
    current_states = acquired[3:]
    calls, driver_details, wrapper_records, call_rows, inputs, links = [], [], [], [], [], []
    raw_definitions, scopes, receipts, handoffs = [], [], [], []

    for ordinal, item in enumerate(old["drivers"]):
        name = f"await.wrapper.advance.{ordinal}"
        w = _Builder(name, domains)
        roles = (REFERENCE, RAW, *((REFERENCE,) if ordinal else ()))
        w_entry = w.formals(name + ".entry", (*roles, *states))
        read_id = OperationID(name + ".held.read")
        held = w.value(name + ".held.body", OperationResult(read_id, 0), REFERENCE)
        read_inputs = (_use(name + ".held.wrapper", w_entry[0]),
                       _use(name + ".held.world", w_entry[len(roles) + world_index], state=True))
        read = w.add(read_id.value, read_inputs, results=(held,), effects_complete=True,
            accesses=(StateAccess(domains[world_index], read_inputs[1].id, AccessMode.READ),))
        read = replace(read, behaviors=(Behavior.READ,))
        w.operations[-1] = read
        inner_inputs = (_use(name + ".driver.body", held),
            _use(name + ".driver.raw", w_entry[1], protocol=True),
            *(() if ordinal == 0 else (_use(name + ".driver.sent", w_entry[2]),)),
            *(_use(name + f".driver.state.{slot}", state, state=True)
              for slot, state in enumerate(w_entry[len(roles):])))
        inner_edges, wrapper_landings, wrapper_terminals = [], {}, {}
        for exit_ in item["driver_region"].exits:
            label = "normal" if exit_.kind is ExitKind.NORMAL else "failure"
            landing_name = name + "." + label
            landing = w.formals(landing_name, exit_.types)
            terminal = w.terminal(landing_name + ".exit", landing,
                                  fail=exit_.kind is ExitKind.RAISE)
            inner_edges.append(CompletionSuccessor(exit_.kind, BlockID(landing_name),
                tuple(CompletionResult(slot) for slot in range(len(landing)))))
            w.block(landing_name, landing, (terminal,))
            wrapper_landings[exit_.kind] = landing
            wrapper_terminals[exit_.kind] = terminal
        inner_call = w.add(name + ".driver.call", inner_inputs, effects_complete=True,
            callee=item["driver_region"].id,
            invoke_arguments=tuple(use.id for use in inner_inputs),
            completions=tuple(CompletionSignature(exit_.kind, exit_.types)
                              for exit_ in item["driver_region"].exits),
            terminator=Terminator(TerminatorKind.INVOKE, tuple(inner_edges)))
        w.block(name + ".entry", w_entry, (read, inner_call))
        wrapper_region = w.finish(name + ".entry", parent=b.region)
        wrapper_region = replace(wrapper_region, exits=tuple(exit_ for exit_ in wrapper_region.exits
            if exit_.kind in wrapper_terminals))

        call_name = item["caller_call"].id.value
        raw_operands = () if ordinal == 0 else (_use(call_name + ".raw.operand", sent),)
        raw = b.value(call_name + ".raw.value", OperationResult(OperationID(call_name + ".raw"), 0), RAW)
        pack = b.add(call_name + ".raw", raw_operands, results=(raw,), effects_complete=True)
        raw_definitions.append(RawRequestDefinition(raw,
            RawRequestKind.NEXT if ordinal == 0 else RawRequestKind.SEND,
            tuple(use.id for use in raw_operands)))
        actual_values = (wrapper, raw, *((sent,) if ordinal else ()), *current_states)
        actuals = tuple(_use(call_name + f".input.{slot}", value,
            protocol=slot == 1, state=slot >= len(roles))
            for slot, value in enumerate(actual_values))
        edges, forwards, normal_data = [], [], None
        selected_kind = ExitKind.RAISE if zero_cut or ordinal == 2 else ExitKind.NORMAL
        selected_landing = None
        for exit_ in wrapper_region.exits:
            landing_name = call_name + "." + exit_.kind.value.lower()
            copied = tuple(_use(call_name + f".forward.{slot}", value)
                           for slot, value in enumerate((main_body, decoy, wrapper))) if (
                               exit_.kind is ExitKind.NORMAL) else ()
            landing = b.formals(landing_name,
                (*(REFERENCE for _ in copied), *exit_.types))
            forwards.extend(copied)
            edges.append(CompletionSuccessor(exit_.kind, BlockID(landing_name),
                (*(use.id for use in copied),
                 *(CompletionResult(slot) for slot in range(len(exit_.types))))))
            if exit_.kind is ExitKind.NORMAL:
                normal_data = landing_name, landing
            elif exit_.kind is not selected_kind:
                b.block(landing_name, landing,
                    (b.terminal(landing_name + ".exit", landing, fail=True),))
            if exit_.kind is selected_kind:
                selected_landing = landing_name, landing
        call = b.add(call_name, (*actuals, *forwards), effects_complete=True,
            callee=wrapper_region.id,
            invoke_arguments=tuple(use.id for use in actuals),
            completions=tuple(CompletionSignature(exit_.kind, exit_.types)
                              for exit_ in wrapper_region.exits),
            terminator=Terminator(TerminatorKind.INVOKE, tuple(edges)))
        b.block(current_name, current_args,
                ((*handoffs[-1:], pack, call) if ordinal else (pack, call)))
        call_scope = ProtocolScopeID(call_name + ".scope")
        scopes.append(ProtocolScope(call_scope, ProtocolProfile.DELEGATION_SITE_V1,
            OperationSiteSubject(b.region, call.id), _source_gap()))
        projection = WrapperHeldBody(source, expected_body,
            OwnedUse(constructor.id, construction_inputs[0].id),
            OwnedUse(read.id, read_inputs[0].id), OperationResult(read.id, 0),
            (ExistingAccess(read.id, 0),))
        for slot in range(len(edges)):
            row = ProtocolOperation(call_scope, ProtocolClause.DELEGATE_ADVANCE, call.id, slot,
                ProtocolCall(actuals[0].id, () if ordinal == 0 else (actuals[2].id,),
                    InvokeLiteralResult(ControlEdgeReference(call.id, slot), CompletionResult(0)),
                    tuple(InvokeStateOperand(call.id, use.id) for use in actuals[len(roles):]),
                    ProtocolCallRule.DELEGATE_NEXT if ordinal == 0 else ProtocolCallRule.DELEGATE_SEND),
                _source_gap())
            call_rows.append(row)
            raw_use = OwnedUse(call.id, actuals[1].id)
            inputs.append(ProtocolCallInputs(_site(row), (ProtocolCallInputCase(None,
                iterator_source, () if ordinal == 0 else (RawOperandSource(raw_use, 0),),
                InitialAdvance(iterator_source) if ordinal == 0 else RawRequestTrigger(raw_use)),)))
            links.append(AwaitBodyLink(source, _site(row), item["drive"].operation,
                                      projection, None))
        selected_edge = next(slot for slot, edge in enumerate(edges) if edge.kind is selected_kind)
        inner_selected = next(slot for slot, edge in enumerate(inner_edges) if edge.kind is selected_kind)
        record = {"region": wrapper_region, "entry": w_entry, "read": read,
            "read_body": held, "inner_call": inner_call, "terminals": wrapper_terminals,
            "landing_values": wrapper_landings, "projection": projection,
            "path": ((wrapper_region.entry, inner_selected),
                     (inner_edges[inner_selected].block, None)),
            "operations": tuple(w.operations), "values": tuple(w.values), "ordinal": ordinal}
        wrapper_records.append(record)
        calls.append(call)
        driver_details.append({**item, "caller_call": call, "wrapper": record,
            "selected_call_edge": selected_edge, "selected_landing": BlockID(selected_landing[0]),
            "direct": False})
        if normal_data is not None:
            current_name, current_args = normal_data
            main_body, decoy, wrapper = current_args[:3]
            payload, *current_states = current_args[3:]
            handoff_inputs = (_use(call_name + ".handoff.value", payload),
                             _use(call_name + ".handoff.world", current_states[world_index], state=True))
            handoff = b.add(call_name + ".handoff", handoff_inputs, effects_complete=True,
                accesses=(StateAccess(domains[world_index], handoff_inputs[1].id, AccessMode.READ),))
            handoff = replace(handoff, behaviors=(Behavior.CONTROL, Behavior.READ))
            b.operations[-1] = handoff
            handoffs.append(handoff)

    # E and its two caller exits retain their exact original canonical ports.
    landing_name, incoming = selected_landing
    b.block(landing_name, incoming, (old["extract"],))
    b.operations.append(old["extract"])
    for block_name, terminal in (("await.resume.final", old["final"]),
            ("await.resume.extract.failure", old_operations[OperationID("await.resume.extract.failure.raise")])):
        old_block = next(block for block in old["caller"].blocks if block.id == BlockID(block_name))
        b.values.extend(old_values[identity] for identity in old_block.arguments)
        b.operations.append(terminal)
        b.block(block_name, old_block.arguments, (terminal,))
    caller = b.finish(entry_name)
    old_caller_operations = {identity for block in old["caller"].blocks for identity in block.operations}
    operations = tuple(replace(operation,
        terminator=replace(operation.terminator, flavor=SuspensionFlavor.AWAIT))
        if type(operation.terminator) is SuspendTerminator else operation
        for operation in graph.operations if operation.id not in old_caller_operations)

    def native_row(row):
        if type(row.contract) is OutcomeAdapter and row.contract.rule is (
                OutcomeAdapterRule.GENERATOR_RETURN_TO_STOP_ITERATION):
            return replace(row, clause=ProtocolClause.AWAIT_COMPLETION_ADAPTER,
                contract=replace(row.contract,
                    rule=OutcomeAdapterRule.COROUTINE_RETURN_TO_STOP_ITERATION))
        return row

    old_rows = tuple(row for row in graph.protocol_operations
        if row.scope != scope and row.operation not in {call.id for call in old["calls"]})
    conversion_rows = tuple(native_row(row) for row in old["conversion_rows"])
    row_sites = {_site(row): _site(native_row(row)) for row in old_rows}
    receipts.extend(replace(row, site=row_sites.get(row.site, row.site))
        for row in graph.protocol_result_consumers
        if row.site.scope != scope and row.site.operation not in {call.id for call in old["calls"]})
    receipts.extend((ProtocolResultConsumers(source,
        tuple(OwnedUse(call.id, call.uses[0].id) for call in calls)),
        ProtocolResultConsumers(_site(constructor_rows[1]), (HostTerminal(constructor_failure.id),))))
    receipts.extend(row for row in graph.protocol_result_consumers if row.site in old["final_sites"])
    final_advance = next(row for row in call_rows if row.operation == calls[-1].id
                         and row.slot == driver_details[-1]["selected_call_edge"])
    receipts.append(ProtocolResultConsumers(_site(final_advance), (old["extract_input"],)))
    wrapper_by_driver = {item["driver_region"].id: item["wrapper"]["region"].id
                         for item in driver_details}
    regions = tuple(replace(region, parent=wrapper_by_driver[region.id])
        if region.id in wrapper_by_driver else region
        for region in graph.regions if region.id != caller.id)
    graph = replace(graph, root=caller.id,
        regions=(caller, *regions, *(row["region"] for row in wrapper_records)),
        operations=(*operations, *b.operations,
                    *(operation for row in wrapper_records for operation in row["operations"])),
        values=(*(value for value in graph.values if value.region != caller.id), *b.values,
                *(value for row in wrapper_records for value in row["values"])),
        resumable_bodies=(replace(body_definition, kind=ResumableKind.COROUTINE),),
        resumable_creates=old["creations"], raw_driver_requests=tuple(raw_definitions),
        control_scopes=(*(row for row in graph.control_scopes if row.region != caller.id),
            ControlScope(ControlScopeID("await.wrapper.final.caller.function"), caller.id,
                None, ControlScopeKind.FUNCTION, _source("native wrapper final caller"),
                tuple(block.id for block in caller.blocks)),
            *(ControlScope(ControlScopeID(row["region"].id.value + ".function"),
                row["region"].id, None, ControlScopeKind.FUNCTION, _source("held body wrapper"),
                tuple(block.id for block in row["region"].blocks)) for row in wrapper_records)),
        protocol_scopes=(*(replace(row, profile=ProtocolProfile.COROUTINE_BODY_V1)
            if row.profile is ProtocolProfile.GENERATOR_COROUTINE_BODY_V1 else row
            for row in graph.protocol_scopes
            if row.id != scope and row.id not in {ProtocolScopeID(call.id.value + ".scope") for call in old["calls"]}),
            ProtocolScope(scope, ProtocolProfile.COROUTINE_WRAPPER_CONSTRUCTION_V1,
                OperationSiteSubject(caller.id, constructor.id), _source_gap()), *scopes),
        protocol_operations=(*(native_row(row) for row in old_rows),
            *constructor_rows, *call_rows, *(old["final_rows"] if final_adapters else ())),
        protocol_call_inputs=tuple(inputs), protocol_result_consumers=tuple(receipts),
        protocol_bindings=tuple(links) if attach_link else ())
    choices = {operation.id: 0 for operation in create_operations}
    choices[constructor.id] = 0
    choices.update((item["caller_call"].id, item["selected_call_edge"]) for item in driver_details)
    choices[old["extract"].id] = 0
    return graph, {**old, "caller": caller,
        "caller_path": _selected_path(graph, caller, choices),
        "body_kind": ResumableKind.COROUTINE, "body_definition": graph.resumable_bodies[0],
        "construction_scope": scope, "source": source, "constructor": constructor,
        "constructor_rows": constructor_rows, "constructor_expected": expected_body,
        "constructor_body": construction_inputs[0], "constructor_failure": constructor_failure,
        "get": constructor, "get_rows": constructor_rows,
        "create_operations": tuple(create_operations), "calls": tuple(calls),
        "drivers": tuple(driver_details), "wrapper_records": tuple(wrapper_records),
        "call_rows": tuple(call_rows), "links": tuple(links), "handoffs": tuple(handoffs),
        "sent_value": sent, "conversion_rows": conversion_rows,
        "conversion_sites": tuple(_site(row) for row in conversion_rows),
        "attach_link": attach_link, "stale_child_state": stale_child_state}


__all__ = ["await_wrapper_final_program"]
