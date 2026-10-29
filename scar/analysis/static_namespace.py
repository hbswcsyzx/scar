"""Conditional namespace dependence over original canonical ports and CFG.

No target execution, replacement graph, runtime identity or empty-effect proof.
The reader checks declared protocol/address joins. Mapping semantics and unknown
intervening effects stay explicit conditions of every derived binding route.
"""
from __future__ import annotations

from collections import defaultdict, deque
from dataclasses import dataclass, replace
from enum import Enum

from scar.ir.record_codec import decode
from scar.ir.program.ids import BlockID, OperationID, RegionID, UseID, ValueID
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


class NamespaceOwnerRelation(str, Enum):
    SAME_REFERENCE = 'SAME_REFERENCE'
    CONDITIONAL_REFERENCE_ALIAS = 'CONDITIONAL_REFERENCE_ALIAS'


def _witness_types(owner, operation, world, key, path, intervening, conditions):
    if (type(owner) is not ValueID or type(operation) is not OperationID or type(world) is not UseID
            or type(key) is not str or type(path) is not tuple
            or any(type(row) is not ControlEdgeReference for row in path)
            or type(intervening) is not tuple or any(type(row) is not OperationID for row in intervening)
            or type(conditions) is not tuple or any(type(row) is not C for row in conditions)
            or len(set(conditions)) != len(conditions)):
        raise ValueError('namespace witness requires original typed query/path/condition records')


@dataclass(frozen=True, slots=True)
class NamespaceBindingWitness:
    """One conditional normal-store definition at an existing operation input."""
    write: NamespaceAccess
    query_owner: ValueID
    query_operation: OperationID
    query_world: UseID
    key: str
    owner_relation: NamespaceOwnerRelation
    path: tuple[ControlEdgeReference, ...]
    intervening_operations: tuple[OperationID, ...]
    conditions: tuple[C, ...]

    def __post_init__(self):
        if type(self.write) is not NamespaceAccess or type(self.owner_relation) is not NamespaceOwnerRelation:
            raise ValueError('namespace binding needs its original access and explicit owner relation')
        _witness_types(self.query_owner, self.query_operation, self.query_world, self.key,
                       self.path, self.intervening_operations, self.conditions)


@dataclass(frozen=True, slots=True)
class NamespaceEntryPathWitness:
    """An original region-entry binding can survive to this real query point."""
    region: RegionID
    entry: BlockID
    query_owner: ValueID
    query_operation: OperationID
    query_world: UseID
    key: str
    path: tuple[ControlEdgeReference, ...]
    intervening_operations: tuple[OperationID, ...]
    conditions: tuple[C, ...]
    read: NamespaceAccess | None = None
    read_slot: int | None = None
    entry_owner: ValueID | None = None

    def __post_init__(self):
        if type(self.region) is not RegionID or type(self.entry) is not BlockID:
            raise ValueError('namespace entry path needs its original region/entry')
        _witness_types(self.query_owner, self.query_operation, self.query_world, self.key,
                       self.path, self.intervening_operations, self.conditions)
        if self.entry_owner is None:
            object.__setattr__(self, 'entry_owner', self.query_owner)
        if type(self.entry_owner) is not ValueID:
            raise ValueError('namespace entry owner must retain its original reference ID')
        if ((self.read is None) != (self.read_slot is None)
                or self.read is not None and (type(self.read) is not NamespaceAccess
                    or type(self.read_slot) is not int or not 0 <= self.read_slot < len(self.read.owners))):
            raise ValueError('namespace read path needs its exact original access/owner ordinal')


EntryPathWitness = NamespaceEntryPathWitness


def protocol_kinds(document):
    result = {}
    for key in ('module', 'structured', 'class'):
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
    def __init__(self, graph, document, *, max_steps=4096, check=None, index=None):
        if index is not None and (type(index) is not ProgramIndex or index.graph is not graph):
            raise ValueError('namespace index belongs to another original graph')
        self.graph, self.index = graph, ProgramIndex(graph) if index is None else index
        self.max_steps, self.check = max_steps, check or (lambda: None)
        self.protocols = protocol_kinds(document)
        self.blocks = {b.id: b for r in graph.regions for b in r.blocks}
        self.owners = {op: (r.id, b.id, n) for r in graph.regions for b in r.blocks
                       for n, op in enumerate(b.operations)}
        self.reads, self.writes = {}, {}
        self.by_result = {}
        self._cache = {}
        self._binding_cache, self._entry_cache = {}, {}
        for op in graph.operations:
            kind = self.protocols.get(op.id)
            writing = kind in ('STORE_NAME_314', 'STORE_GLOBAL','COMPILER_STORE_NAME')
            # Function lowering names this two-namespace primitive LOOKUP_GLOBAL;
            # compiler-backed class lowering uses LOAD_GLOBAL. Both retain the
            # declared globals-then-builtins owner/key Uses below. This joins
            # their existing ports; it does not discharge mapping/effect guards.
            if not writing and kind not in ('LOAD_NAME_314', 'LOAD_GLOBAL', 'LOOKUP_GLOBAL'):
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

    def _query(self, owner, key, operation, world_use):
        if (type(owner) is not ValueID or type(key) is not str or type(operation) is not OperationID
                or type(world_use) is not UseID or owner not in self.index.values
                or type(self.index.values[owner]) is not ReferenceValue or operation not in self.owners):
            raise ValueError('namespace query needs an original reference, key and operation')
        try:
            point = self.index.use_site(world_use)
        except KeyError as error:
            raise ValueError('namespace query world is not an original Use') from error
        op = self.index.operations[operation]
        if (point.operation != operation or type(self.index.values[point.use.value]) is not StateVersionValue
                or op.terminator is not None and op.terminator.kind is TerminatorKind.INVOKE
                and world_use not in op.invoke_arguments):
            raise ValueError('namespace query world must be this original operation input Use')
        region, block, offset = self.owners[operation]
        if self.index.values[owner].region != region:
            raise ValueError('namespace query owner belongs to a different original region')
        return region, block, offset

    def _replacement(self, operation, key, equivalent_owners):
        write = self.writes.get(operation)
        return (write is not None and self._string(write.keys[0]) == key
                and self._value(write.owners[0]) in equivalent_owners)

    def _find_path(self, start, operation, key, equivalent_owners):
        """One original CFG witness for this candidate, with edge-aware kills.

        A RAISE edge remains traversable: custom namespace stores can mutate
        before raising. INTERVENING_EFFECTS_PRESERVE_BINDING stays mandatory,
        so such an edge is never interpreted as an empty write effect.
        """
        region, target, offset = self.owners[operation]
        queue, seen, steps = deque(((start, (), ()),)), set(), 0
        while queue:
            self.check()
            block_id, path, intervening = queue.popleft()
            if block_id in seen:
                continue
            seen.add(block_id); steps += 1
            if steps > self.max_steps:
                raise OverflowError('namespace CFG reachability budget exhausted')
            block = self.blocks[block_id]
            local = block.operations[:offset] if block_id == target else block.operations
            operations = intervening + tuple(local)
            if block_id == target:
                if not any(self._replacement(identity, key, equivalent_owners) for identity in local):
                    return path, operations
                continue
            if not block.operations:
                continue
            last = self.index.operations[block.operations[-1]]
            if last.terminator is None:
                continue
            for ordinal, edge in enumerate(last.terminator.successors):
                if (self._replacement(last.id, key, equivalent_owners) and edge.kind is ExitKind.NORMAL):
                    continue
                if edge.block not in self.blocks or self.index._blocks[edge.block] != region:
                    continue
                queue.append((edge.block, path + (ControlEdgeReference(last.id, ordinal),), operations))
        return None

    def _validate_path(self, start, operation, key, equivalent_owners, path, intervening):
        if len(path) > self.max_steps:
            raise OverflowError('namespace CFG witness budget exhausted')
        region, target, offset = self.owners[operation]
        current, operations = start, []
        if current not in self.blocks or self.index._blocks[current] != region:
            raise ValueError('namespace path starts outside its original query region')
        for reference in path:
            self.check()
            block = self.blocks[current]
            if not block.operations or reference.operation != block.operations[-1]:
                raise ValueError('namespace witness is not a contiguous original CFG path')
            edge = self._edge(reference)
            if self._replacement(reference.operation, key, equivalent_owners) and edge.kind is ExitKind.NORMAL:
                raise ValueError('namespace path crosses a committed replacement under its owner relation')
            if edge.block not in self.blocks or self.index._blocks[edge.block] != region:
                raise ValueError('namespace path crossed a different original region')
            operations.extend(block.operations)
            current = edge.block
        if current != target:
            raise ValueError('namespace witness does not reach its original query block')
        tail = self.blocks[current].operations[:offset]
        operations.extend(tail)
        if tuple(operations) != intervening or any(self._replacement(identity, key, equivalent_owners) for identity in tail):
            raise ValueError('namespace witness changed original operations or crosses a replacement')
        return True

    @staticmethod
    def _conditions(*, alias=False, read_slot=None):
        conditions = (C.PATH_TAKEN, C.ALL_NORMAL_NAMESPACE_STORES_COMMIT_INPUT,
                      C.INTERVENING_EFFECTS_PRESERVE_BINDING)
        if alias:
            conditions += (C.NAMESPACE_OWNERS_ALIAS,)
        if read_slot is not None:
            conditions += (C.NORMAL_READ_RETURNS_MAPPING_BINDING,)
            if read_slot:
                conditions += (C.PRIOR_LOOKUP_NAMESPACES_MISSING,)
        return conditions

    def bindings_at(self, owner: ValueID, key: str, operation: OperationID, world_use: UseID,
                    *, allow_owner_alias=False):
        """Possible normal-store definitions before an existing CALL/LOAD/op.

        Owner aliasing is only a conditional candidate. The caller must justify
        whether that guard is applicable; this method never equates module L/G
        or function/class namespaces merely because they are namespace ports.
        """
        region, _, _ = self._query(owner, key, operation, world_use)
        if type(allow_owner_alias) is not bool:
            raise ValueError('namespace owner-alias policy must be an explicit bool')
        cache_key = owner, key, operation, world_use, allow_owner_alias
        if cache_key in self._binding_cache:
            return self._binding_cache[cache_key]
        rows = []
        for write in self.writes.values():
            self.check()
            if self.owners[write.operation][0] != region or self._string(write.keys[0]) != key:
                continue
            write_owner = self._value(write.owners[0])
            alias = write_owner != owner
            if alias and not allow_owner_alias:
                continue
            relation = (NamespaceOwnerRelation.CONDITIONAL_REFERENCE_ALIAS if alias
                        else NamespaceOwnerRelation.SAME_REFERENCE)
            path = self._find_path(self._edge(write.normal_edge).block, operation, key, {owner, write_owner})
            if path is not None:
                rows.append(NamespaceBindingWitness(write, owner, operation, world_use, key,
                    relation, path[0], path[1], self._conditions(alias=alias)))
        result = tuple(rows)
        self._binding_cache[cache_key] = result
        return result

    def _entry_owner(self, region, owner):
        if (type(owner) is not ValueID or owner not in self.index.values
                or type(self.index.values[owner]) is not ReferenceValue
                or self.index.values[owner].region != region):
            raise ValueError('namespace entry owner is not an original reference in this region')
        return owner

    def entry_paths_to(self, owner: ValueID, key: str, operation: OperationID, world_use: UseID,
                       *, entry_owner: ValueID | None = None):
        """Existing region entry to any real point, with no known overwrite."""
        region, _, _ = self._query(owner, key, operation, world_use)
        entry_owner = self._entry_owner(region, owner if entry_owner is None else entry_owner)
        cache_key = owner, key, operation, world_use, entry_owner
        if cache_key not in self._entry_cache:
            entry = self.index.regions[region].entry
            path = self._find_path(entry, operation, key, {owner, entry_owner})
            self._entry_cache[cache_key] = (() if path is None else (NamespaceEntryPathWitness(
                region, entry, owner, operation, world_use, key, path[0], path[1],
                self._conditions(alias=entry_owner != owner), entry_owner=entry_owner),))
        return self._entry_cache[cache_key]

    entry_paths_at = entry_paths_to

    def entry_paths_to_read(self, read: NamespaceAccess, slot=0, *, entry_owner: ValueID | None = None):
        if (type(read) is not NamespaceAccess or self.reads.get(read.operation) != read
                or type(slot) is not int or not 0 <= slot < len(read.owners)):
            raise ValueError('namespace entry/read query needs its original access/owner ordinal')
        key = self._string(read.keys[slot])
        if key is None:
            return ()
        owner = self._value(read.owners[slot])
        return tuple(replace(row, read=read, read_slot=slot,
                            conditions=self._conditions(alias=row.entry_owner != owner, read_slot=slot))
            for row in self.entry_paths_to(owner, key, read.operation, read.world, entry_owner=entry_owner))

    def validate_binding(self, witness):
        if type(witness) is not NamespaceBindingWitness:
            raise ValueError('namespace binding validation needs its typed local witness')
        witness.__post_init__()
        region, _, _ = self._query(witness.query_owner, witness.key, witness.query_operation, witness.query_world)
        write = self.writes.get(witness.write.operation)
        if write != witness.write or self.owners[write.operation][0] != region or self._string(write.keys[0]) != witness.key:
            raise ValueError('namespace binding changed its original write/key/region endpoint')
        owner = self._value(write.owners[0])
        alias = owner != witness.query_owner
        expected_relation = NamespaceOwnerRelation.CONDITIONAL_REFERENCE_ALIAS if alias else NamespaceOwnerRelation.SAME_REFERENCE
        if witness.owner_relation is not expected_relation or witness.conditions != self._conditions(alias=alias):
            raise ValueError('namespace binding dropped or changed an explicit owner/path/effect condition')
        return self._validate_path(self._edge(write.normal_edge).block, witness.query_operation, witness.key,
            {owner, witness.query_owner}, witness.path, witness.intervening_operations)

    def validate_entry_path(self, witness, *, entry_owner: ValueID | None = None):
        if type(witness) is not NamespaceEntryPathWitness:
            raise ValueError('namespace entry validation needs its typed local witness')
        witness.__post_init__()
        region, _, _ = self._query(witness.query_owner, witness.key, witness.query_operation, witness.query_world)
        if witness.region != region or witness.entry != self.index.regions[region].entry:
            raise ValueError('namespace entry witness changed its original region entry')
        original_owner = self._entry_owner(region, witness.entry_owner)
        if entry_owner is not None and entry_owner != original_owner:
            raise ValueError('namespace entry witness changed the externally qualified entry owner')
        if witness.read is not None:
            read, slot = witness.read, witness.read_slot
            if (self.reads.get(read.operation) != read or read.operation != witness.query_operation
                    or read.world != witness.query_world or self._value(read.owners[slot]) != witness.query_owner
                    or self._string(read.keys[slot]) != witness.key):
                raise ValueError('namespace entry witness changed its original read owner/key/world')
        if witness.conditions != self._conditions(alias=original_owner != witness.query_owner, read_slot=witness.read_slot):
            raise ValueError('namespace entry witness changed its path/read/effect conditions')
        return self._validate_path(witness.entry, witness.query_operation, witness.key, {witness.query_owner, original_owner},
                                   witness.path, witness.intervening_operations)

    def _path(self, write, read):
        return self._find_path(self._edge(write.normal_edge).block, read.operation,
                               self._string(write.keys[0]), {self._value(write.owners[0])})

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
        return self._validate_path(self._edge(write.normal_edge).block, read.operation,
            self._string(write.keys[0]), {self._value(write.owners[0])}, flow.path, flow.intervening_operations)


__all__ = ['NamespaceDependencies', 'NamespaceAccess', 'NamespaceOwnerRelation',
           'NamespaceBindingWitness', 'NamespaceEntryPathWitness', 'EntryPathWitness',
           'normal_reference', 'protocol_kinds']
