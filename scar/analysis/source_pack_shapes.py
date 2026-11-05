"""Memoize static argument-pack witnesses, separately from dynamic guards.

Private integers are existing solver indices, never new source identities.
Contents retain original ordered points. The legacy sealed merge admission
is reused; no shape is inferred from runtime contents or current values.
"""
from collections import defaultdict
from dataclasses import dataclass


@dataclass(frozen=True, slots=True)
class StaticPackShape:
    origin: int
    kind: str
    contents: tuple
    dependencies: frozenset[tuple[int, str]]


@dataclass(frozen=True, slots=True)
class StaticPackReject:
    reason: str


class StaticPackShapes:
    """One immutable unit index; every use rechecks opening and readiness.

    A shape-cache miss computes a witness or a specific structural refusal.
    Empty contents are a positive witness. Opening a nested merge dependency
    invalidates applicability without discarding its source-structure proof.
    """

    def __init__(self, flow):
        self.flow = flow
        self._unit_cursor = 0
        self._metadata = {}
        self._shapes = {}
        self._merge_proofs = {}
        self._stats = dict(metadata_units=0, metadata_items=0, shape_builds=0,
            shape_hits=0, merge_proof_reads=0, merge_proof_hits=0,
            open_checks=0, open_refusals=0, readiness_checks=0,
            readiness_refusals=0, caller_cycle_refusals=0)

    @property
    def stats(self):
        return dict(self._stats, cached_shapes=len(self._shapes),
            positive_shapes=sum(type(s) is StaticPackShape for s in self._shapes.values()),
            negative_shapes=sum(type(s) is StaticPackReject for s in self._shapes.values()))

    def _index_new_units(self):
        # EntrySolver.units is an append-only list. Source tables and offset
        # intervals of an already indexed unit never grow with admission.
        units = self.flow.s.units
        while self._unit_cursor < len(units):
            self.flow._index_pack_unit(units[self._unit_cursor])
            self._unit_cursor += 1

    def _unit_metadata(self, unit):
        if unit.unit not in self._metadata:
            flow = self.flow
            blocked = set()
            for point in (*flow.pack_escapes[unit.unit], *flow.pack_writes[unit.unit]):
                origin = flow._pack_origin(point)
                if origin is not None:
                    blocked.add(origin)
            updates = defaultdict(list)
            for target, source, append in flow.pack_updates[unit.unit]:
                origin = flow._pack_origin(target)
                if origin is not None:
                    updates[origin].append((target, source, append))
            self._metadata[unit.unit] = frozenset(blocked), {
                origin:tuple(items) for origin, items in updates.items()}
            self._stats['metadata_units'] += 1
            self._stats['metadata_items'] += sum(len(table[unit.unit]) for table in (
                flow.pack_escapes, flow.pack_writes, flow.pack_updates))
        return self._metadata[unit.unit]

    def _proof(self, unit, origin):
        key = unit.unit, origin
        if key not in self._merge_proofs:
            self._stats['merge_proof_reads'] += 1
            self._merge_proofs[key] = frozenset(self.flow._merge_proof(unit, origin))
        else:
            self._stats['merge_proof_hits'] += 1
        return self._merge_proofs[key]

    def _shape(self, point, kind, active):
        flow = self.flow
        origin = flow._pack_origin(point)
        if origin is None or origin not in flow.pack_constructors:
            return StaticPackReject('NO_CLOSED_SOURCE_CONSTRUCTOR')
        if origin in active:
            # This is an actual cycle in the immutable merge dependency
            # graph. The in-progress entry itself is never memoized.
            return StaticPackReject('CYCLIC_SOURCE_MERGE')
        key = origin, kind
        if key in self._shapes:
            self._stats['shape_hits'] += 1
            return self._shapes[key]
        self._stats['shape_builds'] += 1
        result = self._build(origin, kind, active)
        self._shapes[key] = result
        return result

    def _build(self, origin, kind, active):
        flow = self.flow
        unit, item = flow.pack_constructors[origin]
        offset = flow.s.offsets[unit.unit]
        if item.kind.value != kind:
            return StaticPackReject('CONSTRUCTOR_KIND_MISMATCH')
        blocked, by_origin = self._unit_metadata(unit)
        if origin in blocked:
            return StaticPackReject('SOURCE_CONSTRUCTOR_ESCAPES_OR_IS_WRITTEN')
        updates = by_origin.get(origin, ())
        if kind == 'SEQUENCE':
            if updates:
                return StaticPackReject('SEQUENCE_CONSTRUCTION_HAS_UPDATES')
            return StaticPackShape(origin, kind, tuple(offset+p for p in item.elements),
                                   frozenset(((origin, kind),)))
        pairs = {}
        for key, value in item.pairs:
            literal = flow.pack_constants.get(flow._pack_origin(offset+key))
            if literal is None or type(name := literal.to_python()) is not str:
                return StaticPackReject('KEY_IS_NOT_A_CLOSED_STRING_LITERAL')
            pairs[name] = offset+value
        dependencies = {(origin, kind)}
        if updates:
            proof = self._proof(unit, origin)
            for target, source, append in updates:
                if append or (target, source) not in proof:
                    return StaticPackReject('UPDATE_LACKS_SEALED_DICT_MERGE_PROOF')
                child = self._shape(source, 'MAPPING', active | {origin})
                if type(child) is StaticPackReject:
                    return child
                dependencies.update(child.dependencies)
                for name, value in child.contents:
                    if name in pairs:
                        return StaticPackReject('MERGED_KEY_IS_NOT_UNIQUE')
                    pairs[name] = value
        return StaticPackShape(origin, kind, tuple(pairs.items()), frozenset(dependencies))

    def shape(self, point, kind):
        if kind not in ('SEQUENCE', 'MAPPING'):
            raise ValueError('an argument-pack kind is required')
        self._index_new_units()
        return self._shape(point, kind, frozenset())

    def closed(self, point, kind, seen=frozenset()):
        witness = self.shape(point, kind)
        if type(witness) is StaticPackReject:
            return None
        if any(origin in seen for origin, _ in witness.dependencies):
            self._stats['caller_cycle_refusals'] += 1
            return None
        self._stats['open_checks'] += 1
        if any(('container', origin, dependency_kind) in self.flow.open_containers
               for origin, dependency_kind in witness.dependencies):
            self._stats['open_refusals'] += 1
            return None
        return witness.contents, witness.origin

    def arguments(self, invocation):
        """Preserve the legacy pack ABI, including independent-side queries."""
        positional = list(invocation.positional)
        keywords = list(invocation.keywords)
        for point, kind in ((invocation.positional_pack, 'SEQUENCE'),
                            (invocation.keyword_pack, 'MAPPING')):
            if point is None:
                continue
            closed = self.closed(point, kind)
            if closed is None:
                return None
            contents, origin = closed
            values = self.flow.s.values.get(point, ())
            self._stats['readiness_checks'] += 1
            if len(values) != 1 or ('container', origin, kind) not in values:
                self._stats['readiness_refusals'] += 1
                return None
            if kind == 'SEQUENCE':
                positional.extend(contents)
            else:
                keywords.extend(contents)
        return tuple(positional), tuple(keywords)
