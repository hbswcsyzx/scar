"""Conditional original write/result associations; no readiness authority."""
from scar.ir.program.model import AccessMode, DataValue, ReferenceValue
from scar.ir.v2.evidence import EvidenceRelation
from scar.ir.v2.common import Completeness
from .common import Unresolved
from .content import NativeOutputRef
from .content_validation import artifact_key, native_port, resolve_placement
from .coordinates import OccurrencePhase, OccurrencePoint
from .effects import effect_context, resolve_canonical_effect
from .ids import OperationOccurrenceID
from .production import (
    BytePrefixWrite, ExternalEstablishment, HostWrite, RawRecordRef,
    SourceEdgeRef, SourceEndpointRef, StateProduction, ValueProduction, WorkWrite,
)
from .work import WithinOperation


def _effect(ctx, effect, path):
    """Resolve an original effect; write policy and WorkWrite ownership stay local."""
    issue_codes = {
        'effect_operation': 'production_effect',
        'effect_access': 'production_effect',
        'invoke_kind': 'production_invoke',
        'invoke_input': 'production_invoke_input',
        'invoke_successor': 'production_invoke_successor',
        'invoke_actual_edge': 'production_invoke_actual',
        'invoke_formal': 'production_invoke_formal',
        'invoke_result': 'production_invoke_result',
        'invoke_formal_visit': 'production_invoke_actual',
        'invoke_formal_scope': 'production_invoke_scope',
    }
    gap_codes = {
        'invoke_input_unobserved': 'production_invoke_input_unobserved',
        'invoke_completion_unobserved': 'production_invoke_completion_unobserved',
        'invoke_post_unresolved': 'production_invoke_post_unresolved',
    }
    view = resolve_canonical_effect(effect_context(
        ctx,
        issue=lambda code, p, message: ctx.issue(issue_codes.get(code, 'production_' + code), p, message),
        gap=lambda code, p, message: ctx.gap(gap_codes.get(code, 'production_' + code), p, message),
    ), effect, path)
    if view is None:
        return None
    if view['kind'] == 'access':
        if view['mode'] is AccessMode.READ:
            ctx.issue('production_read_only', path, 'READ-only access cannot be a write production')
        before = view['before']
        if before is not None and type(before.value) is not Unresolved:
            ctx.check_support((before.value,), OccurrencePoint(effect.operation, OccurrencePhase.BEFORE), path)
        return {'reference': effect, 'operation': view['operation'], 'access': view['access'],
                'before': before, 'after': view['after']}

    before = view['input']
    if before is not None and type(before.value) is not Unresolved:
        ctx.check_support((before.value,), OccurrencePoint(effect.invocation, OccurrencePhase.BEFORE), path)
    ctx.gap('production_invoke_write_unverified', path,
            'state transport alone does not prove native write semantics/bytes')
    return {'reference': effect, 'operation': view['operation'], 'input': before,
            'after': view['formal'], 'transfer': view['actual_transfer']}


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


def produced_errors(ctx):
    from .production_ranges import resolve_actual_range

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
        ranges = resolve_actual_range(ctx, write, row.actual, row.rule,
                                      outcome.protocol_result, path)
        actual, requested, profile = (ranges[key] for key in ('actual', 'requested', 'rawprofile'))
        ctx.gap('production_native_protocol_unverified', path, 'parsed declaration does not establish physical write/native applicability, source authority or content stability')
        ctx.resolved_produced[row.id] = {'row': row, 'write': write, 'outcome': outcome,
            'frontier': frontier, 'protocol_result': outcome.protocol_result, 'rawprofile': profile,
            'placement_match': ranges['placement_match'],
            'actual': actual, 'requested': requested, 'conditions': ('native/source applicability remains unverified',),
            'gaps': tuple(ctx.gaps[start:])}


__all__ = ['write_errors', 'produced_errors']
