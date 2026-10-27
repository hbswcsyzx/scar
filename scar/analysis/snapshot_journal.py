"""Offline validation and original JSONL encoding of a temporary CPython journal."""
from __future__ import annotations

from hashlib import sha256
from io import BytesIO
import json
import marshal
import math
import os
from pathlib import Path
import sys

from scar.trace.snapshot_journal import (FORMAT, FRAME, FOOTER, FOOTER_RESERVE,
    HEADER_LENGTH, HEADER_LIMIT, MAGIC, RECORD)


def _need(value, detail):
    if not value:
        raise ValueError(detail)


def _strict_json(raw):
    def pairs(items):
        result = {}
        for key, value in items:
            _need(key not in result, 'duplicate journal metadata key')
            result[key] = value
        return result
    def constant(_value):
        raise ValueError('nonfinite journal metadata')
    return json.loads(raw.decode('ascii'), object_pairs_hook=pairs, parse_constant=constant)


def _plain_row(row, max_nodes, max_depth):
    """Full Python validation is deliberately offline, never in append."""
    _need(type(row) is dict, 'snapshot root is not an exact dict')
    stack, active, nodes = [(row, 0, False)], set(), 0
    while stack:
        value, depth, leaving = stack.pop()
        if leaving:
            active.remove(id(value)); continue
        nodes += 1
        _need(nodes <= max_nodes and depth <= max_depth, 'snapshot tree node/depth ceiling exceeded')
        kind = type(value)
        if value is None or kind in (str, bool, int):
            continue
        if kind is float:
            _need(math.isfinite(value), 'snapshot has a nonfinite float'); continue
        _need(kind in (dict, list, tuple), 'snapshot contains a non-JSON plain type')
        _need(id(value) not in active, 'snapshot has a container cycle')
        active.add(id(value)); stack.append((value, depth, True))
        if kind is dict:
            _need(all(type(key) is str for key in value), 'snapshot dictionary key is not an exact string')
            children = value.values()
        else:
            children = value
        for child in reversed(tuple(children)):
            stack.append((child, depth + 1, False))


def materialize_snapshot_journal(path, output_jsonl, *, expected_sha256=None,
        max_record_bytes=4 * 1024 * 1024, max_total_bytes=1024 * 1024 * 1024,
        max_output_bytes=1024 * 1024 * 1024, max_output_line_bytes=None,
        max_row_nodes=1_000_000, max_row_depth=64):
    """Return explicit source/output receipts; only complete input is published.

    Existing output (including an empty file) is never overwritten. On a
    framing, validation, producer or byte-quota failure the validated prefix
    stays at output_jsonl+'.partial', and complete/published are both false.
    The caller must run its ordinary domain/typed reader afterward.
    """
    max_output_line_bytes = max_output_bytes if max_output_line_bytes is None else max_output_line_bytes
    for value in (max_record_bytes, max_total_bytes, max_output_bytes, max_output_line_bytes,
                  max_row_nodes, max_row_depth):
        _need(type(value) is int and value > 0, 'materializer ceilings must be positive exact integers')
    if expected_sha256 is not None:
        _need(type(expected_sha256) is str and len(expected_sha256) == 64
              and all(c in '0123456789abcdef' for c in expected_sha256), 'exact expected journal SHA256 required')
    source, output = Path(path).absolute(), Path(output_jsonl).absolute()
    partial = output.with_name(output.name + '.partial')
    _need(source == source.resolve() and not source.is_symlink() and source.is_file(), 'regular canonical source journal required')
    _need(output == output.resolve() and source not in (output, partial)
          and not output.exists() and not output.is_symlink() and not partial.exists() and not partial.is_symlink(),
          'fresh canonical output and partial paths required')
    before = source.stat()
    _need(before.st_size <= max_total_bytes, 'source journal exceeds independent total-byte ceiling')
    source_hash, output_hash = sha256(), sha256()
    read_bytes = output_bytes = lines = payload_bytes = frame_bytes = 0
    header, footer, errors = None, None, []
    complete = published = False
    fd = os.open(partial, os.O_WRONLY | os.O_CREAT | os.O_EXCL | os.O_CLOEXEC, 0o600)
    with source.open('rb') as raw, os.fdopen(fd, 'wb') as destination:
        def read(size):
            nonlocal read_bytes
            _need(size >= 0 and read_bytes + size <= max_total_bytes, 'journal read byte ceiling exceeded')
            data = raw.read(size)
            read_bytes += len(data); source_hash.update(data)
            return data
        def exact(size):
            data = read(size)
            _need(len(data) == size, 'partial journal header/frame/payload')
            return data
        try:
            _need(exact(len(MAGIC)) == MAGIC, 'journal magic/version differs')
            length = HEADER_LENGTH.unpack(exact(HEADER_LENGTH.size))[0]
            _need(0 < length <= HEADER_LIMIT, 'journal header length exceeds ceiling')
            header = _strict_json(exact(length))
            _need(type(header) is dict and header.get('format') == FORMAT
                and type(header.get('schema_version')) is int and header['schema_version'] == 1
                and header.get('implementation') == sys.implementation.name == 'cpython'
                and header.get('python') == sys.version and header.get('python_version') == list(sys.version_info)
                and header.get('cache_tag') == sys.implementation.cache_tag
                and type(header.get('marshal_version')) is int and header['marshal_version'] == marshal.version
                and header.get('allow_code') is False, 'journal requires its exact CPython/marshal runtime')
            _need(type(header.get('owner_pid')) is int and header['owner_pid'] > 0
                  and type(header.get('max_record_bytes')) is int and header['max_record_bytes'] > 0,
                  'journal process/record declaration differs')
            while True:
                prefix = read(FRAME.size)
                _need(bool(prefix), 'journal has no closed footer')
                _need(len(prefix) == FRAME.size, 'partial journal frame prefix')
                kind, ordinal, length = FRAME.unpack(prefix)
                _need(ordinal == lines + 1, 'journal record order differs')
                if kind == FOOTER:
                    _need(0 < length + FRAME.size <= FOOTER_RESERVE, 'journal footer length exceeds ceiling')
                    footer = _strict_json(exact(length))
                    _need(read(1) == b'', 'journal bytes follow the footer')
                    _need(type(footer) is dict and footer.get('schema') == 'scar.snapshot-journal-footer'
                        and type(footer.get('schema_version')) is int and footer['schema_version'] == 1
                        and footer.get('owner_pid') == header['owner_pid'] and type(footer.get('complete')) is bool,
                        'journal footer schema/process differs')
                    counts = footer['counts']
                    _need(type(counts) is dict and counts.get('accepted_records') == lines
                        and counts.get('written_records') == lines and counts.get('accepted_bytes') == payload_bytes
                        and counts.get('accepted_frame_bytes') == counts.get('written_frame_bytes') == frame_bytes,
                        'journal footer counts differ from the actual stream')
                    rejected = counts.get('rejected')
                    _need(type(rejected) is dict and all(type(v) is int and v >= 0 for v in rejected.values()),
                          'journal rejection counters differ')
                    _need(footer['complete'] and counts.get('append_calls') == lines
                        and not any(rejected.values()) and counts.get('writer_error') is None
                        and counts.get('close_timed_out') is False and counts.get('queued_bytes') == 0,
                        'producer journal is explicitly incomplete')
                    complete = True
                    break
                _need(kind == RECORD and 0 < length <= min(max_record_bytes, header['max_record_bytes']),
                      'journal frame kind/record byte ceiling differs')
                payload = exact(length)
                stream = BytesIO(payload)
                row = marshal.load(stream, allow_code=False)
                _need(stream.tell() == len(payload), 'trailing bytes in marshal record')
                _plain_row(row, max_row_nodes, max_row_depth)
                encoded = json.dumps(row, ensure_ascii=True, separators=(',', ':'),
                                     allow_nan=False).encode('ascii') + b'\n'
                _need(len(encoded) <= max_output_line_bytes, 'original JSONL line byte ceiling exceeded')
                _need(output_bytes + len(encoded) <= max_output_bytes, 'original JSONL total byte ceiling exceeded')
                destination.write(encoded)
                output_hash.update(encoded); output_bytes += len(encoded); lines += 1
                payload_bytes += length; frame_bytes += FRAME.size + length
        except Exception as error:
            complete = False
            errors.append({'type': type(error).__name__, 'detail': str(error), 'next_record_ordinal': lines + 1})
        # Bind the source receipt to all actual bytes, including an unparsed
        # suffix after a failed frame; such a receipt never validates its rows.
        while True:
            remaining = max_total_bytes - read_bytes
            if remaining <= 0:
                break
            data = read(min(1024 * 1024, remaining))
            if not data:
                break
    after = source.stat()
    stamp = lambda s: (s.st_dev, s.st_ino, s.st_size, s.st_mtime_ns, s.st_ctime_ns)
    if stamp(before) != stamp(after) or read_bytes != before.st_size:
        complete = False; errors.append({'type': 'SourceChanged', 'detail': 'journal changed during materialization'})
    digest = source_hash.hexdigest()
    if expected_sha256 is not None and digest != expected_sha256:
        complete = False; errors.append({'type': 'SourceSHAMismatch', 'detail': 'journal SHA differs from expected receipt'})
    if complete:
        try:
            # Same-directory hard link publishes exclusively, without an
            # overwrite race against an existing output, even an empty file.
            os.link(partial, output)
            partial.unlink(); published = True
        except OSError as error:
            complete = False; errors.append({'type': type(error).__name__, 'detail': 'exclusive JSONL publication failed'})
    return {'status': 'MATERIALIZED' if complete else 'INCOMPLETE', 'complete': complete,
        'source': {'uri': str(source), 'raw_bytes': read_bytes, 'sha256': digest, 'format': FORMAT,
                   'declared_pid': header.get('owner_pid') if type(header) is dict else None,
                   'closed_footer': footer is not None},
        'output': {'uri': str(output if published else partial), 'raw_bytes': output_bytes,
                   'lines': lines, 'sha256': output_hash.hexdigest(), 'published': published},
        'producer_receipt': footer, 'errors': errors, 'rows_validated': complete,
        'domain_schema_validated': False, 'legacy_meta_allowed': complete,
        'encoder': {'ensure_ascii': True, 'separators': [',', ':'], 'allow_nan': False, 'newline': '\n'},
        'max_output_bytes': max_output_bytes, 'max_output_line_bytes': max_output_line_bytes}
