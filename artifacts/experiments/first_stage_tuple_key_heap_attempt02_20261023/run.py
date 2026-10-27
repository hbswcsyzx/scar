"""ONE fresh attempt for the prior exact failed body, with two port fixes."""
import ast
from hashlib import sha256
import gzip
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
EXPERIMENTS = HERE.parent
sys.path.insert(0, str(ROOT))
STARTED = time.perf_counter()
log = (HERE / 'progress.jsonl').open('x', buffering=1)
def receipt(path):
    path = Path(path).resolve(); raw = path.read_bytes()
    return {'path': str(path), 'sha256': sha256(raw).hexdigest(), 'bytes': len(raw)}
def save(name, document, zipped=False):
    raw = json.dumps(document, sort_keys=True, ensure_ascii=False, separators=(',', ':'), allow_nan=False).encode() + b'\n'
    if len(raw) > 64_000_000:
        raise ValueError('independent64MB record ceiling exceeded')
    path = HERE / name
    with path.open('xb') as stream:
        stream.write(gzip.compress(raw, mtime=0) if zipped else raw)
    return {**receipt(path), 'decoded_sha256': sha256(raw).hexdigest(), 'decoded_bytes': len(raw)}
def progress(stage, **fields):
    log.write(json.dumps({'stage': stage, 'elapsed_s': time.perf_counter() - STARTED,
        'max_rss_kib': resource.getrusage(resource.RUSAGE_SELF).ru_maxrss, **fields}) + '\n')
def expired(signum, frame):
    raise TimeoutError('independent one-body source attempt exceeded wall180s')
signal.signal(signal.SIGALRM, expired); signal.setitimer(signal.ITIMER_REAL, 180)

try:
    candidates = {str(path.resolve()): receipt(path) for path in (ROOT / 'scar').rglob('*.py')}
    save('candidate-source-hashes.json', list(candidates.values()))
    heap = json.loads((HERE / 'application.json').read_text())
    if receipt(heap['module'])['sha256'] != heap['sha256']:
        raise ValueError('applied narrow heap producer differs')
    triple = json.loads((EXPERIMENTS / 'first_stage_tuple_key_applied_20261023/application.json').read_text())
    for row in triple['modules']:
        if receipt(ROOT / row['path'])['sha256'] != row['sha256']:
            raise ValueError('frozen tuple producer differs')
    from scar.analysis.code_witness import CodeWitnessStore, CodeWitnessBudget
    from scar.analysis.program_composition import CompositionIndex
    from scar.analysis.program_lowering import PreparedSource, SourceProgram, _symbol_tables
    from scar.analysis.source_language import SourceCodeEvidence, SourceLanguageOptions
    from scar.analysis.source_language_validation import validate_language_body
    from scar.analysis.source_tuple_validation import validate_tuple_key_ownership
    from scar.analysis.structured_lowering import require_valid_structured_body
    from scar.ir.program.call_edges import CapturedCode
    from scar.ir.program.functions import BodyLoweringProfile
    from scar.ir.program.inventory import DefinitionInventory
    from scar.ir.record_codec import decode, encode
    from scar.ir.v2.semantic import OperationKind

    parent = EXPERIMENTS / 'first_stage_tuple_key_bodies_20261023'
    parent_summary = json.loads((parent / 'summary.json').read_text())
    failed = [row for row in parent_summary['results'] if row['status'] == 'FAILED_RETAINED']
    selection = json.loads((parent / 'selection.json').read_text())['records']
    if len(failed) != 1:
        raise ValueError('parent gate has no unique exact failed input')
    item, = [row for row in selection if row['definition'] == failed[0]['definition'] and row['source'] == failed[0]['source']]
    comp_path = EXPERIMENTS / 'first_stage_source_publication_current_20261023/result/composition/index.json.gz'
    composition = CompositionIndex(comp_path)
    fi, = [i for i, row in enumerate(composition.document['files']) if row['snapshot'] == item['snapshot']]
    definition, = [row for row in decode(tuple[DefinitionInventory, ...], composition.inventory_file(fi)['definitions'])
                   if encode(row.id) == item['definition'] and encode(row.source) == item['source']]
    view = composition.source(fi)
    if encode(view.context) != item['context']:
        raise ValueError('original exact source context differs')
    store_path = EXPERIMENTS / 'first_stage_partitioned_operand_routes_20261023/result/code-witnesses'
    old_before = [receipt(path) for path in sorted(store_path.iterdir()) if path.is_file()]
    save('old-store-before.json', old_before)
    store = CodeWitnessStore(store_path, budget=CodeWitnessBudget(max_compile_keys=20))
    evidence = SourceCodeEvidence(store, composition, decode(CapturedCode, item['captured']))
    evidence.require_definition(view.snapshot, definition.id, definition.source)
    text = store.text(view.snapshot)
    if 'sha256:' + sha256(text.encode()).hexdigest() != view.snapshot.fingerprint:
        raise ValueError('owned exact archived source differs')
    tree = ast.parse(text, filename=view.snapshot.path)
    span = item['selection_proof']['tuple_source']
    node, = [node for node in ast.walk(tree) if isinstance(node, ast.Tuple)
             and (node.lineno, node.end_lineno, node.col_offset, node.end_col_offset)
             == (span['start_line'], span['end_line'], span['start_column'], span['end_column'])]
    parents = {child: parent for parent in ast.walk(tree) for child in ast.iter_child_nodes(parent)}
    if not isinstance(parents[node], ast.Subscript) or parents[node].slice is not node:
        raise ValueError('source candidate is not the exact original Tuple key')
    atom = span['atom_id']['wire']
    sg = [row for row in view.semantic.definitions.values() if row.code_id == atom
          and any(source.wire == atom for source in row.source_atoms) and row.kind is OperationKind.OPERATOR
          and row.metadata.get('ast_type') == 'Tuple' and len(row.output_slots) == 1]
    if len(sg) != 1 or any(row.source.atom_id.wire == atom for row in view.semantics.operations.values()):
        raise ValueError('original unique SG-only Tuple proof no longer holds')
    def audit_exec(event, arguments):
        if event == 'exec' and arguments and getattr(arguments[0], 'co_filename', None) == view.snapshot.path:
            raise RuntimeError('target code execution is prohibited')
    sys.addaudithook(audit_exec)
    context = PreparedSource(Path(view.snapshot.path), Path(view.context.namespace_root), text,
        view.semantic, view.semantics, view.control, tree, _symbol_tables(text, view.snapshot.path))
    session = context.seal_for_lowering(); options = SourceLanguageOptions(code_evidence=evidence)
    save('producer.json', {'head_at_start': subprocess.check_output(['git', 'rev-parse', 'HEAD'], cwd=ROOT, text=True).strip(),
        'pid': os.getpid(), 'runner': receipt(__file__), 'heap_application': receipt(HERE / 'application.json'),
        'triple_application': receipt(EXPERIMENTS / 'first_stage_tuple_key_applied_20261023/application.json'),
        'parent_summary': receipt(parent / 'summary.json'), 'parent_selection': receipt(parent / 'selection.json'),
        'composition': receipt(comp_path), 'owned_store': store.receipt(), 'max_bodies': 1, 'max_source_files': 1,
        'max_operations': 4000, 'max_wall_seconds': 180, 'source_prepare': 0, 'compile': 0, 'target_executed': False})
    save('input.json', {'original_request': item, 'independent_source_code': evidence.to_dict(),
                       'source_archive': encode(view.artifact_locator)})
    progress('LOWER_BEGIN')
    result = session.lower(definition.qualname, source=definition.source, max_operations=4000,
        expand_candidates=False, profile=BodyLoweringProfile.STRUCTURED_ENV, language_options=options)
    save('returned.json', {'metadata': encode(result.metadata), 'interface': encode(result.interface),
        'structured': encode(result.structured), 'language': encode(result.language),
        'operations_emitted': result.operations_emitted, 'graph_present': result.graph is not None})
    checks, artifact = {}, None
    if result.graph is not None:
        program = SourceProgram(result.graph, result.metadata, context.semantic, context.semantics, context.control,
            BodyLoweringProfile.STRUCTURED_ENV, result.interface, result.frame, result.structured, result.language)
        artifact = save('source-program5.json.gz', program.to_dict(), zipped=True)
        document = json.loads(gzip.decompress(Path(artifact['path']).read_bytes()))
        loaded = SourceProgram.read_structure(document, max_operations=4000)
        if loaded.to_dict() != document:
            raise ValueError('public stored structure roundtrip differs')
        require_valid_structured_body(loaded.structured, loaded.graph, loaded.interface, loaded.metadata,
            semantic=loaded.semantic, control=loaded.control, language=loaded.language,
            source_tree=tree, language_options=options)
        checks = validate_language_body(loaded.structured, loaded.graph, loaded.interface, loaded.metadata,
            loaded.semantic, loaded.language, source_tree=tree, options=options)
    after = [receipt(path) for path in sorted(store_path.iterdir()) if path.is_file()]
    save('old-store-after.json', after)
    if after != old_before or store.counts['compile_attempts'] or store.counts['source_bytes_read']:
        raise ValueError('read-only archive changed or source/compile ceiling violated')
    participants = []
    archive = HERE / 'participating-source-evidence'; archive.mkdir()
    for module in tuple(sys.modules.values()):
        filename = getattr(module, '__file__', None)
        if filename:
            path = Path(filename).resolve()
            if path.is_relative_to(ROOT / 'scar') and path.suffix == '.py':
                current = receipt(path)
                if current != candidates.get(str(path)):
                    raise ValueError('actual participating source drifted: ' + str(path))
                if current not in participants:
                    participants.append(current)
                    (archive / (current['sha256'] + '.py-source')).write_bytes(path.read_bytes())
    save('participating-producer.json', {'sources': participants, 'all_participating_bytes_unchanged': True,
                                       'unused_candidates_not_guards': True})
    summary = {'status': 'RECOVERED_WITH_OPEN' if result.graph is not None else 'UNSUPPORTED',
        'operations_emitted': result.operations_emitted,
        'graph_operations': len(result.graph.operations) if result.graph is not None else None,
        'artifact': artifact, 'checks': checks, 'gaps': encode(result.metadata.gaps),
        'source_files': 1, 'ast_parses': 1, 'symtable_parses': 1, 'source_prepare': 0,
        'code_witness_counts': dict(store.counts), 'old_archive_unchanged': True,
        'previous_successful_body_lowered_again': False, 'whole_lifetime_verified': False,
        'publication_performed': False, 'current_run_integrated': False,
        'target_executed': False, 'whole_program_established': False,
        'elapsed_s': time.perf_counter() - STARTED, 'max_rss_kib': resource.getrusage(resource.RUSAGE_SELF).ru_maxrss}
    save('summary.json', summary); progress('FINISHED', status=summary['status'])
    print(json.dumps({key: summary[key] for key in ('status', 'operations_emitted', 'graph_operations', 'elapsed_s')}))
except BaseException as error:
    save('failure.json', {'type': type(error).__name__, 'detail': str(error), 'traceback': traceback.format_exc(),
        'elapsed_s': time.perf_counter() - STARTED, 'partial_outputs_retained': True})
    progress('FAILED', type=type(error).__name__, detail=str(error)); raise
finally:
    signal.setitimer(signal.ITIMER_REAL, 0); log.close()
