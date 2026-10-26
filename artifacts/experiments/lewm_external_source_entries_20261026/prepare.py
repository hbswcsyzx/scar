"""Normal metadata-only full catalog and mechanical ready window; no graph/CodeType."""
from collections import Counter, OrderedDict
import ast
import json
from pathlib import Path
import time
from run import HERE, ROOT, Meter, canonical, create_plan, install_meter, need, receipt, save


def main():
    tick = time.monotonic()
    config = json.loads((HERE / 'inputs.json').read_bytes())
    need(not (HERE / 'metadata-window.json').exists(), 'metadata outputs must be fresh')
    meter = Meter(config['budgets']['input_stored_plus_decoded_bytes'])
    install_meter(meter, metadata_only=True)
    owner, archives, catalog, budget, plan = create_plan(config, HERE / 'prepared-plan')
    preview = json.loads((HERE / 'metadata-preview.json').read_bytes())
    need({r['entry_key'] for r in plan.dispatch} == {r['entry_key'] for r in preview['window']}
         and len(plan.dispatch) == len(preview['window']), 'file grouping changed the original selected key set')
    selected, graphs, texts = {}, {}, {}
    lru = OrderedDict()
    graph_misses, source_runs = [], []
    previous = None
    for candidate in plan.dispatch:
        key = candidate['entry_key']
        _owner, witness, captured, link = catalog._owners[key]
        need(_owner is owner, 'unexpected non-original source owner')
        filename = link.snapshot.path
        source_row = owner._files[filename]
        path, artifact = owner._artifact_path(source_row['source_graph_artifact'], source_row['source_root'], 'graphs')
        graphs[filename] = {'source_path': filename, 'path': str(path), 'source_root': source_row['source_root'],
            'original_locator': source_row['source_graph_artifact'], 'declaration': artifact,
            'stored_bytes_stat': path.stat().st_size}
        need(path.stat().st_size == artifact['compressed_bytes'], 'declared source graph stored size differs')
        variants = candidate['archive_variants']
        need(bool(variants), 'dispatch without admitted compile key')
        store = archives.store_for(variants[0]['store'])
        source_records = [r for r in store.document['sources'].values() if r['snapshot'] == candidate['basis']['source_snapshot']]
        need(len(source_records) == 1, 'selected archive lacks exact unique snapshot text declaration')
        texts[filename] = source_records[0]['artifact']['bytes']
        selected[key] = {'entry_key': key, 'calls': candidate['calls'], 'file_key': candidate['file_key'],
                         'source_path': filename, 'archive_variants': variants}
        if filename != previous:
            source_runs.append(filename)
            previous = filename
        if filename not in lru:
            graph_misses.append(filename)
        lru[filename] = None
        lru.move_to_end(filename)
        while len(lru) > owner.budget.cached_files:
            lru.popitem(last=False)
    allvariants = {v['module_key']: v['compile_key'] for r in plan.dispatch for v in r['archive_variants']}
    preferred = {r['archive_variants'][0]['module_key']: r['archive_variants'][0]['compile_key'] for r in plan.dispatch}
    graph_sum = lambda names, field: sum(graphs[n]['declaration'][field] for n in names)
    measurements = owner.measurements()
    activity = [dict(store.counts) for store in archives._stores.values()]
    need(measurements.get('graph_artifacts_read', 0) == 0 and all(all(v == 0 for v in row.values()) for row in activity),
         'metadata preparation loaded graph/CodeType')
    window = {'schema': 'scar.lewm-external-source-entry-metadata-window/1', 'status': 'METADATA_PREPARED_WORKER_NOT_RUN',
        'inputs': receipt(HERE / 'inputs.json'), 'plan_sha256': plan.digest,
        'original_groups': len(plan.groups), 'original_calls': plan.document['summary']['current_calls'],
        'candidate_entries': len(plan.entries), 'candidate_statuses': dict(Counter(r['status'] for r in plan.entries)),
        'dispatch_count': len(plan.dispatch), 'dispatch_call_weight_historical': sum(r['calls'] for r in plan.dispatch),
        'dispatch_entries': list(selected.values()), 'source_files': len(graphs), 'source_text_unique_bytes': sum(texts.values()),
        'source_context_run_count': len(source_runs), 'worker_source_text_charge_if_all_reached': sum(texts[n] for n in source_runs),
        'unique_compile_keys_all_variants': allvariants, 'unique_compile_keys_preferred': preferred,
        'source_graph_declarations': list(graphs.values()),
        'unique_source_graph_stored_bytes': graph_sum(graphs, 'compressed_bytes'),
        'unique_source_graph_decoded_bytes': graph_sum(graphs, 'canonical_bytes'),
        'expected_graph_reads_under_original_LRU2_if_all_reached': len(graph_misses),
        'expected_graph_stored_bytes_LRU2': graph_sum(graph_misses, 'compressed_bytes'),
        'expected_graph_decoded_bytes_LRU2': graph_sum(graph_misses, 'canonical_bytes'),
        'LRU_estimate_scope': 'original successful reference/context path and original dispatch order; actual failures/budget stops may read less',
        'owner_measurements': measurements, 'readonly_counts': activity, 'metadata_preparation_IO': meter.report(),
        'budget': config['budgets'], 'public_worker_budget': plan.document['budget'], 'capabilities': plan.document['capabilities'],
        'input_budget_scope': 'all delegated source/aux/archive/SP5 readback incl repeated normal guards; control SHA and runtime import I/O separately excluded',
        'dispatch_order': config['dispatch_order'], 'original_call_weight_window_same_exact_keys': True,
        'dynamic_guard_repetition_cost': 'not predicted as actual;4GB precharge may stop and retains per-entry status',
        'graph_decode_CodeType_compile_lower_target': False, 'current369749_binding': 'NOT_RUN', 'publication': 'NOT_RUN',
        'live_owner_created_by_prepare': False, 'first_stage_complete': False, 'elapsed_s': time.monotonic() - tick}
    save('metadata-window.json', window)
    inputs = {config['continuation']['path']: config['continuation'], **{x['manifest']['path']: x['manifest'] for x in config['archives']}}
    for ref in (owner.receipts()['parent'],):
        inputs[ref['artifact']['uri']] = receipt(ref['artifact']['uri'])
    for name in ('inputs.json', 'metadata-window.json'):
        row = receipt(HERE / name); inputs[row['path']] = row
    row = receipt(config['compiler_workset']['path']); inputs[row['path']] = row
    sources = [receipt(p) for p in sorted((ROOT / 'scar').rglob('*.py'))]
    sources += [receipt(p) for p in sorted(HERE.glob('*.py'))]
    if (ROOT / 'sitecustomize.py').exists():
        sources.append(receipt(ROOT / 'sitecustomize.py'))
    for path in HERE.glob('*.py'):
        ast.parse(path.read_bytes(), filename=str(path))
    save('freeze.json', {'schema': 'scar.lewm-external-source-entry-freeze/1', 'sources': sources,
        'scar_source_count': len(list((ROOT / 'scar').rglob('*.py'))), 'control_inputs': list(inputs.values()),
        'graph_declared_roots': window['source_graph_declarations'], 'archive_member_identity': 'normal readonly manifest SHA and payload hashes on actual load',
        'runtime_binary_prepost': 'OPEN; no new runtime-byte claim', 'original_URI_unchanged': True,
        'budget': config['budgets'], 'worker_not_run': True})
    print(json.dumps({key: window[key] for key in ('status', 'original_groups', 'original_calls', 'candidate_entries',
        'candidate_statuses', 'dispatch_count', 'dispatch_call_weight_historical', 'source_files', 'source_text_unique_bytes',
        'source_context_run_count', 'worker_source_text_charge_if_all_reached', 'unique_source_graph_stored_bytes',
        'unique_source_graph_decoded_bytes', 'expected_graph_reads_under_original_LRU2_if_all_reached',
        'expected_graph_stored_bytes_LRU2', 'expected_graph_decoded_bytes_LRU2', 'metadata_preparation_IO')}, sort_keys=True), flush=True)

if __name__ == '__main__':
    main()
