"""ONE ADD+REVISE publication/compose/reader gate; no lowering or raw scan."""
import ast
from copy import deepcopy
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
EXPERIMENTS = HERE.parent
sys.path.insert(0, str(ROOT))
STARTED = time.perf_counter()
log = (HERE / 'progress.jsonl').open('x', buffering=1)
def canonical(value):
    return json.dumps(value, sort_keys=True, ensure_ascii=False, separators=(',', ':'), allow_nan=False).encode()
def save(name, value):
    path = HERE / name; path.parent.mkdir(parents=True, exist_ok=True)
    with path.open('xb') as stream:
        stream.write(canonical(value) + b'\n')
def receipt(path):
    path = Path(path).resolve(); raw = path.read_bytes()
    return {'path': str(path), 'sha256': sha256(raw).hexdigest(), 'bytes': len(raw)}
def progress(row):
    log.write(json.dumps({'elapsed_s': time.perf_counter() - STARTED,
        'max_rss_kib': resource.getrusage(resource.RUSAGE_SELF).ru_maxrss, **row}) + '\n')
def expired(signum, frame):
    raise TimeoutError('independent publication/compose/reader gate exceeded wall180s')
signal.signal(signal.SIGALRM, expired); signal.setitimer(signal.ITIMER_REAL, 180)

try:
    candidates = {str(path.resolve()): receipt(path) for path in (ROOT / 'scar').rglob('*.py')}
    save('candidate-source-hashes.json', list(candidates.values()))
    freeze = json.loads((HERE / 'freeze.json').read_text())
    for row in freeze['modules']:
        if receipt(ROOT / row['path'])['sha256'] != row['sha256']:
            raise ValueError('frozen source revision module drifted')
    from scar.analysis.code_witness import CodeWitnessBudget, CodeWitnessStore
    from scar.analysis.inventory_partitions import InventoryPartitions
    from scar.analysis.program_composition import CompositionIndex, compose_source_publication
    from scar.analysis.source_language import SourceCodeEvidence, SourceLanguageOptions
    from scar.analysis.source_program_publication import (
        SourceBodyPublicationPlan, plan_source_body_publication, publish_source_body_revisions,
        validate_body_revision_publication,
    )
    from scar.ir.program.call_edges import CapturedCode
    from scar.ir.record_codec import decode, encode

    repair_dir = EXPERIMENTS / 'first_stage_tuple_key_bodies_20261023'
    repair = json.loads((repair_dir / 'summary.json').read_text())
    programs = [row['artifact']['path'] for row in repair['results'] if row['status'] == 'RECOVERED']
    addition_dir = EXPERIMENTS / 'first_stage_tuple_key_heap_attempt02_20261023'
    addition = json.loads((addition_dir / 'summary.json').read_text())
    if addition['status'] != 'RECOVERED_WITH_OPEN':
        raise ValueError('new body source gate did not recover an immutable graph')
    programs.append(addition['artifact']['path'])
    if len(programs) != 2:
        raise ValueError('bounded publication must have exactly two existing verified input artifacts')
    parent_path = EXPERIMENTS / 'first_stage_source_publication_current_20261023/result/composition/index.json.gz'
    parent = CompositionIndex(parent_path)
    store_dir = EXPERIMENTS / 'first_stage_partitioned_operand_routes_20261023/result/code-witnesses'
    store = CodeWitnessStore(store_dir, budget=CodeWitnessBudget(max_compile_keys=20))
    old_store = [receipt(path) for path in sorted(store_dir.iterdir()) if path.is_file()]
    save('old-store-before.json', old_store)
    old_graph = repair_dir.parent / 'first_stage_source_language_bodies_attempt03_20261023/result/body-26.source-program5.json.gz'
    old_graph_before = receipt(old_graph)
    plan = plan_source_body_publication(parent, tuple(programs), max_programs=2, max_record_bytes=64_000_000)
    if {row['operation'] for row in plan.document['expectations']} != {'ADD_GRAPH', 'REVISE_GRAPH'}:
        raise ValueError('real plan is not one ADD and one exact revision')
    if len({row['file_index'] for row in plan.document['expectations']}) != 2:
        raise ValueError('bounded publication is not two original source files')
    save('plan.json', {'sha256': plan.sha256, 'document': plan.document})
    producer = {'head_at_start': subprocess.check_output(['git', 'rev-parse', 'HEAD'], cwd=ROOT, text=True).strip(),
        'pid': os.getpid(), 'runner': receipt(__file__), 'freeze': receipt(HERE / 'freeze.json'),
        'parent_composition': receipt(parent_path), 'old_graph': old_graph_before,
        'inputs': [receipt(path) for path in programs], 'plan': receipt(HERE / 'plan.json'),
        'code_witness_archive': store.receipt(), 'max_programs': 2, 'max_changed_sources': 2,
        'max_operations_per_body': 4000, 'max_record_bytes': 64_000_000,
        'max_wall_seconds': 180, 'source_lowering_performed': False, 'raw_trace_read': False,
        'source_prepare': 0, 'compile': 0, 'target_executed': False}
    save('producer.json', producer)
    stale = deepcopy(plan.document)
    target, = [row for row in stale['expectations'] if row['operation'] == 'REVISE_GRAPH']
    target['expected_namespace']['record_pointer'] = '#/stale-expected-graph'
    stale_plan = SourceBodyPublicationPlan(stale, sha256(canonical(stale)).hexdigest())
    try:
        publish_source_body_revisions(parent, stale_plan, HERE / 'rejected-stale', code_witnesses=store,
            max_programs=2, max_changed_sources=2, max_operations_per_body=4000, max_record_bytes=64_000_000)
    except ValueError as error:
        if 'stale parent/checkpoint/namespace/digest' not in str(error) or (HERE / 'rejected-stale').exists():
            raise
        save('stale-expectation-rejected.json', {'type': type(error).__name__, 'detail': str(error),
            'output_created': False, 'store_counts': dict(store.counts), 'source_graph_rebuilt': False})
    else:
        raise ValueError('stale exact previous namespace was not rejected')
    progress({'stage': 'PUBLICATION', 'status': 'BEGIN'})
    publication = publish_source_body_revisions(parent, plan, HERE / 'result/publication', code_witnesses=store,
        max_programs=2, max_changed_sources=2, max_operations_per_body=4000,
        max_record_bytes=64_000_000, progress=progress)
    save('publication-result.json', publication)
    progress({'stage': 'COMPOSE', 'status': 'BEGIN'})
    composed = compose_source_publication(parent, publication['manifest'], HERE / 'result/composition',
        max_record_bytes=64_000_000, progress=progress)
    save('compose-result.json', composed)
    index = CompositionIndex(HERE / 'result/composition/index.json.gz', max_record_bytes=64_000_000)
    inventory = InventoryPartitions(publication['manifest'], max_shard_bytes=64_000_000)
    lineage = validate_body_revision_publication(parent, inventory, max_programs=2)
    checked = []
    for expectation in plan.document['expectations']:
        fi, bi = expectation['file_index'], expectation['body_index']
        raw = inventory.body_record(fi, bi)
        source_program = inventory.checkpoint(inventory.file(fi)['bodies'][bi]['checkpoint'])['source_program']
        import gzip
        program = json.loads(gzip.decompress(Path(source_program['uri']).read_bytes()))
        captured = decode(CapturedCode, program['language']['code_evidence']['captured'])
        evidence = SourceCodeEvidence(store, index, captured)
        text = store.text(evidence.source_link.snapshot)
        tree = ast.parse(text, filename=evidence.source_link.snapshot.path)
        options = SourceLanguageOptions(code_evidence=evidence)
        body = inventory.typed_body(fi, bi, language_options=options, source_tree=tree)
        if not (body.public_graph_validated and body.public_language_structure_validated
                and body.source_shape_verified and body.source_code_witness_verified):
            raise ValueError('new active body did not pass public source/code reader checks')
        checked.append({'operation': expectation['operation'], 'definition': encode(body.body.definition),
            'namespace': body.namespace, 'locators': body.locators,
            'graph_operations': len(body.body.graph.operations), 'graph_values': len(body.body.graph.values),
            'public_structure_and_independent_source_code_verified': True,
            'whole_lifetime_verified': False, 'current_run_integrated': False})
    if index.original_code_source_origin() != parent.original_code_source_origin():
        raise ValueError('revision changed original compiler/source evidence basis')
    after_store = [receipt(path) for path in sorted(store_dir.iterdir()) if path.is_file()]
    save('old-store-after.json', after_store)
    if after_store != old_store or receipt(old_graph) != old_graph_before or store.counts['compile_attempts']:
        raise ValueError('historical bytes changed or compiler budget violated')
    participants = []
    archive = HERE / 'participating-source-evidence'; archive.mkdir()
    for module in tuple(sys.modules.values()):
        filename = getattr(module, '__file__', None)
        if filename:
            path = Path(filename).resolve()
            if path.is_relative_to(ROOT / 'scar') and path.suffix == '.py':
                row = receipt(path)
                if row != candidates.get(str(path)):
                    raise ValueError('actual participating source changed: ' + str(path))
                if row not in participants:
                    participants.append(row); (archive / (row['sha256'] + '.py-source')).write_bytes(path.read_bytes())
    save('participating-producer.json', {'sources': participants, 'all_bytes_unchanged': True,
        'unused_candidates_are_not_guards': True})
    summary = {'status': 'PASS_WITH_OPEN', 'lineage_accounting': lineage, 'active_bodies': checked,
        'manifest_counts': inventory.manifest['counts'], 'header_summary': inventory.component('header')['summary'],
        'publication_header': index.publication_header(), 'stale_expectation_rejected': True,
        'code_witness_counts': dict(store.counts), 'old_graph_and_store_unchanged': True,
        'static_body_denominator': sum(len(row['bodies']) for row in index.document['files']),
        'source_files': len(index.document['files']), 'old_source_typed_legality_asserted': False,
        'source_lowered': False, 'raw_trace_read': False, 'source_prepare': 0, 'target_executed': False,
        'current_run_integrated': False, 'whole_program_established': False,
        'elapsed_s': time.perf_counter() - STARTED, 'max_rss_kib': resource.getrusage(resource.RUSAGE_SELF).ru_maxrss}
    save('summary.json', summary); progress({'stage': 'FINISHED', 'status': summary['status']})
    print(json.dumps({key: summary[key] for key in ('status', 'manifest_counts', 'elapsed_s')}))
except BaseException as error:
    save('failure.json', {'type': type(error).__name__, 'detail': str(error), 'traceback': traceback.format_exc(),
        'elapsed_s': time.perf_counter() - STARTED, 'partial_outputs_retained': True})
    progress({'stage': 'FAILED', 'type': type(error).__name__, 'detail': str(error)}); raise
finally:
    signal.setitimer(signal.ITIMER_REAL, 0); log.close()
