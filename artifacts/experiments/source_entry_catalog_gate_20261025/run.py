"""One real entry/owned-return/public-reader gate. Root owns execution."""
from __future__ import annotations
import argparse
import hashlib
import json
from pathlib import Path
import signal
import sys
import time

HERE = Path(__file__).resolve().parent
ROOT = HERE.parents[2]
PRIOR = ROOT / 'artifacts/experiments/model_run_dependency_gate_20261025/model/model-run.json'


def digest(path):
    h, count = hashlib.sha256(), 0
    with path.open('rb') as stream:
        while block := stream.read(1_048_576):
            h.update(block); count += len(block)
    return {'uri': str(path), 'sha256': h.hexdigest(), 'size_bytes': count}


def small(path):
    assert path.stat().st_size <= 2_000_000
    return json.loads(path.read_bytes())


def put(path, document):
    with path.open('x') as stream:
        json.dump(document, stream, sort_keys=True, ensure_ascii=False, allow_nan=False, indent=2)
        stream.write('\n')


def prepare(label):
    assert not (HERE / 'freeze.json').exists()
    prior = small(PRIOR)
    report_ref = prior['products']['dependency_admissions']
    witness_ref = prior['products']['dependency_workload_witness']
    report = small(Path(report_ref['uri']))
    witness = small(Path(witness_ref['uri']))
    previous = {row['uri']: row for stage in prior['stages'] for row in stage['post_stage']['stage_outputs']}
    refs = {str(PRIOR): digest(PRIOR), report_ref['uri']: report_ref, witness_ref['uri']: witness_ref}
    directory = Path(report_ref['uri']).parent
    # Reuse the prior measured stored receipts. Preparation only stats graph
    # artifacts; the root-run pre/post checks verify their stored bytes.
    for file in report['source_files']:
        declarations = [file['snapshot_artifact'], file['source_graph_artifact']]
        for provider in file['providers']:
            declarations.extend(provider[field] for field in ('metadata_artifact', 'record_artifact') if field in provider)
        for declaration in declarations:
            if declaration is not None:
                path = directory / declaration['path']
                ref = previous[str(path)]
                assert path.stat().st_size == ref['size_bytes']
                refs[str(path)] = {key: ref[key] for key in ('uri', 'sha256', 'size_bytes')}
    archive = Path(witness_ref['uri']).parent
    for kind in ('sources', 'modules'):
        for item in witness[kind].values():
            path = archive / item['artifact']['path']
            ref = previous[str(path)]
            assert path.stat().st_size == ref['size_bytes']
            refs[str(path)] = {key: ref[key] for key in ('uri', 'sha256', 'size_bytes')}
    sources = [digest(path) for path in sorted((ROOT / 'scar').rglob('*.py'))]
    put(HERE / 'freeze.json', {'schema': 'scar.source-entry-gate-freeze/1', 'head_label': label,
        'entry': digest(Path(__file__).resolve()), 'sources': sources, 'inputs': list(refs.values()),
        'prior': str(PRIOR), 'admissions': report_ref, 'witness': witness_ref,
        'input_denominators': report['summary'], 'source_payloads_copied': 0,
        'graph_decode_during_prepare': 0, 'runtime_binary_freeze': 'OPEN',
        'budget': {'dispatch': 1, 'source_files': 1, 'operations_per_body': 4000, 'total_operations': 4000,
                   'selected_source_provider_decode_bytes': 128_000_000, 'record_bytes': 64_000_000,
                   'stored_output_bytes': 128_000_000, 'external_wall_seconds': 180},
        'not_run': ['raw', 'source_prepare', 'compile_acquisition', 'target', 'native_OS', 'publication', 'binding']})
    print(json.dumps({'status': 'PREPARED_NOT_RUN', 'freeze': digest(HERE / 'freeze.json'), 'sources': len(sources)}))


def verify(freeze):
    actual = sorted(str(path) for path in (ROOT / 'scar').rglob('*.py'))
    assert actual == sorted(item['uri'] for item in freeze['sources']), 'source inventory changed'
    count = 0
    for ref in [freeze['entry'], *freeze['sources'], *freeze['inputs']]:
        measured = digest(Path(ref['uri']))
        assert measured == {key: ref[key] for key in measured}, 'frozen bytes changed: ' + ref['uri']
        count += measured['size_bytes']
    return count


class ExternalStop(BaseException):
    pass


def stop(number, _frame):
    raise ExternalStop('external signal ' + str(number))


def run():
    freeze = small(HERE / 'freeze.json')
    output = HERE / 'result'
    assert not output.exists(), 'fresh gate output required'
    output.mkdir()
    started = time.monotonic()
    document = {'schema': 'scar.source-entry-gate-result/1', 'status': 'RUNNING',
                'publication': 'NOT_RUN', 'runtime_binding': 'NOT_RUN', 'whole_model': 'OPEN'}
    old = signal.signal(signal.SIGTERM, stop)
    journal = (output / 'journal.jsonl').open('x', buffering=1)
    def progress(row):
        row = {'elapsed_s': time.monotonic() - started, **row}
        journal.write(json.dumps(row, allow_nan=False) + '\n')
        print(json.dumps(row, allow_nan=False), flush=True)
    try:
        document['precheck_stored_bytes_read'] = verify(freeze)
        progress({'phase': 'FROZEN_INPUTS_VERIFIED'})
        from scar.analysis.source_attachments import SourceAttachments, SourceAttachmentBudget
        from scar.analysis.source_entry_catalog import SourceEntryCatalog
        from scar.analysis.code_witness import CodeWitnessBudget
        from scar.analysis.compiler_witness_archives import CompilerWitnessArchives, CompilerArchiveBudget
        from scar.analysis.source_frontend_worklist import SourceFrontendBudget, plan_source_entries, run_source_entries
        report = small(Path(freeze['admissions']['uri']))
        attachment = SourceAttachments.from_admissions(freeze['admissions']['uri'],
            expected_report_sha256=freeze['admissions']['sha256'], project_root=report['program_root'],
            budget=SourceAttachmentBudget(max_report_bytes=2_000_000, max_files=6, max_codes=16, max_roots=8,
                max_artifact_bytes=128_000_000, max_record_bytes=64_000_000, cached_files=1))
        archives = CompilerWitnessArchives(((str(Path(freeze['witness']['uri']).parent), freeze['witness']['sha256']),),
            store_budget=CodeWitnessBudget(max_compile_keys=4, max_source_files=4, max_source_bytes=1_000_000,
                max_archive_bytes=32_000_000, max_manifest_bytes=2_000_000),
            budget=CompilerArchiveBudget(max_archives=1, max_total_modules=4, max_total_sources=4,
                max_declared_payload_bytes=32_000_000))
        before = [dict(archives.store_for(ref).counts) for ref in archives.receipts()]
        catalog = SourceEntryCatalog(archives=archives, admissions=(attachment,), max_groups=16,
            max_candidates=16, max_selected_decode_bytes=128_000_000)
        budget = SourceFrontendBudget(max_catalog_files=6, max_catalog_bodies=16, max_catalog_groups=16,
            max_dispatch_bodies=1, max_source_files=1, max_source_bytes=1_000_000,
            max_operations_per_body=4000, max_total_operations=4000, max_record_bytes=64_000_000,
            max_output_bytes=128_000_000, max_elapsed_seconds=180)
        plan = plan_source_entries(catalog, budget=budget, out_dir=output / 'plan')
        document['plan'] = plan.document
        progress({'phase': 'ENTRY_PLAN_COMPLETE', **plan.document['summary']})
        result = run_source_entries(plan, output / 'worker', budget=budget, progress=progress)
        result.require_unchanged()
        document['worker'] = result.document
        document['live_owned_returns'] = len(result.owned_returns)
        after = [dict(archives.store_for(ref).counts) for ref in archives.receipts()]
        document['readonly_activity'] = [{key: right[key] - left[key] for key in left} for left, right in zip(before, after)]
        assert all(row['compile_attempts'] == 0 for row in document['readonly_activity'])
        document['postcheck_stored_bytes_read'] = verify(freeze)
        document['stored_output_bytes_before_terminal'] = sum(path.stat().st_size for path in output.rglob('*') if path.is_file())
        assert document['stored_output_bytes_before_terminal'] <= 128_000_000
        assert result.document['original_current_groups'] == report['summary']['entered_code_groups']
        assert result.document['original_current_calls'] == report['summary']['entered_invocations']
        document['status'] = 'FAILED' if result.document['counts'].get('FAILED', 0) else 'ACTUAL_ENTRY_ATTEMPT_WITH_OPEN'
    except BaseException as error:
        document.update(status='FAILED', failure={'type': type(error).__name__, 'detail': str(error)})
    finally:
        signal.signal(signal.SIGTERM, old)
        journal.close()
    document['wall_seconds'] = time.monotonic() - started
    document['freeze'] = digest(HERE / 'freeze.json')
    stored = sum(path.stat().st_size for path in output.rglob('*') if path.is_file())
    terminal_bytes = len((json.dumps(document, sort_keys=True, ensure_ascii=False, allow_nan=False, indent=2) + '\n').encode())
    if stored + terminal_bytes > 128_000_000:
        document.update(status='FAILED', failure={'type': 'PostStageOutputBudget',
            'detail': 'final terminal would exceed stored output ceiling; partial files retained'})
    put(output / 'result.json', document)
    print(json.dumps({'status': document['status'], 'out': str(output), 'wall_seconds': document['wall_seconds']}), flush=True)
    return 1 if document['status'] == 'FAILED' else 0


if __name__ == '__main__':
    parser = argparse.ArgumentParser()
    parser.add_argument('--prepare', action='store_true')
    parser.add_argument('--head-label', default='root-supplied-label; source bytes pinned independently')
    args = parser.parse_args()
    if args.prepare:
        prepare(args.head_label)
    else:
        raise SystemExit(run())
