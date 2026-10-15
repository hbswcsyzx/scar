"""Public raw Python capture to compact source seeds, without manual graphs."""
from copy import deepcopy
import gzip
import json
import os
from pathlib import Path
import subprocess
import sys

import pytest


REPOSITORY = Path(__file__).resolve().parents[2]


def cli(*arguments, cwd=None):
    env = dict(os.environ, PYTHONPATH=str(REPOSITORY), PYTHONDONTWRITEBYTECODE='1')
    for name in ('SCAR_TRACE_DIR', 'SCAR_TRACE_CALL_EDGES', 'SCAR_CALL_TRACE_OWNER_PID'):
        env.pop(name, None)
    return subprocess.run([sys.executable, '-m', 'scar.cli', *map(str, arguments)],
                          cwd=cwd or REPOSITORY, env=env, capture_output=True,
                          text=True, timeout=60)


def read(path):
    with gzip.open(path, 'rt') if path.suffix == '.gz' else path.open() as stream:
        return json.load(stream)


@pytest.fixture
def captured(tmp_path):
    project = tmp_path / 'project'
    project.mkdir()
    (project / 'helper.py').write_text('def identity(value):\n    return value\n')
    marker = project / 'executed'
    entry = project / 'entry.py'
    entry.write_text('from helper import identity\n'
                     'class Token: pass\n'
                     'def run(value):\n'
                     '    for _ in range(5):\n'
                     '        result = identity(value)\n'
                     '    return result\n'
                     'value = Token()\n'
                     'assert run(value) is value\n'
                     f'open({str(marker)!r}, "w").write("ran")\n')
    trace = tmp_path / 'trace'
    process = cli('trace', '--calls-only', '--project-root', project,
                  '--out', trace, '--', sys.executable, entry, cwd=project)
    assert process.returncode == 0, process.stdout + process.stderr
    assert marker.read_text() == 'ran'
    marker.unlink()
    return project, entry, trace, marker


@pytest.mark.parametrize('suffix', ['.json', '.json.gz'])
@pytest.mark.parametrize('archive_trace', [False, True])
def test_public_seed_build_and_independent_replay(captured, tmp_path, suffix, archive_trace):
    project, entry, trace, marker = captured
    source = entry.read_bytes()
    if archive_trace:
        for path in list(trace.glob('call-*')):
            path.with_name(path.name + '.gz').write_bytes(gzip.compress(path.read_bytes()))
            path.unlink()
    output = tmp_path / ('seeds' + suffix)
    generated = cli('seed-calls', trace, '--project-root', project, '--out', output)
    assert generated.returncode == 0, generated.stdout + generated.stderr
    assert json.loads(generated.stdout)['status'] == 'SOURCE_SEEDS'
    report = read(output)
    assert report['schema'] == 'scar.call-source-seeds'
    assert report['target_executed_by_resolver'] is False
    for flag in ('caller_connections_established', 'data_connections_established',
                 'effects_established', 'function_environment_established',
                 'transformation_authorized'):
        assert report[flag] is False
    codes = {capture['code']['key']: capture['code']['qualname']
             for capture in report['model']['codes']}
    identity, = [group for group in report['model']['groups'] if codes[group['code']] == 'identity']
    assert identity['count'] == 5
    assert 'references' not in report['model'] and 'edges' not in report['model']
    replay = cli('check-call-seeds', output)
    assert replay.returncode == 0, replay.stdout + replay.stderr
    assert json.loads(replay.stdout)['status'] == 'REPLAYED'
    assert not marker.exists() and entry.read_bytes() == source


@pytest.mark.parametrize('change', ['count', 'authority', 'summary'])
def test_seed_replay_rejects_changed_claims(captured, tmp_path, change):
    project, _, trace, _ = captured
    output = tmp_path / 'seeds.json'
    assert cli('seed-calls', trace, '--project-root', project, '--out', output).returncode == 0
    report = deepcopy(read(output))
    if change == 'count':
        report['model']['groups'][0]['count'] += 1
    elif change == 'authority':
        report['data_connections_established'] = True
    else:
        report['summary']['invented_claim'] = True
    output.write_text(json.dumps(report))
    replay = cli('check-call-seeds', output)
    assert replay.returncode == 2 and json.loads(replay.stdout)['status'] == 'INVALID'


def test_seed_replay_rejects_source_drift(captured, tmp_path):
    project, entry, trace, _ = captured
    output = tmp_path / 'seeds.json'
    assert cli('seed-calls', trace, '--project-root', project, '--out', output).returncode == 0
    entry.write_text(entry.read_text() + '\n# source changed without changing the function bytecode\n')
    replay = cli('check-call-seeds', output)
    assert replay.returncode == 2 and 'replay' in replay.stdout


@pytest.mark.parametrize('argument', ['--max-call-report-bytes', '--max-call-references', '--max-call-trace-bytes'])
def test_seed_replay_has_independent_input_and_raw_ceilings(captured, tmp_path, argument):
    project, _, trace, _ = captured
    output = tmp_path / 'seeds.json.gz'
    assert cli('seed-calls', trace, '--project-root', project, '--out', output).returncode == 0
    replay = cli('check-call-seeds', output, argument, 1)
    assert replay.returncode == 2 and json.loads(replay.stdout)['status'] == 'INVALID'


def test_seed_outputs_preserve_trace_hardlinks_and_unrelated_files(captured, tmp_path):
    project, _, trace, _ = captured
    metadata, = trace.glob('call-meta.*.json')
    alias = tmp_path / 'metadata-alias.json'
    os.link(metadata, alias)
    before = metadata.read_bytes()
    rejected = cli('seed-calls', trace, '--project-root', project, '--out', alias)
    assert rejected.returncode == 2 and 'differ from' in rejected.stdout
    assert metadata.read_bytes() == before and alias.read_bytes() == before
    unrelated = tmp_path / 'important.json'
    unrelated.write_text('{"keep": true}')
    rejected = cli('seed-calls', trace, '--project-root', project, '--out', unrelated)
    assert rejected.returncode == 2 and unrelated.read_text() == '{"keep": true}'


@pytest.mark.parametrize('existing', [False, True])
def test_seed_report_write_ceiling_leaves_no_partial_replacement(captured, tmp_path, existing):
    project, _, trace, _ = captured
    output = tmp_path / 'seeds.json.gz'
    before = gzip.compress(b'{"schema":"scar.call-source-seeds"}')
    if existing:
        output.write_bytes(before)
    rejected = cli('seed-calls', trace, '--project-root', project, '--out', output,
                   '--max-call-report-bytes', 100)
    assert rejected.returncode == 2 and 'write byte ceiling' in rejected.stdout
    assert output.read_bytes() == before if existing else not output.exists()
    assert not list(tmp_path.glob('.scar-call-*'))
