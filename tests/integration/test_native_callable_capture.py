"""One native CALL capture replays into the shared graph and strict export."""
from pathlib import Path
import subprocess
import sys

import pytest


@pytest.mark.skipif(sys.implementation.name != 'cpython' or sys.version_info[:3] != (3, 14, 7),
    reason='the native probe uses the CPython 3.14.7 full ABI')
def test_native_callable_capture_replay_and_shared_graph(tmp_path):
    from scar.analysis.call_operand_reader import read_call_operands
    from scar.analysis.native_callables import read_native_callables
    from scar.analysis.observed_dependency_export import export_observed_dependencies, read_observed_dependencies
    from scar.analysis.program_dependency_session import ProgramDependencySession
    from scar.ir.program.native_callables import NativeCarrier as Carrier, NativeFieldState as State
    from scar.trace.files import resolve as resolve_trace_file

    repository = Path(__file__).resolve().parents[2]
    project = tmp_path / 'source'
    project.mkdir()
    program = project / 'target.py'
    text = (
        'def identity(value):\n    return value\n\n'
        'upper = str.upper("scar")\n'
        'items = []\nappend = items.append\nappend(upper)\n'
        'summed = int.__add__(2, 3)\n'
        'reduce_none = None.__reduce__\n'
        'try:\n    reduced = reduce_none()\nexcept TypeError:\n    reduced = None\n'
        'selected = identity(summed)\n'
        'print("native-complete")\n')
    program.write_text(text)
    trace = tmp_path / 'trace'
    captured = subprocess.run([sys.executable, '-B', '-m', 'scar.cli', 'trace',
        '--native-callables', '--capture-transport', 'snapshot', '--project-root', str(project),
        '--out', str(trace), '--', sys.executable, '-B', str(program)],
        cwd=repository, capture_output=True, text=True, timeout=40)
    assert captured.returncode == 0, captured.stdout + captured.stderr
    assert 'native-complete' in captured.stdout

    def replay():
        return read_native_callables(read_call_operands(trace, project))

    raw = read_call_operands(trace, project)
    native = read_native_callables(raw)
    assert native is not None
    attempts = {(item.process_id, item.index): item for item in raw.attempts}
    assert len(native.facts) == len(native.anchors) == len(attempts)
    assert {(fact.caller.process_id, fact.attempt_index) for fact in native.facts} == set(attempts)
    for fact in native.facts:
        original = attempts[fact.caller.process_id, fact.attempt_index]
        assert fact.caller == original.invocation
        assert fact.callable_reference == original.dispatch.reference
        assert fact.fields.exact_type.state is State.OBSERVED
        assert fact.fields.exact_type_name.state is State.OBSERVED
    codes = {item.code.key for item in raw.frame_scan.captures if item.code.filename == str(program)}
    by_line = {attempts[fact.caller.process_id, fact.attempt_index].site.position[0]: fact
        for fact in native.facts
        if attempts[fact.caller.process_id, fact.attempt_index].site.code in codes}

    def at(statement):
        return by_line[text.splitlines().index(statement) + 1]

    upper = at('upper = str.upper("scar")')
    assert upper.carrier is Carrier.METHOD_DEF
    assert upper.fields.method_name.value == 'upper'
    assert upper.fields.exact_type_name.value == 'method_descriptor'
    assert upper.fields.descriptor_owner.state is State.OBSERVED
    assert upper.fields.descriptor_owner_name.value == 'str'
    assert upper.fields.method_flags.state is State.OBSERVED
    assert upper.fields.entrypoint_address.value > 0 and upper.fields.methoddef_address.value > 0
    append = at('append(upper)')
    assert append.carrier is Carrier.METHOD_DEF
    assert append.fields.exact_type_name.value == 'builtin_function_or_method'
    assert append.fields.bound_self.state is State.OBSERVED
    assert append.fields.wrapper_flags.state is State.ABSENT
    addition = at('summed = int.__add__(2, 3)')
    assert addition.carrier is Carrier.WRAPPER_SLOT
    assert addition.fields.exact_type_name.value == 'wrapper_descriptor'
    assert addition.fields.descriptor_owner_name.value == 'int'
    assert addition.fields.wrapper_flags.state is State.OBSERVED
    assert addition.fields.wrapper_adapter_address.value > 0
    assert addition.fields.wrapped_slot_address.value > 0
    assert addition.fields.method_flags.state is State.ABSENT
    none = at('    reduced = reduce_none()')
    assert none.carrier is Carrier.METHOD_DEF
    assert none.fields.bound_self.state is State.OBSERVED  # Real Py_None, not a NULL field.
    unknown = at('selected = identity(summed)')
    assert unknown.carrier is Carrier.UNKNOWN and unknown.fields.exact_type_name.value == 'function'
    assert unknown.fields.entrypoint_address.state is State.UNKNOWN
    assert all(meta.abi.version == (3, 14, 7) and meta.abi.pointer_bits == 64 for meta in native.metadata)

    # Preserve original absolute receipts while exercising an older trace
    # with no optional capability, and a broken half-present capability.
    meta_path, = trace.glob('native-callable-meta.*.json')
    output_path = resolve_trace_file(Path(native.metadata[0].file.path))
    backup_meta, backup_output = tmp_path / meta_path.name, tmp_path / output_path.name
    meta_path.rename(backup_meta)
    output_path.rename(backup_output)
    try:
        assert replay() is None
        backup_output.rename(output_path)
        with pytest.raises(ValueError):
            replay()
    finally:
        backup_meta.rename(meta_path)
        if backup_output.exists():
            backup_output.rename(output_path)
    probe_source = Path(native.metadata[0].probe_source.path)
    original = probe_source.read_bytes()
    try:
        probe_source.write_bytes(original + b'\n/* altered retained probe */\n')
        with pytest.raises(ValueError):
            replay()
    finally:
        probe_source.write_bytes(original)
    assert replay().facts == native.facts

    model = tmp_path / 'model'
    built = subprocess.run([sys.executable, '-B', '-m', 'scar.cli', 'static', str(project),
        '--phase', 'bodies', '--jobs', '1', '--out', str(model)],
        cwd=repository, capture_output=True, text=True, timeout=40)
    assert built.returncode == 0, built.stdout + built.stderr
    with ProgramDependencySession(model) as session:
        graph = session.graph()
        static_providers = tuple(graph.providers)
        provider = session.attach_observations(trace)
        assert tuple(graph.providers) == static_providers
        assert provider.native_callables
        for scope in provider.scopes:
            rows = graph.observed_native_callables(scope)
            assert rows == tuple(item for item in provider.native_callables if item.scope == scope)
            for row in rows:
                binding = provider.binding(scope)
                assert row.call.scope == row.callable.scope == row.scope == scope
                assert row.call.original == binding.call and row.callable.original == binding.callable
                assert row.fact.caller == scope.caller and row.fact.attempt_index == scope.attempt_index
                if row.fact.carrier is not Carrier.UNKNOWN:
                    assert scope.callee is None  # No native implementation frame/body is invented.
        document = export_observed_dependencies(provider)
        assert document['schema_version'] == 3
        restored = read_observed_dependencies(document)
        assert restored.native_callables == provider.native_callables
        assert restored.native_frontiers == provider.native_frontiers
        assert restored.native_metadata == provider.native_metadata
