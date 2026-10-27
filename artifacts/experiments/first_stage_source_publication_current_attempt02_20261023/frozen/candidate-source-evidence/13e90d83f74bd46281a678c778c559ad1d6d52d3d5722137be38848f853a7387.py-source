"""Current session predicates over fixed owner aliases and canonical state SSA.

P is a finite must relation of ordered (R, B, predicate) triples. Supporting
state versions are derived from the current program point, never a second
mutable world. Boolean facts stabilize before explanatory source sets grow.
"""
from __future__ import annotations

from collections import deque
from dataclasses import dataclass
from types import MappingProxyType
from typing import Mapping

from .drivers import BodyDriveTerminator
from .ids import OperationID, RegionID, ValueID
from .lifecycle import LifecyclePostBinding, SessionPost
from .lifecycle_flow import reference_assignments
from .model import AccessMode, ExitKind, ReferenceValue, StateVersionValue, TerminatorKind
from .resumption import SuspendTerminator


@dataclass(frozen=True, slots=True)
class SessionPostFact:
    request: ValueID
    body: ValueID
    post: SessionPost
    support: tuple[StateVersionValue, ...]
    sources: frozenset[OperationID]


@dataclass(frozen=True, slots=True)
class SessionPointFacts:
    reachable: bool
    posts: tuple[SessionPostFact, ...]

    def for_pair(self, request, body):
        return tuple(fact for fact in self.posts if fact.request == request and fact.body == body)


@dataclass(frozen=True, slots=True)
class SessionFacts:
    region: RegionID
    before: Mapping[OperationID, SessionPointFacts]
    after: Mapping[OperationID, SessionPointFacts]
    edges: Mapping[tuple[OperationID, int], SessionPointFacts]

    def __post_init__(self):
        for name in ("before", "after", "edges"):
            object.__setattr__(self, name, MappingProxyType(dict(getattr(self, name))))


def _post_closure(post):
    # These are current predicates, not mutually exclusive machine phases.
    return (post, SessionPost.ABANDON) if post is SessionPost.COMPLETE else (post,)


def _reference_targets(assignments, carriers):
    """Preindex all parallel edge assignments once, including unchanged names."""
    targets = {}
    for target in carriers:
        source = assignments.get(target, target)
        if source is not None:
            targets.setdefault(source, []).append(target)
    return targets


def _rename_relation(relation, targets):
    """Simultaneously rename closed alias carriers from the pre-edge snapshot."""
    return frozenset((request, body, post) for old_request, old_body, post in relation
                     for request in targets.get(old_request, ()) for body in targets.get(old_body, ()))


def derive_session_facts(graph, interface, terminal) -> SessionFacts:
    """Call only after shape validation and fixed E/F/T in this enabled driver."""
    region = next(row for row in graph.regions if row.id == interface.region)
    blocks = {block.id: block for block in region.blocks}
    all_ops = {op.id: op for op in graph.operations}
    operations = {identity: all_ops[identity] for block in region.blocks for identity in block.operations}
    values = {value.id: value for value in graph.values}
    updates = {row.operation: row for row in graph.session_updates if row.operation in operations}
    if not updates:
        # Empty-entry must analysis with no post sources cannot create a P.
        def empty(points):
            return {key: SessionPointFacts(point.reachable, ()) for key, point in points.items()}
        return SessionFacts(region.id, empty(terminal.before), empty(terminal.after), empty(terminal.edges))
    body_only = {row.operation for row in (*graph.body_outcome_commits, *graph.no_body_finishes)}
    lifecycle = tuple(interface.lifecycle)
    carriers = tuple(terminal.before[blocks[region.entry].operations[0]].aliases)
    incoming, outgoing = {block: [] for block in blocks}, {block: [] for block in blocks}
    edge_maps, edge_targets, edge_seed = {}, {}, {}
    support_before, support_after, support_edge = {}, {}, {}
    seeds, forget, kills = {}, {}, {}

    def seed(row, point):
        own = {use.id: use.value for use in operations[row.operation].uses}
        return frozenset((request, body, post)
            for request in point.aliases[own[row.request]]
            for body in point.aliases[own[row.body]] for post in _post_closure(row.post))

    for block in region.blocks:
        current = {values[value].location: value for value in block.arguments
                   if isinstance(values[value], StateVersionValue)}
        for identity in block.operations:
            op = operations[identity]
            support_before[identity] = tuple(current[location] for location in lifecycle)
            for result in op.results:
                value = values[result]
                if isinstance(value, StateVersionValue):
                    current[value.location] = result
            support_after[identity] = tuple(current[location] for location in lifecycle)
            forget[identity] = frozenset(result for result in op.results if isinstance(values[result], ReferenceValue))
            row = updates.get(identity)
            if row is not None and row.binding is LifecyclePostBinding.AFTER_OPERATION:
                seeds[identity] = seed(row, terminal.after[identity])
            kills[identity] = (identity not in body_only and (
                not op.effects_complete or op.callee is not None
                or isinstance(op.terminator, (BodyDriveTerminator, SuspendTerminator))
                or (op.terminator is not None and op.terminator.kind is TerminatorKind.INVOKE)
                or any(access.location in lifecycle and access.mode is not AccessMode.READ for access in op.accesses)
                or any(isinstance(values[result], StateVersionValue) and values[result].location in lifecycle
                       for result in op.results)))
        op = operations[block.operations[-1]]
        row = updates.get(op.id)
        for index, edge in enumerate(op.terminator.successors):
            key = (op.id, index)
            edge_targets[key] = edge.block
            outgoing[block.id].append(key)
            incoming[edge.block].append((block.id, key))
            edge_maps[key] = _reference_targets(reference_assignments(op, edge, values=values, blocks=blocks), carriers)
            states = {values[formal].location: formal for formal in blocks[edge.block].arguments
                      if isinstance(values[formal], StateVersionValue)}
            support_edge[key] = tuple(states[location] for location in lifecycle)
            if row is not None and row.binding is LifecyclePostBinding.NORMAL_COMPLETION and edge.kind is ExitKind.NORMAL:
                edge_seed[key] = seed(row, terminal.edges[key])

    def transfer(state, identity):
        if state is None:
            return None
        if identity in seeds:
            return seeds[identity]
        if kills[identity]:
            return frozenset()
        return frozenset(key for key in state if key[0] not in forget[identity] and key[1] not in forget[identity])

    def edge_transfer(state, key):
        if state is None:
            return None
        return edge_seed[key] if key in edge_seed else _rename_relation(state, edge_maps[key])

    before_blocks, after_blocks = {block: None for block in blocks}, {block: None for block in blocks}
    work, queued = deque((region.entry,)), {region.entry}
    while work:
        block_id = work.popleft()
        queued.remove(block_id)
        arriving = [edge_transfer(after_blocks[parent], key) for parent, key in incoming[block_id]
                    if after_blocks[parent] is not None]
        state = frozenset() if block_id == region.entry else (
            frozenset.intersection(*arriving) if arriving else None)
        before_blocks[block_id] = state
        for identity in blocks[block_id].operations:
            state = transfer(state, identity)
        if state != after_blocks[block_id]:
            after_blocks[block_id] = state
            for key in outgoing[block_id]:
                target = edge_targets[key]
                if target not in queued:
                    work.append(target)
                    queued.add(target)
    before, after, edges = {}, {}, {}
    for block in region.blocks:
        state = before_blocks[block.id]
        for identity in block.operations:
            before[identity] = state
            state = transfer(state, identity)
            after[identity] = state
        for key in outgoing[block.id]:
            edges[key] = edge_transfer(state, key)

    def mask(sources, allowed):
        return {key: origins for key, origins in sources.items() if allowed is not None and key in allowed and origins}

    def source_transfer(sources, identity):
        if identity in seeds:
            return {key: frozenset((identity,)) for key in seeds[identity]}
        if kills[identity]:
            return {}
        return mask(sources, after[identity])

    def source_edge(sources, key):
        if key in edge_seed:
            return {fact: frozenset((key[0],)) for fact in edge_seed[key]}
        result = {}
        for fact, origins in sources.items():
            for renamed in _rename_relation((fact,), edge_maps[key]):
                result[renamed] = result.get(renamed, frozenset()) | origins
        return mask(result, edges[key])

    source_before, source_after = {block: {} for block in blocks}, {block: {} for block in blocks}
    work = deque(block.id for block in region.blocks if before_blocks[block.id] is not None)
    queued = set(work)
    while work:
        block_id = work.popleft()
        queued.remove(block_id)
        sources = {}
        if block_id != region.entry:
            for parent, key in incoming[block_id]:
                if after_blocks[parent] is not None:
                    for fact, origins in source_edge(source_after[parent], key).items():
                        sources[fact] = sources.get(fact, frozenset()) | origins
            sources = mask(sources, before_blocks[block_id])
        source_before[block_id] = sources
        for identity in blocks[block_id].operations:
            sources = source_transfer(sources, identity)
        if sources != source_after[block_id]:
            source_after[block_id] = sources
            for key in outgoing[block_id]:
                target = edge_targets[key]
                if target not in queued:
                    work.append(target)
                    queued.add(target)

    def point(facts, sources, support):
        if facts is None:
            return SessionPointFacts(False, ())
        if any(not sources.get(key) for key in facts):
            raise AssertionError("a current session predicate requires a declared post source")
        states = tuple(values[identity] for identity in support)
        return SessionPointFacts(True, tuple(SessionPostFact(*key, states, sources[key])
            for key in sorted(facts, key=lambda key: (key[0].wire, key[1].wire, key[2].value))))

    public_before, public_after, public_edges = {}, {}, {}
    for block in region.blocks:
        sources = source_before[block.id]
        for identity in block.operations:
            public_before[identity] = point(before[identity], sources, support_before[identity])
            sources = source_transfer(sources, identity)
            public_after[identity] = point(after[identity], sources, support_after[identity])
        for key in outgoing[block.id]:
            public_edges[key] = point(edges[key], source_edge(sources, key), support_edge[key])
    return SessionFacts(region.id, public_before, public_after, public_edges)


__all__ = ["SessionPostFact", "SessionPointFacts", "SessionFacts", "derive_session_facts"]
