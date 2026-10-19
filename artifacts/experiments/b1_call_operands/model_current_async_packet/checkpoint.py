"""Check source-bound progress and retained scope; never execute tests."""
import hashlib
import json
from pathlib import Path
import subprocess
import sys
import xml.etree.ElementTree as ET

from scripts.run_gate import fingerprint

ROOT = Path.cwd()
HERE = Path(__file__).resolve().parent
PRIOR = HERE.parent / 'model_direct_qualification_and_foreign_result'
BASE = '9293836d75e9c1d9a64849749d1b8b92529908b1'
MANIFEST = HERE / 'checkpoint.json'
NEW_TESTS = ('tests/unit/test_program_async_scheduler_packets.py',
             'tests/unit/test_program_async_completed_reuse.py')

def sha(path):
    return hashlib.sha256(path.read_bytes()).hexdigest()

def read(path):
    return json.loads(path.read_text())

def cases(path, *, green=False):
    rows = tuple(ET.parse(path).iter('testcase'))
    ids = {(row.get('classname'), row.get('name')) for row in rows}
    assert len(ids) == len(rows), path
    if green:
        assert rows and all(not any(row.find(tag) is not None for tag in
                                   ('failure', 'error', 'skipped')) for row in rows), path
    return ids, rows

def stable_attempt(folder):
    record = read(folder / 'result.json')
    before, after = read(folder / 'sources.before.json'), read(folder / 'sources.after.json')
    assert before == after and record['source_unchanged'], folder
    assert record['source_count'] == len(before), folder
    bound = hashlib.sha256(json.dumps(before, sort_keys=True).encode()).hexdigest()
    assert bound == record['source_sha256_before'] == record['source_sha256_after'], folder
    return record

def main():
    design, previous = read(HERE / 'design-baseline.json'), read(PRIOR / 'checkpoint.json')
    assert design['base_revision'] == BASE
    assert design['prior_checkpoint_sha256'] == sha(PRIOR / 'checkpoint.json')
    assert sha(ROOT / design['scope_plan']) == design['plan_sha256']
    for path, digest in previous['files'].items():
        assert sha(ROOT / path) == digest, path
    prior_sources = read(PRIOR / 'verified-final/sources.after.json')
    digest, sources = fingerprint()
    assert set(sources) - set(prior_sources) == set(NEW_TESTS)
    assert set(prior_sources) <= set(sources)
    for path, previous_digest in prior_sources.items():
        if path != 'scar/ir/program/protocol_async.py':
            assert sources[path] == previous_digest, path
    original_tests = {path: digest for path, digest in prior_sources.items()
                      if path.startswith('tests/')}
    for path, test_digest in original_tests.items():
        assert sha(ROOT / path) == test_digest, path
    # A source bridge needs no new canonical identity/codec records.
    for path in ('scar/ir/program/model.py', 'scar/ir/program/codec.py',
                 'scar/ir/program/protocol_connections.py', 'scar/ir/execution/model.py',
                 'scar/ir/execution/codec.py', 'scar/ir/execution/resumables.py'):
        assert sha(ROOT / path) == prior_sources[path], path
    for state in design['protected'].values():
        def git(*args):
            return subprocess.check_output(['git', *args], cwd=state['path'], text=True)
        assert git('rev-parse', 'HEAD').strip() == state['head']
        assert git('status', '--porcelain=v1') == state['status']
    result = stable_attempt(HERE / 'verified-final')
    assert result['returncode'] == 0 and digest == result['source_sha256_before']
    old_ids, _ = cases(PRIOR / 'verified-final/junit.xml', green=True)
    current, _ = cases(HERE / 'verified-final/junit.xml', green=True)
    assert len(old_ids) == 1854 and old_ids <= current, 'lost previous exact test identity'
    modules = {path.removesuffix('.py').replace('/', '.') for path in NEW_TESTS}
    assert current - old_ids and all(item[0] in modules for item in current - old_ids)
    assert all(any(item[0] == module for item in current) for module in modules)
    assert len(current - old_ids) == 11
    selection, old_selection = read(HERE / 'focused-selection.json'), read(PRIOR / 'focused-selection-f12.json')
    assert selection['selectors'] == old_selection['selectors'] + list(NEW_TESTS)
    original, family = read(HERE / 'original-obligations.json'), read(HERE / 'family-obligations.json')
    assert original == read(PRIOR / 'original-obligations.json')
    assert family == read(PRIOR / 'family-obligations.json')
    assert len(design['obligation_groups']) == 16 and len(family['remaining_other_families']) == 10
    assert set(family['closed']) == {'F12', 'F13', 'F15', 'F17', 'F21', 'F23'}
    # Every retained acceptance selector must also execute on this final source.
    for row in (*original['rows'], *family['reviewed']):
        for selector in row['existing_selectors']:
            path, name = selector.split('::')
            classname = path.removesuffix('.py').replace('/', '.')
            assert any(item[0] == classname and (item[1] == name or item[1].startswith(name + '['))
                       for item in current), selector
    attempts = {}
    for path in sorted(HERE.glob('*/result.json')):
        attempt = stable_attempt(path.parent)
        ids, rows = cases(path.parent / 'junit.xml')
        assert ids <= current, path
        attempts[path.parent.name] = {**attempt, 'cases': len(rows),
            'failures': sum(row.find('failure') is not None for row in rows),
            'errors': sum(row.find('error') is not None for row in rows),
            'skips': sum(row.find('skipped') is not None for row in rows)}
    snapshots = read(HERE / 'source-snapshots.json')
    assert snapshots['tests_started'] == 0 and set(snapshots['attempts']) == set(attempts)
    for attempt, archived in snapshots['attempts'].items():
        source_map = read(HERE / attempt / 'sources.before.json')
        assert set(source_map) == set(sources)
        for path, expected in source_map.items():
            saved = archived['overrides'].get(path)
            actual = ROOT / (path if saved is None else saved['path'])
            assert sha(actual) == expected, (attempt, path)
            if saved is not None:
                assert saved['sha256'] == expected
    reviews = read(HERE / 'independent-review.json')
    assert not reviews['full_family_closed'] and not reviews['transformation_authorized']
    for role in ('scheduler', 'completed_reuse'):
        review = reviews[role]
        assert sha(ROOT / review['test']) == review['test_sha256']
        if 'product' in review:
            assert sha(ROOT / review['product']) == review['product_sha256']
    documents = [ROOT / name for name in (
        design['scope_plan'], 'docs/M1_CURRENT_ASYNC_PACKET_PROGRESS.md',
        'docs/M1_COROUTINE_PHASE_NEXT_GATE.md')]
    paths = [path for path in HERE.rglob('*') if path.is_file() and path != MANIFEST
             and '__pycache__' not in path.parts] + documents
    record = {'status': 'PROGRESS_CURRENT_REQUEST_PACKET_AND_REUSE', 'base_revision': BASE,
        'source_sha256': digest, 'source_files': len(sources), 'focused_cases': len(current),
        'previous_focused_obligations_retained': len(old_ids), 'new_cases': len(current - old_ids),
        'original_tests_unchanged': original_tests, 'test_input_migrations': [],
        'attempts': attempts, 'closed_original_A_H_structural_obligations': original['closed'],
        'completed_obligation_groups': family['closed'],
        'remaining_other_families': family['remaining_other_families'],
        'obligation_groups': design['obligation_groups'], 'protected': design['protected'],
        'program_maximum_schema_version': 23, 'execution8_record_schema_unchanged': True,
        'program23_codec_unchanged': True, 'p4_complete': False, 'p5_complete': False,
        'm2_original_constructs': 113, 'm2_original_fields': 196, 'm0_m2_complete': False,
        'full_regression_on_this_source': False, 'source_runtime_verified': False,
        'transformation_authorized': False, 'new_backend': False, 'new_lewm_speedup': False,
        'tests_started_by_archive_check': 0,
        'files': {str(path.relative_to(ROOT)): sha(path) for path in sorted(paths)}}
    if sys.argv[1:] == ['--write']:
        assert not MANIFEST.exists()
        MANIFEST.write_text(json.dumps(record, indent=2) + '\n')
    else:
        assert sys.argv[1:] == ['--check']
        assert read(MANIFEST) == record
    print(json.dumps({key: record[key] for key in (
        'status', 'source_sha256', 'source_files', 'focused_cases',
        'previous_focused_obligations_retained', 'new_cases', 'completed_obligation_groups',
        'm0_m2_complete', 'tests_started_by_archive_check')}, indent=2))

if __name__ == '__main__':
    main()
