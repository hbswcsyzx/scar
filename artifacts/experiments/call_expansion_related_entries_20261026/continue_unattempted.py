"""Continue only the prior real failures/unattempted entries, never successes."""
from collections import Counter
import gc
import json
from pathlib import Path
import time
from run import HERE, ROOT, INPUTS, receipt, save


def main():
    started = time.monotonic()
    prior = json.loads((HERE / 'result/terminal.json').read_bytes())
    selected = [r for r in prior['entries'] if r['status'] in ('FAILED', 'NOT_ATTEMPTED')]
    assert len(selected) == 3 and Counter(r['status'] for r in selected) == {'FAILED': 2, 'NOT_ATTEMPTED': 1}
    out = HERE / 'continuation01'
    out.mkdir()
    from scar.analysis.source_attachments import SourceAttachments, SourceAttachmentBudget
    from scar.analysis.code_witness import CodeWitnessBudget
    from scar.analysis.compiler_witness_archives import CompilerWitnessArchives, CompilerArchiveBudget
    from scar.analysis.source_entry_catalog import SourceEntryCatalog
    from scar.analysis.source_frontend_worklist import SourceFrontendBudget, plan_source_entries, run_source_entries
    config = json.loads(INPUTS.read_bytes())
    pins = [receipt(p) for p in sorted((ROOT / 'scar').rglob('*.py'))]
    save(out / 'inputs.json', {'prior_terminal': receipt(HERE / 'result/terminal.json'),
                             'ordinary_inputs': receipt(INPUTS), 'selected': selected, 'sources': pins})
    owner = SourceAttachments(config['continuation']['path'], expected_report_sha256=config['continuation']['sha256'],
        project_root=config['project_root'], budget=SourceAttachmentBudget(max_report_bytes=8_000_000,
        max_artifact_bytes=3_000_000_000, max_record_bytes=128_000_000, cached_files=2))
    archives = CompilerWitnessArchives(tuple((r['directory'], r['manifest']['sha256']) for r in config['archives']),
        store_budget=CodeWitnessBudget(max_compile_keys=94, max_source_files=94, max_source_bytes=8_000_000,
        max_module_bytes=16_000_000, max_archive_bytes=256_000_000, max_manifest_bytes=8_000_000),
        budget=CompilerArchiveBudget(max_archives=4, max_total_modules=256, max_total_sources=256,
                                    max_declared_payload_bytes=256_000_000))
    catalog = SourceEntryCatalog(admissions=(owner,), projects=(), archives=archives,
        max_groups=8192, max_candidates=8192, max_selected_decode_bytes=3_000_000_000)
    metadata = catalog.metadata()
    assert (len(metadata['groups']), metadata['entered_invocations'], len(metadata['candidates'])) == (817, 100438, 243)
    budget = SourceFrontendBudget(max_catalog_files=256, max_catalog_bodies=8192, max_catalog_groups=8192,
        max_dispatch_bodies=64, max_source_files=8, max_source_bytes=2_000_000,
        max_operations_per_body=10_000, max_total_operations=200_000,
        max_record_bytes=128_000_000, max_output_bytes=512_000_000, max_elapsed_seconds=900)
    plan = plan_source_entries(catalog, budget=budget, eligible_entry_keys=tuple(r['entry_key'] for r in selected),
        automatic_function_try=True, automatic_call_expansion=True,
        dispatch_order='FILE_GROUPED_V1', out_dir=out / 'plan')
    assert {r['entry_key'] for r in plan.dispatch} == {r['entry_key'] for r in selected}
    returned = run_source_entries(plan, out / 'worker', budget=budget,
        progress=lambda row: print(json.dumps(row), flush=True))
    summary = returned.document
    save(out / 'public-return.json', {'document': summary, 'digest': returned.digest,
                                     'owned_returns_before_release': len(returned.owned_returns)})
    returned = plan = None
    gc.collect()
    assert [receipt(Path(p['path'])) for p in pins] == pins
    rows = [dict(json.loads(p.read_bytes()), public_terminal=str(p)) for p in sorted(out.glob('worker/attempt-*/result.json'))]
    counts = dict(Counter(r['status'] for r in rows))
    final = {'status': 'RELATED_CONTINUATION_WITH_OPEN', 'entries': rows, 'counts': counts,
        'original_partial_and_failures_retained': True, 'original_terminal': receipt(HERE / 'result/terminal.json'),
        'readonly_counts': [s.counts for s in archives._stores.values()], 'elapsed_s': time.monotonic() - started,
        'raw': 0, 'compile': 0, 'target': 0, 'publication': 0, 'currentRun_binding': 0, 'whole_model_complete': False}
    save(out / 'terminal.json', final)
    print(json.dumps({'counts': counts, 'elapsed_s': final['elapsed_s']}), flush=True)
    return 1 if counts.get('FAILED') or len(rows) != len(selected) else 0


if __name__ == '__main__':
    raise SystemExit(main())
