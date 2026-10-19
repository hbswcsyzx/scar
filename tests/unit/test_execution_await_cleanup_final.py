"""Current pending projection, persistent B, and exact final call occurrences."""
import pytest

from scar.ir.execution.composition_routes import routes
from scar.ir.execution.query import ExecutionIndex
from scar.ir.execution.validity_budget import ValidityBudget
from scar.ir.execution.validation import validate
from scar.ir.program.control import PendingPayload
from scar.ir.program.validation import require_valid
from tests.fixtures.execution_await_cleanup_final_graphs import await_cleanup_final_execution


BUDGET = 1048576


def _index(program, model):
    require_valid(program)
    validation = validate(model, program)
    assert validation.valid, validation.issues
    return ExecutionIndex(model, program)


def _row(report, details):
    result, = tuple(row for row in report['outcomes']
        if row['definition']['drive_outcome'] == details['drive_outcome']
        and row['definition']['advance_operation'] == details['static']['advance_operation'])
    return result


def _occurrence(row, example):
    result, = tuple(item for item in row['occurrences'] if item['advance'] is not None
        and item['advance'].id == example['advance']
        and item['drive'] is not None and item['drive'].id == example['body_drives'][-1].drive)
    return result


def _projection(report, example):
    arguments = tuple(argument for transfer in report['transfers']
        if transfer['occurrence'].id == example['dispatch'] for argument in transfer['arguments']
        if type(argument['argument']) is PendingPayload)
    assert len(arguments) == 1
    return arguments[0]['projection']['payload']


@pytest.mark.parametrize(('body_raised', 'depth', 'child_raised'),
    ((False, 1, False), (False, 2, True), (True, 1, False)),
    ids=('cleanup-return-child-normal', 'cleanup-return-nested-child-raise', 'cleanup-body-raise'))
def test_actual_pending_payload_reaches_this_b_terminal_and_its_own_await_consumer(
        body_raised, depth, child_raised):
    program, model, details = await_cleanup_final_execution(body_raised=body_raised,
        depth=depth, child_raised=child_raised)
    index = _index(program, model)
    projected = routes(index._content_context(), budget=ValidityBudget(BUDGET))
    report = index.await_body_links(details['static']['acquisition_scope'], budget=BUDGET)
    row = _row(report, details)
    for example in details['instances']:
        assert len(example['body_segments']) == 3
        witness = _projection(projected, example)
        assert witness['constructor'].id == example['pending_constructor']
        assert witness['definition'] == example['pending_definition']
        assert witness['selector'].operation == example['dispatch']
        assert witness['payload_use'].operation == example['pending_constructor']
        assert witness['payload_use'].use == example['pending_payload_use']
        assert witness['payload_value'].id != next(use.value for use in model.uses
            if use.operation == example['dispatch'] and use.use == witness['selector'].use)
        assert witness['target_value'].id != witness['payload_value'].id
        assert witness['binding']['match'] is True
        assert witness['token_path']
        occurrence = _occurrence(row, example)
        assert occurrence['selected'] is True
        assert occurrence['body_outcome'].id == example['body_outcome']
        assert occurrence['drive'].id == example['body_drives'][-1].drive
        consumers = tuple(consumer for consumer in occurrence['consumers']
                          if consumer['definition']['actual'] == details['static']['extract_input'])
        assert consumers and all(consumer['binding']['match'] is True for consumer in consumers)
        assert all(consumer['operation'].id == (example['final'] if body_raised else example['extraction'])
                   for consumer in consumers)
        if body_raised:
            assert row['definition']['kind'] == 'EXCEPTION'
            assert occurrence['conversion_legs'] == ()
            assert all(consumer['definition']['requires_final_extraction'] is False for consumer in consumers)
            packet = details['static']['packet_use']
            payload_use, = tuple(use for use in model.uses
                if use.operation == example['final'] and use.use == packet.use)
            assert all(consumer['use'] == payload_use for consumer in consumers)
            assert all(consumer['advance_value'].id == payload_use.value for consumer in consumers)
            assert all(consumer['targets'][0]['use'] == payload_use
                and consumer['targets'][0]['binding']['match'] is True for consumer in consumers)
            # This host is on the exact last CALL's actual RAISE landing. Each
            # state Use must consume that completion's real produced slot.
            from scar.ir.program.model import CompletionResult, ExitKind

            call = details['static']['drivers'][-1]['caller_call']
            transfer, = tuple(transfer for transfer in model.transfers if transfer.operation == example['advance'])
            edge = call.terminator.successors[transfer.successor_index]
            assert edge.kind is ExitKind.RAISE
            landing = next(block for region in program.regions for block in region.blocks if block.id == edge.block)
            for slot, actual in enumerate(details['static']['state_uses'], start=1):
                formal, = tuple(formal for argument, formal in zip(edge.arguments, landing.arguments)
                                 if type(argument) is CompletionResult and argument.index == slot)
                current, = tuple(value for value in model.values
                                  if value.origin == transfer.target and value.value == formal)
                state_use, = tuple(use for use in model.uses
                                   if use.operation == example['final'] and use.use == actual.use)
                assert state_use.value == current.id
        else:
            completed = tuple(consumer for consumer in consumers
                              if consumer['definition']['requires_final_extraction'] is True)
            assert completed
            implementation = completed[0]['implementation']
            assert len(implementation['frames']) == depth
            assert tuple(frame['completion'].id for frame in implementation['frames']) == tuple(
                frame['completion'] for frame in example['implementation_frames'])
            paths = tuple(path for stage in implementation['stages'] for leg in stage['legs']
                          if leg['selected'] is True for result in leg['results'] for path in result['paths']
                          if path['selected'] is True and path['binding']['match'] is True)
            assert paths and all(path['targets'] for path in paths)
        for flag in ('source_runtime_verified', 'runtime_identity_verified',
                     'value_identity_verified', 'transformation_authorized'):
            assert report[flag] is False


@pytest.mark.parametrize('body_raised', (False, True), ids=('return-payload', 'raise-payload'))
@pytest.mark.parametrize('missing', ('missing_payload_use', 'missing_dispatch', 'missing_second_resume'))
def test_missing_instance_zero_pending_evidence_cannot_borrow_the_complete_sibling(body_raised, missing):
    program, model, details = await_cleanup_final_execution(body_raised=body_raised, **{missing: 0})
    index = _index(program, model)
    report = index.await_body_links(details['static']['acquisition_scope'], budget=BUDGET)
    row = _row(report, details)
    first = _occurrence(row, details['instances'][0])
    second = _occurrence(row, details['instances'][1])
    assert first['status'] not in ('DECLARED', 'NOT_APPLICABLE')
    assert first['gaps'] or any(consumer['gaps'] for consumer in first['consumers'])
    assert second['selected'] is True
    assert second['body_outcome'].id == details['instances'][1]['body_outcome']
    if missing == 'missing_payload_use':
        projected = routes(index._content_context(), budget=ValidityBudget(BUDGET))
        absent = _projection(projected, details['instances'][0])
        present = _projection(projected, details['instances'][1])
        assert absent['binding']['match'] is not True and absent['gaps']
        assert present['binding']['match'] is True
        assert present['payload_use'].operation != details['instances'][0]['pending_constructor']


def test_dynamic_budget_one_keeps_the_static_outcome_key_and_unknown_cursor():
    program, model, details = await_cleanup_final_execution(instances=1)
    index = _index(program, model)
    report = index.await_body_links(details['static']['acquisition_scope'], budget=1)
    assert any(row['definition']['drive_outcome'] == details['drive_outcome'] for row in report['outcomes'])
    assert report['outcome_inventory']['known_inventory_complete'] is False
    assert report['outcome_inventory']['jobs_total'] is None
    assert report['cursor'] is not None or report['outcome_inventory']['cursor'] is not None


def test_pending_payload_projection_rejects_known_same_artifact_object_identity_conflict():
    from dataclasses import replace

    from scar.ir.execution.await_outcome_evidence import pair
    from scar.ir.execution.common import Unresolved
    from scar.ir.execution.content import ObjectIdentity, ObjectRef, ValueDenotation
    from scar.ir.execution.ids import DenotationID
    from scar.ir.execution.snapshot import external_artifact
    from scar.ir.program.model import ReferenceValue
    from scar.ir.v2.evidence import EvidenceEndpoint, EvidenceGraph, EvidenceNodeKind
    from scar.ir.v2.ids import ObjectID

    program, model, details = await_cleanup_final_execution(instances=1)
    example = details['instances'][0]
    uses = {(use.operation, use.use): use for use in model.uses}
    values = {value.id: value for value in model.values}
    source_use = uses[example['pending_constructor'], example['pending_payload_use']]
    source_value = values[source_use.value]
    dispatch = next(operation for operation in program.operations
                    if operation.id == details['static']['pending_projection'].id)
    transfer, = tuple(row for row in model.transfers if row.operation == example['dispatch'])
    edge = dispatch.terminator.successors[transfer.successor_index]
    block = next(block for region in program.regions for block in region.blocks if block.id == edge.block)
    formal, = tuple(formal for actual, formal in zip(edge.arguments, block.arguments)
                     if type(actual) is PendingPayload)
    target_value, = tuple(value for value in model.values
                          if value.origin == transfer.target and value.value == formal)
    canonical = {value.id: value for value in program.values}
    assert type(canonical[source_value.value]) is type(canonical[target_value.value]) is ReferenceValue
    assert source_value.id != target_value.id

    evidence = EvidenceGraph()
    original, different = ObjectID('cleanup.pending.original'), ObjectID('cleanup.pending.different')
    for identity in (original, different):
        evidence.register_external(EvidenceEndpoint(EvidenceNodeKind.OBJECT, identity))
    artifact = external_artifact(evidence, 'memory:cleanup-pending-payload-object-conflict')
    basis = Unresolved('scoped object declarations, not runtime identity evidence', details['point'])
    declarations = tuple(ValueDenotation(DenotationID('cleanup.pending.' + label), value.id,
        ObjectIdentity(ObjectRef(artifact, identity)), basis, details['source'])
        for label, value, identity in (('source', source_value, original),
                                       ('target', target_value, different)))
    changed = replace(model, denotations=(*model.denotations, *declarations))
    assert changed.operations == model.operations and changed.values == model.values
    assert changed.uses == model.uses and changed.transfers == model.transfers
    require_valid(program)
    validated = validate(changed, program, evidence_graphs={artifact.sha256: evidence})
    assert validated.valid, validated.issues
    index = ExecutionIndex(changed, program, evidence_graphs={artifact.sha256: evidence})
    context = index._content_context()
    projected = routes(context, budget=ValidityBudget(BUDGET))
    receipt = _projection(projected, example)
    assert receipt['constructor'].id == example['pending_constructor']
    assert receipt['payload_use'] == source_use
    assert receipt['payload_value'] == source_value and receipt['target_value'] == target_value
    assert receipt['binding']['match'] is False
    assert receipt['status'] == 'CONTRADICTED'

    compared = pair(context, source_value, target_value, ValidityBudget(BUDGET))
    assert compared['match'] is not True
    for report in (projected, receipt, receipt['binding'], compared):
        for flag in ('source_runtime_verified', 'runtime_identity_verified',
                     'value_identity_verified', 'transformation_authorized'):
            assert report[flag] is False
