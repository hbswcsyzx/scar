"""V7 wire associations; these local records do not claim a valid execution."""
from copy import deepcopy
from dataclasses import fields, replace
from hashlib import sha256
import json
from pathlib import Path

import pytest

from scar.ir.execution import CallActivation, CallActivationID
from scar.ir.execution.codec import SCHEMA_VERSION, dumps, from_dict, loads, to_dict
from scar.ir.execution.common import Unresolved
from scar.ir.execution.ids import BlockVisitID, OperationOccurrenceID, RegionActivationID
from scar.ir.program.providers import ProviderFactReference
from tests.fixtures.execution_validity_records import validity_record_model

FIXTURES = Path(__file__).parents[1] / 'fixtures'


def _call_model(*, unresolved=False, provider_source=False):
    """Exercise rich nested wire variants, without graph validation or proof."""
    model = validity_record_model()
    gap = Unresolved('call observation is missing, not proof of pending or no effects',
                     model.activations[0].entry)
    source = (ProviderFactReference(model.snapshot.artifact, 'declared-call-pair')
              if provider_source else model.runs[0].source)
    call = CallActivation(CallActivationID('wire.call'), model.operations[0].id,
        model.activations[0].id, gap if unresolved else model.visits[0].id,
        gap if unresolved else model.operations[-1].id, source)
    return replace(model, call_activations=(call,))


@pytest.mark.parametrize('unresolved', (False, True))
@pytest.mark.parametrize('provider_source', (False, True))
def test_v7_roundtrip_keeps_exact_original_ids_and_unresolved_variants(unresolved, provider_source):
    model = _call_model(unresolved=unresolved, provider_source=provider_source)
    document = to_dict(model)
    assert SCHEMA_VERSION == document['schema_version'] == 7
    restored = loads(dumps(model))
    assert restored == model
    assert dumps(restored) == dumps(model)
    call, = restored.call_activations
    assert type(call) is CallActivation
    assert type(call.id) is CallActivationID
    assert call.id.wire == 'exec_call_activation:wire.call'
    assert type(call.caller) is OperationOccurrenceID
    assert type(call.activation) is RegionActivationID
    assert type(call.entry) is (Unresolved if unresolved else BlockVisitID)
    assert type(call.completion) is (Unresolved if unresolved else OperationOccurrenceID)
    assert tuple(field.name for field in fields(call)) == (
        'id', 'caller', 'activation', 'entry', 'completion', 'source')
    assert not hasattr(call, 'arguments') and not hasattr(call, 'results')
    assert not hasattr(call, 'runtime_verified')


@pytest.mark.parametrize('version', range(1, 7))
def test_all_independent_v1_to_v6_golden_bytes_and_empty_call_defaults_remain_exact(version):
    payload = (FIXTURES / f'execution_v{version}_frozen.json').read_bytes()
    model = loads(payload.decode('utf-8'))
    assert model.call_activations == ()
    assert dumps(model, schema_version=version).encode('utf-8') == payload
    assert to_dict(model)['schema_version'] == version
    assert 'call_activations' not in to_dict(model)['model']['fields']


def test_v6_golden_was_generated_by_old_codec_and_old_rich_validity_fixture():
    payload = (FIXTURES / 'execution_v6_frozen.json').read_bytes()
    proof = json.loads((FIXTURES / 'execution_v6_frozen.json.proof.json').read_text())
    assert proof['revision'] == '348d18277b963bc183fb420bf173f05594d667d8'
    assert proof['schema_version'] == 6
    assert proof['codec_sha256'] == 'b8520a675e5c07d1a6c6cfbba1d1efea790c445535fef4c2e3897d5b2bea7580'
    assert proof['fixture_source'] == 'tests/fixtures/execution_validity_records.py'
    assert proof['fixture_sha256'] == 'a2c99cd2f7deba2c8aa1e03118d9d09476049082c15cd39ef5a78b1ec339d83c'
    assert proof['payload_sha256'] == sha256(payload).hexdigest() == (
        'fa27345cfc12c97865e975206099970e61621b0689f60967fc6445045a96a570')
    assert proof['payload_bytes'] == len(payload) == 94738
    assert proof['validity_table_counts'] == dict(established_productions=2,
        target_lifetime_events=2, order_associations=2, contribution_supports=7)
    assert proof['immutable_blobs']['scar/ir/execution/codec.py'] == proof['codec_sha256']
    assert proof['immutable_blobs'][proof['fixture_source']] == proof['fixture_sha256']
    assert json.loads(payload)['model']['fields'].get('call_activations') is None


@pytest.mark.parametrize('version', range(1, 7))
def test_populated_call_association_cannot_be_silently_downgraded(version):
    with pytest.raises(ValueError, match='call capability'):
        dumps(_call_model(), schema_version=version)


@pytest.mark.parametrize('version', range(1, 7))
def test_explicit_empty_v7_roundtrips_but_auto_chooses_original_capability(version):
    model = loads((FIXTURES / f'execution_v{version}_frozen.json').read_text())
    document = to_dict(model, schema_version=7)
    assert document['schema_version'] == 7
    assert document['model']['fields']['call_activations'] == []
    restored = from_dict(document)
    assert restored == model
    assert to_dict(restored)['schema_version'] == version


@pytest.mark.parametrize('version', range(1, 7))
@pytest.mark.parametrize('injection', ('table', 'record-tag', 'id-tag'))
def test_pre_call_schemas_reject_new_table_and_unreachable_call_tags(version, injection):
    document = json.loads((FIXTURES / f'execution_v{version}_frozen.json').read_text())
    root = document['model']['fields']
    if injection == 'table':
        root['call_activations'] = []
        message = 'missing or unknown fields'
    elif injection == 'record-tag':
        root['runs'][0]['fields']['source'] = {
            '$record': 'scar.ir.execution.calls.CallActivation', 'fields': {}}
        message = 'unknown type tag'
    else:
        root['runs'][0]['fields']['id'] = {
            '$id': 'scar.ir.execution.ids.CallActivationID', 'kind': 'exec_call_activation',
            'value': 'wire.call', 'wire': 'exec_call_activation:wire.call'}
        message = 'unknown type tag'
    with pytest.raises(ValueError, match=message):
        from_dict(document)


@pytest.mark.parametrize('corruption', (
    'missing-table', 'missing-entry', 'extra-actuals', 'unknown-record', 'wrong-caller-family',
    'wrong-entry-family', 'wrong-completion-family', 'untyped-activation', 'bool-id',
    'wrong-prefix', 'wrong-wire', 'wrong-source-family', 'null-completion',
))
def test_v7_rejects_missing_fields_unknown_tags_and_wrong_union_identity(corruption):
    document = to_dict(_call_model())
    root = document['model']['fields']
    encoded = root['call_activations'][0]
    call = encoded['fields']
    if corruption == 'missing-table':
        del root['call_activations']
    elif corruption == 'missing-entry':
        del call['entry']
    elif corruption == 'extra-actuals':
        call['arguments'] = []
    elif corruption == 'unknown-record':
        encoded['$record'] = 'untrusted.calls.CallActivation'
    elif corruption == 'wrong-caller-family':
        call['caller'] = deepcopy(call['activation'])
    elif corruption == 'wrong-entry-family':
        call['entry'] = deepcopy(call['caller'])
    elif corruption == 'wrong-completion-family':
        call['completion'] = deepcopy(call['entry'])
    elif corruption == 'untyped-activation':
        call['activation'] = 'exec_region_activation:untyped'
    elif corruption == 'bool-id':
        call['id']['value'] = True
    elif corruption == 'wrong-prefix':
        call['id']['kind'] = 'exec_region_activation'
    elif corruption == 'wrong-wire':
        call['id']['wire'] = 'exec_call_activation:other'
    elif corruption == 'wrong-source-family':
        call['source'] = deepcopy(call['activation'])
    else:
        call['completion'] = None
    with pytest.raises(ValueError):
        from_dict(document)


@pytest.mark.parametrize('corruption', ('false-like-table', 'subclass-row', 'mutated-id'))
def test_local_mutation_cannot_hide_capability_or_bypass_exact_records(corruption):
    model = _call_model()
    if corruption == 'false-like-table':
        object.__setattr__(model, 'call_activations', [])
    elif corruption == 'subclass-row':
        class DerivedCall(CallActivation):
            pass
        row, = model.call_activations
        object.__setattr__(model, 'call_activations', (DerivedCall(
            row.id, row.caller, row.activation, row.entry, row.completion, row.source),))
    else:
        object.__setattr__(model.call_activations[0].id, 'value', True)
    with pytest.raises(ValueError):
        dumps(model)


@pytest.mark.parametrize('version', (True, 0, -1, '7', 8))
def test_new_max_version_does_not_admit_bool_string_or_future_version(version):
    model = _call_model()
    with pytest.raises(ValueError, match='schema_version'):
        dumps(model, schema_version=version)
    document = to_dict(model)
    document['schema_version'] = version
    with pytest.raises(ValueError, match='schema_version'):
        from_dict(document)


def test_call_wire_never_runs_graph_validation_resolves_artifacts_or_follows_urls(monkeypatch):
    model = _call_model(unresolved=True, provider_source=True)

    def forbidden(*args, **kwargs):
        raise AssertionError('codec must not establish graph or runtime correspondence')

    monkeypatch.setattr('builtins.open', forbidden)
    monkeypatch.setattr('scar.ir.execution.validation.validate', forbidden)
    monkeypatch.setattr('scar.ir.execution.snapshot.ExternalSnapshots.graph', forbidden)
    assert loads(dumps(model)) == model
