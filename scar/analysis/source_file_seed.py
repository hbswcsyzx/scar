"""Seed explicit source files for later formal frontend stages.

No directory inventory, import resolution, or target execution occurs here.
The existing source/lexical builder supplies each unit; its navigation
catalog does not grant authority to any formal F0--F4 material reader.
"""
from __future__ import annotations

from collections import Counter
from hashlib import sha256
from pathlib import Path
import argparse
import json
import os
import shutil
import sys
import tempfile
import time

from scar.analysis.static_program import _build_file, _json, read_static_program
from scar.analysis.static_sources import (
    _absolute, _has_symlink_component, _read_raw_source, _read_source, _root_state,
)
from scar.ir.program.discovery import ModuleMapping
from scar.ir.program.providers import ProviderArtifact
from scar.ir.program.static_sources import StaticSourceFile


def _producer(api='seed_source_file', profile='EXPLICIT_SINGLE_FILE_SOURCE_LEXICAL_SEED_V1'):
    package = Path(__file__).resolve().parents[1]
    names = (
        'analysis/source_file_seed.py', 'analysis/static_program.py',
        'analysis/static_sources.py', 'analysis/static_lexical.py',
        'ir/frontend_v2.py', 'ir/record_codec.py',
        'ir/program/static_sources.py', 'ir/program/discovery.py',
    )
    files = {name: sha256((package / name).read_bytes()).hexdigest() for name in names}
    return dict(api='scar.analysis.source_file_seed.' + api, profile=profile,
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


def _source_file(path, namespace_root, modules, expected=None):
    source_path, namespace = map(_absolute, (path, namespace_root))
    if _has_symlink_component(source_path) is not None:
        raise ValueError('source path must not traverse a symbolic link')
    state, detail = _root_state(namespace)
    if state != 'ok':
        raise ValueError('invalid source namespace: ' + detail)
    if not source_path.is_relative_to(namespace):
        raise ValueError('source namespace must contain the explicit source file')
    if source_path.suffix not in ('.py', '.pyi'):
        raise ValueError('an explicit Python source or stub file is required')
    mappings = tuple(ModuleMapping(module, str(namespace)) for module in modules)
    # The original reader bounds the read by this exact observed file size,
    # checks path/fd stamps, and detects encoding without executing the file.
    byte_limit = source_path.lstat().st_size if expected is None else expected.size_bytes
    raw, text, encoding = _read_source(source_path, byte_limit)
    if expected is not None and (expected.uri != str(source_path)
            or len(raw) != expected.size_bytes or sha256(raw).hexdigest() != expected.sha256):
        raise ValueError('source file differs from its admission artifact: ' + str(source_path))
    source = StaticSourceFile(str(source_path), str(namespace), modules, text,
        sha256(raw).hexdigest(), sha256(text.encode('utf-8')).hexdigest(),
        encoding, len(raw), mappings)

    return source


def _publish_sources(sources, output, scope, evidence, *, started, producer_args=(), validate=None):
    producer = _producer(*producer_args)
    for source in sources:
        _fresh_output(output, Path(source.path), Path(source.namespace_root))
    output.parent.mkdir(parents=True, exist_ok=True)
    temporary = Path(tempfile.mkdtemp(prefix='.source-file-seed-', dir=output.parent))
    reserved = False
    try:
        units = [_build_file(source, str(temporary), phase='sources', max_body_operations=10000)
            for source in sources]
        units.sort(key=lambda unit: (unit['namespace_root'],unit['path'],unit['key']))
        if len({unit['key'] for unit in units}) != len(units):
            raise ValueError('explicit source interpretations produced duplicate unit identities')
        roots = sorted({source.namespace_root for source in sources})
        counts = Counter()
        for unit in units:counts.update(unit['counts'])
        result = dict(schema='scar.static-program', schema_version=1, phase='sources',
            project_root=os.path.commonpath(roots), source_roots=roots, source_input_scope=scope,
            target_executed=False, runtime_evidence_required=False,
            import_choice_established=False, source_catalog_status='COMPLETE',
            source_issues=[], remaining=[], worker_errors=[], source_changed=[],
            artifacts={}, units=units,
            source_file_seed=dict(**evidence, producer=producer,
                module_mapping_semantics='DECLARED_NAMESPACE_CANDIDATE_NOT_IMPORT_SELECTION',
                builder=dict(phase='sources', max_body_operations=10000),
                formal_stages={stage: 'NOT_ATTEMPTED' for stage in ('F0', 'F1', 'F2', 'F3', 'F4')}),
            summary=dict(files=len(sources), processed_files=len(units),
                source_bytes=sum(source.size_bytes for source in sources), **dict(counts),
                statuses=dict(Counter(unit['status'] for unit in units)),
                body_statuses=dict(Counter(body['status'] for unit in units for body in unit['bodies'])),
                issues_by_stage=dict(Counter(issue['stage'] for unit in units for issue in unit['issues']))),
            completion=dict(selected_materials_complete=True, source_scan_complete=False,
                dependency_closure_complete=False, first_stage_complete=False,
                whole_program_model_complete=False,
                reason='Only explicit source/lexical seeds were built; formal frontend stages, directory discovery, and import selection remain unperformed.'),
            storage=dict(files=sum(len(unit['artifacts']) for unit in units),
                compressed_bytes=sum(d['bytes'] for unit in units for d in unit['artifacts'].values())),
            analyzer_seconds=time.monotonic() - started)
        (temporary / 'manifest.json').write_bytes(_json(result))
        read_static_program(temporary)
        if _producer(*producer_args) != producer:
            raise ValueError('seed producer changed during construction')
        for source in sources:
            raw = _read_source(Path(source.path), source.size_bytes)[0]
            if len(raw) != source.size_bytes or sha256(raw).hexdigest() != source.raw_sha256:
                raise ValueError('original source version changed during seed construction')
            _fresh_output(output, Path(source.path), Path(source.namespace_root))
        if validate is not None:validate()
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


def seed_source_file(path, namespace_root, out, module=None):
    """Publish one fresh SOURCE_ONLY model; module is only a name candidate."""
    started = time.monotonic()
    source_path, namespace, output = map(_absolute, (path, namespace_root, out))
    _fresh_output(output, source_path, namespace)
    source = _source_file(source_path, namespace, () if module is None else (module,))
    return _publish_sources((source,),output,'EXPLICIT_SINGLE_SOURCE_FILE',
        dict(inputs=dict(path=source.path,namespace_root=source.namespace_root,module=module),
            source_version=source.to_manifest_dict()),started=started)


def _admission(plan):
    from scar.analysis.source_symbol_variants import _table

    root = _absolute(plan)
    report_path = root / 'result.json' if root.is_dir() else root
    root = report_path.parent
    if report_path.name != 'result.json' or _has_symlink_component(report_path) is not None:
        raise ValueError('a non-symlink admission result.json or directory is required')
    raw = _read_raw_source(report_path,report_path.stat().st_size)
    report = json.loads(raw)
    implementation = Path(__file__).with_name('source_admission.py')
    table_reader = Path(__file__).with_name('source_symbol_variants.py')
    reader_sha = sha256(table_reader.read_bytes()).hexdigest()
    if ((report.get('schema'),report.get('schema_version'),report.get('status')) !=
            ('scar.source-admission-plan',1,'DEMANDS_LINKED_TO_MATERIALS')
            or report.get('implementation_sha256') != sha256(implementation.read_bytes()).hexdigest()):
        raise ValueError('admission schema or current producer differs')
    descriptors = dict(module_admission=report['module_admission'],
        searched_materials=report['tables']['searched_materials'])
    def tables():
        result = {}
        for name,descriptor in descriptors.items():
            relative = Path(descriptor['path'])
            if relative.is_absolute() or '..' in relative.parts or _has_symlink_component(root/relative) is not None:
                raise ValueError('admission table must remain inside its original directory')
            result[name] = _table(root,descriptor)
        return result
    def validate():
        if (report_path.read_bytes() != raw
                or sha256(implementation.read_bytes()).hexdigest() != report['implementation_sha256']
                or sha256(table_reader.read_bytes()).hexdigest() != reader_sha):
            raise ValueError('admission report or producer changed before source publication')
        tables()
        for reference in report['input_receipts']:
            path = Path(reference['path'])
            if not path.is_absolute() or _has_symlink_component(path) is not None:
                raise ValueError('admission parent must retain its actual non-symlink path')
            parent = _read_raw_source(path,reference['bytes'])
            if len(parent) != reference['bytes'] or sha256(parent).hexdigest() != reference['sha256']:
                raise ValueError('admission input parent differs: ' + str(path))
    values = tables()
    validate()
    evidence = dict(report=dict(path=str(report_path),bytes=len(raw),sha256=sha256(raw).hexdigest()),
        implementation_sha256=report['implementation_sha256'],tables=descriptors,
        input_receipts=report['input_receipts'],pins=report.get('pins',{}),
        table_reader=dict(path=str(table_reader),sha256=reader_sha),
        remaining_plan_obligations_retained_by_reference=True)
    return report,values,evidence,validate


def seed_admission_sources(plan, out, max_files=16):
    """Seed one bounded batch of hashed, actually ready search candidates.

    Material indices remain local to the demand-derived searched-materials
    table. Recorded dependency-inventory references are never ingested here.
    """
    if type(max_files) is not int or max_files < 1:
        raise ValueError('max_files must be a positive exact integer')
    started = time.monotonic()
    report,tables,basis,validate = _admission(plan)
    scope = 'DEMAND_DERIVED_EXPLICIT_ROOT_SEARCH'
    materials = tables['searched_materials']
    candidates = {}
    for row_index,row in enumerate(tables['module_admission']):
        for ordinal,reference in enumerate(row.get('source_ready_candidates',())):
            if reference.get('scope') != scope:continue
            index = reference['material']
            if type(index) is not int or not 0 <= index < len(materials):
                raise ValueError('ready reference lies outside its searched-materials table')
            material = materials[index]
            if material['scope'] != scope or material['module'] != row['module']:
                raise ValueError('ready reference scope or module differs from its search material')
            if material['kind'] != 'SOURCE' or material['version_status'] != 'CONTENT_HASHED':continue
            artifact = ProviderArtifact(**material['artifact'])
            path,root = map(_absolute,(material['path'],material['source_root']))
            if (str(path) != material['path'] or str(root) != material['source_root']
                    or str(root) not in report['search_roots'] or artifact.uri != str(path)):
                raise ValueError('searched source path/root differs from its declared input')
            key = (str(path),material['module'],str(root))
            row_ref = dict(module_admission_row=row_index,source_ready_candidate=ordinal,
                reference=reference)
            if key in candidates and candidates[key]['artifact'] != material['artifact']:
                raise ValueError('one explicit source interpretation has conflicting versions')
            candidate = candidates.setdefault(key,dict(path=str(path),module=material['module'],
                namespace_root=str(root),artifact=material['artifact'],materials=[],ready_references=[]))
            if index not in candidate['materials']:candidate['materials'].append(index)
            candidate['ready_references'].append(row_ref)
    # Preserve every full path/name/root interpretation while sharing the
    # existing unit when the same physical path/root has several name candidates.
    groups = {}
    for key,candidate in sorted(candidates.items()):
        groups.setdefault((key[0],key[2]),[]).append(candidate)
    chosen = list(groups.items())[:max_files]
    if not chosen:raise ValueError('admission has no demand-derived hashed ready source files')
    selected = [candidate for _,group in chosen for candidate in group]
    selected_indices = {i for candidate in selected for i in candidate['materials']}
    ready_indices = {i for candidate in candidates.values() for i in candidate['materials']}
    frontier = [dict(scope=scope,material=i,path=material['path'],module=material['module'],
        kind=material['kind'],version_status=material['version_status'],
        reason='MAX_FILES' if i in ready_indices else 'NOT_A_HASHED_READY_SOURCE')
        for i,material in enumerate(materials) if i not in selected_indices]
    sources = []
    output = _absolute(out)
    for (path,root),group in chosen:
        _fresh_output(output,Path(path),Path(root))
        if any(candidate['artifact'] != group[0]['artifact'] for candidate in group):
            raise ValueError('source namespace candidates disagree about the physical version')
        sources.append(_source_file(path,root,tuple(sorted({c['module'] for c in group})),
            ProviderArtifact(**group[0]['artifact'])))
    return _publish_sources(tuple(sources),output,'EXPLICIT_SOURCE_FILES',
        dict(inputs=[dict(path=c['path'],namespace_root=c['namespace_root'],module=c['module']) for c in selected],
            source_versions=[source.to_manifest_dict() for source in sources],
            admission_plan=basis,selection=dict(scope=scope,max_files=max_files,
                ready_interpretations=len(candidates),ready_source_units=len(groups),
                selected_source_units=len(sources),selected=selected,frontier=frontier)),
        started=started,producer_args=('seed_admission_sources','EXPLICIT_SOURCE_FILES_SEED_V1'),validate=validate)


def main(argv=None):
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument('--admission',required=True)
    parser.add_argument('--out',required=True)
    parser.add_argument('--max-files',type=int,default=16)
    args = parser.parse_args(argv)
    result = seed_admission_sources(args.admission,args.out,args.max_files)
    print(_json(dict(out=str(_absolute(args.out)),source_input_scope=result['source_input_scope'],
        files=result['summary']['files'],source_bytes=result['summary']['source_bytes'])).decode().strip())
    return 0


__all__ = ['seed_source_file','seed_admission_sources']


if __name__ == '__main__':
    raise SystemExit(main())
