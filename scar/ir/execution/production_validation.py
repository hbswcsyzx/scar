"""Conditional original write/result associations; no readiness authority."""
from scar.ir.program.model import (
    AccessMode, BlockArgument, CompletionResult, DataValue, LiteralOrigin,
    ReferenceValue, StateVersionValue, TerminatorKind,
)
from scar.ir.program.providers import ProviderFactReference
from scar.ir.v2.evidence import EvidenceRelation
from scar.ir.v2.common import Completeness
from .common import Unresolved
from .content import NativeOutputRef, StorageContent
from .content_validation import artifact_key, native_port, resolve_placement
from .coordinates import AccessRef, OccurrencePhase, OccurrencePoint
from .coverage import CoverageStatus, RegionRef, _ValueCatalog, _storage_coverage
from .ids import OperationOccurrenceID
from .production import (
    BytePrefixWrite, ExternalEstablishment, HostWrite, RawRecordRef,
    SourceEdgeRef, SourceEndpointRef, StateProduction, ValueProduction, WorkWrite,
)
from .work import ActualCompletionState, WithinOperation


def _effect(ctx, effect, path):
    """Resolve the original effect, including work-free host INVOKE effects."""
    if type(effect) is AccessRef:
        occurrence = ctx.occurrences.get(effect.operation)
        operation = None if occurrence is None else ctx.core_operations[occurrence.operation]
        if operation is None or effect.index >= len(operation.accesses):
            ctx.issue('production_effect', path, 'effect must select an existing original StateAccess')
            return None
        access = operation.accesses[effect.index]
        if access.mode is AccessMode.READ:
            ctx.issue('production_read_only', path, 'READ-only access cannot be a write production')
        before = ctx.uses.get((effect.operation, access.before))
        if before is not None and type(before.value) is not Unresolved:
            ctx.check_support((before.value,), OccurrencePoint(effect.operation, OccurrencePhase.BEFORE), path)
        return {'reference': effect, 'operation': occurrence, 'access': access, 'before': before,
                'after': None if access.after is None else ctx.results.get((effect.operation, access.after))}
    occurrence = ctx.occurrences.get(effect.invocation)
    operation = None if occurrence is None else ctx.core_operations[occurrence.operation]
    if operation is None or operation.terminator is None or operation.terminator.kind is not TerminatorKind.INVOKE:
        ctx.issue('production_invoke', path, 'boundary effect requires an actual canonical INVOKE')
        return None
    original = ctx.core_uses.get(effect.state_input.use)
    if (effect.state_input.operation != effect.invocation or original is None
            or original[0].id != operation.id or effect.state_input.use not in operation.invoke_arguments):
        ctx.issue('production_invoke_input', path, 'state input is not an exact original invoke argument')
        return None
    value = ctx.core_values[original[1].value]
    if not isinstance(value, StateVersionValue):
        ctx.issue('production_invoke_input', path, 'invoke state input must have canonical state type')
        return None
    before = ctx.uses.get((effect.invocation, effect.state_input.use))
    if before is not None and type(before.value) is not Unresolved:
        ctx.check_support((before.value,), OccurrencePoint(effect.invocation, OccurrencePhase.BEFORE), path)
    transfer = ctx.outgoing.get(effect.invocation)
    after = None
    if type(effect.post) is ActualCompletionState:
        post = effect.post
        successors = operation.terminator.successors
        if post.successor_index >= len(successors):
            ctx.issue('production_invoke_successor', path, 'post selects no original successor')
            return None
        successor = successors[post.successor_index]
        after = ctx.values.get(post.formal)
        definition = None if after is None else ctx.core_values[after.value]
        if (not isinstance(definition, StateVersionValue) or not isinstance(definition.origin, BlockArgument)
                or definition.origin.block != successor.block or definition.location != value.location):
            ctx.issue('production_invoke_formal', path, 'post is not the exact state/location landing formal')
        else:
            actual = successor.arguments[definition.origin.index]
            if not isinstance(actual, CompletionResult) or actual.index != post.result_index:
                ctx.issue('production_invoke_result', path, 'post does not match its original CompletionResult')
        if transfer is None:
            ctx.gap('production_invoke_completion_unobserved', path, 'actual completion transfer is unobserved')
        elif transfer.successor_index != post.successor_index or after is not None and after.origin != transfer.target:
            ctx.issue('production_invoke_actual', path, 'post belongs to another actual completion/traversal')
        if after is not None and ctx.value_activation(after.id) != ctx.activation_of(effect.invocation):
            ctx.issue('production_invoke_scope', path, 'post formal belongs to another activation')
    else:
        ctx.gap('production_invoke_post_unresolved', path, 'actual invoke post state is unresolved')
    ctx.gap('production_invoke_write_unverified', path, 'state transport alone does not prove native write semantics/bytes')
    return {'reference': effect, 'operation': occurrence, 'input': before, 'after': after, 'transfer': transfer}


def write_errors(ctx):
    from .source_validation import resolve_edge, resolve_endpoint, resolve_raw

    ctx.resolved_writes = {}
    write_relations = {EvidenceRelation.PRODUCES, EvidenceRelation.OBSERVED_WRITE,
                       EvidenceRelation.OVERWRITES, EvidenceRelation.MATERIALIZES}
    for row in ctx.writes.values():
        path = f'writes[{row.id}]'
        start = len(ctx.gaps)
        writer, value, effect, operation, run = None, None, None, None, None
        if type(row.writer) is WorkWrite:
            writer = ctx.submissions.get(row.writer.ticket)
            if writer is None:
                ctx.issue('production_ticket', path, 'writer references an absent work ticket')
            elif type(writer.origin) is WithinOperation:
                operation = writer.origin.operation
                run = ctx.processes[ctx.activations[ctx.activation_of(operation)].process].run
            else:
                run = writer.origin.point.run
        elif type(row.writer) is HostWrite:
            operation = row.writer.operation
            writer = ctx.occurrences.get(operation)
            if writer is None:
                ctx.issue('production_host', path, 'host writer references an absent operation occurrence')
                operation = None
            else:
                run = ctx.processes[ctx.activations[ctx.activation_of(operation)].process].run
        elif type(row.writer) is ExternalEstablishment:
            writer = row.writer
            ctx.check_point(writer.point, path)
            run = writer.point.run
            ctx.gap('production_external_establishment_unverified', path, 'external establishment has no native/content correspondence proof')
        else:
            ctx.check_point(row.writer.point, path)
            ctx.gap('production_writer_unresolved', path, row.writer.reason)
        if type(row.production) is ValueProduction:
            value = ctx.values.get(row.production.value)
            if value is None:
                ctx.issue('production_value', path, 'production references an absent original value occurrence')
            else:
                definition = ctx.core_values[value.value]
                if type(definition) not in (DataValue, ReferenceValue):
                    ctx.issue('production_value_kind', path, 'state/binding/protocol is not a logical value production')
                value_run = ctx.processes[ctx.activations[ctx.value_activation(value.id)].process].run
                if run is not None and run != value_run:
                    ctx.issue('production_run', path, 'writer and value production belong to different runs')
                if operation is not None and type(value.origin) is OperationOccurrenceID and value.origin != operation:
                    if ctx.activation_of(value.origin) == ctx.activation_of(operation):
                        ctx.issue('production_value_owner', path, 'another sequential operation produced this value')
                    else:
                        ctx.gap('production_nested_value_unverified', path, 'nested result-to-writer pairing is not established')
        elif type(row.production) is StateProduction:
            effect = _effect(ctx, row.production.effect, path)
            if effect is not None:
                actual_operation = effect['operation'].id
                if operation is not None and actual_operation != operation:
                    if ctx.activation_of(actual_operation) == ctx.activation_of(operation):
                        ctx.issue('production_effect_owner', path, 'effect belongs to another sequential writer occurrence')
                    else:
                        ctx.gap('production_nested_effect_unverified', path, 'nested effect-to-writer pairing is not established')
                effect_run = ctx.processes[ctx.activations[ctx.activation_of(actual_operation)].process].run
                if run is not None and effect_run != run:
                    ctx.issue('production_run', path, 'writer and effect belong to different runs')
                if type(row.writer) is WorkWrite and writer is not None and row.production.effect not in writer.effects:
                    if writer.effects_coverage is Completeness.COMPLETE:
                        ctx.issue('production_submitted_effect', path, 'write contradicts the complete submitted effect association')
                    else:
                        ctx.gap('production_submitted_effect_unresolved', path, 'exact effect has no submitted work association')
        else:
            ctx.gap('production_target_unresolved', path, row.production.reason)
        stage = None
        if type(row.stage) is RawRecordRef:
            stage = resolve_raw(ctx, row.stage, path)
        elif type(row.stage) is SourceEdgeRef:
            stage = resolve_edge(ctx, row.stage, path)
            if stage is not None and stage['edge'].relation not in write_relations:
                ctx.issue('production_source_relation', path, 'stage relation is not a write/production relation')
        elif type(row.stage) is NativeOutputRef:
            stage = native_port(ctx, row.stage, path)
            if stage is not None and value is not None and stage['value'] is not None and stage['value'].id != value.id:
                ctx.issue('production_native_actual', path, 'native stage selects another actual output incarnation')
        else:
            ctx.gap('production_stage_unresolved', path, row.stage.reason)
        sources, source_pairs = [], []
        for reference in row.evidence:
            resolved = resolve_edge(ctx, reference, path)
            if resolved is not None:
                sources.append(resolved)
                source_pairs.append((reference, resolved))
                if resolved['edge'].relation not in write_relations:
                    ctx.issue('production_source_relation', path, 'write evidence must retain a write/production relation')
        for reference in (row.stage, *row.evidence):
            if type(reference) in (RawRecordRef, SourceEdgeRef):
                inventory = ctx.source_inventories.get(reference.source.inventory)
                if inventory is not None and run is not None and inventory.run != run:
                    ctx.issue('production_source_run', path, 'source inventory and writer belong to different runs')
        placement = resolve_placement(ctx, row.placement, path)
        edge_sources = ([(row.stage, stage)] if type(row.stage) is SourceEdgeRef and stage is not None else []) + source_pairs
        for reference, resolved in edge_sources:
            edge = resolved['edge']
            endpoint = resolve_endpoint(ctx, SourceEndpointRef(reference.source, edge.target), path)
            resolved['target'] = endpoint
            if (endpoint is not None and placement is not None
                    and artifact_key(endpoint['values_artifact']) == artifact_key(row.placement.materialization.artifact)):
                materialization = placement[0]
                if (endpoint['value_version'] is not None
                        and endpoint['value_version'] != materialization.value_version):
                    ctx.issue('production_source_version', path, 'original same-bundle source endpoint names another logical version')
                if (endpoint['materialization'] is not None
                        and endpoint['materialization'] != materialization.id):
                    ctx.issue('production_source_materialization', path, 'original same-bundle source endpoint names another materialization')
        ctx.gap('production_source_join_unverified', path, 'source stage/native write-to-effect/placement correspondence is not established by labels or shared host ownership')
        ctx.gap('production_state_content_unverified', path, 'original state/value and source endpoints do not prove physical content/version production')
        ctx.resolved_writes[row.id] = {'row': row, 'writer': writer, 'production': row.production,
            'value': value, 'effect': effect, 'placement': placement, 'stage': stage,
            'sources': tuple(sources), 'gaps': tuple(ctx.gaps[start:])}


def _profile(ctx, resolved, path):
    record = resolved['record']
    payload = record.payload
    if type(payload) is not dict:
        ctx.gap('production_profile_unavailable', path, 'raw record has no decoded JSON object payload')
        return None
    metadata = payload.get('metadata')
    keys = {'schema', 'schema_version', 'stage', 'requested_bytes', 'written_bytes'}
    if type(metadata) is not dict or 'scar_native_result' not in metadata:
        ctx.gap('production_profile_unavailable', path, 'exact raw record has no byte-prefix protocol payload')
        return None
    profile = metadata['scar_native_result']
    if (type(profile) is not dict or set(profile) != keys
            or profile['schema'] != 'scar.native.byte-prefix-write'
            or type(profile['schema_version']) is not int or profile['schema_version'] != 1
            or type(profile['stage']) is not str or not profile['stage']):
        ctx.issue('production_profile', path, 'native result must have the exact closed byte-prefix schema')
        return None
    requested, written = profile['requested_bytes'], profile['written_bytes']
    if (type(requested) is not int or type(written) is not int
            or requested < 0 or written < 0 or written > requested):
        ctx.issue('production_profile_count', path, 'native byte counts must be exact integers with 0 <= written <= requested')
        return None
    return profile


def produced_errors(ctx):
    from .source_validation import resolve_raw

    ctx.resolved_produced = {}
    for row in ctx.produced.values():
        path = f'produced[{row.id}]'
        start = len(ctx.gaps)
        write = ctx.writes.get(row.write)
        outcome = ctx.outcomes.get(row.outcome)
        if write is None:
            ctx.issue('production_write', path, 'produced association references an absent write')
        if outcome is None:
            ctx.issue('production_outcome', path, 'produced association references an absent actual outcome')
        if write is None or outcome is None:
            continue
        if type(write.writer) is not WorkWrite or write.writer.ticket != outcome.ticket:
            ctx.issue('production_outcome_ticket', path, 'resource outcome must belong to this exact work writer')
        frontier = None
        if type(write.production) is ValueProduction:
            if row.frontier is not None:
                ctx.issue('production_value_frontier', path, 'value production has no state frontier: use None/NotApplicable')
        elif type(write.production) is StateProduction:
            if row.frontier is None:
                ctx.issue('production_state_frontier', path, 'state production requires an actual frontier index or explicit unresolved')
            elif type(row.frontier) is int:
                if row.frontier >= len(outcome.effect_frontier):
                    ctx.issue('production_frontier', path, 'frontier index does not select an actual outcome effect')
                else:
                    frontier = outcome.effect_frontier[row.frontier]
                    if frontier != write.production.effect:
                        ctx.issue('production_frontier_effect', path, 'frontier selects another original effect')
            else:
                ctx.gap('production_frontier_unresolved', path, row.frontier.reason)
        else:
            ctx.gap('production_frontier_unresolved', path, 'production target is unresolved')
        actual = None
        if type(row.actual) is RegionRef:
            graph = ctx.external_values(row.actual.artifact, path)
            actual = None if graph is None else graph.regions.get(row.actual.region)
            if graph is not None and actual is None:
                ctx.issue('production_actual_region', path, 'actual selector is absent from exact ValueGraph')
        else:
            ctx.gap('production_actual_unresolved', path, 'actual selector has no parsed byte geometry')
        raw, profile, requested = None, None, None
        if type(row.rule) is BytePrefixWrite:
            if type(write.stage) is not RawRecordRef:
                ctx.gap('production_profile_stage_unresolved', path, 'byte-prefix profile requires an exact original raw record stage')
            else:
                raw = resolve_raw(ctx, write.stage, path)
                if raw is not None:
                    profile = _profile(ctx, raw, path)
            resolved = ctx.resolved_writes.get(write.id)
            if type(write.placement) is not StorageContent:
                ctx.gap('production_profile_placement_unresolved', path, 'byte-prefix rule does not interpret endpoint or unknown placements')
            elif resolved is not None and resolved['placement'] is not None:
                mat, selector = resolved['placement']
                if selector is not None:
                    graph = ctx.external_values(selector.artifact, path)
                    requested = None if graph is None else graph.regions.get(selector.region)
                    if type(row.actual) is RegionRef and artifact_key(row.actual.artifact) != artifact_key(selector.artifact):
                        ctx.issue('production_selector_scope', path, 'actual and requested selectors belong to different exact ValueGraphs')
                if actual is not None and mat.region is not None and type(row.actual) is RegionRef:
                    original = RegionRef(write.placement.materialization.artifact, mat.region)
                    coverage = _storage_coverage(row.actual, (original,),
                        catalog=_ValueCatalog.from_snapshots(ctx.snapshots), budget=4096)
                    if coverage.status is CoverageStatus.INCOMPLETE:
                        ctx.issue('production_actual_outside', path, 'actual selector extends outside the original materialization region')
                    elif coverage.status is CoverageStatus.UNRESOLVED:
                        ctx.gap('production_actual_coverage_unresolved', path, 'actual selector subset is not established within geometry budget')
                if requested is not None and actual is not None:
                    if requested.allocation != actual.allocation:
                        ctx.issue('production_selector_allocation', path, 'actual selector belongs to another allocation incarnation')
                    linear = lambda x: x.dtype == 'uint8' and x.layout == 'strided' and len(x.shape) == 1 and x.strides == (1,)
                    if not linear(requested) or not linear(actual):
                        ctx.gap('production_byte_layout_unresolved', path, 'prefix rule only interprets linear rank1 uint8 byte buffers')
                    elif profile is not None:
                        if requested.shape != (profile['requested_bytes'],) or actual.shape != (profile['written_bytes'],):
                            ctx.issue('production_selector_count', path, 'original selector geometry does not equal parsed requested/produced byte counts')
                        if actual.offset != requested.offset:
                            ctx.issue('production_selector_offset', path, 'actual byte prefix must start at the original request offset')
            result = outcome.protocol_result
            if type(result) is ProviderFactReference and raw is not None:
                # ResolvedSource exposes the exact original raw artifact.
                original = raw['source'].raw_artifact
                if (artifact_key(result.artifact) != artifact_key(original)
                        or result.locator != f'#L{write.stage.line}/metadata/scar_native_result'):
                    ctx.issue('production_protocol_result', path, 'protocol result must reference this exact raw record payload')
            elif type(result) is not Unresolved and result in ctx.values:
                definition = ctx.core_values[ctx.values[result].value]
                if (isinstance(definition, DataValue) and isinstance(definition.origin, LiteralOrigin)
                        and type(definition.origin.value) is int and profile is not None):
                    if definition.origin.value != profile['written_bytes']:
                        ctx.issue('production_protocol_result', path, 'literal protocol result conflicts with parsed produced bytes')
                else:
                    ctx.gap('production_result_unresolved', path, 'original result value has no decoded exact integer payload/port correspondence')
            else:
                ctx.gap('production_result_unresolved', path, 'protocol result has no parsed exact raw/result correspondence')
        else:
            ctx.gap('production_rule_unresolved', path, row.rule.reason)
        ctx.gap('production_native_protocol_unverified', path, 'parsed declaration does not establish physical write/native applicability, source authority or content stability')
        ctx.resolved_produced[row.id] = {'row': row, 'write': write, 'outcome': outcome,
            'frontier': frontier, 'protocol_result': outcome.protocol_result, 'rawprofile': profile,
            'actual': actual, 'requested': requested, 'conditions': ('native/source applicability remains unverified',),
            'gaps': tuple(ctx.gaps[start:])}


__all__ = ['write_errors', 'produced_errors']
