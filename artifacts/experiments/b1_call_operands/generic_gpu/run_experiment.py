"""Run bounded public CLI CUDA evidence and retain every command/output."""
from __future__ import annotations

import argparse
import gzip
import hashlib
import json
import os
from pathlib import Path
import resource
import subprocess
import sys
import time

BASE = Path(__file__).resolve().parent
SCAR = Path('/tmp/scar-call-operands-fe9ytsud')
PROJECT = BASE / 'project'
RECEIPT = BASE / 'receipt.json'


def save(document):
    RECEIPT.write_text(json.dumps(document, indent=2, sort_keys=True) + '\n')


def sha(path):
    digest = hashlib.sha256()
    with path.open('rb') as stream:
        for block in iter(lambda: stream.read(1024 * 1024), b''):
            digest.update(block)
    return digest.hexdigest()


def read(path):
    with gzip.open(path, 'rt') if path.suffix == '.gz' else path.open() as stream:
        return json.load(stream)


def command(receipt, name, arguments, *, cwd=PROJECT, timeout=180):
    out, err = BASE / 'logs' / (name + '.stdout'), BASE / 'logs' / (name + '.stderr')
    environment = dict(os.environ, PYTHONPATH=str(SCAR), PYTHONDONTWRITEBYTECODE='1')
    for key in tuple(environment):
        if key.startswith('SCAR_'):
            environment.pop(key)
    started = time.perf_counter()
    entry = {'name': name, 'argv': list(map(str, arguments)), 'cwd': str(cwd),
             'stdout': str(out), 'stderr': str(err), 'timeout_seconds': timeout,
             'PYTHONPATH': str(SCAR), 'PYTHONDONTWRITEBYTECODE': '1'}
    with out.open('wb') as stdout, err.open('wb') as stderr:
        try:
            process = subprocess.run(entry['argv'], cwd=cwd, env=environment,
                                     stdout=stdout, stderr=stderr, timeout=timeout)
            entry['returncode'] = process.returncode
        except subprocess.TimeoutExpired:
            entry['returncode'] = None
            entry['timed_out'] = True
    entry['elapsed_seconds'] = time.perf_counter() - started
    entry['stdout_bytes'], entry['stderr_bytes'] = out.stat().st_size, err.stat().st_size
    receipt['commands'].append(entry)
    save(receipt)
    if entry['returncode'] != 0:
        raise RuntimeError(name + ' failed; raw files and complete logs retained')
    return out


def cli(receipt, name, *arguments, timeout=180):
    return command(receipt, name, [sys.executable, '-m', 'scar.cli', *map(str, arguments)], timeout=timeout)


def main():
    parser = argparse.ArgumentParser()
    parser.add_argument('--micro-only', action='store_true')
    arguments = parser.parse_args()
    if RECEIPT.exists():
        receipt = read(RECEIPT)
    else:
        receipt = {'schema': 'scar.b1-generic-gpu-experiment', 'schema_version': 1,
                   'source_worktree': str(SCAR), 'expected_commit': 'c91876b73ed7b15351a0cb925d17c2e017d2c88d',
                   'project_root': str(PROJECT), 'tensor_values_saved': False, 'commands': [],
                   'wall_started_unix': time.time(), 'status': 'STARTED'}
        command(receipt, 'source_head_before', ['git', 'rev-parse', 'HEAD'], cwd=SCAR)
        command(receipt, 'source_status_before', ['git', 'status', '--porcelain=v1'], cwd=SCAR)
        command(receipt, 'gpu_before', ['nvidia-smi', '--query-gpu=index,name,uuid,memory.total,memory.used,driver_version', '--format=csv,noheader'])
        receipt['input_files'] = [{'path': str(path), 'bytes': path.stat().st_size, 'sha256': sha(path)}
                                  for path in [PROJECT / 'helper.py', PROJECT / 'entry.py', BASE / 'driver.py', Path(__file__)]]
        save(receipt)
    try:
        names = {entry['name'] for entry in receipt['commands']}
        if 'untraced_original' not in names:
            output = command(receipt, 'untraced_original', [sys.executable, BASE / 'driver.py'])
            receipt['untraced_runtime'] = json.loads(output.read_text().splitlines()[-1])
            receipt['status'] = 'MICRO_ORIGINAL_PASSED'
            save(receipt)
        if arguments.micro_only:
            return
        raw, inventory, report = BASE / 'raw', BASE / 'reports' / 'inventory.json.gz', BASE / 'reports' / 'operands.json.gz'
        if raw.exists() or inventory.exists() or report.exists():
            raise RuntimeError('refusing to overwrite an existing public pipeline; retained for inspection')
        traced = cli(receipt, 'trace', 'trace', '--call-operands', '--project-root', PROJECT,
                     '--out', raw, '--max-call-events', 100000, '--max-call-bytes', 64000000,
                     '--max-operand-events', 100000, '--max-operand-bytes', 32000000,
                     '--', sys.executable, BASE / 'driver.py')
        runtime_lines = [line for line in traced.read_text().splitlines() if 'CUDA_AUTOGRAD_COMPLETED' in line]
        if len(runtime_lines) != 1:
            raise RuntimeError('expected one runtime state receipt from traced original program')
        receipt['traced_runtime'] = json.loads(runtime_lines[0])
        save(receipt)
        cli(receipt, 'inventory', 'inventory-program', PROJECT / 'entry.py', '--project-root', PROJECT,
            '--calls', raw, '--out', inventory)
        cli(receipt, 'link', 'link-operands', raw, '--project-root', PROJECT,
            '--inventory', inventory, '--out', report)
        cli(receipt, 'check', 'check-operand-links', report)
        document, inventory_document = read(report), read(inventory)
        analysis = document['analysis']
        routing = analysis['routing']
        definitions = {item['id']['wire']: item['qualname']
                       for file in inventory_document['files'] for item in file['definitions']}
        runs = sorted([value for value in routing['returns'] if definitions[value['definition']['wire']] == 'run'],
                      key=lambda value: (value['invocation']['process_id'], value['invocation']['thread_id'],
                                         value['invocation']['invocation_id']))
        if len(runs) != 2:
            raise RuntimeError('expected two automatically resolved run return roots')
        queries = []
        for mode, root in zip(('distinct', 'shared'), runs):
            invocation = root['invocation']
            output = cli(receipt, 'query_' + mode, 'query-operand-refs', report,
                         '--process', invocation['process_id'], '--thread', invocation['thread_id'],
                         '--invocation', invocation['invocation_id'])
            query_document = json.loads(output.read_text())
            (BASE / 'reports' / ('query_' + mode + '.json')).write_text(json.dumps(query_document, indent=2, sort_keys=True) + '\n')
            query = query_document['query']
            endpoints = [(value['invocation'], definitions[value['definition']['wire']], value['formal_name'])
                         for value in query['endpoints']]
            if endpoints != [(invocation, 'run', 'x')]:
                raise RuntimeError('public query does not reach only this run.x: ' + repr(endpoints))
            completions = [step['completion'] for step in query['routes'] if step['kind'] == 'COMPLETION']
            if len(completions) != 2 or {definitions[value['callee_definition']['wire']] for value in completions} != {'relay', 'choose'}:
                raise RuntimeError('public query does not traverse exactly run->relay->choose completions')
            if any(query[key] is not False for key in ('function_environment_established', 'contents_or_effects_established',
                                                       'world_equivalence_established', 'transformation_authorized')):
                raise RuntimeError('query authority unexpectedly increased')
            if not query['conditional_only'] or not query['conditions'] or not query['obligations']:
                raise RuntimeError('query lost explicit conditions or frame obligations')
            queries.append({'mode': mode, 'invocation': invocation,
                            'endpoints': [{'invocation': invocation, 'definition': 'run', 'formal_name': 'x'}],
                            'completion_route_count': len(completions), 'route_count': len(query['routes']),
                            'conditions': query['conditions'], 'issue_kinds': [issue['kind'] for issue in query['issues']]})
        choose = {}
        for route in routing['argument_routes']:
            if definitions[route['callee_definition']['wire']] == 'choose':
                key = tuple(route['callee'][name] for name in ('process_id', 'thread_id', 'invocation_id'))
                choose.setdefault(key, []).append(route)
        if len(choose) != 4:
            raise RuntimeError('expected four actual choose invocations')
        for routes in choose.values():
            if not (len(routes) == 2 and {route['actual_index'] for route in routes} == {0, 1}
                    and len({route['actual_use']['wire'] for route in routes}) == 2
                    and len({(route['load_anchor']['index'], route['load_suboperand']) for route in routes}) == 2):
                raise RuntimeError('choose actual Use or operand occurrence was collapsed')
        receipt['validation'] = {'queries': queries, 'choose_invocations': len(choose),
                                 'choose_actual_routes': sum(map(len, choose.values())),
                                 'choose_uses_and_occurrences_distinct': True,
                                 'inventory_schema_version': inventory_document['schema_version'],
                                 'public_report_summary': analysis.get('summary'),
                                 'whole_program_complete': analysis['whole_program_complete'],
                                 'authority_remains_conditional': True}
        receipt['raw_manifest'] = [{'path': str(path), 'bytes': path.stat().st_size, 'sha256': sha(path)}
                                   for path in sorted(raw.iterdir()) if path.is_file()]
        receipt['report_manifest'] = [{'path': str(path), 'bytes': path.stat().st_size, 'sha256': sha(path)}
                                      for path in sorted((BASE / 'reports').iterdir()) if path.is_file()]
        command(receipt, 'gpu_after', ['nvidia-smi', '--query-gpu=index,name,uuid,memory.total,memory.used,driver_version', '--format=csv,noheader'])
        command(receipt, 'source_head_after', ['git', 'rev-parse', 'HEAD'], cwd=SCAR)
        command(receipt, 'source_status_after', ['git', 'status', '--porcelain=v1'], cwd=SCAR)
        if (BASE / 'logs/source_head_before.stdout').read_bytes() != (BASE / 'logs/source_head_after.stdout').read_bytes():
            raise RuntimeError('frozen commit changed during experiment')
        if (BASE / 'logs/source_status_before.stdout').read_bytes() != (BASE / 'logs/source_status_after.stdout').read_bytes():
            raise RuntimeError('source status changed during experiment')
        receipt['status'] = 'PUBLIC_PIPELINE_PASSED'
    except Exception as error:
        receipt['status'] = 'FAILED_RETAINED'
        receipt['error'] = type(error).__name__ + ': ' + str(error)
        raise
    finally:
        usage = resource.getrusage(resource.RUSAGE_CHILDREN)
        receipt['child_cpu_user_seconds'] = usage.ru_utime
        receipt['child_cpu_system_seconds'] = usage.ru_stime
        receipt['child_peak_rss_kib'] = usage.ru_maxrss
        receipt['commands_total_elapsed_seconds'] = sum(entry['elapsed_seconds'] for entry in receipt['commands'])
        receipt['artifact_bytes_excluding_receipt'] = sum(path.stat().st_size for path in BASE.rglob('*')
                                                        if path.is_file() and path != RECEIPT)
        receipt['wall_finished_unix'] = time.time()
        save(receipt)


if __name__ == '__main__':
    main()
