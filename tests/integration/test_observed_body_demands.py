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


@pytest.mark.skipif(sys.implementation.name != 'cpython' or sys.version_info[:3] != (3, 14, 7),
    reason='the existing lean CALL collector uses the CPython 3.14.7 contract')
def test_observed_external_source_appends_without_replacing_prior_graph(tmp_path):
    from scar.analysis.observed_body_demands import expand_observed_bodies
    from scar.analysis.program_dependency_session import ProgramDependencySession
    from scar.analysis.static_calls import input_basis_unit
    from scar.analysis.static_class_publication import link_static_class_program
    from scar.analysis.static_basis_compatibility import published_units_basis_compatible
    from scar.analysis.static_program import _artifacts, link_static_program
    from scar.ir.program.dependencies import DependencyKind as K, DependencyPoint as P, GraphNamespace
    from scar.trace.code_snapshot import code_key
    from scar.trace.lean_capture import LeanCapturePlan

    repository = Path(__file__).resolve().parents[2]
    source = tmp_path / 'source'
    source.mkdir()
    external = tmp_path / 'external.py'
    external_text = 'def remote(value):\n    return value\n'
    external.write_text(external_text)
    program = source / 'program.py'
    execution_marker = tmp_path / 'executed-once'
    # A module dictionary display must not hide the later exec/call ports.
    text = (f'open({str(execution_marker)!r}, "x").close()\n'
        'def f(value):\n    return value\n\n'
        'class Anchor:\n    pass\n\nseed = f(1)\n'
        'namespace = {}\n'
        f'exec(compile(open({str(external)!r}).read(), {str(external)!r}, "exec"), namespace)\n'
        'result = namespace["remote"](2)\n')
    program.write_text(text)
    model = tmp_path / 'model'
    built = subprocess.run([sys.executable, '-B', '-m', 'scar.cli', 'static', str(source),
        '--out', str(model), '--jobs', '1', '--phase', 'bodies'],
        cwd=repository, capture_output=True, text=True, timeout=40)
    assert built.returncode == 0, built.stdout + built.stderr
    link_static_program(model)
    before = link_static_class_program(model)
    assert [unit['path'] for unit in before['units']] == [str(program)]
    retained = {descriptor['path']: (model / descriptor['path']).read_bytes()
        for descriptor in _artifacts(before)}
    before_manifest = (model / 'manifest.json').read_bytes()

    def prior_argument_edges():
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

    prior_edges = prior_argument_edges()
    roots = [compile(body, str(path), 'exec', flags=0, dont_inherit=True, optimize=0)
        for path, body in ((program, text), (external, external_text))]
    pending, codes = list(roots), []
    while pending:
        code = pending.pop()
        codes.append(code)
        pending.extend(value for value in code.co_consts if type(value) is CodeType)
    plan = LeanCapturePlan.from_codes(source, codes)
    assert any(body.source.path == str(external) and body.source.fingerprint for body in plan.bodies)
    selection = tmp_path / 'capture-plan.json'
    selection_bytes = (json.dumps(plan.to_dict(), sort_keys=True, separators=(',', ':')) + '\n').encode()
    selection.write_bytes(selection_bytes)
    trace = tmp_path / 'trace'
    captured = subprocess.run([sys.executable, '-B', '-m', 'scar.cli', 'trace',
        '--calls-only', '--capture-plan', str(selection), '--capture-plan-sha256',
        hashlib.sha256(selection_bytes).hexdigest(), '--capture-transport', 'snapshot',
        '--out', str(trace), '--project-root', str(source), '--', sys.executable, '-B', str(program)],
        cwd=repository, capture_output=True, text=True, timeout=40)
    assert captured.returncode == 0, captured.stdout + captured.stderr
    assert execution_marker.is_file()
    execution_stamp = execution_marker.stat()

    # Code identity alone cannot establish the whole source version: this
    # comment changes its SHA while retaining the same compiled code.
    changed_text = external_text.replace('return value', 'return value  # changed source version')
    assert code_key(compile(changed_text, str(external), 'exec')) == code_key(roots[1])
    try:
        external.write_text(changed_text)
        rejected = expand_observed_bodies(model, trace, tmp_path / 'changed-source', max_bodies=8)
        assert rejected['expanded_body_count'] == 0
        assert rejected['source_expansion']['added_source_count'] == 0
        assert any(issue['kind'] == 'CAPTURE_SOURCE_VERSION_CHANGED'
            for issue in rejected['source_expansion']['issues'])
        assert (model / 'manifest.json').read_bytes() == before_manifest
    finally:
        external.write_text(external_text)

    report = expand_observed_bodies(model, trace, tmp_path / 'expansion', max_bodies=8)
    assert report['target_executed'] is False
    assert report['expanded_body_count'] >= 1
    source_report = report['source_expansion']
    assert source_report['target_executed'] is False and source_report['added_source_count'] == 1
    assert source_report['added_files'] == [str(external)]
    assert source_report['prior_manifest_sha256'] == hashlib.sha256(before_manifest).hexdigest()
    assert source_report['published_manifest_sha256'] == report['prior_manifest_sha256']
    assert Path(source_report['plan']).parent != Path(report['plan']).parent
    after = json.loads((model / 'manifest.json').read_bytes())
    assert after['units'][:len(before['units'])] == before['units']
    appended, = after['units'][len(before['units']):]
    assert appended['path'] == str(external) and appended['module_names'] == []
    assert after['static_calls'] == before['static_calls']
    assert after['static_classes'] == before['static_classes']
    assert all((model / path).read_bytes() == contents for path, contents in retained.items())
    assert prior_argument_edges() == prior_edges
    assert input_basis_unit(after['units'][0]) == input_basis_unit(before['units'][0])
    ledger = after['source_expansion']
    assert ledger['coverage'] == 'PRIOR_SOURCE_BASIS_ONLY'
    old_basis = [input_basis_unit(unit) for unit in before['units']]
    current_basis = [input_basis_unit(unit) for unit in after['units']]
    assert published_units_basis_compatible(old_basis, current_basis, source_expansion=ledger)
    assert not published_units_basis_compatible(old_basis, current_basis)
    for field in ('body', 'source', 'namespace'):
        changed = deepcopy(current_basis)
        if field == 'body':
            next(row for row in changed[0]['bodies'] if 'artifact' in row)['artifact']['sha256'] = '0' * 64
        elif field == 'source':
            changed[0]['artifacts']['source']['sha256'] = '0' * 64
        else:
            changed[0]['namespace_root'] += '/different'
        assert not published_units_basis_compatible(old_basis, changed, source_expansion=ledger)

    with ProgramDependencySession(model) as session:
        provider = session.attach_observations(trace)
        line = text.splitlines().index('result = namespace["remote"](2)') + 1
        remote, = (item for item in provider.interfaces if item.binding.source.start_line == line)
        assert remote.interface.body.source.path == str(external)
        argument, = remote.interface.arguments
        assert argument.formal_name == 'value' and argument.index == 0
        assert remote.selected_return in remote.interface.normal_returns
        scope, = (scope for scope in provider.scopes if provider.binding(scope) == remote.binding)
        edges = tuple(edge for point in provider.ports(scope)
            for edge in session.graph().observed_outgoing(point).edges)
        assert {K.CALL_TARGET, K.ARGUMENT, K.COMPLETION} <= {edge.kind for edge in edges}
    assert program.read_text() == text and external.read_text() == external_text
    assert execution_marker.stat() == execution_stamp


@pytest.mark.skipif(sys.implementation.name != 'cpython' or sys.version_info[:3] != (3, 14, 7),
    reason='observed code correspondence uses the CPython 3.14.7 contract')
def test_current_library_source_is_only_a_matched_code_scope_candidate(tmp_path):
    from scar.analysis.observed_body_demands import expand_observed_bodies
    from scar.analysis.program_dependency_session import ProgramDependencySession
    from scar.trace.code_snapshot import code_key

    repository = Path(__file__).resolve().parents[2]
    source = tmp_path / 'source'
    source.mkdir()
    external = tmp_path / 'library.py'
    original_library = ('GLOBAL = 3\n\ndef remote(value):\n    return value\n\n'
        'def sibling(value):\n    return 11\n')
    external.write_text(original_library)
    program = source / 'program.py'
    program_text = ('namespace = dict()\n'
        f'exec(compile(open({str(external)!r}).read(), {str(external)!r}, "exec"), namespace)\n'
        'result = namespace["remote"](2)\n')
    program.write_text(program_text)
    model = tmp_path / 'model'
    built = subprocess.run([sys.executable, '-B', '-m', 'scar.cli', 'static', str(source),
        '--out', str(model), '--jobs', '1', '--phase', 'bodies'],
        cwd=repository, capture_output=True, text=True, timeout=40)
    assert built.returncode == 0, built.stdout + built.stderr
    trace = tmp_path / 'trace'
    # snapshot is the transport, not a historical source capture plan.
    captured = subprocess.run([sys.executable, '-B', '-m', 'scar.cli', 'trace',
        '--python-call-targets', '--capture-transport', 'snapshot', '--out', str(trace),
        '--project-root', str(source), '--', sys.executable, '-B', str(program)],
        cwd=repository, capture_output=True, text=True, timeout=40)
    assert captured.returncode == 0, captured.stdout + captured.stderr
    assert not tuple(trace.glob('lean-plan.*.json'))

    # Current file material may differ outside the observed function. Its
    # initializer would now raise if accidentally executed, and its uncalled
    # sibling has a different implementation. Neither is capture-time state.
    current_library = original_library.replace('GLOBAL = 3', 'GLOBAL = 1 / 0').replace('return 11', 'return 29')
    def function_code(text, name):
        return next(value for value in compile(text, str(external), 'exec').co_consts
                    if type(value) is CodeType and value.co_name == name)
    assert code_key(function_code(original_library, 'remote')) == code_key(function_code(current_library, 'remote'))
    assert code_key(function_code(original_library, 'sibling')) != code_key(function_code(current_library, 'sibling'))
    external.write_text(current_library)
    expansion = tmp_path / 'expansion'
    report = expand_observed_bodies(model, trace, expansion, max_bodies=8)
    assert report['target_executed'] is False
    source_report = report['source_expansion']
    assert source_report['added_files'] == [str(external)] and source_report['added_source_count'] == 1
    plan = json.loads(Path(source_report['plan']).read_bytes())
    demand, = plan['demands']
    assert demand['import_or_class_origin_established'] is False
    assert demand['runtime_globals_established'] is demand['file_execution_established'] is False
    assert demand['source']['module_names'] == [] and demand['source']['module_mappings'] == []
    assert demand['proofs'] and {proof['capture']['code']['qualname'] for proof in demand['proofs']} == {'remote'}
    for proof in demand['proofs']:
        assert proof['source_origin'] == 'CURRENT_STATIC_SOURCE_CANDIDATE'
        assert proof['historical_snapshot'] is proof['source_snapshot'] is proof['plan'] is None
    requests = json.loads((expansion / 'plan.json').read_bytes())['requests']
    selected = [request for request in requests if request['capture']['code']['filename'] == str(external)]
    assert len(selected) == 1 and selected[0]['capture']['code']['qualname'] == 'remote'
    authority = selected[0]['source_authority']
    assert authority['source_origin'] == 'CURRENT_STATIC_SOURCE_CANDIDATE'
    assert authority['scope'] == 'MATCHED_CODE_SCOPE_ONLY' and authority['historical_snapshot'] is None
    manifest = json.loads((model / 'manifest.json').read_bytes())
    unit, = (unit for unit in manifest['units'] if unit['path'] == str(external))
    sibling, = (row for row in unit['bodies'] if row['name'] == '<module>.sibling')
    assert 'artifact' not in sibling  # The current static declaration still exists.
    with ProgramDependencySession(model) as session:
        provider = session.attach_observations(trace)
        interfaces = [item for item in provider.interfaces
            if item.interface.body.source.path == str(external)]
        remote, = interfaces
        assert remote.interface.body.entry == 'remote' and len(remote.interface.arguments) == 1
        assert remote.selected_return in remote.interface.normal_returns
        assert not remote.interface.environment_routes
        assert {'OBSERVED_FUNCTION_ENVIRONMENT_OPEN', 'FINE_EFFECTS_OPEN'} <= {
            frontier.kind for frontier in remote.interface.frontiers}
    assert external.read_text() == current_library and program.read_text() == program_text

