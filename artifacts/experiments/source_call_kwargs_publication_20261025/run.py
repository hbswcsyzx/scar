"""Single formal three-ADD publication gate. Root owns the actual session."""
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
from prepare import canonical, receipt

STARTED = time.perf_counter()

def save(name, value):
    path = HERE / name
    path.parent.mkdir(parents=True, exist_ok=True)
    with path.open('xb') as stream:
        stream.write(canonical(value) + b'\n')

def verify_freeze(freeze):
    for category in ('sources', 'runtime', 'inputs', 'entry'):
        for row in freeze[category]:
            if receipt(row['path']) != row:
                raise ValueError('frozen ' + category + ' changed: ' + row['path'])
    runtime = {'version': sys.version, 'executable': str(Path(sys.executable).resolve()),
        'magic': importlib.util.MAGIC_NUMBER.hex(), 'marshal_version': marshal.version}
    if runtime != freeze['runtime_identity']:
        raise ValueError('frozen Python runtime identity differs')

def main():
    # Exclusive entry refuses a second attempt even after a failed run.
    with (HERE / 'run-started.json').open('xb') as stream:
        stream.write(canonical({'freeze': receipt(HERE / 'freeze.json'), 'started_unix_s': time.time()}) + b'\n')
    config = json.loads((HERE / 'inputs.json').read_text())
    freeze = json.loads((HERE / 'freeze.json').read_text())
    budgets = config['budgets']
    progress_stream = (HERE / 'progress.jsonl').open('x', buffering=1)
    def progress(row):
        progress_stream.write(json.dumps({'elapsed_s': time.perf_counter() - STARTED,
            'max_rss_kib': resource.getrusage(resource.RUSAGE_SELF).ru_maxrss, **row}) + '\n')
    def expired(*_):
        raise TimeoutError('single publication gate wall ceiling exceeded')
    signal.signal(signal.SIGALRM, expired)
    signal.setitimer(signal.ITIMER_REAL, budgets['max_wall_seconds'])
    try:
        progress({'stage': 'FROZEN_INPUTS', 'status': 'BEGIN'})
        verify_freeze(freeze)
        save('before-freeze-check.json', {'status': 'PASS', 'freeze': receipt(HERE / 'freeze.json')})
        from scar.analysis.code_witness import CodeWitnessBudget, CodeWitnessStore
        from scar.analysis.inventory_partitions import InventoryPartitions, _read_receipt
        from scar.analysis.program_composition import CompositionIndex, compose_source_publication
        from scar.analysis.source_language import SourceCodeEvidence, SourceLanguageOptions
        from scar.analysis.source_program_publication import (
            plan_source_body_publication, publish_source_body_revisions, validate_body_revision_publication)
        from scar.ir.program.call_edges import CapturedCode
        from scar.ir.program.source_language import SourceLanguageCapability
        from scar.ir.record_codec import decode, encode
        from scar.ir.semantics_v2 import SourceSnapshot

        parent = CompositionIndex(config['parent_composition'],
            max_input_bytes=budgets['max_composition_input_bytes'], max_record_bytes=budgets['max_record_bytes'])
        if parent.original_code_source_origin() != freeze['original_code_source_origin']:
            raise ValueError('strict original compiler/source origin differs')
        store = CodeWitnessStore(config['readonly_code_witnesses'], budget=CodeWitnessBudget(max_compile_keys=20))
        programs = tuple(row['program']['path'] for row in config['programs'])
        plan = plan_source_body_publication(parent, programs, max_programs=budgets['max_programs'],
            max_record_bytes=budgets['max_record_bytes'])
        frozen_plan = json.loads((HERE / 'plan.json').read_text())
        if {'sha256': plan.sha256, 'document': plan.document} != frozen_plan:
            raise ValueError('current exact-parent ADD plan changed since preflight')
        if any(row['operation'] != 'ADD_GRAPH' for row in plan.document['expectations']):
            raise ValueError('this gate admits only the three ordinary additions')
        # One bounded pass over each saved graph records independent decoded
        # receipts and keeps only metadata; no lowering or checkpoint resume.
        metadata = []
        for row in config['programs']:
            document, actual = _read_receipt(row['program']['path'], limit=budgets['max_record_bytes'])
            for key in ('decoded_sha256', 'decoded_bytes'):
                if actual[key] != row['program'][key]:
                    raise ValueError('original SourceProgram decoded receipt differs')
            if document['language']['capabilities'] != config['exact_capabilities']:
                raise ValueError('input graph capability declarations differ')
            metadata.append({'snapshot': document['metadata']['source'],
                'captured': document['language']['code_evidence']['captured'],
                'capabilities': document['language']['capabilities']})
            del document
        save('producer.json', {'schema': 'scar.kwargs-publication-producer', 'schema_version': 1,
            'freeze': receipt(HERE / 'freeze.json'), 'original_graphs_and_producers': config['programs'],
            'parent_composition': parent.index_receipt, 'original_code_source_origin': parent.original_code_source_origin(),
            'code_witness_archive': store.receipt(), 'budgets': budgets,
            'raw_reads': 0, 'source_lowered': 0, 'source_prepared': 0, 'compiled': 0, 'target_executed': 0,
            'new_reader_is_not_original_graph_producer': True})
        retained = config['retained_unpublished_subject']
        retained_before = parent.inventory_file(retained['file_index'])['bodies'][retained['body_index']]
        progress({'stage': 'PUBLICATION', 'status': 'BEGIN'})
        publication = publish_source_body_revisions(parent, plan, HERE / 'result/publication', code_witnesses=store,
            max_programs=budgets['max_programs'], max_changed_sources=budgets['max_changed_sources'],
            max_operations_per_body=budgets['max_operations_per_body'],
            max_record_bytes=budgets['max_record_bytes'], progress=progress)
        save('publication-result.json', publication)
        progress({'stage': 'COMPOSE', 'status': 'BEGIN'})
        composed = compose_source_publication(parent, publication['manifest'], HERE / 'result/composition',
            max_record_bytes=budgets['max_record_bytes'], max_output_bytes=budgets['max_composition_output_bytes'],
            progress=progress)
        save('compose-result.json', composed)
        progress({'stage': 'PUBLIC_READER', 'status': 'BEGIN'})
        index = CompositionIndex(HERE / 'result/composition/index.json.gz',
            max_input_bytes=budgets['max_composition_input_bytes'], max_record_bytes=budgets['max_record_bytes'])
        inventory = InventoryPartitions(publication['manifest'], max_shard_bytes=budgets['max_record_bytes'])
        lineage = validate_body_revision_publication(parent, inventory, max_programs=budgets['max_programs'])
        checked = []
        for expected, original, meta in zip(plan.document['expectations'], config['programs'], metadata):
            fi, bi = expected['file_index'], expected['body_index']
            progress({'stage': 'PUBLIC_READER_BODY', 'file_index': fi, 'body_index': bi, 'status': 'BEGIN'})
            captured = decode(CapturedCode, meta['captured'])
            snapshot = decode(SourceSnapshot, meta['snapshot'])
            evidence = SourceCodeEvidence(store, index, captured)
            if evidence.source_link.snapshot != snapshot or index.original_code_source_origin() != freeze['original_code_source_origin']:
                raise ValueError('new body witness source/origin differs from the original')
            text = store.text(snapshot)
            options = SourceLanguageOptions(tuple(SourceLanguageCapability(value) for value in meta['capabilities']), evidence)
            body = inventory.typed_body(fi, bi, language_options=options,
                source_tree=ast.parse(text, filename=snapshot.path), source_texts={snapshot.path: text})
            if not all((body.public_graph_validated, body.public_language_structure_validated,
                        body.source_shape_verified, body.source_code_witness_verified)):
                raise ValueError('ordinary public structure/AST/CodeWitness admission failed')
            if len(body.body.graph.operations) != original['operations']:
                raise ValueError('observed graph operation count differs from original artifact receipt')
            checkpoint = inventory.checkpoint(inventory.file(fi)['bodies'][bi]['checkpoint'])
            if checkpoint['source_program'] != expected['replacement']:
                raise ValueError('publication changed original graph logical URI or byte identity')
            checked.append({'file_index': fi, 'body_index': bi, 'operation': expected['operation'],
                'definition': encode(body.body.definition), 'namespace': body.namespace,
                'locators': body.locators, 'operations_observed': len(body.body.graph.operations),
                'values_observed': len(body.body.graph.values), 'source_program': checkpoint['source_program'],
                'public_structure_ast_code_witness_passed': True, 'current_run_integrated': False})
            progress({'stage': 'PUBLIC_READER_BODY', 'file_index': fi, 'body_index': bi, 'status': 'PASS'})
        if inventory.file(retained['file_index'])['bodies'][retained['body_index']] != retained_before:
            raise ValueError('unpublished JoinedStr subject was changed')
        if len(index.document['files']) != 151 or sum(len(row['bodies']) for row in index.document['files']) != 2217:
            raise ValueError('definition/file denominator changed')
        if store.counts['compile_attempts'] or store.writable or store.compile_missing:
            raise ValueError('read-only witness policy violated')
        verify_freeze(freeze)
        participants = []
        frozen_sources = {row['path']: row for row in freeze['sources']}
        frozen_runtime = {row['path']: row for row in freeze['runtime']}
        for module in tuple(sys.modules.values()):
            filename = getattr(module, '__file__', None)
            if not filename:
                continue
            path = Path(filename).resolve()
            if path.is_file() and path.is_relative_to(ROOT / 'scar'):
                row = receipt(path)
                if frozen_sources.get(str(path)) != row:
                    raise ValueError('participating SCAR module not frozen')
                if row not in participants:
                    participants.append(row)
            elif path.is_file() and not path.is_relative_to(ROOT):
                row = receipt(path)
                if frozen_runtime.get(str(path)) != row:
                    raise ValueError('participating runtime module not frozen: ' + str(path))
        save('participating-producer.json', {'sources': participants, 'all_source_and_runtime_bytes_unchanged': True})
        save('after-freeze-check.json', {'status': 'PASS', 'freeze': receipt(HERE / 'freeze.json')})
        result = {'status': 'PASS_WITH_OPEN', 'lineage': lineage, 'active_bodies': checked,
            'manifest_counts': inventory.manifest['counts'], 'header_summary': inventory.component('header')['summary'],
            'publication_header': index.publication_header(), 'parent_composition': parent.index_receipt,
            'composition': receipt(HERE / 'result/composition/index.json.gz'),
            'manifest': receipt(publication['manifest']), 'source_files': len(index.document['files']),
            'definition_denominator': sum(len(row['bodies']) for row in index.document['files']),
            'unpublished_subject_unchanged': True, 'retained_unsupported_attempt': config['retained_unsupported_attempt'],
            'code_witness_counts': dict(store.counts), 'strict_original_code_source_origin_preserved': True,
            'raw_reads': 0, 'source_lowered': 0, 'source_prepared': 0, 'compiled': 0, 'target_executed': 0,
            'current_run_integrated': False, 'whole_program_established': False,
            'elapsed_s': time.perf_counter() - STARTED,
            'max_rss_kib': resource.getrusage(resource.RUSAGE_SELF).ru_maxrss}
        save('result.json', result)
        progress({'stage': 'FINISHED', 'status': result['status']})
        print(json.dumps({'status': result['status'], 'manifest_counts': result['manifest_counts'], 'elapsed_s': result['elapsed_s']}))
    except BaseException as error:
        save('failure.json', {'type': type(error).__name__, 'detail': str(error), 'traceback': traceback.format_exc(),
            'elapsed_s': time.perf_counter() - STARTED, 'partial_outputs_retained': True,
            'rerun_authorized': False})
        progress({'stage': 'FAILED', 'type': type(error).__name__, 'detail': str(error)})
        raise
    finally:
        signal.setitimer(signal.ITIMER_REAL, 0)
        progress_stream.close()

if __name__ == '__main__':
    main()
