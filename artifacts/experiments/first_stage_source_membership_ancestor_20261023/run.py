"""ONE actual ancestor query/cache/wrong-ancestor gate, without any raw read."""
from hashlib import sha256
import json
import os
from pathlib import Path
import resource
import signal
import subprocess
import sys
import time
import traceback

HERE = Path(__file__).resolve().parent
ROOT = HERE.parents[2]
sys.path.insert(0, str(ROOT))
STARTED = time.perf_counter()
log = (HERE / 'progress.jsonl').open('x', buffering=1)
def receipt(path):
    path = Path(path).resolve(); raw = path.read_bytes()
    return {'path': str(path), 'sha256': sha256(raw).hexdigest(), 'bytes': len(raw)}
def save(name, value):
    with (HERE / name).open('x') as stream:
        json.dump(value, stream, indent=2); stream.write('\n')
def progress(stage, **fields):
    log.write(json.dumps({'stage': stage, 'elapsed_s': time.perf_counter() - STARTED,
        'max_rss_kib': resource.getrusage(resource.RUSAGE_SELF).ru_maxrss, **fields}) + '\n')
def expired(signum, frame):
    raise TimeoutError('independent dry ancestor gate exceeded wall180s')
signal.signal(signal.SIGALRM, expired); signal.setitimer(signal.ITIMER_REAL, 180)
try:
    candidates = {str(path.resolve()): receipt(path) for path in (ROOT / 'scar').rglob('*.py')}
    save('candidate-source-hashes.json', list(candidates.values()))
    freeze = json.loads((HERE / 'freeze.json').read_text())
    for row in freeze['modules']:
        if receipt(ROOT / row['path'])['sha256'] != row['sha256']:
            raise ValueError('frozen ancestor producer differs')
    from scar.analysis.program_composition import CompositionIndex
    index_path = HERE.parent / 'first_stage_source_body_revision_20261023/result/composition/index.json.gz'
    report_path = HERE.parent / 'first_stage_current_source_gate_20261023/result/source/report.json'
    report = json.loads(report_path.read_text())
    save('producer.json', {'head_at_start': subprocess.check_output(['git', 'rev-parse', 'HEAD'], cwd=ROOT, text=True).strip(),
        'pid': os.getpid(), 'runner': receipt(__file__), 'freeze': receipt(HERE / 'freeze.json'),
        'current_composition': receipt(index_path), 'original_source_report': receipt(report_path),
        'max_depth': 16, 'max_total_decoded_bytes': 1_000_000_000,
        'source_report_is_navigation_input_not_new_dynamic_proof': True,
        'raw_trace_read': False, 'private_source_proof_factory_called': False,
        'target_executed': False, 'compile_performed': False, 'source_prepared': False})
    progress('COMPOSITION_LOAD_BEGIN')
    composition = CompositionIndex(index_path)
    progress('COMPOSITION_LOAD_END')
    if composition.original_code_source_origin()['inventory'] != report['inventory']:
        raise ValueError('original compiler inventory differs from original source report')
    progress('ANCESTOR_QUERY_BEGIN')
    ancestor = composition.require_source_membership_ancestor(report['composition_canonical_sha256'],
        report['inventory'], max_depth=16, max_total_decoded_bytes=1_000_000_000)
    counts = composition.source_membership_query_counts()
    save('ancestor.json', ancestor); progress('ANCESTOR_QUERY_END', counts=counts, depth=ancestor['depth'])
    again = composition.require_source_membership_ancestor(report['composition_canonical_sha256'], report['inventory'])
    if again != ancestor or composition.source_membership_query_counts() != counts:
        raise ValueError('same-input ancestor query failed exact small-receipt reuse')
    save('same-input-cache.json', {'identical_receipt': True, 'before': counts,
                                  'after': composition.source_membership_query_counts()})
    try:
        composition.require_source_membership_ancestor('0' * 64, report['inventory'])
    except ValueError as error:
        if 'requested ancestor is not in the bounded exact source chain' not in str(error):
            raise
        save('wrong-ancestor-rejected.json', {'type': type(error).__name__, 'detail': str(error),
            'before': counts, 'after': composition.source_membership_query_counts(),
            'new_parent_indexes_parsed': composition.source_membership_query_counts()['parent_compositions']
                - counts['parent_compositions']})
    else:
        raise ValueError('an unrepresented ancestor canonical SHA was accepted')
    participants = []
    archive = HERE / 'participating-source-evidence'; archive.mkdir()
    for module in tuple(sys.modules.values()):
        filename = getattr(module, '__file__', None)
        if filename:
            path = Path(filename).resolve()
            if path.is_relative_to(ROOT / 'scar') and path.suffix == '.py':
                row = receipt(path)
                if candidates.get(str(path)) != row:
                    raise ValueError('actual ancestor-query imported source drifted: ' + str(path))
                if row not in participants:
                    participants.append(row); (archive / (row['sha256'] + '.py-source')).write_bytes(path.read_bytes())
    save('participating-producer.json', {'modules': participants, 'all_bytes_unchanged': True,
                                       'unused_candidates_are_not_guards': True})
    summary = {'status': 'PASS_WITH_OPEN', 'depth': ancestor['depth'],
        'owned_ancestor_reader_counts': composition.source_membership_query_counts(),
        'same_query_no_parent_reads': True, 'wrong_ancestor_rejected': True,
        'original_compiler_inventory_strict_equality_preserved': True,
        'raw_trace_read': False, 'private_source_proof_factory_called': False,
        'new_dynamic_body_refs_or_activations_created': False, 'source_prepared': False,
        'code_compiled': False, 'target_executed': False, 'whole_program_established': False,
        'elapsed_s': time.perf_counter() - STARTED,
        'max_rss_kib': resource.getrusage(resource.RUSAGE_SELF).ru_maxrss}
    save('summary.json', summary); progress('FINISHED', status=summary['status'])
    print(json.dumps(summary))
except BaseException as error:
    save('failure.json', {'type': type(error).__name__, 'detail': str(error), 'traceback': traceback.format_exc(),
        'elapsed_s': time.perf_counter() - STARTED, 'partial_outputs_retained': True})
    progress('FAILED', type=type(error).__name__, detail=str(error)); raise
finally:
    signal.setitimer(signal.ITIMER_REAL, 0); log.close()
