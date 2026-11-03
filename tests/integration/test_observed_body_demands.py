"""An observed missing body adds a shard without replacing prior authorities."""
from copy import deepcopy
import gzip
import hashlib
import json
from pathlib import Path
import subprocess
import sys
from types import CodeType

import pytest


@pytest.mark.skipif(sys.implementation.name != 'cpython' or sys.version_info[:3] != (3, 14, 7),
    reason='the existing lean CALL collector uses the CPython 3.14.7 contract')
def test_observed_missing_body_preserves_original_call_publication_and_shards(tmp_path):
    from scar.analysis.observed_body_demands import expand_observed_bodies
    from scar.analysis.observed_call_bindings import build_observed_call_bindings
    from scar.analysis.observed_function_interfaces import read_observed_function_interfaces
    from scar.analysis.program_dependency_session import ProgramDependencySession
    from scar.analysis.static_basis_compatibility import units_basis_compatible
    from scar.analysis.static_body import expand_static_bodies
    from scar.analysis.static_calls import input_basis_unit
    from scar.analysis.static_program import link_static_program
    from scar.ir.program.dependencies import DependencyKind as K, DependencyPoint as P, GraphNamespace
    from scar.trace.code_snapshot import describe_code
    from scar.trace.lean_capture import LeanCapturePlan

    repository = Path(__file__).resolve().parents[2]
    source = tmp_path / 'source'
    source.mkdir()
    program = source / 'program.py'
    text = ('def f(value):\n    return value\n\n'
        'def g(value):\n    return f(value)\n\nseed = f(1)\nresult = g(2)\n')
    program.write_text(text)
    source_hash = hashlib.sha256(program.read_bytes()).hexdigest()
    model = tmp_path / 'model'
    built = subprocess.run([sys.executable, '-B', '-m', 'scar.cli', 'static', str(source),
        '--out', str(model), '--jobs', '1', '--phase', 'graph'],
        cwd=repository, capture_output=True, text=True)
    assert built.returncode == 0, built.stdout + built.stderr
    graph_manifest = json.loads((model / 'manifest.json').read_bytes())
    unit, = graph_manifest['units']
    module_key, = (row['entry_key'] for row in unit['bodies'] if row['kind'] == 'MODULE')
    f_key, = (row['entry_key'] for row in unit['bodies'] if row['name'] == '<module>.f')
    g_key, = (row['entry_key'] for row in unit['bodies'] if row['name'] == '<module>.g')
    expand_static_bodies(model, jobs=1, entries=(module_key, f_key))
    before = link_static_program(model)
    unit, = before['units']
    original_rows = {row['entry_key']: row for row in unit['bodies'] if 'artifact' in row}
    assert set(original_rows) == {module_key, f_key}
    assert not next(row for row in unit['bodies'] if row['entry_key'] == g_key).get('artifact')
    assert before['static_calls']['counts']['argument_port_edges'] > 0
    basis = [input_basis_unit(unit) for unit in before['units']]
    descriptors = [*before.get('artifacts', {}).values(), *before['static_calls']['artifacts'],
        *(descriptor for name, descriptor in unit['artifacts'].items()
          if name in ('source', 'lexical', 'semantic', 'semantics', 'control')),
        *(row['artifact'] for row in original_rows.values())]
    retained = {descriptor['path']: (model / descriptor['path']).read_bytes() for descriptor in descriptors}

    def original_calls_and_argument_edges():
        # Each new public session freshly revalidates the old relationship
        # input basis, including the row which originally had no g artifact.
        with ProgramDependencySession(model) as session:
            shards = tuple(shard for shard, _ in session.relation_shards())
            call, = (call for shard in shards for call in shard.calls
                if call.source.start_line == text.splitlines().index('seed = f(1)') + 1)
            target, = (target for target in call.targets if target.body is not None and target.arguments)
            argument, = target.arguments
            point = P(GraphNamespace.from_source(call.caller), argument.actual_use)
            edges = tuple(edge for edge in session.graph().outgoing(point, kinds=(K.ARGUMENT,)).edges
                if edge.target.node == argument.formal_value)
            assert edges
            return shards, edges

    old_shards, old_edges = original_calls_and_argument_edges()

    # Select immutable code descriptors without importing the program; only
    # the trace child below actually executes its f/g calls, once.
    compiled = compile(text, str(program), 'exec', flags=0, dont_inherit=True, optimize=0)
    pending, codes = [compiled], []
    while pending:
        code = pending.pop()
        codes.append(code)
        pending.extend(value for value in code.co_consts if type(value) is CodeType)
    plan = LeanCapturePlan.from_codes(source, codes)
    selection = tmp_path / 'capture-plan.json'
    selection_bytes = (json.dumps(plan.to_dict(), sort_keys=True, separators=(',', ':')) + '\n').encode()
    selection.write_bytes(selection_bytes)
    trace = tmp_path / 'trace'
    captured = subprocess.run([sys.executable, '-B', '-m', 'scar.cli', 'trace',
        '--calls-only', '--capture-plan', str(selection), '--capture-plan-sha256',
        hashlib.sha256(selection_bytes).hexdigest(), '--capture-transport', 'snapshot',
        '--out', str(trace), '--project-root', str(source), '--', sys.executable, '-B', str(program)],
        cwd=repository, capture_output=True, text=True)
    assert captured.returncode == 0, captured.stdout + captured.stderr

    expansion = tmp_path / 'expansion'
    report = expand_observed_bodies(model, trace, expansion, max_bodies=4)
    assert report['target_executed'] is False
    assert report['request_count'] == 1 and report['requested_entries'] == [g_key]
    assert report['expanded_entries'] == [g_key] and report['expanded_body_count'] == 1
    request, = json.loads((expansion / 'plan.json').read_bytes())['requests']
    selected = compiled
    for position in request['compiler']['code_path']:
        selected = selected.co_consts[position]
    assert type(selected) is CodeType and selected.co_name == 'g'
    assert describe_code(selected) == request['capture']['code']

    after = json.loads((model / 'manifest.json').read_bytes())
    after_unit, = after['units']
    rows = {row['entry_key']: row for row in after_unit['bodies']}
    assert all(rows[key] == row for key, row in original_rows.items())
    assert rows[g_key]['artifact'] and rows[g_key]['status'] == 'LOWERED_WITH_GAPS'
    assert after['static_calls'] == before['static_calls']
    assert all((model / path).read_bytes() == contents for path, contents in retained.items())
    coverage = after['body_expansion']['relationship_coverage']
    assert coverage['scope'] == 'PRIOR_BODY_BASIS_ONLY' and coverage['added_bodies_linked'] is False
    assert original_calls_and_argument_edges() == (old_shards, old_edges)

    current_basis = [input_basis_unit(unit) for unit in after['units']]
    assert units_basis_compatible(basis, current_basis)
    # These lightweight comparisons cannot bless replaced artifacts or
    # different source/declaration identities as merely filling a body hole.
    changed = deepcopy(current_basis)
    next(row for row in changed[0]['bodies'] if row['entry_key'] == f_key)['artifact']['sha256'] = '0' * 64
    assert not units_basis_compatible(basis, changed)
    changed = deepcopy(current_basis)
    changed[0]['artifacts']['source']['sha256'] = '0' * 64
    assert not units_basis_compatible(basis, changed)
    changed = deepcopy(current_basis)
    next(row for row in changed[0]['bodies'] if row['entry_key'] == g_key)['definitions'] = []
    assert not units_basis_compatible(basis, changed)

    bound = tmp_path / 'bindings'
    joined = build_observed_call_bindings(model, trace, bound)
    interfaces = read_observed_function_interfaces(gzip.decompress((bound / 'function-interfaces.json.gz').read_bytes()))
    g_line = text.splitlines().index('result = g(2)') + 1
    observed_g, = (item for item in interfaces if item.binding.source.start_line == g_line)
    assert observed_g.interface.body.entry == 'g'
    assert len(observed_g.interface.arguments) == 1
    assert observed_g.selected_return in observed_g.interface.normal_returns
    assert joined['target_executed'] is False and joined['transformation_authorized'] is False
    assert hashlib.sha256(program.read_bytes()).hexdigest() == source_hash

