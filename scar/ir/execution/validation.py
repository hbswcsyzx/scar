"""Validate declared execution links without certifying source/runtime identity."""
from dataclasses import dataclass, fields, is_dataclass
import hashlib
import json

from scar.ir.program.codec import dumps as program_dumps
from scar.ir.program.model import BlockArgument, LiteralOrigin, OperationResult, StateVersionValue
from scar.ir.program.resumption import SuspendTerminator
from scar.ir.v2._validation import record_errors
from scar.ir.v2.values import ValueGraph
from scar.ir.v2.evidence import EvidenceGraph
from .common import EvidencePoint, MissingEvidence, Unresolved
from .coordinates import (
    CaptureIngress, InitialEntry, OccurrencePhase, OccurrencePoint, ResumeIngress,
    UnresolvedHostThread,
)
from .ids import BlockVisitID, OperationOccurrenceID, RegionActivationID
from .model import ExecutionModel
from .snapshot import external_bytes


@dataclass(frozen=True, slots=True)
class ExecutionIssue:
    code: str
    path: str
    message: str


@dataclass(frozen=True, slots=True)
class ValidationReport:
    issues: tuple[ExecutionIssue, ...]
    gaps: tuple[ExecutionIssue, ...]

    @property
    def valid(self):
        return not self.issues

    @property
    def source_runtime_verified(self):
        return False

    @property
    def transformation_authorized(self):
        return False


class _Context:
    def __init__(self, model, program, value_graphs, evidence_graphs):
        self.model, self.program = model, program
        self.issues, self.gaps = [], []
        self._gap_keys = set()
        self.value_graphs = {} if value_graphs is None else value_graphs
        self.evidence_graphs = {} if evidence_graphs is None else evidence_graphs
        self._external_cache = {}
        for name in ('runs', 'processes', 'threads', 'activations', 'segments', 'visits',
                     'operations', 'values', 'resources', 'realizations', 'requirements', 'handles', 'accesses',
                     'submissions', 'outcomes', 'quiescences', 'retentions', 'queue_prefixes'):
            registry = {}
            for row in getattr(model, name):
                if row.id in registry:
                    self.issue('duplicate_id', name, f'duplicate {row.id}')
                registry[row.id] = row
            setattr(self, 'occurrences' if name == 'operations' else name, registry)
        self.regions = {row.id: row for row in program.regions}
        self.blocks = {row.id: row for region in program.regions for row in region.blocks}
        self.block_regions = {row.id: region.id for region in program.regions for row in region.blocks}
        self.core_operations = {row.id: row for row in program.operations}
        self.core_values = {row.id: row for row in program.values}
        self.core_uses = {use.id: (row, use) for row in program.operations for use in row.uses}
        self.operation_blocks = {op: block for block in self.blocks.values() for op in block.operations}
        self.uses = {}
        for row in model.uses:
            key = row.operation, row.use
            if key in self.uses:
                self.issue('duplicate_use', 'uses', 'one dynamic Use has conflicting bindings')
            self.uses[key] = row
        self.results = {}
        for row in model.values:
            key = row.origin, row.value
            if key in self.results:
                self.issue('duplicate_definition', 'values', 'one dynamic definition has two value identities')
            self.results[key] = row
        self.incoming, self.outgoing = {}, {}
        self.before, self.after, self.edges = {}, {}, {}
        self.state_definitions_before, self.state_definitions_after, self.state_definitions_edges = {}, {}, {}
        self.visit_environments = {}
        self.work_effects = {effect for row in model.submissions for effect in row.effects}
        self.work_effects.update(effect for row in model.outcomes for effect in row.effect_frontier)
        self.work_outcomes, self.work_quiescences, self.work_retentions = {}, {}, {}
        for rows, registry in ((model.outcomes, self.work_outcomes), (model.quiescences, self.work_quiescences),
                               (model.retentions, self.work_retentions)):
            for row in rows:
                registry.setdefault(row.ticket, []).append(row)

    def issue(self, code, path, message):
        self.issues.append(ExecutionIssue(code, str(path), message))

    def gap(self, code, path, message):
        key = code, str(path), message
        if key not in self._gap_keys:
            self._gap_keys.add(key)
            self.gaps.append(ExecutionIssue(code, str(path), message))

    def activation_of(self, operation):
        return self.segments[self.visits[self.occurrences[operation].visit].segment].activation

    def value_activation(self, value):
        origin = self.values[value].origin
        if type(origin) is RegionActivationID:
            return origin
        if type(origin) is BlockVisitID:
            return self.segments[self.visits[origin].segment].activation
        return self.activation_of(origin)

    def _point_process(self, point):
        if type(point) is EvidencePoint:
            return point.process
        if point.operation in self.occurrences:
            activation = self.activation_of(point.operation)
            return self.activations[activation].process
        return None

    def check_point(self, point, path):
        if type(point) is EvidencePoint:
            if point.run not in self.runs:
                self.issue('point_run', path, 'evidence point references an unknown run')
            if point.process is not None:
                process = self.processes.get(point.process)
                if process is None or process.run != point.run:
                    self.issue('point_process', path, 'point process is absent or belongs to another run')
            return
        if type(point) is not OccurrencePoint:
            self.issue('point_type', path, 'expected exact OccurrencePoint or EvidencePoint')
            return
        if point.operation not in self.occurrences:
            self.issue('point_operation', path, 'point references an unknown operation occurrence')
            return
        if point.phase is OccurrencePhase.EDGE:
            op = self.core_operations[self.occurrences[point.operation].operation]
            if op.terminator is None or point.successor_index >= len(op.terminator.successors):
                self.issue('point_edge', path, 'point index does not select an actual canonical successor')
            elif point.operation in self.outgoing:
                if self.outgoing[point.operation].successor_index != point.successor_index:
                    self.issue('point_untaken_edge', path, 'this occurrence took a different successor')
            else:
                self.gap('point_edge_unobserved', path, 'the selected successor has no recorded transfer')

    def current(self, point):
        if type(point) is not OccurrencePoint:
            return None
        if point.phase is OccurrencePhase.BEFORE:
            return self.before.get(point.operation)
        if point.phase is OccurrencePhase.AFTER:
            return self.after.get(point.operation)
        return self.edges.get((point.operation, point.successor_index))

    def current_definitions(self, point):
        if type(point) is not OccurrencePoint:
            return None
        if point.phase is OccurrencePhase.BEFORE:
            return self.state_definitions_before.get(point.operation)
        if point.phase is OccurrencePhase.AFTER:
            return self.state_definitions_after.get(point.operation)
        return self.state_definitions_edges.get((point.operation, point.successor_index))

    def check_support(self, support, point, path):
        self.check_point(point, path)
        current = self.current(point)
        definitions = self.current_definitions(point)
        seen = set()
        for identity in support:
            row = self.values.get(identity)
            value = None if row is None else self.core_values.get(row.value)
            if not isinstance(value, StateVersionValue):
                self.issue('state_support', path, 'support must reference a canonical state occurrence')
                continue
            if value.location in seen:
                self.issue('state_support', path, 'support contains two versions of one location')
            seen.add(value.location)
            if type(point) is OccurrencePoint and point.operation in self.occurrences:
                if self.value_activation(identity) != self.activation_of(point.operation):
                    self.issue('state_support_scope', path, 'support belongs to another activation')
            if current is None or current.get(value.location) is None:
                expected = None if definitions is None else definitions.get(value.location)
                origin = (self.occurrences[row.origin].visit
                          if row.origin in self.occurrences else row.origin)
                if expected is not None and (row.value, origin) != expected:
                    self.issue('stale_state', path, 'support names an older canonical state definition despite a missing current observation')
                else:
                    self.gap('state_support_unresolved', path, 'current dynamic state is not established at this point')
            elif current[value.location] != identity:
                self.issue('stale_state', path, 'support is not the exact current dynamic state incarnation')

    def point_precedes(self, left, right):
        if type(left) is not OccurrencePoint or type(right) is not OccurrencePoint:
            return None
        if left.operation not in self.occurrences or right.operation not in self.occurrences:
            return None
        for point in (left, right):
            if point.phase is OccurrencePhase.EDGE:
                transfer = self.outgoing.get(point.operation)
                if transfer is None or transfer.successor_index != point.successor_index:
                    return None
        a, b = self.occurrences[left.operation], self.occurrences[right.operation]
        if self.activation_of(a.id) != self.activation_of(b.id):
            return None
        rank = {OccurrencePhase.BEFORE: 0, OccurrencePhase.AFTER: 1, OccurrencePhase.EDGE: 2}
        if a.visit == b.visit:
            block = self.blocks[self.visits[a.visit].block]
            return (block.operations.index(a.operation), rank[left.phase]) <= (
                block.operations.index(b.operation), rank[right.phase])
        cursor, visited = b.visit, set()
        while cursor not in visited and cursor in self.incoming:
            visited.add(cursor)
            cursor = self.occurrences[self.incoming[cursor].operation].visit
            if cursor == a.visit:
                return True
        return None

    def _external(self, artifact, path, kind, catalog):
        key = artifact.sha256, artifact.schema, artifact.size_bytes, kind
        if key in self._external_cache:
            return self._external_cache[key]
        graph = catalog.get(artifact.sha256)
        if graph is None:
            self.gap('external_graph_unavailable', path, 'exact external artifact has not been supplied')
            return None
        if type(graph) is not kind:
            self.issue('external_graph_type', path, 'supplied external graph has the wrong graph family')
            return None
        try:
            report = graph.validate()
            if not report['valid']:
                self.issue('external_graph_invalid', path, '; '.join(report['errors']))
                return None
            wire = external_bytes(graph)
        except (AttributeError, TypeError, ValueError, KeyError) as error:
            self.issue('external_graph_invalid', path, f'external graph shape or encoding is invalid: {error}')
            return None
        if (artifact.schema != graph.SCHEMA or len(wire) != artifact.size_bytes
                or hashlib.sha256(wire).hexdigest() != artifact.sha256):
            self.issue('external_snapshot', path, 'external bytes/schema/digest do not match the named artifact')
            return None
        self._external_cache[key] = graph
        return graph

    def external_values(self, artifact, path):
        return self._external(artifact, path, ValueGraph, self.value_graphs)


def _coordinates(ctx):
    m = ctx.model
    for row in m.processes:
        if row.run not in ctx.runs:
            ctx.issue('process_run', row.id, 'process belongs to an unknown run')
    for row in m.threads:
        if row.process not in ctx.processes:
            ctx.issue('thread_process', row.id, 'thread belongs to an unknown process incarnation')
    for row in m.activations:
        if row.region not in ctx.regions or row.process not in ctx.processes:
            ctx.issue('activation_owner', row.id, 'activation requires existing region and process')
        ctx.check_point(row.entry, row.id)
        if row.entry.process is not None and row.entry.process != row.process:
            ctx.issue('activation_scope', row.id, 'entry refers to another process')
        process = ctx.processes.get(row.process)
        if process is not None and row.entry.run != process.run:
            ctx.issue('activation_run', row.id, 'entry refers to another run')
    for row in m.segments:
        activation = ctx.activations.get(row.activation)
        if activation is None:
            ctx.issue('segment_activation', row.id, 'unknown activation')
            continue
        if isinstance(row.host_thread, UnresolvedHostThread):
            ctx.check_point(row.host_thread.point, row.id)
            ctx.gap('host_thread_unresolved', row.id, row.host_thread.reason)
            unresolved = row.host_thread.point
            process = ctx.processes.get(activation.process)
            if ((unresolved.process is not None and unresolved.process != activation.process)
                    or (process is not None and unresolved.run != process.run)):
                ctx.issue('segment_unresolved_thread_scope', row.id, 'unresolved thread point belongs to another process/run')
        else:
            thread = ctx.threads.get(row.host_thread)
            if thread is None or thread.process != activation.process:
                ctx.issue('segment_thread', row.id, 'segment thread belongs to another process or is absent')
        ctx.check_point(row.ingress.source, row.id)
        process = ctx.processes.get(activation.process)
        if process is not None and row.ingress.source.run != process.run:
            ctx.issue('segment_scope', row.id, 'segment ingress belongs to another run')
        if row.ingress.source.process is not None and row.ingress.source.process != activation.process:
            ctx.issue('segment_scope', row.id, 'segment ingress belongs to another process')
        if isinstance(row.ingress, CaptureIngress):
            ctx.gap('capture_ingress', row.id, row.ingress.reason)
    for row in m.visits:
        segment = ctx.segments.get(row.segment)
        if segment is None or row.block not in ctx.blocks:
            ctx.issue('visit_owner', row.id, 'visit needs an existing segment and canonical block')
        elif segment.activation in ctx.activations and ctx.block_regions[row.block] != ctx.activations[segment.activation].region:
            ctx.issue('visit_region', row.id, 'block does not belong to this activation region')
    if ctx.issues:
        return
    occupied = set()
    for row in m.operations:
        visit = ctx.visits.get(row.visit)
        if visit is None or row.operation not in ctx.core_operations:
            ctx.issue('occurrence_owner', row.id, 'operation occurrence references missing visit/operation')
        elif row.operation not in ctx.blocks[visit.block].operations:
            ctx.issue('occurrence_block', row.id, 'operation does not occur in this canonical block')
        key = row.visit, row.operation
        if key in occupied:
            ctx.issue('duplicate_operation_visit', row.id, 'one operation executes at most once per block visit')
        occupied.add(key)
    if ctx.issues:
        return
    for row in m.values:
        value = ctx.core_values.get(row.value)
        if value is None:
            ctx.issue('value_definition', row.id, 'unknown static value definition')
            continue
        origin = value.origin
        if type(row.origin) is OperationOccurrenceID:
            producer = ctx.occurrences.get(row.origin)
            good = (producer is not None and isinstance(origin, OperationResult)
                    and producer.operation == origin.operation and row.value in ctx.core_operations[producer.operation].results)
            activation = None if producer is None else ctx.activation_of(producer.id)
        elif type(row.origin) is BlockVisitID:
            visit = ctx.visits.get(row.origin)
            good = visit is not None and isinstance(origin, BlockArgument) and visit.block == origin.block
            activation = None if visit is None else ctx.segments[visit.segment].activation
        else:
            activation = row.origin
            good = activation in ctx.activations and isinstance(origin, LiteralOrigin)
        if not good or activation not in ctx.activations or ctx.activations[activation].region != value.region:
            ctx.issue('value_origin', row.id, 'dynamic definition does not match the exact canonical producer/formal/literal')
    if ctx.issues:
        return
    for row in m.uses:
        occurrence = ctx.occurrences.get(row.operation)
        site = ctx.core_uses.get(row.use)
        if occurrence is None or site is None or site[0].id != occurrence.operation:
            ctx.issue('use_owner', row.use, 'Use is not owned by this operation occurrence')
        elif isinstance(row.value, Unresolved):
            ctx.gap('use_unresolved', row.use, row.value.reason)
        elif row.value not in ctx.values or ctx.values[row.value].value != site[1].value:
            ctx.issue('use_definition', row.use, 'dynamic operand references another static value definition')
        elif ctx.value_activation(row.value) != ctx.activation_of(row.operation):
            ctx.issue('use_activation', row.use, 'operand comes from another activation rather than its own formal')


def _flow(ctx):
    from .flow import derive_flow
    derive_flow(ctx)


def _evidence_gaps(ctx):
    """Retain precise declared gaps; references never imply runtime proof."""
    def visit(value, path):
        if type(value) is EvidencePoint:
            ctx.check_point(value, path)
        if type(value) is MissingEvidence:
            ctx.gap('evidence_missing', path, value.reason)
        if type(value) is Unresolved:
            ctx.gap('unresolved', path, value.reason)
        if is_dataclass(value):
            for field in fields(value):
                visit(getattr(value, field.name), f'{path}.{field.name}')
        elif type(value) is tuple:
            for index, item in enumerate(value):
                visit(item, f'{path}[{index}]')
    visit(ctx.model, 'model')


def _analyze(model, program, *, value_graphs=None, evidence_graphs=None):
    if type(model) is not ExecutionModel:
        return ValidationReport((ExecutionIssue('record', 'model', 'expected exact ExecutionModel'),), ()), None
    for name, catalog in (('value_graphs', value_graphs), ('evidence_graphs', evidence_graphs)):
        if catalog is not None and (type(catalog) is not dict or any(type(key) is not str for key in catalog)):
            return ValidationReport((ExecutionIssue('catalog_type', name, 'expected dict keyed by artifact SHA256 strings'),), ()), None
    try:
        errors = record_errors(model, ExecutionModel, 'ExecutionModel')
        if errors:
            return ValidationReport(tuple(ExecutionIssue('record', 'model', e) for e in errors), ()), None
        wire = program_dumps(program).encode('utf-8')
    except (TypeError, ValueError, AttributeError) as error:
        return ValidationReport((ExecutionIssue('record_or_program', 'model', str(error)),), ()), None
    ctx = _Context(model, program, value_graphs, evidence_graphs)
    artifact = model.snapshot.artifact
    if (artifact.schema != 'scar.program-graph' or artifact.sha256 != hashlib.sha256(wire).hexdigest()
            or artifact.size_bytes != len(wire) or model.snapshot.schema_version != json.loads(wire)['schema_version']):
        ctx.issue('program_snapshot', 'snapshot', 'canonical program bytes/schema/version/digest mismatch')
    _coordinates(ctx)
    if not ctx.issues:
        _flow(ctx)
    if not ctx.issues:
        _evidence_gaps(ctx)
    if not ctx.issues:
        from .resource_validation import resource_errors
        resource_errors(ctx)
    if not ctx.issues:
        from .work_validation import work_errors
        work_errors(ctx)
    if not ctx.issues:
        for row in model.evidence_bindings:
            if row.operation not in ctx.occurrences:
                ctx.issue('evidence_occurrence', 'evidence_bindings', 'missing core occurrence endpoint')
            graph = ctx._external(row.legacy.artifact, 'evidence_bindings', EvidenceGraph, ctx.evidence_graphs)
            if graph is not None and row.legacy.instance not in graph.instances:
                ctx.issue('evidence_instance', 'evidence_bindings', 'missing exact legacy instance endpoint')
    # Evidence reference presence is not native/source/runtime applicability.
    ctx.gap('source_runtime_unverified', 'model', 'declared occurrence/identity links have not been established by a runtime adapter')
    return ValidationReport(tuple(ctx.issues), tuple(ctx.gaps)), ctx


def validate(model, program, *, value_graphs=None, evidence_graphs=None):
    return _analyze(model, program, value_graphs=value_graphs, evidence_graphs=evidence_graphs)[0]


def require_valid(model, program, *, value_graphs=None, evidence_graphs=None):
    report = validate(model, program, value_graphs=value_graphs, evidence_graphs=evidence_graphs)
    if report.issues:
        raise ValueError('; '.join(f'{row.code} at {row.path}: {row.message}' for row in report.issues))
    return report


__all__ = ['ExecutionIssue', 'ValidationReport', 'validate', 'require_valid']
