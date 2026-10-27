"""Read-only P4 design/helper checkpoint check; starts no tests or workload."""
from collections import Counter
import hashlib
import json
from pathlib import Path
import runpy
import subprocess
import xml.etree.ElementTree as ET

HERE = Path(__file__).resolve().parent
ROOT = HERE.parents[3]


def read(path):
    return json.loads(path.read_text())


def digest(path):
    return hashlib.sha256(path.read_bytes()).hexdigest()


def main():
    checkpoint = read(HERE / 'intermediate-checkpoint.json')
    for path, sha in checkpoint['files'].items():
        assert digest(ROOT / path) == sha, path
    sha, files = runpy.run_path(str(ROOT / 'scripts/run_gate.py'))['fingerprint']()
    final = HERE / 'helper-inputs/final-focused001'
    receipt = read(final / 'result.json')
    assert receipt['returncode'] == 0 and receipt['source_unchanged']
    assert sha == receipt['source_sha256_before'] == receipt['source_sha256_after'] == checkpoint['source_sha256']
    assert files == read(final / 'sources.before.json') == read(final / 'sources.after.json')
    assert len(files) == checkpoint['source_files'] == 670
    cases = list(ET.parse(final / 'junit.xml').iter('testcase'))
    assert len(cases) == checkpoint['focused_cases'] == 112
    assert all(row.find(tag) is None for row in cases for tag in ('failure', 'error', 'skipped'))
    assert Counter(row.get('classname') for row in cases) == Counter(checkpoint['case_classes'])
    red = HERE / 'helper-inputs/red001'
    assert read(red / 'result.json')['returncode'] == 1
    red_cases = list(ET.parse(red / 'junit.xml').iter('testcase'))
    assert len(red_cases) == 1 and red_cases[0].find('failure') is not None
    green = HERE / 'helper-inputs/green001'
    assert read(green / 'result.json')['returncode'] == 0
    assert len(list(ET.parse(green / 'junit.xml').iter('testcase'))) == 22
    baseline = read(ROOT / 'artifacts/experiments/b1_call_operands/model_body_occurrence/repair/full/source.before.json')
    assert len(baseline['files']) == 668 and baseline['files'].keys() <= files.keys()
    changed = sorted(path for path in baseline['files'] if baseline['files'][path] != files[path])
    added = sorted(files.keys() - baseline['files'].keys())
    assert changed == ['scar/ir/program/request_inputs.py']
    assert added == ['tests/fixtures/program_request_helper_graphs.py',
                     'tests/unit/test_program_request_helper_inputs.py']
    fixtures = {str(path.relative_to(ROOT)): digest(path) for path in sorted((ROOT / 'tests/fixtures').rglob('*'))
                if path.is_file() and '__pycache__' not in path.parts}
    assert len(fixtures) == 100 and len(baseline['fixture_sha256']) == 99
    assert all(fixtures.get(path) == old for path, old in baseline['fixture_sha256'].items())
    protected = read(HERE / 'protected.before.json')
    for row in protected.values():
        assert subprocess.check_output(['git', 'rev-parse', 'HEAD'], cwd=row['path'], text=True).strip() == row['head']
        assert subprocess.check_output(['git', 'status', '--porcelain=v1'], cwd=row['path'], text=True).strip() == row['status'] == ''
    assert checkpoint['status'] == 'PASS_WITH_SCOPE_DESIGN_AND_HELPER_QUERY'
    assert not any(checkpoint[key] for key in ('p4_complete', 'full_regression_on_current_source',
        'm0_m2_complete', 'source_runtime_verified', 'transformation_authorized', 'new_lewm_speedup'))
    assert digest(HERE / 'design/reviewed-contract-v1.md') == '5dd62427c6b702f8a25e54816a68b9780b37cfdfc409b007782c273bc25fa557'
    print(json.dumps({'status': 'PASS', 'scope': checkpoint['status'], 'source_files': len(files),
        'focused_cases': len(cases), 'old_fixtures_preserved': 99, 'current_fixtures': len(fixtures),
        'tests_started_by_checker': 0, 'p4_complete': False}))


if __name__ == '__main__':
    main()
