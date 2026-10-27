"""One bounded LeWM import-prefix diagnostic. Not production source evidence."""
import atexit
import functools
import json
import os
from pathlib import Path
import runpy
import signal
import sys
import threading
from time import perf_counter_ns as now

ROOT = Path(__file__).resolve().parent
SOURCE = ROOT / 'diagnostic-source'
LEWM = Path('/home/zyf/AAA/le-wm')
sys.path.insert(0, str(SOURCE))
sys.path.insert(1, str(LEWM))
os.sched_setaffinity(0, {54, 55})
for name in tuple(os.environ):
    if name.startswith('SCAR_'):
        del os.environ[name]
os.environ.update(SCAR_CAPTURE_TRANSPORT='snapshot', SCAR_SNAPSHOT_BUFFER_BYTES='8388608',
    SCAR_PYTHON_CAPTURE_PROFILE='SCAR_PROGRAM_PORTS_V2', SCAR_OPERAND_CAPTURE='process-ports',
    SCAR_PYTHON_CALL_TARGETS='PYTHON_CALL_TARGETS_V2', SCAR_STREAM_INTERFACES='1',
    SCAR_STREAM_BACKING_OBSERVATIONS='1', SCAR_CALL_MAX_EVENTS='2000000',
    SCAR_CALL_MAX_BYTES='1000000000', SCAR_CALL_MAX_CODES='65536',
    SCAR_CALL_MAX_REFERENCES='262144', SCAR_OPERAND_MAX_EVENTS='2000000',
    SCAR_OPERAND_MAX_BYTES='1000000000', SCAR_SOURCE_MAX_FILES='4096',
    SCAR_SOURCE_MAX_FILE_BYTES='4000000', SCAR_SOURCE_MAX_BYTES='256000000',
    CUDA_VISIBLE_DEVICES='', OMP_NUM_THREADS='1', MKL_NUM_THREADS='1', OPENBLAS_NUM_THREADS='1',
    LEWM_OUTPUT_ROOT=str(ROOT/'lewm-output'), LEWM_RUN_NAME='diagnostic-import-only')

from scar.trace import call_edges as edges, call_operands as operands
from scar.trace import python_call_targets as targets, callable_environment as environments
from scar.trace import code_snapshot as code, deferred_jsonl as deferred, snapshot_journal as journal
from scar.trace.captured_sources import CapturedSources

selection = [
    (edges.CallEdgeRecorder, name, 'edges.'+name) for name in ('_code','_site','_bindings','_reference')]
selection += [(operands.CallOperandObserver, name, 'operands.'+name)
    for name in ('_shape','_reference','_emit')]
selection += [(operands, '_layout', 'operands._layout')]
selection += [(targets, '_target_record', 'targets._target_record')]
selection += [(targets.PythonTargetObserver, name, 'targets.'+name)
    for name in ('on_call','pending_for','emit','_emit_fields')]
selection += [(environments.CallableEnvironmentObserver, name, 'env.'+name)
    for name in ('dispatch','_anchored_reference','_emit')]
selection += [(code, name, 'code.'+name)
    for name in ('_key_record','describe_code','site','code_key','code_parameters')]
selection += [(deferred.DeferredJsonl,'append','deferred.append'),
              (journal.SnapshotJournal,'append','journal.append'),
              (CapturedSources,'observe','sources.observe')]

local = threading.local()
threads = []
enabled = True
def counters():
    rows = getattr(local, 'rows', None)
    if rows is None:
        rows = [[0,0] for _ in selection]
        local.rows = rows
        threads.append((threading.get_ident(), rows))
    return rows

def wrap(function, index):
    @functools.wraps(function)
    def measured(*args, **kwargs):
        if not enabled:
            return function(*args, **kwargs)
        started = now()
        try:
            return function(*args, **kwargs)
        finally:
            elapsed = now() - started
            row = counters()[index]
            row[0] += 1
            row[1] += elapsed
    return measured

originals = []
for index, (owner, name, label) in enumerate(selection):
    original = getattr(owner, name)
    replacement = wrap(original, index)
    originals.append((label, original.__code__.co_filename, original.__code__.co_firstlineno))
    setattr(owner, name, replacement)
    # Imported aliases must be timed too; no application module is modified.
    for module in (edges, operands, targets, environments, code, deferred, journal):
        for alias, value in tuple(vars(module).items()):
            if value is original:
                setattr(module, alias, replacement)

def no_operation():
    return None
probe = wrap(no_operation, 0)
started = now()
for _ in range(20000): no_operation()
plain_ns = now()-started
started = now()
for _ in range(20000): probe()
wrapped_ns = now()-started
threads.clear()
del local.rows

trace = ROOT/'capture'/'trace'
trace.mkdir(parents=True)
recorder = edges.install(trace, LEWM)
observer = operands.install(recorder, capture='process-ports', python_targets=True, stream_interfaces=True)
started = now()
state = {'stage':'IMPORT_PREFIX_RUNNING','signal':None}
def dump():
    global enabled
    enabled = False
    recorder._closing = True
    rows = []
    for index, (label, filename, line) in enumerate(originals):
        count = sum(values[index][0] for _, values in threads)
        inclusive = sum(values[index][1] for _, values in threads)
        rows.append(dict(helper=label, source=filename, line=line, calls=count,
                         inclusive_ns=inclusive, inclusive_seconds=inclusive/1e9))
    result = dict(status=state['stage'], signal=state['signal'], pid=os.getpid(),
        elapsed_ns=now()-started, affinity=sorted(os.sched_getaffinity(0)),
        workload='runpy.run_path(original run_inference.py, non-main name): same top-level import prefix only',
        helpers=sorted(rows,key=lambda r:-r['inclusive_ns']), completed_helper_calls_only=True,
        timer_threads=len(threads), timer_calibration=dict(iterations=20000,plain_ns=plain_ns,
            wrapped_ns=wrapped_ns,incremental_ns_per_call=(wrapped_ns-plain_ns)/20000),
        inclusive_times_overlap=True, exclusive_time_established=False, performance_AB=False,
        collector_witness_enabled=False, production_source_qualification=False,
        native_OS_profiler_enabled=False, CUDA_VISIBLE_DEVICES='', episode_started=False,
        differences=['timer wrappers add clock/counter/function-call cost',
            'only unchanged LeWM import prefix; no main/eval/model construction',
            'no strace/native/collector execution witness; 2 CPU affinity; BLAS threads=1',
            'diagnostic copy, not frozen collector byte/source equivalence',
            'counter dump precedes collector materialization; close costs not included'])
    (ROOT/'HELPER_TIMINGS.json').write_text(json.dumps(result,indent=2)+'\n')

atexit.register(dump)  # Save before the earlier registered collector close.
def interrupted(number, frame):
    state.update(stage='INTERRUPTED_IMPORT_PREFIX',signal=number)
    raise KeyboardInterrupt
signal.signal(signal.SIGINT, interrupted)
sys.argv = [str(LEWM/'run_inference.py')]
runpy.run_path(str(LEWM/'run_inference.py'), run_name='__scar_import_prefix_diagnostic__')
state['stage']='IMPORT_PREFIX_COMPLETED'
