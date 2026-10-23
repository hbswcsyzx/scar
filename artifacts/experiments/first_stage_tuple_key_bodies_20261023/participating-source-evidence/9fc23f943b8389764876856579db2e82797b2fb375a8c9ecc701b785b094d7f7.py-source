"""Derived owner aliases and terminal history, never a runtime lifetime proof.

Call after core, D1, publication, no-body and lifecycle operation-shape checks.
The fixed native/no-reset profile makes terminal history stable across callbacks;
current session state and reference ownership are separate properties. E/F reach
a fixed point before explanatory source sets T are computed on that fixed CFG.
"""
from __future__ import annotations

from collections import deque
from dataclasses import dataclass
from types import MappingProxyType
from typing import Mapping

from .ids import OperationID, RegionID, ValueID
from .model import ReferenceValue, TerminatorKind
from .resumption import saved_actual_use


@dataclass(frozen=True, slots=True)
class TerminalPointFacts:
    """Immutable must facts for current Reference carriers at one program point.

    Different alias classes mean unknown equality, not proved disequality.
    Sources are possible seed operation witnesses, not licenses or producers.
    """

    reachable: bool
    aliases: Mapping[ValueID, frozenset[ValueID]]
    finished: frozenset[ValueID]
    sources: Mapping[ValueID, frozenset[OperationID]]

    def __post_init__(self):
        object.__setattr__(self, "aliases", MappingProxyType(
            {value: frozenset(aliases) for value, aliases in self.aliases.items()}))
        object.__setattr__(self, "finished", frozenset(self.finished))
        object.__setattr__(self, "sources", MappingProxyType(
            {value: frozenset(sources) for value, sources in self.sources.items()}))

    def same_owner(self, left: ValueID, right: ValueID) -> bool:
        return self.reachable and right in self.aliases.get(left, ())

    def is_finished(self, value: ValueID) -> bool:
        return self.reachable and value in self.finished

    def source_operations(self, value: ValueID) -> frozenset[OperationID]:
        return self.sources.get(value, frozenset()) if self.is_finished(value) else frozenset()


@dataclass(frozen=True, slots=True)
class TerminalFacts:
    """Before/after operation facts and each renamed edge before target meet."""

    region: RegionID
    before: Mapping[OperationID, TerminalPointFacts]
    after: Mapping[OperationID, TerminalPointFacts]
    edges: Mapping[tuple[OperationID, int], TerminalPointFacts]

    def __post_init__(self):
        for name in ("before", "after", "edges"):
            object.__setattr__(self, name, MappingProxyType(dict(getattr(self, name))))


def reference_assignments(operation, successor, *, values, blocks):
    """Resolve one real edge's Reference formal <- old actual Value or None.

    All assignments use the source snapshot simultaneously. None is a fresh
    boundary, including CompletionResult, BodyDriveResult and ResumeInput.
    This reuses canonical owned Uses, including ordinary UseID subclasses.
    The caller supplies already indexed and validated values/blocks.
    """
    own = {use.id: use.value for use in operation.uses}
    return {
        formal: own.get(saved_actual_use(operation, actual))
        for actual, formal in zip(successor.arguments, blocks[successor.block].arguments)
        if isinstance(values[formal], ReferenceValue)
    }


@dataclass(frozen=True, slots=True)
class _Must:
    # Canonical partition: each member stores its class's smallest carrier index.
    classes: tuple[int, ...]
    finished: frozenset[int]


def _empty(size):
    return _Must(tuple(range(size)), frozenset())


def _rename(state, assignments):
    """Forget targets, then copy from one pre-edge snapshot, including swaps."""
    if state is None or not assignments:
        return state
    representatives = {}
    classes, finished = [], set()
    for index in range(len(state.classes)):
        source = assignments.get(index, index)
        key = ("fresh", index) if source is None else ("old", state.classes[source])
        classes.append(representatives.setdefault(key, index))
        if source is not None and source in state.finished:
            finished.add(index)
    return _Must(tuple(classes), frozenset(finished))


def _meet(states):
    states = tuple(state for state in states if state is not None)
    if not states:
        return None  # unreachable, distinct from reachable with no terminal fact
    if len(states) == 1:
        return states[0]
    representatives = {}
    classes = tuple(representatives.setdefault(tuple(state.classes[index] for state in states), index)
                    for index in range(len(states[0].classes)))
    finished = states[0].finished.intersection(*(state.finished for state in states[1:]))
    return _Must(classes, finished)


def _finish(state, owner):
    if state is None or owner in state.finished:
        return state
    same = state.classes[owner]
    return _Must(state.classes, state.finished | frozenset(
        index for index, group in enumerate(state.classes) if group == same))


def derive_terminal_facts(graph, interface) -> TerminalFacts:
    """Derive finite E/F, then T, in exactly this enabled driver's real CFG.

    No validate/ProgramIndex recursion, external identity assumptions, current
    state stamps, writable proof data or path/configuration enumeration occurs.
    The caller establishes all referenced declarations and private landings.
    """
    if not any(scope.region == interface.region for scope in graph.driver_lifecycles):
        raise ValueError("terminal facts require an explicit DriverLifecycle scope")
    region = next((row for row in graph.regions if row.id == interface.region), None)
    if region is None:
        raise ValueError("terminal facts require their existing driver Region")
    blocks = {block.id: block for block in region.blocks}
    all_operations = {operation.id: operation for operation in graph.operations}
    operations = {identity: all_operations[identity]
                  for block in region.blocks for identity in block.operations}
    values = {value.id: value for value in graph.values}
    carriers = tuple(value.id for value in graph.values
                     if value.region == region.id and isinstance(value, ReferenceValue))
    indices = {identity: index for index, identity in enumerate(carriers)}
    size = len(carriers)
    initial = _empty(size)

    seeds = {}
    for row in graph.body_outcome_commits:
        if (row.operation in operations and all_operations[row.outcome.source].terminator.kind
                in (TerminatorKind.RETURN, TerminatorKind.RAISE)):
            seeds[row.operation] = next(indices[use.value] for use in operations[row.operation].uses
                                        if use.id == row.instance)
    for row in graph.no_body_finishes:
        if row.operation in operations:
            seeds[row.operation] = next(indices[use.value] for use in operations[row.operation].uses
                                        if use.id == row.instance)
    from .protocol_validation import no_entry_seeds
    protocol_seeds = no_entry_seeds(graph, interface.region)
    edge_seeds = {}
    for (identity, successor), owner in protocol_seeds.items():
        if successor is None:
            seeds[identity] = indices[owner]
        else:
            edge_seeds[identity, successor] = indices[owner]
    forget = {op.id: {indices[result]: None for result in op.results if result in indices}
              for op in operations.values()}

    # One transient index of actual CFG edges; no second actual/producer store.
    incoming = {identity: [] for identity in blocks}
    outgoing = {identity: [] for identity in blocks}
    edge_maps, edge_targets = {}, {}
    for block in region.blocks:
        op = operations[block.operations[-1]]
        for number, edge in enumerate(op.terminator.successors):
            key = (op.id, number)
            edge_maps[key] = {indices[formal]: None if source is None else indices[source]
                              for formal, source in reference_assignments(
                                  op, edge, values=values, blocks=blocks).items()}
            incoming[edge.block].append((block.id, key))
            outgoing[block.id].append(key)
            edge_targets[key] = edge.block

    def must_transfer(state, op):
        state = _rename(state, forget[op.id])
        return _finish(state, seeds[op.id]) if op.id in seeds else state

    def edge_transfer(state, key):
        if key in edge_seeds:
            state = _finish(state, edge_seeds[key])
        return _rename(state, edge_maps[key])

    block_before = {identity: None for identity in blocks}
    block_after = dict(block_before)
    work, queued = deque((region.entry,)), {region.entry}
    while work:
        identity = work.popleft()
        queued.remove(identity)
        state = initial if identity == region.entry else _meet(
            edge_transfer(block_after[parent], key) for parent, key in incoming[identity])
        block_before[identity] = state
        for op_id in blocks[identity].operations:
            state = must_transfer(state, operations[op_id])
        if state != block_after[identity]:
            block_after[identity] = state
            for key in outgoing[identity]:
                target = edge_targets[key]
                if target not in queued:
                    work.append(target)
                    queued.add(target)

    before, after, edge_must = {}, {}, {}
    for block in region.blocks:
        state = block_before[block.id]
        for op_id in block.operations:
            before[op_id] = state
            state = must_transfer(state, operations[op_id])
            after[op_id] = state
        for key in outgoing[block.id]:
            edge_must[key] = edge_transfer(state, key)

    # E/F is now immutable. T alone grows by finite union over fixed transfers.
    empty_sources = (frozenset(),) * size

    def mask(sources, must):
        return tuple(sources[index] if must is not None and index in must.finished else frozenset()
                     for index in range(size))

    def rename_sources(sources, assignments, must):
        return mask(tuple(frozenset() if assignments.get(index, index) is None
                          else sources[assignments.get(index, index)] for index in range(size)), must)

    def source_transfer(sources, op_id):
        sources = rename_sources(sources, forget[op_id], after[op_id])
        if op_id in seeds and after[op_id] is not None:
            group = after[op_id].classes[seeds[op_id]]
            sources = tuple(frozenset((op_id,)) if after[op_id].classes[index] == group else source
                            for index, source in enumerate(sources))
        return sources

    def source_edge(sources, key):
        if key in edge_seeds and after[key[0]] is not None:
            group = after[key[0]].classes[edge_seeds[key]]
            sources = tuple(frozenset((key[0],)) if after[key[0]].classes[index] == group else source
                            for index, source in enumerate(sources))
        return rename_sources(sources, edge_maps[key], edge_must[key])

    source_before = {identity: empty_sources for identity in blocks}
    source_after = dict(source_before)
    work = deque(block.id for block in region.blocks if block_before[block.id] is not None)
    queued = set(work)
    while work:
        identity = work.popleft()
        queued.remove(identity)
        if identity == region.entry:
            sources = empty_sources
        else:
            arriving = [source_edge(source_after[parent], key)
                        for parent, key in incoming[identity] if block_after[parent] is not None]
            sources = mask(tuple(frozenset().union(*(state[index] for state in arriving))
                                 for index in range(size)), block_before[identity])
        source_before[identity] = sources
        for op_id in blocks[identity].operations:
            sources = source_transfer(sources, op_id)
        if sources != source_after[identity]:
            source_after[identity] = sources
            for key in outgoing[identity]:
                target = edge_targets[key]
                if target not in queued:
                    work.append(target)
                    queued.add(target)

    unreachable = TerminalPointFacts(False, {}, frozenset(), {})
    point_cache = {}

    def point(must, sources):
        if must is None:
            return unreachable
        key = (must, sources)
        if key not in point_cache:
            groups = {}
            for index, group in enumerate(must.classes):
                groups.setdefault(group, set()).add(carriers[index])
            aliases = {group: frozenset(members) for group, members in groups.items()}
            proof = {carriers[index]: sources[index] for index in must.finished}
            if any(not origins for origins in proof.values()):
                raise AssertionError("a must terminal fact requires a derived seed source")
            point_cache[key] = TerminalPointFacts(
                True, {carrier: aliases[must.classes[index]] for index, carrier in enumerate(carriers)},
                frozenset(proof), proof)
        return point_cache[key]

    public_before, public_after, public_edges = {}, {}, {}
    for block in region.blocks:
        sources = source_before[block.id]
        for op_id in block.operations:
            public_before[op_id] = point(before[op_id], sources)
            sources = source_transfer(sources, op_id)
            public_after[op_id] = point(after[op_id], sources)
        for key in outgoing[block.id]:
            public_edges[key] = point(edge_must[key], source_edge(sources, key))
    return TerminalFacts(region.id, public_before, public_after, public_edges)


__all__ = ["TerminalPointFacts", "TerminalFacts", "derive_terminal_facts", "reference_assignments"]
