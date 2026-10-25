"""Bounded existing-artifact preflight and freeze; never publish or lower."""
import ast
from hashlib import sha256
import importlib.util
import json
import marshal
from pathlib import Path
import resource
import signal
import sys
import time
import traceback

HERE = Path(__file__).resolve().parent
ROOT = HERE.parents[2]
sys.path.insert(0, str(ROOT))

def canonical(value):
    return json.dumps(value, sort_keys=True, ensure_ascii=False, separators=(',', ':'), allow_nan=False).encode()

def save(name, value):
    with (HERE / name).open('xb') as stream:
        stream.write(canonical(value) + b'\n')

def receipt(path):
    path = Path(path).resolve()
    if not path.is_file():
        raise ValueError('missing regular input: ' + str(path))
    raw = path.read_bytes()
    return {'path': str(path), 'sha256': sha256(raw).hexdigest(), 'bytes': len(raw)}

def main():
    started = time.perf_counter()
    def expired(*_):
        raise TimeoutError('preflight wall180s ceiling exceeded')
    signal.signal(signal.SIGALRM, expired)
    signal.setitimer(signal.ITIMER_REAL, 180)
    from scar.analysis.code_witness import CodeWitnessBudget, CodeWitnessStore
    from scar.analysis.inventory_partitions import _read_receipt
    from scar.analysis.program_composition import CompositionIndex
    from scar.analysis.program_lowering import SourceProgram
    from scar.analysis.source_program_publication import plan_source_body_publication
    from scar.ir.record_codec import decode
    from scar.ir.semantics_v2 import SourceSnapshot

    original = Path('/home/zyf/AAA/scar-worktrees/source-call-model/artifacts/experiments/source_call_kwargs_bodies_20261025/candidate04/postflight01/receipt.json')
    old = json.loads(original.read_text())
    programs = old['finite_artifacts']
    if [row['operations'] for row in programs] != [92, 85, 217] or old['full_scope_subject_count'] != 4:
        raise ValueError('original finite artifact receipt differs')
    inputs = [receipt(original)]
    for row in programs:
        actual = receipt(row['program']['path'])
        if any(actual[key] != row['program'][key] for key in ('path', 'sha256', 'bytes')):
            raise ValueError('original immutable graph stored bytes differ')
        inputs.append(actual)
    parent_path = HERE.parent / 'first_stage_source_body_revision_20261023/result/composition/index.json.gz'
    store_path = HERE.parent / 'first_stage_partitioned_operand_routes_20261023/result/code-witnesses'
    parent = CompositionIndex(parent_path, max_record_bytes=64_000_000)
    plan = plan_source_body_publication(parent, tuple(row['program']['path'] for row in programs),
        max_programs=3, max_record_bytes=64_000_000)
    if len(plan.document['expectations']) != 3 or any(row['operation'] != 'ADD_GRAPH' for row in plan.document['expectations']):
        raise ValueError('three exact additions to the current parent required')
    if len(parent.document['files']) != 151 or sum(len(row['bodies']) for row in parent.document['files']) != 2217:
        raise ValueError('original definition/file denominator differs')
    subjects = {row['original_sequence']: row for row in old['full_scope_subjects']}
    for artifact, expected in zip(programs, plan.document['expectations']):
        subject = subjects[artifact['sequence']]
        if (subject['file_index'], subject['body_index']) != (expected['file_index'], expected['body_index']):
            raise ValueError('receipt subject does not identify the planned original body')
    store = CodeWitnessStore(store_path, budget=CodeWitnessBudget(max_compile_keys=20))
    document, graph_receipt = _read_receipt(programs[0]['program']['path'], limit=64_000_000)
    for key in ('decoded_sha256', 'decoded_bytes'):
        if graph_receipt[key] != programs[0]['program'][key]:
            raise ValueError('one existing artifact decoded receipt differs')
    snapshot = decode(SourceSnapshot, document['metadata']['source'])
    text = store.text(snapshot)
    checked = SourceProgram.read_structure(document, max_operations=512, source_texts={snapshot.path: text})
    if len(checked.graph.operations) != programs[0]['operations']:
        raise ValueError('existing artifact operation denominator differs')
    # Use the exact archived declaration below; never replace it with defaults.
    capabilities = list(document['language']['capabilities'])
    if len(capabilities) != 4 or 'PYTHON_CALL_KWARGS_314_V1' not in capabilities:
        raise ValueError('existing graph does not explicitly declare the four-capability profile')
    if store.counts['compile_attempts'] or store.writable or store.compile_missing:
        raise ValueError('preflight must not compile or mutate the witness store')
    save('plan.json', {'sha256': plan.sha256, 'document': plan.document})
    config = {'schema': 'scar.kwargs-source-publication-gate-inputs', 'schema_version': 1,
        'parent_composition': str(parent_path.resolve()), 'readonly_code_witnesses': str(store_path.resolve()),
        'original_postflight': str(original), 'programs': programs,
        'retained_unpublished_subject': subjects[5], 'retained_unsupported_attempt': old['seq5'],
        'exact_capabilities': capabilities,
        'budgets': {'max_programs': 3, 'max_changed_sources': 3, 'max_operations_per_body': 512,
            'max_record_bytes': 64_000_000, 'max_composition_input_bytes': 512_000_000,
            'max_composition_output_bytes': 256_000_000, 'max_wall_seconds': 300,
            'preflight_max_wall_seconds': 180},
        'no_lowering': True, 'no_compile': True, 'no_target': True, 'no_raw': True,
        'current_run_integrated': False, 'whole_program_established': False}
    save('inputs.json', config)
    inputs += [receipt(parent_path), receipt(parent.document['inventory']['path'])]
    inputs += [receipt(path) for path in sorted(store_path.iterdir()) if path.is_file()]
    inputs += [receipt(row['evidence']['path']) for row in programs if 'evidence' in row]
    inputs += [receipt(old['seq5']['evidence']['path'])]
    sources = [receipt(path) for path in sorted((ROOT / 'scar').rglob('*.py'))]
    runtime_paths = {Path(sys.executable).resolve()}
    for module in tuple(sys.modules.values()):
        filename = getattr(module, '__file__', None)
        if filename:
            path = Path(filename).resolve()
            if path.is_file() and not path.is_relative_to(ROOT):
                runtime_paths.add(path)
    runtimes = [receipt(path) for path in sorted(runtime_paths)]
    snapshot_dir = HERE / 'source-snapshot'; snapshot_dir.mkdir()
    for row in sources:
        path = snapshot_dir / (row['sha256'] + '.py-source')
        if not path.exists():
            path.write_bytes(Path(row['path']).read_bytes())
    frozen = {'schema': 'scar.kwargs-source-publication-freeze', 'schema_version': 1,
        'head_label_supplied_by_root': '48d2c691', 'head_label_is_not_source_byte_proof': True,
        'sources': sources, 'runtime': runtimes, 'inputs': inputs,
        'entry': [receipt(HERE / name) for name in ('run.py', 'prepare.py', 'README.md', 'inputs.json', 'plan.json')],
        'runtime_identity': {'version': sys.version, 'executable': str(Path(sys.executable).resolve()),
            'magic': importlib.util.MAGIC_NUMBER.hex(), 'marshal_version': marshal.version},
        'original_code_source_origin': parent.original_code_source_origin(),
        'source_snapshot_is_new_reader_not_original_graph_producer': True,
        'original_graph_producer_receipts_remain_original': True,
        'actual_publication_started': False}
    save('freeze.json', frozen)
    save('preflight.json', {'status': 'READY_FOR_ROOT_REVIEW', 'plan_sha256': plan.sha256,
        'operations': [row['operation'] for row in plan.document['expectations']],
        'subjects': [{'file_index': row['file_index'], 'body_index': row['body_index']} for row in plan.document['expectations']],
        'parent_counts': parent.inventory.manifest['counts'],
        'one_existing_artifact_structure_checked': receipt(programs[0]['program']['path']),
        'one_graph_operations_observed': len(checked.graph.operations),
        'exact_capabilities': capabilities, 'code_witness_counts': dict(store.counts),
        'sources': len(sources), 'runtime_files': len(runtimes),
        'no_formal_publication_performed': True, 'raw_reads': 0, 'compile': 0, 'target': 0,
        'elapsed_s': time.perf_counter() - started,
        'max_rss_kib': resource.getrusage(resource.RUSAGE_SELF).ru_maxrss,
        'freeze': receipt(HERE / 'freeze.json')})
    signal.setitimer(signal.ITIMER_REAL, 0)
    print(json.dumps({'status': 'READY_FOR_ROOT_REVIEW', 'freeze': receipt(HERE / 'freeze.json')}))

if __name__ == '__main__':
    main()
