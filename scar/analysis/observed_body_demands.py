"""Captured code selects missing static bodies through original compiler paths.

Observation supplies a demand, not a replacement graph. Retained source is
compiled without execution, lexical occurrences and complete code descriptors
are checked, all readers close, and the ordinary static lowerer builds only
previously unmaterialized entries. Existing canonical bodies are not replaced.
"""
from __future__ import annotations

import ast
from collections import defaultdict
from dataclasses import dataclass
import hashlib
from pathlib import Path
import sys
import time

from scar.analysis.observed_call_bindings import _json, _read_trace
from scar.analysis.observed_code_correspondence import ObservedCodeSources, SourceScopeAuthority
from scar.analysis.python_call_targets import read_python_call_targets
from scar.analysis.static_calls import StaticCallBudget, StaticCallSession
from scar.analysis.static_compilation import StaticCodeEvidence, _scope_nodes
from scar.analysis.static_rules import _at_path
from scar.ir.program.call_edges import CodeCapture
from scar.ir.program.source_references import SourceArtifactLocator
from scar.ir.program.source_subjects import ModuleUnitSource, SourceCompilationCodeRef
from scar.ir.record_codec import decode, encode
from scar.ir.semantics_v2 import SourceSnapshot
from scar.ir.v2.common import SourceReference
from scar.ir.v2.ids import OperationDefinitionID
from scar.trace.code_snapshot import code_key, describe_code


@dataclass(frozen=True, slots=True)
class ObservedBodyDemand:
    run_scope: str
    capture: CodeCapture
    unit_number: int
    entry_key: str
    lexical_entry: SourceArtifactLocator
    source_artifact: SourceArtifactLocator
    compiler: SourceCompilationCodeRef
    source_authority: SourceScopeAuthority

    def __post_init__(self):
        for value, kind in ((self.capture, CodeCapture), (self.lexical_entry, SourceArtifactLocator),
                (self.source_artifact, SourceArtifactLocator), (self.compiler, SourceCompilationCodeRef),
                (self.source_authority, SourceScopeAuthority)):
            if type(value) is not kind:
                raise TypeError('observed body demand needs exact ' + kind.__name__)
            post = getattr(value, '__post_init__', None)
            if post is not None:
                post()
        compiler_source = (self.compiler.source.snapshot if type(self.compiler.source) is ModuleUnitSource
                           else self.compiler.source)
        if (type(self.run_scope) is not str or len(self.run_scope) != 64
                or type(self.unit_number) is not int or self.unit_number < 0
                or type(self.entry_key) is not str or not self.entry_key.startswith('lexical:')
                or self.compiler.code_layout_key != self.capture.code.key
                or self.source_authority.run_scope != self.run_scope
                or self.source_authority.capture != self.capture
                or self.source_authority.source.path != compiler_source.path
                or self.source_authority.source.fingerprint != compiler_source.fingerprint):
            raise ValueError('observed body demand changed original captured/compiler identity')


def _span(value):
    return value.start_line, value.end_line, value.start_column, value.end_column


def _source(owner, number):
    unit = owner.units[number]
    catalog = owner._catalog(number)
    source = owner._read(unit['artifacts']['source'])
    if (source.get('schema') != 'scar.static-source-text' or source.get('schema_version') != 1
            or source.get('path') != unit['path'] or source.get('namespace_root') != unit['namespace_root']
            or source.get('decoded_sha256') != unit['decoded_sha256']
            or hashlib.sha256(source['text'].encode()).hexdigest() != unit['decoded_sha256']):
        raise ValueError('retained source text/namespace differs from its original unit receipt')
    text = source['text']
    tree = ast.parse(text, filename=unit['path'])
    root = compile(text, unit['path'], 'exec', flags=0, dont_inherit=True, optimize=0)
    scopes, issues = {}, []
    _scope_nodes(tree, root, (), ast.Module, scopes, issues)
    return catalog, tree, root, scopes, issues


def _entry_code(entry, tree, root, scopes, snapshot):
    node = _at_path(tree, entry['ast_path'])
    ids = entry.get('semantic_definition_ids') or ()
    if len(ids) != 1:
        raise LookupError('LEXICAL_ENTRY_DEFINITION_NOT_UNIQUE')
    definition = decode(OperationDefinitionID, ids[0])
    if entry['kind'] == 'MODULE' and type(node) is ast.Module:
        return definition, ModuleUnitSource(snapshot, entry['namespace_root'], definition), (), root
    expected = {'FUNCTION': ast.FunctionDef, 'ASYNC_FUNCTION': ast.AsyncFunctionDef, 'CLASS': ast.ClassDef}
    if expected.get(entry['kind']) is not type(node):
        raise LookupError('LEXICAL_COMPILER_SCOPE_KIND_UNSUPPORTED')
    source = decode(SourceReference, entry['source_ref'])
    if (source.path != snapshot.path or source.fingerprint != snapshot.fingerprint
            or (node.lineno, node.end_lineno, node.col_offset, node.end_col_offset) != _span(source)):
        raise ValueError('lexical entry occurrence differs from its retained source reference')
    rows = [(path, code) for path, code, scope in scopes.get(_span(source), ()) if scope is node]
    if len(rows) != 1:
        raise LookupError('LEXICAL_COMPILER_PATH_NOT_UNIQUE')
    path, code = rows[0]
    return definition, source, path, code


def expand_observed_bodies(model, trace, out, budget=None, max_bodies=32, *,
                           max_source_files=8, max_source_bytes=8 * 1024 * 1024):
    """Plan from original capture, close readers, then add missing static bodies.

    ``out`` is a separate expansion report directory. The observed-calls CLI
    subsequently reconnects the same retained trace using a fresh reader.
    """
    started = time.monotonic()
    out, model = Path(out).absolute(), Path(model).absolute()
    if (out.resolve() != out or out.is_symlink() or out.is_relative_to(model)
            or out.exists() and (not out.is_dir() or any(out.iterdir()))):
        raise FileExistsError('body-demand report needs a fresh canonical directory outside the model')
    limits = StaticCallBudget() if budget is None else budget
    if type(limits) is not StaticCallBudget:
        raise TypeError('observed body demands need StaticCallBudget')
    if type(max_bodies) is not int or max_bodies < 1 or max_bodies > limits.max_bodies:
        raise ValueError('max_bodies must be positive and within the static body budget')
    from scar.analysis.observed_source_demands import expand_observed_sources
    source_expansion = expand_observed_sources(model, trace, out / 'sources', limits,
        max_source_files=max_source_files, max_source_bytes=max_source_bytes)
    # Source publication closes its readers before mutation. Reopen original
    # capture and the updated canonical source owner for the separate body phase.
    trace = _read_trace(trace)
    observed = read_python_call_targets(trace)
    code_sources = ObservedCodeSources(trace, observed.source_sha256)
    metadata = {meta.process_id: meta for meta in trace.metadata}
    groups = defaultdict(list)
    issues = []
    for capture in trace.frame_scan.captures:
        meta = metadata.get(capture.process_id)
        if meta is None or meta.implementation != sys.implementation.name or meta.python != sys.version:
            issues.append({'kind': 'CAPTURE_COMPILER_PROFILE_UNSUPPORTED', 'code': capture.code.key,
                           'process_id': capture.process_id})
            continue
        groups[capture.code.filename].append(capture)
    requests, already, matches, unmatched_reasons = {}, {}, {}, {}
    owner = StaticCallSession(model, out=out / 'source-basis', budget=limits)
    prior = owner.manifest_sha256
    try:
        by_path = defaultdict(list)
        for number, unit in enumerate(owner.units):
            by_path[unit['path']].append(number)
        for filename, captures in groups.items():
            try:
                owner._check()
                numbers = by_path.get(filename, ())
                if not numbers:
                    kind = ('CAPTURE_SOURCE_UNIT_UNAVAILABLE' if Path(filename).is_absolute()
                            else 'CAPTURE_NONFILESYSTEM_SOURCE_UNAVAILABLE')
                    issues.append({'kind': kind, 'file': filename,
                                   'codes': sorted({item.code.key for item in captures})})
                    continue
                for number in numbers:
                    owner._check()
                    unit = owner.units[number]
                    if any(kind not in unit['artifacts'] for kind in ('source', 'lexical')):
                        raise LookupError('RETAINED_SOURCE_OR_LEXICAL_INPUT_UNAVAILABLE')
                    catalog, tree, root, scopes, scope_issues = _source(owner, number)
                    snapshot = SourceSnapshot(filename, 'sha256:' + unit['decoded_sha256'],
                                              'utf-8', f'{sys.version_info.major}.{sys.version_info.minor}')
                    rows = {row['entry_key']: row for row in unit['bodies']}
                    root_key = code_key(root)
                    wanted = defaultdict(list)
                    for capture in captures:
                        wanted[capture.code.qualname, capture.code.first_line].append(capture)
                    for ordinal, entry in enumerate(catalog['entries']):
                        owner._check()
                        if entry['kind'] not in ('MODULE', 'FUNCTION', 'ASYNC_FUNCTION', 'CLASS'):
                            continue
                        try:
                            definition, source, path, code = _entry_code(entry, tree, root, scopes, snapshot)
                        except LookupError:
                            continue  # Unmatched captures receive an explicit issue below.
                        selected = wanted.get((code.co_qualname, code.co_firstlineno), ())
                        if not selected:
                            continue
                        description = describe_code(code)
                        for capture in selected:
                            if description != encode(capture.code):
                                continue
                            try:
                                source_authority = code_sources.require_source(capture, snapshot)
                            except (LookupError, ValueError, TypeError) as error:
                                issues.append({'kind': 'CAPTURE_CODE_SOURCE_SCOPE_OPEN',
                                    'code': capture.code.key, 'process_id': capture.process_id,
                                    'detail': type(error).__name__ + ': ' + str(error)})
                                continue
                            record_key = capture.process_id, capture.code.key
                            matches.setdefault(record_key, []).append(entry['entry_key'])
                            row = rows.get(entry['entry_key'])
                            if row is None or row.get('definitions') != entry.get('semantic_definition_ids'):
                                raise ValueError('original body ledger changed the selected lexical definition')
                            if 'artifact' in row:
                                already[entry['entry_key']] = None
                                continue
                            evidence = StaticCodeEvidence(snapshot, unit['namespace_root'], definition, source,
                                path, code, code_key(code), sys.implementation.name, tuple(sys.version_info[:3]),
                                sys.version, sys.implementation.cache_tag, root_code_layout_key=root_key)
                            demand = ObservedBodyDemand(observed.source_sha256, capture, number, entry['entry_key'],
                                owner._locator(unit['artifacts']['lexical'], 'scar.static-lexical-catalog/1',
                                    '#/entries/' + str(ordinal), f'#/units/{number}/artifacts/lexical'),
                                owner._locator(unit['artifacts']['source'], 'scar.static-source-text/1', '#',
                                    f'#/units/{number}/artifacts/source'), evidence.to_reference(),
                                source_authority)
                            requests.setdefault(entry['entry_key'], demand)
                    # Distinguish missing scope adapters from actual code
                    # mismatches without guessing from a display name.
                    unresolved = [item for item in captures
                        if not matches.get((item.process_id, item.code.key))]
                    for capture in unresolved:
                        unmatched_reasons.setdefault((capture.process_id, capture.code.key),
                                                     'CAPTURE_CODE_DESCRIPTOR_MISMATCH')
                    pending = [root]
                    while pending and unresolved:
                        owner._check()
                        compiled_code = pending.pop()
                        pending.extend(item for item in compiled_code.co_consts
                                       if type(item) is type(root))
                        for capture in unresolved:
                            if ((compiled_code.co_qualname, compiled_code.co_firstlineno)
                                    != (capture.code.qualname, capture.code.first_line)):
                                continue
                            same = describe_code(compiled_code) == encode(capture.code)
                            if same:
                                unmatched_reasons[capture.process_id, capture.code.key] = (
                                    'CAPTURE_COMPILER_SCOPE_ADAPTER_UNAVAILABLE')
            except (LookupError, ValueError, SyntaxError, TypeError, OverflowError, TimeoutError) as error:
                issues.append({'kind': 'CAPTURE_SOURCE_COMPILER_MAPPING_OPEN', 'file': filename,
                               'detail': type(error).__name__ + ': ' + str(error)})
                if isinstance(error, (OverflowError, TimeoutError)):
                    break
        ambiguous = set()
        for capture in trace.frame_scan.captures:
            candidates = matches.get((capture.process_id, capture.code.key), ())
            if len(candidates) != 1:
                ambiguous.update(candidates)
                reason = ('CAPTURE_LEXICAL_ENTRY_AMBIGUOUS' if candidates else
                    unmatched_reasons.get((capture.process_id, capture.code.key),
                                          'CAPTURE_LEXICAL_CODE_MAPPING_UNAVAILABLE'))
                issues.append({'kind': reason, 'code': capture.code.key,
                    'file': capture.code.filename, 'candidates': candidates,
                    'detail': 'Generated/unsupported/mismatched code is not selected by spelling or line number.'})
        for entry in ambiguous:
            requests.pop(entry, None)
        selected = list(requests)[:max_bodies]
        if len(requests) > max_bodies:
            issues.append({'kind': 'OBSERVED_BODY_DEMAND_BUDGET', 'remaining': len(requests) - max_bodies})
        plan = {'schema': 'scar.observed-body-demand-plan', 'schema_version': 1,
            'model': str(model), 'prior_manifest_sha256': prior, 'run_scope': observed.source_sha256,
            'source_expansion_result': str(out / 'sources' / 'result.json'),
            'requests': encode(tuple(requests[key] for key in selected)), 'requested_entries': selected,
            'already_materialized_entries': list(already), 'issues': issues,
            'target_executed': False, 'runtime_class_identity_proved': False,
            'qualification': 'Complete code/source correspondence selects static lowering, not transformation.'}
    finally:
        owner.close()  # All artifact/source owners close before model mutation.
    out.mkdir(parents=True, exist_ok=True)
    with (out / 'plan.json').open('xb') as stream:
        stream.write(_json(plan))
    results = []
    if selected:
        from scar.analysis.static_body import expand_static_bodies
        updated = expand_static_bodies(model, jobs=1, entries=tuple(selected),
                                       max_bodies=len(selected), additive_only=True)
        wanted = set(selected)
        results = [dict(row) for unit in updated['units'] for row in unit['bodies'] if row['entry_key'] in wanted]
    published = hashlib.sha256((model / 'manifest.json').read_bytes()).hexdigest()
    expanded = [row['entry_key'] for row in results
                if row.get('status') == 'LOWERED_WITH_GAPS' and 'artifact' in row]
    report = {'schema': 'scar.observed-body-expansion', 'schema_version': 1,
        'model': str(model), 'trace': trace.directory, 'plan': str(out / 'plan.json'),
        'prior_manifest_sha256': prior, 'published_manifest_sha256': published,
        'source_expansion': source_expansion,
        'requested_entries': selected, 'request_count': len(selected),
        'expanded_entries': expanded, 'expanded_body_count': len(expanded),
        'already_materialized_entries': list(already), 'results': results, 'issues': issues,
        'readers_closed_before_expansion': True, 'additive_only': True,
        'target_executed': False, 'whole_program_complete': False,
        'analyzer_seconds': time.monotonic() - started}
    with (out / 'result.json').open('xb') as stream:
        stream.write(_json(report))
    return report


__all__ = ['ObservedBodyDemand', 'expand_observed_bodies']
