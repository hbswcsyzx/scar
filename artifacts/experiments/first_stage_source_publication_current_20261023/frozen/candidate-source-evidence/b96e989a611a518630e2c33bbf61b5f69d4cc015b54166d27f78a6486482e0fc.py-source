"""Session post and terminal frame-release shape over canonical endpoints.

The declared native conditions are not proved here. Historical terminal
eligibility is checked only after these local shapes and the core have passed.
"""
from __future__ import annotations

from .lifecycle import LifecyclePostBinding
from .model import (
    AccessMode, Behavior, CompletionResult, ExitKind, FootprintKind,
    ReferenceValue, StateVersionValue, TerminatorKind, UseRole,
)


def session_release_errors(graph, *, operation_blocks, region_domains):
    errors = []

    def error(code, path, message):
        errors.append((code, str(path), message))

    values = {value.id: value for value in graph.values}
    operations = {operation.id: operation for operation in graph.operations}
    blocks = {block.id: block for region in graph.regions for block in region.blocks}
    owners = {block.id: region.id for region in graph.regions for block in region.blocks}
    interfaces = {row.region: row for row in graph.driver_interfaces}
    scopes = {row.region for row in graph.driver_lifecycles}

    def operation_scope(row):
        op = operations.get(row.operation)
        if op is None:
            error("session_release_operation", row.operation, "declaration must name its real operation")
            return None, None
        interface = interfaces.get(owners[operation_blocks[op.id]])
        if interface is None or interface.region not in scopes:
            error("session_release_scope", row.operation, "declaration requires its owning enabled driver scope")
            return op, None
        return op, interface

    def reference(op, use_id):
        use = next((use for use in op.uses if use.id == use_id), None)
        return (use is not None and use.role is UseRole.REFERENCE
                and isinstance(values[use.value], ReferenceValue))

    def ordinary(op, expected, complete, prefix):
        if (op.terminator is not None or op.callee is not None or op.call_arguments
                or op.invoke_arguments or op.completions or op.effects_complete is not complete
                or set(op.behaviors) != expected):
            error(prefix + "_shape", op.id, "operation must satisfy its exact ordinary intrinsic effect shape")

    def accesses(op, domains, role_uses, *, release=False):
        prefix = "terminal_release" if release else "session_post"
        own = {use.id: use for use in op.uses}
        locations, before_uses, writes = [], set(), set()
        for access in op.accesses:
            locations.append(access.location)
            before_uses.add(access.before)
            before = own.get(access.before)
            if (access.mode not in ((AccessMode.READ_WRITE,) if release
                                    else (AccessMode.READ, AccessMode.READ_WRITE))
                    or access.footprint.kind is not FootprintKind.WHOLE
                    or access.full_overwrite or access.reference not in (None, *role_uses)
                    or before is None or before.role is not UseRole.STATE_CONTENT
                    or not isinstance(values[before.value], StateVersionValue)):
                error(prefix + "_access", op.id, "intrinsic uses whole current states with its fixed read/write shape")
            if access.mode is AccessMode.READ_WRITE:
                writes.add(access.after)
        if set(locations) != domains or len(locations) != len(domains):
            error(prefix + "_domains", op.id, "accesses cover each required domain exactly once")
        if not writes:
            error(prefix + "_writes", op.id, "intrinsic requires an actual nonempty written state set")
        if set(op.results) != writes:
            error(prefix + "_results", op.id, "results are exactly the actual written after states")
        if set(own) != before_uses | set(role_uses):
            error(prefix + "_uses", op.id, "only actual roles and state-access inputs belong to the intrinsic")

    for row in graph.session_updates:
        op, interface = operation_scope(row)
        if interface is None:
            continue
        if not reference(op, row.request) or not reference(op, row.body):
            error("session_post_roles", op.id, "request and body are independent owned Reference Uses")
        if row.binding is LifecyclePostBinding.AFTER_OPERATION:
            ordinary(op, {Behavior.CONTROL, Behavior.READ, Behavior.WRITE}, True, "session_post")
            accesses(op, set(interface.lifecycle), (row.request, row.body))
        else:
            if (op.terminator is None or op.terminator.kind is not TerminatorKind.INVOKE
                    or op.effects_complete or row.request not in op.invoke_arguments
                    or row.body not in op.invoke_arguments):
                error("session_post_invoke", op.id, "normal post requires a real unknown helper with both actual roles")
                continue
            own = {use.id: use for use in op.uses}
            domains = region_domains[interface.region]
            state_inputs = [values[own[identity].value].location for identity in op.invoke_arguments
                            if isinstance(values[own[identity].value], StateVersionValue)]
            if set(state_inputs) != domains or len(state_inputs) != len(domains):
                error("session_post_invoke_states", op.id, "helper consumes every current driver state exactly once")
            for edge in op.terminator.successors:
                produced = [values[formal].location for actual, formal in
                            zip(edge.arguments, blocks[edge.block].arguments)
                            if isinstance(values[formal], StateVersionValue)
                            and isinstance(actual, CompletionResult)]
                if set(produced) != domains or len(produced) != len(domains):
                    error("session_post_completion", op.id, "normal and raise retain every actual produced driver post-state")
            if not any(edge.kind is ExitKind.NORMAL for edge in op.terminator.successors):
                error("session_post_completion", op.id, "post attaches only to its helper's actual NORMAL successor")

    for row in graph.terminal_frame_releases:
        op, interface = operation_scope(row)
        if interface is None:
            continue
        if not reference(op, row.owner):
            error("terminal_release_owner", op.id, "release uses its owned original Reference owner")
        ordinary(op, {Behavior.READ, Behavior.WRITE, Behavior.MEMORY}, False, "terminal_release")
        accesses(op, region_domains[interface.region], (row.owner,), release=True)
    return tuple(errors)


__all__ = ["session_release_errors"]
