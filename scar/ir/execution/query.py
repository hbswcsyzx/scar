"""Read-only associations back to original program ports and evidence.

Queries expose declarations and precise validation gaps. They cannot turn an
association into native/runtime correspondence, content equality, or a proof.
"""
from __future__ import annotations

from copy import deepcopy
from dataclasses import dataclass

from scar.ir.program.ids import UseID, ValueID
from scar.ir.program.model import BlockArgument, CompletionResult, TerminatorKind
from scar.ir.program.drivers import BodyDriveResult
from scar.ir.program.resumption import ResumeInput, SavedInput, saved_actual_use
from .common import Unresolved
from .coordinates import AccessRef, ControlTransfer, OccurrencePhase, OccurrencePoint, UseOccurrence
from .ids import BlockVisitID, OperationOccurrenceID, QueuePrefixID, RegionActivationID, ValueOccurrenceID
from .validation import _analyze
from .work import ActualCompletionState, InvokeBoundaryStateEffect, WithinOperation
from .order import EventSignal, PrefixEnd, WorkEnd, WorkStart


@dataclass(frozen=True, slots=True)
class DefinitionLink:
    operation: OperationOccurrenceID
    use: UseID
    definition: ValueID
    occurrence: ValueOccurrenceID | Unresolved
    origin: OperationOccurrenceID | BlockVisitID | RegionActivationID | None


@dataclass(frozen=True, slots=True)
class FormalRoute:
    formal: ValueOccurrenceID
    transfer: ControlTransfer | None
    argument: UseID | CompletionResult | BodyDriveResult | ResumeInput | SavedInput | None
    source_use: UseOccurrence | None


class ExecutionIndex:
    def __init__(self, model, program, *, value_graphs=None, evidence_graphs=None, semantic_graphs=None):
        report, ctx = _analyze(model, program, value_graphs=value_graphs, evidence_graphs=evidence_graphs,
                               semantic_graphs=semantic_graphs)
        if not report.valid:
            raise ValueError('; '.join(f'{x.code} at {x.path}: {x.message}' for x in report.issues))
        self._ctx = ctx
        self.report = deepcopy(report)

    def _content_context(self):
        """Fresh external snapshots per content query, reusing canonical flow.

        The caller's mutable external graphs may have changed since this index
        was built. Recheck D/Q associations; never mutate the construction-time
        report or reuse its trusted external graph objects.
        """
        from copy import copy
        from .snapshot import ExternalSnapshots
        from .observation_validation import observation_errors
        from .content_validation import content_errors
        ctx = copy(self._ctx)
        ctx.issues, ctx.gaps, ctx._gap_keys = [], [], set()
        ctx.snapshots = ExternalSnapshots(ctx.value_graphs, ctx.evidence_graphs, ctx.semantic_graphs)
        observation_errors(ctx)
        content_errors(ctx)
        if ctx.issues:
            raise ValueError('; '.join(f'{x.code} at {x.path}: {x.message}' for x in ctx.issues))
        return ctx

    def denotation(self, value):
        """Canonical type/identity; content versions never stand for references."""
        from scar.ir.program.model import (
            DataValue, ReferenceValue, StateVersionValue, LocalBindingValue,
            ProtocolValue, LiteralOrigin,
        )
        ctx = self._content_context()
        row = ctx.values[value]
        definition = ctx.core_values[row.value]
        association = ctx.resolved_denotations.get(value)
        kind = {DataValue: 'data', ReferenceValue: 'reference', StateVersionValue: 'state',
                LocalBindingValue: 'binding', ProtocolValue: 'protocol'}[type(definition)]
        return deepcopy({'kind': kind, 'occurrence': row, 'definition': definition,
            'association': association,
            'literal': definition.origin if type(definition.origin) is LiteralOrigin else None,
            'gaps': tuple(ctx.gaps), 'source_runtime_verified': False,
            'transformation_authorized': False})

    def content_read(self, identity):
        """Original consumer/effect/selector associations, never ready=True."""
        from .content import ResourceConsumer, NativeWorkRead
        from .order import WorkStart, WorkEnd
        ctx = self._content_context()
        result = ctx.resolved_content_reads[identity]
        consumer = result['read'].consumer
        if type(consumer) is ResourceConsumer:
            conservative = (WorkStart(consumer.read.ticket), WorkEnd(consumer.read.ticket))
            interval = conservative
            native_interval = consumer.read.interval if type(consumer.read) is NativeWorkRead else None
        else:
            conservative = None
            native_interval = None
            interval = (result['observation_root'].interval if result['observation_root'] is not None
                        else consumer.interval)
        return deepcopy({**result, 'interval': interval, 'conservative_work_interval': conservative,
            'declared_native_interval': native_interval,
            'gaps': tuple(ctx.gaps), 'source_runtime_verified': False,
            'transformation_authorized': False})

    def observation_root(self, identity):
        """Resolve an explicit Q requirement to its actual value/endpoint."""
        from .observations import BoundEndpoint, OutputValue
        ctx = self._content_context()
        root = ctx.observation_roots[identity]
        requirement = ctx.observation_requirements[root.requirement]
        graph = ctx.external_semantic(requirement.contract.artifact, identity)
        actual = (ctx.requirements[root.actual.binding] if type(root.actual) is BoundEndpoint
                  else ctx.values[root.actual.value] if type(root.actual) is OutputValue else root.actual)
        return deepcopy({'root': root, 'requirement': requirement,
            'contract': None if graph is None else graph.contracts[requirement.contract.contract],
            'actual': actual, 'gaps': tuple(ctx.gaps), 'source_runtime_verified': False,
            'transformation_authorized': False})

    def definition_for_use(self, operation, use):
        """Original Use/definition plus its declared dynamic definition endpoint."""
        ctx = self._ctx
        binding = ctx.uses[operation, use]
        definition = ctx.core_uses[use][1].value
        row = None if type(binding.value) is Unresolved else ctx.values[binding.value]
        return deepcopy(DefinitionLink(operation, use, definition, binding.value, None if row is None else row.origin))

    def formal_route(self, value):
        """Actual predecessor port, without claiming copied data/object identity."""
        ctx = self._ctx
        row = ctx.values[value]
        core = ctx.core_values[row.value]
        if not isinstance(core.origin, BlockArgument):
            raise ValueError('formal_route requires a block argument occurrence')
        transfer = ctx.incoming.get(row.origin)
        if transfer is None:
            return deepcopy(FormalRoute(value, None, None, None))
        operation = ctx.core_operations[ctx.occurrences[transfer.operation].operation]
        argument = operation.terminator.successors[transfer.successor_index].arguments[core.origin.index]
        use = saved_actual_use(operation, argument)
        binding = None if use is None else ctx.uses.get((transfer.operation, use))
        return deepcopy(FormalRoute(value, transfer, argument, binding))

    def state_at(self, point):
        """Declared current state occurrences; None is explicitly unresolved."""
        ctx = self._ctx
        count = len(ctx.issues)
        ctx.check_point(point, 'query.state_at')
        if len(ctx.issues) != count:
            errors = ctx.issues[count:]
            del ctx.issues[count:]
            raise ValueError('; '.join(row.message for row in errors))
        current = ctx.current(point)
        return None if current is None else deepcopy(current)

    def occurrence(self, identity):
        ctx = self._ctx
        row = ctx.occurrences[identity]
        op = ctx.core_operations[row.operation]
        return deepcopy({
            'occurrence': row, 'operation': op,
            'uses': tuple(ctx.uses.get((identity, use.id)) for use in op.uses),
            'results': tuple(ctx.results.get((identity, value)) for value in op.results),
            'before': ctx.current(OccurrencePoint(identity, OccurrencePhase.BEFORE)),
            'after': ctx.current(OccurrencePoint(identity, OccurrencePhase.AFTER)),
            'transfer': ctx.outgoing.get(identity),
        })

    def resource_access(self, identity):
        ctx = self._ctx
        row = ctx.accesses[identity]
        binding = ctx.requirements[row.requirement]
        requirement = next(x for x in ctx.program.resource_requirements if x.id == binding.requirement)
        op = ctx.occurrences[row.operation].operation
        original = next(x for x in ctx.program.resource_uses if x.operation == op and x.requirement == requirement.id)
        return deepcopy({'access': row, 'binding': binding, 'requirement': requirement, 'original_use': original})

    def canonical_effect(self, effect):
        """Resolve original access/input and actual landing; no copied effects."""
        ctx = self._ctx
        if type(effect) is AccessRef:
            effect.__post_init__()
            occurrence = ctx.occurrences[effect.operation]
            operation = ctx.core_operations[occurrence.operation]
            if effect.index >= len(operation.accesses):
                raise ValueError('effect index does not select an original StateAccess')
            access = operation.accesses[effect.index]
            return deepcopy({'kind': 'access', 'reference': effect, 'operation': occurrence,
                'access': access, 'before': ctx.uses.get((occurrence.id, access.before)),
                'after': None if access.after is None else ctx.results.get((occurrence.id, access.after))})
        if type(effect) is not InvokeBoundaryStateEffect:
            raise TypeError('canonical_effect requires exact AccessRef or InvokeBoundaryStateEffect')
        if effect not in ctx.work_effects:
            raise ValueError('invoke boundary effect must be an existing validated work association')
        occurrence = ctx.occurrences[effect.invocation]
        operation = ctx.core_operations[occurrence.operation]
        transfer = ctx.outgoing.get(effect.invocation)
        post = None if type(effect.post) is not ActualCompletionState else ctx.values[effect.post.formal]
        return deepcopy({'kind': 'invoke_boundary', 'reference': effect, 'operation': occurrence,
            'input': ctx.uses.get((effect.state_input.operation, effect.state_input.use)),
            'actual_transfer': transfer, 'post': effect.post if post is None else post,
            'successor': None if transfer is None else operation.terminator.successors[transfer.successor_index]})

    def work(self, identity):
        """Keep host completion, terminal observations and quiescence separate."""
        ctx = self._ctx
        row = ctx.submissions[identity]
        host = None
        if type(row.origin) is WithinOperation:
            occurrence = ctx.occurrences[row.origin.operation]
            operation = ctx.core_operations[occurrence.operation]
            transfer = ctx.outgoing.get(row.origin.operation)
            if (transfer is not None and operation.terminator is not None
                    and operation.terminator.kind is TerminatorKind.INVOKE):
                host = operation.terminator.successors[transfer.successor_index].kind
        return deepcopy({'submission': row, 'host_completion': host,
            'outcomes': tuple(ctx.work_outcomes.get(identity, ())),
            'quiescences': tuple(ctx.work_quiescences.get(identity, ())),
            'retentions': tuple(ctx.work_retentions.get(identity, ())),
            'effects': tuple(self.canonical_effect(effect) for effect in row.effects),
            'source_runtime_verified': False, 'transformation_authorized': False})

    def queue_prefix(self, identity, *, budget=4096):
        """Inspect persistent predecessor links; this does not assert device HB."""
        if type(budget) is not int or budget <= 0:
            raise ValueError('queue-prefix query budget must be a positive integer')
        ctx = self._ctx
        current = ctx.queue_prefixes[identity]
        rows = []
        while len(rows) < budget:
            rows.append(current)
            if type(current.previous) is not QueuePrefixID:
                return deepcopy({'prefixes': tuple(rows), 'boundary': current.previous,
                                 'truncated': False, 'runtime_order_verified': False})
            current = ctx.queue_prefixes[current.previous]
        return deepcopy({'prefixes': tuple(rows), 'boundary': current.id,
                         'truncated': True, 'runtime_order_verified': False})

    def order_path(self, source, target, *, budget=4096):
        """A bounded conditional path, never completion, readiness or authority.

        Missing paths are UNRESOLVED, not proof of independence. Protocols and
        original association rows are returned as conditions in each step.
        """
        from collections import deque
        if type(budget) is not int or budget <= 0:
            raise ValueError('order query budget must be a positive integer')
        ctx = self._ctx
        for point in (source, target):
            if type(point) not in (WorkStart, WorkEnd, PrefixEnd, EventSignal):
                raise TypeError('order endpoints must be exact typed resource boundaries')
            point.__post_init__()
            registry, identity = ((ctx.submissions, point.ticket) if type(point) in (WorkStart, WorkEnd)
                                  else (ctx.queue_prefixes, point.prefix) if type(point) is PrefixEnd
                                  else (ctx.event_records, point.record))
            if identity not in registry:
                raise KeyError(identity)
        predecessor, pending = {source: None}, deque([source])
        examined, path, truncated = 0, (), False
        while pending and source != target:
            current = pending.popleft()
            for step in ctx.order_adjacency.get(current, ()):
                if examined >= budget:
                    truncated = True
                    break
                examined += 1
                if step.target in predecessor:
                    continue
                predecessor[step.target] = step
                pending.append(step.target)
                if step.target == target:
                    chain, cursor = [], target
                    while cursor != source:
                        link = predecessor[cursor]
                        chain.append(link)
                        cursor = link.source
                    path = tuple(reversed(chain))
                    break
            if path or truncated:
                break
        return deepcopy({'source': source, 'target': target,
            'status': 'CONDITIONAL' if path else 'UNRESOLVED', 'path': path,
            'truncated': truncated, 'examined_edges': examined, 'gaps': self.report.gaps,
            'runtime_order_verified': False, 'source_runtime_verified': False,
            'transformation_authorized': False})

    def work_order(self, producer, consumer, *, budget=4096):
        """Require producer completion before consumer *start*, not its end."""
        return self.order_path(WorkEnd(producer), WorkStart(consumer), budget=budget)

    def materialization_coverage(self, required, offered, *, budget=4096):
        """Compare declared storage selectors; never content or readiness.

        Materializations without a region need an explicit endpoint/selector
        mapping. They are not silently removed from the offered alternatives.
        The local resolver verifies one exact snapshot per artifact per query;
        the execution context's mutable external-graph cache is not reused.
        """
        from .coverage import (
            CoverageGap, CoverageStatus, RegionRef, _ValueCatalog, _storage_coverage,
        )
        from .resources import _record
        from .work import MaterializationRef
        from dataclasses import replace

        if type(budget) is not int or budget <= 0:
            raise ValueError('materialization coverage budget must be a positive integer')
        _record(required, MaterializationRef, 'required materialization')
        if type(offered) is not tuple:
            raise TypeError('offered materializations must be an exact tuple')
        for ref in offered:
            _record(ref, MaterializationRef, 'offered materialization')
        catalog = _ValueCatalog(self._ctx.value_graphs)
        gaps, resolved, unmapped = [], [], []
        used, regions = 0, {}

        def key(ref):
            artifact = ref.artifact
            return artifact.sha256, artifact.schema, artifact.size_bytes, ref.materialization

        def resolve(ref):
            graph = catalog.graph(ref.artifact)
            if graph is None:
                gaps.append(CoverageGap('external_graph_unavailable', None,
                    f'exact ValueGraph unavailable for {ref.materialization}; no URI is opened'))
                unmapped.append(ref)
                return None
            row = graph.materializations.get(ref.materialization)
            if row is None:
                raise ValueError('materialization is absent from the exact ValueGraph')
            region = None if row.region is None else RegionRef(ref.artifact, row.region)
            resolved.append({'reference': ref, 'materialization': row, 'region': region})
            if region is None:
                gaps.append(CoverageGap('materialization_region_unresolved', None,
                    f'{ref.materialization} requires an explicit endpoint placement/selector; region=None is not storage'))
                unmapped.append(ref)
            return region

        for ref in (required, *offered):
            if used >= budget:
                gaps.append(CoverageGap('geometry_budget_exhausted', None,
                    'shared coverage budget cannot visit all materialization references'))
                break
            used += 1
            if key(ref) not in regions:
                regions[key(ref)] = resolve(ref)

        geometry = None
        status = CoverageStatus.UNRESOLVED
        required_region = regions.get(key(required))
        all_visited = used == len(offered) + 1
        if all_visited and required_region is not None:
            available = tuple(regions[key(ref)] for ref in offered if regions[key(ref)] is not None)
            if used < budget:
                geometry = _storage_coverage(required_region, available, catalog=catalog, budget=budget - used)
                used += geometry.budget_used
                status = geometry.status
                if unmapped and status is CoverageStatus.INCOMPLETE:
                    # Missing offered placements may cover currently missing
                    # bytes; absence of their geometry cannot prove a hole.
                    geometry = replace(geometry, status=CoverageStatus.UNRESOLVED,
                                       missing_intervals=None, gaps=(*geometry.gaps, *gaps))
                    status = CoverageStatus.UNRESOLVED
            else:
                gaps.append(CoverageGap('geometry_budget_exhausted', required_region,
                    'shared coverage budget was consumed by materialization references'))
        return deepcopy({'required': required, 'offered': offered,
            'resolved': tuple(resolved), 'unmapped': tuple(unmapped),
            'status': status.value, 'geometry': geometry, 'budget_used': used,
            'gaps': tuple(gaps) + (() if geometry is None else geometry.gaps),
            'execution_gaps': self.report.gaps,
            'source_runtime_verified': False, 'transformation_authorized': False})


__all__ = ['DefinitionLink', 'FormalRoute', 'ExecutionIndex']
