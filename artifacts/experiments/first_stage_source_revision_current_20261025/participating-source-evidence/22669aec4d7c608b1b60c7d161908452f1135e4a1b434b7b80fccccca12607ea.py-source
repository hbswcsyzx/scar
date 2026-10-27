"""Declared created-close branch and body-only mark, never guard execution.

Core and D1/publication validation must succeed first. No native predicate,
association, phase or true-path feasibility is inferred by this overlay.
"""
from __future__ import annotations

from .control import ProtocolValueKind
from .driver_flow import driver_role_copies
from .drivers import DriverReceiverKind
from .ids import UseID
from .lifecycle_validation import _body_update_errors
from .model import (
    AccessMode, Behavior, DataValue, FootprintKind, OperationResult, ProtocolValue,
    ReferenceValue, StateVersionValue, TerminatorKind, UseRole,
)


def no_body_errors(graph, *, operation_blocks, incoming_edges):
    """Join exact roles, current READs, actual branch and private first mark."""
    errors = []

    def error(code, path, message):
        errors.append((code, str(path), message))

    values = {value.id: value for value in graph.values}
    operations = {operation.id: operation for operation in graph.operations}
    blocks = {block.id: block for region in graph.regions for block in region.blocks}
    owners = {block.id: region.id for region in graph.regions for block in region.blocks}
    interfaces = {row.region: row for row in graph.driver_interfaces}
    scopes = {row.region for row in graph.driver_lifecycles}
    copies = {}
    predicates = {}

    def scope(operation, path):
        region = owners[operation_blocks[operation.id]]
        interface = interfaces.get(region)
        if region not in scopes or interface is None:
            error("no_body_scope", path, "no-body declarations require their owning enabled driver scope")
            return None
        return interface

    for row in graph.created_close_tests:
        op = operations.get(row.operation)
        if op is None:
            error("no_body_test_operation", row.operation, "test must name its real operation")
            continue
        interface = scope(op, row.operation)
        if interface is None:
            continue
        own = {use.id: use for use in op.uses}
        if interface.region not in copies:
            copies[interface.region] = driver_role_copies(graph, interface)
        receivers, schedulers = copies[interface.region]

        def role(identity, expected, kind):
            use = own.get(identity)
            valid = use is not None and use.role is kind
            if expected is ReferenceValue:
                valid = valid and isinstance(values[use.value], ReferenceValue)
            else:
                valid = (valid and isinstance(values[use.value], ProtocolValue)
                         and values[use.value].protocol is ProtocolValueKind.RAW_DRIVER_REQUEST)
            return use if valid else None

        instance = role(row.instance, ReferenceValue, UseRole.REFERENCE)
        scheduler = role(row.scheduler_request, ProtocolValue, UseRole.PROTOCOL)
        effective = role(row.effective_request, ProtocolValue, UseRole.PROTOCOL)
        session = None if row.session is None else role(row.session, ReferenceValue, UseRole.REFERENCE)
        if (instance is None or scheduler is None or effective is None
                or scheduler.value not in schedulers):
            error("no_body_test_roles", row.operation, "test requires actual Reference/RAW roles and fixed scheduler copy")
        if interface.receiver_kind is DriverReceiverKind.BODY:
            if (row.session is not None or instance is None or instance.value not in receivers
                    or effective is None or scheduler is None or effective.value != scheduler.value):
                error("no_body_test_roles", row.operation, "BODY test uses its fixed instance, independent Uses of the same scheduler, and no session")
        elif session is None or session.value not in receivers:
            error("no_body_test_roles", row.operation, "ASYNC_REQUEST test requires its fixed session; body and latent remain actual values")

        result = values.get(row.result)
        if (op.results != (row.result,) or not isinstance(result, DataValue)
                or result.data_type != "builtins.bool"
                or not isinstance(result.origin, OperationResult)
                or result.origin.operation != op.id):
            error("no_body_test_result", row.operation, "test defines exactly its own builtins.bool result")
        if (op.terminator is not None or op.callee is not None or op.call_arguments
                or op.invoke_arguments or op.completions or not op.effects_complete
                or set(op.behaviors) != {Behavior.CONTROL, Behavior.READ}):
            error("no_body_test_shape", row.operation, "predicate is a complete callback-free ordinary read intrinsic")
        lifecycle = set(interface.lifecycle)
        locations, state_uses = [], set()
        for access in op.accesses:
            locations.append(access.location)
            state_uses.add(access.before)
            before = own.get(access.before)
            if (access.mode is not AccessMode.READ or access.after is not None
                    or access.full_overwrite or access.footprint.kind is not FootprintKind.WHOLE
                    or before is None or before.role is not UseRole.STATE_CONTENT
                    or not isinstance(values[before.value], StateVersionValue)):
                error("no_body_test_access", row.operation, "predicate only reads whole current lifecycle state")
        if set(locations) != lifecycle or len(locations) != len(lifecycle):
            error("no_body_test_access", row.operation, "predicate reads each lifecycle domain exactly once")
        roles = {row.instance, row.scheduler_request, row.effective_request}
        if row.session is not None:
            roles.add(row.session)
        if set(own) != state_uses | roles:
            error("no_body_test_uses", row.operation, "predicate owns only its independent roles and access-before Uses")
        block = blocks[operation_blocks[op.id]]
        branch = operations[block.operations[-1]]
        condition = next((use for use in branch.uses
                          if branch.terminator is not None and use.id == branch.terminator.condition), None)
        if (len(block.operations) < 2 or block.operations[-2] != op.id
                or branch.terminator is None or branch.terminator.kind is not TerminatorKind.BRANCH
                or condition is None or condition.value != row.result):
            error("no_body_test_branch", row.operation, "test must immediately precede the branch of its own bool")
        else:
            if (not branch.effects_complete or set(branch.behaviors) != {Behavior.CONTROL}
                    or branch.results or branch.accesses or branch.callee is not None
                    or branch.call_arguments or branch.invoke_arguments or branch.completions):
                error("no_body_branch_shape", branch.id, "guard branch is complete callback-free control forwarding without writes")
            predicates[branch.id] = row

    # Only an explicit Finish asserts a mark. A predicate alone never does.
    for row in graph.no_body_finishes:
        op = operations.get(row.operation)
        if op is None:
            error("no_body_operation", row.operation, "finish must name its real operation")
            continue
        interface = scope(op, row.operation)
        if interface is None:
            continue
        branch = operations.get(row.precondition.operation)
        test = predicates.get(row.precondition.operation)
        if (row.precondition.successor_index != 0 or branch is None or test is None
                or owners[operation_blocks[branch.id]] != interface.region):
            error("no_body_precondition", row.operation, "finish requires its driver's declared predicate branch true edge")
            continue
        edge = branch.terminator.successors[0]
        landing = blocks[edge.block]
        if (operation_blocks[op.id] != edge.block or landing.operations[0] != op.id
                or len(incoming_edges[edge.block]) != 1):
            error("no_body_landing", row.operation, "finish is first on the exact private true landing")
        own = {use.id: use for use in op.uses}
        instance = own.get(row.instance)
        test_op = operations[test.operation]
        test_owner = next((use.value for use in test_op.uses if use.id == test.instance), None)
        branch_uses = {use.id: use for use in branch.uses}
        owner_matches = instance is not None and instance.value == test_owner
        if instance is not None and instance.value in landing.arguments:
            actual = edge.arguments[landing.arguments.index(instance.value)]
            owner_matches = (isinstance(actual, UseID) and actual in branch_uses
                             and branch_uses[actual].value == test_owner)
        if (instance is None or instance.role is not UseRole.REFERENCE
                or not isinstance(values[instance.value], ReferenceValue) or not owner_matches):
            error("no_body_owner", row.operation, "finish owner must exactly copy this predicate instance")
        _body_update_errors(op, row.instance, interface, values, error, "no_body")
    return tuple(errors)


__all__ = ["no_body_errors"]
