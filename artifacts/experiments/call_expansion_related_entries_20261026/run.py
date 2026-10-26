"""Ordinary worker on mechanically selected expanded-call and old Try gaps."""
from collections import Counter, OrderedDict
from dataclasses import asdict
import gc
import hashlib
import json
from pathlib import Path
import resource
import time
import traceback

ROOT = Path(__file__).resolve().parents[3]
HERE = Path(__file__).resolve().parent
SELECTION = ROOT / 'artifacts/analysis/complete_source_entry_selection_20261026/complete-latest-ledger.json'
INPUTS = Path('/home/zyf/AAA/scar-worktrees/source209-model/artifacts/experiments/source209_resume01_20261026/inputs.json')


def save(path, value):
    with path.open('x') as stream:
        json.dump(value, stream, ensure_ascii=False, sort_keys=True, separators=(',', ':'), allow_nan=False)
        stream.write('\n')


def receipt(path):
    raw = path.read_bytes()
    return {'path': str(path), 'bytes': len(raw), 'sha256': hashlib.sha256(raw).hexdigest()}


def main():
    out = HERE / 'result'
    out.mkdir()
    started = time.monotonic()
    resource.setrlimit(resource.RLIMIT_AS, (8 * 1024**3,) * 2)
    from scar.analysis.source_attachments import SourceAttachments, SourceAttachmentBudget
    from scar.analysis.code_witness import CodeWitnessBudget
    from scar.analysis.compiler_witness_archives import CompilerWitnessArchives, CompilerArchiveBudget
    from scar.analysis.source_entry_catalog import SourceEntryCatalog
    from scar.analysis.source_frontend_worklist import SourceFrontendBudget, plan_source_entries, run_source_entries
    config = json.loads(INPUTS.read_bytes())
    original = json.loads(SELECTION.read_bytes())
    selected = []
    for row in original['entries']:
        if row['status'] != 'UNSUPPORTED':
            continue
        terminal = Path(row['public_terminal'])
        returned = json.loads(terminal.with_name('returned-metadata.json').read_bytes())
        gap = returned['metadata']['gaps'][-1]['detail']
        group = ('EXPANDED_CALL' if 'KWARGS_' in gap or gap == 'structured expression protocol still required for Call'
                 else 'OLD_TRY_POLICY' if gap == 'structured control/effect protocol still required for Try' else None)
        if group:
            selected.append({**{k: row[k] for k in ('entry_key', 'file_key', 'historical_calls', 'public_terminal')},
                             'group': group, 'original_gap': gap})
    assert Counter(row['group'] for row in selected) == {'EXPANDED_CALL': 13, 'OLD_TRY_POLICY': 10}
    source_pins = [receipt(p) for p in sorted((ROOT / 'scar').rglob('*.py'))]
    save(out / 'inputs.json', {'selection': receipt(SELECTION), 'ordinary_inputs': receipt(INPUTS),
                             'selected': selected, 'sources': source_pins})
    owner = SourceAttachments(config['continuation']['path'], expected_report_sha256=config['continuation']['sha256'],
        project_root=config['project_root'], budget=SourceAttachmentBudget(max_report_bytes=8_000_000,
        max_artifact_bytes=3_000_000_000, max_record_bytes=128_000_000, cached_files=2))
    archives = CompilerWitnessArchives(tuple((x['directory'], x['manifest']['sha256']) for x in config['archives']),
        store_budget=CodeWitnessBudget(max_compile_keys=94, max_source_files=94, max_source_bytes=8_000_000,
        max_module_bytes=16_000_000, max_archive_bytes=256_000_000, max_manifest_bytes=8_000_000),
        budget=CompilerArchiveBudget(max_archives=4, max_total_modules=256, max_total_sources=256,
                                    max_declared_payload_bytes=256_000_000))
    catalog = SourceEntryCatalog(admissions=(owner,), projects=(), archives=archives,
        max_groups=8192, max_candidates=8192, max_selected_decode_bytes=3_000_000_000)
    metadata = catalog.metadata()
    assert (len(metadata['groups']), metadata['entered_invocations'], len(metadata['candidates'])) == (817, 100438, 243)
    candidates = {row['entry_key']: row for row in metadata['candidates']}
    groups = OrderedDict()
    for row in sorted(selected, key=lambda r: (-r['historical_calls'], r['entry_key'])):
        assert candidates[row['entry_key']]['file_key'] == row['file_key']
        assert candidates[row['entry_key']]['calls'] == row['historical_calls']
        groups.setdefault(row['file_key'], []).append(row)
    batches, active, decoded = [], [], 0
    for key, rows in groups.items():
        filename = candidates[rows[0]['entry_key']]['basis']['source']['path']
        declaration = owner._artifact_path(owner._files[filename]['source_graph_artifact'],
                                          owner._files[filename]['source_root'], 'graphs')[1]
        assert declaration['canonical_bytes'] <= 300_000_000
        if active and (len(active) == 8 or decoded + declaration['canonical_bytes'] > 300_000_000):
            batches.append(active)
            active, decoded = [], 0
        active.append((key, rows))
        decoded += declaration['canonical_bytes']
    if active:
        batches.append(active)
    save(out / 'read-plan.json', {'selected': selected,
        'batches': [[r['entry_key'] for _, rows in batch for r in rows] for batch in batches],
        'full_denominators': {'groups': 817, 'calls': 100438, 'candidates': 243},
        'io_accounting': 'normal API counters; no cumulative stored+decoded claim'})
    summaries, failure = [], None
    try:
        for ordinal, batch in enumerate(batches, 1):
            folder = out / f'batch-{ordinal:02d}'
            folder.mkdir()
            keys = tuple(r['entry_key'] for _, rows in batch for r in rows)
            budget = SourceFrontendBudget(max_catalog_files=256, max_catalog_bodies=8192, max_catalog_groups=8192,
                max_dispatch_bodies=64, max_source_files=8, max_source_bytes=2_000_000,
                max_operations_per_body=10_000, max_total_operations=200_000,
                max_record_bytes=128_000_000, max_output_bytes=512_000_000, max_elapsed_seconds=900)
            plan = plan_source_entries(catalog, budget=budget, eligible_entry_keys=keys,
                dispatch_order='FILE_GROUPED_V1', automatic_function_try=True,
                automatic_call_expansion=True, out_dir=folder / 'plan')
            assert [r['entry_key'] for r in plan.dispatch] == list(keys)
            save(folder / 'budget.json', asdict(budget))
            def progress(row):
                print(json.dumps({'batch': ordinal, **row}), flush=True)
            returned = run_source_entries(plan, folder / 'worker', budget=budget, progress=progress)
            save(folder / 'public-return.json', {'document': returned.document, 'digest': returned.digest,
                'owned_returns_before_release': len(returned.owned_returns), 'publication': 'NOT_RUN'})
            summaries.append(returned.document)
            returned = plan = None
            gc.collect()
        assert [receipt(Path(p['path'])) for p in source_pins] == source_pins
    except BaseException as error:
        failure = {'type': type(error).__name__, 'detail': str(error), 'traceback': traceback.format_exc()}
    records = {}
    for path in sorted(out.glob('batch-*/worker/attempt-*/result.json')):
        row = json.loads(path.read_bytes())
        assert row['entry_key'] not in records
        records[row['entry_key']] = {**row, 'public_terminal': str(path)}
    entries = [{**row, **records.get(row['entry_key'], {'status': 'NOT_ATTEMPTED'})} for row in selected]
    counts = dict(Counter(row['status'] for row in entries))
    final = {'status': 'FAILED_RETAINED_WITH_OPEN' if failure or counts.get('FAILED') else 'RELATED_SOURCE_ATTEMPTS_WITH_OPEN',
        'failure': failure, 'entries': entries, 'counts': counts,
        'groups': {group: dict(Counter(row['status'] for row in entries if row['group'] == group))
                   for group in ('EXPANDED_CALL', 'OLD_TRY_POLICY')},
        'batches': summaries, 'elapsed_s': time.monotonic() - started,
        'readonly_counts': [s.counts for s in archives._stores.values()],
        'full_denominators': {'groups': 817, 'calls': 100438, 'candidates': 243},
        'raw': 0, 'compile': 0, 'target': 0, 'publication': 0, 'currentRun_binding': 0,
        'whole_model_complete': False}
    save(out / 'terminal.json', final)
    print(json.dumps({k: final[k] for k in ('status', 'counts', 'groups', 'elapsed_s', 'failure')}), flush=True)
    return 1 if failure or counts.get('FAILED') else 0


if __name__ == '__main__':
    raise SystemExit(main())
