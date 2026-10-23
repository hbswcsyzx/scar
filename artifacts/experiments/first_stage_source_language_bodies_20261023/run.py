"""Bounded static source-language gate: one archived source, two real bodies.

No prepare_source, target execution, trace import, or new CodeWitness compile.
The old 272038 composition supplies static witnesses only, never new Run facts.
"""
from __future__ import annotations

import ast
from dataclasses import replace
import gzip
from hashlib import sha256
import json
from pathlib import Path
import resource
import subprocess
import sys
import time
import tokenize
import traceback


HERE = Path(__file__).resolve().parent
ROOT = HERE.parents[2]
EXPERIMENTS = HERE.parent
FREEZE = EXPERIMENTS / 'first_stage_source_language_implementation_20261023/freeze.json'
COMPOSITION = EXPERIMENTS / 'first_stage_partitioned_composition_bindings_20261023/composition/index.json.gz'
STORE = EXPERIMENTS / 'first_stage_partitioned_operand_routes_20261023/result/code-witnesses'
started = time.perf_counter()
log = (HERE / 'progress.jsonl').open('x', buffering=1)
out = HERE / 'result'
out.mkdir(exist_ok=False)


def write(stage, **fields):
    log.write(json.dumps({'stage': stage, 'elapsed_s': time.perf_counter() - started,
        'max_rss_kib': resource.getrusage(resource.RUSAGE_SELF).ru_maxrss, **fields}) + '\n')


def receipt(path):
    raw = Path(path).read_bytes()
    return {'path': str(Path(path).resolve()), 'sha256': sha256(raw).hexdigest(), 'bytes': len(raw)}


def frozen():
    doc = json.loads(FREEZE.read_text())
    for row in doc['modules']:
        if receipt(ROOT / row['path'])['sha256'] != row['sha256']:
            raise ValueError('frozen language producer drifted: ' + row['path'])
    return doc


def save(name, doc):
    raw = (json.dumps(doc, sort_keys=True, separators=(',', ':'), allow_nan=False) + '\n').encode()
    if len(raw) > 32_000_000:
        raise ValueError('independent per-body 32MB output ceiling exceeded')
    path = out / name
    with path.open('xb') as stream:
        with gzip.GzipFile(filename='', fileobj=stream, mode='wb', mtime=0) as zipped:
            zipped.write(raw)
    return {**receipt(path), 'decoded_sha256': sha256(raw).hexdigest(), 'decoded_bytes': len(raw)}


try:
    freeze = frozen()
    producer = {'head_at_start': subprocess.check_output(['git', 'rev-parse', 'HEAD'], cwd=ROOT, text=True).strip(),
        'script': receipt(__file__), 'freeze': receipt(FREEZE), 'composition': receipt(COMPOSITION),
        'code_witness_manifest': receipt(STORE / 'manifest.json'), 'source_file_count': 1,
        'source_body_indices': [[140, 11], [140, 26]], 'max_operations_per_body': 4000,
        'source_prepare_ceiling': 0, 'compile_ceiling': 0, 'target_executed': False,
        'current_run_integration_performed': False}
    (HERE / 'producer.json').write_text(json.dumps(producer, indent=2) + '\n')
    write('imports', status='BEGIN')
    from scar.analysis.code_witness import CodeWitnessStore
    from scar.analysis.program_composition import CompositionIndex
    from scar.analysis.program_lowering import PreparedSource, SourceProgram, _symbol_tables, validate_source_program
    from scar.analysis.source_language import SourceCodeEvidence, SourceLanguageOptions
    from scar.analysis.structured_lowering import require_valid_structured_body
    from scar.ir.program.call_edges import CapturedCode, CodeSourceLink, CallLinkStatus
    from scar.ir.program.functions import BodyLoweringProfile
    from scar.ir.record_codec import decode, encode
    write('imports', status='END')

    composition = CompositionIndex(COMPOSITION)
    write('one_source', status='BEGIN', file_index=140)
    source = composition.source(140)
    path = Path(source.snapshot.path)
    with tokenize.open(path) as stream:
        text = stream.read()
    if 'sha256:' + sha256(text.encode()).hexdigest() != source.snapshot.fingerprint:
        raise ValueError('current exact source differs from archived source snapshot')
    tree = ast.parse(text, filename=str(path))
    context = PreparedSource(path, Path(source.context.namespace_root), text, source.semantic,
        source.semantics, source.control, tree, _symbol_tables(text, path))
    (HERE / 'source-input.json').write_text(json.dumps({'file_index': 140,
        'snapshot': encode(source.snapshot), 'context': encode(source.context),
        'source_artifact': source.metadata, 'current_source': receipt(path),
        'source_prepared': False, 'source_ast_and_symtable_parsed': True}, indent=2) + '\n')
    store = CodeWitnessStore(STORE)
    model = composition.inventory_component('call_sources')['model']
    captures = {}
    for row in model['codes']:
        captured = decode(CapturedCode, row['code'])
        if captured.key in captures and captures[captured.key] != captured:
            raise ValueError('captured descriptor conflict')
        captures[captured.key] = captured
    links = [decode(CodeSourceLink, row) for row in model['code_links']]
    write('one_source', status='END')
    results = []
    for body_index in (11, 26):
        write('body', status='BEGIN', file_index=140, body_index=body_index)
        original = composition.inventory_body(140, body_index)
        definition = composition.document['files'][140]['bodies'][body_index]['definition']
        candidates = [link for link in links if link.status is CallLinkStatus.VERIFIED
            and link.snapshot == source.snapshot and link.definition is not None and link.definition.wire == definition]
        if len(candidates) != 1:
            raise ValueError('real body has no unique original complete code/source link')
        link, = candidates
        evidence = SourceCodeEvidence(store, composition, captures[link.code])
        options = SourceLanguageOptions(code_evidence=evidence)
        body = context.lower(original['metadata']['entry'], source=link.source,
            profile=BodyLoweringProfile.STRUCTURED_ENV, expand_candidates=False,
            max_operations=4000, language_options=options)
        program = SourceProgram(body.graph, body.metadata, context.semantic, context.semantics,
            context.control, BodyLoweringProfile.STRUCTURED_ENV, body.interface, body.frame,
            body.structured, body.language)
        document = program.to_dict()
        artifact = save(f'body-{body_index:02d}.source-program5.json.gz', document)
        checks = {'source_replay': 'NOT_REQUESTED_NO_SOURCE_REPREPARE', 'source_program5': document['schema_version'] == 5}
        # This public read validates the stored graph, original source layers,
        # and language structural overlay without code/source proof elevation.
        loaded = SourceProgram.read_structure(document, max_operations=4000)
        checks['stored_structure'] = validate_source_program(loaded, verification='STRUCTURE', max_operations=4000)
        checks['canonical_roundtrip'] = loaded.to_dict() == document
        if body.graph is not None:
            require_valid_structured_body(loaded.structured, loaded.graph, loaded.interface,
                loaded.metadata, semantic=loaded.semantic, control=loaded.control,
                language=loaded.language, source_tree=tree, language_options=options)
            checks['exact_source_and_independent_code_witness'] = True
            for variant in ('producer_v4', 'parser_v4'):
                try:
                    if variant == 'producer_v4':
                        replace(program, language=None).to_dict()
                    else:
                        old = dict(document); old['schema_version'] = 4; del old['language']
                        SourceProgram.from_dict(old, max_operations=4000)
                except ValueError as error:
                    if 'historical source wrapper' not in str(error):
                        raise
                    checks[variant + '_rejects_new_protocols'] = str(error)
                else:
                    raise ValueError(variant + ' accepted an extended language protocol')
            try:
                SourceProgram.from_dict(document, max_operations=4000)
            except ValueError as error:
                if 'independently supplied' not in str(error):
                    raise
                checks['v5_full_verification_requires_independent_inputs'] = str(error)
            else:
                raise ValueError('v5 claimed source/code proof from a report receipt alone')
        row = {'body_index': body_index, 'original_definition': definition, 'entry': body.metadata.entry,
            'original_inventory_locator': composition.inventory_body_locators(140, body_index),
            'body_recovered': body.graph is not None, 'operations_emitted': body.operations_emitted,
            'operation_count': len(body.graph.operations) if body.graph else 0,
            'language': encode(body.language), 'frontiers': encode(body.metadata.gaps),
            'checks': checks, 'artifact': artifact, 'current_run_integration_performed': False}
        results.append(row)
        write('body', status='END', body_index=body_index, recovered=row['body_recovered'],
            operations=row['operation_count'])
    if store.counts['compile_attempts'] != 0 or store.counts['source_bytes_read'] != 0:
        raise ValueError('read-only CodeWitness budget violated')
    frozen()
    modules = []
    for name, module in sorted(sys.modules.items()):
        path = getattr(module, '__file__', None)
        if name.startswith('scar.') and path and str(Path(path).resolve()).startswith(str(ROOT)):
            modules.append(receipt(Path(path).resolve()))
    summary = {'status': 'PASS_WITH_OPEN' if all(row['body_recovered'] for row in results) else 'RETAINED_BODY_FRONTIERS',
        'results': results, 'code_witness_counts': store.counts, 'code_witness': store.receipt(),
        'elapsed_s': time.perf_counter() - started, 'max_rss_kib': resource.getrusage(resource.RUSAGE_SELF).ru_maxrss,
        'source_prepare_count': 0, 'current_run_integration_performed': False,
        'runtime_code_instance_established': False, 'whole_program_established': False,
        'target_executed': False, 'actual_imported_modules': modules}
    (HERE / 'summary.json').write_text(json.dumps(summary, indent=2) + '\n')
    write('FINISHED', status=summary['status'])
    print(json.dumps({'status': summary['status'], 'elapsed_s': summary['elapsed_s'],
                      'code_witness_counts': store.counts, 'recovered_bodies': sum(row['body_recovered'] for row in results)}))
except BaseException as error:
    failure = {'status': 'ERROR_RETAINED_NO_RETRY', 'type': type(error).__name__, 'detail': str(error),
        'elapsed_s': time.perf_counter() - started, 'traceback': traceback.format_exc()}
    (HERE / 'failure.json').write_text(json.dumps(failure, indent=2) + '\n')
    write('FAILED', error_type=type(error).__name__, detail=str(error))
    raise
finally:
    log.close()
