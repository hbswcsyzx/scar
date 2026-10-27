"""D2.4 canonical compositions; no native guard or runtime lifecycle proof."""
from dataclasses import replace

from scar.ir.program.cleanup import (
    CleanupEnter, CleanupInterface, CleanupReplace, CleanupResume,
    CleanupRouteSuccessor, CleanupRouteTerminator, HandledContextDomain,
)
from scar.ir.program.control import (
    ControlPort, ControlScope, ControlScopeKind, LanguageCompletionKind,
    PendingCompletionDefinition, PendingDispatchTerminator, PendingPayload,
    PendingSuccessor, ProtocolValueKind as P, ProtocolValueType,
)
from scar.ir.program.ids import BlockID, ControlPortID, ControlScopeID, OperationID, UseID, ValueID
from scar.ir.program.lifecycle import LifecyclePostBinding, SessionPost, SessionUpdate, TerminalFrameRelease
from scar.ir.program.model import (
    AccessMode, Behavior, Block, BlockArgument, CompletionResult, CompletionSignature,
    CompletionSuccessor, ExitKind, Footprint, FootprintKind, Operation, OperationResult,
    ProtocolValue, ReferenceValue, StateAccess, StateVersionValue, Successor,
    Terminator, TerminatorKind, Use, UseRole, ValueKind, ValueType,
)
from scar.ir.program.structured import ControlEdgeReference
from tests.fixtures.program_publication_graphs import publication_program
from tests.fixtures.program_resumption_graphs import resumption_cleanup_invoke_program
from tests.fixtures.program_session_release_graphs import _Tail


def body_cleanup_session_release_program(*, helper=False):
    """Both actual body terminal sources publish, update session and release."""
    graph = publication_program(target="value", body_graph=resumption_cleanup_invoke_program(),
                                async_request=True, extra_domain=True)
    for number, row in enumerate(graph.body_outcome_commits):
        tail = _Tail(graph, row.operation)
        if helper:
            tail.invoke(f"body-composition.helper.{number}", SessionPost.COMPLETE)
        else:
            tail.metadata(SessionPost.COMPLETE, f"body-composition.post.{number}")
        tail.release(number)
        graph = tail.finish()
    return graph


def driver_cleanup_release_program(*, helper=False):
    """Terminal body sources merge into a driver-owned active C1 cleanup.

    The optional real helper forwards private C1 values only on CFG operands.
    Its RAISE creates a new pending before an isolated Replace+JUMP block.
    """
    graph = publication_program(target="value", body_graph=resumption_cleanup_invoke_program(),
                                async_request=True, extra_domain=True)
    interface, = graph.driver_interfaces
    region = next(row for row in graph.regions if row.id == interface.region)
    values = {row.id: row for row in graph.values}
    operations = {row.id: row for row in graph.operations}
    blocks = {row.id: row for row in region.blocks}
    domains = tuple(values[value].location for value in blocks[region.entry].arguments
                    if isinstance(values[value], StateVersionValue))
    function = next(row for row in graph.control_scopes if row.region == region.id)
    protected, cleanup = ControlScopeID("composition.protected"), ControlScopeID("composition.cleanup")
    entry = BlockID("composition.entry")
    return_port, raise_port = ControlPortID("composition.return"), ControlPortID("composition.raise")
    pending_definitions, updates, releases, resumes, replacements = [], [], [], [], []
    cleanup_blocks = []

    def use(name, value):
        value = values[value]
        role = (UseRole.STATE_CONTENT if isinstance(value, StateVersionValue) else
                UseRole.REFERENCE if isinstance(value, ReferenceValue) else UseRole.PROTOCOL)
        return Use(UseID(name), value.id, role)

    def value(name, origin, kind):
        identity = ValueID(name)
        row = (StateVersionValue(identity, region.id, origin, kind) if kind in domains else
               ReferenceValue(identity, region.id, origin) if kind == "reference" else
               ProtocolValue(identity, region.id, origin, kind))
        values[identity] = row
        return identity

    def formals(name, kinds):
        identity = BlockID(name)
        return tuple(value(f"{name}.{index}", BlockArgument(identity, index), kind)
                     for index, kind in enumerate(kinds))

    def add(name, uses=(), results=(), accesses=(), *, complete=True, term=None, behaviors=(Behavior.CONTROL,), **kw):
        op = Operation(OperationID(name), name, tuple(behaviors), tuple(uses), tuple(results),
                       tuple(accesses), effects_complete=complete, terminator=term, **kw)
        operations[op.id] = op
        return op.id

    def jump(name, target, actuals):
        actual = tuple(use(f"{name}.{index}", source) for index, source in enumerate(actuals))
        return add(name, actual, term=Terminator(TerminatorKind.JUMP, (
            Successor(BlockID(target), tuple(item.id for item in actual)),)))

    def pack(name, payload, port):
        actual = use(name + ".payload", payload)
        result = value(name + ".pending", OperationResult(OperationID(name), 0), P.PENDING_COMPLETION)
        identity = add(name, (actual,), (result,))
        pending_definitions.append(PendingCompletionDefinition(result, port, actual.id))
        return identity, result

    def state_op(name, roles, current, *, complete, write_all, protocol_result=None, memory=False):
        actual = [use(f"{name}.role.{index}", item) for index, item in enumerate(roles)]
        results, accesses, after = [], [], dict(current)
        if protocol_result is not None:
            results.append(value(name + ".saved", OperationResult(OperationID(name), 0), protocol_result))
        for index, location in enumerate(domains if write_all else interface.lifecycle):
            before = use(f"{name}.before.{index}", current[location])
            actual.append(before)
            mode = AccessMode.READ_WRITE if write_all or index == 0 else AccessMode.READ
            result = None
            if mode is AccessMode.READ_WRITE:
                result = value(f"{name}.after.{index}", OperationResult(OperationID(name), len(results)), location)
                results.append(result)
                after[location] = result
            accesses.append(StateAccess(location, before.id, mode, result,
                                        Footprint(FootprintKind.WHOLE)))
        behaviors = ((Behavior.READ, Behavior.WRITE, Behavior.MEMORY) if memory else
                     (Behavior.CONTROL, Behavior.READ, Behavior.WRITE))
        identity = add(name, actual, results, accesses, complete=complete, behaviors=behaviors)
        return identity, actual, after, results

    # Exact BodyDrive private landings retain first publication, then start a
    # protected transfer. Gate rejection remains outside this protected scope.
    protected_blocks = []
    for number, commit in enumerate(graph.body_outcome_commits):
        block = next(block for block in region.blocks if commit.operation in block.operations)
        protected_blocks.append(block.id)
        marker = operations[commit.operation]
        owner = next(item.value for item in marker.uses if item.id == commit.instance)
        current = {values[item].location: item for item in block.arguments
                   if isinstance(values[item], StateVersionValue)}
        for result in marker.results:
            current[values[result].location] = result
        before_enter, actual, current, _ = state_op(f"composition.source-post.{number}",
            (interface.receiver, owner), current, complete=True, write_all=False)
        updates.append(SessionUpdate(before_enter, actual[0].id, actual[1].id,
                                     LifecyclePostBinding.AFTER_OPERATION, SessionPost.HOLD))
        source = operations[commit.outcome.source]
        port = raise_port if source.terminator.kind is TerminatorKind.RAISE else return_port
        packed, pending = pack(f"composition.source.{number}", block.arguments[0], port)
        selector = use(f"composition.route-in.{number}.selector", pending)
        forwarded = tuple(use(f"composition.route-in.{number}.{index}", source) for index, source in enumerate(
            (pending, owner, interface.receiver, *(current[location] for location in domains))))
        route = add(f"composition.route-in.{number}", (selector, *forwarded),
                    term=CleanupRouteTerminator(selector.id, (
                        CleanupRouteSuccessor(port, entry, tuple(item.id for item in forwarded)),)))
        operations.pop(block.operations[-1])
        blocks[block.id] = replace(block, operations=(commit.operation, before_enter, packed, route))

    args = formals(entry.value, (P.PENDING_COMPLETION, "reference", "reference", *domains))
    pending, owner, request = args[:3]
    current = dict(zip(domains, args[3:]))
    enter, actual, current, outputs = state_op("composition.enter", (pending,), current,
        complete=False, write_all=True, protocol_result=P.SAVED_HANDLED_CONTEXT)
    saved = outputs[0]
    post, actual, current, _ = state_op("composition.post", (request, owner), current,
                                      complete=True, write_all=False)
    updates.append(SessionUpdate(post, actual[0].id, actual[1].id,
                                 LifecyclePostBinding.AFTER_OPERATION, SessionPost.HOLD))

    def release(name, owner, current):
        identity, actual, after, _ = state_op(name, (owner,), current, complete=False,
                                            write_all=True, memory=True)
        releases.append(TerminalFrameRelease(identity, actual[0].id))
        return identity, after

    def finish_cleanup(name, block, arguments, prefix_ops, old_pending, selected, saved, current, *, replacing):
        action, actual, after, _ = state_op(name, (old_pending, selected, saved) if replacing else
                                          (old_pending, saved), current, complete=False, write_all=True)
        out = jump(name + ".jump", "composition.route", (selected, *(after[location] for location in domains)))
        continuation = ControlEdgeReference(out, 0)
        if replacing:
            replacements.append(CleanupReplace(action, cleanup, actual[0].id, actual[1].id,
                                                actual[2].id, continuation))
        else:
            resumes.append(CleanupResume(action, cleanup, actual[0].id, actual[1].id, continuation))
        blocks[block] = Block(block, arguments, (*prefix_ops, action, out))
        cleanup_blocks.append(block)

    if not helper:
        released, current = release("composition.release", owner, current)
        finish_cleanup("composition.resume", entry, args, (enter, post, released),
                       pending, pending, saved, current, replacing=False)
    else:
        name = "composition.helper"
        actual = [use(name + ".request", request), use(name + ".body", owner)]
        actual.extend(use(f"{name}.state.{index}", current[location]) for index, location in enumerate(domains))
        invoke_arguments = tuple(item.id for item in actual)
        edges = []
        path_args = {}
        for label, kind in (("normal", ExitKind.NORMAL), ("raise", ExitKind.RAISE)):
            kinds = (*((P.EXCEPTION_PACKET,) if kind is ExitKind.RAISE else ()),
                     P.PENDING_COMPLETION, P.SAVED_HANDLED_CONTEXT, "reference", "reference", *domains)
            target = BlockID(name + "." + label)
            target_args = formals(target.value, kinds)
            path_args[label] = target_args
            forwards = tuple(use(f"{name}.{label}.forward.{index}", item)
                             for index, item in enumerate((pending, saved, owner, request)))
            actual.extend(forwards)
            offset = int(kind is ExitKind.RAISE)
            edges.append(CompletionSuccessor(kind, target,
                (*((CompletionResult(0),) if offset else ()), *(item.id for item in forwards),
                 *(CompletionResult(index + offset) for index in range(len(domains))))))
        state_types = tuple(ValueType(ValueKind.STATE, location=location) for location in domains)
        call = add(name, actual, complete=False, invoke_arguments=invoke_arguments,
            completions=(CompletionSignature(ExitKind.NORMAL, state_types),
                         CompletionSignature(ExitKind.RAISE, (ProtocolValueType(P.EXCEPTION_PACKET), *state_types))),
            term=Terminator(TerminatorKind.INVOKE, tuple(edges)))
        updates.append(SessionUpdate(call, actual[0].id, actual[1].id,
                                     LifecyclePostBinding.NORMAL_COMPLETION, SessionPost.COMPLETE))
        blocks[entry] = Block(entry, args, (enter, post, call))
        cleanup_blocks.append(entry)
        normal = path_args["normal"]
        normal_current = dict(zip(domains, normal[4:]))
        released, normal_current = release("composition.release.normal", normal[2], normal_current)
        finish_cleanup("composition.resume", BlockID(name + ".normal"), normal, (released,),
                       normal[0], normal[0], normal[1], normal_current, replacing=False)
        failed = path_args["raise"]
        failed_current = dict(zip(domains, failed[5:]))
        fresh_op, fresh = pack("composition.fresh-raise", failed[0], raise_port)
        released, failed_current = release("composition.release.raise", failed[3], failed_current)
        replacement = formals("composition.replace-block", (P.PENDING_COMPLETION, P.PENDING_COMPLETION,
                                                              P.SAVED_HANDLED_CONTEXT, *domains))
        out = jump("composition.failed.jump", "composition.replace-block",
                   (failed[1], fresh, failed[2], *(failed_current[location] for location in domains)))
        failed_block = BlockID(name + ".raise")
        blocks[failed_block] = Block(failed_block, failed, (fresh_op, released, out))
        cleanup_blocks.append(failed_block)
        finish_cleanup("composition.replace", BlockID("composition.replace-block"), replacement, (),
                       replacement[0], replacement[1], replacement[2],
                       dict(zip(domains, replacement[3:])), replacing=True)

    route_args = formals("composition.route", (P.PENDING_COMPLETION, *domains))
    dispatch_args = formals("composition.dispatch", (P.PENDING_COMPLETION, *domains))
    selector = use("composition.route.selector", route_args[0])
    route_uses, edges = [selector], []
    for number, port in enumerate((return_port, raise_port)):
        forwarded = tuple(use(f"composition.route.{number}.{index}", item)
                          for index, item in enumerate(route_args))
        route_uses.extend(forwarded)
        edges.append(CleanupRouteSuccessor(port, BlockID("composition.dispatch"), tuple(item.id for item in forwarded)))
    route = add("composition.route", route_uses, term=CleanupRouteTerminator(selector.id, tuple(edges)))
    blocks[BlockID("composition.route")] = Block(BlockID("composition.route"), route_args, (route,))
    selector = use("composition.dispatch.selector", dispatch_args[0])
    dispatch_uses, edges = [selector], []
    for label, port, kind, payload_kind in (("normal", return_port, TerminatorKind.RETURN, "reference"),
                                          ("raise", raise_port, TerminatorKind.RAISE, P.EXCEPTION_PACKET)):
        target = BlockID("composition.exit." + label)
        exit_args = formals(target.value, (payload_kind, *domains))
        states = tuple(use(f"composition.dispatch.{label}.{index}", item)
                       for index, item in enumerate(dispatch_args[1:]))
        dispatch_uses.extend(states)
        edges.append(PendingSuccessor(port, target, (PendingPayload(), *(item.id for item in states))))
        exit_uses = tuple(use(f"{target.value}.out.{index}", item) for index, item in enumerate(exit_args))
        terminal = add(target.value, exit_uses, term=Terminator(kind,
            exit="normal" if label == "normal" else "failure", values=tuple(item.id for item in exit_uses)))
        blocks[target] = Block(target, exit_args, (terminal,))
    dispatch = add("composition.dispatch", dispatch_uses,
                   term=PendingDispatchTerminator(selector.id, tuple(edges)))
    blocks[BlockID("composition.dispatch")] = Block(BlockID("composition.dispatch"), dispatch_args, (dispatch,))

    direct_root = tuple(identity for identity in blocks if identity not in (*protected_blocks, *cleanup_blocks))
    scopes = tuple(replace(row, blocks=direct_root) if row.id == function.id else row
                   for row in graph.control_scopes)
    scopes = (*scopes,
        ControlScope(protected, region.id, function.id, ControlScopeKind.BLOCK, function.source, tuple(protected_blocks)),
        ControlScope(cleanup, region.id, function.id, ControlScopeKind.CLEANUP, function.source, tuple(cleanup_blocks)))
    enter_op = operations[enter]
    return replace(graph, values=tuple(values.values()), operations=tuple(operations.values()),
        regions=tuple(replace(row, blocks=tuple(blocks.values())) if row.id == region.id else row for row in graph.regions),
        control_scopes=scopes, control_ports=(*graph.control_ports,
            ControlPort(return_port, function.id, LanguageCompletionKind.RETURN, exit="normal"),
            ControlPort(raise_port, function.id, LanguageCompletionKind.RAISE, exit="failure")),
        pending_completions=(*graph.pending_completions, *pending_definitions),
        handled_context_domains=(*graph.handled_context_domains,
            HandledContextDomain(region.id, graph.handled_context_domains[0].location)),
        cleanup_interfaces=(*graph.cleanup_interfaces, CleanupInterface(cleanup, protected, entry, pending)),
        cleanup_enters=(*graph.cleanup_enters, CleanupEnter(enter, cleanup, enter_op.uses[0].id, saved)),
        cleanup_resumes=(*graph.cleanup_resumes, *resumes),
        cleanup_replacements=(*graph.cleanup_replacements, *replacements),
        session_updates=tuple(updates), terminal_frame_releases=tuple(releases))
