"""F2 sidecar capture/replay over admitted F0/F1 source materials."""
from __future__ import annotations

import argparse
from collections import Counter
from concurrent.futures import ProcessPoolExecutor
import json
import multiprocessing
from pathlib import Path
import time

from scar.analysis.source_materials import _matches, _source_envelope
from scar.analysis.source_stage import SourceStage


def _parse_unit(task):
    from scar.analysis.source_syntax import read_source_syntax, source_syntax_document
    from scar.analysis.static_program import _write
    from scar.analysis.static_query import _Fragments
    root, staging, unit, mode, max_nodes, max_tokens = task
    reader = _Fragments(root)
    source = reader.read(unit['artifacts']['source'])
    size = _source_envelope(unit, source)
    f0 = reader.read(unit['artifacts']['source_bytes'])
    if not _matches(unit, source, f0, size):
        raise ValueError('F2 requires matching F0 source bytes')
    f1 = reader.read(unit['artifacts']['source_tokens'])
    if f1['max_tokens'] > max_tokens:
        raise ValueError('F1 replay budget exceeds the F2 --max-tokens limit')
    prior = unit['artifacts'].get('source_syntax')
    if prior is not None:
        document = reader.read(prior)
        if document['mode'] != mode or (document['max_nodes'] != max_nodes if staging is not None
                                      else document['max_nodes'] > max_nodes):
            raise ValueError('F2 mode or node budget differs from the admitted artifact')
        read_source_syntax(document, f0, f1)
        descriptor = prior
    elif staging is None:
        raise ValueError('F2 source-syntax artifact is absent')
    else:
        document = source_syntax_document(f0, f1, mode=mode, max_nodes=max_nodes)
        relative = 'units/' + unit['key'] + '/source_syntax.json.gz'
        if (Path(staging) / relative).exists():
            raise ValueError('new F2 sidecar would overwrite an existing artifact')
        descriptor = _write(Path(staging), relative, document)
    return {'unit': unit['key'], 'status': document['status'], 'artifact': descriptor,
        'upstream_status': document['input']['f1_status'], 'nodes': len(document['nodes']),
        'field_slots': sum(len(node['fields']) for node in document['nodes']),
        'attribute_slots': sum(len(node['attributes']) for node in document['nodes']),
        'observed_constructors': dict(Counter(node['constructor'] for node in document['nodes'])),
        'warning_count': len(document['warnings']), 'error': document['error'],
        'frontiers': document['frontiers']}


def model_source_syntax(model, out, *, mode='exec', max_nodes=1_000_000,
                        max_tokens=2_000_000, jobs=4, verify=False):
    if (mode not in ('exec', 'eval', 'single', 'func_type') or type(mode) is not str
            or type(max_nodes) is not int or max_nodes < 0
            or type(max_tokens) is not int or max_tokens < 0
            or type(jobs) is not int or not 1 <= jobs <= 32 or type(verify) is not bool):
        raise ValueError('F2 needs an exact parser mode and bounded jobs/node/token budgets')
    started = time.monotonic()
    with SourceStage(model, out, artifact='source_syntax', verify=verify,
            consumes=('source', 'source_bytes', 'source_tokens', 'source_syntax')) as stage:
        tasks = [(stage.root, stage.staging, unit, mode, max_nodes, max_tokens)
            for unit in stage.manifest['units']]
        if jobs == 1:
            rows = list(map(_parse_unit, tasks))
        else:
            with ProcessPoolExecutor(max_workers=jobs, mp_context=multiprocessing.get_context('spawn')) as pool:
                rows = list(pool.map(_parse_unit, tasks, chunksize=1))
        constructors = Counter()
        for row in rows:
            constructors.update(row['observed_constructors'])
        def covered(row):
            return row['status'] not in ('BUDGET_STOPPED', 'PARSER_RESOURCE_ERROR') and row['upstream_status'] != 'BUDGET_STOPPED'
        complete = all(covered(row) for row in rows)
        counts = dict(Counter(row['status'] for row in rows))
        report = {'schema': 'scar.source-syntax-verification' if verify else 'scar.source-syntax-gate',
            'schema_version': 1, 'stage': 'F2', 'input_scope': 'DECLARED_MODEL_SOURCE_UNITS',
            'units': len(rows), 'covered_units': sum(covered(row) for row in rows),
            'complete_for_declared_units': complete,
            'all_declared_units_parsed': all(row['status'] == 'PARSED' for row in rows),
            'status_counts': counts, 'nodes': sum(row['nodes'] for row in rows),
            'field_slots': sum(row['field_slots'] for row in rows),
            'attribute_slots': sum(row['attribute_slots'] for row in rows),
            'observed_constructors': dict(sorted(constructors.items())),
            'warning_count': sum(row['warning_count'] for row in rows), 'results': rows,
            'mode': mode, 'jobs': jobs, 'parser_executed': any(row['status'] != 'UPSTREAM_NOT_TOKENIZED' for row in rows),
            'symtable_executed': False, 'target_executed': False, 'later_stages_verified': False,
            'whole_program_complete': False}
        if not verify and complete:
            stage.publish(rows, {'schema': 'scar.source-syntax-inventory', 'schema_version': 1,
                'stage': 'F2', 'scope': 'DECLARED_MODEL_SOURCE_UNITS', 'units': len(rows),
                'nodes': report['nodes'], 'mode': mode, 'status_counts': counts,
                'later_stages_verified': False, 'whole_program_complete': False})
        report['seconds'] = time.monotonic() - started
        return stage.finish(report)


def main(argv=None):
    from scar.analysis.static_program import _json, _write
    parser = argparse.ArgumentParser(prog='scar source-syntax')
    group = parser.add_mutually_exclusive_group(required=True)
    group.add_argument('--model')
    group.add_argument('--file')
    parser.add_argument('--out', required=True)
    parser.add_argument('--namespace-root')
    parser.add_argument('--mode', choices=('exec', 'eval', 'single', 'func_type'), default='exec')
    parser.add_argument('--jobs', type=int, default=4)
    parser.add_argument('--max-nodes', type=int, default=1_000_000)
    parser.add_argument('--max-tokens', type=int, default=2_000_000)
    parser.add_argument('--max-bytes', type=int, default=64 * 1024 * 1024)
    parser.add_argument('--verify', action='store_true')
    args = parser.parse_args(argv)
    if args.max_nodes < 0 or args.max_tokens < 0:
        parser.error('node/token budgets must be nonnegative')
    if args.model:
        report = model_source_syntax(args.model, args.out, mode=args.mode,
            max_nodes=args.max_nodes, max_tokens=args.max_tokens, jobs=args.jobs, verify=args.verify)
        print(_json({k: report[k] for k in ('stage', 'units', 'nodes', 'status_counts',
            'complete_for_declared_units', 'seconds', 'symtable_executed', 'later_stages_verified')}).decode().strip())
        return 0 if report['complete_for_declared_units'] else 1
    if args.verify:
        parser.error('--verify requires --model')
    from scar.analysis.source_lexing import main as lex_main
    from scar.analysis.source_syntax import source_syntax_document
    from scar.analysis.static_query import _Fragments
    upstream_args = ['--file', args.file, '--out', args.out,
        '--max-bytes', str(args.max_bytes), '--max-tokens', str(args.max_tokens)]
    if args.namespace_root:
        upstream_args += ['--namespace-root', args.namespace_root]
    code = lex_main(upstream_args)
    out = Path(args.out).absolute()
    upstream = json.loads((out / 'result.json').read_bytes())
    if upstream['schema'] != 'scar.source-token-file':
        return code
    reader = _Fragments(out)
    document = source_syntax_document(reader.read(upstream['source_bytes']),
        reader.read(upstream['artifact']), mode=args.mode, max_nodes=args.max_nodes)
    descriptor = _write(out, 'source_syntax.json.gz', document)
    report = {'schema': 'scar.source-syntax-file', 'schema_version': 1, 'stage': 'F2',
        'source_bytes': upstream['source_bytes'], 'source_tokens': upstream['artifact'],
        'artifact': descriptor, 'status': document['status'], 'nodes': len(document['nodes']),
        'symtable_executed': False, 'target_executed': False, 'later_stages_verified': False}
    (out / 'result.json').write_bytes(_json(report))
    print(_json(report).decode().strip())
    return 1 if document['status'] in ('BUDGET_STOPPED', 'PARSER_RESOURCE_ERROR') or code else 0


__all__ = ['model_source_syntax', 'main']
