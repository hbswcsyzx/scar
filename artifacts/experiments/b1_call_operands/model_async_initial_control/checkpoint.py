"""Audit original obligations, exact source bytes and real attempts; run no tests."""
import hashlib
import json
from pathlib import Path
import subprocess
import sys
import xml.etree.ElementTree as ET

from scripts.run_gate import fingerprint


ROOT = Path.cwd()
HERE = Path(__file__).resolve().parent
PRIOR = HERE.parent / 'model_call_effect_expansions'
BASE = '96b8a322590217151ff6a5e839c7ab17d068f560'
MANIFEST = HERE / 'checkpoint.json'
ACCEPTANCE = HERE / 'original-acceptance.json'
OLD_PRODUCTS = tuple('scar/ir/' + path for path in (
    'program/codec.py', 'program/protocol_async.py',
    'program/protocol_connection_validation.py', 'program/protocol_connections.py',
    'program/protocol_query.py', 'program/protocol_rules.py',
    'program/protocol_validation.py', 'execution/resumable_sessions.py'))
NEW_PRODUCT = 'scar/ir/program/async_initial.py'
NEW_FIXTURES = tuple('tests/fixtures/' + name + '.py' for name in (
    'program_async_initial_selection_graphs', 'program_async_initial_control_graphs',
    'execution_async_initial_control_graphs'))
NEW_TESTS = tuple('tests/unit/' + name + '.py' for name in (
    'test_program_async_initial_selection', 'test_program_async_initial_control',
    'test_execution_async_initial_control', 'test_program_async_initial_control_codec'))
DOCUMENTS = tuple('docs/M1_ASYNC_INITIAL_CONTROL_' + name + '.md' for name in (
    'PLAN', 'CODEC_MIGRATION', 'F16_AUDIT', 'TERMINAL_SUPPLEMENT',
    'PROGRESS', 'ACCEPTANCE', 'NEXT_GATE'))


def read(path):
    return json.loads(path.read_text())


def sha(path):
    return hashlib.sha256(path.read_bytes()).hexdigest()


def digest(sources):
    return hashlib.sha256(json.dumps(sources, sort_keys=True).encode()).hexdigest()


def identity(selector):
    path, name = selector.split('::')
    return path.removesuffix('.py').replace('/', '.'), name


def cases(path, *, green=False):
    rows = tuple(ET.parse(path).iter('testcase'))
    result = {(row.get('classname'), row.get('name')) for row in rows}
    assert len(result) == len(rows), path
    if green:
        assert rows and not any(row.find(tag) is not None for row in rows
                               for tag in ('failure', 'error', 'skipped')), path
    return result, rows


def matches(selector, identities):
    module, name = identity(selector)
    found = sorted(row for row in identities if row[0] == module
                   and (row[1] == name or row[1].startswith(name + '[')))
    assert found, selector
    return found


def migrations(prior_sources):
    declaration = read(HERE / 'test-input-migrations.json')
    assert declaration['base_revision'] == BASE
    assert sha(ROOT / declaration['amendment']) == declaration['amendment_sha256']
    changes, moved = {}, {}
    for row in declaration['replacements']:
        changes.setdefault(row['file'], []).append((row['before'], row['after']))
        if row['kind'] == 'future_version':
            moved[identity(row['old_case'])] = identity(row['new_case'])
    assert len(changes) == declaration['expected_file_count'] == 17
    assert sum(map(len, changes.values())) == declaration['expected_replacement_count'] == 22
    assert len(moved) == declaration['migrated_testcase_count'] == 6
    for path, replacements in changes.items():
        original = subprocess.check_output(['git', 'show', f'{BASE}:{path}'], cwd=ROOT)
        assert hashlib.sha256(original).hexdigest() == prior_sources[path], path
        expected = original.decode()
        for before, after in replacements:
            assert expected.count(before) == 1, (path, before)
            expected = expected.replace(before, after, 1)
        assert (ROOT / path).read_bytes() == expected.encode(), path
    return declaration, changes, moved


def stable_attempt(folder, prior_sources):
    result = read(folder / 'result.json')
    before, after = read(folder / 'sources.before.json'), read(folder / 'sources.after.json')
    assert before == after and result['source_unchanged'], folder
    assert digest(before) == result['source_sha256_before'] == result['source_sha256_after']
    assert result['source_count'] == len(before)
    command = read(folder / 'command.json')
    assert command['base_revision'] == BASE and command['cwd'] == str(ROOT)
    assert command['runner_sha256'] == sha(HERE / 'run_focused.py')
    assert command['environment'] == {'PYTHONPATH': '.', 'PYTHONDONTWRITEBYTECODE': '1'}
    snapshots = read(folder / 'source-bytes.json')
    assert set(snapshots) == {path for path, value in before.items() if prior_sources.get(path) != value}
    for path, saved in snapshots.items():
        assert saved['sha256'] == before[path] == sha(HERE / saved['path'])
    for path, expected in before.items():
        if path not in snapshots:
            assert prior_sources[path] == expected, (folder, path)
    return result, before


def main():
    writing = sys.argv[1:] == ['--write']
    assert writing or sys.argv[1:] == ['--check']
    design, previous = read(HERE / 'design-baseline.json'), read(PRIOR / 'checkpoint.json')
    assert design['base_revision'] == BASE
    assert design['prior_checkpoint_sha256'] == sha(PRIOR / 'checkpoint.json')
    for path, expected in previous['files'].items():
        assert sha(ROOT / path) == expected, path
    for field, hash_field in (('scope_plan', 'plan_sha256'), ('codec_migration', 'codec_migration_sha256')):
        assert sha(ROOT / design[field]) == design[hash_field]
    supplement = read(HERE / 'terminal-supplement.json')
    assert sha(ROOT / supplement['amendment']) == supplement['amendment_sha256']
    prior_sources = read(PRIOR / 'verified-final/sources.after.json')
    source_digest, sources = fingerprint()
    assert len(prior_sources) == 884 and len(sources) == 892
    assert design['previous_source_sha256'] == digest(prior_sources)
    added = (NEW_PRODUCT, *NEW_FIXTURES, *NEW_TESTS)
    assert set(sources) - set(prior_sources) == set(added)
    assert set(prior_sources) <= set(sources)
    declaration, changed_tests, moved = migrations(prior_sources)
    assert {path for path in prior_sources if sources[path] != prior_sources[path]} == set(OLD_PRODUCTS) | set(changed_tests)
    for state in design['protected'].values():
        assert subprocess.check_output(['git', 'rev-parse', 'HEAD'], cwd=state['path'], text=True).strip() == state['head']
        assert subprocess.check_output(['git', 'status', '--porcelain=v1'], cwd=state['path'], text=True) == state['status']
    result, final_sources = stable_attempt(HERE / 'verified-final', prior_sources)
    assert result['returncode'] == 0 and final_sources == sources
    old, _ = cases(PRIOR / 'verified-final/junit.xml', green=True)
    current, _ = cases(HERE / 'verified-final/junit.xml', green=True)
    assert len(old) == 2016
    assert set(moved) <= old and not set(moved) & current
    assert set(moved.values()) <= current and not set(moved.values()) & old
    exact = old - set(moved)
    retained = exact | set(moved.values())
    assert len(exact) == 2010 and len(retained) == 2016 and retained <= current
    new = current - retained
    modules = {path.removesuffix('.py').replace('/', '.') for path in NEW_TESTS}
    assert len(current) == 2058 and len(new) == 42
    assert {module: sum(row[0] == module for row in new) for module in modules} == {
        'tests.unit.test_program_async_initial_selection': 6,
        'tests.unit.test_program_async_initial_control': 12,
        'tests.unit.test_execution_async_initial_control': 9,
        'tests.unit.test_program_async_initial_control_codec': 15}
    selection = read(HERE / 'focused-selection.json')
    assert selection['selectors'] == read(PRIOR / 'focused-selection.json')['selectors'] + list(NEW_TESTS)
    command = read(HERE / 'verified-final/command.json')['command']
    assert command[1:4] == ['-m', 'pytest', '-q'] and command[4:-1] == selection['selectors']
    original, family = read(HERE / 'original-obligations.json'), read(HERE / 'family-obligations.json')
    assert original == read(PRIOR / 'original-obligations.json')
    # The original ledger is an immutable historical input, not this gate's new verdict.
    assert family == read(PRIOR / 'family-obligations.json')
    review = read(HERE / 'f16-review.json')
    assert review['source_sha256'] == source_digest and review['status'] == 'CONDITIONAL_SUPPLIED_MODEL_ACCEPTANCE'
    assert review['closed_before'] == family['closed'] and review['newly_closed'] == ['F16']
    assert set(review['closed_after']) == set(family['closed']) | {'F16'}
    assert set(review['remaining_families']) == set(family['remaining_other_families']) - {'F16'}
    assert len(review['closed_after']) == len(review['remaining_families']) == 8
    assert not review['automatic_source_recovery'] and not review['transformation_authorized']
    matched = {}
    for row in (*original['rows'], *family['reviewed'], family['F14_review'], *review['clauses']):
        for selector in row['existing_selectors']:
            matched[selector] = matches(selector, current)
    for selector in family['F16_current_scope_review']['already_covered_selectors']:
        matched[selector] = matches(selector, current)
    attempts, attempt_sources = {}, {}
    expected_attempts = {
        'initial-scheduler-counterexample': (2, 2, 886),
        'first-joint-authored': (38, 4, 892),
        'joint-completeness-counterexamples': (2, 1, 892),
        'revised-joint-control': (42, 3, 892),
        'precise-original-input-chain': (3, 0, 892),
        'verified-final': (2058, 0, 892)}
    for folder in sorted(HERE.glob('*/junit.xml')):
        attempt, snapshot = stable_attempt(folder.parent, prior_sources)
        identities, rows = cases(folder)
        assert {moved.get(row, row) for row in identities} <= current, folder
        attempt_sources[folder.parent.name] = snapshot
        attempts[folder.parent.name] = {**attempt, 'cases': len(rows),
            'failures': sum(row.find('failure') is not None for row in rows),
            'errors': sum(row.find('error') is not None for row in rows),
            'skips': sum(row.find('skipped') is not None for row in rows)}
    assert set(attempts) == set(expected_attempts)
    for name, (count, failures, files) in expected_attempts.items():
        attempt = attempts[name]
        assert (attempt['cases'], attempt['failures'], attempt['source_count']) == (count, failures, files), name
        assert attempt['errors'] == attempt['skips'] == 0
        assert (attempt['returncode'] == 0) == (failures == 0)
    counter_sources = attempt_sources['initial-scheduler-counterexample']
    assert all(counter_sources[path] == value for path, value in prior_sources.items())
    assert attempt_sources['precise-original-input-chain'] == final_sources
    native, native_run = read(HERE / 'native-probe.json'), read(HERE / 'native-initial/result.json')
    for item in (native, native_run):
        assert item['script_sha256'] == sha(HERE / 'native_probe.py')
        assert item['sources'] == prior_sources
        assert item['source_sha256_before'] == item['source_sha256_after'] == digest(prior_sources)
        assert item['tests_started'] == 0
    assert native_run['returncode'] == 0 and native_run['source_unchanged']
    assert native['base_revision'] == BASE and len(native['observations']) == 11
    for name, attempt in (('processing-before.json', 'revised-joint-control'),
                          ('processing-after.json', 'verified-final')):
        value = read(HERE / name)
        assert value['script_sha256'] == sha(HERE / 'probe_processing.py')
        assert value['sources'] == attempt_sources[attempt]
        assert value['source_sha256_before'] == value['source_sha256_after'] == digest(value['sources'])
        assert value['tests_started'] == 0 and len(value['scenarios']) == 2
    before, after = read(HERE / 'processing-before.json'), read(HERE / 'processing-after.json')
    assert all(row['source_binding']['match'] is None for row in before['scenarios'])
    assert all(row['source_binding']['match'] is True and all(
        item['raw']['match'] is None and item['effective']['match'] is True for item in row['operands'])
        for row in after['scenarios'])
    reviewers = read(HERE / 'independent-review.json')
    assert reviewers['source_sha256'] == source_digest
    assert reviewers['all_authors_frozen'] and reviewers['interpreters_started_by_reviewers'] == 0
    assert set(reviewers['reviewed_sources']) == set((*OLD_PRODUCTS, *added))
    assert all(sources[path] == expected for path, expected in reviewers['reviewed_sources'].items())
    assert len(design['obligation_groups']) == 16
    assert design['m2_original_constructs'] == 113 and design['m2_original_fields'] == 196
    acceptance = {'status': 'CONDITIONAL_SUPPLIED_MODEL_F16_ACCEPTANCE',
        'source_sha256': source_digest, 'matched_selectors': matched, 'new_cases': sorted(new),
        'previous_focused_obligations_retained': len(retained), 'previous_exact_identities_retained': len(exact),
        'explicit_identity_migrations': [{'old': old_id, 'new': new_id} for old_id, new_id in sorted(moved.items())],
        'newly_closed_families': ['F16'], 'p4_complete': False, 'm0_m2_complete': False,
        'automatic_source_recovery': False, 'transformation_authorized': False, 'tests_started': 0}
    if writing:
        assert not MANIFEST.exists() and not ACCEPTANCE.exists()
        ACCEPTANCE.write_text(json.dumps(acceptance, indent=2) + '\n')
    else:
        assert read(ACCEPTANCE) == json.loads(json.dumps(acceptance))
    paths = [path for path in HERE.rglob('*') if path.is_file() and path != MANIFEST
             and '__pycache__' not in path.parts] + [ROOT / path for path in DOCUMENTS]
    record = {'status': acceptance['status'], 'base_revision': BASE, 'source_sha256': source_digest,
        'source_files': len(sources), 'focused_cases': len(current),
        'previous_focused_obligations_retained': len(retained), 'previous_exact_identities_retained': len(exact),
        'explicit_identity_migrations': len(moved), 'new_cases': len(new), 'test_input_migrations': declaration,
        'attempts': attempts, 'protected': design['protected'], 'obligation_groups': design['obligation_groups'],
        'closed_original_A_H_structural_obligations': original['closed'],
        'completed_obligation_groups': review['closed_after'], 'newly_closed_obligation_groups': ['F16'],
        'remaining_other_families': review['remaining_families'],
        'program_maximum_schema_version': 26, 'legacy_wire_meaning_preserved': True,
        'execution8_record_schema_unchanged': True, 'p4_complete': False, 'p5_complete': False,
        'm2_original_constructs': 113, 'm2_original_fields': 196, 'm0_m2_complete': False,
        'full_regression_on_this_source': False, 'source_runtime_verified': False,
        'transformation_authorized': False, 'new_backend': False, 'new_lewm_speedup': False,
        'tests_started_by_archive_check': 0,
        'files': {str(path.relative_to(ROOT)): sha(path) for path in sorted(paths)}}
    if writing:
        MANIFEST.write_text(json.dumps(record, indent=2) + '\n')
    else:
        assert read(MANIFEST) == record
    print(json.dumps({key: record[key] for key in (
        'status', 'source_sha256', 'source_files', 'focused_cases',
        'previous_focused_obligations_retained', 'previous_exact_identities_retained',
        'explicit_identity_migrations', 'new_cases', 'newly_closed_obligation_groups',
        'm0_m2_complete', 'tests_started_by_archive_check')}, indent=2))


if __name__ == '__main__':
    main()
