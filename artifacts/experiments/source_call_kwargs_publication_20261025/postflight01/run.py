"""Stored metadata/receipts only; no publisher, composer, graph codec or target."""
import gzip
from hashlib import sha256
from io import BytesIO
import json
from pathlib import Path
import resource
import signal
import time
import traceback

HERE = Path(__file__).resolve().parent
GATE = HERE.parent
STARTED = time.perf_counter()
COUNTS = {'stored_bytes_read': 0, 'metadata_decoded_bytes': 0, 'files_hashed': 0}

def need(value, detail):
    if not value:
        raise ValueError(detail)

def canonical(value):
    return json.dumps(value, sort_keys=True, ensure_ascii=False, separators=(',', ':'), allow_nan=False).encode()

def save(name, value):
    with (HERE / name).open('xb') as stream:
        stream.write(canonical(value) + b'\n')

def receipt(path):
    path = Path(path).resolve()
    need(path.is_file(), 'missing regular artifact: ' + str(path))
    digest, size = sha256(), 0
    with path.open('rb') as stream:
        for block in iter(lambda: stream.read(65536), b''):
            size += len(block)
            COUNTS['stored_bytes_read'] += len(block)
            need(COUNTS['stored_bytes_read'] <= 64_000_000, 'stored input budget exceeded')
            digest.update(block)
    COUNTS['files_hashed'] += 1
    return {'path': str(path), 'sha256': digest.hexdigest(), 'bytes': size}

def metadata(path, limit=2_000_000):
    path = Path(path)
    need(path.stat().st_size <= limit, 'metadata stored ceiling exceeded')
    raw = path.read_bytes()
    COUNTS['stored_bytes_read'] += len(raw)
    need(COUNTS['stored_bytes_read'] <= 64_000_000, 'stored input budget exceeded')
    if path.suffix == '.gz':
        with gzip.GzipFile(fileobj=BytesIO(raw)) as stream:
            payload = stream.read(limit + 1)
    else:
        payload = raw
    need(len(payload) <= limit, 'metadata decoded ceiling exceeded')
    COUNTS['metadata_decoded_bytes'] += len(payload)
    need(COUNTS['metadata_decoded_bytes'] <= 4_000_000, 'metadata aggregate decoded ceiling exceeded')
    return json.loads(payload)

def resolve_ref(ref, root):
    return Path(ref['uri']) if ref['external'] else root / ref['uri']

def verify_ref(ref, root):
    actual = receipt(resolve_ref(ref, root))
    need((actual['bytes'], actual['sha256']) == (ref['physical_bytes'], ref['physical_sha256']),
         'stored reference SHA/size differs: ' + actual['path'])
    return actual

def main():
    def expired(*_):
        raise TimeoutError('postflight wall45s ceiling exceeded')
    signal.signal(signal.SIGALRM, expired)
    signal.setitimer(signal.ITIMER_REAL, 45)
    try:
        prepared = metadata(HERE / 'freeze.json')
        need(receipt(__file__) == prepared['entry'], 'postflight script changed')
        for row in prepared['small_inputs']:
            need(receipt(row['path']) == row, 'saved gate metadata/root changed')
        old = metadata(GATE / 'freeze.json')
        need(sha256(canonical(old)).hexdigest() == prepared['original_freeze_canonical_sha256'],
             'original freeze document differs')
        for row in old['sources']:
            need(receipt(row['path']) == row, 'original source freeze differs: ' + row['path'])
        failure = metadata(GATE / 'failure.json')
        unknown = '/home/zyf/miniconda3/envs/lewm/lib/python3.14/_compat_pickle.py'
        need(failure['detail'] == 'participating runtime module not frozen: ' + unknown,
             'terminal failure is not the reviewed runtime freeze failure')
        need(unknown not in {row['path'] for row in old['runtime']}, 'runtime omission classification differs')
        need(not (GATE / 'result.json').exists(), 'original gate result was unexpectedly backfilled')
        progress = [json.loads(line) for line in (GATE / 'progress.jsonl').read_text().splitlines()]
        plan = metadata(GATE / 'plan.json')['document']
        config = metadata(GATE / 'inputs.json')
        expected_keys = [(row['file_index'], row['body_index']) for row in plan['expectations']]
        passes = [row for row in progress if row.get('stage') == 'PUBLIC_READER_BODY' and row.get('status') == 'PASS']
        need([(row['file_index'], row['body_index']) for row in passes] == expected_keys,
             'three exact saved public-reader PASS records missing or reordered')
        need(progress[-1]['stage'] == 'FAILED' and progress[-1]['detail'] == failure['detail'],
             'saved progress terminal differs')
        publication_result = metadata(GATE / 'publication-result.json')
        composed = metadata(GATE / 'compose-result.json')
        need(composed == metadata(GATE / 'result/composition/summary.json'), 'saved composer summaries differ')
        publication_root = GATE / 'result/publication'
        manifest_path = publication_root / 'manifest.json'
        manifest = metadata(manifest_path)
        need(manifest['schema'] == 'scar.partitioned-program-inventory' and manifest['schema_version'] == 2,
             'unexpected published manifest schema')
        need(manifest['capabilities'] == ['SOURCE_PROGRAM5_ADMISSION_V1', 'SOURCE_BODY_REVISION_V1'],
             'published capability pair differs')
        need(manifest['counts'] == publication_result['counts'], 'saved manifest counts differ')
        for ref in list(manifest['components'].values()) + manifest['files']:
            if not ref['external']:
                verify_ref(ref, publication_root)
        def component(name):
            document = metadata(resolve_ref(manifest['components'][name], publication_root))
            need(document['name'] == name, 'published component name differs')
            return document['value']
        publication, header = component('publication'), component('header')
        need(publication['code_source_origin'] == old['original_code_source_origin'], 'original compiler origin differs')
        need(publication['base_composition'] == plan['base_composition'] and
             publication['base_inventory'] == plan['base_inventory'], 'publication exact parent differs')
        need(publication['changed_bodies'] == publication_result['changed_bodies'], 'saved changed-body receipts differ')
        need([(row['file_index'], row['body_index']) for row in publication['changed_bodies']] == expected_keys,
             'published change inventory differs')
        graph_references = []
        for changed, expectation, original in zip(publication['changed_bodies'], plan['expectations'], config['programs']):
            need(changed['operation'] == expectation['operation'] == 'ADD_GRAPH', 'non-ADD operation')
            cp_ref = changed['checkpoint']
            verify_ref(cp_ref, publication_root)
            cp = metadata(resolve_ref(cp_ref, publication_root))
            need(cp['schema_version'] == 2 and cp['source_program'] == expectation['replacement'] == changed['source_program'],
                 'CP2 original graph reference differs')
            need(cp['construction_operations'] is None and cp['construction_cost_known'] is False,
                 'unknown construction cost was promoted')
            need(cp['body_identity']['definition'] == changed['definition'], 'CP2 qualified definition differs')
            actual = receipt(cp['source_program']['uri'])
            need(actual == {key: original['program'][key] for key in ('path', 'sha256', 'bytes')},
                 'original stored graph bytes/URI differ')
            graph_references.append({'file_index': changed['file_index'], 'body_index': changed['body_index'],
                'source_program': cp['source_program'], 'checkpoint': cp_ref,
                'original_operations_receipt': original['operations'],
                'typed_validation_reexecuted': False})
        need(manifest['counts']['graph_bodies'] == composed['summary']['counts']['canonical_bodies'] == 846,
             'published static body count differs')
        need(composed['summary']['inventory_denominators']['bodies'] == 2217 and composed['files_total'] == 151,
             'static denominator differs')
        need(header['summary']['body_statuses']['UNSUPPORTED'] == 781 and
             header['summary']['body_statuses']['NOT_ATTEMPTED'] == 590,
             'retained unsupported/not-attempted count differs')
        roots = {'manifest': receipt(manifest_path),
            'composition': receipt(GATE / 'result/composition/index.json.gz')}
        need(roots == prepared['published_roots'], 'stored publication/composition root bytes changed')
        report = {'schema': 'scar.kwargs-source-publication-postflight', 'schema_version': 1,
            'postflight_status': 'STORED_ARTIFACT_METADATA_CHECKS_PASS',
            'original_gate_status': 'FAILED_ENV_FREEZE', 'original_exit_code_reported_by_root': 1,
            'original_gate_elapsed_s': failure['elapsed_s'], 'original_failure': failure['detail'],
            'original_freeze': prepared['small_inputs'][0], 'published_roots': roots,
            'source_freeze_files_checked': len(old['sources']), 'source_freeze_current_bytes_match': True,
            'public_reader_passes_from_original_progress': passes, 'graph_references': graph_references,
            'manifest_counts': manifest['counts'], 'header_summary': header['summary'],
            'composition_summary': composed['summary'], 'original_parent': publication['base_composition'],
            'runtime_execution_bytes_missing_from_original_freeze': [unknown],
            'complete_historical_runtime_inventory': 'OPEN', 'historical_runtime_bytes_proved': False,
            'new_hash_not_used_to_retroactively_attest_runtime': True,
            'static_published_bodies': 846, 'latest_full_runtime_snapshot_bodies': 843,
            'current_runtime_rebound': False, 'whole_first_stage_established': False,
            'scope_and_collector_assumptions_remain_open': True,
            'composition_decoded_or_semantics_revalidated': False,
            'source_programs_decoded_or_typed_revalidated': False,
            'publisher_calls': 0, 'composer_calls': 0, 'lowering': 0, 'compile': 0, 'target': 0, 'raw': 0,
            'cost': {**COUNTS, 'elapsed_s': time.perf_counter() - STARTED,
                'max_rss_kib': resource.getrusage(resource.RUSAGE_SELF).ru_maxrss}}
        save('receipt.json', report)
        (HERE / 'RESULT.md').write_text(
            '# 已发布 kwargs source artifacts：最小 postflight\n\n'
            '原门实际 exit1，281.584s，状态 FAILED_ENV_FREEZE；原 freeze 与失败保留。\n'
            'publisher/composer 已完成，三项公共 reader 在原 progress 中逐项 PASS。\n'
            '本 postflight 仅核保存的 metadata、stored SHA/引用及源码 freeze；没有重跑这些 producer 或 typed 检查。\n\n'
            '静态源码已发布846/2217 bodies、151 files，781 UNSUPPORTED、590 NOT_ATTEMPTED。\n'
            '最新完整 runtime 接线仍绑定843快照，未因静态发布自动变更。\n\n'
            '原 _compat_pickle.py 未预冻结；本轮不测其新 hash 来追认执行时字节，完整 historical runtime inventory 亦未补齐。\n'
            '产物可读与原门资格分开：本次 metadata 检查通过不把原门改称 PASS。\n'
            '旧 scope 债务、collector 实现 provenance、内容/state/ready、完整 kwargs lifetime 及第一阶段仍 OPEN。\n\n'
            '根、三份原图引用、原三 PASS 及准确成本见 receipt.json。composition 只核 stored SHA，未重新解码。\n')
        print(json.dumps({'status': report['postflight_status'], 'original_gate': report['original_gate_status'],
            'roots': roots, 'cost': report['cost']}))
    except BaseException as error:
        save('failure.json', {'type': type(error).__name__, 'detail': str(error),
            'traceback': traceback.format_exc(), 'original_gate_unchanged': True, 'cost': COUNTS})
        raise
    finally:
        signal.setitimer(signal.ITIMER_REAL, 0)

if __name__ == '__main__':
    main()
