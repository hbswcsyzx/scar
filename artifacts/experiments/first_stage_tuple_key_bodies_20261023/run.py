"""ONE two-body source repair window; no prepare, compile or target execution."""
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
output_bytes = 0
def canonical(value):
    return json.dumps(value, sort_keys=True, ensure_ascii=False, separators=(',', ':'), allow_nan=False).encode()
def receipt(path):
    path = Path(path).resolve(); raw = path.read_bytes()
    return {'path': str(path), 'sha256': sha256(raw).hexdigest(), 'bytes': len(raw)}
def save(name, document, *, zipped=False):
    global output_bytes
    raw = canonical(document) + b'\n'
    if len(raw) > 64_000_000:
        raise ValueError('independent per-record64MB output ceiling exceeded')
    data = gzip.compress(raw, mtime=0) if zipped else raw
    output_bytes += len(data)
    if output_bytes > 64_000_000:
        raise ValueError('independent total64MB output ceiling exceeded')
    path = HERE / name; path.parent.mkdir(parents=True, exist_ok=True)
    with path.open('xb') as stream:
        stream.write(data)
    return {**receipt(path), 'decoded_sha256': sha256(raw).hexdigest(), 'decoded_bytes': len(raw)}
def progress(stage, **fields):
    log.write(json.dumps({'stage': stage, 'elapsed_s': time.perf_counter() - STARTED,
        'max_rss_kib': resource.getrusage(resource.RUSAGE_SELF).ru_maxrss, **fields}) + '\n')
def expired(signum, frame):
    raise TimeoutError('independent two-body source gate exceeded wall180s')
signal.signal(signal.SIGALRM, expired); signal.setitimer(signal.ITIMER_REAL, 180)

try:
    candidates = {str(path.resolve()): receipt(path) for path in (ROOT / 'scar').rglob('*.py')}
    save('candidate-source-hashes.json', list(candidates.values()))
    applied_path = EXPERIMENTS / 'first_stage_tuple_key_applied_20261023/application.json'
    if not applied_path.exists():
        members = sorted((EXPERIMENTS / 'first_stage_tuple_key_applied_20261023').glob('*.json'))
        if len(members) != 1:
            raise ValueError('applied tuple producer receipt is not unique')
        applied_path, = members
    applied = json.loads(applied_path.read_text())
    for row in applied['modules']:
        if receipt(ROOT / row['path'])['sha256'] != row['sha256']:
            raise ValueError('applied tuple producer drifted')
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
    from scar.ir.program.source import LoweringMetadata
    from scar.ir.program.source_language import SourceLanguageOverlay
    from scar.ir.program.functions import BodyEntryInterface
    from scar.ir.record_codec import decode, encode
    from scar.ir.semantics_v2 import Opcode
    from scar.ir.v2.semantic import OperationKind
    initial_participating = []
    for module in tuple(sys.modules.values()):
        filename = getattr(module, '__file__', None)
        if filename:
            path = Path(filename).resolve()
            if path.is_relative_to(ROOT / 'scar') and path.suffix == '.py':
                current = receipt(path)
                if current not in initial_participating:
                    initial_participating.append(current)
    save('freeze-before.json', {'applied_modules': applied['modules'],
        'initial_actual_imports': initial_participating,
        'unused_candidate_sources_are_not_guards': True})

    automatic = EXPERIMENTS / 'first_stage_source_frontend_automatic_20261023'
    audit_path = automatic / 'exact-ast-frontiers.json'
    audit = json.loads(audit_path.read_text())
    rows = [row for row in audit['rows'] if any(shape['ast_kind'] == 'Tuple'
                                              for shape in row['exact_ast_shapes'])]
    if len(rows) != 1:
        raise ValueError('original twelve source-evidence frontiers have no unique Tuple candidate')
    candidate, = rows
    old_attempts = [json.loads(line) for line in (automatic / 'worker/attempts.jsonl').read_text().splitlines()]
    original = [row for row in old_attempts if row['body_key'] == candidate['body_key']]
    if len(old_attempts) != 12 or len(original) != 1:
        raise ValueError('original full twelve-attempt denominator or body join differs')
    original, = original
    result_receipt = original['result_artifact']
    if receipt(result_receipt['path']) != result_receipt:
        raise ValueError('original terminal body receipt differs')
    saved_terminal = json.loads(Path(result_receipt['path']).read_text())
    if saved_terminal != {key: value for key, value in original.items() if key != 'result_artifact'}:
        raise ValueError('original terminal row differs from checked attempt index')
    old_witness_check = json.loads((EXPERIMENTS / 'first_stage_tuple_key_proposal_20261023/ir-check-final.json').read_text())
    old_artifact = old_witness_check['original_artifact']
    if receipt(old_artifact['path']) != old_artifact:
        raise ValueError('original defective v5 artifact bytes differ')
    old_document = json.loads(gzip.decompress(Path(old_artifact['path']).read_bytes()))
    # Read exact typed source metadata, not a false successful new-validator
    # admission of this already-known defective old graph.
    old_metadata = decode(LoweringMetadata, old_document['metadata'])
    old_interface = decode(BodyEntryInterface, old_document['interface'])
    old_language = decode(SourceLanguageOverlay, old_document['language'])
    old_captured = decode(CapturedCode, old_language.code_evidence['captured'])

    comp_path = EXPERIMENTS / 'first_stage_source_publication_current_20261023/result/composition/index.json.gz'
    composition = CompositionIndex(comp_path)
    store_path = EXPERIMENTS / 'first_stage_partitioned_operand_routes_20261023/result/code-witnesses'
    store = CodeWitnessStore(store_path, budget=CodeWitnessBudget(max_compile_keys=20))
    before_store = [receipt(path) for path in sorted(store_path.iterdir()) if path.is_file()]
    save('old-store-before.json', before_store)
    requested = [
        {'origin': 'AUTOMATIC_SG_ONLY_TUPLE_KEY', 'definition': original['work_input']['definition'],
         'source': original['work_input']['source'], 'snapshot': original['work_input']['snapshot'],
         'captured': original['work_input']['captured'], 'body_key': original['body_key']},
        {'origin': 'ARCHIVED_TUPLE_FAILURE_OWNERSHIP_REPAIR', 'definition': encode(old_interface.definition),
         'source': old_document['structured']['source'],
         'snapshot': encode(old_metadata.source), 'captured': encode(old_captured),
         'original_artifact': old_artifact},
    ]
    if len({row['snapshot']['path'] for row in requested}) != 2:
        raise ValueError('bounded repair input is not two distinct original source files')
    target_paths = {row['snapshot']['path'] for row in requested}
    def audit_exec(event, arguments):
        if event == 'exec' and arguments and getattr(arguments[0], 'co_filename', None) in target_paths:
            raise RuntimeError('target code execution is forbidden in the source repair gate')
    sys.addaudithook(audit_exec)
    selected, contexts = [], {}
    for item in requested:
        file_indices = [i for i, row in enumerate(composition.document['files']) if row['snapshot'] == item['snapshot']]
        if len(file_indices) != 1:
            raise ValueError('source snapshot does not identify one original inventory file')
        fi, = file_indices
        definitions = decode(tuple[DefinitionInventory, ...], composition.inventory_file(fi)['definitions'])
        definitions = [row for row in definitions if encode(row.id) == item['definition'] and encode(row.source) == item['source']]
        if len(definitions) != 1:
            raise ValueError('exact source/definition does not identify one original indexed body')
        definition, = definitions
        view = composition.source(fi)
        text = store.text(view.snapshot)
        if 'sha256:' + sha256(text.encode()).hexdigest() != view.snapshot.fingerprint:
            raise ValueError('owned source text differs from original snapshot')
        tree = ast.parse(text, filename=view.snapshot.path)
        context = PreparedSource(Path(view.snapshot.path), Path(view.context.namespace_root), text,
            view.semantic, view.semantics, view.control, tree, _symbol_tables(text, view.snapshot.path))
        if item['origin'] == 'AUTOMATIC_SG_ONLY_TUPLE_KEY':
            span = candidate['last_frontier']['source']
            nodes = [node for node in ast.walk(tree) if isinstance(node, ast.Tuple)
                and (node.lineno, node.end_lineno, node.col_offset, node.end_col_offset)
                == (span['start_line'], span['end_line'], span['start_column'], span['end_column'])]
            parents = {child: parent for parent in ast.walk(tree) for child in ast.iter_child_nodes(parent)}
            if len(nodes) != 1 or not isinstance(parents.get(nodes[0]), ast.Subscript) or parents[nodes[0]].slice is not nodes[0]:
                raise ValueError('exact original AST Tuple is not its Subscript key')
            atom = span['atom_id']['wire']
            sg = [row for row in view.semantic.definitions.values() if row.code_id == atom
                  and any(source.wire == atom for source in row.source_atoms) and row.output_slots
                  and row.kind is OperationKind.OPERATOR and row.metadata.get('ast_type') == 'Tuple']
            old = [row for row in view.semantics.operations.values() if row.source.atom_id.wire == atom]
            if len(sg) != 1 or len(sg[0].output_slots) != 1 or old:
                raise ValueError('Tuple is not uniquely SG-backed with an absent computational overlay')
            item['selection_proof'] = {'tuple_source': span, 'sg_definition': encode(sg[0].id),
                'sg_output_slot': encode(sg[0].output_slots[0]), 'old_computational_records': 0,
                'original_attempt_denominator': 12, 'name_or_reason_selection_used': False}
        else:
            if (view.semantic.to_dict() != old_document['semantic'] or view.semantics.to_dict() != old_document['semantics']
                    or view.control.to_dict() != old_document['control']):
                raise ValueError('original v5 source layers differ from the reused exact source context')
        evidence = SourceCodeEvidence(store, composition, decode(CapturedCode, item['captured']))
        evidence.require_definition(view.snapshot, definition.id, definition.source)
        item.update(file_index=fi, definition_record=encode(definition), context=encode(view.context),
            source_archive=encode(view.artifact_locator), independently_verified_code=evidence.to_dict())
        selected.append(item); contexts[fi] = (context, context.seal_for_lowering(), definition, evidence)
    producer = {'head_at_start': subprocess.check_output(['git', 'rev-parse', 'HEAD'], cwd=ROOT, text=True).strip(),
        'pid': os.getpid(), 'runner': receipt(__file__), 'applied_producer': receipt(applied_path),
        'composition': receipt(comp_path), 'original_v5': old_artifact,
        'automatic_ast_evidence': receipt(audit_path), 'old_witness_check': receipt(EXPERIMENTS / 'first_stage_tuple_key_proposal_20261023/ir-check-final.json'),
        'store': store.receipt(), 'source_prepare_count': 0, 'target_executed': False}
    save('producer.json', producer); save('selection.json', {'records': selected,
        'max_bodies': 2, 'max_source_files': 2, 'max_operations_per_body': 4000,
        'max_total_operations': 8000, 'max_wall_seconds': 180, 'max_output_bytes': 64_000_000})
    progress('SELECTION_READY', bodies=2, files=2, source_prepare=0, compile=store.counts['compile_attempts'])
    results, charged = [], 0
    for sequence, item in enumerate(selected, 1):
        attempt = f'attempt-{sequence:02d}'
        context, session, definition, evidence = contexts[item['file_index']]
        options = SourceLanguageOptions(code_evidence=evidence)
        save(attempt + '/started.json', item); progress('LOWER_BEGIN', sequence=sequence, origin=item['origin'])
        lowered = None
        try:
            lowered = session.lower(definition.qualname, source=definition.source, max_operations=4000,
                expand_candidates=False, profile=BodyLoweringProfile.STRUCTURED_ENV, language_options=options)
            charged += lowered.operations_emitted
            save(attempt + '/returned.json', {'metadata': encode(lowered.metadata), 'interface': encode(lowered.interface),
                'structured': encode(lowered.structured), 'language': encode(lowered.language),
                'operations_emitted': lowered.operations_emitted, 'graph_present': lowered.graph is not None})
            row = {'sequence': sequence, 'origin': item['origin'], 'definition': encode(definition.id),
                'source': encode(definition.source), 'operations_emitted': lowered.operations_emitted,
                'graph_operations': len(lowered.graph.operations) if lowered.graph is not None else None,
                'gaps': encode(lowered.metadata.gaps), 'status': 'UNSUPPORTED' if lowered.graph is None else 'RECOVERED'}
            if lowered.graph is not None:
                program = SourceProgram(lowered.graph, lowered.metadata, context.semantic, context.semantics,
                    context.control, BodyLoweringProfile.STRUCTURED_ENV, lowered.interface, lowered.frame,
                    lowered.structured, lowered.language)
                artifact = save(attempt + '/source-program5.json.gz', program.to_dict(), zipped=True)
                document = json.loads(gzip.decompress(Path(artifact['path']).read_bytes()))
                loaded = SourceProgram.read_structure(document, max_operations=4000)
                if loaded.to_dict() != document:
                    raise ValueError('public SourceProgram5 structural roundtrip differs')
                require_valid_structured_body(loaded.structured, loaded.graph, loaded.interface, loaded.metadata,
                    semantic=loaded.semantic, control=loaded.control, language=loaded.language,
                    source_tree=context.tree, language_options=options)
                language_check = validate_language_body(loaded.structured, loaded.graph, loaded.interface,
                    loaded.metadata, loaded.semantic, loaded.language, source_tree=context.tree, options=options)
                ownership = validate_tuple_key_ownership(loaded.structured, loaded.graph, loaded.interface,
                    loaded.metadata, loaded.semantic, source_tree=context.tree, options=options)
                row.update(artifact=artifact, public_reader_structure_verified=True,
                    independent_source_and_code_verified=True, source_reprepare_or_full_source_replay=False,
                    language_check=language_check, tuple_ownership=ownership,
                    whole_lifetime_verified=False, runtime_code_instance_established=False)
            save(attempt + '/result.json', row)
        except Exception as error:
            if lowered is None:
                charged += 4000  # reservation only; actual emitted cost is UNKNOWN.
            row = {'sequence': sequence, 'origin': item['origin'], 'status': 'FAILED_RETAINED',
                'definition': encode(definition.id), 'source': encode(definition.source),
                'operations_emitted': lowered.operations_emitted if lowered is not None else None,
                'error': {'type': type(error).__name__, 'detail': str(error), 'traceback': traceback.format_exc()},
                'no_retry': True}
            save(attempt + '/failure.json', row)
        results.append(row); progress('LOWER_END', sequence=sequence, status=row['status'])
        if charged > 8000:
            raise ValueError('independent total operation budget exceeded')
    after_store = [receipt(path) for path in sorted(store_path.iterdir()) if path.is_file()]
    save('old-store-after.json', after_store)
    if before_store != after_store or store.counts['compile_attempts'] != 0 or store.counts['source_bytes_read'] != 0:
        raise ValueError('old owned archive changed or compile/source-read budget violated')
    if receipt(old_artifact['path']) != old_artifact:
        raise ValueError('old defective v5 graph artifact changed')
    participating = []
    for module in tuple(sys.modules.values()):
        filename = getattr(module, '__file__', None)
        if not filename:
            continue
        path = Path(filename).resolve()
        if path.is_relative_to(ROOT / 'scar') and path.suffix == '.py':
            current = receipt(path)
            if candidates.get(str(path)) != current:
                raise ValueError('actual participating source drifted: ' + str(path))
            if current not in participating:
                participating.append(current)
                archive = HERE / 'participating-source-evidence'; archive.mkdir(exist_ok=True)
                (archive / (current['sha256'] + '.py-source')).write_bytes(path.read_bytes())
    save('participating-producer.json', {'sources': participating, 'all_participating_bytes_unchanged': True,
        'unused_candidate_sources_are_not_guards': True})
    summary = {'status': 'FINISHED_WITH_OPEN', 'results': results, 'bodies_attempted': len(results),
        'recovered_graphs': sum(row['status'] == 'RECOVERED' for row in results),
        'source_files': {str(key): {'context_loads': 1, 'prepared_source_instances': 1, 'ast_parses': 1,
                                 'symtable_parses': 1, 'source_prepares': 0} for key in contexts},
        'operation_budget_charge': charged, 'code_witness_counts': dict(store.counts),
        'old_artifact_unchanged': True, 'old_store_unchanged': True, 'compile_count': 0,
        'source_prepare_count': 0, 'target_executed': False, 'publication_performed': False,
        'current_run_integrated': False, 'whole_program_established': False,
        'elapsed_s': time.perf_counter() - STARTED, 'max_rss_kib': resource.getrusage(resource.RUSAGE_SELF).ru_maxrss}
    save('summary.json', summary); progress('FINISHED', recovered_graphs=summary['recovered_graphs'])
    print(json.dumps({key: summary[key] for key in ('status', 'bodies_attempted', 'recovered_graphs', 'elapsed_s')}))
except BaseException as error:
    save('failure.json', {'type': type(error).__name__, 'detail': str(error), 'traceback': traceback.format_exc(),
        'elapsed_s': time.perf_counter() - STARTED, 'partial_outputs_retained': True})
    progress('FAILED', error_type=type(error).__name__, detail=str(error)); raise
finally:
    signal.setitimer(signal.ITIMER_REAL, 0); log.close()
