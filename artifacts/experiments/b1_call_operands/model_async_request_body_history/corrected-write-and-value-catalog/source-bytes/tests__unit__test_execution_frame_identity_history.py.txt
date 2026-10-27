"""Declared current-object guards complete historical F, never copy equality."""
from dataclasses import replace

import pytest

from scar.ir.execution.content import ObjectIdentity, ObjectRef
from scar.ir.execution.coordinates import OccurrencePhase, OccurrencePoint
from scar.ir.execution.query import ExecutionIndex
from scar.ir.execution.snapshot import external_artifact, snapshot_for
from scar.ir.execution.validation import validate as validate_execution
from scar.ir.program.model import StateVersionValue
from scar.ir.v2.evidence import EvidenceEndpoint, EvidenceGraph, EvidenceNodeKind
from scar.ir.v2.ids import LogicalValueID, ObjectID, ValueVersionID
from scar.ir.v2.values import LogicalValue, ObjectBinding, ValueGraph, ValueVersion
from scar.ir.program.validation import require_valid
from tests.fixtures.execution_frame_identity_graphs import (
    _normal_value, _use_value, frame_identity_execution,
)


_BUDGET = 1048576
_FLAGS = ('source_runtime_verified', 'runtime_identity_verified',
          'value_identity_verified', 'transformation_authorized')


def _index(program, model, details):
    require_valid(program)
    report = validate_execution(model, program, evidence_graphs=details['evidence_graphs'])
    assert report.valid, report.issues
    return ExecutionIndex(model, program, evidence_graphs=details['evidence_graphs'])


def _candidate(view, endpoint):
    rows = tuple(row for row in view['terminal_candidates'] if row['source'].id == endpoint['source'])
    assert len(rows) == 1
    return rows[0]


def _identity_binding(binding):
    assert binding['match'] is True
    assert binding['binding_kind'] == 'DECLARED_SCOPED_OBJECT_IDENTITY'
    assert binding['ordinary_binding']['match'] is None
    assert binding['identity_guard']['match'] is True
    assert binding['identity_guard']['status'] == 'DECLARED_SAME_OBJECT'
    assert len(binding['identity_guard']['inventory']) == 2
    assert all(binding['identity_guard'][flag] is False for flag in _FLAGS)


def test_independent_current_frame_identity_supports_each_real_terminal_without_copy_or_peer_borrowing():
    program, model, details = frame_identity_execution(instances=2, retry=True)
    index = _index(program, model, details)
    assert len(model.body_activation_origins) == 2
    assert len(model.body_drive_executions) == details['static']['base_drive_count'] * 2
    assert details['objects'][0] != details['objects'][1]
    for number, endpoint in enumerate(details['frame_identities']):
        view = index.body_state_history(endpoint['read'], budget=_BUDGET)
        # This is the first semantic assertion: the old implementation has
        # all actual ports/call routes, but cannot use declared object identity.
        assert view['expected_bool'] is True
        assert view['observed_branch'] is True
        assert view['drive_inventory'] == program.body_drives
        assert view['commit_inventory'] == program.body_outcome_commits
        assert view['budget']['truncated'] is False
        candidate = _candidate(view, endpoint)
        assert candidate['commit'] == endpoint['publication']
        assert candidate['post_established'] is candidate['expected_bool'] is True
        assert candidate['drive_support']['supported'] is True
        assert candidate['source_chain']['supported'] is candidate['read_chain']['supported'] is True
        assert candidate['source_chain']['root'] == candidate['read_chain']['root'] == endpoint['caller_activation']
        assert candidate['terminal_route']
        _identity_binding(candidate['subject_binding'])
        _identity_binding(candidate['source_subject_binding'])
        _identity_binding(candidate['drive_support']['creation_binding'])
        # F is stable under the original native/no-reset contract. It does not
        # assert that opaque calls or the real context writes preserved content.
        assert candidate['content_preservation']['preserved'] is None
        assert candidate['content_preservation']['blockers']
        assert candidate['terminal_scope'].applicability.value == 'UNKNOWN'
        assert view['read_scope'].applicability.value == 'UNKNOWN'
        peer = _candidate(view, details['frame_identities'][1 - number])
        assert peer['expected_bool'] is None
        assert all(view[flag] is False for flag in (*_FLAGS, 'native_phase_verified'))


def _unchanged_sources(view, program, original):
    assert view['drive_inventory'] == program.body_drives
    assert view['commit_inventory'] == program.body_outcome_commits
    assert view['source_keys'] == original['source_keys']
    assert {row['source'].id for row in view['terminal_candidates']} == {
        row['source'].id for row in original['terminal_candidates']}


def test_same_request_body_write_and_independent_current_b2_cannot_use_old_b1_terminal_history():
    program, model, details = frame_identity_execution(instances=2, retry=True, body_write=True)
    index = _index(program, model, details)
    first, second = details['frame_identities']
    example = details['instances'][0]
    finished = details['static']['finished_request']
    write = details['body_write']
    occurrence = example['caller_operations'][write.id]
    owner = _use_value(model, occurrence, write.uses[0].id)
    request = _normal_value(program, model, example['new_request_creation'],
                            finished['request_source'].result.index)
    assert owner.id == request.id
    access, = write.accesses
    replacement = _use_value(model, occurrence, write.uses[1].id)
    denotations = {row.value: row.identity for row in model.denotations}
    assert denotations[first['creation_handle'].id].object.object == first['object']
    assert denotations[replacement.id].object.object == second['object']
    assert denotations[first['read_value'].id].object.object == second['object']
    call = details['body_write_call']
    caller = example['caller_operations'][call.id]
    after, = tuple(row for row in model.values if row.origin == occurrence and row.value == access.after)
    assert index.state_at(OccurrencePoint(caller, OccurrencePhase.BEFORE))[access.location] == after.id
    actual = next(use for use in call.uses if use.id in call.invoke_arguments
        and next(value for value in program.values if value.id == use.value).id == access.after)
    assert _use_value(model, caller, actual.id).id == after.id
    comparison = index.object_identity(first['publication_owners'][-1].id,
                                       first['read_value'].id, budget=_BUDGET)
    assert comparison['match'] is False and comparison['status'] == 'DECLARED_DISTINCT_OBJECTS'
    view = index.body_state_history(first['read'], budget=_BUDGET)
    assert view['expected_bool'] is None and view['observed_branch'] is True
    candidate = _candidate(view, first)
    assert candidate['post_established'] is True
    assert candidate['subject_binding']['match'] is False
    assert candidate['expected_bool'] is None
    assert not any(row['expected_bool'] is True for row in view['terminal_candidates'])
    # Different candidates are ordinary alternatives, not global model errors.
    sibling = index.body_state_history(second['read'], budget=_BUDGET)
    assert sibling['expected_bool'] is True
    assert _candidate(sibling, second)['post_established'] is True


@pytest.mark.parametrize('missing', ('read_identity', 'read_use', 'read_state', 'create_input', 'drive_input'))
def test_missing_exact_identity_or_actual_port_keeps_source_inventory_and_the_complete_sibling(missing):
    program, model, details = frame_identity_execution(instances=2, retry=True)
    first, second = details['frame_identities']
    original = _index(program, model, details).body_state_history(first['read'], budget=_BUDGET)
    static, example = details['static'], details['instances'][0]
    if missing == 'read_identity':
        changed = replace(model, denotations=tuple(row for row in model.denotations
                                                   if row.value != first['read_value'].id))
    else:
        if missing in ('read_use', 'read_state'):
            predicate = next(row for row in program.operations if row.id == static['finished_request']['predicate'].id)
            occurrence = first['read']
            use = (static['finished_request']['body_row'].contract.subject.instance_use
                   if missing == 'read_use' else predicate.accesses[0].before)
        elif missing == 'create_input':
            occurrence = example['creation']
            create = next(row for row in program.operations if row.id == static['primary_creation'].operation)
            values = {row.id: row for row in program.values}
            use = next(use.id for use in create.uses if use.id in create.invoke_arguments
                       and type(values[use.value]) is StateVersionValue)
        else:
            drive = static['drivers'][-1]['drive']
            occurrence = example['driver_scopes'][-1][2][drive.operation]
            use = drive.state_inputs[0].source
        changed = replace(model, uses=tuple(row for row in model.uses
                                            if (row.operation, row.use) != (occurrence, use)))
    index = _index(program, changed, details)
    view = index.body_state_history(first['read'], budget=_BUDGET)
    _unchanged_sources(view, program, original)
    assert view['expected_bool'] is None
    candidate = _candidate(view, first)
    assert candidate['expected_bool'] is None
    assert view['gaps'] or candidate['gaps'] or candidate['subject_binding']['gaps']
    assert index.body_state_history(second['read'], budget=_BUDGET)['expected_bool'] is True


@pytest.mark.parametrize('scope', ('different_object', 'different_artifact'))
def test_identity_comparison_keeps_distinct_object_false_and_cross_artifact_unknown_local(scope):
    program, model, details = frame_identity_execution(instances=2, retry=True)
    first, second = details['frame_identities']
    target = first['read_value'].id
    if scope == 'different_object':
        identity = ObjectIdentity(ObjectRef(details['identity_artifact'], second['object']))
    else:
        graph = EvidenceGraph()
        graph.register_external(EvidenceEndpoint(EvidenceNodeKind.OBJECT, first['object']))
        graph.add_control_event('a separate exact catalog; URI alone is not scope')
        artifact = external_artifact(graph, 'memory:independent-current-frame-catalog')
        identity = ObjectIdentity(ObjectRef(artifact, first['object']))
        details = {**details, 'evidence_graphs': {**details['evidence_graphs'], artifact.sha256: graph}}
    changed = replace(model, denotations=tuple(replace(row, identity=identity) if row.value == target else row
                                              for row in model.denotations))
    index = _index(program, changed, details)
    comparison = index.object_identity(first['publication_owners'][-1].id, target, budget=_BUDGET)
    assert len(comparison['inventory']) == 2
    assert comparison['match'] is (False if scope == 'different_object' else None)
    assert comparison['status'] == ('DECLARED_DISTINCT_OBJECTS' if scope == 'different_object' else 'UNPROVED')
    assert index.body_state_history(first['read'], budget=_BUDGET)['expected_bool'] is None
    assert index.body_state_history(second['read'], budget=_BUDGET)['expected_bool'] is True
    assert index.report.valid
    assert all(comparison[flag] is False for flag in _FLAGS)


def test_tiny_budget_keeps_both_identity_endpoints_and_all_original_history_sources_unchecked():
    program, model, details = frame_identity_execution(instances=2, retry=True)
    index = _index(program, model, details)
    first = details['frame_identities'][0]
    full = index.body_state_history(first['read'], budget=_BUDGET)
    comparison = index.object_identity(first['publication_owners'][-1].id, first['read_value'].id, budget=1)
    assert tuple(row['role'] for row in comparison['inventory']) == ('source', 'target')
    assert tuple(row['value'].id for row in comparison['inventory']) == (
        first['publication_owners'][-1].id, first['read_value'].id)
    assert comparison['match'] is None and comparison['cursor']
    assert comparison['budget']['used'] <= 1 and comparison['budget']['truncated'] is True
    view = index.body_state_history(first['read'], budget=1)
    _unchanged_sources(view, program, full)
    assert view['expected_bool'] is None and view['cursor']
    assert view['budget']['used'] <= 1 and view['budget']['truncated'] is True
    assert not any(row['expected_bool'] is True for row in view['terminal_candidates'])


def test_identity_query_rechecks_a_missing_catalog_and_rejects_changed_bytes_on_refresh():
    program, model, details = frame_identity_execution(instances=2, retry=True)
    index = _index(program, model, details)
    first = details['frame_identities'][0]
    left, right = first['publication_owners'][-1].id, first['read_value'].id
    assert index.object_identity(left, right, budget=_BUDGET)['match'] is True
    catalogs = details['evidence_graphs']
    saved = dict(catalogs)
    catalogs.clear()
    missing = index.object_identity(left, right, budget=_BUDGET)
    assert missing['match'] is None and len(missing['inventory']) == 2
    assert missing['gaps'] or missing['source_gaps']
    catalogs.update(saved)
    details['identity_graph'].add_control_event('catalog mutated after index construction')
    with pytest.raises(ValueError, match='snapshot|artifact|external'):
        index.object_identity(left, right, budget=_BUDGET)


def test_value_graph_registration_scan_is_budgeted_without_losing_either_endpoint():
    program, model, details = frame_identity_execution(instances=2, retry=True)
    graph = ValueGraph()
    # Neither target is registered until after a substantial unrelated prefix.
    # These bindings declare catalog membership, not ordinary value copies.
    unrelated = tuple(ObjectID(f'frame.identity.unrelated.{number}') for number in range(100))
    for number, identity in enumerate((*unrelated, *details['objects'])):
        logical = LogicalValueID(f'frame.identity.registry.logical.{number}')
        version = ValueVersionID(logical, 0)
        graph.add_logical_value(LogicalValue(logical, 'declared reference registry'))
        graph.add_version(ValueVersion(version))
        graph.add_binding(ObjectBinding(identity, version,
            evidence='supplied registry without native capture'))
    assert graph.validate()['valid'] is True
    artifact = external_artifact(graph, 'memory:declared-current-frame-value-registry')
    assignments = details['object_assignments']
    changed = replace(model, denotations=tuple(
        replace(row, identity=ObjectIdentity(ObjectRef(artifact, assignments[row.value])))
        if row.value in assignments else row for row in model.denotations))
    require_valid(program)
    catalogs = {artifact.sha256: graph}
    report = validate_execution(changed, program, value_graphs=catalogs,
                                evidence_graphs=details['evidence_graphs'])
    assert report.valid, report.issues
    index = ExecutionIndex(changed, program, value_graphs=catalogs,
                           evidence_graphs=details['evidence_graphs'])
    first = details['frame_identities'][0]
    left, right = first['publication_owners'][-1].id, first['read_value'].id
    complete = index.object_identity(left, right, budget=_BUDGET)
    assert complete['match'] is True and complete['status'] == 'DECLARED_SAME_OBJECT'
    assert all(row['registered'] is True for row in complete['inventory'])
    assert complete['budget']['costs']['object_identity_registry_bindings'] > 100
    limited = index.object_identity(left, right, budget=16)
    assert tuple(row['role'] for row in limited['inventory']) == ('source', 'target')
    assert tuple(row['value'].id for row in limited['inventory']) == (left, right)
    assert limited['match'] is None and limited['status'] == 'UNPROVED'
    assert limited['budget']['truncated'] is True and limited['budget']['used'] <= 16
    assert limited['cursor']['phase'] == 'registry_bindings'
    assert 'object_identity_budget_exhausted' in limited['gaps']
    assert all(limited[flag] is False for flag in _FLAGS)


@pytest.mark.parametrize('removed', ('association', 'predicate'))
def test_optional_request_projection_and_body_predicate_have_distinct_history_obligations(removed):
    program, model, details = frame_identity_execution(instances=2, retry=True)
    first = details['frame_identities'][0]
    finished = details['static']['finished_request']
    original = _index(program, model, details).body_state_history(first['read'], budget=_BUDGET)
    target = finished['association_row'] if removed == 'association' else finished['body_row']
    changed_program = replace(program, protocol_operations=tuple(row for row in program.protocol_operations
                                                                  if row != target))
    changed = replace(model, snapshot=snapshot_for(changed_program))
    view = _index(changed_program, changed, details).body_state_history(first['read'], budget=_BUDGET)
    _unchanged_sources(view, changed_program, original)
    assert view['expected_bool'] is (True if removed == 'association' else None)
    if removed == 'association':
        assert not any(row == finished['association_row'] for row in changed_program.protocol_operations)
        candidate = _candidate(view, first)
        _identity_binding(candidate['subject_binding'])
    else:
        assert view['predicate'] is None and 'body_state_predicate_unresolved' in view['gaps']
