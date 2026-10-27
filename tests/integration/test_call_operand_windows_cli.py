"""Public automatic construction survives a large unrelated Python loop."""
import gzip
import json
import os
from pathlib import Path
import subprocess
import sys

import pytest


ROOT = Path(__file__).resolve().parents[2]


def cli(*arguments, cwd=None, environment=None):
    env = dict(os.environ, PYTHONPATH=str(ROOT), PYTHONDONTWRITEBYTECODE='1')
    for name in list(env):
        if name.startswith('SCAR_'):
            env.pop(name)
    if environment:
        env.update(environment)
    result = subprocess.run([sys.executable, '-m', 'scar.cli', *map(str, arguments)],
        cwd=cwd or ROOT, env=env, capture_output=True, text=True, timeout=120)
    assert result.returncode == 0, result.stdout + result.stderr
    return result


def read(path):
    with gzip.open(path, 'rt') if path.suffix == '.gz' else path.open() as stream:
        return json.load(stream)


@pytest.mark.parametrize('mode', ('windows', 'instructions'))
def test_original_program_automatic_query_with_explicit_capture_profile(tmp_path, mode):
    project = tmp_path / 'original'
    project.mkdir()
    (project / 'helper.py').write_text(
        'def choose(left, right):\n    return left\n'
        'def relay(a, b):\n    selected = choose(a, b)\n    return selected\n')
    iterations = 100_000 if mode == 'windows' else 3
    entry = project / 'entry.py'
    entry.write_text(
        'from helper import relay\n'
        'class Token: pass\n'
        'def preparation(n):\n'
        '    pairs = [(i, i + 1) for i in range(n)]\n'
        '    return len(pairs)\n'
        'def run(x, y):\n'
        '    first = relay(x, y)\n'
        '    second = relay(y, x)\n'
        '    return first\n'
        f'assert preparation({iterations}) == {iterations}\n'
        'left = Token()\nright = left\n'
        "assert run(left, right) is left\nprint('original completed')\n")
    trace = tmp_path / 'trace'
    captured = cli('trace', '--call-operands', '--operand-capture', mode,
        '--project-root', project, '--out', trace, '--', sys.executable, entry,
        cwd=project, environment={'SCAR_OPERAND_CAPTURE':'invalid-inherited-choice'})
    assert 'original completed' in captured.stdout
    meta_path, = trace.glob('call-operand-meta.*.json')
    meta = read(meta_path)
    assert meta['rule'] == {'windows':'CPYTHON_CALL_WINDOWS_V1',
                            'instructions':'CPYTHON_LOAD_OCCURRENCES_V1'}[mode]
    assert meta['dropped_events'] == 0 and meta['errors'] == [] and not meta['io_failed']
    if mode == 'windows':
        assert meta['events'] < 2_000
        assert meta['bytes'] < 1_000_000
    inventory = tmp_path / 'inventory.json.gz'
    cli('inventory-program', entry, '--project-root', project, '--calls', trace, '--out', inventory)
    report = tmp_path / 'operands.json.gz'
    cli('link-operands', trace, '--project-root', project, '--inventory', inventory, '--out', report)
    cli('check-operand-links', report)
    document = read(report)['analysis']
    names = {definition['id']['wire']:definition['qualname'] for file in read(inventory)['files']
             for definition in file['definitions']}
    returned, = [item for item in document['routing']['returns']
                 if names[item['definition']['wire']] == 'run']
    invocation = returned['invocation']
    queried = cli('query-operand-refs', report, '--process', invocation['process_id'],
        '--thread', invocation['thread_id'], '--invocation', invocation['invocation_id'])
    query = json.loads(queried.stdout)['query']
    assert {(item['invocation']['invocation_id'],names[item['definition']['wire']],item['formal_name'])
            for item in query['endpoints'] if item['kind'] == 'FORMAL'} == {
                (invocation['invocation_id'],'run','x')}
    assert len([step for step in query['routes'] if step['kind'] == 'COMPLETION']) == 2
    assert query['conditional_only'] and len(query['conditions']) == 8
    assert document['whole_program_complete'] is False
    assert document['transformation_authorized'] is False


def test_call_operands_default_selects_windows_without_inherited_mode(tmp_path):
    project = tmp_path / 'project'
    project.mkdir()
    entry = project / 'entry.py'
    entry.write_text('def identity(x):\n    return x\nx = []\ny = identity(x)\n')
    trace = tmp_path / 'trace'
    cli('trace', '--call-operands', '--project-root', project, '--out', trace,
        '--', sys.executable, entry, cwd=project,
        environment={'SCAR_OPERAND_CAPTURE':'instructions'})
    meta_path, = trace.glob('call-operand-meta.*.json')
    assert read(meta_path)['rule'] == 'CPYTHON_CALL_WINDOWS_V1'
