"""Normal catalog metadata preview while the unrelated consumer finishes review."""
from collections import Counter, OrderedDict
import json
import time
from run import HERE, Meter, create_catalog, install_meter, need, save


def main():
    tick = time.monotonic()
    meter = Meter()
    install_meter(meter, metadata_only=True)
    config = json.loads((HERE / 'inputs.json').read_bytes())
    owner, archives, catalog, budget = create_catalog(config)
    metadata = catalog.metadata()
    need(metadata['entered_code_groups'] == 817 and metadata['entered_invocations'] == 100438, 'denominator changed')
    window, files = [], set()
    for row in metadata['candidates']:
        if row['status'] != 'CANDIDATE_SOURCE_GRAPH_UNVERIFIED':
            continue
        if len(window) >= budget.max_dispatch_bodies:
            break
        if row['file_key'] not in files and len(files) >= budget.max_source_files:
            continue
        window.append(row); files.add(row['file_key'])
    graphs, texts, variants, preferred = {}, {}, {}, {}
    lru, misses, runs, previous = OrderedDict(), [], [], None
    for row in window:
        filename = row['basis']['source_snapshot']['path']
        file = owner._files[filename]
        path, declaration = owner._artifact_path(file['source_graph_artifact'], file['source_root'], 'graphs')
        need(path.stat().st_size == declaration['compressed_bytes'], 'source graph declaration size differs')
        graphs[filename] = {'path': str(path), 'original_locator': file['source_graph_artifact'], 'declaration': declaration}
        store = archives.store_for(row['archive_variants'][0]['store'])
        match = [s for s in store.document['sources'].values() if s['snapshot'] == row['basis']['source_snapshot']]
        need(len(match) == 1, 'archive text snapshot declaration missing')
        texts[filename] = match[0]['artifact']['bytes']
        for v in row['archive_variants']:
            variants[v['module_key']] = v['compile_key']
        v = row['archive_variants'][0]; preferred[v['module_key']] = v['compile_key']
        if filename != previous:
            runs.append(filename); previous = filename
        if filename not in lru:
            misses.append(filename)
        lru[filename] = None; lru.move_to_end(filename)
        while len(lru) > owner.budget.cached_files:
            lru.popitem(last=False)
    count = lambda names, field: sum(graphs[n]['declaration'][field] for n in names)
    measurements = owner.measurements()
    need(measurements.get('graph_artifacts_read', 0) == 0 and all(all(v == 0 for v in s.counts.values()) for s in archives._stores.values()), 'preview loaded graph or CodeType')
    result = {'status': 'NORMAL_CATALOG_METADATA_PREVIEW_NOT_FRONTEND_PLAN',
        'original_groups': metadata['entered_code_groups'], 'original_calls': metadata['entered_invocations'],
        'candidate_entries': len(metadata['candidates']), 'candidate_statuses': dict(Counter(r['status'] for r in metadata['candidates'])),
        'ready_entries_all': sum(r['status'] == 'CANDIDATE_SOURCE_GRAPH_UNVERIFIED' for r in metadata['candidates']),
        'automatic_window_entries': len(window), 'historical_window_call_weight': sum(r['calls'] for r in window),
        'window_source_files': len(files), 'normalized_source_unique_bytes': sum(texts.values()),
        'source_context_runs': len(runs), 'source_byte_charge_if_all_reached': sum(texts[n] for n in runs),
        'unique_graph_stored_bytes': count(graphs, 'compressed_bytes'), 'unique_graph_decoded_bytes': count(graphs, 'canonical_bytes'),
        'LRU2_graph_reads_if_all_reached': len(misses), 'LRU2_graph_stored_bytes': count(misses, 'compressed_bytes'),
        'LRU2_graph_decoded_bytes': count(misses, 'canonical_bytes'),
        'unique_all_variant_keys': len(variants), 'unique_preferred_keys': len(preferred),
        'compile_keys_all_variants': variants, 'compile_keys_preferred': preferred,
        'window': window, 'graph_declarations': graphs, 'normal_owner_measurements': measurements,
        'metadata_IO': meter.report(), 'elapsed_s': time.monotonic() - tick,
        'scope': 'original272038 static source entries; no current369749 binding', 'worker_graph_CodeType_compile_target': False,
        'producer_frozen': False, 'first_stage_complete': False}
    save('metadata-preview.json', result)
    print(json.dumps({k: v for k, v in result.items() if k not in ('window', 'graph_declarations', 'compile_keys_all_variants', 'compile_keys_preferred')}, sort_keys=True), flush=True)

if __name__ == '__main__':
    main()
