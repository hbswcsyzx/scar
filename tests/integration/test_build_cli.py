"""The one-command workflow retains bodies, cross-call contexts and gaps."""
import json
from pathlib import Path
import subprocess
import sys

import pytest

from scar.analysis.build import build, BuildSession, query_main
from scar.ir.program.dependencies import DependencyKind as K, DependencyPoint as P, GraphNamespace
from scar.ir.program.ids import OperationID


@pytest.fixture
def built(tmp_path):
    project = tmp_path / 'project'
    project.mkdir()
    entry = project / 'main.py'
    marker = tmp_path / 'not-executed'
    entry.write_text('def transform(x):\n    for i in range(2):\n        x = x + i\n    return x\n\n'
        'value = transform(3)\n' + f'open({str(marker)!r}, "w")\n')
    (project / 'config.yaml').write_text('model:\n  width: 128\npath: ${data.root}\n')
    out = tmp_path / 'built'
    report = build(entry, None, out, jobs=1)
    assert not marker.exists()
    return entry, out, report


def test_build_readback_queries_original_calls_loops_and_resources(built):
    entry, out, report = built
    assert report['workflow_complete'] and not report['first_stage_complete']
    assert report['original_body_bytes_copied'] == 0 and not report['loops_unrolled']
    with BuildSession(out) as session:
        children = session.view.expand(session.entry)
        assert children
        namespaces = session.select(entry='transform')
        assert len(namespaces) == 1
        loops = session.session.loop_views(GraphNamespace.from_source(namespaces[0]))
        assert loops
        # Stored relationships and scoped ports reference the original shared body.
        shards = tuple(session.session.relation_shards())
        calls = [call for shard, _ in shards for call in shard.calls]
        target_call = next(c for c in calls if any(t.body and t.arguments for t in c.targets))
        target = next(t for t in target_call.targets if t.body and t.arguments)
        point = P(GraphNamespace.from_source(target_call.caller), target.arguments[0].actual_use, ())
        edges = session.view.dependencies.outgoing(point, kinds=(K.ARGUMENT,)).edges
        assert any(e.target.node == target.arguments[0].formal_value for e in edges)
        assert any(e.target.context is not None for e in edges)
        operation = P(point.namespace, target_call.operation, ())
        resource_edges = session.view.dependencies.incoming(operation, kinds=(K.RESOURCE,)).edges
        assert resource_edges
        resource = next(e.source for e in resource_edges if hasattr(session.view.original(e.source), 'owner'))
        assert session.view.original(resource).owner == operation.node
        assert session.view.get(resource).point == resource
    gaps = json.loads((out / 'gaps.json').read_text())['gaps']
    assert any(g['kind'] == 'TRACE_NOT_SUPPLIED' for g in gaps)
    assert any(g['kind'] == 'INFERENCE_PATH_NOT_CERTIFIED' for g in gaps)
    configuration = json.loads((out / 'configuration.json').read_text())
    assert configuration['materials'][0]['nodes'] > 0
    assert not configuration['runtime_configuration_proven']


def test_build_cli_reuse_and_fragment_tampering_are_checked(built, tmp_path, capsys):
    entry, out, report = built
    assert query_main([str(out), '--action', 'expand']) == 0
    assert json.loads(capsys.readouterr().out)['children']
    # No replacement of an existing publication, even with a different entry.
    with pytest.raises(ValueError, match='fresh'):
        build(entry, None, out, jobs=1)
    model = Path(report['model']['path'])
    model.write_bytes(model.read_bytes() + b' ')
    with pytest.raises(ValueError, match='receipt changed'):
        BuildSession(out)


@pytest.mark.skipif(sys.version_info[:3] != (3, 14, 7), reason='collector contract')
def test_build_joins_actual_scoped_calls_without_executing_target_again(tmp_path):
    root = tmp_path / 'source'
    root.mkdir()
    entry = root / 'main.py'
    entry.write_text('def f(x):\n    return x + 1\n\ny = f(2)\n')
    trace = tmp_path / 'trace'
    repository = Path(__file__).resolve().parents[2]
    captured = subprocess.run([sys.executable, '-B', '-m', 'scar.cli', 'trace',
        '--out', str(trace), '--call-operands', '--python-call-targets', '--project-root', str(root),
        '--', sys.executable, str(entry)], cwd=repository, capture_output=True, text=True, timeout=45)
    assert captured.returncode == 0, captured.stdout + captured.stderr
    out = tmp_path / 'build'
    report = build(entry, trace, out, jobs=1)
    assert report['observed']['scopes'] > 0
    assert (out / 'observed.json').is_file()
    with BuildSession(out) as session:
        observed = session.attach_trace()
        assert observed.interfaces
        assert observed.edges
        assert session.attach_trace() is observed
        assert len(session.view.dependencies.observed_scopes()) == report['observed']['scopes']
