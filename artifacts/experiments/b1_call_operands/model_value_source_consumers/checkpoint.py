"""Root-only verification of the limited value-source consumer checkpoint."""
import hashlib
import json
from pathlib import Path
import subprocess
import sys
import xml.etree.ElementTree as ET

from scripts.run_gate import fingerprint

ROOT = Path.cwd()
HERE = Path(__file__).resolve().parent
PRIOR = HERE.parent / 'model_stored_value_relations'
BASE = 'fff1895fd3abc312409b9b95d40affa9b2c06f86'
MODIFIED = {'scar/ir/execution/query.py', 'scar/ir/execution/stored_values.py',
            'scar/ir/execution/body_state_history.py'}
ADDED = {'scar/ir/execution/value_sources.py', 'scar/ir/execution/stored_value_projection.py',
         'tests/fixtures/execution_value_sources.py', 'tests/unit/test_execution_value_sources.py'}


def read(path):
    return json.loads(path.read_text())


def sha(path):
    return hashlib.sha256(path.read_bytes()).hexdigest()


def digest(value):
    return hashlib.sha256(json.dumps(value, sort_keys=True).encode()).hexdigest()


def cases(path, *, green=False):
    rows = tuple(ET.parse(path).iter('testcase'))
    ids = {(row.get('classname'), row.get('name')) for row in rows}
    counts = {'rows': len(rows), 'identities': len(ids),
              'failures': sum(row.find('failure') is not None for row in rows),
              'errors': sum(row.find('error') is not None for row in rows),
              'skips': sum(row.find('skipped') is not None for row in rows)}
    assert len(rows) == len(ids) and all(all(identity) for identity in ids)
    if green:
        assert rows and counts['failures'] == counts['errors'] == counts['skips'] == 0
    return ids, counts


def main():
    writing = sys.argv[1:] == ['--write']
    assert writing or sys.argv[1:] == ['--check']
    design = read(HERE / 'design-baseline.json')
    expected = read(HERE / 'gate-expectations.json')
    assert design['base_revision'] == BASE
    assert sha(ROOT / design['plan']) == design['plan_sha256']
    assert sha(PRIOR / 'checkpoint.json') == design['previous_checkpoint_sha256']
    # The previous immutable evidence and its own seven documents remain intact.
    for name, expected_sha in read(PRIOR / 'checkpoint.json')['files'].items():
        assert sha(ROOT / name) == expected_sha, name
    baseline = read(PRIOR / 'verified-current/sources.after.json')
    assert len(baseline) == 913 and digest(baseline) == design['source_sha256']
    diagnosis = read(HERE / 'baseline.json')
    assert diagnosis['base_revision'] == BASE and diagnosis['sources'] == baseline
    assert diagnosis['source_sha256_before'] == diagnosis['source_sha256_after'] == digest(baseline)
    assert diagnosis['stored_match'] is True and diagnosis['ordinary_match'] is None
    assert diagnosis['original_copy_table_unchanged'] and not diagnosis['value_source_pair_api_present']
    assert diagnosis['script_sha256'] == sha(HERE / 'baseline_probe.py')
    current_digest, current = fingerprint()
    assert set(baseline) <= set(current) and set(current) - set(baseline) == ADDED
    assert {name for name in baseline if baseline[name] != current[name]} == MODIFIED
    assert all(current[name] == value for name, value in baseline.items() if name.startswith('tests/'))
    depth = read(HERE / 'depth-probe-final.json')
    assert depth['returncode'] == 0 and depth['outcome'] == 'BOUNDED_UNKNOWN_WITH_DETACHED_PUBLIC_OUTPUT'
    assert depth['source_unchanged'] and depth['sources'] == current
    assert depth['source_sha256_before'] == depth['source_sha256_after'] == current_digest
    assert depth['script_sha256'] == sha(HERE / 'depth_probe.py')
    assert depth['analysis_depth_limit'] == 32 and depth['length'] == 40
    assert depth['match'] is None and depth['budget']['truncated'] and depth['cursor_present']
    attempts = {}
    for result_path in sorted(HERE.glob('*/result.json')):
        folder = result_path.parent
        result, command = read(result_path), read(folder / 'command.json')
        before, after = read(folder / 'sources.before.json'), read(folder / 'sources.after.json')
        assert before == after and result['source_unchanged']
        assert digest(before) == result['source_sha256_before'] == result['source_sha256_after']
        assert result['source_count'] == len(before) == 917
        assert command['base_revision'] == BASE and command['cwd'] == str(ROOT)
        assert command['runner_sha256'] == sha(HERE / 'run_focused.py')
        assert command['environment'] == {'PYTHONPATH': '.', 'PYTHONDONTWRITEBYTECODE': '1'}
        snapshots = read(folder / 'source-bytes.json')
        assert set(snapshots) == {name for name in before if baseline.get(name) != before[name]}
        for name, saved in snapshots.items():
            assert sha(HERE / saved['path']) == saved['sha256'] == before[name], name
        _, summary = cases(folder / 'junit.xml', green=result['returncode'] == 0)
        attempts[folder.name] = {**result, **summary}
    assert set(attempts) == set(expected['attempts'])
    for name, values in expected['attempts'].items():
        assert {key: attempts[name][key] for key in values} == values, name
    final, summary = cases(HERE / 'verified-current/junit.xml', green=True)
    assert read(HERE / 'verified-current/sources.after.json') == current
    assert attempts['verified-current']['source_sha256_after'] == current_digest
    assert read(HERE / 'verified-current/command.json')['command'][4:-1] == read(
        HERE / 'focused-selection.json')['selectors']
    old = {tuple(identity) for identity in read(PRIOR / 'case-catalog.json')['identities']}
    assert len(old) == 2304
    previous_history, _ = cases(HERE.parent / 'model_async_request_body_history/verified-current/junit.xml', green=True)
    migrations = {tuple(row['before']): tuple(row['after'])
                  for row in read(PRIOR / 'checkpoint.json')['case_id_migrations']}
    previous_history = {migrations.get(identity, identity) for identity in previous_history}
    previous_stored = {identity for identity in old if identity[0].endswith('test_execution_stored_values')}
    assert len(previous_history) == 231 and len(previous_stored) == 25
    assert previous_history | previous_stored <= final
    new = {identity for identity in final if identity[0].endswith('test_execution_value_sources')}
    assert len(new) == expected['new_cases'] and not new & old
    additional = final - old - new
    for module, _ in additional:
        source_module = next(part for part in module.split('.') if part.startswith('test_'))
        assert 'tests/unit/' + source_module + '.py' in baseline
    review = read(HERE / 'independent-review.json')
    assert review['source_sha256'] == current_digest and review['source_frozen']
    assert not review['unresolved_blocking_findings']
    for name, expected_sha in review['reviewed_files'].items():
        assert current[name] == expected_sha, name
    for folder, head in (('/home/zyf/AAA/le-wm', design['lewm_protected_head']),
                         ('/home/zyf/AAA/scar', design['scar_main_protected_head'])):
        assert subprocess.check_output(['git', 'rev-parse', 'HEAD'], cwd=folder, text=True).strip() == head
        assert not subprocess.check_output(['git', 'status', '--porcelain=v1'], cwd=folder, text=True)
    catalog = old | final
    catalog_record = {'kind': 'retained test obligations, not a claim all currently pass',
        'scope': 'known affected focused-case catalog; not whole repository or phase denominator',
        'prior_catalog': len(old), 'additional_preexisting': len(additional), 'new': len(new),
        'total': len(catalog), 'currently_retested': len(final),
        'identities': [list(identity) for identity in sorted(catalog)]}
    if writing:
        (HERE / 'case-catalog.json').write_text(json.dumps(catalog_record, indent=2) + '\n')
    else:
        assert read(HERE / 'case-catalog.json') == catalog_record
    names = [path for path in HERE.rglob('*') if path.is_file() and path.name != 'checkpoint.json']
    names += [ROOT / name for name in expected['bound_documents']]
    record = {'status': 'VERIFIED_CONDITIONAL_VALUE_SOURCE_CONSUMERS', 'base_revision': BASE,
        'source_sha256': current_digest, 'source_files': len(current),
        'current_focused': summary, 'new_case_identities': len(new),
        'prior_case_catalog_retained': len(old), 'prior_full_catalog_rerun': False,
        'prior_catalog_retested': len(final & old), 'additional_preexisting_cases': len(additional),
        'current_case_catalog_size': len(catalog), 'case_catalog_is_whole_repository': False,
        'all_prior_tests_and_fixtures_unchanged': True, 'ordinary_copy_semantics_unchanged': True,
        'program_schema': 27, 'execution_schema': 8,
        'accepted_families': 9, 'open_families': 7, 'm2_denominator': [113, 196],
        'attempts': attempts, 'f19_family_complete': False, 'first_stage_complete': False,
        'automatic_source_recovery_complete': False, 'native_target_executions': 0,
        'native_identity_verified': False, 'source_runtime_verified': False,
        'transformation_authorized': False, 'new_lewm_speedup': None,
        'files': {str(path.relative_to(ROOT)): sha(path) for path in sorted(names)}}
    if writing:
        (HERE / 'checkpoint.json').write_text(json.dumps(record, indent=2) + '\n')
    else:
        assert read(HERE / 'checkpoint.json') == record
    print(json.dumps({key: value for key, value in record.items() if key not in ('files', 'attempts')}))


if __name__ == '__main__':
    main()
