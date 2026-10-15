"""Independent reader oracle pinned to the accepted pre-streaming source.

The legacy function and its wire helpers come from the fixed Git object, not
the current collecting adapter. Importing current record types does not route
the historical function through the new scanner.
"""
import ast
from pathlib import Path
import subprocess

import pytest

from scar.analysis.call_trace_reader import CollectingCallSink, scan_call_trace
from scar.ir.program.call_edges import CallEdgeBudget
from tests.unit.test_call_trace_reader import _code, _enter, _exit, _single_trace, _write_trace


REVISION = '8eeaffeabd6d3e475af2d4221441f7c83f3a62e8'


@pytest.fixture(scope='module')
def historical_reader():
    root = Path(__file__).resolve().parents[2]
    original = subprocess.check_output(
        ['git', 'show', REVISION + ':scar/analysis/call_edges.py'], cwd=root, text=True)
    functions = {'_require', '_exact_int', '_boolean', '_issue', '_reference', '_bindings', '_read_trace'}
    constants = {'_ENTER_FIELDS', '_EXIT_FIELDS'}
    nodes = []
    for node in ast.parse(original).body:
        if (isinstance(node, (ast.Import, ast.ImportFrom))
                or isinstance(node, ast.FunctionDef) and node.name in functions
                or isinstance(node, ast.Assign) and any(
                    isinstance(target, ast.Name) and target.id in constants for target in node.targets)):
            nodes.append(node)
    namespace = {'__name__': 'scar_historical_reader_oracle'}
    exec(compile(ast.Module(body=nodes, type_ignores=[]), '<historical-reader-' + REVISION + '>', 'exec'), namespace)
    assert namespace['_read_trace'].__code__.co_filename.startswith('<historical-reader-')
    return namespace['_read_trace']


def current_reader(trace, root, budget):
    sink = CollectingCallSink()
    result = scan_call_trace(trace, root, budget, sink=sink)
    return (result.directory, result.files, result.captures, tuple(sink.entries),
            tuple(sink.exits), result.metadata, result.issues)


@pytest.mark.parametrize('archive', [False, True])
def test_current_stream_matches_fixed_historical_raw_manifest(tmp_path, historical_reader, archive):
    root, trace = _single_trace(tmp_path, gzip_families=('codes', 'events') if archive else (),
                                overrides={'extra_metadata': {'arbitrary': [1, 'retained']}})
    assert current_reader(trace, root, CallEdgeBudget()) == historical_reader(trace, root, CallEdgeBudget())


def test_later_process_descriptor_cannot_change_earlier_decode(tmp_path, historical_reader):
    root = tmp_path / 'project'
    root.mkdir()
    later = _code('a', filename=str(root / 'later.py'), qualname='f', parameters=('later_param',))
    # The old format can retain an entry whose own process descriptor was
    # dropped. A later process must not retrospectively validate its formals.
    events = [_enter(17, 1, later['key'], 0), _exit(17, 1, later['key'], 1)]
    trace = _write_trace(root, tmp_path / 'trace', [(17, [], events, {}), (18, [later], [], {})])
    assert current_reader(trace, root, CallEdgeBudget()) == historical_reader(trace, root, CallEdgeBudget())


@pytest.mark.parametrize('limit', ['max_references', 'max_raw_bytes', 'max_events', 'max_line_bytes'])
def test_current_and_historical_readers_both_enforce_raw_ceilings(tmp_path, historical_reader, limit):
    refs = tuple({'name': f'x{i}', 'ref': f'weak:17:{i + 1}'} for i in range(4))
    root, trace = _single_trace(tmp_path, parameters=refs)
    budget = CallEdgeBudget(**{limit: 1})
    for reader in (historical_reader, current_reader):
        with pytest.raises((ValueError, TypeError)):
            reader(trace, root, budget)
