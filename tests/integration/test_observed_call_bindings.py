"""CALL-only observations bind instances to shared original static ports."""
import hashlib
import gzip
import json
from pathlib import Path
import subprocess
import sys
from types import CodeType

import pytest


@pytest.mark.skipif(sys.implementation.name != 'cpython' or sys.version_info[:3] != (3, 14, 7),
    reason='the existing lean CALL collector uses the CPython 3.14.7 contract')
def test_two_actual_classes_bind_one_static_call_without_claiming_class_origin(tmp_path):
    from scar.analysis.observed_call_bindings import build_observed_call_bindings
    from scar.analysis.observed_dependency_export import export_observed_dependencies, read_observed_dependencies
    from scar.analysis.observed_function_interfaces import read_observed_function_interfaces
    from scar.analysis.program_dependency_session import ProgramDependencySession
    from scar.ir.program.call_edges import FrameCompletion
    from scar.ir.program.dependencies import DependencyKind as K
    from scar.ir.program.model import ExitKind
    from scar.ir.program.observed_dependencies import ObservedPortPhase as Phase
    from scar.trace.lean_capture import LeanCapturePlan
    from scar.trace.python_call_targets import _is_type_object

    class TrapMeta(type):
        def __getattribute__(cls, name):
            raise AssertionError('classification must not execute a metaclass getter')

    class ActualClass(metaclass=TrapMeta):
        pass

    class PretendsClass:
        @property
        def __class__(self):
            raise AssertionError('classification must not inspect a spoofed __class__')

        def __call__(self):
            return None

    assert _is_type_object(ActualClass)
    assert not _is_type_object(PretendsClass())

    repository = Path(__file__).resolve().parents[2]
    source = tmp_path / 'source'
    source.mkdir()
    program = source / 'program.py'
    text = (repository / 'examples/python_observed_calls/program.py').read_text()
    prefix, assertion, suffix = text.partition('assert first.value == second.value == 3')
    assert assertion
    # The existing module lowerer stops at Assert. Keep that source boundary;
    # this test binds CALLs in its canonical prefix, not Assert or its suffix.
    text = (prefix + '\n\ndef select(first, second):\n    return second\n\n'
        'mixed = select(11, second=29)\n\n'
        'def identity(value):\n    return value\n\n'
        'def twice(left, right, fn):\n    for value in (left, right):\n'
        '        result = fn(value)\n    return result\n\n'
        'repeated = twice(11, 29, identity)\n' + assertion + suffix + 'assert mixed == 29\n')
    program.write_text(text)
    original = hashlib.sha256(program.read_bytes()).hexdigest()
    model = tmp_path / 'model'
    built = subprocess.run([sys.executable, '-B', '-m', 'scar.cli', 'static', str(source),
        '--out', str(model), '--jobs', '1', '--phase', 'bodies'],
        cwd=repository, capture_output=True, text=True)
    assert built.returncode == 0, built.stdout + built.stderr
    manifest_hash = hashlib.sha256((model / 'manifest.json').read_bytes()).hexdigest()

    # Compilation selects immutable code descriptors. It does not import or
    # execute the sample, create its classes, or call build().
    root = compile(text, str(program), 'exec', flags=0, dont_inherit=True, optimize=0)
    pending, codes = [root], []
    while pending:
        code = pending.pop()
        codes.append(code)
        pending.extend(value for value in code.co_consts if type(value) is CodeType)
    plan = LeanCapturePlan.from_codes(source, codes)
    plan_path = tmp_path / 'capture-plan.json'
    plan_bytes = (json.dumps(plan.to_dict(), sort_keys=True, separators=(',', ':')) + '\n').encode()
    plan_path.write_bytes(plan_bytes)

    # Only this child executes the sample, once. CALL-only local monitoring
    # reuses the existing bounded recorder and deferred snapshot transport.
    trace = tmp_path / 'trace'
    captured = subprocess.run([sys.executable, '-B', '-m', 'scar.cli', 'trace',
        '--calls-only', '--capture-plan', str(plan_path), '--capture-plan-sha256',
        hashlib.sha256(plan_bytes).hexdigest(), '--capture-transport', 'snapshot',
        '--out', str(trace), '--project-root', str(source), '--',
        sys.executable, '-B', str(program)], cwd=repository, capture_output=True, text=True)
    assert captured.returncode == 0, captured.stdout + captured.stderr

    report = build_observed_call_bindings(model, trace, tmp_path / 'bindings')
    assert report['observation_only'] is True
    assert report['target_executed'] is False  # the offline binding step executes no target
    assert report['class_origin_verified'] is False
    assert report['transformation_authorized'] is False
    assert report['binding_count'] == len(report['bindings'])
    line = text.splitlines().index('    return cls(3)') + 1
    calls = [binding for binding in report['bindings']
        if binding['source']['path'] == str(program) and binding['source']['start_line'] == line]
    assert len(calls) == 2
    assert {binding['kind'] for binding in calls} == {'TYPE_OBJECT'}
    assert len({binding['call_operation'] for binding in calls}) == 1
    assert len({binding['callee_use'] for binding in calls}) == 1
    references = {binding['callable_reference'] for binding in calls}
    assert len(references) == 2 and all(reference.startswith('weak:') for reference in references)
    assert len({binding['invocation_id'] for binding in calls}) == 2
    assert all(binding['class_origin_verified'] is False for binding in calls)
    assert sum(binding['kind'] == 'FUNCTION' for binding in report['bindings']) >= 2

    # The same raw run supplies entry/exit instances. Static interface ports
    # remain shared declarations; an observed normal return does not delete
    # the function's other completion alternatives.
    interfaces = read_observed_function_interfaces(gzip.decompress(
        (tmp_path / 'bindings' / 'function-interfaces.json.gz').read_bytes()))
    assert report['function_interface_count'] == len(interfaces)
    assert all(item.binding.target.kind.value == 'FUNCTION' for item in interfaces)
    build_lines = {text.splitlines().index(statement) + 1
        for statement in ('first = build(Left)', 'second = build(Right)')}
    builds = [item for item in interfaces if item.binding.source.start_line in build_lines]
    assert len(builds) == 2
    assert builds[0].interface.body == builds[1].interface.body
    assert len({item.entry.callee for item in builds}) == 2
    assert {item.entry.callee.invocation_id for item in builds} == {
        binding['invocation_id'] for binding in calls}
    for item in builds:
        assert item.entry.caller == item.binding.target.caller
        assert item.entry.caller != item.entry.callee
        assert item.observed_exit is not None
        assert item.observed_exit.invocation == item.entry.callee
        assert item.observed_exit.completion is FrameCompletion.NORMAL
        assert item.selected_return in item.interface.normal_returns
        assert item.interface.qualification == 'STATIC_CALL_INTERFACE_NOT_DISPATCH'
        completion_kinds = {route.kind for route in item.interface.completions}
        assert ExitKind.NORMAL in completion_kinds
        # A declared exception packet can require an ABI adapter before a
        # route is connected. Observing NORMAL does not prove RAISE impossible.
        if ExitKind.RAISE not in completion_kinds:
            assert any(frontier.kind == 'COMPLETION_PAYLOAD_ADAPTER_REQUIRED'
                for frontier in item.interface.frontiers)
        port, = item.interface.arguments
        assert port.operation == item.binding.call.node
        assert port.actual_body == item.binding.call.namespace.source_body
        assert port.formal_body == item.interface.body
        assert port.formal_name == 'cls'

    keyword_line = text.splitlines().index('mixed = select(11, second=29)') + 1
    keyword, = (item for item in interfaces if item.binding.source.start_line == keyword_line)
    assert keyword.binding.captured_site.opname == 'CALL_KW'
    assert keyword.entry.caller == keyword.binding.target.caller
    assert keyword.observed_exit.invocation == keyword.entry.callee
    assert keyword.observed_exit.completion is FrameCompletion.NORMAL
    assert keyword.selected_return in keyword.interface.normal_returns
    assert {port.formal_name for port in keyword.interface.arguments} == {'first', 'second'}
    assert len({port.actual_use for port in keyword.interface.arguments}) == 2
    assert all(port.operation == keyword.binding.call.node
        and port.formal_body == keyword.interface.body for port in keyword.interface.arguments)
    assert any(route.kind is ExitKind.NORMAL for route in keyword.interface.completions)

    # The same caller activation executes one static CALL twice. Both data
    # interfaces need the attempt axis, independently of the shared template.
    with ProgramDependencySession(model) as session:
        graph = session.graph()
        static_providers = tuple(graph.providers)
        provider = session.attach_observations(trace)
        assert tuple(graph.providers) == static_providers
        repeated_line = text.splitlines().index('        result = fn(value)') + 1
        scopes = tuple(scope for scope in provider.scopes
            if provider.binding(scope).source.start_line == repeated_line)
        assert len(scopes) == 2 and scopes[0].caller == scopes[1].caller
        assert scopes[0].attempt_index != scopes[1].attempt_index
        assert all(scope.callee is not None for scope in scopes)
        assert len({scope.callee for scope in scopes}) == 2
        bindings = tuple(provider.binding(scope) for scope in scopes)
        assert bindings[0].call == bindings[1].call
        original_call = session.index(bindings[0].call.namespace).operations[bindings[0].call.node]
        declared_completions = original_call.completions
        assert ExitKind.RAISE in {completion.kind for completion in declared_completions}
        occurrences = []
        for scope in scopes:
            ports = provider.ports(scope)
            selected = [port for port in ports if port.phase in (Phase.ENTRY_INTERFACE, Phase.NORMAL_INTERFACE)]
            edges = tuple(edge for port in selected
                for edge in graph.observed_incoming(port, kinds=(K.ARGUMENT, K.COMPLETION)).edges)
            assert {edge.kind for edge in edges} == {K.ARGUMENT, K.COMPLETION}
            for edge in edges:
                assert edge.source.scope == edge.target.scope == scope
                expected = (scope.caller, scope.callee) if edge.kind is K.ARGUMENT else (scope.callee, scope.caller)
                assert (edge.source.invocation, edge.target.invocation) == expected
                assert edge in graph.observed_outgoing(edge.source, kinds=(edge.kind,)).edges
                assert edge.template not in graph.outgoing(edge.source.original, kinds=(edge.kind,)).edges
                assert edge.template.conditions
            occurrences.append(edges)
        assert {edge.template for edge in occurrences[0]} == {edge.template for edge in occurrences[1]}
        assert not set(occurrences[0]).intersection(occurrences[1])
        assert original_call.completions == declared_completions
        document = export_observed_dependencies(provider)
        snapshot = read_observed_dependencies(json.dumps(document))
        assert snapshot.scopes == provider.scopes and snapshot.edges == provider.edges
        assert snapshot.bindings == provider.bindings and snapshot.interfaces == provider.interfaces
        with pytest.raises(ValueError):
            read_observed_dependencies(dict(document, transformation_authorized=True))

    # Corrupt only this test's synthetic capture, after its positive checks.
    # Both a live view and a fresh admission must reject changed raw inputs;
    # a successfully decoded/saved DTO cannot lend them its prior authority.
    live = ProgramDependencySession(model)
    replay = live.attach_observations(trace)
    port = replay.ports(replay.scopes[0])[0]
    stream = Path(replay.binding(replay.scopes[0]).target_anchor.path)
    stream.write_bytes(stream.read_bytes()[:-1])
    with pytest.raises(ValueError, match='observed capture inputs changed'):
        live.graph().observed_outgoing(port)
    with pytest.raises(ValueError, match='observed capture inputs changed'):
        live.close()
    with ProgramDependencySession(model) as fresh:
        with pytest.raises(ValueError):
            fresh.attach_observations(trace)

    assert hashlib.sha256(program.read_bytes()).hexdigest() == original
    assert hashlib.sha256((model / 'manifest.json').read_bytes()).hexdigest() == manifest_hash
    assert not tuple(trace.glob('torch-profiler.*'))

