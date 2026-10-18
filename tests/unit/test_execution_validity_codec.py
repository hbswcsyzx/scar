"""V6 capability isolation and independent v1-v5 bytes at the wire boundary."""
from copy import deepcopy
from dataclasses import replace
import hashlib
import json
from pathlib import Path

import pytest

from scar.ir.execution.codec import SCHEMA_VERSION, dumps, from_dict, loads, to_dict
from scar.ir.execution.validity import ContributionSupport, EstablishedProduction
from tests.fixtures.execution_validity_records import validity_record_model

FIXTURES = Path(__file__).parents[1] / 'fixtures'
FIELDS = ('established_productions', 'target_lifetime_events', 'order_associations', 'contribution_supports')


def test_v6_wire_preserves_all_new_capabilities_and_exact_nested_variants():
    model = validity_record_model()
    document = to_dict(model)
    assert SCHEMA_VERSION >= 7
    assert document['schema_version'] == 6
    assert all(document['model']['fields'][name] for name in FIELDS)
    restored = loads(dumps(model))
    assert restored == model and dumps(restored) == dumps(model)
    assert type(restored.established_productions[0]) is EstablishedProduction
    assert type(restored.contribution_supports[0]) is ContributionSupport


@pytest.mark.parametrize('version', range(1, 6))
def test_independent_old_golden_bytes_remain_exact_and_supply_only_empty_v_defaults(version):
    payload = (FIXTURES / f'execution_v{version}_frozen.json').read_bytes()
    restored = loads(payload.decode())
    assert dumps(restored, schema_version=version).encode() == payload
    assert all(getattr(restored, name) == () for name in FIELDS)
    assert to_dict(restored)['schema_version'] == version


def test_v5_golden_proof_names_pre_v_codec_and_all_p_tables():
    payload = (FIXTURES / 'execution_v5_frozen.json').read_bytes()
    proof = json.loads((FIXTURES / 'execution_v5_frozen.json.proof.json').read_text())
    assert proof['revision'] == 'f2b4672d9555348dcd05da62a8cd126711ef22f9'
    assert proof['codec_sha256'] == '981ce8adbae591a9fea25534d9987923c901db8a2fb4861e20a52b5755057dc7'
    assert proof['payload_sha256'] == hashlib.sha256(payload).hexdigest()
    assert proof['payload_bytes'] == len(payload) == 64321
    assert proof['p_table_counts'] == dict(produced=3, source_bridges=10, source_inventories=1, writes=4)


@pytest.mark.parametrize('version', range(1, 6))
def test_populated_validity_cannot_be_downgraded(version):
    with pytest.raises(ValueError, match='validity capability'):
        dumps(validity_record_model(), schema_version=version)


@pytest.mark.parametrize('version', range(1, 6))
def test_older_vocabulary_cannot_reach_new_tag_or_accept_even_empty_new_tables(version):
    document = json.loads((FIXTURES / f'execution_v{version}_frozen.json').read_text())
    document['model']['fields']['runs'][0]['fields']['source'] = {
        '$record': 'scar.ir.execution.validity.EstablishedProduction', 'fields': {}}
    with pytest.raises(ValueError, match='unknown type tag'):
        from_dict(document)
    document = json.loads((FIXTURES / f'execution_v{version}_frozen.json').read_text())
    document['model']['fields']['contribution_supports'] = []
    with pytest.raises(ValueError, match='missing or unknown fields'):
        from_dict(document)


@pytest.mark.parametrize('field', FIELDS)
def test_empty_validity_keeps_lowest_schema_and_false_like_tampering_cannot_hide_it(field):
    original = loads((FIXTURES / 'execution_v5_frozen.json').read_text())
    assert to_dict(original)['schema_version'] == 5
    broken = replace(original)
    object.__setattr__(broken, field, [])
    with pytest.raises(ValueError):
        dumps(broken)


@pytest.mark.parametrize('corruption', ('id-namespace', 'bool-value', 'unknown-field', 'wrong-domain', 'untyped-production'))
def test_v6_nested_forgery_rejected(corruption):
    document = to_dict(validity_record_model())
    support = document['model']['fields']['contribution_supports'][0]['fields']
    if corruption == 'id-namespace':
        support['id']['kind'] = 'exec_write_association'
    elif corruption == 'bool-value':
        support['write']['value'] = True
    elif corruption == 'unknown-field':
        support['ready'] = True
    elif corruption == 'wrong-domain':
        support['visibility']['fields']['domain'] = deepcopy(support['write'])
    else:
        support['production'] = 'production.outcome.region'
    with pytest.raises(ValueError):
        from_dict(document)


def test_codec_does_not_open_or_resolve_artifacts_for_validity_records(monkeypatch):
    model = validity_record_model()
    def forbidden(*args, **kwargs):
        raise AssertionError('wire codec may not resolve facts')
    monkeypatch.setattr('builtins.open', forbidden)
    monkeypatch.setattr('scar.ir.execution.snapshot.ExternalSnapshots.graph', forbidden)
    assert loads(dumps(model)) == model


def test_empty_explicit_v6_migrates_back_to_lowest_populated_capability():
    model = loads((FIXTURES / 'execution_v5_frozen.json').read_text())
    assert to_dict(model, schema_version=6)['schema_version'] == 6
    assert to_dict(loads(dumps(model, schema_version=6)))['schema_version'] == 5
