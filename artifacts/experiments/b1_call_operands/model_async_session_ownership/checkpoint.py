"""Check original obligations, exact migrations and source-bound evidence; no tests."""
import hashlib
import json
from pathlib import Path
import subprocess
import sys
import xml.etree.ElementTree as ET

from scripts.run_gate import fingerprint


ROOT = Path.cwd()
HERE = Path(__file__).resolve().parent
PRIOR = HERE.parent / 'model_native_coroutine_connections'
BASE = 'f22d64196d2f706c66e99f7acb4bcffa8373a98c'
MANIFEST = HERE / 'checkpoint.json'
ACCEPTANCE = HERE / 'original-acceptance.json'
OLD_PRODUCTS = tuple('scar/ir/' + name for name in (
    'execution/query.py', 'execution/request_state_history.py', 'program/admission.py',
    'program/codec.py', 'program/protocol_async.py', 'program/protocol_connection_validation.py',
    'program/protocol_connections.py', 'program/protocol_query.py', 'program/protocol_rules.py',
    'program/protocol_validation.py', 'program/protocols.py'))
NEW_PRODUCTS = ('scar/ir/program/session_occupancy.py',
                'scar/ir/execution/session_occupancy_history.py')
NEW_FIXTURES = ('tests/fixtures/program_async_competition_graphs.py',
                'tests/fixtures/execution_async_competition_graphs.py')
NEW_TESTS = tuple('tests/unit/' + name + '.py' for name in (
    'test_program_session_occupancy', 'test_program_session_occupancy_codec',
    'test_execution_async_competition', 'test_execution_session_occupancy'))


def sha(path):
    return hashlib.sha256(path.read_bytes()).hexdigest()


def read(path):
    return json.loads(path.read_text())


def digest(sources):
    return hashlib.sha256(json.dumps(sources, sort_keys=True).encode()).hexdigest()


def cases(path, *, green=False):
    rows = tuple(ET.parse(path).iter('testcase'))
    identities = {(row.get('classname'), row.get('name')) for row in rows}
    assert len(identities) == len(rows), path
    if green:
        assert rows and all(not any(row.find(tag) is not None for tag in
                                   ('failure', 'error', 'skipped')) for row in rows), path
    return identities, rows


def matches(selector, identities):
    path, name = selector.split('::')
    classname = path.removesuffix('.py').replace('/', '.')
    selected = sorted(identity for identity in identities if identity[0] == classname
                      and (identity[1] == name or identity[1].startswith(name + '[')))
    assert selected, selector
    return selected


def migrations(prior_sources):
    """Replay only the frozen exact literals, never exempt entire old tests."""
    declaration = read(HERE / 'test-input-migrations.json')
    assert sha(ROOT / declaration['amendment']) == declaration['amendment_sha256']
    maximum = declaration['reader_maximum']
    replacements = {}
    for path in maximum['codec_prefix_files']:
        replacements.setdefault(path, []).append((maximum['codec_prefix_before'], maximum['codec_prefix_after']))
    replacements.setdefault(maximum['compound_file'], []).append((maximum['compound_before'], maximum['compound_after']))
    for path in maximum['bare_files']:
        replacements.setdefault(path, []).append((maximum['bare_before'], maximum['bare_after']))
    identities = {}
    for row in declaration['future_version']:
        replacements.setdefault(row['file'], []).append((row['before'], row['after']))
        module = row['file'].removesuffix('.py').replace('/', '.')
        identities[(module, row['old_case'])] = (module, row['new_case'])
    assert len(replacements) == 15
    assert sum(map(len, replacements.values())) == declaration['expected_literal_replacements'] == 18
    assert len(identities) == declaration['expected_explicit_identity_migrations'] == 4
    for path, changes in replacements.items():
        old = subprocess.check_output(['git', 'show', f'{BASE}:{path}'], cwd=ROOT)
        assert hashlib.sha256(old).hexdigest() == prior_sources[path], path
        expected = old.decode()
        for before, after in changes:
            assert expected.count(before) == 1, (path, before)
            expected = expected.replace(before, after, 1)
        assert (ROOT / path).read_bytes() == expected.encode(), path
    return declaration, replacements, identities


def stable_attempt(folder, prior_sources):
    result = read(folder / 'result.json')
    before, after = read(folder / 'sources.before.json'), read(folder / 'sources.after.json')
    assert before == after and result['source_unchanged'], folder
    assert digest(before) == result['source_sha256_before'] == result['source_sha256_after']
    assert result['source_count'] == len(before) == 878
    command = read(folder / 'command.json')
    assert command['base_revision'] == BASE and command['cwd'] == str(ROOT)
    assert command['runner_sha256'] == sha(HERE / 'run_focused.py')
    assert command['environment'] == {'PYTHONPATH': '.', 'PYTHONDONTWRITEBYTECODE': '1'}
    snapshots = read(folder / 'source-bytes.json')
    assert set(snapshots) == {name for name, value in before.items() if prior_sources.get(name) != value}
    for name, expected in before.items():
        if name in snapshots:
            saved = snapshots[name]
            assert saved['sha256'] == expected
            assert sha(HERE / saved['path']) == expected, (folder, name)
        else:
            assert prior_sources[name] == expected, (folder, name)
    return result, before


def main():
    writing = sys.argv[1:] == ['--write']
    assert writing or sys.argv[1:] == ['--check']
    design = read(HERE / 'design-baseline.json')
    previous = read(PRIOR / 'checkpoint.json')
    assert design['base_revision'] == BASE
    assert design['prior_checkpoint_sha256'] == sha(PRIOR / 'checkpoint.json')
    for field in ('scope_plan', 'view_contract', 'query_contract'):
        hash_field = {'scope_plan': 'plan_sha256', 'view_contract': 'view_contract_sha256',
                      'query_contract': 'query_contract_sha256'}[field]
        assert sha(ROOT / design[field]) == design[hash_field]
    for path, previous_digest in previous['files'].items():
        assert sha(ROOT / path) == previous_digest, path
    prior_sources = read(PRIOR / 'verified-final/sources.after.json')
    source_digest, sources = fingerprint()
    assert len(prior_sources) == 870 and len(sources) == 878
    assert design['previous_source_sha256'] == digest(prior_sources)
    assert set(sources) - set(prior_sources) == set((*NEW_PRODUCTS, *NEW_FIXTURES, *NEW_TESTS))
    assert set(prior_sources) <= set(sources)
    migration, old_test_changes, moved = migrations(prior_sources)
    changed_old = {path for path, value in prior_sources.items() if sources[path] != value}
    assert changed_old == set(OLD_PRODUCTS) | set(old_test_changes)
    for state in design['protected'].values():
        def git(*args):
            return subprocess.check_output(['git', *args], cwd=state['path'], text=True)
        assert git('rev-parse', 'HEAD').strip() == state['head']
        assert git('status', '--porcelain=v1') == state['status']
    result, final_sources = stable_attempt(HERE / 'verified-final', prior_sources)
    assert result['returncode'] == 0 and source_digest == result['source_sha256_before']
    assert final_sources == sources
    old_ids, _ = cases(PRIOR / 'verified-final/junit.xml', green=True)
    current, _ = cases(HERE / 'verified-final/junit.xml', green=True)
    assert len(old_ids) == 1907
    assert set(moved) <= old_ids and not set(moved) & current
    assert set(moved.values()) <= current and not set(moved.values()) & old_ids
    unchanged = old_ids - set(moved)
    retained = unchanged | set(moved.values())
    assert len(unchanged) == 1903 and len(retained) == 1907 and retained <= current
    added = current - retained
    assert len(added) == 49 and len(current) == 1956
    modules = {path.removesuffix('.py').replace('/', '.') for path in NEW_TESTS}
    assert all(identity[0] in modules for identity in added)
    assert {module: sum(identity[0] == module for identity in added) for module in modules} == {
        'tests.unit.test_program_session_occupancy': 6,
        'tests.unit.test_program_session_occupancy_codec': 27,
        'tests.unit.test_execution_async_competition': 7,
        'tests.unit.test_execution_session_occupancy': 9}
    selection, old_selection = read(HERE / 'focused-selection.json'), read(PRIOR / 'focused-selection.json')
    assert selection['selectors'] == old_selection['selectors'] + list(NEW_TESTS)
    command = read(HERE / 'verified-final/command.json')['command']
    assert command[1:4] == ['-m', 'pytest', '-q']
    assert command[4:-1] == selection['selectors']
    original, family = read(HERE / 'original-obligations.json'), read(HERE / 'family-obligations.json')
    prior_family = read(PRIOR / 'family-obligations.json')
    assert original == read(PRIOR / 'original-obligations.json')
    for key in ('reviewed', 'closed', 'previous_closed', 'previous_remaining_descriptions',
                'F14_review', 'remaining_other_families'):
        assert family[key] == prior_family[key], key
    assert family['newly_closed'] == []
    assert len(design['obligation_groups']) == 16 and len(family['remaining_other_families']) == 9
    assert family['F16_current_scope_review']['historical_remaining_text_retained']
    assert not family['F16_current_scope_review']['family_closed']
    matched = {}
    for row in (*original['rows'], *family['reviewed'], family['F14_review']):
        for selector in row['existing_selectors']:
            matched[selector] = matches(selector, current)
    for selector in family['F16_current_scope_review']['already_covered_selectors']:
        matched[selector] = matches(selector, current)
    new_clauses = {
        'request_body_read_branch_tuple': NEW_TESTS[0] + '::test_occupancy_uses_this_requests_association_body_without_authorizing_a_gate',
        'two_requests_complete_reject_continue': NEW_TESTS[2] + '::test_two_requests_reject_only_r2_then_resume_the_original_body_and_r1',
        'conditional_provenance_not_preservation': NEW_TESTS[3] + '::test_current_occupancy_keeps_provenance_separate_from_whole_call_preservation',
        'local_exact_interval': NEW_TESTS[3] + '::test_local_hold_to_actual_occupancy_read_has_a_complete_current_interval',
        'own_slot_shared_budget': NEW_TESTS[3] + '::test_own_normal_result_slots_cannot_be_scanned_after_shared_budget_is_exhausted'}
    clauses = {key: matches(value, current) for key, value in new_clauses.items()}
    attempts = {}
    for path in sorted(HERE.glob('*/result.json')):
        attempt, attempt_sources = stable_attempt(path.parent, prior_sources)
        identities, rows = cases(path.parent / 'junit.xml')
        assert {moved.get(identity, identity) for identity in identities} <= current, path
        assert set(attempt_sources) == set(sources), path
        attempts[path.parent.name] = {**attempt, 'cases': len(rows),
            'failures': sum(row.find('failure') is not None for row in rows),
            'errors': sum(row.find('error') is not None for row in rows),
            'skips': sum(row.find('skipped') is not None for row in rows)}
    for name, count, failures in (('first-authored', 48, 41), ('corrected-native-getter', 48, 4),
                                  ('slot-budget-counterexample', 1, 1),
                                  ('corrected-branch-and-r2-post', 49, 0)):
        assert (attempts[name]['cases'], attempts[name]['failures']) == (count, failures)
        assert attempts[name]['errors'] == attempts[name]['skips'] == 0
    native = read(HERE / 'native-probe.json')
    assert native['sources'] == prior_sources
    assert native['source_sha256_before'] == native['source_sha256_after'] == digest(prior_sources)
    assert native['script_sha256'] == sha(HERE / 'native_probe.py')
    assert len(native['observations']) == 12 and native['distinct_live_requests_observed']
    assert native['tests_started'] == 0 and not native['automatic_source_recovery']
    first = read(HERE / 'native-first-failure.json')
    assert first['exit_code'] == 1 and first['script_sha256'] == sha(HERE / 'native_probe_first_attempt.py')
    assert not first['after_fingerprint_recorded'] and not first['full_native_snapshot_recorded']
    probe = read(HERE / 'static-tuple-probe.json')
    assert probe['tests_started'] == 0 and probe['script_sha256'] == sha(HERE / 'probe_static_tuple.py')
    assert probe['source_sha256_before'] == probe['source_sha256_after']
    assert probe['source_sha256_before'] == attempts['slot-budget-counterexample']['source_sha256_before']
    reviews = read(HERE / 'independent-review.json')
    assert reviews['all_authors_frozen'] and reviews['interpreters_started_by_reviewers'] == 0
    assert not reviews['p4_complete'] and not reviews['transformation_authorized']
    assert set(reviews['reviewed_sources']) == set((*OLD_PRODUCTS, *NEW_PRODUCTS, *NEW_FIXTURES, *NEW_TESTS))
    for path, reviewed_digest in reviews['reviewed_sources'].items():
        assert sha(ROOT / path) == reviewed_digest, path
    next_review = reviews['next_contract_read_only_review']
    assert not next_review['new_authority'] and next_review['tests_started'] == 0
    for path, reviewed_digest in next_review['source_hashes'].items():
        assert sha(ROOT / path) == reviewed_digest, path
    acceptance = {'status': 'VERIFIED_PROGRESS_F16_OCCUPANCY_NOT_FAMILY_ACCEPTANCE',
        'source_sha256': source_digest, 'clauses': clauses, 'matched_selectors': matched,
        'new_cases': sorted(added), 'previous_exact_identities_retained': len(unchanged),
        'explicit_identity_migrations': [{'old': old, 'new': new} for old, new in sorted(moved.items())],
        'previous_focused_obligations_retained': len(retained),
        'scope': 'Conditional supplied-model connections and exact local interval; full cross-call preservation remains unknown.',
        'newly_closed_families': [], 'f16_complete': False, 'p4_complete': False,
        'm0_m2_complete': False, 'transformation_authorized': False, 'tests_started': 0}
    if writing:
        assert not MANIFEST.exists() and not ACCEPTANCE.exists()
        ACCEPTANCE.write_text(json.dumps(acceptance, indent=2) + '\n')
    else:
        assert read(ACCEPTANCE) == json.loads(json.dumps(acceptance))
    documents = [ROOT / name for name in (design['scope_plan'], migration['amendment'],
        'docs/M1_ASYNC_SESSION_OWNERSHIP_PROGRESS.md', 'docs/M1_ASYNC_SESSION_OWNERSHIP_NEXT_GATE.md')]
    paths = [path for path in HERE.rglob('*') if path.is_file() and path != MANIFEST
             and '__pycache__' not in path.parts] + documents
    record = {'status': acceptance['status'], 'base_revision': BASE,
        'source_sha256': source_digest, 'source_files': len(sources), 'focused_cases': len(current),
        'previous_focused_obligations_retained': len(retained),
        'previous_exact_identities_retained': len(unchanged), 'explicit_identity_migrations': 4,
        'new_cases': len(added), 'test_input_migrations': migration,
        'original_tests_unchanged_except_exact_migrations': {
            path: value for path, value in prior_sources.items()
            if path.startswith('tests/') and path not in old_test_changes},
        'attempts': attempts, 'native_observations': 12,
        'closed_original_A_H_structural_obligations': original['closed'],
        'completed_obligation_groups': family['closed'], 'newly_closed_obligation_groups': [],
        'remaining_other_families': family['remaining_other_families'],
        'obligation_groups': design['obligation_groups'], 'protected': design['protected'],
        'program_maximum_schema_version': 24, 'legacy_wire_meaning_preserved': True,
        'execution8_record_schema_unchanged': True, 'f16_complete': False,
        'p4_complete': False, 'p5_complete': False,
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
