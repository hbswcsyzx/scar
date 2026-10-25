"""Root-held MAIN public V2 gate; retained artifacts supply data, never tool code."""
from collections import Counter
from dataclasses import replace
from hashlib import sha256
import json
from pathlib import Path
import sys
import time
import traceback

HERE = Path(__file__).resolve().parent
BASE = HERE.parents[3]


def verify_sources(freeze):
    count = 0
    for item in freeze['sources'] + freeze['runner']:
        raw = (BASE / item['path']).read_bytes()
        assert len(raw) == item['bytes'] and sha256(raw).hexdigest() == item['sha256'], item['path']
        count += len(raw)
    return count


def main():
    freeze = json.loads((HERE / 'freeze.json').read_bytes())
    assert BASE == Path('/home/zyf/AAA/scar-worktrees/structured-program-model').resolve()
    assert freeze['producer_source_root'] == str(BASE)
    source_read_bytes = verify_sources(freeze)
    from scar.trace.native_capture_batch import bind_native_capture_model_batches
    from scar.trace.native_tensor_inputs import NativeInputPayloadBudget
    from scar.ir.execution.native_port_protocol import SCALAR_INPUT_CAPABILITY_V2, NativePortOrderError, _make_evidence
    from scar.ir.execution.content import DataIdentity, NativeInputRef
    from scar.ir.execution.codec import dumps, loads
    from scar.ir.record_codec import decode, encode
    from scar.ir.program.providers import ProviderArtifact
    observations, negatives, consumed = [], [], []
    runtime_kinds = Counter()

    def consume(shard, _metadata):
        assert shard.execution.snapshot.artifact == decode(ProviderArtifact, freeze['static_program'])
        assert not shard.program.literal_evaluations
        native = shard.native_port_evidence
        # Existing immutable replay inventory, already independently checked.
        # No saved qualification/bulk artifact or extra raw pass is read here.
        for interface in json.loads(native._interfaces):
            for port in interface['ports']['inputs']:
                if port['tensor']: continue
                scalar = port['scalar_input']
                runtime_kinds[(scalar.get('formal_kind', 'ABSENT'), scalar.get('formal_real_kind', 'ABSENT'),
                    port['type'], scalar['frontier'] or 'QUALIFIED')] += 1
        denotations = tuple(d for d in shard.execution.denotations if type(d.identity) is DataIdentity)
        # One genuine scope + immutable projection check for this whole ordered
        # query; no per-leaf full-model serialization or naked-ID memo.
        answers = shard.native_port_evidence.scalar_values(shard.execution, shard.program, denotations, shard.values)
        assert len(answers) == len(denotations)
        consumed.append(shard.report['sequences'])
        for d, answer in zip(denotations, answers, strict=True):
            assert type(d.basis) is NativeInputRef
            assert answer.version == d.identity.version and answer.value == d.value and answer.source == d.source
            version = shard.values.versions[answer.version.version]
            origin = shard.values.provenance[version.provenance_id]
            assert not version.parent_versions and not origin.inputs and origin.producer is None
            assert origin.relation.value == 'origin'
            observations.append(encode(answer))
        equal_ints, pair = {}, None
        for d, answer in zip(denotations, answers, strict=True):
            interface, position = native._scalar_versions[answer.version.version]
            port = interface['ports']['inputs'][position]
            scalar = port['scalar_input']
            if (port['type'] == 'Int' and scalar['formal_kind'] == scalar['formal_real_kind'] == 'NumberType'
                    and answer.literal.kind.value == 'int'):
                content = json.dumps(encode(answer.literal), sort_keys=True)
                if content in equal_ints:
                    pair = (equal_ints[content], (d, answer)); break
                equal_ints[content] = (d, answer)
        if pair is not None and not negatives:
            (first, a), (second, z) = pair
            assert encode(a.literal) == encode(z.literal)
            assert a.version != z.version and a.value != z.value and a.source != z.source
            # These are separate actual NumberType+Int observations. The test
            # claims neither different content nor pre-conversion origins.
            changed = replace(shard.execution, denotations=tuple(
                replace(d, identity=second.identity, source=second.source) if d.id == first.id else
                replace(d, identity=first.identity, source=first.source) if d.id == second.id else d
                for d in shard.execution.denotations))
            changed = loads(dumps(changed))
            native = shard.native_port_evidence
            try:
                _make_evidence(native._owned, shard.program, changed, native._value_artifact, native._evidence_artifact,
                    _prepared=native._prepared, _scalar_projection=native._scalar_projection)
            except NativePortOrderError as error:
                assert 'native_scalar_source' in str(error) and 'native_scalar_identity' in str(error)
                assert 'does not apply' not in str(error)
                negatives.append({'case': 'swap_equal_NumberType_Int_observation_roots_source_and_version', 'rejected': True,
                    'reason': str(error), 'independent_source_slot_rejection': True, 'old_seal_rejection': False,
                    'equal_content': True, 'different_content_or_upstream_claimed': False,
                    'roots': [encode(a.version), encode(z.version)]})
            else:
                raise ValueError('scalar source/version exchange accepted')

    result = bind_native_capture_model_batches(freeze['G1_capture_model']['uri'], HERE / 'products',
        expected_sha256=freeze['G1_capture_model']['sha256'], input_budget=NativeInputPayloadBudget(68000000, 1000000),
        scalar_input_profile=SCALAR_INPUT_CAPABILITY_V2, static_program=decode(ProviderArtifact, freeze['static_program']),
        static_interface=decode(ProviderArtifact, freeze['static_interface']), on_verified_shard=consume,
        progress=lambda row: (HERE / 'progress.json').write_text(json.dumps(row, sort_keys=True)+'\n'))
    report, native = result.report, result.native.report
    assert native['shared_program'] == freeze['static_program'] and native['shared_interface'] == freeze['static_interface']
    assert report['modeled_dispatches'] == 260 and report['enumerated_dispatch_groups'] == 261
    assert report['metadata_counts']['rows'] == 2332 and report['metadata_counts']['metadata_paths'] == 3095
    assert report['metadata_counts']['associated_metadata_paths'] == 516
    assert report['scalar_observed_roots'] == len(observations)
    assert sum(runtime_kinds.values()) == report['scalar_input_ports'] == 264
    for key, expected in freeze['baseline_reference_counts'].items():
        assert native[key] == expected, (key, native[key], expected)
    def footprint(row):
        return json.dumps({key: row[key] for key in ('literal', 'builtin_type', 'source', 'value')} |
                          {'version_id': row['version']['version']}, sort_keys=True)
    assert set(map(footprint, freeze['baseline_V1_observations'])) <= set(map(footprint, observations))
    assert report['scalar_input_ports'] == report['scalar_observed_roots'] + sum(report['scalar_frontiers'].values())
    assert len({json.dumps(r['version'],sort_keys=True) for r in observations}) == len(observations)
    assert len(consumed) == report['verified_shards_consumed'] == 2
    assert report['input_budget']['pending_reserved_bytes'] == 0
    assert report['input_budget']['stored_plus_decoded_bytes'] <= 68000000
    assert report['input_budget']['control_metadata_bytes'] <= 1000000
    if len(negatives) != 1:
        return {'status': 'BLOCKED_NO_QUALIFIED_ACTUAL_EQUAL_NUMBER_INT_PAIR', 'observations': observations,
                'report': report, 'new_target_runs': 0, 'full_model': 'OPEN', 'gate_exit': 2}
    frozen = {str((BASE/r['path']).resolve()): r for r in freeze['sources']}
    imported = []
    denied = set(freeze['forbidden_import_modules'])
    for name, module in sorted(sys.modules.items()):
        if name != 'scar' and not name.startswith('scar.'): continue
        assert name not in denied, 'unrelated Scope module unexpectedly imported: ' + name
        filename = getattr(module, '__file__', None)
        assert filename is not None, 'SCAR module has no exact current source path: ' + name
        path = Path(filename).resolve()
        assert path.is_relative_to(BASE/'scar') and path.suffix == '.py', 'SCAR import escaped main: ' + str(path)
        assert str(path) in frozen, 'unfrozen current SCAR import: ' + str(path)
        imported.append({'module': name, 'path': str(path), 'sha256': frozen[str(path)]['sha256']})
    assert set(freeze['required_live_modules']) <= {x['module'] for x in imported}
    observed_kinds = [dict(zip(('formal_kind','formal_real_kind','provider_type','status'), key), count=count)
        for key, count in sorted(runtime_kinds.items())]
    assert observed_kinds == freeze['expected_iso_v2_runtime_kinds']
    assert report['scalar_observed_roots'] == freeze['expected_iso_v2_counts']['scalar_observed_roots']
    assert report['scalar_frontiers'] == freeze['expected_iso_v2_counts']['scalar_frontiers']
    source_read_bytes += verify_sources(freeze)
    return {'status': 'MAIN_OWNED_NATIVE_SCALAR_UNION_V2_VERIFIED_WITH_FRONTIERS',
        'producer_source_root': str(BASE), 'actual_SCAR_imports': imported,
        'unrelated_Scope_modules_imported': [], 'main_all_source_pins': len(freeze['sources']),
        'same_iso_v2_runtime_counts_preserved': True,
        'scalar_profile': SCALAR_INPUT_CAPABILITY_V2,
        'runtime_kind_distribution': [dict(zip(('formal_kind','formal_real_kind','provider_type','status'), key), count=count)
            for key, count in sorted(runtime_kinds.items())],
        'V1_observation_footprints_preserved': True, 'builtin_type_is_literal_representation_only': True,
        'preconversion_Python_type_or_enum_symbolic_origin_established': False, 'program_snapshot_unchanged': True,
        'observations': observations, 'sole_negative': negatives[0], 'report': report,
        'source_hash_read_bytes_separate': source_read_bytes, 'new_target_runs': 0, 'new_captures': 0,
        'new_G1_imports': 0, 'old8MB_association_reads': 0, 'Tensor_content_established': False,
        'upstream_producers_established': False, 'state_ready_established': False, 'full_model': 'OPEN', 'gate_exit': 0}


if __name__ == '__main__':
    if any((HERE/n).exists() for n in ('products','result.json','failure.json')):raise SystemExit('fresh gate required')
    started=time.monotonic()
    try:
        result=main()
    except BaseException as error:
        result={'status':'INCOMPLETE_MAIN_NATIVE_SCALAR_UNION_V2_GATE','error_type':type(error).__name__,
            'message':str(error),'traceback':traceback.format_exc(),'elapsed_seconds':time.monotonic()-started,
            'new_target_runs':0,'full_model':'OPEN'}
        with (HERE/'failure.json').open('x') as s:json.dump(result,s,sort_keys=True,indent=2)
        print(json.dumps(result),flush=True)
        raise
    result['elapsed_seconds']=time.monotonic()-started
    with (HERE/'result.json').open('x') as s:json.dump(result,s,sort_keys=True,indent=2)
    print(json.dumps(result),flush=True)
    raise SystemExit(result['gate_exit'])
