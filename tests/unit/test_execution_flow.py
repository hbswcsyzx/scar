from dataclasses import replace

import pytest

from scar.ir.execution.coordinates import OccurrencePhase, OccurrencePoint
from scar.ir.execution.ids import BlockVisitID, OperationOccurrenceID, ValueOccurrenceID
from scar.ir.execution.query import ExecutionIndex
from scar.ir.execution.validation import require_valid, validate
from scar.ir.program.ids import BlockID, LocationID, UseID
from tests.fixtures.execution_paths import declared_path
from tests.fixtures.program_graphs import loop_state_program


def _loop():
    program = loop_state_program()
    path = [('loop.entry', 0), ('header', 0), ('body', 0), ('header', 0), ('body', 0), ('header', 1), ('exit', None)]
    model = declared_path(program, [(BlockID(block), edge) for block, edge in path])
    return program, model


def test_loop_revisits_have_fresh_values_and_original_use_and_formal_routes():
    program, model = _loop()
    require_valid(model, program)
    index = ExecutionIndex(model, program)
    link = index.definition_for_use(OperationOccurrenceID('3.compare'), UseID('compare.counter'))
    assert link.occurrence == ValueOccurrenceID('3.counter.value')
    assert link.origin == OperationOccurrenceID('3.read.counter')
    route = index.formal_route(ValueOccurrenceID('3.header.state'))
    assert route.source_use.value == ValueOccurrenceID('2.incremented')
    state = index.state_at(OccurrencePoint(OperationOccurrenceID('3.read.counter'), OccurrencePhase.BEFORE))
    assert state[LocationID('counter')] == ValueOccurrenceID('3.header.state')
    assert not index.report.source_runtime_verified


@pytest.mark.parametrize('use,value', [('compare.counter', '1.counter.value'), ('read.counter.state', '1.header.state')])
def test_loop_rejects_old_result_and_old_state_from_same_static_definition(use, value):
    program, model = _loop()
    model = replace(model, uses=tuple(replace(row, value=ValueOccurrenceID(value))
        if row.operation == OperationOccurrenceID('3.' + ('compare' if use == 'compare.counter' else 'read.counter'))
        and row.use == UseID(use) else row for row in model.uses))
    assert 'stale_incarnation' in {row.code for row in validate(model, program).issues}


@pytest.mark.parametrize('which', ['unknown-visit', 'unknown-origin', 'unknown-block', 'wrong-run', 'cycle', 'fork'])
def test_bad_dynamic_links_report_issues_without_crashing(which):
    program, model = _loop()
    if which == 'unknown-visit':
        model = replace(model, operations=(replace(model.operations[0], visit=BlockVisitID('absent')), *model.operations[1:]))
    elif which == 'unknown-origin':
        model = replace(model, values=(replace(model.values[0], origin=BlockVisitID('absent')), *model.values[1:]))
    elif which == 'unknown-block':
        model = replace(model, visits=(replace(model.visits[0], block=BlockID('absent')), *model.visits[1:]))
    elif which == 'wrong-run':
        from scar.ir.execution.ids import RunID
        model = replace(model, activations=(replace(model.activations[0], entry=replace(model.activations[0].entry, run=RunID('absent'), process=None)),))
    elif which == 'cycle':
        # Backedge targets a prior header occurrence instead of a fresh visit.
        model = replace(model, transfers=tuple(replace(row, target=BlockVisitID('1'))
            if row.operation == OperationOccurrenceID('2.backedge') else row for row in model.transfers))
    else:
        model = replace(model, transfers=(*model.transfers, model.transfers[0]))
    assert validate(model, program).issues


def test_missing_observation_is_gap_and_does_not_authorize_optimization():
    program, model = _loop()
    model = replace(model, uses=tuple(row for row in model.uses if row.use != UseID('compare.counter')))
    report = validate(model, program)
    assert report.valid and not report.transformation_authorized
    assert 'use_unobserved' in {row.code for row in report.gaps}


def test_untaken_edge_cannot_supply_a_state_or_a_host_precedence_point():
    program, model = _loop()
    index = ExecutionIndex(model, program)
    with pytest.raises(ValueError, match='different successor'):
        index.state_at(OccurrencePoint(OperationOccurrenceID('1.loop.choose'), OccurrencePhase.EDGE, 1))


@pytest.mark.parametrize('edge,block', [(0, 'resume.value'), (1, 'resume.packet')])
def test_resume_keeps_body_activation_and_uses_new_segment_state_and_actual_saved_port(edge, block):
    from tests.fixtures.program_resumption_graphs import resumption_program
    program = resumption_program()
    model = declared_path(program, [(BlockID('resume.entry'), edge), (BlockID(block), None)])
    index = ExecutionIndex(model, program)
    assert len(model.activations) == 1 and len(model.segments) == 2
    route = index.formal_route(ValueOccurrenceID('1.' + block + '.x'))
    assert route.source_use.value == ValueOccurrenceID('0.resume.x')
    world = LocationID('resume.world')
    point = OccurrencePoint(OperationOccurrenceID('0.resume.suspend'), OccurrencePhase.EDGE, edge)
    assert index.state_at(point)[world] == ValueOccurrenceID('1.' + block + '.world')
    # A resumed body may run on another actual host thread in the same process.
    from scar.ir.execution.coordinates import HostThreadInstance
    from scar.ir.execution.ids import HostThreadInstanceID
    thread = HostThreadInstance(HostThreadInstanceID('other'), model.processes[0].id, 12, model.threads[0].source)
    migrated = replace(model, threads=(*model.threads, thread),
        segments=(model.segments[0], replace(model.segments[1], host_thread=thread.id)))
    require_valid(migrated, program)


def test_resume_cannot_be_folded_into_initial_segment_or_rebound_to_another_successor():
    from tests.fixtures.program_resumption_graphs import resumption_program
    program = resumption_program()
    model = declared_path(program, [(BlockID('resume.entry'), 0), (BlockID('resume.value'), None)])
    invalid = replace(model, visits=(model.visits[0], replace(model.visits[1], segment=model.segments[0].id)))
    assert 'transfer_resume' in {row.code for row in validate(invalid, program).issues}
    ingress = replace(model.segments[1].ingress, successor_index=1)
    invalid = replace(model, segments=(model.segments[0], replace(model.segments[1], ingress=ingress)))
    assert validate(invalid, program).issues


@pytest.mark.parametrize('edge,block', [(0, 'invoke.normal'), (1, 'invoke.failure')])
def test_invoke_has_no_common_after_state_and_actual_completion_supplies_fresh_formals(edge, block):
    from tests.fixtures.program_resumption_invoke_graphs import partial_state_invoke_program
    program = partial_state_invoke_program()
    model = declared_path(program, [(BlockID('invoke.entry'), edge), (BlockID(block), None)])
    index = ExecutionIndex(model, program)
    invoke = OperationOccurrenceID('0.invoke.call')
    before = index.state_at(OccurrencePoint(invoke, OccurrencePhase.BEFORE))
    after = index.state_at(OccurrencePoint(invoke, OccurrencePhase.AFTER))
    assert before and all(value is None for value in after.values())
    route = index.formal_route(ValueOccurrenceID('1.' + block + '.world'))
    from scar.ir.program.model import CompletionResult
    assert type(route.argument) is CompletionResult and route.source_use is None
    state = index.state_at(OccurrencePoint(invoke, OccurrencePhase.EDGE, edge))
    assert state[program.locations[0].id] == ValueOccurrenceID('1.' + block + '.world')


def test_queries_are_detached_and_snapshot_conflicts_are_not_missing_evidence():
    program, model = _loop()
    index = ExecutionIndex(model, program)
    first = index.occurrence(OperationOccurrenceID('3.compare'))
    object.__setattr__(first['operation'], 'label', 'caller changed a detached result')
    assert index.occurrence(OperationOccurrenceID('3.compare'))['operation'].label != first['operation'].label
    artifact = replace(model.snapshot.artifact, size_bytes=model.snapshot.artifact.size_bytes + 1)
    bad = replace(model, snapshot=replace(model.snapshot, artifact=artifact))
    assert 'program_snapshot' in {row.code for row in validate(bad, program).issues}


@pytest.mark.parametrize('kind', ['ingress', 'unknown-thread-point'])
def test_even_self_consistent_evidence_points_cannot_switch_the_segments_process(kind):
    from scar.ir.execution.coordinates import ProcessInstance, UnresolvedHostThread
    from scar.ir.execution.ids import ProcessInstanceID
    program, model = _loop()
    other = ProcessInstance(ProcessInstanceID('other'), model.runs[0].id, 10, model.processes[0].source)
    segment = model.segments[0]
    point = replace(segment.ingress.source, process=other.id)
    if kind == 'ingress':
        segment = replace(segment, ingress=replace(segment.ingress, source=point))
    else:
        segment = replace(segment, host_thread=UnresolvedHostThread('not observed', point))
    model = replace(model, processes=(*model.processes, other), segments=(segment,))
    assert validate(model, program).issues


def test_absent_producer_does_not_allow_an_old_result_at_a_later_block():
    from scar.ir.execution.common import Unresolved
    program, model = _loop()
    missing = OperationOccurrenceID('5.read.counter')
    point = model.activations[0].entry
    model = replace(model, operations=tuple(row for row in model.operations if row.id != missing),
        values=tuple(row for row in model.values if row.origin != missing),
        uses=tuple(replace(row, value=Unresolved('current result not captured', point))
            if row.operation == OperationOccurrenceID('5.compare') and row.use == UseID('compare.counter') else
            replace(row, value=ValueOccurrenceID('3.counter.value'))
            if row.operation == OperationOccurrenceID('6.loop.done') and row.use == UseID('loop.done.value') else row
            for row in model.uses if row.operation != missing))
    assert 'stale_incarnation' in {row.code for row in validate(model, program).issues}


def test_disconnected_entry_visit_is_not_silently_a_second_initial_entry():
    from scar.ir.execution.coordinates import BlockVisit
    program, model = _loop()
    model = replace(model, visits=(*model.visits, BlockVisit(BlockVisitID('disconnected-entry'), model.segments[0].id,
                                                          BlockID('loop.entry'))))
    report = validate(model, program)
    assert report.valid and 'initial_entry_ambiguous' in {row.code for row in report.gaps}


def test_public_queries_and_catalog_inputs_report_invalid_types():
    program, model = _loop()
    with pytest.raises(ValueError, match='OccurrencePoint'):
        ExecutionIndex(model, program).state_at(None)
    assert 'catalog_type' in {row.code for row in validate(model, program, value_graphs=[]).issues}


@pytest.mark.parametrize('missing_current', [False, True])
def test_resource_support_cannot_fall_back_to_old_loop_state_when_current_formal_is_missing(missing_current):
    from scar.ir.execution.common import Unresolved
    from scar.ir.execution.ids import RealizationID, ResourceAccessID, ResourceBindingID, ResourceInstanceID
    from scar.ir.execution.resources import (
        ImplicitBinding, ImportedAt, InstanceTarget, ProcessRealm, RequirementBinding,
        ResourceAccessBinding, ResourceInstance, ResourceRealization,
    )
    from scar.ir.execution.snapshot import snapshot_for
    from scar.ir.program.ids import OperationID, ResourceDefinitionID, ResourceRequirementID
    from scar.ir.program.providers import ProviderFactReference
    from scar.ir.program.resources import (
        ExternalResource, ResourceDefinition, ResourceKind, ResourceLocation,
        ResourceRequirement, ResourceRole, ResourceUse,
    )
    program, model = _loop()
    definition = ResourceDefinition(ResourceDefinitionID('executor'), ResourceKind.CPU, ResourceRole.EXECUTOR,
                                    ExternalResource(program.root, 'external-executor'))
    requirement = ResourceRequirement(ResourceRequirementID('executor'), program.root,
                                     ResourceKind.CPU, ResourceRole.EXECUTOR)
    program = replace(program, resources=(definition,), resource_requirements=(requirement,),
        resource_uses=(ResourceUse(OperationID('read.counter'), requirement.id, definition.id),),
        resource_locations=(ResourceLocation(LocationID('counter'), definition.id),))
    model = replace(model, snapshot=snapshot_for(program))
    point, source = model.activations[0].entry, model.runs[0].source
    resource = ResourceInstance(ResourceInstanceID('executor'), ResourceKind.CPU, ResourceRole.EXECUTOR,
                                ProcessRealm(model.processes[0].id), ImportedAt(point), source)
    target = InstanceTarget(resource.id)
    binding = RequirementBinding(ResourceBindingID('executor'), requirement.id, model.activations[0].id, target, source)
    current = ValueOccurrenceID('5.header.state')
    support = (current,)
    access = ResourceAccessBinding(ResourceAccessID('last-read'), OperationOccurrenceID('5.read.counter'), binding.id,
        ImplicitBinding(ProviderFactReference(model.snapshot.artifact, 'selection-rule'), support), support, (), source)
    model = replace(model, resources=(resource,), requirements=(binding,), accesses=(access,),
        realizations=(ResourceRealization(RealizationID('executor'), definition.id, model.activations[0].id, target, source),))
    require_valid(model, program)
    old = (ValueOccurrenceID('3.header.state'),)
    access = replace(access, support=old, handle=replace(access.handle, support=old))
    model = replace(model, accesses=(access,))
    if missing_current:
        model = replace(model, values=tuple(row for row in model.values if row.id != current),
            uses=tuple(replace(row, value=Unresolved('current formal not captured', point))
                       if row.value == current else row for row in model.uses))
    assert 'stale_state' in {row.code for row in validate(model, program).issues}
