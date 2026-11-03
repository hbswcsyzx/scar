"""F1 publication over verified F0 materials; never enters the parser layer."""
from __future__ import annotations

import argparse
from collections import Counter
from concurrent.futures import ProcessPoolExecutor
from hashlib import sha256
import json
import multiprocessing
from pathlib import Path
import time

from scar.analysis.source_materials import _matches, _source_envelope
from scar.analysis.source_tokens import read_source_tokens, source_tokens_document


def _lex_unit(task):
    from scar.analysis.static_program import _write
    from scar.analysis.static_query import _Fragments
    root, staging, unit, max_tokens = task
    reader = _Fragments(root)
    source = reader.read(unit['artifacts']['source'])
    size = _source_envelope(unit, source)
    f0 = reader.read(unit['artifacts']['source_bytes'])
    if not _matches(unit, source, f0, size):
        raise ValueError('F1 requires matching, freshly verified F0 source bytes')
    prior = unit['artifacts'].get('source_tokens')
    if prior is not None:
        document = reader.read(prior)
        if staging is None and document['max_tokens'] > max_tokens:
            raise ValueError('F1 artifact replay budget exceeds the requested --max-tokens limit')
        if staging is not None and document['max_tokens'] != max_tokens:
            raise ValueError('existing F1 artifact has a different token budget')
        read_source_tokens(document, f0)
        descriptor = prior
    elif staging is None:
        raise ValueError('F1 source-token artifact is absent')
    else:
        document = source_tokens_document(f0, max_tokens=max_tokens)
        relative = 'units/' + unit['key'] + '/source_tokens.json.gz'
        if (Path(staging) / relative).exists():
            raise ValueError('new F1 sidecar would overwrite an existing artifact')
        descriptor = _write(Path(staging), relative, document)
    return {'unit': unit['key'], 'status': document['status'], 'artifact': descriptor,
        'tokens': len(document['tokens']), 'actual_eof': document['actual_eof'],
        'warning_count': len(document['warnings']), 'error': document['error'],
        'view_characters': document['view']['characters'] if document['view'] else 0,
        'source_gap_characters': sum(span['end'] - span['start']
            for span in document['source_coverage']['gaps']) if document['source_coverage'] else 0,
        'observed_token_types': dict(Counter(str(token['type']) for token in document['tokens']))}


def _parallel(tasks, jobs):
    if jobs == 1:
        return list(map(_lex_unit, tasks))
    # Tokenization and serialization are CPU work, and warnings contexts on
    # GIL builds share process globals. Threads are inappropriate here.
    with ProcessPoolExecutor(max_workers=jobs, mp_context=multiprocessing.get_context('spawn')) as pool:
        return list(pool.map(_lex_unit, tasks, chunksize=1))


def _report(rows, original, *, verify, seconds, jobs):
    counts, token_types = Counter(row['status'] for row in rows), Counter()
    for row in rows:
        token_types.update(row['observed_token_types'])
    complete = not counts['BUDGET_STOPPED']
    return {'schema': 'scar.source-token-verification' if verify else 'scar.source-token-gate',
        'schema_version': 1, 'stage': 'F1', 'input_scope': 'DECLARED_MODEL_SOURCE_UNITS',
        'units': len(rows), 'covered_units': sum(row['status'] != 'BUDGET_STOPPED' for row in rows),
        'complete_for_declared_units': complete,
        'all_declared_units_tokenized': all(row['status'] == 'TOKENIZED' for row in rows),
        'status_counts': dict(counts), 'tokens': sum(row['tokens'] for row in rows),
        'warning_count': sum(row['warning_count'] for row in rows),
        'observed_token_types': dict(sorted(token_types.items(), key=lambda item: int(item[0]))),
        'results': rows, 'prior_manifest_sha256': sha256(original).hexdigest(),
        'lexer_executed': True, 'parser_executed': False, 'target_executed': False,
        'later_stages_verified': False, 'whole_program_complete': False,
        'seconds': seconds, 'jobs': jobs}


def model_source_tokens(model, out, *, jobs=4, max_tokens=2_000_000, verify=False):
    """Append F1 shards, or freshly replay them without touching old layers."""
    from scar.analysis.source_stage import SourceStage
    if (type(jobs) is not int or not 1 <= jobs <= 32
            or type(max_tokens) is not int or max_tokens < 0 or type(verify) is not bool):
        raise ValueError('F1 requires bounded jobs and a nonnegative exact token budget')
    started = time.monotonic()
    with SourceStage(model, out, artifact='source_tokens', verify=verify,
            consumes=('source', 'source_bytes', 'source_tokens')) as stage:
        tasks = [(stage.root, stage.staging, unit, max_tokens) for unit in stage.manifest['units']]
        rows = _parallel(tasks, jobs)
        report = _report(rows, stage.original, verify=verify, jobs=jobs, seconds=0)
        if not verify and report['complete_for_declared_units']:
            stage.publish(rows, {'schema': 'scar.source-token-inventory', 'schema_version': 1,
                'stage': 'F1', 'scope': 'DECLARED_MODEL_SOURCE_UNITS', 'units': len(rows),
                'tokens': report['tokens'], 'status_counts': report['status_counts'],
                'later_stages_verified': False, 'whole_program_complete': False})
        report['seconds'] = time.monotonic() - started
        return stage.finish(report)


def main(argv=None):
    from scar.analysis.source_materials import main as source_materials_main
    from scar.analysis.static_program import _json, _write
    from scar.analysis.static_query import _Fragments
    parser = argparse.ArgumentParser(prog='scar source-tokens')
    group = parser.add_mutually_exclusive_group(required=True)
    group.add_argument('--model')
    group.add_argument('--file')
    parser.add_argument('--out', required=True)
    parser.add_argument('--namespace-root')
    parser.add_argument('--jobs', type=int, default=4)
    parser.add_argument('--max-tokens', type=int, default=2_000_000, help='per-source token budget')
    parser.add_argument('--max-bytes', type=int, default=64 * 1024 * 1024)
    parser.add_argument('--verify', action='store_true')
    args = parser.parse_args(argv)
    if args.max_tokens < 0:
        parser.error('--max-tokens must be nonnegative')
    if args.model:
        report = model_source_tokens(args.model, args.out, jobs=args.jobs,
            max_tokens=args.max_tokens, verify=args.verify)
        print(_json({k: report[k] for k in ('stage', 'units', 'tokens', 'status_counts',
            'complete_for_declared_units', 'seconds', 'parser_executed', 'later_stages_verified')}).decode().strip())
        return 0 if report['complete_for_declared_units'] else 1
    if args.verify:
        parser.error('--verify requires --model')
    # Reuse F0 acquisition so missing/raw-budget errors preserve their proper
    # stage and no lexical request can bypass raw material admission.
    f0_args = ['--file', args.file, '--out', args.out, '--max-bytes', str(args.max_bytes)]
    if args.namespace_root:
        f0_args += ['--namespace-root', args.namespace_root]
    code = source_materials_main(f0_args)
    if code:
        return code
    out = Path(args.out).absolute()
    receipt = json.loads((out / 'result.json').read_bytes())
    f0 = _Fragments(out).read(receipt['artifact'])
    document = source_tokens_document(f0, max_tokens=args.max_tokens)
    descriptor = _write(out, 'source_tokens.json.gz', document)
    report = {'schema': 'scar.source-token-file', 'schema_version': 1, 'stage': 'F1',
        'source_bytes': receipt['artifact'], 'artifact': descriptor, 'status': document['status'],
        'tokens': len(document['tokens']), 'actual_eof': document['actual_eof'],
        'parser_executed': False, 'target_executed': False, 'later_stages_verified': False}
    (out / 'result.json').write_bytes(_json(report))
    print(_json(report).decode().strip())
    return 0 if document['status'] != 'BUDGET_STOPPED' else 1


__all__ = ['model_source_tokens', 'main']
