"""Only the selected original import frontiers, through the normal public worker."""
import argparse
from collections import Counter
import gc
from hashlib import sha256
import importlib.util
import json
from pathlib import Path
import time
import traceback

ROOT = Path(__file__).resolve().parents[3]
HERE = Path(__file__).resolve().parent
spec = importlib.util.spec_from_file_location('ordinary_entry_inputs', ROOT/'artifacts/experiments/function_try_source_entries_20261026/common.py')
common = importlib.util.module_from_spec(spec); spec.loader.exec_module(common)


def save(path, value):
    with path.open('x') as stream:
        json.dump(value, stream, sort_keys=True, ensure_ascii=False, separators=(',', ':')); stream.write('\n')


def pins():
    return {str(p.relative_to(ROOT)): sha256(p.read_bytes()).hexdigest() for p in sorted((ROOT/'scar').rglob('*.py'))}


def main():
    parser = argparse.ArgumentParser(); parser.add_argument('--remaining', action='store_true'); args = parser.parse_args()
    out = HERE/('remaining' if args.remaining else 'first'); out.mkdir()
    before = pins(); start = time.monotonic()
    rows = json.loads((HERE/'selection.json').read_bytes())['selected']
    rows.sort(key=lambda r: (-r['historical_calls'], r['entry_key']))
    rows = rows[1:] if args.remaining else rows[:1]
    selected = tuple(r['entry_key'] for r in rows)
    save(out/'inputs.json', {'source_sha256': before, 'selected': selected, 'no_name_selection': True})
    config = json.loads(Path('/home/zyf/AAA/scar-worktrees/source209-model/artifacts/experiments/source209_resume01_20261026/inputs.json').read_bytes())
    owner, archives, catalog, metadata = common.normal_inputs(config, None)
    from scar.analysis.source_frontend_worklist import SourceFrontendBudget, plan_source_entries, run_source_entries
    from scar.ir.program.source_language import SourceLanguageCapability as C
    budget = SourceFrontendBudget(max_catalog_files=256, max_catalog_bodies=8192, max_catalog_groups=8192,
        max_dispatch_bodies=6, max_source_files=6, max_source_bytes=2_000_000,
        max_operations_per_body=10_000, max_total_operations=60_000,
        max_record_bytes=128_000_000, max_output_bytes=512_000_000, max_elapsed_seconds=900)
    failure = None
    try:
        plan = plan_source_entries(catalog, budget=budget, eligible_entry_keys=selected,
            dispatch_order='FILE_GROUPED_V1', automatic_function_try=True, automatic_call_expansion=True,
            automatic_nested_functions=True, capabilities=(C.FIXED_UNPACK, C.SLICE_KEYS, C.LEXICAL_LOCALS,
                C.CALL_KWARGS_314_V1, C.FUNCTION_IMPORT_314_V1), out_dir=out/'plan')
        assert set(r['entry_key'] for r in plan.dispatch) == set(selected)
        returned = run_source_entries(plan, out/'worker', budget=budget,
            progress=lambda r: print(json.dumps(r, sort_keys=True), flush=True))
        save(out/'public-return.json', {'document': returned.document, 'digest': returned.digest,
            'owned_returns_before_release': len(returned.owned_returns)})
        returned = plan = None; gc.collect()
        assert pins() == before
    except BaseException as error:
        failure = {'type': type(error).__name__, 'detail': str(error), 'traceback': traceback.format_exc()}
    terminals = {}
    for path in (out/'worker').glob('attempt-*/result.json'):
        row = json.loads(path.read_bytes()); terminals[row['entry_key']] = {**row, 'public_terminal': str(path)}
    entries = [{**r, **terminals.get(r['entry_key'], {'status': 'NOT_ATTEMPTED'})} for r in rows]
    result = {'status': 'FAILED_RETAINED_WITH_OPEN' if failure or any(r['status']=='FAILED' for r in entries)
        else 'FUNCTION_IMPORT_SOURCE_RESULTS_WITH_OPEN', 'failure': failure,
        'counts': dict(Counter(r['status'] for r in entries)), 'entries': entries,
        'elapsed_seconds': time.monotonic()-start, 'readonly_counts': [s.counts for s in archives._stores.values()],
        'compile': 0, 'raw': 0, 'target': 0, 'publication': 0, 'currentRun_binding': 0,
        'whole_model_complete': False, 'cumulative_stored_decoded_IO': 'UNMETERED_OPEN'}
    save(out/'terminal.json', result)
    print(json.dumps({k: result[k] for k in ('status','counts','failure','elapsed_seconds')}, sort_keys=True), flush=True)
    return int(failure is not None or any(r['status']=='FAILED' for r in entries))


if __name__ == '__main__':
    raise SystemExit(main())
