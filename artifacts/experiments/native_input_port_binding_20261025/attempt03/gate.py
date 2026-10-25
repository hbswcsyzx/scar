"""One Root-launched offline binding from the saved G1 and genuine binder."""
from hashlib import sha256
import json
from pathlib import Path
import re
import sys
import time
import traceback

HERE = Path(__file__).resolve().parent
BASE = HERE.parents[3]


def pin_sources(freeze):
    total = 0
    for item in freeze['sources'] + freeze['runner']:
        raw = (BASE / item['path']).read_bytes()
        if len(raw) != item['bytes'] or sha256(raw).hexdigest() != item['sha256']:
            raise ValueError('producer/runner freeze changed: ' + item['path'])
        total += len(raw)
    return total


def main():
    freeze = json.loads((HERE / 'freeze.json').read_bytes())
    source_hash_bytes = pin_sources(freeze)
    from scar.trace.native_capture_batch import bind_native_capture_model_batches
    from scar.trace.native_tensor_inputs import NativeInputPayloadBudget
    from scar.ir.record_codec import encode
    from scar.ir.program.providers import ProviderFactReference
    first_positive = []
    negatives = []

    def consume(shard, metadata):
        if negatives:
            return
        expected, _ = metadata._expected(shard)
        if not expected:
            return
        metadata.check(shard, expected)
        baseline = expected[0]
        original = baseline['native_producer']['instance']['instance']['value']
        candidates = [x for x in shard.evidence.instances.values()
                      if x.metadata.get('provider') == 'ETO' and x.id.value != original
                      and type(x.metadata.get('rf_id')) is int and x.metadata['rf_id'] > 0]
        if not candidates:
            raise ValueError('same-Run alternate original producer unavailable for sole negative')
        alternate = candidates[0]
        match = re.fullmatch(r'sha256:([0-9a-f]{64})(#/nodes/[0-9]+)', alternate.metadata['raw_reference'])
        if match is None or match[1] != baseline['native_producer']['source']['artifact']['sha256']:
            raise ValueError('alternate producer lacks original exact ETO ordinal')
        changed = json.loads(json.dumps(expected))
        changed[0]['native_producer']['instance']['instance'] = encode(alternate.id)
        changed[0]['native_producer']['source'] = encode(ProviderFactReference(
            shard.execution.denotations[0].source.artifact, match[2]))
        # Reseal the candidate transport; the true canonical lease is retained.
        resealed = json.dumps(changed, sort_keys=True, separators=(',', ':'), allow_nan=False).encode()
        try:
            metadata.check(shard, json.loads(resealed))
        except ValueError as error:
            if 'producer/path/source mismatch' not in str(error):
                raise ValueError('sole negative failed for an unrelated reason') from error
            negatives.append({'case': 'same_Run_wrong_native_producer_and_ordinal', 'rejected': True,
                'reason': str(error), 'candidate_sha256': sha256(resealed).hexdigest(),
                'original_producer': original, 'changed_producer': alternate.id.value,
                'canonical_lease_changed': False, 'failure_was_old_owner_hash_scope': False})
        else:
            raise ValueError('wrong native input producer was accepted')
        first_positive.append(baseline)

    result = bind_native_capture_model_batches(freeze['G1_capture_model']['uri'], HERE / 'products',
        expected_sha256=freeze['G1_capture_model']['sha256'], input_budget=NativeInputPayloadBudget(68000000, 1000000),
        on_verified_shard=consume,
        progress=lambda row: (HERE / 'progress.json').write_text(json.dumps(row, sort_keys=True) + '\n'))
    report = result.report
    counts = report['metadata_counts']
    assert report['declared_dispatch_attempts'] == report['enumerated_dispatch_groups'] == 261
    assert report['G1_dispatch_outcomes'] == {'RAISED': 1, 'RETURNED': 260}
    assert report['modeled_dispatches'] <= 260
    assert counts['rows'] == 2332 and counts['metadata_paths'] == counts['metadata_at_exact_native_path'] == 3095
    assert report['verified_shards_consumed'] == len(result.native.report['shards'])
    assert len(negatives) == len(first_positive) == 1 and counts['associated_metadata_paths'] > 0
    assert sum(counts['metadata_dispositions'].values()) == 3095
    assert report['input_budget']['stored_plus_decoded_bytes'] <= 68000000
    assert report['input_budget']['control_metadata_bytes'] <= 1000000
    assert report['input_budget']['pending_reserved_bytes'] == 0
    assert report['input_budget']['completed_verified_phase_bytes'] == report['input_budget']['stored_plus_decoded_bytes']
    closure = report['native_parent_closure']
    assert closure['native_parent_nodes'] == 2332
    assert closure['missing_parent_edge_count'] == 1 and closure['parent_frontier_node_count'] == 2
    assert closure['whole_tree_parent_closure_established'] is False
    assert closure['qualified_leases_have_complete_required_parent_closure'] is True
    assert not any(report[k] for k in ('target_executions', 'capture_imports', 'OS_interface_imports',
        'whole_model_established', 'source_call_binding_established', 'logical_content_established',
        'state_effects_established', 'resource_ready_established'))
    pins = {str((BASE / r['path']).resolve()): r for r in freeze['sources']}
    imported = []
    for module in tuple(sys.modules.values()):
        name = getattr(module, '__file__', None)
        if name:
            path = Path(name).resolve()
            if path.is_relative_to(BASE / 'scar') and path.suffix == '.py':
                assert str(path) in pins, 'unfrozen imported SCAR source: ' + str(path)
                imported.append(str(path.relative_to(BASE)))
    source_hash_bytes += pin_sources(freeze)
    return {'status': 'NATIVE_INPUT_METADATA_CANONICAL_SUBSET_BOUND_WITH_OPEN_FRONTIERS',
        'native': {k: v for k, v in report.items() if k not in ('input_budget', 'own_source_hash_checks')},
        'input_budget': report['input_budget'], 'sole_negative': negatives[0], 'first_positive': first_positive[0],
        'frozen_imported_SCAR_sources': imported, 'producer_source_hash_bytes_separate': source_hash_bytes,
        'new_target_runs': 0, 'new_captures': 0, 'G1_reimports': 0, 'old1901_reads': 0,
        'source_calls': {'count': 271, 'bound_bodies': 0, 'status': 'OPEN_UNRESOLVED'},
        'full_model': 'OPEN'}


if __name__ == '__main__':
    if any((HERE / name).exists() for name in ('result.json', 'failure.json', 'products')):
        raise SystemExit('fresh offline attempt required')
    start = time.monotonic()
    try:
        document = main()
    except BaseException as error:
        document = {'status': 'OFFLINE_NATIVE_INPUT_BINDING_FAILED', 'error_type': type(error).__name__,
            'message': str(error), 'traceback': traceback.format_exc(), 'elapsed_seconds': time.monotonic()-start,
            'new_target_runs': 0, 'new_captures': 0, 'G1_reimports': 0, 'full_model': 'OPEN'}
        with (HERE / 'failure.json').open('x') as stream:
            json.dump(document, stream, sort_keys=True, indent=2)
        print(json.dumps(document), flush=True)
        raise
    document['elapsed_seconds'] = time.monotonic()-start
    with (HERE / 'result.json').open('x') as stream:
        json.dump(document, stream, sort_keys=True, indent=2)
    print(json.dumps(document), flush=True)
