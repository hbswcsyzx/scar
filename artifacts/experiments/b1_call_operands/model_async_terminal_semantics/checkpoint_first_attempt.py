"""Audit the original F18 unit and immutable actual attempts; execute no tests."""
import hashlib
import json
from pathlib import Path
import subprocess
import sys
import xml.etree.ElementTree as ET

from scripts.run_gate import fingerprint

ROOT = Path.cwd()
HERE = Path(__file__).resolve().parent
PRIOR = HERE.parent / 'model_async_initial_control'
BASE = '54118247d4ff4c764dbe6f66493bc8609041f24b'
FINAL = 'verified-current'
PRODUCTS = ('scar/ir/program/protocol_async.py', 'scar/ir/execution/resumable_sessions.py',
            'scar/ir/program/protocol_validation.py', 'scar/ir/program/admission.py')
ADDED = ('scar/analysis/source_compilation.py',
    'tests/fixtures/program_async_terminal_graphs.py',
    'tests/fixtures/execution_async_terminal_graphs.py',
    'tests/unit/test_program_async_terminal_inventory.py',
    'tests/unit/test_program_async_terminal.py',
    'tests/unit/test_source_compilation.py',
    'tests/unit/test_execution_async_terminal.py')
NEW_TESTS = ADDED[3:]
DOCS = tuple('docs/M1_ASYNC_TERMINAL_' + name + '.md' for name in (
    'PLAN', 'RESIDUAL_AMENDMENT', 'ORDERING_SUPPLEMENT', 'STATIC_DYNAMIC_SUPPLEMENT',
    'PROGRESS', 'ACCEPTANCE', 'NEXT_GATE'))


def read(path):
    return json.loads(path.read_text())


def sha(path):
    return hashlib.sha256(path.read_bytes()).hexdigest()


def digest(sources):
    return hashlib.sha256(json.dumps(sources, sort_keys=True).encode()).hexdigest()


def cases(path, green=False):
    rows = tuple(ET.parse(path).iter('testcase'))
    identities = {(row.get('classname'), row.get('name')) for row in rows}
    assert len(identities) == len(rows), path
    if green:
        assert rows and not any(row.find(tag) is not None for row in rows
                               for tag in ('failure', 'error', 'skipped')), path
    return identities, rows


def match(selector, identities):
    module, name = selector.split('::')
    module = module.removesuffix('.py').replace('/', '.')
    found = sorted(row for row in identities if row[0] == module and (
        row[1] == name or row[1].startswith(name + '[')))
    assert found, selector
    return found


def attempt(folder, prior_sources):
    result, command = read(folder / 'result.json'), read(folder / 'command.json')
    before, after = read(folder / 'sources.before.json'), read(folder / 'sources.after.json')
    assert before == after and result['source_unchanged'], folder
    assert digest(before) == result['source_sha256_before'] == result['source_sha256_after']
    assert result['source_count'] == len(before)
    assert command['base_revision'] == BASE and command['cwd'] == str(ROOT)
    assert command['runner_sha256'] == sha(HERE / 'run_focused.py')
    assert command['environment'] == {'PYTHONPATH': '.', 'PYTHONDONTWRITEBYTECODE': '1'}
    saved = read(folder / 'source-bytes.json')
    assert set(saved) == {path for path, value in before.items() if prior_sources.get(path) != value}
    for path, entry in saved.items():
        assert entry['sha256'] == before[path] == sha(HERE / entry['path'])
    identities, rows = cases(folder / 'junit.xml')
    stats = {**result, 'cases': len(rows),
        'failures': sum(row.find('failure') is not None for row in rows),
        'errors': sum(row.find('error') is not None for row in rows),
        'skips': sum(row.find('skipped') is not None for row in rows)}
    return stats, before, identities


def main():
    writing = sys.argv[1:] == ['--write']
    assert writing or sys.argv[1:] == ['--check']
    design, prior = read(HERE / 'design-baseline.json'), read(PRIOR / 'checkpoint.json')
    assert design['base_revision'] == BASE
    assert design['prior_checkpoint_sha256'] == sha(PRIOR / 'checkpoint.json')
    for path, expected in prior['files'].items():
        assert sha(ROOT / path) == expected, path
    assert sha(ROOT / design['scope_plan']) == design['plan_sha256']
    assert sha(ROOT / design['residual_amendment']) == design['residual_amendment_sha256']
    assert sha(ROOT / design['ordering_supplement']) == design['ordering_supplement_sha256']
    assert sha(ROOT / design['static_dynamic_supplement']) == design['static_dynamic_supplement_sha256']
    previous = read(PRIOR / 'verified-final/sources.after.json')
    source_digest, sources = fingerprint()
    assert len(previous) == 892 and len(sources) == 899
    assert design['previous_source_sha256'] == digest(previous)
    assert set(previous) <= set(sources) and set(sources) - set(previous) == set(ADDED)
    assert {path for path in previous if sources[path] != previous[path]} == set(PRODUCTS)
    for state in design['protected'].values():
        assert subprocess.check_output(['git', 'rev-parse', 'HEAD'], cwd=state['path'], text=True).strip() == state['head']
        assert subprocess.check_output(['git', 'status', '--porcelain=v1'], cwd=state['path'], text=True) == state['status']
    final, final_sources, current = attempt(HERE / FINAL, previous)
    assert final['returncode'] == 0 and final_sources == sources
    cases(HERE / FINAL / 'junit.xml', green=True)
    old, _ = cases(PRIOR / 'verified-final/junit.xml', green=True)
    assert len(old) == 2058 and old <= current
    new = current - old
    selection = read(HERE / 'focused-selection.json')
    assert selection['selectors'] == read(PRIOR / 'focused-selection.json')['selectors'] + list(NEW_TESTS)
    assert read(HERE / FINAL / 'command.json')['command'][4:-1] == selection['selectors']
    expected = read(HERE / 'gate-expectations.json')
    assert len(new) == sum(expected['new_cases_by_module'].values())
    assert {module: sum(row[0] == module for row in new)
            for module in expected['new_cases_by_module']} == expected['new_cases_by_module']
    attempts, snapshots = {}, {}
    for junit in sorted(HERE.glob('*/junit.xml')):
        stats, snapshot, identities = attempt(junit.parent, previous)
        assert identities <= current, junit
        attempts[junit.parent.name], snapshots[junit.parent.name] = stats, snapshot
    assert set(attempts) == set(expected['attempts'])
    for name, numbers in expected['attempts'].items():
        assert [attempts[name][key] for key in ('cases', 'failures', 'errors', 'skips', 'source_count')] == numbers, name
        if name == 'verified-final':
            assert attempts[name]['returncode'] == 2 and attempts[name]['cases'] == 379
        else:
            assert (attempts[name]['returncode'] == 0) == (
                attempts[name]['failures'] == attempts[name]['errors'] == attempts[name]['skips'] == 0), name
    initial = snapshots['initial-source-denominator']
    assert len(initial) == 893 and all(initial[path] == value for path, value in previous.items())
    assert attempts['initial-source-denominator']['returncode'] != 0
    for filename, script, count in (('native-probe.json', 'native_probe.py', 22),
                                    ('return-source-probe.json', 'probe_return_sources.py', 5)):
        value = read(HERE / filename)
        assert value['script_sha256'] == sha(HERE / script)
        assert value['sources'] == previous
        assert value['source_sha256_before'] == value['source_sha256_after'] == digest(previous)
        assert value['tests_started'] == 0 and len(value['observations']) == count
    native = read(HERE / 'native-probe.json')
    assert native['base_revision'] == BASE and native['all_bodies_finished']
    assert len(native['compile_observations']) == 2
    assert not native['source_runtime_verified'] and not native['transformation_authorized']
    assert read(HERE / 'return-source-probe.json')['target_bodies_executed'] == 0
    offsets = read(HERE / 'syntax-offset-probe.json')
    assert offsets['script_sha256'] == sha(HERE / 'probe_syntax_offsets.py')
    assert offsets['sources'] == snapshots['first-joint-authored']
    assert offsets['source_sha256_before'] == offsets['source_sha256_after'] == digest(offsets['sources'])
    assert offsets['tests_started'] == offsets['target_bodies_executed'] == 0
    assert len(offsets['observations']) == 4
    for item in offsets['observations']:
        if item['phase'] == 'compile':
            original, = item['returns']
            assert item['offset'] - 1 == original['column_utf8_bytes']
            assert item['end_offset'] - 1 == original['end_column_utf8_bytes']
    assert not offsets['source_runtime_verified'] and not offsets['transformation_authorized']
    comments = read(HERE / 'type-comment-probe.json')
    assert comments['script_sha256'] == sha(HERE / 'probe_type_comments.py')
    assert comments['sources'] == snapshots['revised-joint-terminal']
    assert comments['source_sha256_before'] == comments['source_sha256_after'] == digest(comments['sources'])
    assert comments['tests_started'] == comments['target_bodies_executed'] == 0
    assert [(row['mode'], row['accepted']) for row in comments['observations']] == [
        ('ordinary_compile', True), ('ordinary_ast', True), ('type_comment_ast', False)]
    for filename in ('residual-probe.stderr.log', 'residual-probe.revised.stderr.log'):
        assert 'ValueError' in (HERE / filename).read_text()
    assert 'ValueError' in (HERE / 'return-source-probe.first-failure.stderr.log').read_text()
    assert sha(HERE / 'probe_return_sources_first_attempt.py') != sha(HERE / 'probe_return_sources.py')
    for filename in ('native-probe.stderr.log', 'return-source-probe.revised.stderr.log',
                     'syntax-offset-probe.stderr.log', 'type-comment-probe.stderr.log'):
        assert not (HERE / filename).read_bytes()
    references = {
        'reference-intrinsics.c.txt': '9c218e09ee44ef416440ee3e473d3f0686a1752ab68222d49ebcbce99bd1264f',
        'reference-genobject.c.txt': '9f130a9c1fac701a80116f142b5dc72b72f004401fe5053a6510e0c768024e0f',
        'reference-codegen.c.txt': '034c5f2c25c04814f6f48b0c61070f6ea7e7b2cb588bd45428bd9ad48b5ca8d3'}
    for path, expected_sha in references.items():
        assert sha(HERE / path) == expected_sha
    assert read(HERE / 'original-obligations.json') == read(PRIOR / 'original-obligations.json')
    assert read(HERE / 'historical-family-obligations.json') == read(PRIOR / 'family-obligations.json')
    family = read(HERE / 'family-baseline.json')
    assert family['closed'] == design['closed_before']
    assert set(family['remaining']) == set(design['remaining_before'])
    review = read(HERE / 'f18-review.json')
    assert review['status'] == 'CONDITIONAL_SUPPLIED_MODEL_ACCEPTANCE'
    assert review['source_sha256'] == source_digest
    assert review['closed_before'] == family['closed'] and review['newly_closed'] == ['F18']
    assert set(review['closed_after']) == set(family['closed']) | {'F18'}
    assert set(review['remaining_families']) == set(family['remaining']) - {'F18'}
    assert len(review['closed_after']) == 9 and len(review['remaining_families']) == 7
    assert not review['automatic_source_recovery'] and not review['transformation_authorized']
    assert not any(review[key] for key in ('source_runtime_verified', 'p4_complete', 'p5_complete', 'm0_m2_complete'))
    matched = {selector: match(selector, current) for row in review['clauses']
               for selector in row['existing_selectors']}
    reviewers = read(HERE / 'independent-review.json')
    assert reviewers['source_sha256'] == source_digest
    assert reviewers['all_authors_frozen'] and reviewers['interpreters_started_by_reviewers'] == 0
    assert set(reviewers['reviewed_sources']) == set((*PRODUCTS, *ADDED))
    assert all(sources[path] == value for path, value in reviewers['reviewed_sources'].items())
    assert len(design['obligation_groups']) == 16
    assert design['m2_original_constructs'] == 113 and design['m2_original_fields'] == 196
    acceptance = {'status': 'CONDITIONAL_SUPPLIED_MODEL_F18_ACCEPTANCE',
        'source_sha256': source_digest, 'previous_exact_identities_retained': len(old),
        'new_cases': sorted(new), 'matched_selectors': matched,
        'newly_closed_families': ['F18'], 'p4_complete': False, 'p5_complete': False,
        'm0_m2_complete': False, 'source_runtime_verified': False,
        'automatic_source_recovery': False, 'transformation_authorized': False, 'tests_started': 0}
    acceptance_path, manifest = HERE / 'original-acceptance.json', HERE / 'checkpoint.json'
    if writing:
        assert not manifest.exists() and not acceptance_path.exists()
        acceptance_path.write_text(json.dumps(acceptance, indent=2) + '\n')
    else:
        assert read(acceptance_path) == json.loads(json.dumps(acceptance))
    paths = [path for path in HERE.rglob('*') if path.is_file() and path != manifest
             and '__pycache__' not in path.parts] + [ROOT / path for path in DOCS]
    record = {'status': acceptance['status'], 'base_revision': BASE,
        'final_attempt': FINAL,
        'source_sha256': source_digest, 'source_files': len(sources), 'focused_cases': len(current),
        'previous_exact_identities_retained': len(old), 'new_cases': len(new),
        'attempts': attempts, 'protected': design['protected'],
        'obligation_groups': design['obligation_groups'],
        'closed_original_A_H_structural_obligations': family['original_A_H'],
        'completed_obligation_groups': review['closed_after'], 'newly_closed_obligation_groups': ['F18'],
        'remaining_other_families': review['remaining_families'],
        'program_maximum_schema_version': 26, 'legacy_wire_meaning_preserved': True,
        'execution8_record_schema_unchanged': True, 'old_tests_or_fixtures_changed': False,
        'p4_complete': False, 'p5_complete': False, 'm2_original_constructs': 113,
        'm2_original_fields': 196, 'm0_m2_complete': False, 'full_regression_on_this_source': False,
        'source_runtime_verified': False, 'automatic_source_recovery': False,
        'transformation_authorized': False, 'new_backend': False, 'new_lewm_speedup': False,
        'tests_started_by_archive_check': 0,
        'files': {str(path.relative_to(ROOT)): sha(path) for path in sorted(paths)}}
    if writing:
        manifest.write_text(json.dumps(record, indent=2) + '\n')
    else:
        assert read(manifest) == record
    print(json.dumps({key: record[key] for key in ('status', 'source_sha256', 'source_files',
        'focused_cases', 'previous_exact_identities_retained', 'new_cases',
        'newly_closed_obligation_groups', 'm0_m2_complete', 'tests_started_by_archive_check')}, indent=2))


if __name__ == '__main__':
    main()
