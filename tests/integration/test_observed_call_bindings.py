"""CALL-only observations bind instances to shared original static ports."""
import hashlib
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
    assert hashlib.sha256(program.read_bytes()).hexdigest() == original
    assert hashlib.sha256((model / 'manifest.json').read_bytes()).hexdigest() == manifest_hash
    assert not tuple(trace.glob('torch-profiler.*'))

