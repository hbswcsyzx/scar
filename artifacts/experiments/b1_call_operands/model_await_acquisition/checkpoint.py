"""Archive an await-model progress checkpoint; never starts tests/workloads."""
import hashlib
import json
from pathlib import Path
import subprocess
import sys
import xml.etree.ElementTree as ET

from scripts.run_gate import fingerprint

ROOT = Path.cwd()
HERE = Path(__file__).resolve().parent
BASE = '0bbc6235992e89e2a5735287e94622cfe0755cf8'
PRIOR = HERE.parent / 'model_async_pipeline'
MANIFEST = HERE / 'checkpoint.json'
MAXIMUM_MIGRATIONS = (
    'test_lifecycle_composition_codec.py', 'test_program_admission_codec.py',
    'test_program_driver_codec.py', 'test_program_exception_match_codec.py',
    'test_program_literal_codec.py', 'test_program_lookup_fallback_codec.py',
    'test_program_no_body_codec.py', 'test_program_protocol_codec.py',
    'test_program_publication_codec.py', 'test_program_resumption_codec.py',
    'test_program_session_release_codec.py', 'test_program_state_address_codec.py',
)
FUTURE_MIGRATIONS = {
    'test_program_method_lookup_codec.py': 'test_program_graph_rejects_future_or_boolean_schema_versions',
    'test_program_exception_match_codec.py': 'test_future_and_boolean_schema_versions_remain_rejected',
    'test_program_lookup_fallback_codec.py': 'test_future_and_boolean_schema_versions_remain_rejected',
}


def normalize(identities):
    changes = {('tests.unit.' + Path(name).stem, test + '[23]'):
               ('tests.unit.' + Path(name).stem, test + '[24]')
               for name, test in FUTURE_MIGRATIONS.items()}
    return {changes.get(identity, identity) for identity in identities}


def migrate(name, before):
    expected, steps = before, []
    base = Path(name).name
    if base in MAXIMUM_MIGRATIONS:
        assert expected.count(b'SCHEMA_VERSION == 22') == 1
        expected = expected.replace(b'SCHEMA_VERSION == 22', b'SCHEMA_VERSION == 23')
        steps.append('maximum-reader22->23 only')
    if base in FUTURE_MIGRATIONS:
        variants = [(b'"version", [23, True]', b'"version", [24, True]'),
                    (b'"version", (23, True)', b'"version", (24, True)')]
        old, new = next((old, new) for old, new in variants if old in expected)
        assert expected.count(old) == 1
        expected = expected.replace(old, new)
        steps.append('future-version23->24; strict rejection retained; case identity explicitly migrated')
    if base == 'test_program_protocol_connection_records.py':
        original = b'from scar.ir.program.protocol_connections import ('
        assert expected.count(original) == 1
        expected = expected.replace(original,
            b'from scar.ir.program.protocol_await_records import AwaitBodyLink\n' + original)
        original = b'\n' + b' ' * 43 + b'CancelHandling, TaskStatusRead, DelegateLookupFallback}'
        assert expected.count(original) == 1
        expected = expected.replace(original,
            b'\n' + b' ' * 47 + b'CancelHandling, TaskStatusRead, DelegateLookupFallback, AwaitBodyLink}')
        steps.append('exact closed binding set explicitly adds AwaitBodyLink')
    return expected, steps


def git(*args, cwd=ROOT):
    return subprocess.check_output(['git', *args], cwd=cwd)


def sha(path):
    return hashlib.sha256(path.read_bytes()).hexdigest()


def cases(path, passed=False):
    rows = tuple(ET.parse(path).iter('testcase'))
    assert rows, path
    if passed:
        assert all(not any(row.find(tag) is not None for tag in ('failure', 'error', 'skipped'))
                   for row in rows), path
    identities = {(row.get('classname'), row.get('name')) for row in rows}
    assert len(identities) == len(rows), path
    return identities


def main():
    design = json.loads((HERE / 'design-baseline.json').read_text())
    freeze = json.loads((HERE / 'design-freeze.json').read_text())
    assert design['base_revision'] == freeze['baseline'] == BASE
    assert sha(ROOT / freeze['scope_plan']) == design['scope_plan_sha256'] == freeze['scope_sha256']
    assert sha(ROOT / freeze['contract']) == freeze['contract_sha256']
    assert sha(HERE / 'contract-reviewed-draft-97f2aaf1.md') == freeze['reviewed_draft_sha256']
    assert len(design['obligation_groups']) == 16 and design['completed_obligation_groups'] == []
    prior = json.loads((PRIOR / 'checkpoint.json').read_text())
    assert prior['protected'] == design['protected']
    for state in design['protected'].values():
        assert git('rev-parse', 'HEAD', cwd=state['path']).decode().strip() == state['head']
        assert git('status', '--porcelain=v1', cwd=state['path']).decode() == state['status']
    original_tests, original_fixtures, migrations = {}, {}, {}
    for name in git('ls-tree', '-r', '--name-only', BASE, 'tests').decode().splitlines():
        before = git('show', BASE + ':' + name)
        now = (ROOT / name).read_bytes()
        expected, steps = migrate(name, before) if name.startswith('tests/unit/') else (before, [])
        assert now == expected, name
        if steps:
            migrations[name] = steps
        original_tests[name] = hashlib.sha256(before).hexdigest()
        if name.startswith('tests/fixtures/'):
            original_fixtures[name] = original_tests[name]
    assert len(migrations) == 14
    frozen = ('docs/M1_PROTOCOL_CONTRACT.md', 'docs/M1_PROTOCOL_CONNECTION_CONTRACT.md',
              'docs/M1_PENDING_PAYLOAD_PLAN.md', 'docs/M1_REMAINING_PROTOCOL_PLAN.md',
              'docs/M1_CLEANUP_INTERFACES.md', 'scar/ir/execution/model.py',
              'scar/ir/execution/codec.py', 'scar/ir/execution/resumables.py')
    for name in frozen:
        assert (ROOT / name).read_bytes() == git('show', BASE + ':' + name), name
    for name, digest in prior['files'].items():
        if name.startswith('artifacts/'):
            assert sha(ROOT / name) == digest, name
    native = json.loads((HERE / 'native-evidence.json').read_text())
    assert len(native['cases']) == 12 and native['script_sha256'] == sha(HERE / 'audit_native.py')
    assert native['plan_sha256'] == freeze['scope_sha256']
    final = HERE / 'accepted-focused'
    result = json.loads((final / 'result.json').read_text())
    digest, sources = fingerprint()
    assert result['returncode'] == 0 and result['source_unchanged']
    assert digest == result['source_sha256_before'] == result['source_sha256_after']
    previous_original = cases(PRIOR / 'final-focused/junit.xml', passed=True)
    previous = normalize(previous_original)
    current = cases(final / 'junit.xml', passed=True)
    assert len(previous) == 1308 and previous <= current, 'original case identity lost'
    assert len(previous_original & current) == 1305
    assert len(previous_original - current) == 3
    assert cases(HERE / 'first-contract-and-old-regression/junit.xml', passed=True) <= current
    attempts = {}
    for path in sorted(HERE.rglob('junit.xml')):
        rows = tuple(ET.parse(path).iter('testcase'))
        ordinary = {identity for identity in cases(path)
                    if identity[0] and identity[0].startswith('tests.unit.')}
        assert normalize(ordinary) <= current, path
        attempts[str(path.relative_to(HERE))] = {
            'tests': len(rows), 'ordinary_case_ids_retained': len(ordinary),
            'failures': sum(row.find('failure') is not None for row in rows),
            'errors': sum(row.find('error') is not None for row in rows)}
    docs = [ROOT / name for name in (
        'docs/M1_AWAIT_ACQUISITION_PLAN.md', 'docs/M1_AWAIT_ACQUISITION_CONTRACT.md',
        'docs/M1_AWAIT_ACQUISITION_PROGRESS.md')]
    paths = [path for path in HERE.rglob('*') if path.is_file() and path != MANIFEST
             and '__pycache__' not in path.parts] + docs
    record = {'status': 'PROGRESS_ARCHIVE_FULL_A_H_OPEN', 'base_revision': BASE,
        'source_sha256': digest, 'source_files': len(sources), 'focused_cases': len(current),
        'previous_focused_obligations_retained': len(previous), 'new_cases': len(current - previous),
        'unchanged_previous_case_identities': len(previous_original & current),
        'explicit_case_identity_migrations': {str(old): str(new) for old, new in
            zip(sorted(previous_original - current), sorted(previous - previous_original))},
        'existing_test_assertion_migration': migrations, 'original_fixtures': original_fixtures,
        'attempts': attempts, 'program_maximum_schema_version': 23,
        'old_program_bytes_independent_oracle': 'test_independent_v22_archive_encoder_preserves_meaningful_fallback_bytes',
        'execution8_implementation_unchanged': True, 'protected': design['protected'],
        'obligation_groups': design['obligation_groups'], 'completed_obligation_groups': [],
        'full_A_H_complete': False, 'p4_complete': False, 'm0_m2_complete': False,
        'full_regression_on_this_source': False, 'source_runtime_verified': False,
        'transformation_authorized': False, 'new_lewm_speedup': False, 'new_backend': False,
        'tests_started_by_archive_check': 0,
        'files': {str(path.relative_to(ROOT)): sha(path) for path in sorted(paths)}}
    if sys.argv[1:] == ['--write']:
        assert not MANIFEST.exists()
        MANIFEST.write_text(json.dumps(record, indent=2) + '\n')
    else:
        assert sys.argv[1:] == ['--check']
        assert record == json.loads(MANIFEST.read_text())
    print(json.dumps({key: record[key] for key in ('status', 'source_sha256', 'source_files',
        'focused_cases', 'previous_focused_obligations_retained', 'new_cases',
        'full_A_H_complete', 'p4_complete', 'm0_m2_complete', 'tests_started_by_archive_check')}, indent=2))


if __name__ == '__main__':
    main()
