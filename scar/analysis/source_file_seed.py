"""Seed one explicit source file for later formal frontend stages.

No directory inventory, import resolution, or target execution occurs here.
The existing source/lexical builder supplies the sole unit; its navigation
catalog does not grant authority to any formal F0--F4 material reader.
"""
from __future__ import annotations

from collections import Counter
from hashlib import sha256
from pathlib import Path
import json
import shutil
import sys
import tempfile
import time

from scar.analysis.static_program import _build_file, _json, read_static_program
from scar.analysis.static_sources import (
    _absolute, _has_symlink_component, _read_source, _root_state,
)
from scar.ir.program.discovery import ModuleMapping
from scar.ir.program.static_sources import StaticSourceFile


def _producer():
    package = Path(__file__).resolve().parents[1]
    names = (
        'analysis/source_file_seed.py', 'analysis/static_program.py',
        'analysis/static_sources.py', 'analysis/static_lexical.py',
        'ir/frontend_v2.py', 'ir/record_codec.py',
        'ir/program/static_sources.py', 'ir/program/discovery.py',
    )
    files = {name: sha256((package / name).read_bytes()).hexdigest() for name in names}
    return dict(api='scar.analysis.source_file_seed.seed_source_file',
        profile='EXPLICIT_SINGLE_FILE_SOURCE_LEXICAL_SEED_V1',
        source_files=files, source_sha256=sha256(_json(files)).hexdigest(),
        python=sys.version, executable=sys.executable,
        authority='SOURCE_LEXICAL_SEED_ONLY_NOT_FORMAL_FRONTEND_STAGE')


def _fresh_output(output, source, namespace):
    if _has_symlink_component(output) is not None or output.resolve() != output:
        raise ValueError('seed output must not traverse a symbolic link')
    if output.exists():
        raise FileExistsError('seed output must be fresh: ' + str(output))
    if source.is_relative_to(output) or namespace.is_relative_to(output):
        raise ValueError('seed output must not contain the original source namespace')
    # A fresh child of a frozen model would still change that model's exact
    # owned-file set, even though no former file was overwritten.
    for parent in output.parents:
        manifest = parent / 'manifest.json'
        if manifest.is_file():
            try:
                schema = json.loads(manifest.read_bytes()).get('schema')
            except (ValueError, AttributeError):
                continue
            if schema == 'scar.static-program':
                raise ValueError('seed output must be outside existing static models')


def seed_source_file(path, namespace_root, out, module=None):
    """Publish a fresh SOURCE_ONLY model and return its manifest dictionary.

    ``module`` supplies an optional namespace candidate, never an import
    selection or a module object. Source paths retain their actual locations.
    The output is independent of all existing models and can subsequently be
    consumed by the ordinary F0--F4 owned-material pipeline.
    """
    started = time.monotonic()
    source_path, namespace, output = map(_absolute, (path, namespace_root, out))
    if _has_symlink_component(source_path) is not None:
        raise ValueError('source path must not traverse a symbolic link')
    state, detail = _root_state(namespace)
    if state != 'ok':
        raise ValueError('invalid source namespace: ' + detail)
    if not source_path.is_relative_to(namespace):
        raise ValueError('source namespace must contain the explicit source file')
    if source_path.suffix not in ('.py', '.pyi'):
        raise ValueError('an explicit Python source or stub file is required')
    _fresh_output(output, source_path, namespace)
    mappings = () if module is None else (ModuleMapping(module, str(namespace)),)
    modules = () if module is None else (module,)
    producer = _producer()
    # The original reader bounds the read by this exact observed file size,
    # checks path/fd stamps, and detects encoding without executing the file.
    byte_limit = source_path.lstat().st_size
    raw, text, encoding = _read_source(source_path, byte_limit)
    source = StaticSourceFile(str(source_path), str(namespace), modules, text,
        sha256(raw).hexdigest(), sha256(text.encode('utf-8')).hexdigest(),
        encoding, len(raw), mappings)

    output.parent.mkdir(parents=True, exist_ok=True)
    temporary = Path(tempfile.mkdtemp(prefix='.source-file-seed-', dir=output.parent))
    reserved = False
    try:
        unit = _build_file(source, str(temporary), phase='sources', max_body_operations=10000)
        result = dict(schema='scar.static-program', schema_version=1, phase='sources',
            project_root=str(namespace), source_roots=[str(namespace)],
            source_input_scope='EXPLICIT_SINGLE_SOURCE_FILE',
            target_executed=False, runtime_evidence_required=False,
            import_choice_established=False, source_catalog_status='COMPLETE',
            source_issues=[], remaining=[], worker_errors=[], source_changed=[],
            artifacts={}, units=[unit],
            source_file_seed=dict(
                inputs=dict(path=str(source_path), namespace_root=str(namespace), module=module),
                source_version=source.to_manifest_dict(), producer=producer,
                module_mapping_semantics='DECLARED_NAMESPACE_CANDIDATE_NOT_IMPORT_SELECTION',
                builder=dict(phase='sources', max_body_operations=10000),
                formal_stages={stage: 'NOT_ATTEMPTED' for stage in ('F0', 'F1', 'F2', 'F3', 'F4')}),
            summary=dict(files=1, processed_files=1, source_bytes=source.size_bytes,
                **unit['counts'], statuses={unit['status']: 1},
                body_statuses=dict(Counter(body['status'] for body in unit['bodies'])),
                issues_by_stage=dict(Counter(issue['stage'] for issue in unit['issues']))),
            completion=dict(selected_materials_complete=True, source_scan_complete=False,
                dependency_closure_complete=False, first_stage_complete=False,
                whole_program_model_complete=False,
                reason='Only the explicit file source/lexical seed was built; formal frontend stages, directory discovery, and import selection remain unperformed.'),
            storage=dict(files=len(unit['artifacts']),
                compressed_bytes=sum(d['bytes'] for d in unit['artifacts'].values())),
            analyzer_seconds=time.monotonic() - started)
        (temporary / 'manifest.json').write_bytes(_json(result))
        read_static_program(temporary)
        if _producer() != producer:
            raise ValueError('seed producer changed during construction')
        if _read_source(source_path, byte_limit)[0] != raw:
            raise ValueError('original source version changed during seed construction')
        _fresh_output(output, source_path, namespace)
        # Reserve the name without replacing even an empty pre-existing output.
        output.mkdir()
        reserved = True
        temporary.rename(output)
        reserved = False
        return result
    finally:
        if temporary.exists():
            shutil.rmtree(temporary)
        if reserved:
            try:
                output.rmdir()
            except OSError:
                pass


__all__ = ['seed_source_file']
