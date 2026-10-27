"""Positive OS provenance for owned snapshot materializers, not a new OS graph.

Use the normal same-Run OS fragment and bounded original worker exec rows.
Declarations alone, PID equality and timestamps cannot establish a role. No
syscall/work/resource record is removed, rewritten or declared complete here.
"""
from __future__ import annotations

from collections import defaultdict
from copy import deepcopy
from dataclasses import dataclass
import hashlib
from pathlib import Path
import re

from scar.ir.record_codec import encode, loads
from scar.ir.program.providers import ProviderArtifact, ProviderFactReference
from scar.ir.execution.ids import ProcessInstanceID
from scar.trace.capture_coordinates import CaptureCoordinates
from scar.trace.files import open_binary, resolve
from scar.trace.os_resources import (
    OSResourceFragment, _CLONE, _EXIT, _TIME, _CALL, _UNFINISHED, _RESUMED,
    _arguments, _clone_flags, _number,
)


ROLE = 'SCAR_OFFLINE_POSTPROCESSING'
_EXEC = frozenset(('execve', 'execveat'))
_LINE = re.compile(r'#/lines/([1-9][0-9]*)')
_SHA = re.compile(r'[0-9a-f]{64}')


def _need(value, message):
    if not value:
        raise ValueError('OS postprocessing roles: ' + message)


@dataclass(frozen=True)
class PostprocessingRoleBudgets:
    max_receipts: int = 32
    max_metadata_bytes: int = 4_000_000
    max_worker_os_bytes: int = 64_000_000
    max_line_bytes: int = 64_000

    def __post_init__(self):
        _need(all(type(x) is int and x > 0 for x in vars(self).values()),
              'positive exact budgets required')


def _local(uri, coordinates):
    logical = Path(uri)
    original = Path(coordinates.report['original_root'])
    root = Path(coordinates.report['local_root'])
    _need(logical.is_absolute() and '..' not in logical.parts
          and logical.is_relative_to(original), 'source outside original capture namespace')
    path = resolve(root / logical.relative_to(original))
    _need(not path.is_symlink() and path.resolve().is_relative_to(root.resolve()),
          'local source escapes capture or is symlinked')
    return path


def _same_birth(original, coordinate, coordinates):
    if original == coordinate:
        return True
    # A lossless archive can give the ordinary importer an explicit physical
    # gzip URI. Accept only the coordinate binder's exact logical/local map,
    # never a guessed suffix or hash-only namespace substitution.
    return (original.locator == coordinate.locator
        and (original.artifact.sha256, original.artifact.size_bytes, original.artifact.schema)
            == (coordinate.artifact.sha256, coordinate.artifact.size_bytes, coordinate.artifact.schema)
        and any(row['artifact'] == encode(coordinate.artifact)
                and row['local_path'] == original.artifact.uri
                for row in coordinates.report['membership']))


def _fact(fragment, selector):
    _need(type(selector) is dict and set(selector) == {'artifact', 'line'},
          'normal original physical-line selector required')
    index, line = selector['artifact'], selector['line']
    _need(type(index) is int and 0 <= index < len(fragment.artifacts)
          and type(line) is int and line > 0, 'invalid original source selector')
    return ProviderFactReference(fragment.artifacts[index], '#/lines/' + str(line))


def _exec_arguments(entry, returned, name):
    """Decode only a complete original exec argv, never target buffers/env."""
    first, last = _TIME.match(entry), _TIME.match(returned)
    _need(first is not None and last is not None, 'exec has no provider printleader')
    if entry != returned:
        start, end = _UNFINISHED.match(first[1]), _RESUMED.match(last[1])
        _need(start is not None and end is not None and start[1] == end[1] == name,
              'exec entry/return are not the same unfinished call')
        body = start[1] + '(' + start[2] + end[2]
    else:
        body = first[1]
    call = _CALL.match(body)
    _need(call is not None and call[1] == name and _number(call[3]) == 0,
          'original exec is not successful')
    args = _arguments(call[2])
    path_index, argv_index = (0, 1) if name == 'execve' else (1, 2)
    _need(len(args) == (3 if name == 'execve' else 5), 'exec argument shape differs')
    executable, argv = loads(args[path_index]), loads(args[argv_index])
    _need(type(executable) is str and executable.startswith('/')
          and type(argv) is list and len(argv) == 16 and all(type(x) is str for x in argv),
          'exec argv is abbreviated, escaped outside JSON, or unsupported')
    _need(argv[0] == executable and argv[1:4] == ['-B', '-m', 'scar.analysis.snapshot_materialization'],
          'exec does not name the collector materializer')
    pairs = argv[4:]
    flags = dict(zip(pairs[::2], pairs[1::2]))
    _need(len(flags) == 6 and set(flags) == {'--journal', '--sha256', '--out', '--receipt',
          '--max-output-bytes', '--max-line-bytes'} and all(
              re.fullmatch(r'[1-9][0-9]*', flags[k]) for k in ('--max-output-bytes', '--max-line-bytes')),
          'exec flags differ from the explicit converter interface')
    return flags


class SnapshotPostprocessorRoles:
    """Read-only role navigation over original facts; no owner reconstruction."""

    def __init__(self, document):
        self._document = deepcopy(document)

    def to_dict(self):
        return deepcopy(self._document)

    def query(self, source, *, process):
        """Return a positive role for this exact process/source interval only.

        Other threads, pre-exec work, later images and unknown scopes return
        None. None means unclassified, never APPLICATION/RECORDING or no work.
        """
        _need(type(source) is ProviderFactReference and type(process) is ProcessInstanceID,
              'qualified original process and source required')
        source.__post_init__(); process.__post_init__()
        match = _LINE.fullmatch(source.locator)
        _need(match is not None, 'exact original provider line required')
        line = int(match[1])
        for row in self._document['roles']:
            interval = row['interval']
            if (row['process'] == encode(process) and interval['artifact'] == encode(source.artifact)
                    and interval['first_line'] <= line
                    and (interval['end_line_exclusive'] is None or line < interval['end_line_exclusive'])):
                return deepcopy(row)
        return None


def bind_snapshot_postprocessor_roles(coordinates, fragment, receipt_artifacts, *, budgets=None):
    """Bridge declarations to normal same-Run parent/child and exact exec facts.

    Reuses the already imported birth facts. Only candidate worker OS files
    are reread/hash-checked for argv, which the generic interface view omits.
    A role describes the closed-journal decoder image, not all capture phases,
    code-image identity, source/body equivalence, FD state or complete effects.
    """
    limits = budgets or PostprocessingRoleBudgets()
    _need(type(limits) is PostprocessingRoleBudgets, 'typed budgets required')
    limits.__post_init__()
    _need(type(coordinates) is CaptureCoordinates and type(fragment) is OSResourceFragment
          and fragment.interface_work and fragment.run == coordinates.run,
          'normal coordinate-bound interface-work fragment required')
    _need(hashlib.sha256(coordinates.payload).hexdigest() == coordinates.artifact.sha256,
          'coordinate input changed')
    protocol = loads(fragment.protocol_bytes.decode('utf-8'))
    _need(len(fragment.protocol_bytes) == fragment.protocol_artifact.size_bytes
          and hashlib.sha256(fragment.protocol_bytes).hexdigest() == fragment.protocol_artifact.sha256
          and protocol['contract'].get('coordinate_binding') == encode(coordinates.artifact),
          'OS fragment binds another coordinate input')
    _need(type(receipt_artifacts) is tuple and len(receipt_artifacts) <= limits.max_receipts
          and all(type(a) is ProviderArtifact for a in receipt_artifacts)
          and len({a.uri for a in receipt_artifacts}) == len(receipt_artifacts),
          'explicit unique receipt artifacts required')
    declarations, frontiers, metadata_bytes = [], [], 0
    for artifact in receipt_artifacts:
        artifact.__post_init__()
        _need(artifact.size_bytes <= limits.max_metadata_bytes - metadata_bytes,
              'aggregate metadata byte budget exceeded')
        with open_binary(_local(artifact.uri, coordinates)) as stream:
            raw = stream.read(artifact.size_bytes + 1)
        metadata_bytes += len(raw)
        _need(len(raw) == artifact.size_bytes and hashlib.sha256(raw).hexdigest() == artifact.sha256,
              'materialization receipt bytes differ')
        doc = loads(raw.decode('utf-8'))
        _need(type(doc) is dict, 'receipt must be a metadata object')
        post, source, output = doc.get('postprocessor', {}), doc.get('source', {}), doc.get('output', {})
        if type(post) is not dict or post.get('role') != ROLE:
            frontiers.append({'declaration': encode(ProviderFactReference(artifact, '#')),
                              'reason': 'POSTPROCESSOR_DECLARATION_UNAVAILABLE'})
            continue
        _need(type(source) is dict and type(output) is dict,
              'materializer declaration lacks original source/output anchors')
        _need(type(doc.get('complete')) is bool and type(output.get('published')) is bool
              and post.get('role') == ROLE and source.get('format') == 'scar.snapshot-journal/1',
              'receipt has no explicit materializer declaration')
        pid, parent = post.get('process_id'), post.get('parent_process_id')
        _need(type(pid) is int and pid > 0 and type(parent) is int and parent > 0 and pid != parent
              and type(source.get('declared_pid')) is int and source['declared_pid'] == parent,
              'receipt parent/source ownership differs')
        _need(type(source.get('uri')) is str and source['uri'].endswith('.snapshot')
              and type(output.get('uri')) is str
              and artifact.uri == source['uri'][:-len('.snapshot')] + '.snapshot-receipt.json'
              and output['uri'] == source['uri'][:-len('.snapshot')] + ('' if output['published'] else '.partial')
              and type(source.get('sha256')) is str and _SHA.fullmatch(source['sha256']) is not None,
              'receipt source/output namespace differs')
        _local(source['uri'], coordinates); _local(output['uri'], coordinates)
        declarations.append((artifact, doc, pid, parent))
    processes = {p.id: p for p in fragment.processes}
    threads = {t.tid: t for t in fragment.threads}
    requested = {d[2] for d in declarations}
    births, events = defaultdict(list), defaultdict(list)
    for row in fragment.observations:
        if row.get('syscall') in _CLONE and row.get('result') in requested:
            births[row['result']].append(row)
        if row.get('tid') in requested and row.get('syscall') in _EXEC | _EXIT:
            events[row['tid']].append(row)
    roles, selected_bytes, cache = [], 0, {}
    for declaration, doc, pid, parent in declarations:
        base = {'declaration': encode(ProviderFactReference(declaration, '#/postprocessor')),
                'declared_process_id': pid, 'declared_parent_process_id': parent}
        candidates = births[pid]
        if len(candidates) != 1:
            frontiers.append({**base, 'reason': 'PARENT_BIRTH_ABSENT_OR_AMBIGUOUS'}); continue
        birth = candidates[0]
        parent_thread, child_thread = threads.get(birth['tid']), threads.get(pid)
        flags = _clone_flags({'name': birth['syscall'], 'args': [x for x in birth.get('arguments', ()) if type(x) is str]})
        if (not birth.get('argument_rendering_complete') or flags is None or 'CLONE_THREAD' in flags
                or parent_thread is None or child_thread is None
                or processes[parent_thread.process].pid != parent or processes[child_thread.process].pid != pid):
            frontiers.append({**base, 'reason': 'QUALIFIED_PARENT_CHILD_PROCESS_UNRESOLVED'}); continue
        child, parent_process = processes[child_thread.process], processes[parent_thread.process]
        birth_source = _fact(fragment, birth['source'])
        # The ordinary coordinate binder derives the ProcessInstanceID from
        # this exact unique birth source. Reuse that independent incarnation
        # anchor, not only the PID/result copied into a mutable observation.
        _need(type(child.source) is ProviderFactReference and _same_birth(birth_source, child.source, coordinates)
            and coordinates.process_for(
            birth_source.artifact, birth['tid']) == parent_process,
            'normal birth fact differs from original child/parent incarnations')
        execs = [r for r in events[pid] if r['syscall'] in _EXEC and r.get('result') == 0]
        matches = []
        for row in execs:
            original = _fact(fragment, row['source'])
            entry = _fact(fragment, row['entry_source'])
            _need(original.artifact == entry.artifact, 'exec sources crossed provider artifacts')
            _need(coordinates.process_for(original.artifact, pid) == child,
                  'exec artifact lacks this exact same-Run process membership')
            key = original.artifact
            if key not in cache:
                _need(key.size_bytes <= limits.max_worker_os_bytes - selected_bytes,
                      'selected worker OS byte budget exceeded')
                wanted = {r[s]['line'] for r in execs for s in ('source', 'entry_source')
                          if fragment.artifacts[r[s]['artifact']] == key}
                digest, size, lines = hashlib.sha256(), 0, {}
                with open_binary(_local(key.uri, coordinates)) as stream:
                    for line_number, raw in enumerate(iter(lambda: stream.readline(limits.max_line_bytes + 1), b''), 1):
                        size += len(raw); selected_bytes += len(raw); digest.update(raw)
                        _need(len(raw) <= limits.max_line_bytes and selected_bytes <= limits.max_worker_os_bytes,
                              'selected worker OS line/aggregate byte budget exceeded')
                        if line_number in wanted:
                            lines[line_number] = raw.decode('utf-8').rstrip('\r\n')
                _need(size == key.size_bytes and digest.hexdigest() == key.sha256,
                      'selected original worker artifact changed')
                cache[key] = lines
            try:
                flags = _exec_arguments(cache[key][row['entry_source']['line']], cache[key][row['source']['line']], row['syscall'])
            except (ValueError, KeyError, UnicodeError):
                continue  # A different/abbreviated argv cannot authorize a role.
            if (flags['--journal'] == doc['source']['uri'] and flags['--sha256'] == doc['source']['sha256']
                    and flags['--out'] == doc['source']['uri'][:-len('.snapshot')]
                    and flags['--receipt'] == declaration.uri):
                matches.append(row)
        if len(matches) != 1:
            frontiers.append({**base, 'reason': 'EXACT_MATERIALIZER_EXEC_ABSENT_OR_AMBIGUOUS'}); continue
        row = matches[0]; start = row['source']['line']; artifact = _fact(fragment, row['source']).artifact
        boundaries = [(r['entry_source']['line'], _fact(fragment, r['entry_source']), 'NEXT_EXEC_OR_EXIT')
                      for r in events[pid] if (r['syscall'] in _EXIT or r['syscall'] in _EXEC and r.get('result') == 0)
                      and r['entry_source']['artifact'] == row['source']['artifact'] and r['entry_source']['line'] > start]
        boundaries.extend((line, ProviderFactReference(artifact, '#/lines/' + str(line)), 'UNPARSED_PROVIDER_BOUNDARY')
                          for index, line, classification, _, _ in fragment.line_classifications
                          if index == row['source']['artifact'] and line > start and classification == 'UNSUPPORTED')
        boundary = min(boundaries, key=lambda x: x[0]) if boundaries else None
        roles.append({**base, 'role': ROLE, 'phase': 'POSTPROCESSING',
            'declared_materialization_complete': doc['complete'],
            'declared_output_published': doc['output']['published'],
            'run': encode(fragment.run.id), 'process': encode(child.id), 'parent_process': encode(parent_process.id),
            'birth': encode(birth_source), 'exec': encode(_fact(fragment, row['source'])),
            'interval': {'artifact': encode(artifact), 'first_line': start,
                         'end_line_exclusive': None if boundary is None else boundary[0]},
            'boundary': None if boundary is None else {'source': encode(boundary[1]), 'kind': boundary[2]},
            'unknown': ['other threads/descendants and pre-exec work are not classified',
                        'code image equivalence and complete effects are not established']})
    return SnapshotPostprocessorRoles({'schema': 'scar.os-postprocessing-role-navigation', 'schema_version': 1,
        'coordinate_binding': encode(coordinates.artifact), 'run': encode(fragment.run.id),
        'roles': roles, 'frontiers': frontiers,
        'io': {'metadata_decoded_bytes': metadata_bytes, 'selected_worker_os_decoded_bytes': selected_bytes},
        'scope': 'positive provenance only; original OS facts and denominators unchanged; unclassified does not mean application',
        'whole_program_complete': False})
