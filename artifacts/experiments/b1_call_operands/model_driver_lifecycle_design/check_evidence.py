"""Read-only archive verification; do not execute probes, tests or workloads."""
import ast
import hashlib
import json
from pathlib import Path


BASE = Path(__file__).resolve().parent


def read(name):
    return json.loads((BASE / name).read_text())


def main():
    manifest = read('manifest.json')['files']
    actual_names = {str(path.relative_to(BASE)) for path in BASE.rglob('*')
                    if path.is_file() and path.name != 'manifest.json'}
    assert actual_names == set(manifest)
    for name, item in manifest.items():
        path = (BASE / name).resolve()
        assert BASE in path.parents and not (BASE / name).is_symlink(), name
        raw = path.read_bytes()
        assert len(raw) == item['bytes'], name
        assert hashlib.sha256(raw).hexdigest() == item['sha256'], name
    receipt, source = read('receipt.json'), read('source_audit.json')
    prior = read('../model_driver_implementation/full/source.after.json')
    assert receipt['design_gate_status'] == 'OPEN' and receipt['review_completed']
    assert all(receipt[key] is False for key in (
        'd2_product_implemented', 'd2_fields_frozen', 'full_first_stage_complete',
        'lewm_speedup_measured', 'new_pytest_run', 'new_lewm_gpu_run'))
    assert source['files'] == prior['files'] and not source['changed_product_files']
    assert source['source_sha256'] == prior['source_sha256'] == receipt['source_sha256']
    assert len(source['files']) == source['source_file_count'] == receipt['source_file_count'] == 415
    assert all(not row['worktree_status'] for row in source['protected_checkouts'].values())
    probe = read('review/session_release_probe.json')
    assert probe['attempt'] == 1 and probe['passed'] == 3 and probe['failed'] == probe['exit_code'] == 0
    assert probe['torch_imported'] == probe['scar_imported'] == 0
    assert all(case['status'] == 'PASS' for case in probe['cases'])
    assert {case['case'] for case in probe['cases']} == {
        'callback_changes_post', 'raise_after_partial_write', 'unraisable_keeps_completion_and_effects'}
    assert probe['cases'][0]['final_phase'] == 'HOLD'
    assert probe['cases'][1]['final_phase'] == 'COMPLETE' and probe['cases'][1]['world'] == 1
    assert probe['cases'][2]['result'] == 'KEPT' and probe['cases'][2]['world'] == 1
    assert receipt['session_probe_assertion_cases'] == {'passed': 3, 'failed': 0}
    observation = read('review/lifecycle_probe.json')['observations']
    assert len(observation) == receipt['lifecycle_probe_observation_groups'] == 6
    tree = ast.parse((BASE / 'review/lifecycle_probe.py').read_text())
    assert not any(isinstance(node, ast.Assert) for node in ast.walk(tree))
    assert receipt['lifecycle_probe_contains_assertions'] is False
    async_retry = observation['asyncgen_close_yield_then_retry']
    assert async_retry['retry_error'] == 'StopAsyncIteration'
    assert async_retry['final_state'] == 'AGEN_SUSPENDED'
    assert observation['close_yield_then_retry']['final_state'] == 'GEN_CLOSED'
    assert observation['created_close_no_body']['body_log'] == []
    assert observation['terminal_frame_drop_reentry']['release_callbacks'] == [
        {'observed_state': 'GEN_CLOSED', 'reentry_result': 'StopIteration'}]
    first = read('review/lifecycle_probe.attempt1.json')['observations']
    assert first['asyncgen_close_yield_then_retry']['final_state'] == 'AGEN_SUSPENDED'
    for stem in ('session_release_probe', 'lifecycle_probe', 'lifecycle_probe.attempt1'):
        assert (BASE / f'review/{stem}.json').read_bytes() == (BASE / f'review/{stem}.log').read_bytes()
    initial = (BASE / 'review/adversarial.initial.md').read_bytes()
    assert hashlib.sha256(initial).hexdigest() == '729319f0f3b4d24ccb1a1d6f6f8198929771ad51b586e7f8fc7884e685cc8e1c'
    assert b'Review correction record' in (BASE / 'review/adversarial.md').read_bytes()
    print(json.dumps({'archive_integrity': 'PASS', 'files': len(manifest),
        'design_gate_status': 'OPEN', 'source_unchanged_since_d1': True,
        'session_assertion_cases': 3, 'lifecycle_observation_groups': 6,
        'd2_product_implemented': False}))


if __name__ == '__main__':
    main()
