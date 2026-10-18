"""Original protocol ports and evaluation-relative copies, never a second IR.

Call after canonical CFG/SSA validation.  A producer re-execution invalidates
copies of its previous result, even when both evaluations share a ValueID.
Native/source applicability and runtime instance correspondence stay separate.
"""
from collections import deque
from dataclasses import dataclass

from .drivers import BodyDriveResult
from .driver_flow import body_outcome_uses
from .model import (BlockArgument, CompletionResult, CompletionSuccessor,
                    InvokeLiteralResult, OperationResult, StateVersionValue,
                    TerminatorKind)
from .protocols import (ContractResult, DriveResult, HostTerminal, NativeExit,
                        OwnedUse, StaticProtocolGap)
from .resumption import saved_actual_use


@dataclass(frozen=True, slots=True)
class ProtocolPort:
    source: object
    operation: object
    values: tuple
    phase: str
    edge: int | None = None
    body_use: object = None
    gap: object = None
    # Query-local union of exact completion copies from one call evaluation.
    # These reference original landing ValueIDs, never new graph producers.
    completion_values: tuple = ()


class ProtocolReferenceError(ValueError):
    """An exact contract-result foreign key or owned-result contradiction."""


class ProtocolFlow:
    """One immutable-model query context with shared indexes/cache/budget."""

    def __init__(self, graph, *, budget=None):
        self.graph, self.budget = graph, budget
        self.operations = {row.id: row for row in graph.operations}
        self.values = {row.id: row for row in graph.values}
        self.regions = {row.id: row for row in graph.regions}
        self.blocks, self.region_of, self.block_of, self.positions = {}, {}, {}, {}
        self.uses = {}
        for region in graph.regions:
            for block in region.blocks:
                self.blocks[block.id] = block
                for number, identity in enumerate(block.operations):
                    self.region_of[identity] = region.id
                    self.block_of[identity], self.positions[identity] = block.id, number
        for operation in graph.operations:
            for use in operation.uses:
                self.uses[use.id] = operation.id, use
        self.scopes = {row.id: row for row in graph.protocol_scopes}
        self.rows = {(row.scope, row.clause, row.operation, row.slot): row
                     for row in graph.protocol_operations}
        self.rows_by_clause = {}
        for row in graph.protocol_operations:
            self.rows_by_clause.setdefault((row.scope, row.clause), []).append(row)
        self.drives = {row.operation: row for row in graph.body_drives}
        self.gates = {row.operation: row for row in graph.final_body_gates}
        self.interfaces = {row.region: row for row in graph.driver_interfaces}
        self.bodies = {row.region: row for row in graph.resumable_bodies}
        self._driver_roles = {}
        self.drives_by_region = {}
        for row in graph.body_drives:
            self.drives_by_region.setdefault(self.region_of[row.operation], []).append(row)
        self.raw = {row.value: row for row in graph.raw_driver_requests}
        self.packets = {row.value: row for row in graph.exception_packets}
        self.boundaries = {row.id: row for row in graph.native_boundaries}
        self._ports, self._flows, self._region_edges, self._universes = {}, {}, {}, {}
        self._reachability = {}
        for value in graph.values:
            self._universes.setdefault(value.region, set()).add(value.id)
        self._universes = {key: frozenset(values) for key, values in self._universes.items()}
        self.preparation = {"operations": len(self.operations), "values": len(self.values),
                            "uses": len(self.uses), "blocks": len(self.blocks),
                            "protocol_rows": len(self.rows), "final_body_gates": len(self.gates)}

    def spend(self, kind, cost=1):
        return self.budget is None or self.budget.spend(kind, cost, "protocol." + kind)

    def owned_use(self, operation, identity):
        found = self.uses.get(identity)
        if found is None or found[0] != operation:
            raise ValueError("protocol Use must be owned by the exact operation")
        return found[1]

    def selected_edges(self, guard=None, *, region=None):
        """Exact temporary CFG choices, not a new graph or dynamic visit ID."""
        from .structured import ControlEdgeReference
        edges = () if guard is None else guard if type(guard) is tuple else (guard,)
        selected = {}
        for edge in edges:
            if type(edge) is not ControlEdgeReference:
                raise TypeError("selected edges require exact ControlEdgeReference records")
            edge.__post_init__()
            operation = self.operations.get(edge.operation)
            if (operation is None or operation.terminator is None or
                    edge.successor_index >= len(operation.terminator.successors)):
                raise ValueError("selected edge must exist in the original CFG")
            if edge.operation in selected and selected[edge.operation] != edge:
                raise ValueError("one static operation cannot select two different successors")
            selected[edge.operation] = edge
        return tuple(sorted((edge for edge in selected.values() if region is None
                    or self.region_of[edge.operation] == region),
                    key=lambda edge: (edge.operation.wire, edge.successor_index)))

    def selection_ambiguity(self, guard=None):
        """Different visits to one merge are not one static selection."""
        targets = {}
        for edge in self.selected_edges(guard):
            block = self.operations[edge.operation].terminator.successors[edge.successor_index].block
            if block in targets and targets[block] != edge:
                return {"code": "selected_merge_visits_require_occurrence_context",
                        "merge": block, "edges": (targets[block], edge)}
            targets[block] = edge
        return None

    def driver_roles(self, region):
        """Prepared must-copy roles, not object identity or a second state graph."""
        if region not in self._driver_roles:
            from .driver_flow import driver_role_copies
            self._driver_roles[region] = tuple(frozenset(items) for items in
                driver_role_copies(self.graph, self.interfaces[region]))
            self.preparation['driver_role_copy_analyses'] = len(self._driver_roles)
        return self._driver_roles[region]

    def row_result(self, row):
        from .protocols import AdmissionPredicate, OutcomeAdapter, ProtocolCall, RequestProcessing
        if type(row.contract) in (AdmissionPredicate, RequestProcessing, ProtocolCall):
            return row.contract.result
        if type(row.contract) is OutcomeAdapter and type(row.contract.output) in (
                OperationResult, InvokeLiteralResult, StaticProtocolGap):
            return row.contract.output
        raise ProtocolReferenceError("referenced contract has no own produced result port")

    def port(self, source, *, referring=None):
        if not self.spend("ports"):
            return None
        if type(source) is StaticProtocolGap:
            return ProtocolPort(source, None, (), "missing", gap=source)
        if type(source) is ContractResult:
            key = source.scope, source.clause, source.operation, source.slot
            row = self.rows.get(key)
            if row is None or row is referring:
                raise ProtocolReferenceError("ContractResult must name another existing required row")
            if self.row_result(row) != source.result_port:
                raise ProtocolReferenceError("ContractResult must select that row's own exact result")
            return self.port(source.result_port)
        if source in self._ports:
            return self._ports[source]
        operation = None
        if type(source) is OwnedUse:
            use = self.owned_use(source.operation, source.use)
            result = ProtocolPort(source, source.operation, (use.value,), "before")
        elif type(source) is OperationResult:
            operation = self.operations.get(source.operation)
            if operation is None or source.index >= len(operation.results):
                raise ValueError("protocol ordinary result does not exist")
            identity = operation.results[source.index]
            if self.values[identity].origin != source:
                raise ValueError("protocol result has a different original producer")
            result = ProtocolPort(source, operation.id, (identity,), "after")
        elif type(source) is InvokeLiteralResult:
            operation = self.operations.get(source.edge.operation)
            if (operation is None or operation.terminator is None
                    or operation.terminator.kind is not TerminatorKind.INVOKE):
                raise ValueError("protocol completion requires its original INVOKE")
            number = source.edge.successor_index
            if number >= len(operation.terminator.successors):
                raise ValueError("protocol completion edge does not exist")
            edge = operation.terminator.successors[number]
            signature = next((item for item in operation.completions if item.kind is edge.kind), None)
            if signature is None or source.result.index >= len(signature.types):
                raise ValueError("protocol completion result exceeds the selected signature")
            values = tuple(formal for actual, formal in zip(
                edge.arguments, self.blocks[edge.block].arguments)
                if type(actual) is CompletionResult and actual.index == source.result.index)
            result = ProtocolPort(source, operation.id, values, "edge", number)
        elif type(source) is DriveResult:
            operation = self.operations.get(source.outcome.drive)
            body = self.operations.get(source.outcome.source)
            if operation is None or operation.id not in self.drives or body is None:
                raise ValueError("DriveResult must select an existing BodyDrive/source")
            matches = [(i, edge) for i, edge in enumerate(operation.terminator.successors)
                       if edge.source == body.id]
            if len(matches) != 1:
                raise ValueError("DriveResult source is not one selected drive successor")
            number, edge = matches[0]
            outputs = body_outcome_uses(body)
            if source.index >= len(outputs):
                raise ValueError("DriveResult index exceeds this exact body source")
            values = tuple(formal for actual, formal in zip(
                edge.arguments, self.blocks[edge.block].arguments)
                if type(actual) is BodyDriveResult and actual.index == source.index)
            result = ProtocolPort(source, operation.id, values, "edge", number,
                                  OwnedUse(body.id, outputs[source.index]))
        elif type(source) is HostTerminal:
            operation = self.operations.get(source.operation)
            if (operation is None or operation.terminator is None
                    or operation.terminator.kind not in (TerminatorKind.RETURN, TerminatorKind.RAISE)):
                raise ValueError("host terminal must be an original RETURN or RAISE")
            values = tuple(self.owned_use(operation.id, identity).value
                           for identity in operation.terminator.values)
            result = ProtocolPort(source, operation.id, values, "before")
        elif type(source) is NativeExit:
            boundary = self.boundaries.get(source.boundary)
            region = self.regions.get(source.port.region)
            if boundary is None or region is None or boundary.region != region.id:
                raise ValueError("native exit must belong to its original boundary")
            exit_ = next((item for item in region.exits if item.name == source.port.exit_name), None)
            if exit_ is None or source.port.index >= len(exit_.types):
                raise ValueError("native exit does not name an original result slot")
            result = ProtocolPort(source, None, (), "native", gap="native_route_unproved")
        else:
            raise TypeError("protocol port requires an exact original port reference")
        self._ports[source] = result
        return result

    def _edges(self, region):
        if region in self._region_edges:
            return self._region_edges[region]
        declaration = self.regions[region]
        outgoing = {block.id: [] for block in declaration.blocks}
        incoming = {block.id: [] for block in declaration.blocks}
        for block in declaration.blocks:
            operation = self.operations[block.operations[-1]]
            for number, edge in enumerate(operation.terminator.successors):
                # Reuse canonical original transfers; a ResumeInput is non-copy.
                assignments = {formal: self.owned_use(operation.id, identity).value
                               if (identity := saved_actual_use(operation, actual)) is not None else None
                               for actual, formal in zip(edge.arguments, self.blocks[edge.block].arguments)}
                item = operation.id, number, edge.block, assignments
                outgoing[block.id].append(item)
                incoming[edge.block].append((block.id, item))
        # Schedule from original CFG successor order, never hash iteration or
        # declaration-table order. Iterative DFS also supports deep/cyclic CFGs
        # without using Python's recursion limit. All original parallel edges
        # stay in outgoing/incoming; only DFS visits are deduplicated.
        reached, postorder = {declaration.entry}, []
        pending = [(declaration.entry, iter(outgoing[declaration.entry]))]
        while pending:
            block, successors = pending[-1]
            edge = next(successors, None)
            if edge is None:
                postorder.append(block)
                pending.pop()
            elif edge[2] not in reached:
                reached.add(edge[2])
                pending.append((edge[2], iter(outgoing[edge[2]])))
        order = tuple(reversed(postorder))
        result = declaration, outgoing, incoming, frozenset(reached), order
        self._region_edges[region] = result
        return result

    def _copy_context_key(self):
        """Optional query context; the historical local engine has none."""
        return ()

    def _copy_call_transfer(self, operation, current, *, mode):
        """Optional known-callee copy projection, never a new producer.

        The default engine retains its historical local-only behavior. None
        means unresolved, rather than an empty set of proved non-copies.
        """
        return frozenset(), {}

    def _fresh_copies(self, port, *, guard=None, mode="must"):
        """Finite copy analysis over original CFG, reset at each evaluation.

        Only transient sets of original ValueIDs are derived. Parallel edge
        renaming uses the pre-edge set. Unreachable predecessors never create
        facts. The default must mode requires every reachable incoming
        alternative; may mode unions possibilities for consumer inventory.
        """
        key = port.operation, port.phase, port.edge, port.values
        if port.completion_values:
            key = (*key, port.completion_values)
        context_key = self._copy_context_key()
        if context_key:
            key = (*key, context_key)
        if mode not in ("must", "may"):
            raise ValueError("copy query mode must be must or may")
        if mode == "may":
            key = (*key, "may")
        guards = self.selected_edges(guard)
        if self.selection_ambiguity(guards) is not None:
            return None
        if guards:
            key = (*key, guards)
        if key in self._flows:
            return self._flows[key]
        region = self.region_of[port.operation]
        declaration, outgoing, incoming, reached, order = self._edges(region)
        if guards:
            source_choices, target_choices = {}, {}
            for selected in guards:
                if not self.spend("guard_choices"):
                    return None
                operation = self.operations[selected.operation]
                if self.region_of[operation.id] != region:
                    raise ValueError("guard must select an original edge in the source region")
                target = operation.terminator.successors[selected.successor_index].block
                pair = operation.id, selected.successor_index
                source_choices[operation.id] = selected.successor_index
                if target in target_choices and target_choices[target] != pair:
                    # Different incoming visits of one merge require an
                    # occurrence context; a static conjunction cannot select it.
                    return None
                target_choices[target] = pair
            outgoing = {block: [edge for edge in edges
                if (edge[0] not in source_choices or source_choices[edge[0]] == edge[1])
                and (edge[2] not in target_choices or target_choices[edge[2]] == (edge[0], edge[1]))]
                for block, edges in outgoing.items()}
            incoming = {block: [] for block in incoming}
            for parent, edges in outgoing.items():
                for edge in edges:
                    incoming[edge[2]].append((parent, edge))
            reachable, pending = set(), [declaration.entry]
            while pending:
                if not self.spend("guard_reachability"):
                    return None
                block = pending.pop()
                if block not in reachable:
                    reachable.add(block)
                    pending.extend(edge[2] for edge in outgoing[block])
            reached = frozenset(reachable)
            order = tuple(block for block in order if block in reached)
        universe = self._universes[region]
        initial = universe if mode == "must" else frozenset()
        edges = {(item[0], item[1]): initial for block in order for item in outgoing[block]}
        before = {}
        pending, queued = deque(order), set(reached)
        while pending:
            if not self.spend("copy_blocks"):
                return None
            block_id = pending.popleft()
            queued.remove(block_id)
            block = self.blocks[block_id]
            if block_id == declaration.entry:
                current = frozenset()
            else:
                parents = [edges[(item[0], item[1])] for parent, item in incoming[block_id]
                           if parent in reached]
                if not self.spend("copy_meet", sum(map(len, parents))):
                    return None
                current = ((frozenset.intersection(*parents) if mode == "must"
                            else frozenset.union(*parents)) if parents else frozenset())
            for identity in block.operations:
                if not self.spend("copy_operations"):
                    return None
                if identity == port.operation and port.phase == "before":
                    current = frozenset(port.values)
                before[identity] = current
                operation = self.operations[identity]
                ordinary, completion_copies = frozenset(), {}
                # A source result is a new evaluation. Its reset must win
                # over any projection of the call's pre-evaluation inputs.
                if not (identity == port.operation and port.phase in ("after", "edge", "edges")):
                    transfer = self._copy_call_transfer(operation, current, mode=mode)
                    if transfer is None:
                        return None
                    ordinary, completion_copies = transfer
                current = current.difference(operation.results)
                current = current.union(ordinary)
                if identity == port.operation:
                    if port.phase == "after":
                        current = frozenset(port.values)
                    elif port.phase in ("edge", "edges"):
                        current = frozenset()
            for operation, number, target, assignments in outgoing[block_id]:
                if not self.spend("copy_edges", len(assignments) + len(current)):
                    return None
                renamed = current.difference(assignments)
                renamed = renamed.union(formal for formal, actual in assignments.items()
                                        if actual in current)
                renamed = renamed.union(completion_copies.get(number, ()))
                if operation == port.operation and port.phase == "edge" and number == port.edge:
                    renamed = renamed.union(port.values)
                if operation == port.operation and port.phase == "edges":
                    renamed = renamed.union(dict(port.completion_values).get(number, ()))
                edge_key = operation, number
                if edges[edge_key] != renamed:
                    edges[edge_key] = frozenset(renamed)
                    if target not in queued:
                        pending.append(target)
                        queued.add(target)
        self._flows[key] = before
        return before

    def forwards(self, source, target, *, referring=None, guard=None):
        """True/False/None for this producer evaluation at an exact consumer Use."""
        port = self.port(source, referring=referring)
        destination = self.owned_use(target.operation, target.use)
        if port is None or port.gap is not None or port.operation is None:
            return None
        if self.region_of[port.operation] != self.region_of[target.operation]:
            return None
        if (self.block_of[port.operation] == self.block_of[target.operation]
                and (self.positions[port.operation] > self.positions[target.operation]
                     or (port.operation == target.operation and port.phase != "before"))):
            return False
        flow = self._fresh_copies(port, guard=guard)
        return None if flow is None else destination.value in flow.get(target.operation, ())

    def reaches(self, source, target):
        """Can this selected original completion reach an operation locally?

        Reachability is not freshness or runtime path selection. In particular,
        a helper on a terminal reject branch is not a competing body producer.
        """
        port = self.port(source)
        if port is None or port.gap is not None or port.operation is None:
            return None
        if self.region_of[port.operation] != self.region_of[target]:
            return False
        key = port.operation, port.phase, port.edge, target
        if key in self._reachability:
            return self._reachability[key]
        _, outgoing, _, _, _ = self._edges(self.region_of[target])
        target_block = self.block_of[target]
        if port.phase == 'edge':
            if not self.spend('protocol_reachability_candidates'):
                return None
            pending = [self.operations[port.operation].terminator.successors[port.edge].block]
        else:
            source_block = self.block_of[port.operation]
            after = self.positions[port.operation] + (port.phase != 'before')
            if source_block == target_block and self.positions[target] >= after:
                self._reachability[key] = True
                return True
            pending = []
            for edge in outgoing[source_block]:
                if not self.spend('protocol_reachability_candidates'):
                    return None
                pending.append(edge[2])
        seen = set()
        while pending:
            if not self.spend('protocol_reachability_blocks'):
                return None
            block = pending.pop()
            if block == target_block:
                self._reachability[key] = True
                return True
            if block in seen:
                continue
            seen.add(block)
            for edge in outgoing[block]:
                if not self.spend('protocol_reachability_edges'):
                    return None
                pending.append(edge[2])
        self._reachability[key] = False
        return False

    def may_forwards(self, source, target):
        """Possible original copy, used only for consumer inventory.

        A union meet can retain infeasible correlated paths. It never proves
        a current input or authorizes an optimization; must/guarded checks
        remain separate and use this same original CFG transfer engine.
        """
        port = self.port(source)
        destination = self.owned_use(target.operation, target.use)
        if port is None or port.gap is not None or port.operation is None:
            return None
        if self.region_of[port.operation] != self.region_of[target.operation]:
            return None
        before = self._fresh_copies(port, mode="may")
        return None if before is None else destination.value in before.get(target.operation, ())

    def terminal_uses(self, terminal):
        port = self.port(terminal)
        if port is None or port.operation is None:
            return ()
        operation = self.operations[port.operation]
        return tuple(OwnedUse(operation.id, identity) for identity in operation.terminator.values
                     if not isinstance(self.values[self.owned_use(operation.id, identity).value], StateVersionValue))


__all__ = ["ProtocolFlow", "ProtocolPort", "ProtocolReferenceError"]
