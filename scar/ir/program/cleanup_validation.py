"""Derive and check cleanup connections on the canonical CFG and state SSA.

This validates declarations, not Python source recovery or runtime unwinding.
No alternate producer, state snapshot or caller-supplied reachability is stored.
"""
from dataclasses import dataclass
from enum import Enum

from .cleanup import CleanupEnter, CleanupReplace, CleanupResume, CleanupRouteTerminator
from .cleanup_forward import derive_cleanup_forward
from .control import ControlScopeKind, PendingDispatchTerminator, ProtocolValueKind as P
from .control_validation import derive_pending_facts
from .ids import BlockID, ControlPortID, ControlScopeID
from .model import (
    AccessMode, Behavior, BlockArgument, FootprintKind, OperationResult,
    ProtocolValue, ReferenceValue, StateVersionValue, TerminatorKind,
)
from .resumption import SavedRole, SuspendTerminator, saved_actual_use


class CleanupRouteKind(str, Enum):
    ENTER = "ENTER"
    REPLACE = "REPLACE"
    FINAL_DISPATCH = "FINAL_DISPATCH"


@dataclass(frozen=True, slots=True)
class CleanupRouteStep:
    port: ControlPortID
    kind: CleanupRouteKind
    cleanup: ControlScopeID | None
    target: BlockID


@dataclass(frozen=True, slots=True)
class CleanupFacts:
    """Derived indexes only, valid for this immutable graph representation."""

    stacks: dict
    forward: dict
    routes: dict


def analyze_cleanup(graph, *, operation_blocks, dominators):
    """Run after core and C0 checks, returning issues and derived query facts."""
    issues = []
    empty = CleanupFacts({}, {}, {})
    domains = {row.region: row for row in graph.handled_context_domains}
    interfaces = {row.scope: row for row in graph.cleanup_interfaces}
    actions = {row.operation: row for rows in (
        graph.cleanup_enters, graph.cleanup_resumes, graph.cleanup_replacements,
        graph.handled_context_reads) for row in rows}
    routes = {op.id: op for op in graph.operations
              if isinstance(op.terminator, CleanupRouteTerminator)}
    saved = {v.id for v in graph.values
             if isinstance(v, ProtocolValue) and v.protocol is P.SAVED_HANDLED_CONTEXT}
    if not (domains or interfaces or actions or routes or saved):
        return [], empty
    regions = {row.id: row for row in graph.regions}
    scopes = {row.id: row for row in graph.control_scopes}
    blocks = {b.id: b for r in graph.regions for b in r.blocks}
    block_region = {b.id: r.id for r in graph.regions for b in r.blocks}
    owners = {b: s.id for s in graph.control_scopes for b in s.blocks}
    operations = {row.id: row for row in graph.operations}
    values = {row.id: row for row in graph.values}
    ports = {row.id: row for row in graph.control_ports}
    pending = derive_pending_facts(graph)
    uses = {use.id: use for op in graph.operations for use in op.uses}

    def error(code, path, message):
        issues.append((code, path, message))

    def ancestor(outer, inner):
        while inner is not None:
            if outer == inner:
                return True
            inner = scopes[inner].parent
        return False

    def chain(inner):
        while inner is not None:
            yield inner
            inner = scopes[inner].parent

    def protocol(identity, kind):
        value = values.get(identity)
        return isinstance(value, ProtocolValue) and value.protocol is kind

    state_domains = {r.id: {values[v].location for v in blocks[r.entry].arguments
                            if isinstance(values[v], StateVersionValue)} for r in graph.regions}
    for domain in domains.values():
        if domain.region not in regions or domain.location not in state_domains[domain.region]:
            error("cleanup_context_domain", domain.region, "context needs an existing carried state location")
        if not any(s.region == domain.region for s in scopes.values()):
            error("cleanup_context_scope", domain.region, "enabled region needs lexical control ownership")
    protected = {}
    for interface in interfaces.values():
        scope, body = scopes.get(interface.scope), scopes.get(interface.protected)
        if (scope is None or body is None or scope.kind is not ControlScopeKind.CLEANUP
                or body.kind is not ControlScopeKind.BLOCK or scope.region != body.region
                or scope.parent != body.parent or scope.region not in domains):
            error("cleanup_interface_scope", interface.scope, "cleanup and protected BLOCK must be siblings in an enabled region")
            continue
        if interface.protected in protected:
            error("cleanup_protected_owner", interface.protected, "a protected scope has one cleanup")
        protected[interface.protected] = interface
        entry = blocks.get(interface.entry)
        if (entry is None or owners.get(interface.entry) != interface.scope
                or interface.pending_argument not in entry.arguments
                or not protocol(interface.pending_argument, P.PENDING_COMPLETION)):
            error("cleanup_entry", interface.scope, "entry must be directly owned and carry its actual pending argument")
    for scope in scopes.values():
        if scope.region in domains and scope.kind is ControlScopeKind.CLEANUP and scope.id not in interfaces:
            error("cleanup_interface_missing", scope.id, "every enabled cleanup needs an interface")
    for identity in saved:
        if values[identity].region not in domains:
            error("cleanup_saved_region", identity, "saved context needs an enabled region")
    for operation in routes.values():
        if block_region[operation_blocks[operation.id]] not in domains:
            error("cleanup_route_region", operation.id, "route needs an enabled region")
    for region in graph.regions:
        signatures = [p.types for p in region.exits]
        signatures += [s.types for op in graph.operations
                       if block_region[operation_blocks[op.id]] == region.id for s in op.completions]
        if any(getattr(t, "protocol", None) is P.SAVED_HANDLED_CONTEXT
               for signature in signatures for t in signature):
            error("cleanup_context_escape", region.id, "private saved context cannot be an external completion payload")
        if any(v in saved for v in blocks[region.entry].arguments):
            error("cleanup_context_escape", region.entry, "private context is not a region input")
    if issues:
        return issues, empty

    enters = {}
    exits = {}
    for action in actions.values():
        operation = operations.get(action.operation)
        if operation is None:
            error("cleanup_action_operation", action.operation, "action needs an existing canonical operation")
            continue
        region_id = block_region[operation_blocks[operation.id]]
        if region_id not in domains:
            error("cleanup_action_region", operation.id, "action needs an enabled region")
            continue
        if operation.terminator is not None or operation.callee is not None:
            error("cleanup_action_kind", operation.id, "cleanup primitives are ordinary non-call operations")
        own = {u.id: u for u in operation.uses}
        if isinstance(action, (CleanupEnter, CleanupResume, CleanupReplace)):
            interface = interfaces.get(action.cleanup)
            if interface is None or scopes[action.cleanup].region != region_id:
                error("cleanup_action_scope", operation.id, "action needs its same-region cleanup interface")
                continue
            if owners[operation_blocks[operation.id]] != action.cleanup:
                error("cleanup_action_scope", operation.id, "entry/exit primitives are directly owned by their cleanup")
            if (operation.effects_complete or set(operation.behaviors) != {
                    Behavior.CONTROL, Behavior.READ, Behavior.WRITE}):
                error("cleanup_action_effects", operation.id, "cleanup primitives preserve unknown callback effects")
            accesses = operation.accesses
            if ({a.location for a in accesses} != state_domains[region_id]
                    or len(accesses) != len(state_domains[region_id]) or any(
                    a.mode is not AccessMode.READ_WRITE or a.full_overwrite
                    or a.footprint.kind is not FootprintKind.WHOLE or a.reference is not None
                    for a in accesses)):
                error("cleanup_action_state", operation.id, "cleanup needs a WHOLE read/write post-state for every carried domain")
            protocol_operands = ({action.pending} if isinstance(action, CleanupEnter)
                                 else {action.pending, action.context} if isinstance(action, CleanupResume)
                                 else {action.saved_pending, action.replacement, action.context})
            if (len(protocol_operands) != (1 if isinstance(action, CleanupEnter) else
                                          2 if isinstance(action, CleanupResume) else 3)
                    or set(own) != protocol_operands | {a.before for a in accesses}):
                error("cleanup_action_operands", operation.id, "primitive has exact distinct protocol and current-state Uses")
            pending_uses = ([action.pending] if isinstance(action, (CleanupEnter, CleanupResume))
                            else [action.saved_pending, action.replacement])
            if any(uid not in own or not protocol(own[uid].value, P.PENDING_COMPLETION) for uid in pending_uses):
                error("cleanup_action_pending", operation.id, "pending operands need owned pending Uses")
            results = {a.after for a in accesses}
            if isinstance(action, CleanupEnter):
                if action.cleanup in enters:
                    error("cleanup_enter_unique", action.cleanup, "each cleanup has one static Enter")
                enters[action.cleanup] = action
                results.add(action.saved_context)
                value = values.get(action.saved_context)
                if (not protocol(action.saved_context, P.SAVED_HANDLED_CONTEXT)
                        or not isinstance(value.origin, OperationResult)
                        or value.origin.operation != operation.id):
                    error("cleanup_saved_result", operation.id, "Enter produces its own saved-context result")
                if (blocks[interface.entry].operations[0] != operation.id
                        or action.pending not in own
                        or own[action.pending].value != interface.pending_argument):
                    error("cleanup_enter_binding", operation.id, "Enter is first and reads the interface entry's original pending argument")
            else:
                exits[operation.id] = action
                if action.context not in own or not protocol(own[action.context].value, P.SAVED_HANDLED_CONTEXT):
                    error("cleanup_action_context", operation.id, "restore needs an owned saved-context Use")
            if set(operation.results) != results:
                error("cleanup_action_results", operation.id, "primitive only produces its declared state and saved context")
        else:
            # An abstract read primitive; source/runtime interposition is unproved.
            result = values.get(action.exception_result)
            if (not operation.effects_complete or set(operation.behaviors) != {Behavior.CONTROL, Behavior.READ}
                    or len(operation.accesses) != 1 or operation.results != (action.exception_result,)
                    or not isinstance(result, ReferenceValue) or not isinstance(result.origin, OperationResult)
                    or result.origin.operation != operation.id or result.targets is not None
                    or result.referent_identity is not None or result.selector.kind is not FootprintKind.UNKNOWN):
                error("cleanup_context_read", operation.id, "abstract context read has one unrefined reference result")
            if (len(operation.accesses) != 1 or any(
                    a.location != domains[region_id].location or a.mode is not AccessMode.READ
                    or a.reference is not None for a in operation.accesses)
                    or set(own) != {a.before for a in operation.accesses}):
                error("cleanup_context_read_state", operation.id, "context read only consumes the current context domain")
    if set(enters) != set(interfaces):
        error("cleanup_enter_missing", "cleanup_interfaces", "every interface needs exactly one canonical Enter")
    if issues:
        return issues, empty

    # Exit corridors refer to the actual final edge, never an independent target.
    for action in exits.values():
        block = blocks[operation_blocks[action.operation]]
        final = operations[block.operations[-1]]
        term = final.terminator
        scope = scopes[action.cleanup]
        if (len(block.operations) < 2 or block.operations[-2] != action.operation
                or term.kind is not TerminatorKind.JUMP
                or action.continuation.operation != final.id or action.continuation.successor_index != 0):
            error("cleanup_continuation", action.operation, "exit immediately precedes its exact final JUMP edge")
            continue
        if isinstance(action, CleanupReplace) and block.operations != (action.operation, final.id):
            error("cleanup_replace_block", action.operation, "Replace is the first operation followed by its JUMP")
        edge = term.successors[0]
        target = blocks[edge.block]
        route = operations[target.operations[-1]]
        if (owners[target.id] != scope.parent or len(target.operations) != 1
                or not isinstance(route.terminator, CleanupRouteTerminator)):
            error("cleanup_corridor", action.operation, "post-pop target is a route-only block directly in the parent scope")
            continue
        route_value = uses[route.terminator.pending].value
        if route_value not in target.arguments:
            error("cleanup_corridor_selector", action.operation, "corridor selector is an actual target argument")
            continue
        actual = edge.arguments[target.arguments.index(route_value)]
        selected = action.replacement if isinstance(action, CleanupReplace) else action.pending
        if uses[actual].value != uses[selected].value:
            error("cleanup_corridor_pending", action.operation, "exit must forward the exact selected pending value")
    if issues:
        return issues, empty

    # Operation-point LIFO, derived over every canonical edge (including INVOKE).
    stacks, after = {}, {}
    for region in graph.regions:
        if region.id not in domains:
            continue
        stacks[region.entry] = ()
        queue = [region.entry]
        while queue:
            block_id = queue.pop()
            current = stacks[block_id]
            lexical = tuple(reversed([s for s in chain(owners[block_id]) if s in interfaces]))
            starting = next((s for s in lexical if interfaces[s].entry == block_id), None)
            expected = lexical[:-1] if starting is not None else lexical
            if current != expected:
                error("cleanup_stack_entry", block_id, "entry stack must match active lexical cleanup ancestors")
            for op_id in blocks[block_id].operations:
                action = actions.get(op_id)
                if isinstance(action, CleanupEnter):
                    if action.cleanup in current:
                        error("cleanup_stack_reentry", op_id, "cannot reenter an active cleanup")
                    current = (*current, action.cleanup)
                elif isinstance(action, (CleanupResume, CleanupReplace)):
                    if not current or current[-1] != action.cleanup:
                        error("cleanup_stack_lifo", op_id, "exit must pop the current innermost cleanup")
                    else:
                        current = current[:-1]
            after[block_id] = current
            term = operations[blocks[block_id].operations[-1]].terminator
            for edge in term.successors:
                if edge.block not in stacks:
                    stacks[edge.block] = current
                    queue.append(edge.block)
                elif stacks[edge.block] != current:
                    error("cleanup_stack_merge", edge.block, "incoming paths disagree on active cleanup stack")
            if term.kind in (TerminatorKind.RETURN, TerminatorKind.RAISE) and (
                    current or any(s in protected for s in chain(owners[block_id]))):
                error("cleanup_exit_bypass", block_id, "terminal exit bypasses a pending cleanup obligation")
    if issues:
        return issues, empty

    # Compute each route's next obligation from lexical ownership and current stack.
    steps = {}
    for operation in routes.values():
        source = operation_blocks[operation.id]
        term = operation.terminator
        selected = uses[term.pending].value
        route_steps = []
        for edge in term.successors:
            port = ports[edge.port]
            target_scope = owners[port.block] if port.block is not None else None
            required, cleanup = CleanupRouteKind.FINAL_DISPATCH, None
            for scope in chain(owners[source]):
                outside = target_scope is None or not ancestor(scope, target_scope)
                if not outside:
                    continue
                if scope in protected:
                    required, cleanup = CleanupRouteKind.ENTER, protected[scope].scope
                    break
                if scope in after[source]:
                    required, cleanup = CleanupRouteKind.REPLACE, scope
                    break
            target = blocks[edge.block]
            first = operations[target.operations[0]]
            target_action = actions.get(first.id)
            formal = None
            if required is CleanupRouteKind.ENTER:
                interface = interfaces[cleanup]
                if edge.block != interface.entry:
                    error("cleanup_route_next", operation.id, "next obligation must enter the innermost exited protected scope's cleanup")
                formal = interface.pending_argument
            elif required is CleanupRouteKind.REPLACE:
                if not isinstance(target_action, CleanupReplace) or target_action.cleanup != cleanup:
                    error("cleanup_route_next", operation.id, "new transfer must replace the active outer cleanup's saved transfer")
                else:
                    formal = uses[target_action.replacement].value
            else:
                if len(target.operations) != 1 or not isinstance(first.terminator, PendingDispatchTerminator):
                    error("cleanup_route_final", operation.id, "completed obligations go to a final C0 dispatch-only block")
                else:
                    formal = uses[first.terminator.pending].value
            if formal is not None:
                if formal not in target.arguments:
                    error("cleanup_route_selector", operation.id, "next-step pending selector must be a target block parameter")
                elif uses[edge.arguments[target.arguments.index(formal)]].value != selected:
                    error("cleanup_route_pending", operation.id, "route forwards its exact selected pending, without repacking")
            route_steps.append(CleanupRouteStep(edge.port, required, cleanup, edge.block))
        steps[operation.id] = tuple(route_steps)

    # No physical detour may leave protection or side-enter an enabled cleanup.
    for operation in graph.operations:
        source = operation_blocks[operation.id]
        if block_region[source] not in domains or operation.terminator is None:
            continue
        for edge in operation.terminator.successors:
            exited = next((s for s in chain(owners[source])
                           if s in protected and not ancestor(s, owners[edge.block])), None)
            if exited is not None and (
                    not isinstance(operation.terminator, CleanupRouteTerminator)
                    or edge.block != protected[exited].entry):
                error("cleanup_protected_bypass", operation.id, "every physical exit from protection first enters its cleanup via a route")
            entering = next((s for s, interface in interfaces.items() if interface.entry == edge.block), None)
            if entering is not None and (
                    not isinstance(operation.terminator, CleanupRouteTerminator)
                    or not any(step.kind is CleanupRouteKind.ENTER and step.cleanup == entering
                               and step.target == edge.block for step in steps.get(operation.id, ()))):
                error("cleanup_entry_edge", operation.id, "cleanup entry only accepts a derived Enter route")
    if issues:
        return issues, empty

    forward = {}
    for scope, interface in interfaces.items():
        subtree = frozenset(b for b, owner in owners.items() if ancestor(scope, owner))
        forward[scope] = derive_cleanup_forward(
            graph, interface, scope_blocks=subtree,
            operation_blocks=operation_blocks, dominators=dominators)
    for action in exits.values():
        facts = forward[action.cleanup]
        original = action.saved_pending if isinstance(action, CleanupReplace) else action.pending
        if uses[original].value not in facts.pending:
            error("cleanup_pending_forward", action.operation, "exit must consume this entry's original pending, not an equal port or repack")
        if uses[action.context].value not in facts.context:
            error("cleanup_context_forward", action.operation, "restore must consume this activation's saved context")
        if isinstance(action, CleanupReplace):
            replacement = uses[action.replacement].value
            if replacement not in facts.fresh:
                error("cleanup_replacement_fresh", action.operation, "replacement must be freshly constructed after this entry on all incoming paths")
            for port_id in pending[replacement].ports:
                port = ports[port_id]
                if port.block is not None and ancestor(action.cleanup, owners[port.block]):
                    error("cleanup_replacement_target", action.operation, "replacement must leave its cleanup subtree")

    # Context is private protocol state. Passing it as ordinary call/exit data is
    # forbidden even if the target value's static protocol type happens to match.
    for operation in graph.operations:
        action = actions.get(operation.id)
        term = operation.terminator
        for use in operation.uses:
            if use.value not in saved:
                continue
            if isinstance(action, (CleanupResume, CleanupReplace)) and use.id == action.context:
                continue
            targets = [formal for edge in (term.successors if term is not None else ())
                       for actual, formal in zip(edge.arguments, blocks[edge.block].arguments)
                       if saved_actual_use(operation, actual) == use.id]
            owning = [scope for scope, facts in forward.items() if use.value in facts.context]
            retained = False
            invalid_save = False
            if isinstance(term, SuspendTerminator):
                slots = [slot for slot in term.saved if slot.use == use.id]
                retained = bool(slots) and all(slot.role is SavedRole.CLEANUP_CONTEXT for slot in slots)
                source = operation_blocks[operation.id]
                retained &= any(scope in after[source] and ancestor(scope, owners[source])
                                for scope in owning)
                invalid_save = bool(slots) and not retained
            if (invalid_save or not (targets or retained)
                    or use.id in (*operation.call_arguments, *operation.invoke_arguments)
                    or not owning or any(not any(
                        ancestor(scope, owners[values[formal].origin.block]) for scope in owning)
                        for formal in targets)):
                error("cleanup_context_escape", use.id,
                      "saved context only forwards, restores, or privately saves within its owning active cleanup")
    if not issues:
        # A logical Return/Raise target can be intercepted by cleanup which
        # diverges or replaces that transfer. Such an exit is a declared
        # potential target, not an invented completion occurrence. Only the
        # exact interface pending argument supplies support: unrelated packs
        # and extra entry operands cannot legalize an unused exit signature.
        captured = {region: set() for region in domains}
        for scope, interface in interfaces.items():
            fact = pending[interface.pending_argument]
            region = scopes[scope].region
            if fact.complete:
                captured[region].update(ports[p].exit for p in fact.ports
                                        if ports[p].exit is not None
                                        and scopes[ports[p].scope].region == region)
        for region in graph.regions:
            if region.id not in domains:
                continue
            actual = {op.terminator.exit for op in graph.operations
                      if op.terminator is not None
                      and block_region[operation_blocks[op.id]] == region.id
                      and op.terminator.exit is not None}
            if {port.name for port in region.exits} - actual - captured[region.id]:
                error("unbound_exit", region.id,
                      "an exit needs an actual terminal site or a target captured by this region's cleanup entry")
    return issues, CleanupFacts(stacks, forward, steps)


def cleanup_errors(graph, *, operation_blocks, dominators):
    return analyze_cleanup(graph, operation_blocks=operation_blocks, dominators=dominators)[0]


__all__ = ["CleanupFacts", "CleanupRouteKind", "CleanupRouteStep", "analyze_cleanup", "cleanup_errors"]
