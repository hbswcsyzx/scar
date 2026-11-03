"""Bind observed CALL objects to retained static ports, without source rewriting.

An observation selects an actual callable for one captured invocation. It does
not prove that object was produced by any class statement, that future calls
select it, or that the called region is pure. Code/source correspondence is
checked using complete descriptors and original compiler and CALL records.
"""
from __future__ import annotations

import argparse
import ast
from collections import Counter, defaultdict
from dataclasses import dataclass, replace
import gzip
import hashlib
import json
from pathlib import Path
import re
import sys
import time
from types import SimpleNamespace

from scar.analysis.call_operand_reader import CallOperandTrace, read_call_operands
from scar.analysis.program_dependency_export import _Tables
from scar.analysis.python_call_targets import read_python_call_targets
from scar.analysis.static_calls import StaticCallBudget, StaticCallSession
from scar.analysis.static_function_origins import _replay_compilation
from scar.analysis.static_compilation import StaticCodeEvidence
from scar.ir.program.call_edges import CallRecordAnchor, CapturedCode, CapturedSite
from scar.ir.program.dependencies import DependencyPoint as Point, GraphNamespace
from scar.ir.program.ids import OperationID, UseID
from scar.ir.program.model import ReferenceValue
from scar.ir.program.python_call_targets import ObservedPythonCallGraph, PythonCallTarget
from scar.ir.record_codec import decode, encode
from scar.ir.semantics_v2 import Opcode
from scar.ir.v2.common import SourceReference
from scar.trace.code_snapshot import code_key, describe_code, site as code_site


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


@dataclass(frozen=True, slots=True)
class ObservedRawEvidence:
    """Original bounded reader results, never a serialized validation token."""
    trace: CallOperandTrace
    targets: ObservedPythonCallGraph

    def __post_init__(self):
        if (type(self.trace) is not CallOperandTrace or type(self.targets) is not ObservedPythonCallGraph
                or self.trace.directory != self.targets.source):
            raise ValueError('observed evidence requires the same original trace/target collection')
        self.targets.__post_init__()


def _dependency_session(owner):
    from scar.analysis.program_dependency_session import ProgramDependencySession
    return type(owner) is ProgramDependencySession


def _check_owner(owner):
    (owner.check if _dependency_session(owner) else owner._check)()


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
    path, code = _replay_compilation(inputs, root, context.unit['namespace_root'])
    subject = (body.module.declaration.compilation.source if body.namespace.source is None
               else body.namespace.source)
    body.code_compilation = StaticCodeEvidence(body.metadata.source, context.unit['namespace_root'],
        body.namespace.definition, subject, path, code, code_key(code), sys.implementation.name,
        tuple(sys.version_info[:3]), sys.version, sys.implementation.cache_tag,
        root_code_layout_key=code_key(root)).to_reference()
    return code


def _checked_code(body, capture, cache, code=None):
    """Authorize this original body only, using this run's source/code facts."""
    if code is None:
        code = _compiler(body)
    correspondence = cache['observed-code-sources'].require(
        capture, body, code, body.code_compilation)
    cache['observed-code-correspondence', capture] = correspondence
    return code


def _candidate(entry, captured):
    # Names are a cheap selection policy only. Complete original CodeRef and
    # captured descriptor equality below are the actual correspondence proof.
    name = entry['qualname'].removeprefix('<module>.')
    name = re.sub(r'<lambda@\d+:\d+>', '<lambda>', name)
    return name == captured.qualname.replace('.<locals>.', '.')


def _session_body(session, number, position, cache):
    """A small source adapter over this session's original graph/index only."""
    session.check()
    original = session._base_body(number, position)
    original = session.load_body(original.namespace)  # Recheck supplied authority/namespace.
    key = 'observed-session-source-context', number
    context = cache.get(key)
    if context is None:
        tree, semantic, text = session.source_context(original)
        refs = {(atom.kind, atom.reference.start_line, atom.reference.end_line,
            atom.reference.start_column, atom.reference.end_column): atom.reference
            for atom in semantic.source_atoms.values()}
        nodes = {}
        for node in ast.walk(tree):
            if type(node) is ast.Call:
                reference = refs.get((type(node).__name__, node.lineno, node.end_lineno,
                                      node.col_offset, node.end_col_offset))
                if reference is not None:
                    nodes[reference.atom_id] = node
        context = SimpleNamespace(number=number, unit=original.unit, tree=tree, semantic=semantic,
            refs=refs, call_nodes=nodes, docs={'source': {'text': text}})
        cache[key] = context
    links = original.module.operation_links if original.module is not None else original.metadata.operation_links
    uses = original.module.use_links if original.module is not None else original.metadata.use_links
    by_operation = defaultdict(list)
    for use in uses:
        if original.index.use_site(use.use).operation != use.operation:
            raise ValueError('observed source Use belongs to another original operation')
        by_operation[use.operation].append(use)
    # This existing routine reads only the supplied source atoms/records; no
    # StaticCallSession fields, constructor, body cache or basis are borrowed.
    StaticCallSession._check_source_references(session, context, (original.metadata, links, uses))
    return SimpleNamespace(**{**vars(original), 'context': context,
        'operation_links': links, 'use_links': uses, 'uses_by_op': by_operation})


def _locate_session_body(session, capture, issues, cache):
    captured = capture.code
    key = 'observed-code-body', capture
    if key in cache:
        body = _session_body(session, *cache[key], cache)
        return body, _checked_code(body, capture, cache)
    matches = []
    numbers = [number for number, unit in enumerate(session.units) if unit['path'] == captured.filename]
    if not numbers:
        raise LookupError('CALLER_SOURCE_UNIT_UNAVAILABLE: captured filename has no supplied source unit')
    for number in numbers:
        session.check()
        unit = session.units[number]
        rows = {row['entry_key']: (position, row) for position, row in enumerate(unit['bodies'])}
        for entry in session._catalog(number)['entries']:
            if not _candidate(entry, captured):
                continue
            pair = rows.get(entry['entry_key'])
            if pair is None or 'artifact' not in pair[1]:
                issues.append({'kind': 'CALLER_CANONICAL_BODY_UNAVAILABLE',
                    'entry': entry['entry_key'], 'file': captured.filename})
                continue
            try:
                body = _session_body(session, number, pair[0], cache)
                code = _compiler(body)
                if describe_code(code) == encode(captured):
                    _checked_code(body, capture, cache, code)
                    matches.append((number, pair[0]))
            except (ValueError, LookupError, TypeError, SyntaxError) as error:
                issues.append({'kind': 'CALLER_SOURCE_OR_INTERFACE_OPEN', 'entry': entry['entry_key'],
                    'file': captured.filename, 'detail': type(error).__name__ + ': ' + str(error)})
    if len(matches) != 1:
        raise LookupError('CAPTURED_CODE_BODY_NOT_UNIQUE: ' + str(len(matches)) + ' complete matches')
    cache[key] = matches[0]
    body = _session_body(session, *matches[0], cache)
    return body, _checked_code(body, capture, cache)


def _locate_body(owner, capture, issues, cache):
    """Share original body coordinates, never a second graph or code owner."""
    if _dependency_session(owner):
        return _locate_session_body(owner, capture, issues, cache)
    captured = capture.code
    key = 'observed-code-body', capture
    if key in cache:
        number, position = cache[key]
        body = owner._body(owner._unit(number), position, owner.units[number]['bodies'][position])
        return body, _checked_code(body, capture, cache)
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
                _checked_code(body, capture, cache, code)
                matches.append((number, position))
            except (ValueError, LookupError, TypeError, SyntaxError) as error:
                issues.append({'kind': 'CALLER_SOURCE_OR_INTERFACE_OPEN', 'entry': entry['entry_key'],
                               'file': captured.filename, 'detail': type(error).__name__ + ': ' + str(error)})
    if len(matches) != 1:
        raise LookupError('CAPTURED_CODE_BODY_NOT_UNIQUE: ' + str(len(matches)) + ' complete matches')
    cache[key] = matches[0]
    number, position = matches[0]
    body = owner._body(owner._unit(number), position, owner.units[number]['bodies'][position])
    return body, _checked_code(body, capture, cache)


def _call_positions(body, link):
    """Compiler positions selecting one original source CALL, not new atoms.

    CPython 3.14.7 codegen.c:update_start_location_to_match_attr shortens
    multiline method CALL/CALL_KW locations to the final attribute name.
    It uses the normalized identifier's Unicode length, not its UTF-8 size.
    The owning code descriptor and exact bytecode site are checked separately.
    https://github.com/python/cpython/blob/v3.14.7/Python/codegen.c
    """
    source = link.source
    position = (source.start_line, source.end_line, source.start_column, source.end_column)
    node = body.context.call_nodes.get(source.atom_id)
    if (type(node) is not ast.Call or type(node.func) is not ast.Attribute
            or type(node.func.ctx) is not ast.Load or node.lineno == node.func.end_lineno
            or any(type(arg) is ast.Starred for arg in node.args)
            or any(keyword.arg is None for keyword in node.keywords)):
        return (position,)
    from scar.analysis.attribute_selector import _cpython_attribute_positions
    return _cpython_attribute_positions(node.func, position)


def _locate(owner, capture, selected_site, issues, cache):
    key = capture, selected_site
    if key in cache:
        return cache[key]
    body, code = _locate_body(owner, capture, issues, cache)
    if decode(CapturedSite, code_site(code, selected_site.offset)) != selected_site:
        raise LookupError('CAPTURED_CALL_SITE_MISMATCH')
    if selected_site.opname is None or not selected_site.opname.startswith('CALL'):
        raise LookupError('CAPTURED_SITE_IS_NOT_CALL')
    links = [link for link in body.operation_links if link.opcode is Opcode.CALL
        and type(link.source) is SourceReference and
        selected_site.position in _call_positions(body, link)]
    if len(links) != 1:
        raise LookupError('ORIGINAL_CANONICAL_CALL_NOT_UNIQUE')
    link, = links
    atom = body.context.semantic.source_atoms.get(link.source.atom_id)
    if atom is None or atom.reference != link.source or atom.kind != 'Call':
        raise ValueError('observed CALL source is not its exact original semantic source atom')
    if link.semantic_operation is not None:
        definition = body.context.semantic.definitions.get(link.semantic_operation)
        if (definition is None or definition.code_id != link.source.atom_id.wire
                or link.source.atom_id not in definition.source_atoms):
            raise ValueError('observed CALL names another original semantic definition')
    node = body.context.call_nodes.get(link.source.atom_id)
    expected = None if node is None else body.context.refs.get((type(node.func).__name__,
        node.func.lineno, node.func.end_lineno, node.func.col_offset, node.func.end_col_offset))
    callee_links = [item for item in body.uses_by_op[link.operation] if item.role == 'callee']
    uses = [item.use for item in callee_links]
    if len(uses) != 1:
        raise LookupError('ORIGINAL_CALL_CALLEE_USE_NOT_UNIQUE')
    use = body.index.use_site(uses[0])
    operation = body.index.operations[link.operation]
    if (use.operation != link.operation or type(body.index.values[use.use.value]) is not ReferenceValue
            or expected is None or callee_links[0].source != expected or callee_links[0].index != 0
            or not operation.invoke_arguments or operation.invoke_arguments[0] != use.use.id):
        raise ValueError('original CALL callee is not its owned reference Use')
    namespace = GraphNamespace.from_source(body.namespace)
    result = Point(namespace, link.operation, None), Point(namespace, uses[0], None), link.source
    cache[key] = result
    return result


def derive_observed_interfaces(session, trace, *, argument_layouts=None):
    """Replay original evidence using one read-only dependency-session owner.

    No existing observed DTO is accepted as evidence. The ordinary readers
    recheck raw EOF/rows/hashes/entries; static bodies, indices and source facts
    belong to the supplied current manifest. No basis, graph or file is written.
    """
    if not _dependency_session(session):
        raise TypeError('observed replay requires the current ProgramDependencySession')
    if argument_layouts is not None and (type(argument_layouts) is not dict or argument_layouts):
        raise ValueError('argument_layouts must be an empty output dictionary')
    session.check()
    raw = _read_trace(trace)
    observed = read_python_call_targets(raw)
    evidence = ObservedRawEvidence(raw, observed)
    attempts = {(item.process_id, item.index): item for item in raw.attempts}
    captures = {(item.process_id, item.code.key): item for item in raw.frame_scan.captures}
    bindings, issues, cache = [], [], {}
    from scar.analysis.observed_code_correspondence import ObservedCodeSources
    cache['observed-code-sources'] = ObservedCodeSources(raw, observed.source_sha256)
    for target, anchor in zip(observed.targets, observed.target_anchors):
        attempt = attempts[target.caller.process_id, target.attempt_index]
        try:
            session.check()
            captured = captures.get((attempt.process_id, attempt.site.code))
            if captured is None:
                raise LookupError('CALLER_CAPTURED_CODE_UNAVAILABLE')
            call, callable_point, source = _locate(session, captured, attempt.site, issues, cache)
            bindings.append(ObservedCallBinding(observed.source_sha256, call, callable_point,
                source, captured.code, attempt.site, attempt.anchor, anchor, target))
        except (LookupError, ValueError, TypeError, OverflowError, TimeoutError) as error:
            issues.append({'kind': 'OBSERVED_CALL_UNBOUND', 'process_id': attempt.process_id,
                'attempt_index': attempt.index, 'detail': type(error).__name__ + ': ' + str(error)})
            if isinstance(error, (OverflowError, TimeoutError)):
                break
    from scar.analysis.observed_function_interfaces import derive_observed_function_interfaces
    interfaces, interface_issues = derive_observed_function_interfaces(
        session, raw, observed, tuple(bindings), cache, argument_layouts=argument_layouts)
    return tuple(bindings), interfaces, evidence, tuple((*issues, *interface_issues))


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
    captures = {(capture.process_id, capture.code.key): capture for capture in raw.frame_scan.captures}
    attempts = {(attempt.process_id, attempt.index): attempt for attempt in raw.attempts}
    bindings, issues, cache = [], [], {}
    from scar.analysis.observed_code_correspondence import ObservedCodeSources
    cache['observed-code-sources'] = ObservedCodeSources(raw, observed.source_sha256)
    function_interfaces, function_issues = (), ()
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
                    source, captured.code, attempt.site, attempt.anchor, anchor, target))
            except (LookupError, ValueError, TypeError, OverflowError, TimeoutError) as error:
                issues.append({'kind': 'OBSERVED_CALL_UNBOUND', 'process_id': attempt.process_id,
                    'attempt_index': attempt.index, 'detail': type(error).__name__ + ': ' + str(error)})
                if isinstance(error, (OverflowError, TimeoutError)):
                    break
        from scar.analysis.observed_function_interfaces import derive_observed_function_interfaces
        function_interfaces, function_issues = derive_observed_function_interfaces(
            owner, raw, observed, tuple(bindings), cache)
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
    from scar.analysis.observed_function_interfaces import export_observed_function_interfaces
    function_raw = _json(export_observed_function_interfaces(function_interfaces))
    function_stored = gzip.compress(function_raw, compresslevel=3, mtime=0)
    if (len(function_raw) > limits.max_record_bytes
            or len(function_stored) + len(stored) > limits.max_output_bytes):
        raise OverflowError('observed function interface output byte budget exhausted')
    with (out / 'function-interfaces.json.gz').open('xb') as stream:
        stream.write(function_stored)
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
        'function_interface_count': len(function_interfaces),
        'function_argument_ports': sum(len(item.interface.arguments) for item in function_interfaces),
        'function_completion_routes': sum(len(item.interface.completions) for item in function_interfaces),
        'function_selected_returns': sum(item.selected_return is not None for item in function_interfaces),
        'function_interface_issues': function_issues,
        'issues': issues, 'input_receipts_stable_at_close': stable,
        'raw_capture_files': encode((*raw.frame_scan.files, *raw.files)),
        'artifacts': [{'path': 'bindings.json.gz', 'bytes': len(stored),
            'sha256': hashlib.sha256(stored).hexdigest(), 'decoded_bytes': len(decoded),
            'decoded_sha256': hashlib.sha256(decoded).hexdigest()},
            {'path': 'function-interfaces.json.gz', 'schema': 'scar.observed-function-interfaces/1',
            'bytes': len(function_stored), 'sha256': hashlib.sha256(function_stored).hexdigest(),
            'decoded_bytes': len(function_raw), 'decoded_sha256': hashlib.sha256(function_raw).hexdigest()}],
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
    parser.add_argument('--expand-missing', action='store_true',
                        help='add version-verified missing source units and bodies before reconnecting')
    parser.add_argument('--max-expand-bodies', type=int, default=32)
    parser.add_argument('--max-source-files', type=int, default=8)
    parser.add_argument('--max-source-bytes', type=int, default=8 * 1024 * 1024)
    parser.add_argument('--expansion-out',
                        help='fresh expansion report directory (default: OUT-expansion)')
    args = parser.parse_args(argv)
    limits = replace(StaticCallBudget(), max_seconds=args.max_seconds)
    expansion = None
    if args.expansion_out and not args.expand_missing:
        parser.error('--expansion-out requires --expand-missing')
    if args.expand_missing:
        normal_out = Path(args.out).absolute()
        if (normal_out.resolve() != normal_out or normal_out.is_symlink()
                or normal_out.exists() and (not normal_out.is_dir() or any(normal_out.iterdir()))):
            raise FileExistsError('observed-call output must be fresh before expanding the model')
        expansion_out = (Path(args.expansion_out).absolute() if args.expansion_out else
                         normal_out.with_name(normal_out.name + '-expansion'))
        if expansion_out.is_relative_to(normal_out) or normal_out.is_relative_to(expansion_out):
            raise ValueError('binding and expansion reports need separate directories')
        from scar.analysis.observed_body_demands import expand_observed_bodies
        expansion = expand_observed_bodies(args.model, args.trace, expansion_out,
            limits, max_bodies=args.max_expand_bodies,
            max_source_files=args.max_source_files, max_source_bytes=args.max_source_bytes)
    report = build_observed_call_bindings(args.model, args.trace, args.out, limits)
    if expansion is not None:
        report['body_expansion'] = {'report': str(expansion_out / 'result.json'),
            'request_count': expansion['request_count'],
            'expanded_body_count': expansion['expanded_body_count'],
            'added_source_count': expansion['source_expansion']['added_source_count']}
        (Path(args.out) / 'summary.json').write_bytes(_json(report))
    print(json.dumps({key: report[key] for key in
        ('binding_count', 'observed_attempts', 'target_kinds', 'analyzer_seconds', 'issues')}
        | ({'body_expansion': report['body_expansion']} if expansion is not None else {}),
        ensure_ascii=False, sort_keys=True))
    return 0


__all__ = ['ObservedCallBinding', 'ObservedRawEvidence', 'derive_observed_interfaces',
           'build_observed_call_bindings', 'read_observed_call_bindings', 'main']
