"""ONE 272038 read/compile/route gate. No target execution or source preparation."""
import gzip
import hashlib
import json
from pathlib import Path
import resource
import shutil
import sys
import time

from prepare import HERE, ROOT, BASE, CAPTURE, CACHE, receipt


started = time.perf_counter()
progress = (HERE / 'progress.jsonl').open('x', buffering=1)
frozen = json.loads((HERE / 'frozen/producer.json').read_text())
expected = {row['path']: row for row in frozen['modules']}
RESULT = HERE / 'result'


def notify(row):
    progress.write(json.dumps({'elapsed_s': time.perf_counter() - started,
        'max_rss_kib': resource.getrusage(resource.RUSAGE_SELF).ru_maxrss, **row}, ensure_ascii=False) + '\n')


def exact_sources(*, initial=False):
    changed = []
    imported = {str(Path(module.__file__).resolve()) for module in tuple(sys.modules.values())
        if getattr(module, '__file__', None) and str(Path(module.__file__).resolve()).startswith(str(ROOT / 'scar') + '/')}
    mandatory = {str(ROOT / name) for name in ('scar/analysis/code_witness.py',
        'scar/analysis/source_body_access.py', 'scar/analysis/call_edges.py', 'scar/analysis/call_operands.py',
        'scar/analysis/call_operand_routes.py', 'scar/analysis/callable_environment_import.py',
        'scar/analysis/program_composition.py', 'scar/analysis/source_layers.py',
        'scar/analysis/source_attachments.py', 'scar/ir/program/source_references.py',
        'scar/analysis/source_invocations.py')}
    selected = imported | mandatory | {str(HERE / name) for name in ('run.py', 'prepare.py', 'run.sh')}
    actual_rows = []
    for name in sorted(selected):
        if name not in expected:
            changed.append({'unrecorded_imported_source': name})
            continue
        old = expected[name]
        path = Path(name)
        current = receipt(path)
        if current != old:
            changed.append({'before': old, 'after': current})
        actual_rows.append(current)
    if changed:
        raise ValueError('frozen producer module drift: ' + json.dumps(changed))
    if not initial:
        destination = HERE / 'frozen/participating-source-evidence'
        destination.mkdir(exist_ok=True)
        for row in actual_rows:
            output = destination / (row['sha256'] + '.py-source')
            if not output.exists():
                shutil.copyfile(row['path'], output)
        path = HERE / 'participating-producer.json'
        path.write_text(json.dumps({'actual_imports': sorted(imported), 'checked': actual_rows,
            'sha_unchanged': True, 'candidate_unused_sources_not_authority': True}, indent=2) + '\n')


def write_json(path, document):
    with path.open('x') as stream:
        json.dump(document, stream, ensure_ascii=False, sort_keys=True, allow_nan=False, indent=2)
        stream.write('\n')


def partitions(document):
    """Preserve one to_dict document in bounded reference-only gzip tables."""
    destination = RESULT / 'analysis'
    destination.mkdir()
    maximum = 16_000_000
    tables = {}

    def table(name, rows):
        chunks, pending, total, number = [], bytearray(), 0, 0
        def flush():
            nonlocal pending, number
            if not pending:
                return
            path = destination / (name + '.' + str(len(chunks)).zfill(4) + '.jsonl.gz')
            payload = bytes(pending)
            with path.open('xb') as raw:
                with gzip.GzipFile(fileobj=raw, mode='wb', filename='', mtime=0) as stream:
                    stream.write(payload)
            chunks.append({**receipt(path), 'decoded_sha256': hashlib.sha256(payload).hexdigest(),
                           'decoded_bytes': len(payload), 'rows': number})
            pending, number = bytearray(), 0
        for row in rows:
            raw = json.dumps(row, ensure_ascii=False, sort_keys=True, separators=(',', ':'), allow_nan=False).encode() + b'\n'
            if len(raw) > maximum:
                raise ValueError('one existing report record exceeds independent 16MB shard ceiling')
            if len(pending) + len(raw) > maximum or number == 1000:
                flush()
            pending.extend(raw)
            number += 1
            total += 1
        flush()
        tables[name] = {'rows': total, 'chunks': chunks}

    header = {key: value for key, value in document.items()
              if key not in ('routing', 'entry_parameters', 'environments', 'code_links')}
    table('code_links', document['code_links'])
    table('entry_parameters', document['entry_parameters'])
    routing = document['routing']
    header['routing'] = {key: value for key, value in routing.items() if type(value) is not list}
    for key, value in routing.items():
        if type(value) is list:
            table('routing.' + key, value)
    environment = document['environments']
    header['environments'] = {key: value for key, value in environment.items()
                              if key not in ('bindings', 'unresolved', 'files', 'metadata')}
    for key in ('bindings', 'unresolved', 'files', 'metadata'):
        table('environments.' + key, environment[key])
    raw = json.dumps(header, ensure_ascii=False, sort_keys=True, separators=(',', ':'), allow_nan=False).encode()
    if len(raw) > maximum:
        raise ValueError('report header exceeds independent 16MB shard ceiling')
    path = destination / 'header.json.gz'
    with path.open('xb') as out:
        with gzip.GzipFile(fileobj=out, mode='wb', filename='', mtime=0) as stream:
            stream.write(raw)
    digest, size = hashlib.sha256(), 0
    for text in json.JSONEncoder(ensure_ascii=False, sort_keys=True, separators=(',', ':'), allow_nan=False).iterencode(document):
        block = text.encode()
        digest.update(block)
        size += len(block)
    manifest = {'schema': 'scar.partitioned-call-operand-links', 'schema_version': 1,
        'original_schema': document['schema'], 'original_schema_version': document['schema_version'],
        'canonical_document_sha256': digest.hexdigest(), 'canonical_document_bytes': size,
        'header': {**receipt(path), 'decoded_sha256': hashlib.sha256(raw).hexdigest(), 'decoded_bytes': len(raw)},
        'tables': tables, 'max_shard_decoded_bytes': maximum, 'max_rows_per_shard': 1000,
        'table_pointer_rule': 'dot-separated table names replace that original JSON array; header holds all other fields',
        'canonical_graphs_copied': False, 'whole_program_established': False, 'transformation_authorized': False}
    write_json(destination / 'manifest.json', manifest)
    return manifest


status = 'FAILED'
try:
    exact_sources(initial=True)
    for old in frozen['inputs']:
        if receipt(old['path']) != old:
            raise ValueError('frozen input drift: ' + old['path'])
    RESULT.mkdir(exist_ok=False)
    notify({'stage': 'INPUT_RECEIPTS_VERIFIED', 'inputs': len(frozen['inputs'])})
    from scar.analysis.code_witness import CodeWitnessBudget, CodeWitnessStore
    from scar.analysis.program_composition import CompositionIndex
    from scar.analysis.call_operands import link_call_operands
    from scar.ir.program.call_edges import CallEdgeBudget
    from scar.ir.program.call_operands import CallOperandBudget
    from scar.ir.program.call_operand_routes import OperandRouteBudget
    from scar.ir.record_codec import encode
    from scar.trace.capture_coordinates import bind_capture_coordinates

    notify({'stage': 'COORDINATES_BEGIN'})
    coordinates = bind_capture_coordinates(CAPTURE, max_bytes=2_000_000_000,
        max_lines=2_000_000, profile_uri=str(RESULT / 'capture-coordinates.json'))
    if encode(coordinates.run) != frozen['source_run']:
        raise ValueError('current coordinate Run differs from old verified source Run')
    (RESULT / 'capture-coordinates.json').write_bytes(coordinates.payload)
    notify({'stage': 'COORDINATES_END', 'run': coordinates.run.id.value})
    composition = CompositionIndex(BASE / 'composition/index.json.gz')
    store = CodeWitnessStore(CACHE, budget=CodeWitnessBudget(max_compile_keys=20), progress=notify)
    if store.writable or store.compile_missing:
        raise ValueError('attempt02 CodeWitnessStore must be read-only')
    report = link_call_operands(CAPTURE / 'trace', '/home/zyf/AAA/le-wm',
        composition=composition, source_bindings=BASE / 'bindings', coordinates=coordinates,
        code_witnesses=store,
        frame_budget=CallEdgeBudget(max_raw_bytes=256_000_000, max_lines=300_000,
                                   max_events=250_000, max_references=2_000_000),
        operand_budget=CallOperandBudget(), route_budget=OperandRouteBudget(),
        include_environments=True, progress=notify)
    frame, operands = report.frame_model, report.operands
    actual = {'frame_entries': len(frame.edges), 'frame_exits': len(frame.exits),
        'entered_groups': len({(edge.entry.invocation.process_id, edge.entry.code) for edge in frame.edges}),
        'operand_events': len(operands.events), 'environment_events': report.environments['summary']['events']}
    expected_counts = {'frame_entries': 100438, 'frame_exits': 100438,
        'entered_groups': 817, 'operand_events': 312812, 'environment_events': 16403}
    if actual != expected_counts:
        raise ValueError('original denominators changed: ' + json.dumps(actual))
    if store.counts['compile_attempts'] != 0:
        raise ValueError('attempt02 must not compile any source')
    notify({'stage': 'TO_DICT_BEGIN'})
    serialization_start = time.perf_counter()
    document = report.to_dict()
    to_dict_seconds = time.perf_counter() - serialization_start
    notify({'stage': 'TO_DICT_END', 'to_dict_seconds': to_dict_seconds})
    write_start = time.perf_counter()
    archive = partitions(document)
    from collections import Counter
    rejection = Counter(item.kind.value for item in report.routing.issues)
    exact_sources()
    summary = {'status': 'ROUTES_RECONSTRUCTED_WITH_OPEN_OBLIGATIONS',
        'elapsed_s': time.perf_counter() - started, 'max_rss_kib': resource.getrusage(resource.RUSAGE_SELF).ru_maxrss,
        'original_denominators': actual, 'summary': report.summary(),
        'entry_parameter_occurrences': len(report.entry_parameters),
        'environment_summary': report.environments['summary'], 'route_issue_kinds': dict(rejection),
        'code_witness_activity': store.counts, 'code_witness_archive': store.receipt(),
        'code_witness_archive_reused_readonly': True, 'source_compiled_this_attempt': False,
        'source_body_summary': {key: value for key, value in report.source_body_access.items()
            if key in ('raw_counts', 'unbound_processes', 'bare_definition_conflicts', 'loaded_bodies',
                       'parsed_source_files', 'code_witness_frontiers')},
        'canonical_namespaces': len(report.source_body_access['namespaces']),
        'to_dict_seconds': to_dict_seconds, 'archive_seconds': time.perf_counter() - write_start,
        'canonical_report_bytes': archive['canonical_document_bytes'],
        'canonical_report_sha256': archive['canonical_document_sha256'],
        'producer_module_sha_unchanged': True, 'first_stage_complete': False,
        'target_executed': False, 'source_prepared': False, 'transformation_authorized': False}
    write_json(HERE / 'summary.json', summary)
    print(json.dumps(summary, ensure_ascii=False))
    status = 'PASS_WITH_OPEN_OBLIGATIONS'
except BaseException as error:
    failure = {'status': 'FAILED', 'type': type(error).__name__, 'detail': str(error),
        'elapsed_s': time.perf_counter() - started, 'max_rss_kib': resource.getrusage(resource.RUSAGE_SELF).ru_maxrss,
        'first_stage_complete': False, 'target_executed': False, 'transformation_authorized': False}
    write_json(HERE / 'failure.json', failure)
    notify({'stage': 'FAILED', **failure})
    raise
finally:
    try:
        exact_sources()
    except BaseException as drift:
        notify({'stage': 'PRODUCER_DRIFT', 'error': str(drift)})
    notify({'stage': 'FINISHED', 'status': status})
    progress.close()
