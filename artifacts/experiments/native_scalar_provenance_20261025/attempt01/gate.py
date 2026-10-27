"""Root-held offline scalar observed roots, over the saved CPU capture only."""
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
    source_read_bytes = verify_sources(freeze)
    from scar.trace.native_capture_batch import bind_native_capture_model_batches
    from scar.trace.native_tensor_inputs import NativeInputPayloadBudget
    from scar.ir.execution.native_port_protocol import SCALAR_INPUT_CAPABILITY, NativePortOrderError, _make_evidence
    from scar.ir.execution.content import DataIdentity, NativeInputRef
    from scar.ir.execution.codec import dumps, loads
    from scar.ir.record_codec import decode, encode
    from scar.ir.program.providers import ProviderArtifact
    observations, negatives, consumed = [], [], []

    def consume(shard, _metadata):
        assert shard.execution.snapshot.artifact == decode(ProviderArtifact, freeze['static_program'])
        assert not shard.program.literal_evaluations
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
        none = [(d, r) for d, r in zip(denotations, answers, strict=True) if r.literal.kind.value == 'none']
        if len(none) >= 2 and not negatives:
            (first, a), (second, z) = none[:2]
            assert encode(a.literal) == encode(z.literal)
            assert a.version != z.version and a.value != z.value and a.source != z.source
            # The same content is compatible with separate observation roots;
            # this does not assert different underlying values or upstreams.
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
                negatives.append({'case': 'swap_equal_None_observation_roots_source_and_version', 'rejected': True,
                    'reason': str(error), 'independent_source_slot_rejection': True, 'old_seal_rejection': False,
                    'equal_content': True, 'different_content_or_upstream_claimed': False,
                    'roots': [encode(a.version), encode(z.version)]})
            else:
                raise ValueError('scalar source/version exchange accepted')

    result = bind_native_capture_model_batches(freeze['G1_capture_model']['uri'], HERE / 'products',
        expected_sha256=freeze['G1_capture_model']['sha256'], input_budget=NativeInputPayloadBudget(68000000, 1000000),
        scalar_input_profile=SCALAR_INPUT_CAPABILITY, static_program=decode(ProviderArtifact, freeze['static_program']),
        static_interface=decode(ProviderArtifact, freeze['static_interface']), on_verified_shard=consume,
        progress=lambda row: (HERE / 'progress.json').write_text(json.dumps(row, sort_keys=True)+'\n'))
    report, native = result.report, result.native.report
    assert native['shared_program'] == freeze['static_program'] and native['shared_interface'] == freeze['static_interface']
    assert report['modeled_dispatches'] == 260 and report['enumerated_dispatch_groups'] == 261
    assert report['metadata_counts']['rows'] == 2332 and report['metadata_counts']['metadata_paths'] == 3095
    assert report['metadata_counts']['associated_metadata_paths'] == 516
    assert report['scalar_observed_roots'] == len(observations)
    assert report['scalar_input_ports'] == report['scalar_observed_roots'] + sum(report['scalar_frontiers'].values())
    assert len({json.dumps(r['version'],sort_keys=True) for r in observations}) == len(observations)
    assert len(consumed) == report['verified_shards_consumed'] == 2
    assert report['input_budget']['pending_reserved_bytes'] == 0
    assert report['input_budget']['stored_plus_decoded_bytes'] <= 68000000
    assert report['input_budget']['control_metadata_bytes'] <= 1000000
    if len(negatives) != 1:
        return {'status': 'BLOCKED_NO_QUALIFIED_ACTUAL_EQUAL_NONE_PAIR', 'observations': observations,
                'report': report, 'new_target_runs': 0, 'full_model': 'OPEN', 'gate_exit': 2}
    frozen = {str((BASE/r['path']).resolve()) for r in freeze['sources']}
    for module in tuple(sys.modules.values()):
        name = getattr(module,'__file__',None)
        if name:
            p = Path(name).resolve()
            if p.is_relative_to(BASE/'scar') and p.suffix=='.py':assert str(p) in frozen,'unfrozen SCAR import'
    source_read_bytes += verify_sources(freeze)
    return {'status': 'OWNED_NATIVE_SCALAR_OBSERVED_ROOTS_VERIFIED_WITH_FRONTIERS',
        'scalar_profile': SCALAR_INPUT_CAPABILITY, 'program_snapshot_unchanged': True,
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
        result={'status':'INCOMPLETE_NATIVE_SCALAR_PROVENANCE_GATE','error_type':type(error).__name__,
            'message':str(error),'traceback':traceback.format_exc(),'elapsed_seconds':time.monotonic()-started,
            'new_target_runs':0,'full_model':'OPEN'}
        with (HERE/'failure.json').open('x') as s:json.dump(result,s,sort_keys=True,indent=2)
        print(json.dumps(result),flush=True)
        raise
    result['elapsed_seconds']=time.monotonic()-started
    with (HERE/'result.json').open('x') as s:json.dump(result,s,sort_keys=True,indent=2)
    print(json.dumps(result),flush=True)
    raise SystemExit(result['gate_exit'])
