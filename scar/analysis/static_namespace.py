"""Conditional namespace dependence over original canonical ports and CFG.

No target execution, replacement graph, runtime identity or empty-effect proof.
The reader checks declared protocol/address joins. Mapping semantics and unknown
intervening effects stay explicit conditions of every derived binding route.
"""
from __future__ import annotations

from collections import defaultdict, deque
from dataclasses import dataclass

from scar.ir.record_codec import decode
from scar.ir.program.ids import OperationID
from scar.ir.program.model import (AccessMode, BlockArgument, CompletionResult, ExitKind,
    LiteralOrigin, ReferenceValue, StateVersionValue, TerminatorKind)
from scar.ir.program.queries import ProgramIndex
from scar.ir.program.state_addresses import InvokeStateOperand, NamespaceKey, ReferenceOwner
from scar.ir.program.static_calls import NamespaceFlowCondition as C, StaticNamespaceFlow
from scar.ir.program.structured import ControlEdgeReference


@dataclass(frozen=True, slots=True)
class NamespaceAccess:
    operation: OperationID
    owners: tuple
    keys: tuple
    world: object
    payload: object
    normal_edge: ControlEdgeReference
    normal_value: object


def protocol_kinds(document):
    result = {}
    for key in ('module', 'structured'):
        for row in (document.get(key) or {}).get('protocols', ()):
            operation = decode(OperationID, row['operation'])
            kind = row['kind']
            if operation in result and result[operation] != kind:
                raise ValueError('namespace operation has conflicting declared protocol kinds')
            result[operation] = kind
    return result


def normal_reference(index, operation, *, blocks=None):
    op = index.operations[operation]
    if op.terminator is None or op.terminator.kind is not TerminatorKind.INVOKE:
        return None
    normals = [(n, edge) for n, edge in enumerate(op.terminator.successors) if edge.kind is ExitKind.NORMAL]
    if len(normals) != 1:
        return None
    n, edge = normals[0]
    blocks = blocks if blocks is not None else {b.id: b for r in index.graph.regions for b in r.blocks}
    block = blocks[edge.block]
    found = [formal for formal, actual in zip(block.arguments, edge.arguments)
             if type(actual) is CompletionResult and actual.index == 0
             and type(index.values[formal]) is ReferenceValue]
    if len(found) != 1:
        return None
    return ControlEdgeReference(op.id, n), found[0]


class NamespaceDependencies:
    def __init__(self, graph, document, *, max_steps=4096, check=None):
        self.graph, self.index = graph, ProgramIndex(graph)
        self.max_steps, self.check = max_steps, check or (lambda: None)
        self.protocols = protocol_kinds(document)
        self.blocks = {b.id: b for r in graph.regions for b in r.blocks}
        self.owners = {op: (r.id, b.id, n) for r in graph.regions for b in r.blocks
                       for n, op in enumerate(b.operations)}
        self.reads, self.writes = {}, {}
        self.by_result = {}
        self._cache = {}
        for op in graph.operations:
            kind = self.protocols.get(op.id)
            writing = kind in ('STORE_NAME_314', 'STORE_GLOBAL')
            if not writing and kind not in ('LOAD_NAME_314', 'LOAD_GLOBAL'):
                continue
            if op.terminator is None or op.terminator.kind is not TerminatorKind.INVOKE:
                raise ValueError('namespace primitive has no actual INVOKE')
            states = [u for u in op.uses if type(self.index.values[u.value]) is StateVersionValue
                      and u.id in op.invoke_arguments]
            if len(states) != 1:
                raise ValueError('namespace primitive has no unique world Use')
            address = self.index.state_address(InvokeStateOperand(op.id, states[0].id))
            pairs = []
            for item in address['effects']:
                effect = item['effect']
                if (type(effect.owner) is ReferenceOwner and len(effect.path) == 1
                        and type(effect.path[0]) is NamespaceKey
                        and effect.mode is (AccessMode.WRITE if writing else AccessMode.READ)):
                    pairs.append((effect.owner.use, effect.path[0].key))
            if len(pairs) != (1 if writing or kind == 'STORE_GLOBAL' else 3 if kind == 'LOAD_NAME_314' else 2):
                raise ValueError('namespace protocol does not have its ordered declared address selectors')
            if any(self.index.use_site(u).operation != op.id for pair in pairs for u in pair):
                raise ValueError('namespace owner/key is not an original operation Use')
            if writing:
                owned = {states[0].id, *(u for pair in pairs for u in pair)}
                payloads = [u.id for u in op.uses if u.id not in owned]
                if len(payloads) != 1 or type(self.index.values[self.index.use_site(payloads[0]).use.value]) is not ReferenceValue:
                    raise ValueError('namespace store lacks its assigned reference Use')
                normal = self._normal_edge(op.id)
                access = NamespaceAccess(op.id, (pairs[0][0],), (pairs[0][1],), states[0].id,
                                         payloads[0], normal, None)
                self.writes[op.id] = access
            else:
                normal = normal_reference(self.index, op.id, blocks=self.blocks)
                if normal is None:
                    raise ValueError('namespace read lacks its original normal reference result')
                access = NamespaceAccess(op.id, tuple(p[0] for p in pairs), tuple(p[1] for p in pairs),
                                         states[0].id, None, *normal)
                self.reads[op.id] = access
                self.by_result[normal[1]] = access

    def _normal_edge(self, operation):
        op = self.index.operations[operation]
        rows = [ControlEdgeReference(op.id, n) for n, edge in enumerate(op.terminator.successors)
                if edge.kind is ExitKind.NORMAL]
        if len(rows) != 1:
            raise ValueError('namespace write lacks its unique normal completion')
        return rows[0]

    def _edge(self, edge):
        op = self.index.operations[edge.operation]
        if op.terminator is None or not 0 <= edge.successor_index < len(op.terminator.successors):
            raise ValueError('namespace path has an absent control successor')
        return op.terminator.successors[edge.successor_index]

    def _value(self, use):
        return self.index.use_site(use).use.value

    def _string(self, use):
        value = self.index.values[self._value(use)]
        if type(value.origin) is LiteralOrigin and type(value.origin.value) is str:
            return value.origin.value
        return None

    def _same(self, write, read, slot):
        # Same SSA reference proves the owner endpoint, not namespace contents.
        # Separate builtin string references compare by value, not identity.
        key = self._string(write.keys[0])
        return (self._value(write.owners[0]) == self._value(read.owners[slot])
                and key is not None and key == self._string(read.keys[slot]))

    def _kills(self, operation, write):
        other = self.writes.get(operation)
        return (other is not None and self._value(other.owners[0]) == self._value(write.owners[0])
                and self._string(other.keys[0]) == self._string(write.keys[0]))

    def _path(self, write, read):
        start = self._edge(write.normal_edge).block
        target = self.owners[read.operation][1]
        queue = deque([(start, (), ())]); seen = set(); steps = 0
        while queue:
            self.check()
            block_id, path, intervening = queue.popleft()
            if block_id in seen:
                continue
            seen.add(block_id); steps += 1
            if steps > self.max_steps:
                raise OverflowError('namespace CFG reachability budget exhausted')
            block = self.blocks[block_id]
            local = block.operations[:self.owners[read.operation][2]] if block_id == target else block.operations
            # This is conditional on declared mapping stores committing input.
            # A later same-key store then replaces this definition on the path.
            operations = intervening + tuple(local)
            if block_id == target:
                if any(self._kills(op, write) for op in local):
                    continue
                return path, operations
            if not block.operations:
                continue
            op = self.index.operations[block.operations[-1]]
            if op.terminator is not None:
                for n, edge in enumerate(op.terminator.successors):
                    if self._kills(op.id, write) and edge.kind is ExitKind.NORMAL:
                        continue
                    if self.owners.get(op.id, (None,))[0] == self.owners[read.operation][0]:
                        queue.append((edge.block, path + (ControlEdgeReference(op.id, n),), operations))
        return None

    def flows(self, value):
        if value in self._cache:
            return self._cache[value]
        read = self.by_result.get(value)
        if read is None:
            return ()
        result = []
        for write in self.writes.values():
            if self.owners[write.operation][0] != self.owners[read.operation][0]:
                continue
            for slot in range(len(read.owners)):
                if not self._same(write, read, slot):
                    continue
                path = self._path(write, read)
                if path is None:
                    continue
                conditions = (C.PATH_TAKEN, C.ALL_NORMAL_NAMESPACE_STORES_COMMIT_INPUT,
                              C.NORMAL_READ_RETURNS_MAPPING_BINDING, C.INTERVENING_EFFECTS_PRESERVE_BINDING)
                if slot:
                    conditions += (C.PRIOR_LOOKUP_NAMESPACES_MISSING,)
                result.append(StaticNamespaceFlow(write.operation, write.owners[0], write.keys[0], write.payload,
                    write.world, write.normal_edge, read.operation, read.owners[slot], read.keys[slot], read.world,
                    read.normal_edge, value, read.owners[:slot], path[0], path[1], conditions))
        self._cache[value] = tuple(result)
        return self._cache[value]

    def validate(self, flow):
        """Replay endpoint/path joins against the original graph, no semantic execution."""
        if flow.write_operation not in self.writes or flow.read_operation not in self.reads:
            raise ValueError('namespace relation endpoints are not their original declared protocols')
        write, read = self.writes[flow.write_operation], self.reads[flow.read_operation]
        if flow.read_owner not in read.owners:
            raise ValueError('namespace relation has an unrelated lookup owner')
        slot = read.owners.index(flow.read_owner)
        exact = (flow.write_owner, flow.write_key, flow.assigned_reference, flow.write_world, flow.write_normal,
                 flow.read_key, flow.read_world, flow.read_normal, flow.read_result, flow.prior_lookup_owners)
        expected = (write.owners[0], write.keys[0], write.payload, write.world, write.normal_edge,
                    read.keys[slot], read.world, read.normal_edge, read.normal_value, read.owners[:slot])
        if exact != expected or not self._same(write, read, slot):
            raise ValueError('namespace relation changed an original owner/key/value/world port')
        current = self._edge(write.normal_edge).block; operations = []
        for edge in flow.path:
            block = self.blocks[current]
            if not block.operations or edge.operation != block.operations[-1]:
                raise ValueError('namespace witness is not a contiguous original CFG path')
            successor = self._edge(edge)
            if self._kills(edge.operation, write) and successor.kind is ExitKind.NORMAL:
                raise ValueError('namespace path crosses a committed replacement write')
            operations.extend(block.operations)
            current = successor.block
        if current != self.owners[read.operation][1]:
            raise ValueError('namespace witness does not reach its original read block')
        tail = self.blocks[current].operations[:self.owners[read.operation][2]]
        operations.extend(tail)
        if tuple(operations) != flow.intervening_operations or any(self._kills(op, write) for op in tail):
            raise ValueError('namespace witness changed operations or crosses a replacement write')
        return True


__all__ = ['NamespaceDependencies', 'normal_reference', 'protocol_kinds']
