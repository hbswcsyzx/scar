"""Owned metadata micro workload; no hooks, LeWM, Tensor values or capture.

cProfile cannot share sys.setprofile with the frame collector. This drives the
actual operand shape, Python target and environment methods directly around
small Python calls; it does not claim whole-collector/run attribution.
"""
import argparse
import cProfile
import dis
import hashlib
import importlib.util
import io
import json
import os
from pathlib import Path
import pstats
import statistics
import subprocess
import sys
import tempfile
import time
from types import SimpleNamespace

from scar.trace import call_operands as operands
from scar.trace import callable_environment as environments
from scar.trace import python_call_targets as targets
from scar.trace.code_snapshot import code_key, site

HERE = Path(__file__).resolve().parent
BASE = '75ee9dcf'


class Receiver:
    pass


def lightweight(self, value=None):
    return value


Receiver.method = lightweight


def call_site(receiver):
    return receiver.method(1)


def load_baseline(directory):
    result = []
    for name in ('call_operands', 'callable_environment', 'python_call_targets'):
        path = directory / (name + '.py')
        path.write_bytes(subprocess.check_output([
            'git', 'show', BASE + ':scar/trace/' + name + '.py']))
        alias = '_before_hotpath_' + name
        spec = importlib.util.spec_from_file_location(alias, path)
        module = importlib.util.module_from_spec(spec)
        sys.modules[alias] = module
        spec.loader.exec_module(module)
        result.append(module)
    return tuple(result)


def workload(modules, directory, count):
    operand_module, environment_module, target_module = modules
    directory.mkdir()
    recorder = SimpleNamespace(out=directory, pid=os.getpid(), root=str(HERE))
    operand = SimpleNamespace(recorder=recorder, _code_inside=lambda code: False)
    observer = target_module.PythonTargetObserver(operand,
        target_module.PythonTargetBudget(count * 2 + 8, 128_000_000, 16))
    environment = environment_module.CallableEnvironmentObserver(directory,
        os.getpid(), max_events=count * 2 + 8, max_bytes=128_000_000,
        max_references=100_000)
    identities = {}
    def reference(value):
        # All objects referenced here are retained by this owned micro workload.
        return identities.setdefault(id(value), f'weak:{os.getpid()}:{len(identities)+1}')
    shape_owner = operand_module.CallOperandObserver.__new__(operand_module.CallOperandObserver)
    shape_owner._reference = lambda value, *unused: reference(value)
    receivers = [Receiver(), Receiver()]
    methods = [receiver.method for receiver in receivers]
    caller_code = call_site.__code__
    offset = next(i.offset for i in dis.get_instructions(caller_code) if i.opname == 'CALL')
    original_site = site(caller_code, offset)
    key = code_key(lightweight.__code__)
    shape_digest = hashlib.sha256()
    returned = 0
    try:
        for index in range(count):
            attempt = index + 1
            receiver = receivers[index % 2]
            # Observe mutable fields each event. Neither tuple nor receiver
            # association may be reused from a prior CALL snapshot.
            lightweight.__defaults__ = None if index % 3 == 0 else (index,)
            lightweight.__kwdefaults__ = {'unused': index}
            callable_object = lightweight if index % 2 == 0 else methods[index % 2]
            shape = shape_owner._shape(callable_object, {}, attempt, {}, [])
            shape_digest.update(json.dumps(shape, separators=(',', ':')).encode())
            observer.on_call(callable_object, receiver, False, caller_code, 1,
                original_site, attempt, reference, operand_module._layout)
            # Entry routing is not profiled here; no invented entry is emitted.
            observer.pending.clear()
            assert environment.dispatch(lightweight, attempt, 1, attempt, key, reference)
            returned += lightweight(receiver, index)
            assert environment.entry(lightweight, attempt, 2, attempt,
                                     lightweight.__globals__, lightweight.__builtins__)
    finally:
        lightweight.__defaults__ = (None,)
        lightweight.__kwdefaults__ = None
        observer.close()
        environment.close()
    return {
        'target_sha256': hashlib.sha256(observer.path.read_bytes()).hexdigest(),
        'environment_sha256': hashlib.sha256(environment.event_path.read_bytes()).hexdigest(),
        'shape_sha256': shape_digest.hexdigest(),
        'target_rows': observer.records, 'environment_rows': environment._events,
        'target_bytes': observer.bytes, 'environment_bytes': environment._bytes,
        'environment_gaps': environment._gap_count, 'checksum': returned,
    }


def profiled(modules, directory, count):
    profiler = cProfile.Profile()
    started = time.perf_counter()
    result = profiler.runcall(workload, modules, directory, count)
    elapsed = time.perf_counter() - started
    stats = pstats.Stats(profiler)
    stream = io.StringIO()
    stats.stream = stream
    stats.sort_stats('cumulative').print_stats(40)
    rows = []
    for (filename, line, function), (primitive, calls, own, cumulative, callers) in stats.stats.items():
        if '/scar/' in filename or '_before_hotpath_' in filename or filename.endswith(('call_operands.py', 'callable_environment.py', 'python_call_targets.py')):
            rows.append(dict(file=filename, line=line, function=function, calls=calls,
                             own_seconds=own, cumulative_seconds=cumulative))
    return dict(elapsed_seconds=elapsed, result=result,
                functions=sorted(rows, key=lambda x: -x['cumulative_seconds'])), stream.getvalue()


def main():
    parser = argparse.ArgumentParser()
    parser.add_argument('--phase', choices=('baseline', 'comparison'), required=True)
    parser.add_argument('--count', type=int, default=5000)
    args = parser.parse_args()
    current = operands, environments, targets
    with tempfile.TemporaryDirectory(prefix='scar-hotpath-') as temporary:
        root = Path(temporary)
        baseline = load_baseline(root) if args.phase == 'comparison' else current
        before, before_text = profiled(baseline, root / 'before-profile', args.count)
        output = dict(base=BASE, python=sys.version, count=args.count,
                      scope='actual metadata methods; no installed hooks or run attribution', before=before)
        (HERE / (args.phase + '-before-profile.txt')).write_text(before_text)
        if args.phase == 'comparison':
            after, after_text = profiled(current, root / 'after-profile', args.count)
            assert before['result'] == after['result'], 'metadata bytes or dynamic observations differ'
            (HERE / 'comparison-after-profile.txt').write_text(after_text)
            output['after'] = after
            timings = {'before': [], 'after': []}
            for repeat in range(3):
                for label, modules in (('before', baseline), ('after', current)):
                    started = time.perf_counter()
                    observed = workload(modules, root / f'{label}-timed-{repeat}', args.count)
                    timings[label].append(time.perf_counter() - started)
                    assert observed == before['result']
            output['unprofiled_seconds'] = timings
            output['median_seconds'] = {key: statistics.median(value) for key, value in timings.items()}
            output['byte_identical'] = True
        (HERE / (args.phase + '.json')).write_text(json.dumps(output, indent=2) + '\n')
        print(json.dumps({key: value for key, value in output.items() if key not in ('before', 'after')}))
        print(json.dumps({'before_elapsed': before['elapsed_seconds'],
                          'before_top': before['functions'][:10]}))


if __name__ == '__main__':
    main()
