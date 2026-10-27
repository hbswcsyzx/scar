"""One original 151-file composition and one same-capture source binding."""
from hashlib import sha256
import json
from pathlib import Path
import resource
import subprocess
import time

from scar.analysis.program_composition import compose_program, CompositionIndex
from scar.analysis.source_invocations import bind_source_invocations
from scar.ir.program.call_edges import CallEdgeBudget
from scar.trace.capture_coordinates import bind_capture_coordinates


HERE = Path(__file__).resolve().parent
ROOT = HERE.parents[2]
MANIFEST = HERE.parent / 'first_stage_full_inventory_restored_20261023/result/manifest.json'
LAYERS = HERE.parent / 'first_stage_source_context_20261022/result/source-layers'
CAPTURE = HERE.parent / 'first_stage_lewm_dispatch_20261023'
COMPOSITION = HERE / 'composition'
BINDINGS = HERE / 'bindings'
started = time.perf_counter()
log = (HERE / 'progress.jsonl').open('x', buffering=1)


def write(event):
    log.write(json.dumps({'elapsed_s': time.perf_counter() - started,
                         'max_rss_kib': resource.getrusage(resource.RUSAGE_SELF).ru_maxrss,
                         **event}, ensure_ascii=False) + '\n')


def receipt(path):
    payload = path.read_bytes()
    return {'path': str(path), 'sha256': sha256(payload).hexdigest(), 'bytes': len(payload)}


sources = [ROOT / name for name in (
    'scar/analysis/program_composition.py', 'scar/analysis/source_invocations.py',
    'scar/analysis/inventory_partitions.py', 'scar/analysis/source_layers.py',
    'scar/trace/capture_coordinates.py', 'scar/analysis/call_trace_reader.py',
    'scar/ir/program/codec.py')]
producer = {'git_revision': subprocess.check_output(['git', 'rev-parse', 'HEAD'], cwd=ROOT, text=True).strip(),
    'modules': [receipt(path) for path in sources], 'script': receipt(Path(__file__)),
    'inventory_manifest': receipt(MANIFEST), 'source_archive_index': receipt(LAYERS / 'index.json'),
    'capture': str(CAPTURE), 'process_scope': 272038, 'witness_mode': 'same_capture',
    'fresh_lower_or_prepare_requested': False, 'whole_program_established': False}
(HERE / 'producer.json').write_text(json.dumps(producer, indent=2) + '\n')
try:
    write({'stage': 'compose', 'status': 'BEGIN'})
    summary = compose_program(MANIFEST, LAYERS, COMPOSITION, max_record_bytes=128_000_000,
                              progress=write)
    write({'stage': 'compose', 'status': 'END', 'summary': summary})
    write({'stage': 'coordinates', 'status': 'BEGIN'})
    coordinates = bind_capture_coordinates(CAPTURE, max_bytes=2_000_000_000,
        max_lines=2_000_000, profile_uri=str(BINDINGS / 'capture-coordinates.json'))
    write({'stage': 'coordinates', 'status': 'END', 'run': coordinates.run.id.value})
    write({'stage': 'bind', 'status': 'BEGIN'})
    report = bind_source_invocations(CompositionIndex(COMPOSITION / 'index.json.gz'),
        coordinates, CAPTURE / 'trace', BINDINGS,
        call_budget=CallEdgeBudget(max_raw_bytes=256_000_000, max_lines=300_000,
            max_events=250_000, max_references=2_000_000), witness_mode='same_capture')
    write({'stage': 'bind', 'status': 'END', 'summary': report['summary']})
    final = {'status': 'COMPOSED_AND_BOUND_WITH_OPEN_OBLIGATIONS',
        'elapsed_s': time.perf_counter() - started,
        'max_rss_kib': resource.getrusage(resource.RUSAGE_SELF).ru_maxrss,
        'composition': summary, 'bindings': report['summary'],
        'fresh_lower_or_prepare_performed': False, 'whole_program_established': False}
    (HERE / 'summary.json').write_text(json.dumps(final, indent=2) + '\n')
    print(json.dumps(final, ensure_ascii=False))
except BaseException as error:
    write({'stage': 'experiment', 'status': 'FAILED', 'error': type(error).__name__ + ': ' + str(error)})
    raise
finally:
    log.close()
