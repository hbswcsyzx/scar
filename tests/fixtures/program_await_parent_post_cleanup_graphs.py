"""P calls a complete await helper, then suspends in its own C1 cleanup.

The synchronous H call finishes before P packs its Return. H retains its
actual B Create, drivers and E/(G)/F implementation. P has a separate external
receiver boundary and two real later cuts; no synchronous driver suspends.
"""
from dataclasses import fields, replace

from scar.ir.program.control import ControlScopeKind, PendingDispatchTerminator
from scar.ir.program.drivers import RawRequestDefinition, RawRequestKind
from scar.ir.program.ids import (
    BlockID, ControlScopeID, LocationID, OperationID, ProtocolScopeID, RegionID, UseID, ValueID,
)
from scar.ir.program.model import (
    AccessMode, Behavior, Block, BlockArgument, CompletionResult, CompletionSignature,
    CompletionSuccessor, ExitKind, ExitPort, Footprint, FootprintKind, InvokeLiteralResult, Operation,
    OperationResult, ProtocolValue, ReferenceValue, StateAccess, StateVersionValue,
    Terminator, TerminatorKind, Use, UseRole, ValueKind, ValueType, value_type,
)
from scar.ir.program.protocols import OwnedUse, ProtocolClause, ProtocolProfile
from scar.ir.program.resumption import FrameContextDetach
from scar.ir.program.structured import ControlEdgeReference
from tests.fixtures.program_async_pipeline_graphs import _selected_path
from tests.fixtures.program_await_cleanup_final_graphs import _PART_TABLES, _rewrite, _stage
from tests.fixtures.program_await_final_region_graphs import await_final_region_program
from tests.fixtures.program_driver_graphs import PACKET, RAW, REFERENCE, _Builder, _use
from tests.fixtures.program_pending_cleanup_graphs import normal_pending_two_cuts_program
from tests.fixtures.program_packet_continuation_graphs import _explicit_transfers
from tests.fixtures.program_protocol_graphs import _scope


def await_parent_post_cleanup_program(*, depth=1, helper_zero_cut=True):
    if type(helper_zero_cut) is not bool:
        raise TypeError("helper_zero_cut requires exact bool")
    helper, h = await_final_region_program(zero_cut=helper_zero_cut, depth=depth)
    parent, pending = normal_pending_two_cuts_program()
    mapping = dict(zip((location.id for location in parent.locations),
                       (location.id for location in helper.locations), strict=True))
    parent = _rewrite(parent, {LocationID: mapping})
    p = parent.regions[0]
    values = {value.id: value for value in parent.values}
    helper_values = {value.id: value for value in helper.values}
    helper_entry = next(block for block in h["caller"].blocks if block.id == h["caller"].entry)
    helper_types = tuple(value_type(helper_values[identity]) for identity in helper_entry.arguments)
    reference_count = sum(type(helper_values[identity]) is ReferenceValue
                          for identity in helper_entry.arguments)
    entry = next(block for block in p.blocks if block.id == p.entry)
    extra = tuple(ReferenceValue(ValueID(f"await.parent.helper.argument.{number}"), p.id,
        BlockArgument(entry.id, len(entry.arguments) + number)) for number in range(reference_count - 1))
    entry = replace(entry, arguments=(*entry.arguments, *(value.id for value in extra)))
    world, context = tuple(location.id for location in helper.locations)
    states = tuple(ValueType(ValueKind.STATE, location=location) for location in (world, context))
    b = _Builder(p.id.value, (world, context))
    normal_name, failure_name = "await.parent.helper.normal", "await.parent.helper.failure"
    caller_value = ValueID("finally.attach.caller")
    caller_type = value_type(values[caller_value])
    normal = b.formals(normal_name, (caller_type, REFERENCE, *states))
    failure = b.formals(failure_name, (caller_type, PACKET, *states))
    references = (entry.arguments[0], *(value.id for value in extra))
    actual_values = (*references, entry.arguments[1], ValueID("finally.attach.after"))
    if len(actual_values) != len(helper_types):
        raise AssertionError("the real H entry must retain all captured references and states")
    actuals = tuple(_use(f"await.parent.helper.input.{number}", identity,
        state=number >= reference_count) for number, identity in enumerate(actual_values))
    kept_callers = tuple(_use(f"await.parent.helper.forward.caller.{slot}", caller_value,
                             protocol=True) for slot in range(2))
    call = b.add("await.parent.helper.call", (*actuals, *kept_callers), effects_complete=True,
        callee=h["caller"].id, invoke_arguments=tuple(use.id for use in actuals),
        completions=tuple(CompletionSignature(port.kind, port.types) for port in h["caller"].exits),
        terminator=Terminator(TerminatorKind.INVOKE, (
            CompletionSuccessor(ExitKind.NORMAL, BlockID(normal_name),
                (kept_callers[0].id, *(CompletionResult(slot) for slot in range(3)))),
            CompletionSuccessor(ExitKind.RAISE, BlockID(failure_name),
                (kept_callers[1].id, *(CompletionResult(slot) for slot in range(3)))),
        )))
    jump = next(operation for operation in parent.operations
                if operation.id == OperationID("finally.to-protected"))
    normal_forward = dict(zip((use.value for use in jump.uses),
                             (normal[1], normal[2], normal[3], normal[0]), strict=True))
    jump = replace(jump, uses=tuple(replace(use, value=normal_forward[use.value]) for use in jump.uses))
    b.block(normal_name, normal, (jump,))

    detach_id = OperationID("await.parent.helper.failure.detach")
    detached_frame = b.value(detach_id.value + ".frame", OperationResult(detach_id, 0),
                            value_type(values[ValueID("finally.initial.frame")]))
    detached_context = b.value(detach_id.value + ".context", OperationResult(detach_id, 1), states[1])
    detach_uses = (_use(detach_id.value + ".caller", failure[0], protocol=True),
                   _use(detach_id.value + ".before", failure[3], state=True))
    detach = b.add(detach_id.value, detach_uses, results=(detached_frame, detached_context),
        effects_complete=True, accesses=(StateAccess(context, detach_uses[1].id,
            AccessMode.READ_WRITE, detached_context, Footprint(FootprintKind.WHOLE)),))
    detach = replace(detach, behaviors=(Behavior.CONTROL, Behavior.READ, Behavior.WRITE))
    b.operations[-1] = detach
    failure_uses = (_use("await.parent.helper.failure.packet", failure[1], protocol=True),
        _use("await.parent.helper.failure.world", failure[2], state=True),
        _use("await.parent.helper.failure.context", detached_context, state=True))
    raised = b.add("await.parent.helper.failure.raise", failure_uses, effects_complete=True,
        terminator=Terminator(TerminatorKind.RAISE, exit="failure",
                              values=tuple(use.id for use in failure_uses)))
    b.block(failure_name, failure, (detach, raised))
    p = replace(p, blocks=tuple(replace(entry, operations=(*entry.operations[:-1], call.id))
        if block.id == entry.id else block for block in p.blocks) + tuple(b.blocks),
        exits=(*p.exits, ExitPort("failure", ExitKind.RAISE, (PACKET, *states))))
    parent = replace(parent, regions=(p,), values=(*parent.values, *extra, *b.values),
        operations=tuple(jump if operation.id == jump.id else operation for operation in parent.operations)
            + tuple(b.operations),
        control_scopes=tuple(replace(scope, blocks=(*scope.blocks, *(block.id for block in b.blocks)))
            if scope.kind is ControlScopeKind.FUNCTION else scope for scope in parent.control_scopes),
        frame_context_detaches=(*parent.frame_context_detaches,
            FrameContextDetach(detach.id, detach_uses[0].id, detached_frame)))
    # This new P fixture declares its original pure control transfers. C1
    # callbacks retain their original unknown effects and current-state writes.
    parent, declared_transfers = _explicit_transfers(parent)
    # Both complete bodies live in the same graph. H is the actual callee of
    # P's INVOKE; no body, outcome or child implementation is a parallel demo.
    updates = {field.name: (*getattr(parent, field.name), *getattr(helper, field.name))
        for field in fields(parent) if field.name not in ("root", "regions", "locations")}
    combined = replace(parent, regions=(p, *(replace(region, parent=p.id)
        if region.id == h["caller"].id else region for region in helper.regions)),
        locations=helper.locations, **updates)
    cuts = (pending["first_suspend"], pending["second_suspend"])
    source_operations = (*cuts, OperationID("finally.return"))
    parts = []
    for number, source in enumerate(source_operations):
        part = _stage(parent, number, source, None if number == 0 else cuts[number - 1])
        maps = {
            RegionID: {part["region"].id: RegionID("parent.outer." + part["region"].id.value)},
            BlockID: {block.id: BlockID("parent.outer." + block.id.value) for block in part["region"].blocks},
            OperationID: {operation.id: OperationID("parent.outer." + operation.id.value)
                          for operation in part["operations"]},
            ValueID: {value.id: ValueID("parent.outer." + value.id.value) for value in part["values"]},
            UseID: {use.id: UseID("parent.outer." + use.id.value)
                    for operation in part["operations"] for use in operation.uses},
            ControlScopeID: {scope.id: ControlScopeID("parent.outer." + scope.id.value)
                             for scope in part["control_scopes"]},
            ProtocolScopeID: {scope.id: ProtocolScopeID("parent.outer." + scope.id.value)
                              for scope in part["protocol_scopes"]},
        }
        part = {key: ({_rewrite(operation, maps): selected for operation, selected in value.items()}
                      if key == "choices" else _rewrite(value, maps)) for key, value in part.items()}
        # P is an ordinary generator. These are P's host adapters; the H/B
        # generator-coroutine and extraction contracts retain their profiles.
        part["protocol_scopes"] = tuple(replace(scope, profile=ProtocolProfile.GENERATOR_BODY_V1)
            if scope.profile is ProtocolProfile.GENERATOR_COROUTINE_BODY_V1 else scope
            for scope in part["protocol_scopes"])
        part["protocol_operations"] = tuple(replace(row, clause=ProtocolClause.HOST_ADAPTER)
            if row.clause is ProtocolClause.DIRECT_HOST_ADAPTER else row
            for row in part["protocol_operations"])
        parts.append(part)
    host = _Builder("await.parent.host", (world, context))
    host_entry_name = "await.parent.host.entry"
    host_entry = host.formals(host_entry_name, (REFERENCE, REFERENCE, *states))
    receiver, sent = host_entry[:2]
    current_name, current_args, current_states = host_entry_name, host_entry, host_entry[2:]
    outer_calls, driver_records, raw_definitions = [], [], []
    for number, part in enumerate(parts):
        name = f"await.parent.host.call.{number}"
        operands = () if number == 0 else (_use(name + ".sent", sent),)
        raw = host.value(name + ".raw.value", OperationResult(OperationID(name + ".raw"), 0), RAW)
        pack = host.add(name + ".raw", operands, results=(raw,), effects_complete=True)
        raw_definitions.append(RawRequestDefinition(raw,
            RawRequestKind.NEXT if number == 0 else RawRequestKind.SEND,
            tuple(use.id for use in operands)))
        inputs = (_use(name + ".receiver", receiver), _use(name + ".raw", raw, protocol=True),
            *(() if number == 0 else (_use(name + ".payload", sent),)),
            *(_use(name + f".state.{slot}", value, state=True) for slot, value in enumerate(current_states)))
        keep = _use(name + ".forward.receiver", receiver)
        edges, normal_data = [], None
        for port in part["region"].exits:
            label = "normal" if port.kind is ExitKind.NORMAL else "failure"
            landing_name = name + "." + label
            landing = host.formals(landing_name,
                (REFERENCE, *port.types) if port.kind is ExitKind.NORMAL else port.types)
            edges.append(CompletionSuccessor(port.kind, BlockID(landing_name),
                ((keep.id, *(CompletionResult(slot) for slot in range(len(port.types))))
                 if port.kind is ExitKind.NORMAL else tuple(CompletionResult(slot) for slot in range(len(port.types))))))
            if port.kind is ExitKind.NORMAL:
                normal_data = landing_name, landing
            else:
                host.block(landing_name, landing,
                           (host.terminal(landing_name + ".raise", landing, fail=True),))
        actual = host.add(name, (*inputs, *((keep,) if normal_data is not None else ())),
            effects_complete=True, callee=part["region"].id,
            invoke_arguments=tuple(use.id for use in inputs),
            completions=tuple(CompletionSignature(port.kind, port.types) for port in part["region"].exits),
            terminator=Terminator(TerminatorKind.INVOKE, tuple(edges)))
        host.block(current_name, current_args, (pack, actual))
        selected_kind = ExitKind.RAISE if number == 2 else ExitKind.NORMAL
        selected_edge = next(slot for slot, edge in enumerate(edges) if edge.kind is selected_kind)
        outer_calls.append(actual)
        driver_records.append({"part": part, "region": part["region"], "call": actual,
            "drive": part["drive"], "outcome_source": source_operations[number],
            "path": part["path"], "terminal": part["host"], "selected_edge": selected_edge})
        if normal_data is not None:
            current_name, current_args = normal_data
            receiver, current_states = current_args[0], current_args[2:]
    host_region = host.finish(host_entry_name)
    host_region = replace(host_region, exits=tuple(port for port in host_region.exits
                                                  if port.kind is ExitKind.RAISE))
    table_updates = {name: (*getattr(combined, name),
        *(row for part in parts for row in part[name])) for name in _PART_TABLES}
    graph = replace(combined, root=host_region.id,
        regions=(host_region, replace(p, parent=host_region.id),
            *(region for region in combined.regions if region.id != p.id),
            *(replace(part["region"], parent=host_region.id) for part in parts)),
        operations=(*combined.operations, *host.operations,
                    *(operation for part in parts for operation in part["operations"])),
        values=(*combined.values, *host.values, *(value for part in parts for value in part["values"])),
        raw_driver_requests=(*combined.raw_driver_requests, *raw_definitions),
        control_scopes=(*combined.control_scopes, _scope(host_region.id, host_region.blocks),
            *(scope for part in parts for scope in part["control_scopes"])), **table_updates)
    host_choices = {record["call"].id: record["selected_edge"] for record in driver_records}
    helper_blocks = {block.id: block for block in h["caller"].blocks}
    choices = tuple(ControlEdgeReference(helper_blocks[block].operations[-1], selected)
        for block, selected in h["caller_path"] if selected is not None)
    choices += tuple(_normal_result(record["operation"]).edge for record in h["stage_records"])
    choices += (ControlEdgeReference(call.id, 0),)
    operations = {operation.id: operation for operation in graph.operations}
    return graph, {"helper": h, "helper_program": helper, "parent": p,
        "parent_helper_call": call, "parent_helper_normal": BlockID(normal_name),
        "parent_helper_failure": BlockID(failure_name), "start": (BlockID(normal_name), 0),
        "source": h["stage_records"][-1]["own_results"][ExitKind.NORMAL],
        "choices": choices, "parent_cuts": cuts, "parent_return": operations[OperationID("finally.return")],
        "parent_failure": raised, "parent_pending": pending,
        "pending_definition": parent.pending_completions[0],
        "declared_transfers": declared_transfers,
        "pending_constructor": operations[OperationID("finally.original")],
        "pending_dispatch": next(operation for operation in parent.operations
            if type(operation.terminator) is PendingDispatchTerminator),
        "host": host_region, "host_path": _selected_path(graph, host_region, host_choices),
        "outer_drivers": tuple(driver_records), "outer_calls": tuple(outer_calls),
        "depth": depth, "helper_zero_cut": helper_zero_cut}


def _normal_result(operation):
    slot, = tuple(slot for slot, edge in enumerate(operation.terminator.successors)
                  if edge.kind is ExitKind.NORMAL)
    return InvokeLiteralResult(ControlEdgeReference(operation.id, slot), CompletionResult(0))


__all__ = ["await_parent_post_cleanup_program"]
