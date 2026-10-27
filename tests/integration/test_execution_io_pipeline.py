"""One cross-call canonical IO pipeline; not automatic native recovery."""
from dataclasses import fields, replace
import json

import pytest

from scar.ir.execution.common import Unresolved
from scar.ir.execution.composition import CompositionScope
from scar.ir.execution.query import ExecutionIndex
from scar.ir.execution.validation import require_valid
from scar.ir.execution.work import BorrowRelease
from scar.ir.program.model import TerminatorKind
from tests.fixtures.execution_io_pipeline import io_pipeline_execution


def _query(fixture, *, budget=131072):
    program, model, catalogs, details = fixture
    require_valid(model, program, **catalogs)
    index = ExecutionIndex(model, program, **catalogs)
    scope = CompositionScope(details['contract'], details['by_region'][program.root][0], details['source'])
    return index, index.resource_composition(scopes=(scope,), budget=budget)


def _read(view, identity):
    return next(row['validity'] for row in view['reads']['items'] if row['read'].id == identity)


def test_complete_pipeline_uses_one_program_and_exact_dynamic_calls(record_property):
    program, model, catalogs, details = io_pipeline_execution()
    index, view = _query((program, model, catalogs, details))
    record_property('composition_scale_and_budget', json.dumps({
        'budget': view['budget'], 'canonical': view['inventory']['canonical_counts'],
        'execution': view['inventory']['execution_counts'],
        'source_rows': sum(source['raw_record_count'] for row in view['sources']['items'] for source in row['sources']),
        'range_bytes': 8}, sort_keys=True))
    assert len(program.regions) == len(model.activations) == 7
    assert len(model.call_activations) == len(view['routes']['calls']) == 6
    assert not view['budget']['truncated'] and view['budget']['used'] <= 131072
    assert view['inventory']['execution'] == model
    assert view['inventory']['program'] == program
    assert len(model.content_reads) == 10
    assert len(model.submissions) == 2  # H2D and compute, never sync read/write/flush/close.
    assert all(row.origin.operation.value.endswith(('io.prepare.materialize', 'io.run.submit')) for row in model.submissions)
    assert all(row['status'] == 'DECLARED' for row in view['routes']['calls'])
    assert len(view['lifecycle']['work']) == 2
    assert details['mats']['normalized.cpu'] != details['mats']['normalized.gpu']
    assert details['mats']['serialized'] != details['mats']['buffer'] != details['mats']['endpoint']
    assert details['versions']['raw'] != details['versions']['normalized']
    assert details['versions']['computed'] != details['versions']['serialized']
    assert {op.id.value for op in program.operations} >= {'io.load.read', 'io.prepare.represent',
        'io.prepare.materialize', 'io.run.submit', 'io.run.wait', 'io.run.consume',
        'io.save.serialize', 'io.save.write', 'io.close.buffer_read', 'io.close.flush', 'io.close.close'}
    buffer_write = next(row for row in model.writes if row.id.value == 'io.save.write')
    file_write = next(row for row in model.writes if row.id.value == 'io.close.flush')
    assert buffer_write.placement.materialization == details['mats']['buffer']
    assert file_write.placement.materialization == details['mats']['endpoint']
    source_read = next(row for row in model.content_reads if row.id == details['source_read'])
    assert source_read.placement.materialization == details['mats']['buffer']
    assert source_read.consumer.subject.operation == file_write.writer.operation
    endpoint = _read(view, details['endpoint_read'])
    assert endpoint['conditional_support']['status'] == 'MATCHED'
    assert endpoint['conditional_fragment_coverage']['status'] == 'COVERED'
    assert endpoint['validity_conditions'] and not endpoint['runtime_visibility_verified']
    assert view['observations']['requirements'] == model.observation_requirements
    assert view['observations']['roots'] == model.observation_roots
    assert view['observations']['scope_status'] == 'PARTIAL'  # Required facets do not define all targets/cardinality.
    assert not view['source_runtime_verified'] and not view['transformation_authorized']


@pytest.mark.parametrize('stage', ('load', 'run', 'save'))
def test_actual_helper_raise_keeps_partial_states_and_executes_close_cleanup(stage):
    program, model, catalogs, details = io_pipeline_execution(raised_stage=stage)
    _, view = _query((program, model, catalogs, details))
    call = next(row for row in view['routes']['calls'] if row['callee'].id.value == 'io.' + stage)
    completion = next(row for row in program.operations if row.id == call['completion'].operation)
    assert completion.terminator.kind is TerminatorKind.RAISE
    assert call['outputs'] and all(row['caller_transfer'] is not None for row in call['outputs'])
    assert all(row['caller_result'] is None for row in call['outputs'])
    assert any(row['callee'].id.value == 'io.close' for row in view['routes']['calls'])
    assert details['main_raise'] is not None and details['main_return'] is None
    assert any(row['definition'].id.value == 'shared.cleanup.resume' for row in view['routes']['operations'])
    assert len(view['observations']['requirements']) == 2
    output = next(row for row in view['observations']['obligations'] if row['kind'] == 'OUTPUT')
    assert output['status'] == 'ROOT_MISSING'
    assert details['called_stages'][-1] == stage
    assert any(row.id.value == 'io.close.close' for row in program.operations)
    if stage in ('load', 'run'):
        assert details['buffer_current'] == details['mats']['buffer.empty']
        graph = catalogs['value_graphs'][details['buffer_current'].artifact.sha256]
        materialization = graph.materializations[details['buffer_current'].materialization]
        assert graph.regions[materialization.region].shape == (0,)
        assert graph.allocations[graph.regions[materialization.region].allocation].nbytes == 8
        assert materialization.value_version == details['versions']['empty']
        value = next(row for row in model.denotations if row.id.value == 'io.close.bytes')
        assert value.identity.version.version == details['versions']['empty']
        assert not any(row.id.value == 'io.close.flush' for row in model.writes)
        assert not any(row.write.value == 'io.close.flush' for row in model.established_productions)
        read = next(row for row in model.content_reads if row.id == details['source_read'])
        assert read.placement.materialization == details['buffer_current']
        assert json.loads(catalogs['artifact_bytes'][details['read_profile'].artifact.sha256])['length_bytes'] == 8


def test_close_raise_replaces_saved_completion_and_keeps_post_close_state():
    program, model, catalogs, details = io_pipeline_execution(close_raises=True)
    _, view = _query((program, model, catalogs, details))
    call = next(row for row in view['routes']['calls'] if row['callee'].id.value == 'io.close')
    assert next(row for row in program.operations if row.id == call['completion'].operation).terminator.kind is TerminatorKind.RAISE
    assert any(row['definition'].id.value == 'invoke.cleanup.replace-action' for row in view['routes']['operations'])
    assert not any(row['definition'].id.value == 'shared.cleanup.resume' for row in view['routes']['operations'])
    assert details['main_raise'] is not None
    assert all(row['caller_formal'] is not None for row in call['outputs'])
    assert any(row['definition'].id.value == 'io.close.flush' for row in view['routes']['operations'])
    assert any(row['definition'].id.value == 'io.close.close' for row in view['routes']['operations'])
    assert not model.target_lifetime_events  # Closing a handle is not target retirement.


def test_missing_native_terminal_does_not_erase_host_return_or_release_borrow():
    program, model, catalogs, details = io_pipeline_execution(pending=True, raised_stage='run')
    _, view = _query((program, model, catalogs, details))
    ticket = details['work_ids']['run', 'submit']
    work = next(row for row in view['lifecycle']['work'] if row['submission'].id == ticket)
    assert work['outcomes'] == work['quiescences'] == ()
    assert type(work['retentions'][0].release) is Unresolved
    assert details['main_raise'] is not None and details['main_return'] is None
    observed = {row.operation.value for row in model.operations}
    assert 'io.run.submit' in observed and 'io.run.wait' not in observed and 'io.run.consume' not in observed
    assert 'io.run.wait' in {row.id.value for row in program.operations}
    assert 'io.run.consume' in {row.id.value for row in program.operations}
    assert 'io.save.write' not in observed
    assert any(type(row.release) is BorrowRelease for row in model.retentions)  # Copy completed independently.
    assert any(row.id == ticket for row in view['inventory']['execution'].submissions)
    assert not view['runtime_visibility_verified']


def test_budget_cuts_keep_entire_program_source_and_q_inventory():
    fixture = io_pipeline_execution()
    program, model, *_ = fixture
    for budget in (1, 32768):
        _, view = _query(fixture, budget=budget)
        assert view['status'] == 'TRUNCATED' and view['budget']['used'] == budget
        assert view['inventory']['program'] == program and view['inventory']['execution'] == model
        assert view['inventory']['execution_counts'] == {field.name: len(getattr(model, field.name))
            for field in fields(model) if field.name != 'snapshot'}
        assert view['routes']['cursor'] is not None
        assert view['routes']['pending']['operations'] == len(model.operations)
        assert view['observations']['requirements'] == model.observation_requirements
        assert view['observations']['roots'] == model.observation_roots
        assert view['reads']['pending']


def test_deleting_call_joins_preserves_obligations_and_does_not_infer_children_by_name():
    program, model, catalogs, details = io_pipeline_execution(include_call_links=False)
    _, view = _query((program, model, catalogs, details))
    assert model.call_activations == ()
    assert len(view['routes']['calls']) == 6
    assert all(row['status'] == 'MISSING' and row['association'] is None for row in view['routes']['calls'])
    assert view['inventory']['execution_counts']['activations'] == 7
    assert view['observations']['requirements'] == model.observation_requirements
    assert view['sources']['items']


def test_buffer_acceptance_is_not_file_visibility_and_partial_flush_keeps_eight_byte_demand():
    fixture = io_pipeline_execution(written=4)
    program, model, catalogs, details = fixture
    _, view = _query(fixture)
    buffer_result = next(row for row in view['production']['established_productions']
                         if row['row'].write.value == 'io.save.write')
    assert buffer_result['actual'].shape == (8,)
    endpoint = _read(view, details['endpoint_read'])
    assert endpoint['conditional_support']['status'] == 'MISSING'
    assert endpoint['conditional_fragment_coverage']['status'] == 'INCOMPLETE'
    file_result = next(row for row in view['production']['established_productions']
                       if row['row'].write.value == 'io.close.flush')
    assert file_result['rawprofile']['requested_bytes'] == 8
    assert file_result['rawprofile']['written_bytes'] == 4
    assert next(row for row in model.content_reads if row.id == details['endpoint_read']).placement.selector == endpoint['read'].placement.selector
    assert not view['runtime_visibility_verified']


def test_missing_flush_contribution_does_not_discard_independent_source_or_satisfy_file_requirement():
    program, model, catalogs, details = io_pipeline_execution(include_flush_production=False)
    _, view = _query((program, model, catalogs, details))
    assert any(row.id.value == 'io.save.write' for row in model.writes)
    assert not any(row.id.value == 'io.close.flush' for row in model.writes)
    result = _read(view, details['endpoint_read'])
    assert result['conditional_support']['status'] == 'MISSING'
    assert result['conditional_fragment_coverage']['status'] != 'COVERED'
    assert view['sources']['items'][0]['sources'][0]['raw_record_count'] == 8
    assert view['observations']['requirements'] == model.observation_requirements
    assert any(not candidate['write_associations'] for candidate in result['source_universe']['candidates'])


def test_observation_before_flush_cannot_borrow_its_future_visibility():
    fixture = io_pipeline_execution(early_observation=True)
    _, view = _query(fixture)
    details = fixture[-1]
    result = _read(view, details['endpoint_read'])
    assert result['conditional_support']['status'] != 'MATCHED'
    assert result['conditional_fragment_coverage']['status'] != 'COVERED'
    assert not any(row.id.value == 'io.endpoint' for row in fixture[1].contribution_supports)
    assert any(row.id.value == 'io.close.flush' for row in fixture[1].writes)
