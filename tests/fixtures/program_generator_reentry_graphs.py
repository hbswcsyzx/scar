"""One resumable body actually invokes its reentry driver, catches, and yields.

The captured holder carries the successful Create handle through original
coarse state and typed addresses. Read-from/object coherence is an explicit
source condition, not inferred from a field name or a fake content version.
"""
from dataclasses import replace

from scar.ir.literals import PythonLiteral
from scar.ir.program.control import ProtocolValueKind as P, ProtocolValueType
from scar.ir.program.drivers import RawRequestDefinition, RawRequestKind
from scar.ir.program.ids import BlockID, OperationID, UseID, ValueID
from scar.ir.program.model import (
    AccessMode, Behavior, Block, BlockArgument, CompletionResult, CompletionSignature,
    CompletionSuccessor, ExitKind, LiteralEvaluation, Operation, OperationResult,
    ReferenceValue, StateAccess, StateVersionValue, Successor, Terminator, TerminatorKind,
    Use, UseRole, ValueKind, ValueType,
)
from scar.ir.program.protocols import BodyStatePredicateRule
from scar.ir.program.state_addresses import (
    AddressCoverage, AddressEffect, ExistingAccess, ObjectField, ReferenceOwner,
    StateAddressRefinement,
)
from tests.fixtures.program_driver_graphs import PACKET, RAW, REFERENCE, _Builder, _use, driver_program
from tests.fixtures.program_generator_admission_graphs import (
    _body, _caller, _driver, _guard, _op, _scope,
)
from tests.fixtures.program_generator_close_graphs import generator_close_program
from tests.fixtures.program_generator_close_retry_graphs import _driver_part
from tests.fixtures.program_publication_graphs import with_publications


def _inner_driver(kind, body):
    if kind is RawRequestKind.CLOSE:
        graph, details = generator_close_program(outcome="yield", adapter="helper", body_graph=body)
        interface, = graph.driver_interfaces
        region = next(region for region in graph.regions if region.id == interface.region)
        entry = next(block for block in region.blocks if block.id == region.entry)
        unused = entry.arguments[2]
        assert not any(use.value == unused for op in graph.operations for use in op.uses)
        args = tuple(value for value in entry.arguments if value != unused)
        graph = replace(graph, values=tuple(replace(value, origin=BlockArgument(entry.id, args.index(value.id)))
            if value.id in args else value for value in graph.values if value.id != unused),
            regions=tuple(replace(item, blocks=tuple(replace(block, arguments=args) if block.id == entry.id
                else block for block in item.blocks)) if item.id == region.id else item for item in graph.regions))
        target = "close"
    else:
        target = "packet" if kind is RawRequestKind.THROW else "value" if kind is RawRequestKind.SEND else "start"
        graph, details = _driver(target)
    interface, = graph.driver_interfaces
    region = next(region for region in graph.regions if region.id == interface.region)
    entry = next(block for block in region.blocks if block.id == region.entry)
    if target == "start":
        candidates = ((entry.id, interface.receiver, interface.scheduler_request),)
    else:
        helper = _op(graph, details["processing"])
        normal, raised = helper.terminator.successors
        landing = next(block for block in region.blocks if block.id == normal.block)
        candidates = ((normal.block, landing.arguments[0], landing.arguments[1]),
                      (raised.block, interface.receiver, interface.scheduler_request))
    guards = []
    for number, (block, owner, raw) in enumerate(candidates):
        graph, guard = _guard(graph, block_id=block, owner=owner, raw=raw,
            label=f"reentry.running.{number}", rule=BodyStatePredicateRule.IS_RUNNING,
            admit_true=False, request_kind=kind)
        guards.append(guard)
    part, maps = _driver_part(graph, "reentry.inner")
    return part, {"guards": tuple(maps[OperationID][guard["predicate"]] for guard in guards),
                  "driver": part["region"].id}


def _body_with_reentry(body, inner, kind):
    region = body.regions[0]
    domains = tuple(location.id for location in body.locations)
    states = tuple(ValueType(ValueKind.STATE, location=location) for location in domains)
    b = _Builder(region.id.value, domains)
    holder, world, attached = ValueID("resume.x"), ValueID("resume.world.0"), ValueID("resume.attach.after")
    caller = ValueID("resume.attach.caller")
    owner = b.value("reentry.loaded.owner", OperationResult(OperationID("reentry.holder.read"), 0), REFERENCE)
    holder_use, state_use = _use("reentry.read.holder", holder), _use("reentry.read.state", world, state=True)
    read = b.add("reentry.holder.read", (holder_use, state_use), results=(owner,), effects_complete=True,
        accesses=(StateAccess(domains[0], state_use.id, AccessMode.READ),))
    read = replace(read, behaviors=(Behavior.READ, Behavior.COMPUTE))
    b.operations[-1] = read
    argument = b.value("reentry.argument.value", OperationResult(OperationID("reentry.argument"), 0), REFERENCE)
    produce = b.add("reentry.argument", results=(argument,), effects_complete=True)
    operands = tuple(_use(f"reentry.raw.operand.{number}", argument)
                     for number in range(1 if kind in (RawRequestKind.SEND, RawRequestKind.THROW) else 0))
    raw = b.value("reentry.raw.value", OperationResult(OperationID("reentry.raw"), 0), RAW)
    pack = b.add("reentry.raw", operands, results=(raw,), effects_complete=True)
    inner_values = {value.id: value for value in inner["values"]}
    entry = next(block for block in inner["region"].blocks if block.id == inner["region"].entry)
    actual_values = (owner, raw, *((argument,) if kind in (RawRequestKind.SEND, RawRequestKind.THROW) else ()), world, attached)
    assert len(actual_values) == len(entry.arguments)
    actuals = tuple(_use(f"reentry.call.actual.{number}", value,
        state=isinstance(inner_values[formal], StateVersionValue),
        protocol=formal == entry.arguments[1]) for number, (formal, value) in enumerate(zip(entry.arguments, actual_values)))
    edges, forwarding, continues, handlers, context_installs = [], [], [], [], []
    for number, port in enumerate(inner["region"].exits):
        label = "reentry.body." + port.kind.value.lower()
        landing = b.formals(label, (*port.types, ProtocolValueType(P.DRIVE_CALLER_CONTEXT), REFERENCE))
        caller_forward = _use(label + ".caller", caller, protocol=True)
        holder_forward = _use(label + ".holder", holder)
        forwarding.extend((caller_forward, holder_forward))
        edges.append(CompletionSuccessor(port.kind, BlockID(label),
            (*(CompletionResult(index) for index in range(len(port.types))), caller_forward.id, holder_forward.id)))
        result = b.value(label + ".continued", OperationResult(OperationID(label + ".handle"), 0), REFERENCE)
        incoming = _use(label + ".selected.result", landing[0], protocol=port.kind is ExitKind.RAISE)
        context = landing[2]
        prefix = []
        if port.kind is ExitKind.RAISE:
            # A declared completion-preserving context write, with no hidden
            # native/user callback. Native except installation applicability
            # is not established by this original operation or its label.
            install_id = OperationID(label + ".caught.context")
            context = b.value(label + ".caught.after", OperationResult(install_id, 0), states[1])
            packet_use = _use(label + ".caught.packet", landing[0], protocol=True)
            context_use = _use(label + ".caught.before", landing[2], state=True)
            install = b.add(install_id.value, (packet_use, context_use), results=(context,),
                accesses=(StateAccess(domains[1], context_use.id, AccessMode.READ_WRITE, context),),
                effects_complete=True)
            install = replace(install, behaviors=(Behavior.CONTROL, Behavior.READ, Behavior.WRITE))
            b.operations[-1] = install
            prefix.append(install)
            context_installs.append(install.id)
        continued = b.add(label + ".handle", (incoming,), results=(result,), effects_complete=True)
        outgoing = tuple(_use(label + f".out.{index}", value, state=index in (1, 2), protocol=index == 0)
                         for index, value in enumerate((landing[-2], landing[1], context, landing[-1], result)))
        jump = b.add(label + ".continue", outgoing, effects_complete=True,
            terminator=Terminator(TerminatorKind.JUMP, (Successor(BlockID("reentry.body.yield"),
                tuple(use.id for use in outgoing)),)))
        b.block(label, landing, (*prefix, continued, jump))
        continues.append(result)
        handlers.append(continued.id)
    call = b.add("reentry.body.call", (*actuals, *forwarding), callee=inner["region"].id,
        effects_complete=True, invoke_arguments=tuple(use.id for use in actuals),
        completions=tuple(CompletionSignature(port.kind, port.types) for port in inner["region"].exits),
        terminator=Terminator(TerminatorKind.INVOKE, tuple(edges)))
    joined = b.formals("reentry.body.yield", (ProtocolValueType(P.DRIVE_CALLER_CONTEXT), *states, REFERENCE, REFERENCE))
    mapping = {caller: joined[0], world: joined[1], attached: joined[2], holder: joined[3]}
    moved = {OperationID("resume.detach"), OperationID("resume.suspend")}
    operations = tuple(replace(op, uses=tuple(replace(use,
        value=joined[4] if use.id == UseID("resume.suspend.export") else mapping.get(use.value, use.value))
        for use in op.uses)) if op.id in moved else op for op in body.operations)
    blocks = tuple(replace(block, operations=(OperationID("resume.initial"), OperationID("resume.attach"),
        read.id, produce.id, pack.id, call.id)) if block.id == region.entry else block for block in region.blocks)
    blocks += (*b.blocks, Block(BlockID("reentry.body.yield"), joined,
                               (OperationID("resume.detach"), OperationID("resume.suspend"))))
    graph = replace(body, operations=(*operations, *b.operations), values=(*body.values, *b.values),
        regions=(replace(region, blocks=blocks),),
        control_scopes=tuple(replace(scope, blocks=tuple(block.id for block in blocks))
                             if scope.region == region.id else scope for scope in body.control_scopes),
        raw_driver_requests=(*body.raw_driver_requests, RawRequestDefinition(raw, kind, tuple(use.id for use in operands))),
        state_address_refinements=(*body.state_address_refinements, StateAddressRefinement(ExistingAccess(read.id, 0),
            (AddressEffect(ReferenceOwner(holder_use.id), (ObjectField("body"),), AccessMode.READ),), AddressCoverage.PARTIAL)))
    return graph, {"read": read.id, "loaded_owner": owner, "inner_call": call.id,
                   "handlers": tuple(handlers), "continuations": tuple(continues), "join": joined,
                   "inner_raw": raw, "holder": holder, "context_installs": tuple(context_installs)}


def generator_reentry_program(*, kind=RawRequestKind.NEXT):
    if type(kind) is not RawRequestKind:
        raise TypeError("kind must be exact RawRequestKind")
    body = _body()
    inner, details = _inner_driver(kind, body)
    body, connection = _body_with_reentry(body, inner, kind)
    graph, _ = _scope(driver_program(target="start", body_graph=body))
    graph = with_publications(graph)
    table_names = ("driver_interfaces", "final_body_gates", "body_drives", "driver_lifecycles",
                   "body_outcome_commits", "terminal_frame_releases", "protocol_scopes",
                   "protocol_operations", "literal_evaluations", "exception_packets")
    graph = replace(graph, regions=(*graph.regions, replace(inner["region"], parent=graph.root)),
        operations=(*graph.operations, *inner["operations"]), values=(*graph.values, *inner["values"]),
        control_scopes=(*graph.control_scopes, *inner["control_scopes"]),
        **{name: (*getattr(graph, name), *inner[name]) for name in table_names})
    graph, caller = _caller(graph, kind=RawRequestKind.NEXT, send_none=True, stage="created")
    create, = graph.resumable_creates
    create_op = _op(graph, create.operation)
    capture = next(row for row in create.captures if row.formal == ValueID("resume.x"))
    holder = next(use.value for use in create_op.uses if use.id == capture.source)
    current = next(value for value in graph.values if value.id == caller["initial_states"][0])
    write_id = OperationID("reentry.holder.store")
    after = StateVersionValue(ValueID("reentry.holder.after"), graph.root, OperationResult(write_id, 0), current.location)
    holder_use = _use("reentry.store.holder", holder)
    payload_use = _use("reentry.store.handle", caller["owner"])
    state_use = _use("reentry.store.before", current.id, state=True)
    write = Operation(write_id, "store successful Create handle", (Behavior.WRITE,),
        (holder_use, payload_use, state_use), (after.id,),
        (StateAccess(current.location, state_use.id, AccessMode.WRITE, after.id),), effects_complete=True)
    call = _op(graph, caller["call"])
    changed = replace(call, uses=tuple(replace(use, value=after.id) if use.value == current.id else use for use in call.uses))
    graph = replace(graph, operations=tuple(changed if op.id == call.id else op for op in graph.operations) + (write,),
        values=(*graph.values, after),
        regions=tuple(replace(region, blocks=tuple(replace(block,
            operations=(write.id, *block.operations)) if call.id in block.operations else block
            for block in region.blocks)) if region.id == graph.root else region for region in graph.regions),
        state_address_refinements=(*graph.state_address_refinements, StateAddressRefinement(ExistingAccess(write.id, 0),
            (AddressEffect(ReferenceOwner(holder_use.id), (ObjectField("body"),), AccessMode.WRITE),), AddressCoverage.PARTIAL)))
    return graph, {**details, **connection, **caller, "kind": kind, "store": write.id,
                   "stored_handle": caller["owner"], "stored_state": after.id,
                   "capture": capture, "holder_actual": holder, "outer_drive": OperationID("driver.drive")}


__all__ = ["generator_reentry_program"]
