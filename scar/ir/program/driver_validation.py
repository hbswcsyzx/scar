"""D1 driver declarations over canonical Uses, CFG and completion state.

These checks establish a static interface contract, never an instance, runtime
admission, source correspondence or lifecycle proof.
"""
from __future__ import annotations

from .cleanup_forward import _must_forward
from .control import ProtocolValueKind as P
from .drivers import (
    BodyDriveResult, BodyDriveTerminator, BodyResume, BodyStart,
    DriverReceiverKind,
)
from .environments import EnvironmentRole
from .driver_flow import body_drive_target, body_outcome_uses
from .model import (
    Behavior, BlockArgument, CompletionResult, ExitKind, OperationResult, ProtocolValue,
    ReferenceValue, StateVersionValue, TerminatorKind, value_type,
)
from .resumption import SuspendTerminator, resume_slot_type, saved_actual_use
from .resumption_flow import first_body_outcome_operations


def driver_errors(graph, *, operation_blocks, region_domains, incoming_edges):
    """Return D1 errors after canonical core and body validation have succeeded."""
    errors = []

    def error(code, path, message):
        errors.append((code, str(path), message))

    values = {row.id: row for row in graph.values}
    operations = {row.id: row for row in graph.operations}
    regions = {row.id: row for row in graph.regions}
    blocks = {row.id: row for region in graph.regions for row in region.blocks}
    owners = {row.id: region.id for region in graph.regions for row in region.blocks}
    bodies = {row.region: row for row in graph.resumable_bodies}

    def protocol(value, kind):
        return isinstance(values.get(value), ProtocolValue) and values[value].protocol is kind

    def owned(op, use_id):
        return next((use for use in op.uses if use.id == use_id), None)

    def argument(op, index):
        if index >= len(op.invoke_arguments):
            return None
        return owned(op, op.invoke_arguments[index])

    def invoke(operation_id, path):
        op = operations.get(operation_id)
        if op is None or op.terminator is None or op.terminator.kind is not TerminatorKind.INVOKE:
            error("driver_invoke", path, "declaration requires its real INVOKE operation")
            return None
        return op

    def normal_result(op, port, path, expected):
        signatures = {row.kind: row for row in op.completions}
        signature = signatures.get(ExitKind.NORMAL)
        if signature is None or port.index >= len(signature.types):
            error("driver_result", path, "NORMAL result index exceeds its signature")
            return None
        normal = next((edge for edge in op.terminator.successors
                       if edge.kind is ExitKind.NORMAL), None)
        if normal is None:
            error("driver_result", path, "result requires a real NORMAL successor")
            return None
        found = [formal for actual, formal in zip(normal.arguments, blocks[normal.block].arguments)
                 if isinstance(actual, CompletionResult) and actual.index == port.index]
        if len(found) != 1 or not expected(values[found[0]]):
            error("driver_result", path, "result must project exactly one correctly typed NORMAL formal")
            return None
        return found[0]

    # No metadata line can make a nonexistent operation into a new producer.
    per_table = (
        (graph.resumable_creates, "resumable_creates", "operation"),
        (graph.raw_driver_requests, "raw_driver_requests", "value"),
        (graph.async_request_creates, "async_request_creates", "operation"),
        (graph.request_association_reads, "request_association_reads", "operation"),
        (graph.driver_interfaces, "driver_interfaces", "region"),
        (graph.final_body_gates, "final_body_gates", "operation"),
        (graph.body_drives, "body_drives", "operation"),
    )
    for rows, name, key in per_table:
        seen = set()
        for row in rows:
            identity = getattr(row, key)
            if identity in seen:
                error("driver_duplicate", name, "declaration key must be unique")
            seen.add(identity)
    op_roles = {}
    for rows, name, _ in per_table:
        if name in ("raw_driver_requests", "driver_interfaces"):
            continue
        for row in rows:
            if row.operation in op_roles:
                error("driver_operation_role", row.operation, "one operation cannot have conflicting driver declarations")
            op_roles[row.operation] = name
    if errors:
        return tuple(errors)

    for row in graph.raw_driver_requests:
        value = values.get(row.value)
        if not protocol(row.value, P.RAW_DRIVER_REQUEST) or not isinstance(value.origin, OperationResult):
            error("driver_raw", row.value, "raw definition needs its RAW_DRIVER_REQUEST operation result")
            continue
        op = operations.get(value.origin.operation)
        if op is None or any(owned(op, use) is None or not isinstance(values[owned(op, use).value], ReferenceValue)
                             for use in row.operands):
            error("driver_raw", row.value, "raw operands must be owned Reference Uses")
            continue
        if (op.terminator is not None or op.callee is not None or op.results != (row.value,)
                or tuple(use.id for use in op.uses) != row.operands or op.accesses
                or op.completions or op.invoke_arguments or op.call_arguments
                or not op.effects_complete or not op.behaviors
                or not set(op.behaviors).issubset({Behavior.COMPUTE, Behavior.CONTROL, Behavior.REPRESENT})):
            error("driver_raw_pack", row.value, "raw pack must be a complete ordinary pure interface constructor with exactly its ordered operands")
    definitions = {row.value for row in graph.raw_driver_requests}
    for value in values.values():
        if protocol(value.id, P.RAW_DRIVER_REQUEST) and isinstance(value.origin, OperationResult) and value.id not in definitions:
            error("driver_raw", value.id, "constructed raw request requires its definition")

    environments = {row.region: row for row in graph.environments}
    layouts = {row.environment: row for row in graph.function_entries}
    create_results = {}
    for row in graph.resumable_creates:
        op = invoke(row.operation, row.operation)
        body = regions.get(row.body)
        if op is None:
            continue
        if body is None or body.id not in bodies:
            error("driver_create_body", row.operation, "Create requires a declared resumable body")
            continue
        environment = environments.get(body.id)
        if environment is None or environment.id not in layouts:
            error("driver_create_environment", row.operation, "bound frame Create requires complete environment and FunctionEntryLayout")
            continue
        reference_formals = tuple(formal for formal in blocks[body.entry].arguments
                                  if isinstance(values[formal], ReferenceValue))
        capture_formals = tuple(item.formal for item in row.captures)
        if (len(set(capture_formals)) != len(capture_formals)
                or set(capture_formals) != set(reference_formals)):
            error("driver_create_captures", row.operation, "captures must cover each nonstate entry Reference exactly once")
        capture_sources = [item.source for item in row.captures]
        if len(set(capture_sources)) != len(capture_sources):
            error("driver_create_captures", row.operation, "each capture occurrence needs its independent Use")
        for capture in row.captures:
            use = owned(op, capture.source)
            if (use is None or capture.source not in op.invoke_arguments
                    or not isinstance(values[use.value], ReferenceValue)):
                error("driver_create_capture", row.operation, "capture must name an owned invoke Reference input")
        function_formal = next(item.reference for item in environment.members
                               if item.role is EnvironmentRole.FUNCTION_OBJECT)
        source = next((item.source for item in row.captures if item.formal == function_formal), None)
        if row.function_object != source:
            error("driver_create_function", row.operation, "function_object must reuse the FUNCTION_OBJECT capture Use")
        result = normal_result(op, row.handle_result, row.operation, lambda value: isinstance(value, ReferenceValue))
        if result is not None:
            create_results[result] = row.body

    for row in graph.async_request_creates:
        op = invoke(row.operation, row.operation)
        if op is None:
            continue
        body, latent = owned(op, row.body), owned(op, row.latent)
        if (body is None or row.body not in op.invoke_arguments or not isinstance(values[body.value], ReferenceValue)
                or latent is None or row.latent not in op.invoke_arguments
                or not protocol(latent.value, P.RAW_DRIVER_REQUEST)):
            error("driver_async_create", row.operation, "request creation needs body Reference and latent raw invoke inputs")
        normal_result(op, row.request_result, row.operation, lambda value: isinstance(value, ReferenceValue))
    for row in graph.request_association_reads:
        op = invoke(row.operation, row.operation)
        if op is None:
            continue
        use = owned(op, row.request)
        if use is None or row.request not in op.invoke_arguments or not isinstance(values[use.value], ReferenceValue):
            error("driver_association", row.operation, "association reads its actual request Reference")
        normal_result(op, row.body_result, row.operation, lambda value: isinstance(value, ReferenceValue))
        normal_result(op, row.latent_result, row.operation,
                      lambda value: isinstance(value, ProtocolValue) and value.protocol is P.RAW_DRIVER_REQUEST)

    known_bodies = {identity: {body} for identity, body in create_results.items()}
    changed = True
    while changed:
        changed = False
        bindings = []
        for op in graph.operations:
            if op.terminator is not None:
                for edge in op.terminator.successors:
                    bindings.extend((saved_actual_use(op, actual), formal)
                                    for actual, formal in zip(edge.arguments, blocks[edge.block].arguments))
            if op.callee is not None:
                callee = regions[op.callee]
                actuals = op.invoke_arguments if op.terminator is not None else op.call_arguments
                bindings.extend(zip(actuals, blocks[callee.entry].arguments))
            for actual, formal in bindings:
                use = owned(op, actual) if actual is not None else None
                if use is not None and use.value in known_bodies:
                    before = len(known_bodies.get(formal, ()))
                    known_bodies.setdefault(formal, set()).update(known_bodies[use.value])
                    changed |= len(known_bodies[formal]) != before
            bindings.clear()

    interfaces = {row.region: row for row in graph.driver_interfaces}
    drives = {row.operation: row for row in graph.body_drives}
    gates = {row.drive: row for row in graph.final_body_gates}
    if len(gates) != len(graph.final_body_gates):
        error("driver_gate_pair", "final_body_gates", "each Drive has exactly one final gate")

    # Fixed receiver/scheduler roles use every real incoming, without origin unions.
    copy_incoming = {}
    for region in graph.regions:
        for block in region.blocks:
            for formal in block.arguments:
                copy_incoming[formal] = []
    for op in graph.operations:
        if op.terminator is None:
            continue
        for edge in op.terminator.successors:
            for actual, formal in zip(edge.arguments, blocks[edge.block].arguments):
                source = saved_actual_use(op, actual)
                use = owned(op, source) if source is not None else None
                copy_incoming[formal].append(use.value if use is not None else None)
    role_copies = {}
    for region_id, interface in interfaces.items():
        region = regions.get(region_id)
        if region is None or interface.body not in bodies:
            error("driver_interface", region_id, "driver/body Region must exist and body be resumable")
            continue
        entry = blocks[region.entry]
        if (interface.receiver not in entry.arguments or not isinstance(values.get(interface.receiver), ReferenceValue)
                or interface.scheduler_request not in entry.arguments
                or not protocol(interface.scheduler_request, P.RAW_DRIVER_REQUEST)):
            error("driver_interface_roles", region_id, "receiver Reference and raw scheduler must be real entry parameters")
        domains = region_domains[region_id]
        if not interface.lifecycle or not set(interface.lifecycle).issubset(domains):
            error("driver_lifecycle", region_id, "lifecycle must be a nonempty subset of the driver's entry state domains")
        role_copies[region_id] = (
            _must_forward({interface.receiver}, copy_incoming),
            _must_forward({interface.scheduler_request}, copy_incoming),
        )

    for operation in operations.values():
        if isinstance(operation.terminator, BodyDriveTerminator) and operation.id not in drives:
            error("driver_missing", operation.id, "BodyDrive terminator requires its declaration")
    for row in graph.body_drives:
        op = operations.get(row.operation)
        region_id = owners.get(operation_blocks.get(row.operation))
        interface = interfaces.get(region_id)
        if op is None or not isinstance(op.terminator, BodyDriveTerminator):
            error("driver_terminator", row.operation, "BodyDrive requires its canonical typed terminator")
            continue
        if interface is None:
            error("driver_interface", row.operation, "BodyDrive requires its owning DriverInterface")
            continue
        if row.operation not in gates:
            error("driver_gate_pair", row.operation, "BodyDrive requires exactly one final gate")
        try:
            body, start, edge = body_drive_target(graph, row)
        except ValueError as exc:
            error("driver_target", row.operation, str(exc))
            continue
        if body.id != interface.body:
            error("driver_target", row.operation, "Drive target differs from its interface body")
        instance_use = owned(op, row.instance)
        if instance_use is not None and any(known != body.id for known in known_bodies.get(instance_use.value, ())):
            error("driver_instance_body", row.operation, "known Create source is incompatible with the declared body interface")
        if edge is None and any(not isinstance(values[formal], (ReferenceValue, StateVersionValue))
                                for formal in blocks[body.entry].arguments):
            error("driver_start_interface", row.operation, "Start capture profile requires every nonstate entry port to be a Reference")
        domains = region_domains[body.id]
        if not domains.issubset(region_domains[region_id]):
            error("driver_state_domains", row.operation, "body domains must be available in the driver")
        if ({item.location for item in row.state_inputs} != domains
                or len(row.state_inputs) != len(domains)):
            error("driver_state_inputs", row.operation, "state inputs must cover body domains exactly once")
        for item in row.state_inputs:
            use = owned(op, item.source)
            if use is None or not isinstance(values[use.value], StateVersionValue) or values[use.value].location != item.location:
                error("driver_state_inputs", row.operation, "state input source must have its declared LocationID")
        expected_slots = [] if edge is None else [index for index, slot in enumerate(edge.inputs)
                                                   if slot.location is None]
        if tuple(item.slot for item in row.resume_inputs) != tuple(expected_slots):
            error("driver_resume_inputs", row.operation, "resume inputs must cover nonstate slots once in target slot order; Start has none")
        if edge is not None:
            for item in row.resume_inputs:
                if item.slot >= len(edge.inputs):
                    continue
                use = owned(op, item.source)
                if use is None or value_type(values[use.value]) != resume_slot_type(edge.inputs[item.slot]):
                    error("driver_resume_type", row.operation, "delivered input differs from its target ResumeSlot type")
        for use_id in (row.instance, row.scheduler_request, *(() if row.session is None else (row.session,))):
            if owned(op, use_id) is None:
                error("driver_role", row.operation, "Drive role must be its own Use")
        if owned(op, row.instance) is not None and not isinstance(values[owned(op, row.instance).value], ReferenceValue):
            error("driver_role", row.operation, "instance must be a Reference")
        if owned(op, row.scheduler_request) is not None and not protocol(owned(op, row.scheduler_request).value, P.RAW_DRIVER_REQUEST):
            error("driver_role", row.operation, "scheduler must be RAW_DRIVER_REQUEST")
        if row.session is not None and owned(op, row.session) is not None and not isinstance(values[owned(op, row.session).value], ReferenceValue):
            error("driver_role", row.operation, "session must be a request Reference")
        expected_sources = set(first_body_outcome_operations(body, operations, start))
        sources = [successor.source for successor in op.terminator.successors]
        if len(set(sources)) != len(sources) or set(sources) != expected_sources:
            error("driver_outcomes", row.operation, "successors must cover exactly the first source outcomes")
        for successor in op.terminator.successors:
            if successor.source not in expected_sources:
                continue
            if len(incoming_edges[successor.block]) != 1:
                error("driver_outcome_landing", row.operation, "each source requires a private landing")

    for row in graph.final_body_gates:
        op = invoke(row.operation, row.operation)
        drive = drives.get(row.drive)
        region_id = owners.get(operation_blocks.get(row.operation))
        interface = interfaces.get(region_id)
        if op is None:
            continue
        if drive is None or interface is None or owners.get(operation_blocks.get(row.drive)) != region_id:
            error("driver_gate_pair", row.operation, "gate and declared Drive require one owning driver Region")
            continue
        drive_op = operations.get(row.drive)
        if drive_op is None or not isinstance(drive_op.terminator, BodyDriveTerminator):
            error("driver_gate_pair", row.operation, "paired Drive requires its existing canonical terminator")
            continue
        normal = next(edge for edge in op.terminator.successors if edge.kind is ExitKind.NORMAL)
        landing = blocks[normal.block]
        if len(incoming_edges[landing.id]) != 1 or landing.operations != (row.drive,):
            error("driver_gate_corridor", row.operation, "NORMAL private landing must contain only its paired BodyDrive")
            continue
        role_indices = [row.body_argument, row.scheduler_argument, *row.delivery_arguments]
        if row.session_argument is not None:
            role_indices.append(row.session_argument)
        if len(set(role_indices)) != len(role_indices):
            error("driver_gate_roles", row.operation, "gate role input indices must be distinct")
        gate_body, gate_scheduler = argument(op, row.body_argument), argument(op, row.scheduler_argument)
        gate_session = None if row.session_argument is None else argument(op, row.session_argument)
        if any(argument(op, index) is None for index in role_indices):
            error("driver_gate_roles", row.operation, "gate role index exceeds invoke inputs")
            continue
        receiver_copy, scheduler_copy = role_copies.get(region_id, (set(), set()))
        if gate_scheduler.value not in scheduler_copy:
            error("driver_scheduler_copy", row.operation, "scheduler must copy the fixed interface scheduler")
        if interface.receiver_kind is DriverReceiverKind.BODY:
            if gate_body.value not in receiver_copy or row.session_argument is not None or drive.session is not None:
                error("driver_receiver_copy", row.operation, "BODY receiver must copy entry receiver and has no session")
        elif gate_session is None or gate_session.value not in receiver_copy or drive.session is None:
            error("driver_receiver_copy", row.operation, "ASYNC_REQUEST session must copy its entry receiver")
        role_pairs = [(gate_body, drive.instance), (gate_scheduler, drive.scheduler_request)]
        if gate_session is not None and drive.session is not None:
            role_pairs.append((gate_session, drive.session))
        if len(row.delivery_arguments) != len(drive.resume_inputs):
            error("driver_gate_delivery", row.operation, "gate delivery list must match the Drive's ordered dynamic slots")
        role_pairs.extend((argument(op, index), item.source)
                          for index, item in zip(row.delivery_arguments, drive.resume_inputs))
        formal_positions = {formal: index for index, formal in enumerate(landing.arguments)}
        forwarded_slots = []
        for gate_use, drive_use_id in role_pairs:
            drive_use = owned(drive_op, drive_use_id)
            index = None if drive_use is None else formal_positions.get(drive_use.value)
            actual = None if index is None else normal.arguments[index]
            forward = owned(op, actual)
            if (gate_use is None or forward is None or forward.value != gate_use.value
                    or actual in op.invoke_arguments):
                error("driver_gate_forward", row.operation, "each original role needs its independent exact edge Use/formal/Drive Use")
            if index is not None:
                forwarded_slots.append(index)
        if len(set(forwarded_slots)) != len(forwarded_slots):
            error("driver_gate_forward", row.operation, "gate role forwarding slots must be distinct")
        domains = region_domains[region_id]
        input_states = [values[owned(op, use).value].location for use in op.invoke_arguments
                        if isinstance(values[owned(op, use).value], StateVersionValue)]
        if len(input_states) != len(domains) or set(input_states) != domains:
            error("driver_gate_states", row.operation, "gate must consume every driver current state domain once")
        for edge in op.terminator.successors:
            produced = [values[formal].location for actual, formal in zip(edge.arguments, blocks[edge.block].arguments)
                        if isinstance(actual, CompletionResult) and isinstance(values[formal], StateVersionValue)]
            if len(produced) != len(domains) or set(produced) != domains:
                error("driver_gate_states", row.operation, "both gate completions must produce every driver poststate")
        for item in drive.state_inputs:
            use = owned(drive_op, item.source)
            index = None if use is None else formal_positions.get(use.value)
            if index is None or not isinstance(normal.arguments[index], CompletionResult):
                error("driver_gate_state_forward", row.operation, "body state must consume the gate NORMAL produced poststate")

    return tuple(errors)


__all__ = ["driver_errors", "body_drive_target", "body_outcome_uses"]
