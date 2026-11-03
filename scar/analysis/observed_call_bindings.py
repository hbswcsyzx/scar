"""Bind observed CALL objects to retained static ports, without source rewriting.

An observation selects an actual callable for one captured invocation. It does
not prove that object was produced by any class statement, that future calls
select it, or that the called region is pure. Code/source correspondence is
checked using complete descriptors and original compiler and CALL records.
"""
from __future__ import annotations

import argparse
from collections import Counter
from dataclasses import dataclass, replace
import gzip
import hashlib
import json
from pathlib import Path
import re
import time
from types import SimpleNamespace

from scar.analysis.call_operand_reader import CallOperandTrace, read_call_operands
from scar.analysis.program_dependency_export import _Tables
from scar.analysis.python_call_targets import read_python_call_targets
from scar.analysis.static_calls import StaticCallBudget, StaticCallSession
from scar.analysis.static_function_origins import _replay_compilation
from scar.ir.program.call_edges import CallRecordAnchor, CapturedCode, CapturedSite
from scar.ir.program.dependencies import DependencyPoint as Point, GraphNamespace
from scar.ir.program.ids import OperationID, UseID
from scar.ir.program.model import ReferenceValue
from scar.ir.program.python_call_targets import PythonCallTarget
from scar.ir.record_codec import decode, encode
from scar.ir.semantics_v2 import Opcode
from scar.ir.v2.common import SourceReference
from scar.trace.code_snapshot import describe_code, site as code_site


@dataclass(frozen=True, slots=True)
class ObservedCallBinding:
    run_scope: str
    call: Point
    callable: Point
    source: SourceReference
    captured_code: CapturedCode
    captured_site: CapturedSite
    attempt_anchor: CallRecordAnchor
    target_anchor: CallRecordAnchor
    target: PythonCallTarget
    class_origin_verified: bool = False

    def __post_init__(self):
        for value, kind in ((self.call, Point), (self.callable, Point),
                (self.source, SourceReference), (self.captured_code, CapturedCode),
                (self.captured_site, CapturedSite), (self.attempt_anchor, CallRecordAnchor),
                (self.target_anchor, CallRecordAnchor), (self.target, PythonCallTarget)):
            if type(value) is not kind:
                raise TypeError('observed CALL binding requires exact ' + kind.__name__)
            value.__post_init__()
        if (type(self.run_scope) is not str or re.fullmatch(r'[0-9a-f]{64}', self.run_scope) is None
                or type(self.call.node) is not OperationID or type(self.callable.node) is not UseID
                or self.call.namespace != self.callable.namespace
                or self.call.context is not None or self.callable.context is not None
                or self.captured_site.code != self.captured_code.key
                or self.captured_code.filename != self.source.path
                or self.class_origin_verified is not False):
            raise ValueError('observed CALL changed original ports/code or claimed class origin')


def _json(value):
    return (json.dumps(value, ensure_ascii=True, separators=(',', ':'),
                       sort_keys=True, allow_nan=False) + '\n').encode()


def read_observed_call_bindings(document):
    """Strictly decode normalized DTOs; this does not replay original inputs."""
    from scar.analysis.contextual_call_export import _MAX_BYTES, _Reader, _TABLES, _preflight
    from scar.ir.record_codec import loads as strict_loads
    if type(document) in (str, bytes):
        size = len(document.encode('utf-8')) if type(document) is str else len(document)
        if size > _MAX_BYTES:
            raise ValueError('observed CALL binding document byte budget exceeded')
        document = strict_loads(document)
    _preflight(document)
    fields = {'schema', 'schema_version', 'bindings', 'observation_only',
              'class_origin_verified', 'target_set_closed', 'transformation_authorized'}
    if (type(document) is not dict or set(document) != fields | set(_TABLES)
            or document['schema'] != 'scar.observed-call-bindings'
            or type(document['schema_version']) is not int or document['schema_version'] != 1):
        raise ValueError('unsupported observed CALL binding document fields/schema')
    if (document['observation_only'] is not True
            or document['class_origin_verified'] is not False
            or document['target_set_closed'] is not False
            or document['transformation_authorized'] is not False):
        raise ValueError('observed CALL binding cannot assert class origin, closure or authorization')
    reader = _Reader(document)
    result = reader.unpack(tuple[ObservedCallBinding, ...], document['bindings'])
    reader.validate_tables()
    return result


def _read_trace(trace):
    if type(trace) is CallOperandTrace:
        directory, root = Path(trace.directory), trace.project_root
    else:
        directory = Path(trace).resolve()
        metas = sorted(directory.glob('call-operand-meta.*.json'))
        if not metas:
            raise ValueError('original call-operand metadata is required')
        first = metas[0]
        if first.is_symlink() or first.stat().st_size > 2_000_000:
            raise ValueError('bounded original operand metadata required')
        # This root is only a hint: the ordinary reader checks every original
        # metadata record and binds its frame/operand file receipts afresh.
        root = json.loads(first.read_bytes())['project_root']
    return read_call_operands(directory, root)


def _compiler(body):
    context = body.context
    text = context.docs['source']['text']
    if 'sha256:' + hashlib.sha256(text.encode()).hexdigest() != body.metadata.source.fingerprint:
        raise ValueError('retained source fingerprint differs')
    root = getattr(context, 'compiled_module_for_namespace', None)
    if root is None:
        root = compile(text, body.metadata.source.path, 'exec', flags=0,
                       dont_inherit=True, optimize=0)
        context.compiled_module_for_namespace = root
    inputs = SimpleNamespace(document=body.document, metadata=body.metadata,
        sources=body.module if body.module is not None else body.metadata, namespace=body.namespace)
    return _replay_compilation(inputs, root, context.unit['namespace_root'])[1]


def _candidate(entry, captured):
    # Names are a cheap selection policy only. Complete original CodeRef and
    # captured descriptor equality below are the actual correspondence proof.
    name = entry['qualname'].removeprefix('<module>.')
    name = re.sub(r'<lambda@\d+:\d+>', '<lambda>', name)
    return name == captured.qualname.replace('.<locals>.', '.')


def _locate(owner, captured, selected_site, issues, cache):
    key = captured, selected_site
    if key in cache:
        return cache[key]
    matches = []
    numbers = [i for i, unit in enumerate(owner.units) if unit['path'] == captured.filename]
    if not numbers:
        raise LookupError('CALLER_SOURCE_UNIT_UNAVAILABLE: captured filename has no supplied source unit')
    for number in numbers:
        owner._check()
        context = owner._unit(number)
        for entry in context.catalog['entries']:
            if not _candidate(entry, captured):
                continue
            row_pair = context.body_rows.get(entry['entry_key'])
            if row_pair is None or 'artifact' not in row_pair[1]:
                issues.append({'kind': 'CALLER_CANONICAL_BODY_UNAVAILABLE',
                               'entry': entry['entry_key'], 'file': captured.filename})
                continue
            position, row = row_pair
            try:
                body = owner._body(context, position, row)
                if body is None:
                    raise LookupError('CALLER_CANONICAL_BODY_UNAVAILABLE')
                code = _compiler(body)
                if describe_code(code) != encode(captured):
                    continue
                if decode(CapturedSite, code_site(code, selected_site.offset)) != selected_site:
                    raise LookupError('CAPTURED_CALL_SITE_MISMATCH')
                if selected_site.opname is None or not selected_site.opname.startswith('CALL'):
                    raise LookupError('CAPTURED_SITE_IS_NOT_CALL')
                links = [link for link in body.operation_links if link.opcode is Opcode.CALL
                    and type(link.source) is SourceReference and
                    (link.source.start_line, link.source.end_line, link.source.start_column,
                     link.source.end_column) == selected_site.position]
                if len(links) != 1:
                    raise LookupError('ORIGINAL_CANONICAL_CALL_NOT_UNIQUE')
                link, = links
                uses = [item.use for item in body.uses_by_op[link.operation] if item.role == 'callee']
                if len(uses) != 1:
                    raise LookupError('ORIGINAL_CALL_CALLEE_USE_NOT_UNIQUE')
                use = body.index.use_site(uses[0])
                if (use.operation != link.operation
                        or type(body.index.values[use.use.value]) is not ReferenceValue):
                    raise ValueError('original CALL callee is not its owned reference Use')
                namespace = GraphNamespace.from_source(body.namespace)
                matches.append((Point(namespace, link.operation, None),
                                Point(namespace, uses[0], None), link.source))
            except (ValueError, LookupError, TypeError, SyntaxError) as error:
                issues.append({'kind': 'CALLER_SOURCE_OR_INTERFACE_OPEN', 'entry': entry['entry_key'],
                               'file': captured.filename, 'detail': type(error).__name__ + ': ' + str(error)})
    if len(matches) != 1:
        raise LookupError('CALLER_CODE_OR_PORT_NOT_UNIQUE: ' + str(len(matches)) + ' complete matches')
    cache[key] = matches[0]
    return matches[0]


def build_observed_call_bindings(model, trace, out, budget=None):
    """Fresh offline join over original raw capture and retained static shards.

    ``trace`` accepts a directory or normal CallOperandTrace (reread afresh).
    Neither program execution nor target imports occur in this function.
    """
    started = time.monotonic()
    out = Path(out).absolute()
    if out.resolve() != out or out.is_symlink() or (out.exists() and
            (not out.is_dir() or any(out.iterdir()))):
        raise FileExistsError('observed-call output must be a fresh or empty canonical directory')
    limits = StaticCallBudget() if budget is None else budget
    if type(limits) is not StaticCallBudget:
        raise TypeError('observed CALL binding needs StaticCallBudget')
    limits.__post_init__()
    raw = _read_trace(trace)
    observed = read_python_call_targets(raw)
    captures = {(capture.process_id, capture.code.key): capture.code for capture in raw.frame_scan.captures}
    attempts = {(attempt.process_id, attempt.index): attempt for attempt in raw.attempts}
    bindings, issues, cache = [], [], {}
    owner = StaticCallSession(model, out=out / 'source-basis', budget=limits)
    stable = False
    try:
        for target, anchor in zip(observed.targets, observed.target_anchors):
            attempt = attempts[target.caller.process_id, target.attempt_index]
            try:
                owner._check()
                if len(bindings) >= limits.max_calls:
                    raise OverflowError('observed binding count budget exhausted')
                captured = captures.get((attempt.process_id, attempt.site.code))
                if captured is None:
                    raise LookupError('CALLER_CAPTURED_CODE_UNAVAILABLE')
                call, callable_point, source = _locate(owner, captured, attempt.site, issues, cache)
                bindings.append(ObservedCallBinding(observed.source_sha256, call, callable_point,
                    source, captured, attempt.site, attempt.anchor, anchor, target))
            except (LookupError, ValueError, TypeError, OverflowError, TimeoutError) as error:
                issues.append({'kind': 'OBSERVED_CALL_UNBOUND', 'process_id': attempt.process_id,
                    'attempt_index': attempt.index, 'detail': type(error).__name__ + ': ' + str(error)})
                if isinstance(error, (OverflowError, TimeoutError)):
                    break
    finally:
        owner.close()
        stable = True
    table = _Tables()
    document = {'schema': 'scar.observed-call-bindings', 'schema_version': 1,
        'bindings': [table.pack(binding) for binding in bindings],
        'observation_only': True, 'class_origin_verified': False,
        'target_set_closed': False, 'transformation_authorized': False}
    document.update(table.tables)
    decoded = _json(document)
    stored = gzip.compress(decoded, compresslevel=3, mtime=0)
    if len(decoded) > limits.max_record_bytes or len(stored) > limits.max_output_bytes:
        raise OverflowError('observed CALL result exceeds output byte budget')
    out.mkdir(parents=True, exist_ok=True)
    with (out / 'bindings.json.gz').open('xb') as stream:
        stream.write(stored)
    report = {'schema': 'scar.observed-call-binding-summary', 'schema_version': 1,
        'model': str(owner.root), 'input_manifest_sha256': owner.manifest_sha256,
        'trace': raw.directory, 'run_scope': observed.source_sha256,
        'observed_attempts': len(observed.targets), 'binding_count': len(bindings),
        'bindings': [{'call_operation': binding.call.node.wire,
            'callee_use': binding.callable.node.wire, 'source': encode(binding.source),
            'kind': binding.target.kind.value, 'callable_reference': binding.target.callable_reference,
            'process_id': binding.target.caller.process_id, 'thread_id': binding.target.caller.thread_id,
            'invocation_id': binding.target.caller.invocation_id,
            'attempt_index': binding.target.attempt_index, 'class_origin_verified': False}
            for binding in bindings],
        'target_kinds': dict(Counter(binding.target.kind.value for binding in bindings)),
        'issues': issues, 'input_receipts_stable_at_close': stable,
        'raw_capture_files': encode((*raw.frame_scan.files, *raw.files)),
        'artifacts': [{'path': 'bindings.json.gz', 'bytes': len(stored),
            'sha256': hashlib.sha256(stored).hexdigest(), 'decoded_bytes': len(decoded),
            'decoded_sha256': hashlib.sha256(decoded).hexdigest()}],
        'measurements': dict(owner.counts), 'analyzer_seconds': time.monotonic() - started,
        'target_executed': False, 'trace_represents_observed_execution': True,
        'observation_only': True, 'class_origin_verified': False,
        'target_set_closed': False, 'whole_program_complete': False,
        'transformation_authorized': False}
    with (out / 'summary.json').open('xb') as stream:
        stream.write(_json(report))
    return report


def main(argv=None):
    parser = argparse.ArgumentParser(prog='scar observed-calls')
    parser.add_argument('--model', required=True)
    parser.add_argument('--trace', required=True)
    parser.add_argument('--out', required=True)
    parser.add_argument('--max-seconds', type=int, default=180)
    args = parser.parse_args(argv)
    report = build_observed_call_bindings(args.model, args.trace, args.out,
        replace(StaticCallBudget(), max_seconds=args.max_seconds))
    print(json.dumps({key: report[key] for key in
        ('binding_count', 'observed_attempts', 'target_kinds', 'analyzer_seconds', 'issues')},
        ensure_ascii=False, sort_keys=True))
    return 0


__all__ = ['ObservedCallBinding', 'build_observed_call_bindings', 'read_observed_call_bindings', 'main']
