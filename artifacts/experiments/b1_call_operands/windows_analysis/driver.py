#!/usr/bin/env python3
"""Run three public offline CLI phases against an already frozen raw trace.

This driver never executes the target program. Use the lewm Python interpreter.
Exit 0: phases completed with unchanged inputs (conditional, not whole-program).
Exit 1: failure retained. Exit 3: analysis completed but no normal-return query.
--out must name a directory that does not exist yet. No resume/overwrite occurs.
"""
from __future__ import annotations

import argparse
from collections import Counter
import gzip
import hashlib
import json
import math
import os
from pathlib import Path
import re
import resource
import subprocess
import sys
import time


REPORT_LIMIT = 256_000_000
COMMON_LIMITS = (
    '--max-files', '256', '--max-lowered-bodies', '256', '--max-operations', '10000',
    '--max-call-trace-bytes', '256000000', '--max-call-trace-lines', '300000',
    '--max-call-trace-events', '250000', '--max-call-references', '2000000',
    '--max-call-report-bytes', str(REPORT_LIMIT),
)
OPERAND_LIMITS = (
    '--max-operand-raw-bytes', '1250000000', '--max-operand-lines', '2000010',
    '--max-operand-events', '2000000', '--max-operand-loads', '2000000',
    '--max-operand-references', '4000000',
    '--operand-max-routes', '100000', '--operand-max-template-values', '100000',
)
AUTHORITY = (
    'target_executed_by_linker', 'function_environment_established',
    'contents_or_effects_established', 'world_equivalence_established',
    'whole_program_complete', 'transformation_authorized',
)


def write_json(path, document):
    temporary = path.with_name(path.name + '.tmp')
    with temporary.open('x', encoding='utf-8') as stream:
        json.dump(document, stream, indent=2, sort_keys=True, ensure_ascii=False, allow_nan=False)
        stream.write('\n')
    os.replace(temporary, path)


def hash_file(path):
    digest = hashlib.sha256()
    with path.open('rb') as stream:
        first = os.fstat(stream.fileno())
        for block in iter(lambda: stream.read(1024 * 1024), b''):
            digest.update(block)
        last = os.fstat(stream.fileno())
    if (first.st_dev, first.st_ino, first.st_size, first.st_mtime_ns) != (
            last.st_dev, last.st_ino, last.st_size, last.st_mtime_ns):
        raise RuntimeError('input changed while hashing: ' + str(path))
    return digest.hexdigest(), last.st_size


def source_fingerprint(root):
    """Exactly scripts/run_gate.py:fingerprint, with streaming per-file hashes."""
    paths = [*root.joinpath('scar').rglob('*.py'), *root.joinpath('tests').rglob('*.py'),
             *root.joinpath('scripts').rglob('*.py'), *root.joinpath('gates').glob('*.json'),
             root / 'pyproject.toml']
    if root.joinpath('sitecustomize.py').is_file():
        paths.append(root / 'sitecustomize.py')
    digests = {str(path.relative_to(root)): hash_file(path)[0] for path in sorted(paths)}
    combined = hashlib.sha256(json.dumps(digests, sort_keys=True).encode()).hexdigest()
    return {'sha256': combined, 'algorithm': 'scripts/run_gate.py:fingerprint', 'files': digests}


def raw_manifest(root):
    """Hash physical input files, including gzip bytes, without decompressing."""
    files = []
    for path in sorted(root.rglob('*')):
        if path.is_symlink() and path.is_dir():
            raise ValueError('raw manifest does not follow directory symlinks: ' + str(path))
        if not path.is_file():
            continue
        digest, size = hash_file(path)
        files.append({'path': str(path.relative_to(root)), 'resolved_path': str(path.resolve()),
                      'physical_bytes': size, 'sha256_file_bytes': digest})
    return {'root': str(root), 'files': files,
            'total_physical_bytes': sum(item['physical_bytes'] for item in files),
            'hash_scope': 'all regular files under trace; physical compressed bytes where .gz'}


def _finite(value):
    result = float(value)
    if not math.isfinite(result):
        raise ValueError('nonfinite JSON number')
    return result


def read_json(path):
    opener = gzip.open if path.name.endswith('.gz') else open
    with opener(path, 'rb') as stream:
        data = stream.read(REPORT_LIMIT + 1)
    if len(data) > REPORT_LIMIT:
        raise ValueError('driver JSON inspection exceeds decompressed report ceiling')
    def invalid(value):
        raise ValueError('invalid JSON constant: ' + value)
    return json.loads(data, parse_float=_finite, parse_constant=invalid)


def issue_counts(document):
    """Count actual serialized issue/gap/error records, never infer missing kinds."""
    counts = {}
    stack = [('', document)]
    while stack:
        location, value = stack.pop()
        if isinstance(value, dict):
            for name, child in value.items():
                child_location = location + ('.' if location else '') + name
                if name in ('issues', 'gaps', 'errors') and isinstance(child, list):
                    kinds = Counter()
                    for item in child:
                        if isinstance(item, dict):
                            kind = item.get('kind', item.get('reason', item.get('code', 'UNCLASSIFIED')))
                            if not isinstance(kind, str):
                                kind = 'UNCLASSIFIED'
                        elif isinstance(item, str):
                            kind = item
                        else:
                            kind = 'UNCLASSIFIED'
                        kinds[kind] += 1
                    existing = Counter(counts.get(child_location, {}))
                    existing.update(kinds)
                    counts[child_location] = dict(sorted(existing.items()))
                if isinstance(child, (list, dict)):
                    stack.append((child_location, child))
        elif isinstance(value, list):
            stack.extend((location + '[*]', child) for child in value if isinstance(child, (list, dict)))
    return dict(sorted(counts.items()))


def invocation_key(value):
    if (type(value) is not dict or set(value) != {'process_id', 'thread_id', 'invocation_id'}
            or any(type(item) is not int for item in value.values())):
        raise ValueError('invalid generated invocation identity')
    return value['invocation_id'], value['process_id'], value['thread_id']


def choose_query(routing):
    """Choose by invocation identity and evidence only, without source names."""
    returned = {invocation_key(item['invocation']): item['invocation'] for item in routing['returns']}
    callers = {invocation_key(item['caller']) for item in routing['completion_routes']}
    preferred = sorted(set(returned) & callers)
    fallback = sorted(returned)
    chosen = preferred[0] if preferred else fallback[0] if fallback else None
    return {'selection_rule': 'ascending (invocation_id, process_id, thread_id); prefer normal-return caller with completion',
            'normal_return_invocations': len(returned), 'preferred_invocations': len(preferred),
            'selected': returned[chosen] if chosen is not None else None,
            'status': 'SELECTED' if chosen is not None else 'NO_LEGAL_NORMAL_RETURN_QUERY'}


def time_metrics(path):
    result = {}
    for line in path.read_text(encoding='utf-8', errors='replace').splitlines():
        if ': ' in line:
            name, value = line.strip().split(': ', 1)
            result[name] = value
    peak = result.get('Maximum resident set size (kbytes)')
    return {'maximum_resident_set_kib': int(peak) if peak and peak.isdecimal() else None,
            'gnu_time_v': result}


class Run:
    def __init__(self, arguments, output, environment):
        self.args, self.output, self.environment = arguments, output, environment
        self.started = time.monotonic()
        self.progress = {'schema': 'scar.windows-external-analysis-progress', 'schema_version': 1,
                         'status': 'INITIALIZING', 'target_executed_by_driver': False,
                         'tensor_values_saved': False, 'transformation_authorized': False,
                         'inputs': {name: str(getattr(arguments, name)) for name in
                                    ('scar_root', 'project_root', 'entry', 'trace', 'out', 'source_sha')},
                         'python': sys.version, 'python_executable': sys.executable,
                         'exact_subprocess_environment': environment, 'phases': [], 'source_checks': []}
        self.save()

    def save(self):
        self.progress['elapsed_seconds'] = time.monotonic() - self.started
        write_json(self.output / 'progress.json', self.progress)

    def check_source(self, label, *, full=False):
        result = source_fingerprint(self.args.scar_root)
        self.progress['source_checks'].append({'label': label, 'sha256': result['sha256'],
                                               'matches_requested': result['sha256'] == self.args.source_sha})
        if full:
            write_json(self.output / ('source-' + label + '.json'), result)
        self.save()
        if result['sha256'] != self.args.source_sha:
            raise RuntimeError('source fingerprint mismatch at ' + label)

    def phase(self, name, arguments):
        self.check_source('before-' + name)
        base = self.output / name
        stdout, stderr, timing = (base.with_suffix('.stdout'), base.with_suffix('.stderr'),
                                  base.with_suffix('.time-v.txt'))
        logical = [sys.executable, '-m', 'scar.cli', *map(str, arguments)]
        exact = ['/usr/bin/time', '-v', '-o', str(timing), '--', *logical]
        phase = {'name': name, 'status': 'RUNNING', 'argv': exact, 'cli_argv': logical,
                 'cwd': str(self.args.scar_root), 'env': self.environment,
                 'stdout': str(stdout), 'stderr': str(stderr), 'time_v': str(timing),
                 'started_unix': time.time()}
        self.progress['status'], self.progress['active_phase'] = 'RUNNING', name
        self.progress['phases'].append(phase)
        self.save()
        begun = time.monotonic()
        try:
            with stdout.open('xb') as out, stderr.open('xb') as err:
                child = subprocess.run(exact, cwd=self.args.scar_root, env=self.environment,
                                       stdout=out, stderr=err, check=False)
            phase['returncode'] = child.returncode
            phase['status'] = 'PASSED' if child.returncode == 0 else 'FAILED'
        except BaseException as error:
            phase['status'] = 'FAILED'
            phase['launch_error'] = type(error).__name__ + ': ' + str(error)
            raise
        finally:
            phase['wall_seconds'] = time.monotonic() - begun
            phase['finished_unix'] = time.time()
            if timing.is_file():
                phase['resources'] = time_metrics(timing)
            phase['stdout_bytes'] = stdout.stat().st_size if stdout.exists() else 0
            phase['stderr_bytes'] = stderr.stat().st_size if stderr.exists() else 0
            self.save()
        self.check_source('after-' + name)
        if phase['returncode'] != 0:
            raise RuntimeError(name + ' returned ' + str(phase['returncode']) + '; later CLI phases were not started')
        return stdout


def main():
    parser = argparse.ArgumentParser(description=__doc__)
    for name in ('scar-root', 'project-root', 'entry', 'trace', 'out'):
        parser.add_argument('--' + name, type=Path, required=True)
    parser.add_argument('--source-sha', required=True, help='full frozen scripts/run_gate.py source fingerprint')
    args = parser.parse_args()
    if re.fullmatch('[0-9a-f]{64}', args.source_sha) is None:
        parser.error('--source-sha must be 64 lowercase hexadecimal characters')
    for name in ('scar_root', 'project_root', 'entry', 'trace', 'out'):
        setattr(args, name, getattr(args, name).resolve())
    if not args.scar_root.is_dir() or not args.project_root.is_dir() or not args.trace.is_dir() or not args.entry.is_file():
        parser.error('scar-root/project-root/trace must exist as directories and entry must be a file')
    if not args.entry.is_relative_to(args.project_root):
        parser.error('entry must be inside project-root')
    if args.out.is_relative_to(args.trace) or args.out.is_relative_to(args.project_root):
        parser.error('out must be outside both raw trace and target project')
    if not Path('/usr/bin/time').is_file():
        parser.error('/usr/bin/time is required for per-phase resource evidence')
    args.out.mkdir(parents=True, exist_ok=False)
    # These are the complete child environments, not merely overrides. Do not
    # copy unrelated credentials or any inherited SCAR_* injection settings.
    environment = {key: os.environ[key] for key in ('PATH', 'HOME', 'TMPDIR', 'CONDA_PREFIX',
                                                   'CONDA_DEFAULT_ENV', 'LD_LIBRARY_PATH') if key in os.environ}
    environment.update(PYTHONPATH=str(args.scar_root), PYTHONDONTWRITEBYTECODE='1',
                       PYTHONUNBUFFERED='1', LANG='C.UTF-8', LC_ALL='C.UTF-8', TZ='UTC')
    run = Run(args, args.out, environment)
    summary = {'schema': 'scar.windows-external-analysis', 'schema_version': 1,
               'status': 'INITIALIZING', 'target_executed_by_driver': False,
               'tensor_values_saved': False, 'transformation_authorized': False,
               'scope': 'three public offline CLI phases; conditional source/core/reference evidence only',
               'budgets': {'common_argv': list(COMMON_LIMITS), 'operand_argv': list(OPERAND_LIMITS)},
               'uncovered_scope': [
                   'No whole-program, state/content/effect closure or transformation permission is established.',
                   'Unobserved calls, unsupported conventions and unselected control predecessors remain boundaries.',
                   'Only the mechanically selected invocation is queried; this is not a claim about all returns.',
                   'Frame issue kinds are not serialized in the public compact report; only their aggregate is available.',
                   'Native Tensor contents are not recorded or reconstructed.',
               ]}
    before = None
    code = 1
    try:
        run.check_source('before', full=True)
        before = raw_manifest(args.trace)
        write_json(args.out / 'raw-manifest-before.json', before)
        if not before['files']:
            raise ValueError('raw trace directory has no input files')
        inventory = args.out / 'inventory.json.gz'
        operands = args.out / 'operands.json.gz'
        inventory_stdout = run.phase('inventory', ['inventory-program', args.entry,
            '--project-root', args.project_root, '--calls', args.trace, '--out', inventory, *COMMON_LIMITS])
        document = read_json(inventory)
        inventory_notes = {'schema_version': document.get('schema_version'), 'summary': document.get('summary'),
                           'issue_kinds': issue_counts(document)}
        write_json(args.out / 'inventory-observations.json', inventory_notes)
        summary['inventory'] = inventory_notes
        del document
        run.phase('link', ['link-operands', args.trace, '--project-root', args.project_root,
                          '--inventory', inventory, '--out', operands, *COMMON_LIMITS, *OPERAND_LIMITS])
        document = read_json(operands)
        analysis = document['analysis']
        if any(analysis[name] is not False for name in AUTHORITY):
            raise ValueError('generated link report unexpectedly grants execution or optimization authority')
        selection = choose_query(analysis['routing'])
        write_json(args.out / 'query-selection.json', selection)
        summary['query_selection'] = selection
        frame = analysis['summary']['frame']
        summary['links'] = {'summary': analysis['summary'], 'issue_kinds': issue_counts(analysis),
                            'code_source_statuses': dict(sorted(Counter(item['status'] for item in analysis['code_links']).items())),
                            'frame_issue_count_aggregate': frame.get('issues'),
                            'frame_issue_kind_counts': None,
                            'frame_issue_kind_scope': 'not serialized by compact public report; no redundant fourth rebuild',
                            'authority': {name: analysis[name] for name in AUTHORITY}}
        del analysis, document
        selected = selection['selected']
        if selected is None:
            run.progress['phases'].append({'name': 'query', 'status': 'NOT_RUN_NO_LEGAL_NORMAL_RETURN',
                                           'reason': 'generated routing contains no verified normal source/core return root'})
            summary['status'] = 'ANALYZED_NO_LEGAL_QUERY'
            code = 3
        else:
            query_stdout = run.phase('query', ['query-operand-refs', operands,
                '--process', selected['process_id'], '--thread', selected['thread_id'],
                '--invocation', selected['invocation_id'], '--max-reference-steps', '4096',
                *COMMON_LIMITS, *OPERAND_LIMITS])
            query_document = read_json(query_stdout)
            query = query_document['query']
            if query['invocation'] != selected or query['conditional_only'] is not True:
                raise ValueError('query returned a different invocation or lost conditional status')
            if any(query[name] is not False for name in ('function_environment_established',
                    'contents_or_effects_established', 'world_equivalence_established', 'transformation_authorized')):
                raise ValueError('query unexpectedly increased authority')
            summary['query'] = {'status': query_document['status'], 'invocation': query['invocation'],
                                'roots': len(query['roots']), 'nodes': len(query['nodes']),
                                'routes': len(query['routes']), 'route_kinds': dict(sorted(Counter(
                                    item['kind'] for item in query['routes']).items())),
                                'endpoints': query['endpoints'], 'conditions': query['conditions'],
                                'issue_kinds': issue_counts(query_document), 'issues': query['issues'],
                                'reference_steps': query['reference_steps'],
                                'max_reference_steps': query['max_reference_steps'],
                                'obligations': len(query['obligations']),
                                'authority': {name: query[name] for name in ('conditional_only',
                                    'function_environment_established', 'contents_or_effects_established',
                                    'world_equivalence_established', 'transformation_authorized')}}
            summary['status'] = 'COMPLETED_CONDITIONAL_ANALYSIS'
            code = 0
    except BaseException as error:
        summary['status'] = 'FAILED_RETAINED'
        summary['error'] = type(error).__name__ + ': ' + str(error)
        run.progress['error'] = summary['error']
        code = 1
    finally:
        verification_errors = []
        try:
            after = raw_manifest(args.trace)
            write_json(args.out / 'raw-manifest-after.json', after)
            summary['raw_inputs_unchanged'] = before is not None and before == after
            if not summary['raw_inputs_unchanged']:
                verification_errors.append('raw input manifest was unavailable or changed')
        except BaseException as error:
            verification_errors.append('raw final verification: ' + type(error).__name__ + ': ' + str(error))
        try:
            run.check_source('after', full=True)
            summary['source_matches_requested_before_and_after'] = all(
                check['matches_requested'] for check in run.progress['source_checks'])
        except BaseException as error:
            verification_errors.append('source final verification: ' + type(error).__name__ + ': ' + str(error))
        if verification_errors:
            summary['status'], code = 'FAILED_INPUT_OR_SOURCE_VERIFICATION', 1
            summary['verification_errors'] = verification_errors
        usage = resource.getrusage(resource.RUSAGE_SELF)
        summary['driver_maximum_resident_set_kib'] = usage.ru_maxrss
        summary['elapsed_seconds'] = time.monotonic() - run.started
        summary['phases'] = run.progress['phases']
        summary['source_checks'] = run.progress['source_checks']
        summary['driver_returncode'] = code
        run.progress['status'] = summary['status']
        run.progress.pop('active_phase', None)
        run.progress['driver_returncode'] = code
        run.save()
        write_json(args.out / 'result.json', summary)
        files = []
        for path in sorted(args.out.rglob('*')):
            if path.is_file() and path.name != 'output-manifest.json':
                digest, size = hash_file(path)
                files.append({'path': str(path.relative_to(args.out)), 'bytes': size, 'sha256': digest})
        write_json(args.out / 'output-manifest.json', {'files': files,
            'total_bytes_excluding_manifest': sum(item['bytes'] for item in files),
            'excludes': 'output-manifest.json itself'})
        print(json.dumps({'status': summary['status'], 'returncode': code,
                          'out': str(args.out), 'result': str(args.out / 'result.json')}, sort_keys=True))
    return code


if __name__ == '__main__':
    raise SystemExit(main())
