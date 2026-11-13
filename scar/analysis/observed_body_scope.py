"""Select canonical bodies by exact observed code; retain every source template.

This schedules offline lowering, not program reachability or transformation.
Unobserved declarations and unresolved compiler mappings stay in the ledger.
"""
import ast
from collections import defaultdict
from hashlib import sha256
import json
from pathlib import Path

from scar.ir.program.call_edges import CallEdgeBudget, CapturedCode
from scar.ir.record_codec import decode


class _DiscardFrames:
    def entry(self, value): pass
    def exit(self, value): pass
    def abort(self): pass


def read_observed_scope(trace):
    from scar.analysis.call_trace_reader import scan_call_trace
    trace = Path(trace).resolve()
    metadata = sorted(trace.glob('call-meta.*.json'))
    if not metadata or any(p.stat().st_size > 2_000_000 for p in metadata):
        raise ValueError('observed body scope requires original bounded call metadata')
    roots = {json.loads(p.read_bytes())['project_root'] for p in metadata}
    if len(roots) != 1:
        raise ValueError('observed body scope requires one capture namespace')
    budget = CallEdgeBudget(max_events=300000, max_raw_bytes=256_000_000,
        max_lines=600000, max_codes=8192, max_source_files=4096)
    return scan_call_trace(trace, roots.pop(), budget, sink=_DiscardFrames())


def select_observed_bodies(model, trace, entry, *, scope=None):
    from scar.analysis.static_compilation import _scope_nodes
    from scar.analysis.static_program import _read_fragment
    from scar.trace.code_snapshot import describe_code
    model, trace, entry = Path(model), Path(trace).resolve(), Path(entry)
    scan = read_observed_scope(trace) if scope is None else scope
    if Path(scan.directory) != trace:
        raise ValueError('body selection scope belongs to a different trace')
    captured = defaultdict(set)
    for capture in scan.captures:
        captured[capture.code.filename].add(capture.code)
    report = json.loads((model / 'manifest.json').read_bytes())
    selected, matched, mapping_issues = set(), set(), []
    for unit in report['units']:
        observations = captured.get(unit['path'], ())
        if not observations and unit['path'] != str(entry):
            continue
        source = _read_fragment(model, unit['artifacts']['source'])
        raw = Path(unit['path']).read_bytes()
        if sha256(raw).hexdigest() != unit['raw_sha256']:
            raise ValueError('source changed before observed body selection')
        code = compile(raw, unit['path'], 'exec', flags=0, dont_inherit=True, optimize=0)
        mappings, issues = {}, []
        _scope_nodes(ast.parse(source['text'], filename=unit['path']), code, (), ast.Module, mappings, issues)
        mapping_issues.extend(dict(file=unit['path'], detail=str(issue)) for issue in issues)
        catalog = _read_fragment(model, unit['artifacts']['lexical'])
        for declaration in catalog['entries']:
            if declaration['kind'] == 'MODULE':
                candidates = (code,)
            else:
                ref = declaration.get('source_ref')
                if ref is None:
                    continue
                span = (ref['start_line'], ref['end_line'], ref['start_column'], ref['end_column'])
                candidates = tuple(c for _, c, _ in mappings.get(span, ()))
            for candidate in candidates:
                descriptor = decode(CapturedCode, describe_code(candidate))
                if descriptor in observations:
                    selected.add(declaration['entry_key'])
                    matched.add(descriptor.key)
            if declaration['kind'] == 'MODULE' and unit['path'] == str(entry):
                selected.add(declaration['entry_key'])
    if not selected:
        raise ValueError('observed body scope selected no original source entries')
    admitted_paths = {u['path'] for u in report['units']}
    unmatched = [dict(file=code.filename, qualname=code.qualname, code=code.key)
        for codes in captured.values() for code in codes
        if code.filename in admitted_paths and code.key not in matched]
    return tuple(sorted(selected)), dict(schema='scar.observed-body-selection', schema_version=1,
        selected_entries=sorted(selected), captured_codes=sum(map(len, captured.values())),
        matched_codes=len(matched), unmatched_admitted_codes=unmatched, mapping_issues=mapping_issues,
        trace_issues=[str(issue) for issue in scan.issues],
        source_templates_dropped=0, unobserved_paths_proven_dead=False,
        loop_iterations_expanded=0, target_executed_by_selector=False)
