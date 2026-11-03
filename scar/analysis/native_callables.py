"""Strict optional native carrier companion over the original CALL streams.

Reading this evidence neither reclassifies Python target v2 nor proves native
effects, dispatch completion, source provenance or cross-event pointer identity.
"""
from __future__ import annotations

import hashlib
import json
from pathlib import Path
import re

from scar.analysis.call_operand_reader import CallOperandTrace
from scar.analysis.python_call_targets import read_python_call_targets
from scar.ir.program.call_edges import CallRecordAnchor, CallTraceFile
from scar.ir.program.native_callables import (
    ADDRESS_FIELDS, NativeCallableCapture, NativeCallableFact,
    NativeCallableMetadata, build_fields,
)
from scar.ir.record_codec import decode, loads
from scar.trace.files import open_binary, resolve


_META = re.compile(r'native-callable-meta\.([1-9][0-9]*)\.json$')
_EVENT = re.compile(r'native-callables\.([1-9][0-9]*)\.jsonl(?:\.gz)?$')
_ROW_KEYS = {'schema', 'schema_version', 'event_index', 'caller', 'attempt_index',
             'callable_reference', 'carrier', 'fields'}
_LEGACY_FAMILIES = {'codes', 'events', 'meta', 'operands', 'operand-meta'}


def _canonical_file(logical, *, archive=False):
    path = Path(logical)
    if not path.is_absolute() or path.resolve() != path or path.is_symlink():
        raise ValueError('native callable inputs must be original canonical paths')
    if archive:
        compressed = Path(str(path) + '.gz')
        if path.exists() and compressed.exists():
            raise ValueError('ambiguous plain/gzip native callable artifact')
        physical = resolve(path)
    else:
        physical = path
    if (not physical.is_file() or physical.is_symlink()
            or physical.resolve() != physical):
        raise ValueError('native callable input is absent, nonregular or symlinked')
    return path, physical


def _verify_receipt(receipt, *, maximum, expected=None):
    if expected is not None and receipt.path != str(expected):
        raise ValueError('native callable receipt changed its original artifact namespace')
    path, _ = _canonical_file(receipt.path)
    if receipt.bytes > maximum or path.stat().st_size != receipt.bytes:
        raise ValueError('native callable receipt exceeds budget or changed size')
    with path.open('rb') as stream:
        payload = stream.read(receipt.bytes + 1)
    if len(payload) != receipt.bytes or hashlib.sha256(payload).hexdigest() != receipt.sha256:
        raise ValueError('native callable input bytes/SHA differ')
    return payload


def _fact(document):
    if (type(document) is not dict or set(document) != _ROW_KEYS
            or document['schema'] != 'scar.native-callables'
            or type(document['schema_version']) is not int or document['schema_version'] != 1):
        raise ValueError('unsupported native callable event schema/fields')
    return decode(NativeCallableFact,
        {key: value for key, value in document.items() if key not in ('schema', 'schema_version')})


def read_native_callables(trace, *, max_bytes=32_000_000, max_rows=100_000):
    """Freshly verify the optional companion; None is legacy NOT_RECORDED.

    A supported complete profile has exactly one fact per original attempt,
    including UNKNOWN carrier facts. Partial/failed companions are rejected,
    never converted to an empty set or a claim that missing calls did not occur.
    """
    if type(trace) is not CallOperandTrace:
        raise TypeError('native callable reader requires the original CallOperandTrace')
    if any(type(value) is not int or value < 1 for value in (max_bytes, max_rows)):
        raise ValueError('native callable read ceilings must be positive exact integers')
    root = Path(trace.directory)
    if not root.is_absolute() or root.resolve() != root or root.is_symlink():
        raise ValueError('native callable directory must be original and canonical')
    metas, event_processes = {}, set()
    for path in root.iterdir():
        match = _META.fullmatch(path.name)
        if match:
            metas[int(match[1])] = path
        elif (match := _EVENT.fullmatch(path.name)) is not None:
            event_processes.add(int(match[1]))
        elif path.name.startswith('native-callable-meta.') and path.name.endswith('.json.gz'):
            raise ValueError('native callable metadata must be retained as original JSON')
    if not metas and not event_processes:
        return None
    if set(metas) != event_processes:
        raise ValueError('native callable events and metadata must be retained together')
    observed = read_python_call_targets(trace)
    attempts = {(row.caller.process_id, row.attempt_index): row for row in observed.targets}
    expected_processes = {row.process_id for row in trace.metadata}
    if set(metas) != expected_processes:
        raise ValueError('native callable capture does not cover every original CALL process')
    facts, anchors, metadata, files, target_basis = [], [], [], [], []
    total = 0
    seen = set()
    originals = (*trace.frame_scan.files, *trace.files)
    for process, meta_path in sorted(metas.items(), key=lambda row: str(row[1])):
        _canonical_file(str(meta_path))
        if meta_path.stat().st_size > min(max_bytes - total, 1_000_000):
            raise ValueError('native callable metadata byte ceiling exceeded')
        with meta_path.open('rb') as stream:
            payload = stream.read(min(max_bytes - total, 1_000_000) + 1)
        if len(payload) > min(max_bytes - total, 1_000_000):
            raise ValueError('native callable metadata grew beyond its byte ceiling')
        total += len(payload)
        meta = decode(NativeCallableMetadata, loads(payload))
        if (meta.process_id != process or meta.project_root != trace.project_root
                or meta.stopped or meta.io_failed or meta.errors):
            raise ValueError('native callable issuer/scope differs or capture is partial/failed')
        expected_inputs = tuple(row for row in originals if row.process_id == process)
        if ({row.family for row in meta.legacy_inputs} != _LEGACY_FAMILIES
                or len(expected_inputs) != 5 or set(meta.legacy_inputs) != set(expected_inputs)):
            raise ValueError('native callable companion changed the five original CALL receipts')
        target_raw = _verify_receipt(meta.target_meta, maximum=min(1_000_000, max_bytes - total),
            expected=root / f'python-call-target-meta.{process}.json')
        total += len(target_raw)
        target_meta = loads(target_raw)
        target_basis.append((str(meta_path.parent / f'python-call-target-meta.{process}.json'),
            meta.target_meta.sha256, target_meta['file']['path'], target_meta['file']['sha256']))
        for receipt in (meta.probe_source, meta.probe_binary):
            _verify_receipt(receipt, maximum=max_bytes - total)
            total += receipt.bytes
        expected_attempts = {key for key in attempts if key[0] == process}
        if (meta.counts.attempts != len(expected_attempts) or meta.counts.rows != meta.file.rows
                or meta.file.rows != len(expected_attempts)
                or meta.file.rows > meta.budget.max_records
                or meta.file.bytes > meta.budget.max_bytes):
            raise ValueError('native callable denominator/output counts or declared budgets differ')
        expected_path = root / f'native-callables.{process}.jsonl'
        if meta.file.path != str(expected_path):
            raise ValueError('native callable output belongs to another artifact namespace')
        logical, physical = _canonical_file(meta.file.path, archive=True)
        if physical.stat().st_size > max_bytes or total + meta.file.bytes > max_bytes:
            raise ValueError('native callable stored/decoded byte ceiling exceeded')
        files.append(CallTraceFile(str(meta_path), 'native-callable-meta', process,
            hashlib.sha256(payload).hexdigest(), len(payload), payload.count(b'\n')))
        digest = hashlib.sha256()
        size = rows = 0
        line_limit = min(meta.budget.max_line_bytes, 2_000_000)
        with open_binary(logical) as stream:
            while raw := stream.readline(line_limit + 1):
                size += len(raw)
                total += len(raw)
                rows += 1
                if (len(raw) > line_limit or not raw.endswith(b'\n') or not raw.strip()
                        or total > max_bytes or len(facts) >= max_rows
                        or rows > meta.budget.max_records or size > meta.budget.max_bytes):
                    raise ValueError('native callable event/line/decoded byte budget or framing differs')
                digest.update(raw)
                fact = _fact(loads(raw))
                key = process, fact.attempt_index
                target = attempts.get(key)
                if (fact.event_index != rows or fact.caller.process_id != process
                        or target is None or key in seen or fact.caller != target.caller
                        or fact.callable_reference != target.callable_reference):
                    raise ValueError('native callable fact changed original CALL/target identity or sequence')
                for name in ADDRESS_FIELDS:
                    field = getattr(fact.fields, name)
                    if field.value is not None and field.value >= 1 << meta.abi.pointer_bits:
                        raise ValueError('native pointer exceeds the original declared ABI width')
                seen.add(key)
                facts.append(fact)
                anchors.append(CallRecordAnchor(str(logical), rows, hashlib.sha256(raw).hexdigest(), rows))
        if (size, rows, digest.hexdigest()) != (meta.file.bytes, meta.file.rows, meta.file.sha256):
            raise ValueError('native callable original EOF/bytes/rows/SHA differ')
        metadata.append(meta)
        files.append(CallTraceFile(str(logical), 'native-callables', process,
            digest.hexdigest(), size, rows))
    if seen != set(attempts):
        raise ValueError('native callable capture left original attempts unrecorded')
    run = hashlib.sha256(json.dumps(target_basis, sort_keys=True).encode()).hexdigest()
    if run != observed.source_sha256:
        raise ValueError('native callable target metadata changed within its original run basis')
    return NativeCallableCapture(str(root), observed.source_sha256, tuple(facts),
        tuple(anchors), tuple(metadata), tuple(files))


__all__ = ['build_fields', 'read_native_callables']
