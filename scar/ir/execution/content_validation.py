"""Resolve content associations to canonical ports, without readiness proof.

Source artifacts are parsed as their closed SCAR schemas. Their port, run and
native protocol gaps remain explicit; arbitrary FactReferences are not proofs.
"""
from scar.ir.program.model import (
    AccessMode, DataValue, ReferenceValue, StateVersionValue, TerminatorKind,
)
from scar.ir.v2.evidence import EvidenceGraph, EvidenceNodeKind as N, EvidenceRelation as R
from scar.ir.v2.common import Completeness
from .common import EvidencePoint, Unresolved
from .content import (
    DataIdentity, EndpointContent, EvidenceEdgeRef, EvidenceObservationRef,
    HostConsumer, NativeInputRef, NativeOutputRef, NativeWorkRead, ObjectIdentity,
    ObservationConsumer, ProtocolSelector, ResourceConsumer, StorageContent,
)
from .coordinates import AccessRef, InitialEntry, OccurrencePhase, OccurrencePoint, UseRef
from .endpoint_protocol import (
    endpoint_extent, resolve_endpoint_profile, same_fact_reference,
)
from .effects import effect_context, resolve_canonical_effect
from .ids import OperationOccurrenceID
from .coverage import CoverageStatus, RegionRef, _ValueCatalog, _storage_coverage
from .resources import AllocationTarget, InstanceTarget, ProcessRealm, ProcessTarget, ThreadTarget
from .work import DirectExecution, InvokeBoundaryStateEffect, Queued, WithinOperation


def artifact_key(artifact):
    return artifact.sha256, artifact.schema, artifact.size_bytes


def target_key(target):
    if type(target) is AllocationTarget:
        return type(target), artifact_key(target.artifact), target.allocation
    return type(target), (target.instance if type(target) is InstanceTarget else target.process
                          if type(target) is ProcessTarget else target.thread)


def point_scope(ctx, point):
    if type(point) is EvidencePoint:
        return point.run, point.process
    if type(point) is OccurrencePoint and point.operation in ctx.occurrences:
        activation = ctx.activations[ctx.activation_of(point.operation)]
        return ctx.processes[activation.process].run, activation.process
    return None, None


def check_interval(ctx, interval, path):
    """Host order is checked where known; it is not a native clock mapping."""
    ctx.check_point(interval.start, path)
    ctx.check_point(interval.end, path)
    left, right = point_scope(ctx, interval.start), point_scope(ctx, interval.end)
    for a, b in zip(left, right):
        if a is not None and b is not None and a != b:
            ctx.issue('content_interval_scope', path, 'read interval crosses known runs/process incarnations')
    order = ctx.point_precedes(interval.start, interval.end)
    if order is False:
        ctx.issue('content_interval_order', path, 'read interval ends before its start')
    elif order is None:
        ctx.gap('content_interval_order_unresolved', path, 'cross-activation/native interval ordering is not established')
    ctx.gap('content_interval_protocol_unverified', path,
            'protocol reference is not a parsed native read-interval/clock correspondence')


def _align_interval(ctx, interval, operation, path, *, host):
    if operation not in ctx.occurrences:
        return
    before = OccurrencePoint(operation, OccurrencePhase.BEFORE)
    after = OccurrencePoint(operation, OccurrencePhase.AFTER)
    expected = point_scope(ctx, before)
    for point in (interval.start, interval.end):
        actual = point_scope(ctx, point)
        pairs = zip(expected, actual) if host else ((expected[0], actual[0]),)
        if any(a is not None and b is not None and a != b for a, b in pairs):
            ctx.issue('content_interval_subject_scope', path, 'read interval conflicts with original subject run/process')
    if host:
        if (ctx.point_precedes(before, interval.start) is False
                or ctx.point_precedes(interval.end, after) is False):
            ctx.issue('content_interval_subject_order', path, 'host read interval lies outside its original operation occurrence')


def check_target(ctx, target, path):
    if type(target) is AllocationTarget:
        graph = ctx.external_values(target.artifact, path)
        if graph is not None and target.allocation not in graph.allocations:
            ctx.issue('content_target', path, 'allocation is absent from its exact ValueGraph')
    else:
        registry, identity = ((ctx.resources, target.instance) if type(target) is InstanceTarget
                              else (ctx.processes, target.process) if type(target) is ProcessTarget
                              else (ctx.threads, target.thread))
        if identity not in registry:
            ctx.issue('content_target', path, 'resource target references an absent incarnation')


def resolve_subject(ctx, subject, path):
    occurrence = ctx.occurrences.get(subject.operation)
    if occurrence is None:
        ctx.issue('content_subject_operation', path, 'subject references an absent operation occurrence')
        return None
    operation = ctx.core_operations[occurrence.operation]
    if type(subject) is UseRef:
        original = ctx.core_uses.get(subject.use)
        if original is None or original[0].id != operation.id:
            ctx.issue('content_subject_use', path, 'subject is not an original Use of this occurrence')
            return None
        actual = ctx.uses.get((subject.operation, subject.use))
        if actual is None or type(actual.value) is Unresolved:
            ctx.gap('content_subject_unobserved', path, 'original Use has no exact observed value occurrence')
        value = None if actual is None or type(actual.value) is Unresolved else ctx.values[actual.value]
        return {'subject': subject, 'operation': occurrence, 'use': original[1],
                'actual': actual, 'value': value, 'definition': ctx.core_values[original[1].value],
                'access': None, 'before': None}
    resolved = resolve_canonical_effect(effect_context(ctx, issue=lambda code, p, message: ctx.issue(
        {'effect_operation': 'content_subject_operation', 'effect_access': 'content_subject_access'}.get(
            code, 'content_subject_access'), p, message)), subject, path)
    if resolved is None:
        return None
    access = resolved['access']
    if access.mode is AccessMode.WRITE:
        ctx.issue('content_subject_write', path, 'a write-only StateAccess is not a content read')
    before = resolved['before']
    if before is None or type(before.value) is Unresolved:
        ctx.gap('content_subject_unobserved', path, 'StateAccess has no exact observed before state')
    reference = resolved['reference_use']
    return {'subject': subject, 'operation': occurrence, 'access': access, 'before': before,
            'reference': reference, 'value': None, 'actual': None, 'use': None}


def native_port(ctx, basis, path):
    """Locate declared native signature slots through actual canonical ports."""
    boundary = next((row for row in ctx.program.native_boundaries if row.id == basis.boundary), None)
    if boundary is None:
        ctx.issue('content_native_boundary', path, 'native boundary does not exist in ProgramGraph')
        return None
    slots = boundary.inputs if type(basis) is NativeInputRef else boundary.outputs
    if basis.position >= len(slots):
        ctx.issue('content_native_position', path, 'position is not a native signature slot')
        return None
    port = slots[basis.position].port
    if type(basis) is NativeInputRef:
        visit = ctx.visits.get(basis.entry)
        if visit is None:
            ctx.issue('content_native_entry', path, 'native input requires an actual entry block visit')
            return None
        segment = ctx.segments[visit.segment]
        region = ctx.regions[port.region]
        if visit.block != region.entry or ctx.activations[segment.activation].region != port.region:
            ctx.issue('content_native_entry', path, 'visit does not enter the exact native region')
            return None
        if basis.entry in ctx.incoming or type(segment.ingress) is not InitialEntry:
            ctx.issue('content_native_initial_entry', path, 'loop/resume/capture visits cannot replace initial native entry')
        value = ctx.results.get((basis.entry, port.value))
        if value is None:
            ctx.gap('content_native_value_unobserved', path, 'native entry formal occurrence has not been observed')
        return {'boundary': boundary, 'slot': slots[basis.position], 'value': value, 'use': None}
    occurrence = ctx.occurrences.get(basis.operation)
    if occurrence is None:
        ctx.issue('content_native_exit', path, 'native output requires an actual Return/Raise occurrence')
        return None
    operation = ctx.core_operations[occurrence.operation]
    term = operation.terminator
    if (ctx.activations[ctx.activation_of(occurrence.id)].region != port.region
            or term is None or term.kind not in (TerminatorKind.RETURN, TerminatorKind.RAISE)
            or term.exit != port.exit_name or port.index >= len(term.values)):
        ctx.issue('content_native_exit', path, 'output slot does not match the actual canonical completion')
        return None
    use = ctx.uses.get((occurrence.id, term.values[port.index]))
    value = None if use is None or type(use.value) is Unresolved else ctx.values[use.value]
    if value is None:
        ctx.gap('content_native_value_unobserved', path, 'native output Use has no observed value occurrence')
    return {'boundary': boundary, 'slot': slots[basis.position], 'value': value, 'use': use}


def _evidence(ctx, artifact, path):
    return ctx._external(artifact, path, EvidenceGraph, ctx.evidence_graphs)


def _version(ctx, ref, path):
    graph = ctx.external_values(ref.artifact, path)
    if graph is not None and ref.version not in graph.versions:
        ctx.issue('content_version', path, 'version is absent from the exact ValueGraph')
    return graph


def _object(ctx, ref, path):
    if ref.artifact.schema == EvidenceGraph.SCHEMA:
        graph = _evidence(ctx, ref.artifact, path)
        if graph is not None and (N.OBJECT, ref.object.wire) not in graph.external_references:
            ctx.issue('content_object', path, 'object is absent from the exact EvidenceGraph registry')
    else:
        graph = ctx.external_values(ref.artifact, path)
        if graph is not None and not graph.has_object(ref.object):
            ctx.issue('content_object', path, 'object is absent from the exact ValueGraph object registry')


def _paired(ctx, artifact, instance, operation, ticket, path):
    matches = ()
    if ticket is not None:
        bindings = [row for row in ctx.model.work_evidence_bindings if row.ticket == ticket]
        matches = tuple(row for row in bindings if artifact_key(row.artifact) == artifact_key(artifact)
                        and row.instance == instance)
        if not matches:
            ctx.gap('content_work_source_unresolved', path,
                    'no exact work-to-source pair for this consumer; other partial bindings do not prove exclusion or supply this join')
    elif operation is not None:
        bindings = [row for row in ctx.model.evidence_bindings if row.operation == operation]
        matches = tuple(row for row in bindings if artifact_key(row.legacy.artifact) == artifact_key(artifact)
                        and row.legacy.instance == instance)
        if not matches:
            ctx.gap('content_operation_source_unresolved', path,
                    'no exact occurrence-to-source pair; partial bindings and parent relationships do not supply this join')
        elif operation in ctx.occurrences:
            graph = _evidence(ctx, artifact, path)
            original = None if graph is None else graph.instances.get(instance)
            process = ctx.processes[ctx.activations[ctx.activation_of(operation)].process]
            if (original is not None and type(original.process_id) is int and process.pid is not None
                    and original.process_id != process.pid):
                ctx.issue('content_operation_process', path, 'matched occurrence and source have conflicting known process IDs')
    ctx.gap('content_source_run_unverified', path,
            'EEG process IDs and association rows do not establish native run/port correspondence')
    return matches


def resolve_basis(ctx, basis, path, *, identity=None, placement=None, operation=None,
                  ticket=None, expected_value=None, require_read=False):
    """Parse source rows and reject known mismatches; never infer port ordinals."""
    if type(basis) is Unresolved:
        ctx.gap('content_basis_unresolved', path, basis.reason)
        return None
    if type(basis) in (NativeInputRef, NativeOutputRef):
        resolved = native_port(ctx, basis, path)
        if resolved is not None and expected_value is not None and resolved['value'] is not None:
            if resolved['value'].id != expected_value:
                ctx.issue('content_native_actual', path, 'native slot selects another actual value incarnation')
        evidence = ctx.native_port_evidence
        scalar = (evidence.resolve_scalar(ctx, basis, resolved, identity, path)
                  if evidence is not None and type(identity) is DataIdentity else None)
        if scalar is not None:
            from .native_port_protocol import NativeScalarObservation
            if type(scalar) is not NativeScalarObservation:
                ctx.issue('native_scalar_content', path, 'native scalar content requires the exact owned typed query result')
            else:
                resolved['scalar_content'] = scalar
                ctx.gap('native_scalar_upstream_unproved', path, 'observed scalar input root has no established upstream producer')
                if require_read:
                    ctx.gap('native_scalar_read_effect_unproved', path, 'input content alone does not prove a content-read effect')
                # Exact local input content is distinct from upstream lineage,
                # Python identity, native writes, complete state and readiness.
                return resolved
        reference_matched = (evidence is not None
            and evidence.resolve(ctx, basis, resolved, identity, path))
        if not reference_matched:
            ctx.gap('content_native_correspondence_unverified', path,
                    'native slot association does not prove physical work/input or content correspondence')
        else:
            ctx.gap('native_reference_content_unproved', path,
                    'held reference correspondence does not prove contents, complete state/alias effects or readiness')
        return resolved
    graph = _evidence(ctx, basis.artifact, path)
    if graph is None:
        return None
    observation, edge, endpoint, instance = None, None, None, None
    if type(basis) is EvidenceObservationRef:
        observation = graph.observations.get(basis.observation)
        if observation is None:
            ctx.issue('content_evidence_observation', path, 'source observation is absent from exact artifact')
            return None
        instance = observation.operation
        if require_read:
            ctx.gap('content_read_relation_unresolved', path, 'observation role strings do not establish an observed read')
    else:
        edge = graph.edges.get(basis.edge)
        if edge is None:
            ctx.issue('content_evidence_edge', path, 'source edge is absent from exact artifact')
            return None
        if require_read and edge.relation is not R.OBSERVED_READ:
            ctx.issue('content_read_relation', path, 'a content read must reference an OBSERVED_READ edge')
        if edge.source.kind is N.OPERATION_INSTANCE:
            instance, endpoint = edge.source.reference, edge.target
        else:
            ctx.gap('content_evidence_operation_unresolved', path, 'source relation does not identify the actual reader/producer operation')
            endpoint = edge.target
        if endpoint.kind is N.VALUE_OBSERVATION:
            observation = graph.observations[endpoint.reference]
            if observation.operation is not None and instance is not None and observation.operation != instance:
                ctx.issue('content_observation_owner', path, 'source edge and observation name different operation instances')
    correspondence = ()
    if instance is not None:
        correspondence = _paired(ctx, basis.artifact, instance, operation, ticket, path)
    elif ticket is not None or operation is not None:
        ctx.gap('content_evidence_operation_unresolved', path, 'source has no actual operation endpoint')
    source_version = None if observation is None else observation.version
    source_mat = None if observation is None else observation.materialization
    source_object = None
    if endpoint is not None:
        if endpoint.kind is N.VALUE_VERSION:
            source_version = endpoint.reference
        elif endpoint.kind is N.MATERIALIZATION:
            source_mat = endpoint.reference
        elif endpoint.kind is N.OBJECT:
            source_object = endpoint.reference
    expected_version = identity.version.version if type(identity) is DataIdentity else None
    if type(identity) is DataIdentity and source_mat is not None:
        values = ctx.external_values(identity.version.artifact, path)
        if values is not None:
            original_mat = values.materializations.get(source_mat)
            if original_mat is None:
                ctx.issue('content_source_materialization', path, 'source materialization is absent from the scoped denotation ValueGraph')
            elif original_mat.value_version != identity.version.version:
                ctx.issue('content_source_version', path, 'source materialization contains another logical version')
    if type(identity) is ObjectIdentity:
        if source_object is not None and source_object != identity.object.object:
            ctx.issue('content_source_object', path, 'source endpoint names another object identity')
        elif source_object is None:
            ctx.gap('content_source_object_unresolved', path, 'source does not identify this object; a value observation is not object identity')
    if placement is not None:
        materialization, _ = placement
        if materialization is not None:
            if source_mat is not None and source_mat != materialization.id:
                ctx.issue('content_source_materialization', path, 'source refers to another physical materialization')
            if expected_version is not None and expected_version != materialization.value_version:
                ctx.issue('content_source_version', path, 'denotation and selected materialization have different versions')
            expected_version = materialization.value_version
    if expected_version is not None:
        if source_version is not None and source_version != expected_version:
            ctx.issue('content_source_version', path, 'source refers to another logical version')
        elif source_version is None and source_mat is None:
            ctx.gap('content_source_version_unresolved', path, 'source has no exact logical version/materialization endpoint')
    ctx.gap('content_exact_port_unresolved', path,
            'EEG schema has no Use/result ordinal; operation/value relation does not identify an exact original port')
    return {'edge': edge, 'observation': observation, 'instance': instance,
            'endpoint': endpoint, 'source_artifact': basis.artifact,
            'correspondence': correspondence}


def resolve_placement(ctx, placement, path):
    if type(placement) is Unresolved:
        ctx.gap('content_placement_unresolved', path, placement.reason)
        return None
    ref = placement.materialization
    graph = ctx.external_values(ref.artifact, path)
    if graph is None:
        return None
    mat = graph.materializations.get(ref.materialization)
    if mat is None:
        ctx.issue('content_materialization', path, 'materialization does not exist in exact ValueGraph')
        return None
    if type(placement) is StorageContent:
        if mat.region is None:
            ctx.issue('content_storage_region', path, 'storage-backed content requires the original materialization region')
            return mat, None
        declared = RegionRef(ref.artifact, mat.region)
        selector = declared if placement.selector is None else placement.selector
        if artifact_key(selector.artifact) != artifact_key(ref.artifact):
            ctx.issue('content_selector_scope', path, 'selector belongs to another exact ValueGraph artifact')
            return mat, None
        selected = graph.regions.get(selector.region)
        if selected is None:
            ctx.issue('content_selector', path, 'selector is absent from exact ValueGraph')
        elif selected.allocation != graph.regions[mat.region].allocation:
            ctx.issue('content_selector_allocation', path, 'selector belongs to another allocation incarnation')
        else:
            result = _storage_coverage(selector, (declared,),
                catalog=_ValueCatalog.from_snapshots(ctx.snapshots), budget=4096)
            if result.status is CoverageStatus.INCOMPLETE:
                ctx.issue('content_selector_outside', path, 'selector addresses bytes outside this materialization region')
            elif result.status is CoverageStatus.UNRESOLVED:
                ctx.gap('content_selector_coverage_unresolved', path, 'selector subset could not be established within geometry budget')
        return mat, selector
    check_target(ctx, placement.target, path)
    if type(placement.selector) is Unresolved:
        ctx.gap('content_selector_unresolved', path, placement.selector.reason)
    elif type(placement.selector) is ProtocolSelector:
        profile = resolve_endpoint_profile(ctx, placement.selector, path)
        if profile is None:
            ctx.gap('content_selector_protocol_unverified', path,
                    'endpoint selector has no interpreted byte-prefix profile')
    else:
        resolve_subject(ctx, placement.selector, path)
        ctx.gap('content_endpoint_selector_alignment', path, 'canonical selector needs endpoint/protocol correspondence')
    if mat.region is not None:
        ctx.issue('content_endpoint_storage', path, 'endpoint-backed content cannot discard a known storage-backed materialization region')
    return mat, placement.selector


def _content_interval(ctx, consumer, root):
    from .content import NativeWorkRead
    if type(consumer) is HostConsumer:
        return consumer.interval
    if type(consumer) is ResourceConsumer and type(consumer.read) is NativeWorkRead:
        return consumer.read.interval
    if type(consumer) is ObservationConsumer and root is not None:
        return root.interval
    return None


def content_errors(ctx):
    ctx.resolved_denotations, ctx.resolved_content_reads = {}, {}
    for row in ctx.model.work_evidence_bindings:
        path = f'work_evidence_bindings[{row.id}]'
        work = ctx.submissions.get(row.ticket)
        if work is None:
            ctx.issue('content_work_ticket', path, 'work evidence references an absent exact ticket')
        graph = _evidence(ctx, row.artifact, path)
        if graph is not None:
            instance = graph.instances.get(row.instance)
            if instance is None:
                ctx.issue('content_work_instance', path, 'work evidence instance is absent from exact artifact')
            elif work is not None:
                process = None
                if type(work.scheduling) is DirectExecution and type(work.scheduling.thread) is not Unresolved:
                    process = ctx.processes[ctx.threads[work.scheduling.thread].process]
                elif type(work.scheduling) is Queued:
                    access = ctx.accesses[work.scheduling.queue_access]
                    target = ctx.requirements[access.requirement].target
                    resource = ctx.resources.get(target.instance) if type(target) is InstanceTarget else None
                    if resource is not None and type(resource.realm) is ProcessRealm:
                        process = ctx.processes[resource.realm.process]
                if (process is not None and type(instance.process_id) is int and process.pid is not None
                        and instance.process_id != process.pid):
                    ctx.issue('content_work_process', path, 'work and source have conflicting known process IDs')
                elif process is None:
                    ctx.gap('content_work_process_unresolved', path, 'executor/queue process is not established; enclosing host caller is not execution-process proof')
        ctx.gap('content_work_correspondence_unverified', path, 'association is not a native work/run correspondence proof')
    for row in ctx.model.denotations:
        path = f'denotations[{row.id}]'
        actual = ctx.values.get(row.value)
        if actual is None:
            ctx.issue('content_denotation_value', path, 'denotation references an absent value occurrence')
            continue
        core = ctx.core_values[actual.value]
        if row.value in ctx.resolved_denotations:
            ctx.issue('content_denotation_duplicate', path, 'one value occurrence has more than one denotation row')
        if type(core) not in (DataValue, ReferenceValue):
            ctx.issue('content_denotation_kind', path, 'State/Binding/Protocol identities derive from canonical graph, not denotation rows')
        elif type(row.identity) is Unresolved:
            ctx.gap('content_denotation_unresolved', path, row.identity.reason)
        elif type(core) is DataValue and type(row.identity) is not DataIdentity:
            ctx.issue('content_denotation_kind', path, 'DataValue cannot denote an object reference')
        elif type(core) is ReferenceValue and type(row.identity) is not ObjectIdentity:
            ctx.issue('content_denotation_kind', path, 'ReferenceValue identity cannot permanently denote a content version')
        elif type(row.identity) is DataIdentity:
            _version(ctx, row.identity.version, path)
        else:
            _object(ctx, row.identity.object, path)
        source = resolve_basis(ctx, row.basis, path, identity=row.identity, expected_value=row.value,
                               operation=actual.origin if type(actual.origin) is OperationOccurrenceID else None)
        ctx.resolved_denotations[row.value] = {'denotation': row, 'value': actual, 'definition': core, 'basis': source}
    for row in ctx.model.content_reads:
        path = f'content_reads[{row.id}]'
        consumer, subject, actual, ticket, root = row.consumer, None, None, None, None
        if type(consumer) is ObservationConsumer:
            root = ctx.observation_roots.get(consumer.root)
            if root is None:
                ctx.issue('content_observation_root', path, 'observation consumer references an absent root')
            else:
                from .observations import BoundEndpoint, ExternalEndpoint, OutputValue
                if type(root.actual) is OutputValue:
                    actual = ctx.values.get(root.actual.value)
                if type(row.placement) is EndpointContent:
                    target = (ctx.requirements[root.actual.binding].target if type(root.actual) is BoundEndpoint
                              and root.actual.binding in ctx.requirements else root.actual.target
                              if type(root.actual) is ExternalEndpoint else None)
                    if target is not None and target_key(target) != target_key(row.placement.target):
                        ctx.issue('content_observation_target', path, 'placement names another target than the actual observation root')
        else:
            subject = resolve_subject(ctx, consumer.subject, path)
            actual = None if subject is None else subject['value']
            if type(consumer) is HostConsumer:
                check_interval(ctx, consumer.interval, path)
                _align_interval(ctx, consumer.interval, consumer.subject.operation, path, host=True)
            else:
                ticket = consumer.read.ticket
                work = ctx.submissions.get(ticket)
                if work is None:
                    ctx.issue('content_consumer_ticket', path, 'consumer work ticket is absent')
                elif subject is not None and type(work.origin) is WithinOperation and work.origin.operation != consumer.subject.operation:
                    original_run = point_scope(ctx, OccurrencePoint(consumer.subject.operation, OccurrencePhase.BEFORE))[0]
                    work_run = point_scope(ctx, OccurrencePoint(work.origin.operation, OccurrencePhase.BEFORE))[0]
                    if original_run != work_run:
                        ctx.issue('content_consumer_run', path, 'consumer work and original subject belong to different runs')
                    if ctx.activation_of(work.origin.operation) == ctx.activation_of(consumer.subject.operation):
                        ctx.issue('content_consumer_owner', path, 'subject belongs to another sequential submission occurrence')
                    else:
                        ctx.gap('content_consumer_nested_alignment', path, 'nested host/native work mapping has not been established')
                elif work is not None and type(work.origin) is not WithinOperation and subject is not None:
                    original_run = point_scope(ctx, OccurrencePoint(consumer.subject.operation, OccurrencePhase.BEFORE))[0]
                    if work.origin.point.run != original_run:
                        ctx.issue('content_consumer_run', path, 'external consumer work and original subject belong to different runs')
                if type(consumer.read) is NativeWorkRead:
                    check_interval(ctx, consumer.read.interval, path)
                    _align_interval(ctx, consumer.read.interval, consumer.subject.operation, path, host=False)
                    ctx.gap('content_native_read_interval_unverified', path, 'narrow native interval cannot replace whole-work stability without parsed correspondence')
        if type(row.anchor) is Unresolved:
            ctx.gap('content_anchor_unresolved', path, row.anchor.reason)
            if row.support:
                ctx.issue('content_support_anchor', path, 'state support cannot claim currency at an unresolved anchor')
        else:
            ctx.check_support(row.support, row.anchor, path)
            if subject is not None and row.anchor != OccurrencePoint(consumer.subject.operation, OccurrencePhase.BEFORE):
                ctx.issue('content_anchor_subject', path, 'input read anchor must select its original occurrence BEFORE state')
            if root is not None and type(root.anchor) is OccurrencePoint and row.anchor != root.anchor:
                ctx.issue('content_observation_anchor', path, 'content read and actual observation root have different state anchors')
        if subject is not None and subject['access'] is not None:
            if row.effect != consumer.subject:
                ctx.issue('content_effect_subject', path, 'StateAccess read must retain its exact original effect')
            before = subject['before']
            if before is not None and type(before.value) is not Unresolved and before.value not in row.support:
                ctx.issue('content_missing_state_support', path, 'read omits the exact original before-state occurrence')
        elif actual is not None or subject is not None:
            core = ctx.core_values[actual.value] if actual is not None else subject['definition']
            if type(core) is ReferenceValue and row.effect is None:
                ctx.issue('content_reference_effect', path, 'reference content read requires state effect or explicit unresolved effect')
            elif type(core) not in (DataValue, ReferenceValue):
                ctx.issue('content_subject_kind', path, 'State/Binding/Protocol token Use is not an intrinsic content read')
        if type(row.effect) is Unresolved:
            ctx.gap('content_effect_unresolved', path, row.effect.reason)
        elif type(row.effect) is AccessRef:
            effect = resolve_subject(ctx, row.effect, path)
            if effect is not None:
                before = effect['before']
                if before is not None and type(before.value) is not Unresolved and before.value not in row.support:
                    ctx.issue('content_missing_state_support', path, 'effect before-state is absent from read support')
                if subject is not None and type(consumer.subject) is UseRef:
                    access = effect['access']
                    if row.effect.operation != consumer.subject.operation:
                        ctx.issue('content_effect_owner', path, 'read effect belongs to a different occurrence')
                    elif access.reference is None:
                        ctx.gap('content_reference_alignment_unresolved', path, 'original StateAccess does not identify this reference Use')
                    elif access.reference != consumer.subject.use:
                        ctx.issue('content_effect_reference', path, 'original StateAccess identifies another reference Use')
        elif type(row.effect) is InvokeBoundaryStateEffect:
            def invoke_effect_issue(code, p, message):
                ctx.issue('content_invoke_effect', p, message)

            view = resolve_canonical_effect(effect_context(
                ctx, issue=invoke_effect_issue, gap=lambda _code, _path, _message: None), row.effect, path)
            if view is not None:
                if type(consumer) is ResourceConsumer:
                    work = ctx.submissions.get(consumer.read.ticket)
                    if work is not None and row.effect not in work.effects:
                        if work.effects_coverage is Completeness.COMPLETE:
                            ctx.issue('content_invoke_effect', path,
                                      'boundary effect is absent from this consumer ticket complete effect list')
                        else:
                            ctx.gap('content_invoke_effect_unresolved', path,
                                    'this consumer ticket has partial or unknown effect coverage')
            if subject is not None and row.effect.invocation != consumer.subject.operation:
                ctx.issue('content_effect_owner', path, 'invoke effect belongs to a different operation occurrence')
            original = None if view is None else view['input']
            if original is not None and type(original.value) is not Unresolved and original.value not in row.support:
                ctx.issue('content_missing_state_support', path, 'boundary read omits original state input occurrence')
            ctx.gap('content_invoke_read_unverified', path, 'invoke boundary state transport is not a native read/footprint proof')
        placement = resolve_placement(ctx, row.placement, path)
        endpoint_profile, endpoint_range = None, None
        if type(row.placement) is EndpointContent:
            if type(row.placement.selector) is ProtocolSelector:
                endpoint_profile = resolve_endpoint_profile(ctx, row.placement.selector, path)
                if endpoint_profile is not None:
                    if endpoint_profile['operation'] != 'READ':
                        ctx.issue('content_endpoint_profile_role', path,
                                  'endpoint content read requires a READ byte profile')
                    endpoint_range = endpoint_extent(ctx, row.placement.target, endpoint_profile, path,
                        expected_operation='READ', materialization=row.placement.materialization)
                    interval = _content_interval(ctx, consumer, root)
                    if interval is None:
                        ctx.gap('content_endpoint_read_interval_unresolved', path,
                                'endpoint read has no original protocol interval to bind its profile')
                    else:
                        interval_profile = resolve_endpoint_profile(ctx, interval.protocol, path)
                        if interval_profile is not None:
                            if (interval_profile['operation'] != 'READ'
                                    or not same_fact_reference(
                                        interval_profile['reference'], endpoint_profile['reference'])):
                                ctx.issue('content_endpoint_read_profile', path,
                                          'endpoint selector and actual read interval use different profile facts')
                        else:
                            ctx.gap('content_endpoint_read_profile_unresolved', path,
                                    'read interval profile has no exact supported artifact')
            else:
                ctx.gap('content_endpoint_read_profile_unresolved', path,
                        'endpoint byte read requires an explicit ProtocolSelector extent')
        if type(consumer) is ResourceConsumer and type(row.placement) is not Unresolved:
            work = ctx.submissions.get(consumer.read.ticket)
            if work is not None:
                from .work_validation import check_work_materialization
                check_work_materialization(ctx, work, row.placement.materialization, path)
        denotation = None if actual is None else ctx.resolved_denotations.get(actual.id)
        identity = None if denotation is None else denotation['denotation'].identity
        if actual is not None and type(ctx.core_values[actual.value]) is DataValue and identity is None:
            ctx.gap('content_read_denotation_unresolved', path, 'Data input has no scoped logical version denotation')
        if type(identity) is DataIdentity and placement is not None and placement[0] is not None:
            if (artifact_key(identity.version.artifact) != artifact_key(row.placement.materialization.artifact)
                    or identity.version.version != placement[0].value_version):
                ctx.issue('content_denotation_materialization', path, 'Data denotation and selected materialization are not the same scoped version')
        if subject is not None and (subject['access'] is not None or actual is not None
                                   and type(ctx.core_values[actual.value]) is ReferenceValue):
            ctx.gap('content_state_version_unverified', path,
                    'current state/reference occurrence has no established correspondence to this materialization content version')
        operation = None if subject is None else consumer.subject.operation
        basis = resolve_basis(ctx, row.basis, path, identity=identity, placement=placement,
                              operation=operation, ticket=ticket,
                              expected_value=None if actual is None else actual.id, require_read=True)
        if type(consumer) is ResourceConsumer:
            input_basis = resolve_basis(ctx, consumer.input, path + '.consumer.input', identity=identity,
                placement=placement, operation=operation, ticket=ticket,
                expected_value=None if actual is None else actual.id, require_read=True)
        else:
            input_basis = None
        ctx.gap('content_read_stability_unverified', path,
                'host state at anchor does not prove stable content, lifetime or visibility across the actual read interval')
        ctx.resolved_content_reads[row.id] = {'read': row, 'subject': subject, 'actual': actual,
            'denotation': denotation, 'placement': placement, 'basis': basis,
            'consumer_input': input_basis, 'observation_root': root,
            'endpoint_profile': endpoint_profile, 'endpoint_extent': endpoint_range}


__all__ = ['content_errors', 'check_interval', 'check_target']
