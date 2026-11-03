"""Admit missing source materials selected by original captured Code records.

A filename locates a candidate only. The retained plan's whole-file snapshot
and complete compiler descriptors must agree before ordinary source ingestion.
No import, class-object origin, execution or optimization is inferred here.
"""
from __future__ import annotations

from collections import defaultdict
from hashlib import sha256
from pathlib import Path
import sys
import time
from types import CodeType

from scar.analysis.observed_call_bindings import _json, _read_trace
from scar.analysis.program_dependency_session import _stamp
from scar.analysis.program_observed_dependencies import _inputs
from scar.analysis.python_call_targets import read_python_call_targets
from scar.analysis.static_calls import StaticCallBudget
from scar.analysis.static_sources import _ByteBudget, _Changed, _has_symlink_component, _read_source
from scar.ir.program.call_operands import LEAN_PORTS_RULE
from scar.ir.program.providers import ProviderArtifact
from scar.ir.program.static_sources import StaticSourceFile
from scar.ir.record_codec import decode, encode, loads
from scar.trace.code_snapshot import code_key, describe_code
from scar.trace.lean_capture import LeanCapturePlan


def expand_observed_sources(model, trace, out, budget=None, *, max_source_files=8,
                            max_source_bytes=8 * 1024 * 1024):
    """Append only missing files with a receipt-bound source/compiler match.

    File/byte ceilings bound attempted source reads, including reservations
    for failed reads. Unsupported source-version profiles remain explicit gaps.
    Every input stream is closed before the existing static publisher runs.
    """
    started = time.monotonic()
    limits = StaticCallBudget() if budget is None else budget
    if type(limits) is not StaticCallBudget:
        raise TypeError('observed source demands require StaticCallBudget')
    if any(type(value) is not int or value < 1 for value in (max_source_files, max_source_bytes)):
        raise ValueError('observed source file/byte budgets must be positive exact integers')
    model, out = Path(model).absolute(), Path(out).absolute()
    if (model.resolve() != model or model.is_symlink() or out.resolve() != out or out.is_symlink()
            or out.is_relative_to(model)
            or out.exists() and (not out.is_dir() or any(out.iterdir()))):
        raise FileExistsError('source-demand reports require a fresh canonical directory outside the model')
    manifest_path = model / 'manifest.json'
    before_model = _stamp(manifest_path)
    if (manifest_path.is_symlink() or manifest_path.resolve() != manifest_path
            or before_model[2] > limits.max_manifest_bytes):
        raise ValueError('source demands require the original bounded model manifest')
    with manifest_path.open('rb') as stream:
        original = stream.read(limits.max_manifest_bytes + 1)
    if len(original) != before_model[2] or _stamp(manifest_path) != before_model:
        raise ValueError('source model changed during demand discovery')
    manifest = loads(original)
    if (type(manifest) is not dict or manifest.get('schema') != 'scar.static-program'
            or type(manifest.get('schema_version')) is not int or manifest['schema_version'] != 1
            or type(manifest.get('units')) is not list):
        raise ValueError('source demands require the original static program model')
    prior = sha256(original).hexdigest()
    trace_path = Path(getattr(trace, 'directory', trace)).absolute()
    if trace_path.resolve() != trace_path or trace_path.is_symlink():
        raise ValueError('source demands require the original canonical trace directory')
    trace_before = _inputs(trace_path)
    trace = _read_trace(trace)
    observed = read_python_call_targets(trace)
    present = {unit['path'] for unit in manifest['units']}
    groups = defaultdict(list)
    for capture in trace.frame_scan.captures:
        if capture.code.filename not in present:
            groups[capture.code.filename].append(capture)
    metadata = {item.process_id: item for item in trace.metadata}
    frame_metadata = {item['process_id']: item for item in trace.frame_scan.metadata}
    snapshots, plan_receipts, issues = {}, {}, []
    input_bytes = len(original) + sum(item.raw_bytes for item in (*trace.frame_scan.files, *trace.files))

    def check():
        if time.monotonic() - started > limits.max_seconds:
            raise TimeoutError('observed source demand wall budget exhausted')

    def issue(kind, filename, detail, **fields):
        issues.append({'kind': kind, 'file': filename, 'detail': detail, **fields})

    # _read_trace has independently checked these plan declarations against
    # the original frame/operand receipts. Recheck bytes before using content.
    for process in sorted({capture.process_id for values in groups.values() for capture in values}):
        check()
        if process not in metadata or metadata[process].rule != LEAN_PORTS_RULE:
            continue
        receipt = decode(ProviderArtifact, frame_metadata[process]['capture_plan'])
        path = Path(receipt.uri)
        if (path != trace_path / f'lean-plan.{process}.json' or path.is_symlink()
                or path.resolve() != path or receipt.size_bytes > 16_000_000
                or input_bytes + receipt.size_bytes > limits.max_input_bytes):
            raise ValueError('observed source plan changed its original artifact namespace')
        with path.open('rb') as stream:
            raw = stream.read(receipt.size_bytes + 1)
        if len(raw) != receipt.size_bytes or sha256(raw).hexdigest() != receipt.sha256:
            raise ValueError('observed source plan changed its original bytes')
        input_bytes += len(raw)
        plan = LeanCapturePlan.from_dict(loads(raw), max_codes=trace.frame_budget.max_codes)
        if plan.namespace_root != trace.project_root:
            raise ValueError('source demand plan changed its original namespace policy')
        plan_receipts[process] = receipt
        for body in plan.bodies:
            snapshots[process, body.source.path] = body.source

    sources, demands = [], []
    attempted = charged = retained = 0
    for filename, captures in sorted(groups.items()):
        check()
        path = Path(filename)
        candidates = [capture for capture in captures
            if capture.process_id in metadata
            and metadata[capture.process_id].implementation == sys.implementation.name
            and metadata[capture.process_id].python == sys.version
            and (capture.process_id, filename) in snapshots]
        if not candidates:
            issue('CAPTURE_SOURCE_VERSION_UNRECORDED', filename,
                'No supported original whole-file snapshot and matching compiler profile; current source is not promoted to capture-time material.')
            continue
        try:
            available = (path.is_absolute() and path.resolve() == path
                and _has_symlink_component(path) is None and path.suffix == '.py' and path.is_file())
            required = path.stat().st_size if available else None
        except (OSError, ValueError, RuntimeError):
            available, required = False, None
        if not available:
            issue('CAPTURE_SOURCE_FILE_UNAVAILABLE', filename,
                'The captured filename does not locate a canonical regular Python source file.')
            continue
        if attempted >= max_source_files:
            issue('OBSERVED_SOURCE_FILE_BUDGET', filename, 'The source-read file budget was reached.')
            continue
        if required > max_source_bytes - charged or input_bytes + required > limits.max_input_bytes:
            issue('OBSERVED_SOURCE_BYTE_BUDGET', filename, 'The file exceeds the remaining source-read byte budget.')
            continue
        attempted += 1
        charged += required
        input_bytes += required
        try:
            raw, text, encoding = _read_source(path, required)
            raw_sha, decoded_sha = sha256(raw).hexdigest(), sha256(text.encode()).hexdigest()
            matched_versions = [capture for capture in candidates
                if snapshots[capture.process_id, filename].fingerprint == 'sha256:' + decoded_sha]
            if not matched_versions:
                issue('CAPTURE_SOURCE_VERSION_CHANGED', filename,
                    'Current decoded source differs from every supported original whole-file snapshot.')
                continue
            compiled = compile(text, filename, 'exec', flags=0, dont_inherit=True, optimize=0)
            pending, codes = [((), compiled)], []
            while pending:
                compiler_path, code = pending.pop()
                codes.append((compiler_path, code))
                pending.extend(((*compiler_path, index), value) for index, value in enumerate(code.co_consts)
                    if type(value) is CodeType)
            proofs = []
            for capture in matched_versions:
                check()
                matches = [(compiler_path, code) for compiler_path, code in codes
                    if describe_code(code) == encode(capture.code)]
                if len(matches) != 1:
                    issue('CAPTURE_SOURCE_COMPILER_CODE_NOT_UNIQUE', filename,
                        'Complete captured/compiler descriptors have no unique original co_consts path.',
                        code=capture.code.key, candidate_count=len(matches))
                    continue
                compiler_path, _ = matches[0]
                proofs.append({'capture': encode(capture), 'source_snapshot': encode(snapshots[capture.process_id, filename]),
                    'plan': encode(plan_receipts[capture.process_id]), 'compiler_path': list(compiler_path),
                    'root_code_layout_key': code_key(compiled), 'implementation': sys.implementation.name,
                    'python': sys.version, 'cache_tag': sys.implementation.cache_tag})
            if not proofs:
                continue
            source = StaticSourceFile(filename, str(path.parent), (), text, raw_sha,
                decoded_sha, encoding, len(raw), ())
            sources.append(source)
            retained += len(raw)
            demands.append({'source': source.to_manifest_dict(),
                'source_bytes': encode(ProviderArtifact(filename, raw_sha, len(raw), 'scar.observed-source-bytes')),
                'proofs': proofs, 'import_or_class_origin_established': False})
        except (OSError, UnicodeError, SyntaxError, ValueError, _ByteBudget, _Changed) as error:
            issue('CAPTURE_SOURCE_MATERIAL_OPEN', filename, type(error).__name__ + ': ' + str(error))
    if _inputs(trace_path) != trace_before:
        raise ValueError('original trace/plan membership or bytes changed during source demands')
    if _stamp(manifest_path) != before_model:
        raise ValueError('original source model changed before material publication')
    provenance = {'schema': 'scar.observed-source-demands', 'schema_version': 1,
        'prior_model_manifest': encode(ProviderArtifact(str(manifest_path), prior, len(original), 'scar.static-program')),
        'trace': trace.directory, 'run_scope': observed.source_sha256,
        'capture_files': encode((*trace.frame_scan.files, *trace.files)),
        'plans': encode(tuple(plan_receipts.values())), 'demands': demands,
        'namespace_policy': 'INDEPENDENT_FILE_PARENT_WITHOUT_IMPORT_MAPPING',
        'target_executed': False, 'import_or_class_origin_established': False}
    out.mkdir(parents=True, exist_ok=True)
    with (out / 'plan.json').open('xb') as stream:
        stream.write(_json({**provenance, 'issues': issues, 'readers_closed_before_publication': True}))
    # Readers above are eager and all files were opened through context
    # managers. Only this existing owner may now mutate the static model.
    old_keys = {unit['key'] for unit in manifest['units']}
    if sources:
        from scar.analysis.static_dependency_publication import append_static_source_units
        updated = append_static_source_units(model, tuple(sources), provenance=provenance,
            jobs=1, max_bytes=max_source_bytes, expected_manifest_sha256=prior)
    else:
        updated = manifest
    if _inputs(trace_path) != trace_before:
        raise ValueError('original trace changed while the closed-reader source publication was in progress')
    added = [unit for unit in updated['units'] if unit['key'] not in old_keys]
    published = sha256(manifest_path.read_bytes()).hexdigest()
    report = {'schema': 'scar.observed-source-expansion', 'schema_version': 1,
        'model': str(model), 'trace': trace.directory, 'run_scope': observed.source_sha256,
        'prior_manifest_sha256': prior, 'published_manifest_sha256': published,
        'added_files': [unit['path'] for unit in added], 'added_unit_keys': [unit['key'] for unit in added],
        'added_source_count': len(added), 'source_file_read_attempts': attempted,
        'charged_source_bytes': charged, 'retained_source_bytes': retained,
        'max_source_files': max_source_files, 'max_source_bytes': max_source_bytes,
        'issues': issues, 'plan': str(out / 'plan.json'), 'readers_closed_before_publication': True,
        'fresh_bindings_and_protocols_required': bool(added), 'target_executed': False,
        'whole_program_complete': False, 'analyzer_seconds': time.monotonic() - started}
    with (out / 'result.json').open('xb') as stream:
        stream.write(_json(report))
    return report


__all__ = ['expand_observed_sources']
