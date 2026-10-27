"""Bounded original source bytes observed alongside live code descriptors.

These are capture inputs, not compiler witnesses. Reading a file after a code
object exists does not establish which bytes its loader read. Ordinary offline
CodeWitness matching must independently establish any later source association.
"""
from __future__ import annotations

import base64
import hashlib
import io
import json
import os
from pathlib import Path
import re
import sys
import tokenize

PROGRAM_PORTS_PROFILE = 'SCAR_PROGRAM_PORTS_V1'
PROCESS_PORTS_PROFILE = 'SCAR_PROGRAM_PORTS_V2'
PROGRAM_PORTS_PROFILES = (PROGRAM_PORTS_PROFILE, PROCESS_PORTS_PROFILE)
SOURCE_SCHEMA = 'scar.captured-python-sources'
SOURCE_SCOPE = 'PROJECT_ROOT_AND_ACTUAL_PYTHON_DESCENDANTS_V1'
PROCESS_SOURCE_SCOPE = 'TARGET_PROCESS_INSTALLED_PYTHON_THREADS_V1'


def _wire(value):
    return (json.dumps(value, ensure_ascii=True, separators=(',', ':'), allow_nan=False)+'\n').encode('ascii')


def _stamp(value):
    return [value.st_dev, value.st_ino, value.st_size, value.st_mtime_ns, value.st_ctime_ns]


class CapturedSources:
    def __init__(self, out, pid, *, max_files=1024, max_file_bytes=2_000_000,
                 max_total_bytes=64_000_000, profile=PROGRAM_PORTS_PROFILE):
        if any(type(x) is not int or x < 1 for x in (pid, max_files, max_file_bytes, max_total_bytes)):
            raise ValueError('captured source budgets must be positive integers')
        self.pid, self.out = pid, Path(out)
        if profile not in PROGRAM_PORTS_PROFILES:
            raise ValueError('unsupported captured-source scope profile')
        self.profile = profile
        self.limits = dict(max_files=max_files, max_file_bytes=max_file_bytes, max_total_bytes=max_total_bytes)
        self.path = self.out / f'captured-sources.{pid}.jsonl'
        self.meta = self.out / f'captured-source-meta.{pid}.json'
        self.fd = os.open(self.path, os.O_WRONLY | os.O_CREAT | os.O_EXCL, 0o600)
        self.files, self.codes = {}, {}
        self.raw_read = self.written = self.rows = 0
        self.digest = hashlib.sha256()
        self.closed = False

    def _write(self, row):
        raw = _wire(row)
        at = 0
        while at < len(raw):
            n = os.write(self.fd, raw[at:])
            if n <= 0:
                raise OSError('captured source write made no progress')
            self.digest.update(raw[at:at+n]); self.written += n; at += n
        self.rows += 1

    def observe(self, description):
        """One descriptor link per CodeID; one source read per original path."""
        key, filename = description['key'], description['filename']
        if key in self.codes:
            return
        self.codes[key] = filename
        if filename in self.files:
            return
        item = dict(path=filename, status='UNAVAILABLE', frontier=None,
                    compiler_match='NOT_CHECKED', loader_bytes_observed=False)
        self.files[filename] = item
        raw = None
        try:
            if not os.path.isabs(filename):
                item['frontier'] = 'NON_FILESYSTEM_CODE_FILENAME'; return
            if len(self.files) > self.limits['max_files']:
                item['frontier'] = 'SOURCE_FILE_COUNT_BUDGET'; return
            path = Path(filename)
            before = path.stat()
            item['stamp_at_observation'] = _stamp(before)
            if not path.is_file():
                item['frontier'] = 'SOURCE_PATH_NOT_REGULAR_FILE'; return
            if before.st_size > self.limits['max_file_bytes']:
                item['frontier'] = 'SOURCE_FILE_BYTE_BUDGET'; return
            remaining = self.limits['max_total_bytes'] - self.raw_read
            if before.st_size > remaining:
                item['frontier'] = 'SOURCE_TOTAL_BYTE_BUDGET'; return
            # The descriptor stamp and the open file must agree. No re-open or
            # retry can silently replace the first captured source version.
            with path.open('rb') as stream:
                if _stamp(os.fstat(stream.fileno())) != _stamp(before):
                    item['frontier'] = 'SOURCE_CHANGED_BEFORE_READ'; return
                raw = stream.read(min(self.limits['max_file_bytes'], remaining))
                self.raw_read += len(raw)
                if _stamp(os.fstat(stream.fileno())) != _stamp(before):
                    item['frontier'] = 'SOURCE_CHANGED_DURING_READ'; return
            if len(raw) != before.st_size or _stamp(path.stat()) != _stamp(before):
                item['frontier'] = 'SOURCE_CHANGED_DURING_READ'; return
            encoding, _ = tokenize.detect_encoding(io.BytesIO(raw).readline)
            text = raw.decode(encoding).replace('\r\n', '\n').replace('\r', '\n')
            normalized = text.encode('utf-8')
            item.update(status='ARCHIVED_SOURCE_BYTES', raw_sha256=hashlib.sha256(raw).hexdigest(),
                raw_bytes=len(raw), encoding=encoding,
                normalized_sha256=hashlib.sha256(normalized).hexdigest(),
                normalized_bytes=len(normalized), observation='FIRST_DESCRIPTOR_OBSERVATION')
            self._write(dict(schema=SOURCE_SCHEMA, schema_version=1, process_id=self.pid,
                index=self.rows+1, **item, raw_base64=base64.b64encode(raw).decode('ascii')))
            item['source_row'] = self.rows
        except (OSError, UnicodeError, SyntaxError, LookupError) as error:
            item['status'] = 'UNAVAILABLE'
            item['frontier'] = 'SOURCE_CAPTURE_' + type(error).__name__

    def close(self):
        if self.closed or os.getpid() != self.pid:
            return
        self.closed = True
        os.close(self.fd)
        for item in self.files.values():
            if item['status'] != 'ARCHIVED_SOURCE_BYTES':
                continue
            try:
                unchanged = _stamp(Path(item['path']).stat()) == item['stamp_at_observation']
            except OSError:
                unchanged = False
            item['unchanged_at_close'] = unchanged
            if not unchanged:
                item['frontier'] = 'SOURCE_CHANGED_AFTER_OBSERVATION'
        doc = dict(schema=SOURCE_SCHEMA, schema_version=1, profile=self.profile,
            process_id=self.pid, limits=self.limits, files=list(self.files.values()),
            code_sources=[dict(code=key, path=path) for key, path in self.codes.items()],
            file=dict(uri=str(self.path), sha256=self.digest.hexdigest(), size_bytes=self.written,
                      rows=self.rows), source_raw_bytes_read=self.raw_read,
            compiler_match='NOT_CHECKED', loader_bytes_observed=False,
            runtime_optimize=sys.flags.optimize,
            compile_flags_and_per_code_optimize='NOT_OBSERVED')
        raw = _wire(doc)
        if len(raw) > 8_000_000:
            raise ValueError('captured source metadata byte budget exceeded')
        with self.meta.open('xb') as stream:
            stream.write(raw)
        return dict(uri=str(self.meta), sha256=hashlib.sha256(raw).hexdigest(),
                    size_bytes=len(raw), schema=SOURCE_SCHEMA+'/1')


def validate_program_profile(calls, operands):
    """Metadata contract only; source bytes and code matching remain separate."""
    from scar.ir.program.call_operands import PROGRAM_PORTS_RULE, PROCESS_PORTS_RULE
    profile = calls.get('capture_profile')
    requested = profile in PROGRAM_PORTS_PROFILES
    expected = PROGRAM_PORTS_RULE if profile == PROGRAM_PORTS_PROFILE else PROCESS_PORTS_RULE
    if requested != (operands.get('rule') in (PROGRAM_PORTS_RULE, PROCESS_PORTS_RULE)) or requested and operands['rule'] != expected:
        raise ValueError('program ports frame/operand profile differs')
    if not requested:
        return None
    scope = SOURCE_SCOPE if profile == PROGRAM_PORTS_PROFILE else PROCESS_SOURCE_SCOPE
    if (calls.get('scope_policy') != scope or calls.get('instruction_monitoring') is not False
            or 'capture_plan' in calls or operands.get('instructions') != 0
            or type(calls.get('captured_sources')) is not dict):
        raise ValueError('program ports scope/source declaration differs')
    if profile == PROCESS_PORTS_PROFILE:
        hooks = calls.get('thread_hooks')
        ids = hooks.get('python_thread_identifiers_at_install') if type(hooks) is dict else None
        if (type(hooks) is not dict or hooks.get('api') != 'threading.setprofile_all_threads'
                or hooks.get('enumeration_api') != 'sys._current_frames'
                or type(ids) is not list or not ids or len(set(ids)) != len(ids)
                or any(type(x) is not int or x < 1 for x in ids)
                or type(hooks.get('python_threads_at_install')) is not int
                or hooks['python_threads_at_install'] != len(ids)
                or hooks.get('installing_python_ident') not in ids
                or type(hooks.get('installing_native_tid')) is not int or hooks['installing_native_tid'] < 1
                or any(type(hooks.get(x)) is not bool for x in
                       ('known_current_hook_present','known_future_threading_hook_present'))
                or hooks.get('existing_other_thread_hook_history') != 'NOT_OBSERVED'
                or hooks.get('other_thread_hook_restoration') != 'NOT_ENUMERABLE; CLOSED_COLLECTOR_NOOP_IF_STILL_INSTALLED'
                or calls.get('scope_frontiers') != ['FUTURE_NON_THREADING_PYTHON_THREADS_NOT_GUARANTEED',
                    'PREINSTALL_ACTIVE_FRAMES_HAVE_NO_RETROACTIVE_ENTRY',
                    'FORK_AND_EXEC_CHILD_PYTHON_NOT_CAPTURED',
                    'PREEXISTING_OTHER_THREAD_HOOK_HISTORY_NOT_OBSERVED']):
            raise ValueError('process ports thread hook contract differs')
        forwarding = calls.get('target_forwarding')
        roots = forwarding.get('roots') if type(forwarding) is dict else None
        if (type(forwarding) is not dict or forwarding.get('kinds') != ['DISPATCH','IMPORT','TRACE']
                or type(roots) is not list
                or any(type(x) is not list or len(x) != 2 or type(x[0]) is not int or x[0] < 1
                       or type(x[1]) is not int or not 0 <= x[1] < 3 for x in roots)
                or len({x[0] for x in roots}) != len(roots)
                or type(forwarding.get('roots_seen')) is not int or forwarding['roots_seen'] < len(roots)
                or forwarding.get('max_metadata_bytes') != 1_000_000
                or sum(len(json.dumps(x,separators=(',',':')))+1 for x in roots) > 1_000_000
                or type(forwarding.get('frontiers')) is not list
                or any(type(x) is not str or not x for x in forwarding['frontiers'])
                or forwarding.get('context') != 'original entry caller site/path/ancestor; not direct-call or submission proof'):
            raise ValueError('process ports target forwarding declaration differs')
    return calls['captured_sources']


def validate_source_metadata(doc, pid, code_sources=None, *, profile=None):
    """Validate provenance metadata without promoting it to compiler evidence."""
    if (set(doc) != {'schema','schema_version','profile','process_id','limits','files','code_sources',
                     'file','source_raw_bytes_read','compiler_match','loader_bytes_observed',
                     'runtime_optimize','compile_flags_and_per_code_optimize'}
            or doc.get('schema') != SOURCE_SCHEMA or type(doc.get('schema_version')) is not int or doc['schema_version'] != 1
            or type(doc.get('process_id')) is not int or doc['process_id'] != pid
            or doc.get('profile') not in PROGRAM_PORTS_PROFILES
            or profile is not None and doc['profile'] != profile
            or doc.get('compiler_match') != 'NOT_CHECKED'
            or doc.get('loader_bytes_observed') is not False
            or doc.get('compile_flags_and_per_code_optimize') != 'NOT_OBSERVED'):
        raise ValueError('captured source schema/issuer/qualification differs')
    limits = doc.get('limits')
    if (type(limits) is not dict or set(limits) != {'max_files','max_file_bytes','max_total_bytes'}
            or any(type(v) is not int or v < 1 for v in limits.values())):
        raise ValueError('captured source limits differ')
    files, links = doc.get('files'), doc.get('code_sources')
    if type(files) is not list or type(links) is not list:
        raise ValueError('captured source inventories missing')
    if any(type(x) is not dict or set(x) != {'code','path'} for x in links):
        raise ValueError('captured source code links contain unexpected fields')
    if any(type(x) is not dict or type(x.get('path')) is not str or not x['path'] for x in files):
        raise ValueError('captured source original path differs')
    by_path = {item['path']: item for item in files}
    actual_codes = {item['code']: item['path'] for item in links}
    if (len(by_path) != len(files) or len(actual_codes) != len(links)
            or any(type(k) is not str or re.fullmatch(r'pycode-v2:[0-9a-f]{64}', k) is None
                   or p not in by_path for k,p in actual_codes.items())
            or code_sources is not None and actual_codes != code_sources):
        raise ValueError('captured source links differ from original code inventory')
    retained = [x for x in files if x['status'] == 'ARCHIVED_SOURCE_BYTES']
    if any(x.get('compiler_match') != 'NOT_CHECKED' or x.get('loader_bytes_observed') is not False
           or x['status'] not in ('ARCHIVED_SOURCE_BYTES','UNAVAILABLE') for x in files):
        raise ValueError('captured source metadata upgrades source qualification')
    if (len(retained) > limits['max_files'] or
            sorted(x['source_row'] for x in retained) != list(range(1,len(retained)+1))
            or any(type(x['raw_bytes']) is not int or not 0 <= x['raw_bytes'] <= limits['max_file_bytes']
                   for x in retained)
            or type(doc['source_raw_bytes_read']) is not int
            or not sum(x['raw_bytes'] for x in retained) <= doc['source_raw_bytes_read'] <= limits['max_total_bytes']):
        raise ValueError('captured source counts/budgets differ')
    declared = doc['file']
    if (type(declared) is not dict or set(declared) != {'uri','sha256','size_bytes','rows'}
            or declared['rows'] != len(retained)
            or type(declared['size_bytes']) is not int or declared['size_bytes'] < 0
            or re.fullmatch(r'[0-9a-f]{64}',declared['sha256']) is None):
        raise ValueError('captured source row receipt differs')
    return by_path


def validate_source_row(row, doc, index, by_path):
    item = by_path.get(row.get('path'))
    if (item is None or item['status'] != 'ARCHIVED_SOURCE_BYTES'
            or row.get('schema') != SOURCE_SCHEMA or row.get('schema_version') != 1
            or row.get('process_id') != doc['process_id'] or row.get('index') != index
            or item['source_row'] != index or row.get('compiler_match') != 'NOT_CHECKED'
            or row.get('loader_bytes_observed') is not False):
        raise ValueError('captured source row identity/qualification differs')
    raw = base64.b64decode(row['raw_base64'], validate=True)
    encoding,_ = tokenize.detect_encoding(io.BytesIO(raw).readline)
    normalized = raw.decode(encoding).replace('\r\n','\n').replace('\r','\n').encode('utf-8')
    for name,value in (('raw_bytes',len(raw)), ('raw_sha256',hashlib.sha256(raw).hexdigest()),
                       ('encoding',encoding), ('normalized_bytes',len(normalized)),
                       ('normalized_sha256',hashlib.sha256(normalized).hexdigest())):
        if row.get(name) != value or item.get(name) != value:
            raise ValueError('captured source original/normalized bytes differ')
