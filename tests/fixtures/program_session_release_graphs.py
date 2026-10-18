"""Canonical D2.3 declaration fixtures; no native/runtime predicate claims."""
from dataclasses import replace

from scar.ir.program.control import ProtocolValueKind, ProtocolValueType
from scar.ir.program.ids import BlockID, OperationID, UseID, ValueID
from scar.ir.program.lifecycle import (
    LifecyclePostBinding, SessionPost, SessionUpdate, TerminalFrameRelease,
)
from scar.ir.program.model import (
    AccessMode, Behavior, Block, BlockArgument, CompletionResult,
    CompletionSignature, CompletionSuccessor, ExitKind, Footprint, FootprintKind,
    Operation, OperationResult, ProtocolValue, StateAccess, StateVersionValue,
    Terminator, TerminatorKind, Use, UseRole, ValueKind, ValueType,
)
from tests.fixtures.program_no_body_graphs import no_body_program
from tests.fixtures.program_publication_graphs import publication_program


class _Tail:
    """Append real operations before one existing host exit, retaining state SSA."""

    def __init__(self, graph, anchor, *, body=None, request=None):
        self.graph = graph
        self.interface, = graph.driver_interfaces
        self.region = next(row for row in graph.regions if row.id == self.interface.region)
        self.blocks = {block.id: block for block in self.region.blocks}
        self.operations = {op.id: op for op in graph.operations}
        self.values = {value.id: value for value in graph.values}
        self.block = next(block for block in self.region.blocks if anchor in block.operations)
        self.active = list(self.block.operations[:-1])
        self.exit = self.operations[self.block.operations[-1]]
        self.current = {self.values[value].location: value for value in self.block.arguments
                        if isinstance(self.values[value], StateVersionValue)}
        for identity in self.active:
            for result in self.operations[identity].results:
                value = self.values[result]
                if isinstance(value, StateVersionValue):
                    self.current[value.location] = result
        self.request = self.interface.receiver if request is None else request
        marker = self.operations[anchor]
        if body is None:
            declaration = next(row for row in (*graph.body_outcome_commits, *graph.no_body_finishes)
                               if row.operation == anchor)
            body = next(use.value for use in marker.uses if use.id == declaration.instance)
        self.body = body
        self.updates, self.releases = [], []

    def _state(self, name, origin, location):
        value = StateVersionValue(ValueID(name), self.region.id, origin, location)
        self.values[value.id] = value
        return value.id

    def _add(self, operation):
        self.operations[operation.id] = operation
        self.active.append(operation.id)

    def metadata(self, post, name="session.metadata"):
        identity = OperationID(name)
        request = Use(UseID(name + ".request"), self.request, UseRole.REFERENCE)
        body = Use(UseID(name + ".body"), self.body, UseRole.REFERENCE)
        uses, accesses, results = [request, body], [], []
        for index, location in enumerate(self.interface.lifecycle):
            before = Use(UseID(f"{name}.before.{index}"), self.current[location], UseRole.STATE_CONTENT)
            uses.append(before)
            if index == 0:
                after = self._state(f"{name}.after.{index}", OperationResult(identity, len(results)), location)
                results.append(after)
                accesses.append(StateAccess(location, before.id, AccessMode.READ_WRITE, after, Footprint(FootprintKind.WHOLE)))
                self.current[location] = after
            else:
                accesses.append(StateAccess(location, before.id, AccessMode.READ, footprint=Footprint(FootprintKind.WHOLE)))
        self._add(Operation(identity, "session metadata", (Behavior.CONTROL, Behavior.READ, Behavior.WRITE),
                            tuple(uses), tuple(results), tuple(accesses), effects_complete=True))
        self.updates.append(SessionUpdate(identity, request.id, body.id, LifecyclePostBinding.AFTER_OPERATION, post))

    def invoke(self, name, post=None):
        identity = OperationID(name)
        request = Use(UseID(name + ".request"), self.request, UseRole.REFERENCE)
        body = Use(UseID(name + ".body"), self.body, UseRole.REFERENCE)
        locations = tuple(self.current)
        states = tuple(Use(UseID(f"{name}.state.{i}"), self.current[location], UseRole.STATE_CONTENT)
                       for i, location in enumerate(locations))
        normal_id, raise_id = BlockID(name + ".normal"), BlockID(name + ".raise")
        normal = tuple(self._state(f"{name}.normal.state.{i}", BlockArgument(normal_id, i), location)
                       for i, location in enumerate(locations))
        packet = ProtocolValue(ValueID(name + ".packet"), self.region.id,
                               BlockArgument(raise_id, 0), ProtocolValueKind.EXCEPTION_PACKET)
        self.values[packet.id] = packet
        raised = tuple(self._state(f"{name}.raise.state.{i}", BlockArgument(raise_id, i + 1), location)
                       for i, location in enumerate(locations))
        state_types = tuple(ValueType(ValueKind.STATE, location=location) for location in locations)
        helper = Operation(identity, "unknown helper with real completions", (Behavior.CONTROL,),
            (request, body, *states), effects_complete=False,
            invoke_arguments=(request.id, body.id, *(use.id for use in states)),
            completions=(CompletionSignature(ExitKind.NORMAL, state_types),
                         CompletionSignature(ExitKind.RAISE, (ProtocolValueType(ProtocolValueKind.EXCEPTION_PACKET), *state_types))),
            terminator=Terminator(TerminatorKind.INVOKE, (
                CompletionSuccessor(ExitKind.NORMAL, normal_id, tuple(CompletionResult(i) for i in range(len(locations)))),
                CompletionSuccessor(ExitKind.RAISE, raise_id, tuple(CompletionResult(i) for i in range(len(locations) + 1))),
            )))
        self._add(helper)
        self.blocks[self.block.id] = replace(self.block, operations=tuple(self.active))
        failure_uses = (Use(UseID(name + ".raise.packet"), packet.id, UseRole.PROTOCOL),
                        *(Use(UseID(f"{name}.raise.use.{i}"), state, UseRole.STATE_CONTENT) for i, state in enumerate(raised)))
        failure = Operation(OperationID(name + ".raise.exit"), "actual helper failure", (Behavior.CONTROL,), failure_uses,
            terminator=Terminator(TerminatorKind.RAISE, exit="failure", values=tuple(use.id for use in failure_uses)))
        self.operations[failure.id] = failure
        self.blocks[raise_id] = Block(raise_id, (packet.id, *raised), (failure.id,))
        self.block, self.active = Block(normal_id, normal, ()), []
        self.current = dict(zip(locations, normal))
        if post is not None:
            self.updates.append(SessionUpdate(identity, request.id, body.id, LifecyclePostBinding.NORMAL_COMPLETION, post))

    def release(self, index):
        name = f"session.release.{index}"
        identity = OperationID(name)
        owner = Use(UseID(name + ".owner"), self.body, UseRole.REFERENCE)
        uses, accesses, results = [owner], [], []
        for index, location in enumerate(self.current):
            before = Use(UseID(f"{name}.before.{index}"), self.current[location], UseRole.STATE_CONTENT)
            after = self._state(f"{name}.after.{index}", OperationResult(identity, index), location)
            uses.append(before)
            results.append(after)
            accesses.append(StateAccess(location, before.id, AccessMode.READ_WRITE, after, Footprint(FootprintKind.WHOLE)))
            self.current[location] = after
        self._add(Operation(identity, "conditional terminal frame reference release",
            (Behavior.READ, Behavior.WRITE, Behavior.MEMORY), tuple(uses), tuple(results),
            tuple(accesses), effects_complete=False))
        self.releases.append(TerminalFrameRelease(identity, owner.id))

    def finish(self):
        terminal = replace(self.exit, uses=tuple(
            replace(use, value=self.current[self.values[use.value].location])
            if isinstance(self.values[use.value], StateVersionValue) else use for use in self.exit.uses))
        self.operations[terminal.id] = terminal
        self.blocks[self.block.id] = replace(self.block, operations=(*self.active, terminal.id))
        region = replace(self.region, blocks=tuple(self.blocks.values()))
        scopes = tuple(replace(scope, blocks=(*scope.blocks,
            *(block.id for block in region.blocks if block.id not in scope.blocks)))
            if scope.region == region.id else scope for scope in self.graph.control_scopes)
        return replace(self.graph,
            regions=tuple(region if row.id == region.id else row for row in self.graph.regions),
            operations=tuple(self.operations.values()), values=tuple(self.values.values()), control_scopes=scopes,
            session_updates=(*self.graph.session_updates, *self.updates),
            terminal_frame_releases=(*self.graph.terminal_frame_releases, *self.releases))


def session_release_program(binding="AFTER_OPERATION", post="COMPLETE", source="return",
                            release=True, repeat_release=False, callback=False,
                            strict_subset=False, extra_domain=False):
    binding, post = LifecyclePostBinding(binding), SessionPost(post)
    if source == "no-body":
        graph = no_body_program(receiver="ASYNC_REQUEST", target="value", strict_subset=strict_subset,
                                extra_domain=extra_domain)
        anchor = graph.no_body_finishes[0].operation
    else:
        graph = publication_program(target={"return": "value", "raise": "packet", "suspend": "start"}[source],
            async_request=True, strict_subset=strict_subset, extra_domain=extra_domain)
        anchor = graph.body_outcome_commits[0].operation
    tail = _Tail(graph, anchor)
    if binding is LifecyclePostBinding.AFTER_OPERATION:
        tail.metadata(post)
    else:
        tail.invoke("session.helper", post)
    if callback:
        tail.invoke("session.callback")
    if release:
        tail.release(0)
        if repeat_release:
            tail.release(1)
    return tail.finish()


__all__ = ["session_release_program"]
