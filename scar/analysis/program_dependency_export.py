"""Normalized query records: original namespaces, contexts and evidence once."""
from __future__ import annotations

from collections import Counter
from dataclasses import fields, is_dataclass
from enum import Enum

from scar.analysis.program_dependencies import DependencyWalk
from scar.ir.program.dependencies import (GraphNamespace, DependencyFrame, DependencyPoint,
    DependencyCondition, DependencyEvidence, DependencyEdge, DependencyFrontier)
from scar.ir.program.source_references import SourceArtifactLocator
from scar.ir.literals import PythonLiteral
from scar.ir.record_codec import encode
from scar.ir.v2.ids import Identifier


class _Tables:
    def __init__(self, visited=()):
        self.tables = {name: [] for name in ('locators', 'namespaces', 'frames', 'contexts',
            'points', 'conditions', 'evidence', 'frontier_reasons', 'edges')}
        self.indices = {name: {} for name in self.tables}
        self.visited = set(visited)

    def put(self, name, value, record):
        found = self.indices[name].get(value)
        if found is not None:
            return found
        index = len(self.tables[name])
        self.indices[name][value] = index
        self.tables[name].append(record())
        return index

    def locator(self, value):
        return self.put('locators', value, lambda: encode(value))

    def namespace(self, value):
        def record():
            body = value.source_body
            return {'graph': self.locator(value.graph), 'representation': value.representation,
                'root': value.root.wire, 'source_body': None if body is None else {
                    'definition': body.definition.wire, 'entry': body.entry, 'source': encode(body.source)}}
        return self.put('namespaces', value, record)

    def frame(self, value):
        return self.put('frames', value, lambda: {'caller': self.namespace(value.caller),
            'operation': value.operation.wire,
            'callee_use': None if value.callee_use is None else value.callee_use.wire,
            'callee_value': None if value.callee_value is None else value.callee_value.wire,
            'target': self.namespace(value.target),
            'definition': None if value.definition is None else value.definition.wire,
            'entry': None if value.entry is None else value.entry.wire})

    def context(self, value):
        return None if value is None else self.put('contexts', value,
            lambda: {'frames': [self.frame(item) for item in value]})

    def point(self, value):
        return self.put('points', value, lambda: {'namespace': self.namespace(value.namespace),
            'node': value.node.wire, 'node_type': type(value.node).__name__,
            'context': self.context(value.context), 'visited': value in self.visited})

    def condition(self, value):
        return self.put('conditions', value, lambda: {'domain': value.domain, 'name': value.name,
            'subject': None if value.subject is None else self.point(value.subject), 'index': value.index,
            'operands': [self.point(operand) for operand in value.operands]})

    def evidence(self, value):
        return self.put('evidence', value, lambda: {'rule': value.rule,
            'sources': [self.locator(item) for item in value.sources],
            'anchors': [self.point(item) for item in value.anchors]})

    def edge(self, value):
        return self.put('edges', value, lambda: {'source': self.point(value.source),
            'target': self.point(value.target), 'kind': value.kind.value, 'meaning': value.meaning.value,
            'strength': value.strength.value, 'evidence': [self.evidence(item) for item in value.evidence],
            'conditions': [self.condition(item) for item in value.conditions]})

    def frontier(self, value):
        reason = self.put('frontier_reasons', (value.kind, value.detail),
            lambda: {'kind': value.kind, 'detail': value.detail})
        return {'point': self.point(value.point), 'reason': reason}

    def pack(self, value):
        references = ((GraphNamespace, 'namespace', self.namespace), (DependencyFrame, 'frame', self.frame),
            (DependencyPoint, 'point', self.point), (DependencyCondition, 'condition', self.condition),
            (DependencyEvidence, 'evidence', self.evidence), (DependencyEdge, 'edge', self.edge),
            (SourceArtifactLocator, 'locator', self.locator))
        for kind, name, method in references:
            if type(value) is kind:
                return {name: method(value)}
        if type(value) is DependencyFrontier:
            return self.frontier(value)
        if type(value) is PythonLiteral:
            return {'literal': value.as_dict()}
        if isinstance(value, Enum):
            return value.value
        if isinstance(value, Identifier):
            return {'original_id': value.wire}
        if is_dataclass(value):
            return {'record_type': type(value).__name__,
                **{field.name: self.pack(getattr(value, field.name)) for field in fields(value)}}
        if isinstance(value, (tuple, list)):
            return [self.pack(item) for item in value]
        if type(value) is dict:
            if any(type(key) is not str for key in value):
                raise TypeError('query records need string field names')
            return {key: self.pack(item) for key, item in value.items()}
        if value is None or type(value) in (str, int, float, bool):
            return value
        raise TypeError('unsupported query field: ' + type(value).__name__)


def export_dependency_walk(walk):
    """Export a bounded dependency query, retaining original entity references."""
    if type(walk) is not DependencyWalk:
        raise TypeError('expected a typed original dependency traversal')
    table = _Tables(walk.points)
    roots = [table.point(root) for root in walk.roots]
    for point in walk.points:
        table.point(point)
    for edge in walk.edges:
        table.edge(edge)
    frontiers = [table.frontier(item) for item in walk.frontiers]
    return {'schema': 'scar.program-dependency-query', 'schema_version': 2,
        'direction': walk.direction, 'roots': roots, **table.tables, 'frontiers': frontiers,
        'relation_scope': [kind.value for kind in walk.kinds],
        'summary': {'visited_points': len(walk.points), 'referenced_points': len(table.tables['points']),
            'namespaces': len(table.tables['namespaces']), 'edges': len(walk.edges),
            'edge_kinds': dict(Counter(edge.kind.value for edge in walk.edges)),
            'frontier_kinds': dict(Counter(item.kind for item in walk.frontiers))},
        'traversal_exhausted': walk.traversal_exhausted, 'dependence_closed': walk.dependence_closed,
        'whole_program_complete': False, 'transformation_authorized': False,
        'qualification': 'Original typed endpoints and conditional dependencies over shared source fragments. '
            'Context null is unknown; an empty frame list selects no caller. '
            'CFG/sequence/containment are structural, not required ordering or equality. '
            'Query completion is not whole-program closure or transformation permission.'}


def export_value_analysis(result):
    from scar.analysis.program_value_analysis import ValueAnalysisResult
    if type(result) is not ValueAnalysisResult:
        raise TypeError('expected typed original value facts')
    table = _Tables(fact.point for fact in result.facts)
    roots = [table.point(point) for point in result.roots]
    for edge in result.edges:
        table.edge(edge)
    def field(value):
        return {'precision': value.precision.value, 'applicable': value.applicable,
            'alternatives': [table.pack(item) for item in value.alternatives],
            'unknown_paths': [table.frontier(item) for item in value.unknown_paths]}
    def fields_of(value):
        return {name: field(getattr(value, name)) for name in
                ('reference_sources', 'scalar_constant', 'builtin_type', 'immutable_tuple')}
    facts = [{'point': table.point(fact.point), 'role': fact.role, 'feasible': fact.feasible,
        'fields': fields_of(fact.fields),
        'binding_payload': None if fact.binding_payload is None else fields_of(fact.binding_payload),
        'binding_state': field(fact.binding_state),
        'occurrence': table.pack(fact.occurrence),
        'infeasibility': table.pack(fact.infeasibility),
        'binding_states': [item.value for item in fact.binding_states]} for fact in result.facts]
    frontiers = [table.frontier(item) for item in result.frontiers]
    branch_proofs = [table.pack(item) for item in result.branch_proofs]
    binding_proofs = [table.pack(item) for item in result.binding_proofs]
    route_refutations = [table.pack(item) for item in result.route_refutations]
    return {'schema': 'scar.program-value-analysis', 'schema_version': 3, 'roots': roots,
        **table.tables, 'facts': facts, 'frontiers': frontiers, 'branch_proofs': branch_proofs,
        'binding_proofs': binding_proofs,
        'route_refutations': route_refutations,
        'usage': result.usage,
        'fixed_point_reached': result.worklist_stable, 'query_scope_complete': result.exhausted,
        'whole_program_complete': False,
        'transformation_authorized': False,
        'qualification': 'Field-wise definition provenance and supported immutable builtin scalar/tuple content facts. '
            'Binding state knowledge is separate from payload; binding_states is only a convenience projection. '
            'Fixed-point convergence describes represented field constraints, separately from original query scope completeness. '
            'A source Point is not an ObjectID or content identity; conditions, proofs and unknown paths remain explicit.'}


def export_boundary_analysis(result):
    from scar.analysis.program_regions import BoundaryAnalysis
    if type(result) is not BoundaryAnalysis:
        raise TypeError('expected typed original region boundary')
    table = _Tables(result.cut.members)
    records = table.pack(result)
    # Derived API views reference records already present in the normalized
    # export. Keep read/write membership explicit without duplicating state.
    reads, writes = result.reads, result.writes
    records['reads'] = [number for number, state in enumerate(result.state) if state in reads]
    records['writes'] = [number for number, state in enumerate(result.state) if state in writes]
    records['control_dependencies'] = [table.edge(edge) for edge in result.control_dependencies]
    return {'schema': 'scar.program-region-boundary', 'schema_version': 2,
        **table.tables, 'boundary': records, 'whole_program_complete': False,
        'transformation_authorized': False,
        'qualification': 'A cut of original operations and field-wise interface/effect knowledge. '
            'Implementation transfers and outside consumers do not prove observable escape; missing contracts stay open.'}
