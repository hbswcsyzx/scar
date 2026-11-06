"""Compile explicit dependency source materials into an independent fact store.

The original model supplies immutable material candidates only. All frontend
publication, replay and template linking use the newly owned model; no target
module is imported and no runtime import choice is established.
"""
from __future__ import annotations

import argparse
from collections import Counter
import gzip
from hashlib import sha256
import json
import os
import shutil
from pathlib import Path
import time

from scar.analysis.source_stage import _durable_bytes, _durable_mkdir
from scar.analysis.static_program import _artifacts, _json, read_static_program


_MAX_SOURCE_BYTES = 8 * 1024 * 1024


def _receipt(root, path):
    raw = path.read_bytes()
    return dict(path=path.relative_to(root).as_posix(), bytes=len(raw),
                sha256=sha256(raw).hexdigest())


def _manifest(units):
    """Wrap normal expansion units without copying any parent graph records."""
    units = sorted(units, key=lambda u: (u['namespace_root'], u['path'], u['key']))
    roots = sorted({unit['namespace_root'] for unit in units})
    counts = Counter()
    for unit in units:
        counts.update(unit['counts'])
    value = dict(schema='scar.static-program', schema_version=1, phase='graph',
        project_root=os.path.commonpath(roots), source_roots=roots, artifacts={}, units=units,
        source_input_scope='EXPLICIT_DEPENDENCY_MATERIALS',
        target_executed=False, runtime_evidence_required=False,
        source_issues=[], remaining=[], worker_errors=[], source_changed=[],
        summary=dict(files=len(units), processed_files=len(units),
            source_bytes=sum(unit['source_bytes'] for unit in units), **dict(counts),
            statuses=dict(Counter(unit['status'] for unit in units)),
            body_statuses=dict(Counter(body['status'] for unit in units for body in unit['bodies'])),
            issues_by_stage=dict(Counter(issue['stage'] for unit in units for issue in unit['issues']))),
        completion=dict(selected_materials_complete=True, source_scan_complete=False,
            dependency_closure_complete=False, whole_program_model_complete=False,
            reason='Only explicitly selected dependency material interpretations were compiled; no directory scan or runtime import choice was made.'))
    owned = {descriptor['path']: descriptor for descriptor in _artifacts(value)}
    value['storage'] = dict(files=len(owned), compressed_bytes=sum(d['bytes'] for d in owned.values()))
    return value


def build_dependency_frontend(model, material_indices, out, *, jobs=1, explicit_seed=False):
    """Compile selected physical source files through the existing F0--F5 APIs.

    Four or fewer selected files run in this process. Larger batches retain
    the caller's bounded process-worker setting. The fixed raw-byte ceiling
    is enforced by the original dependency expander before frontend admission.
    A failed gate retains its real reports and stops without synthesizing data.
    """
    from scar.analysis.static_dependencies import read_static_dependencies
    from scar.analysis.static_dependency_expansion import expand_static_dependency_materials
    from scar.analysis.source_materials import archive_model_source_bytes, verify_model_source_bytes
    from scar.analysis.source_lexing import model_source_tokens
    from scar.analysis.source_parsing import model_source_syntax
    from scar.analysis.source_symbol_materials import model_source_symbols
    from scar.analysis.source_role_materials import model_source_roles
    from scar.analysis.source_context_materials import model_source_contexts
    from scar.analysis.source_declaration_materials import model_source_declarations
    from scar.analysis.source_binding_materials import model_source_bindings
    from scar.analysis.compiler_topology_materials import model_compiler_topology
    from scar.analysis.compiler_symbol_materials import model_compiler_symbols
    from scar.analysis.frontend_check import check_frontend
    from scar.analysis.source_expression_materials import collect_source_rules
    from scar.analysis.source_template_links import link_source_templates, verify_template_store
    from scar.analysis.normal_links import extract_facts
    from scar.ir.program.static_dependencies import DependencyMaterialKind

    started = time.monotonic()
    model, out = Path(model).absolute(), Path(out).absolute()
    indices = tuple(material_indices)
    if (type(jobs) is not int or not 1 <= jobs <= 32 or type(explicit_seed) is not bool
            or (not indices and not explicit_seed) or (indices and explicit_seed)
            or any(type(index) is not int or index < 0 for index in indices)
            or len(set(indices)) != len(indices)):
        raise ValueError('dependency frontend needs unique material indices and jobs in [1,32]')
    if (model.resolve() != model or out.resolve() != out or out.exists()
            or out.is_relative_to(model) or model.is_relative_to(out)):
        raise ValueError('dependency frontend requires a canonical model and a fresh independent output')
    original = (model / 'manifest.json').read_bytes()
    parent = read_static_program(model, verify=False)
    if json.loads(original) != parent:
        raise ValueError('original model changed before dependency admission')
    inventory = None if explicit_seed else read_static_dependencies(model)
    if explicit_seed and (parent.get('source_input_scope') not in
            ('EXPLICIT_SINGLE_SOURCE_FILE','EXPLICIT_SOURCE_FILES')
            or parent.get('phase')!='sources' or not parent['units']):
        raise ValueError('explicit frontend input must be a source-only seed')
    if inventory is not None and any(index >= len(inventory.materials) for index in indices):
        raise ValueError('material index lies outside the original dependency inventory')
    for index in indices:
        material = inventory.materials[index]
        if (material.kind is not DependencyMaterialKind.SOURCE or material.supplied_unit is not None
                or material.artifact is None or Path(material.path).suffix != '.py'):
            raise ValueError('material ' + str(index) + ' is not an external fingerprinted runtime source candidate')

    implementation = sha256(Path(__file__).read_bytes()).hexdigest()
    source_count = len(parent['units']) if explicit_seed else len(indices)
    effective_jobs = 1 if source_count <= 4 else jobs
    own_model = out / 'model'
    stages = []
    current = 'dependency-expansion'

    def unchanged():
        if (model / 'manifest.json').read_bytes() != original:
            raise ValueError('original model manifest changed during dependency frontend')
        if sha256(Path(__file__).read_bytes()).hexdigest() != implementation:
            raise ValueError('dependency frontend implementation changed')

    def seal(name, directory, report, *, complete=False, status=None):
        nonlocal current
        current = name
        unchanged()
        receipt = _receipt(out, directory / 'result.json')
        stages.append(dict(stage=name, report=receipt, seconds=report.get('seconds')))
        if complete and report.get('complete_for_declared_units') is not True:
            raise ValueError(name + ' did not accept all declared source units')
        if status is not None and report.get('status') != status:
            raise ValueError(name + ' stopped at ' + str(report.get('status')))
        return report

    def run(name, directory, producer, **options):
        nonlocal current
        current = name
        unchanged()
        return seal(name, directory, producer(own_model, directory, jobs=effective_jobs, **options), complete=True)

    unchanged()
    _durable_mkdir(out)
    basis = dict(model=str(model), model_manifest_sha256=sha256(original).hexdigest(),
        dependency_inventory=None if explicit_seed else parent['artifacts']['dependencies'],
        source_input_scope=parent['source_input_scope'] if explicit_seed else 'EXPLICIT_DEPENDENCY_MATERIALS',
        material_indices=indices, jobs=jobs, effective_jobs=effective_jobs,
        max_source_bytes=_MAX_SOURCE_BYTES, implementation_sha256=implementation)
    _durable_bytes(out / 'inputs.json', _json(basis), replace=False)
    try:
        if explicit_seed:
            current='explicit-source-seed'
            # The small, owned source-only seed is the new frontend input.
            # The original source path and version stay in its unit records.
            read_static_program(model)
            shutil.copytree(model,own_model)
        else:
            expansion = expand_static_dependency_materials(inventory, out=own_model,
                material_indices=indices, max_files=len(indices), max_bytes=_MAX_SOURCE_BYTES,
                jobs=effective_jobs, existing_units=())
            expansion_out = out / 'expansion'
            _durable_mkdir(expansion_out)
            _durable_bytes(expansion_out / 'result.json', _json(expansion.to_dict()), replace=False)
            seal(current, expansion_out, expansion.to_dict())
            if expansion.frontiers or not expansion.units:
                raise ValueError('dependency-expansion did not accept the selected materials: ' +
                    ', '.join(sorted({frontier.kind for frontier in expansion.frontiers})))
            _durable_bytes(own_model / 'manifest.json', _json(_manifest(expansion.units)), replace=False)
        read_static_program(own_model)

        current = 'f0-capture'
        seal(current, out / 'f0' / 'capture', archive_model_source_bytes(own_model,
            out / 'f0' / 'capture', jobs=effective_jobs, max_bytes=_MAX_SOURCE_BYTES), complete=True)
        current = 'f0-fresh'
        seal(current, out / 'f0' / 'fresh', verify_model_source_bytes(own_model,
            out / 'f0' / 'fresh'), complete=True)
        for label, producer in (('f1', model_source_tokens), ('f2', model_source_syntax)):
            report = run(label + '-capture', out / label / 'capture', producer)
            if label == 'f2' and report.get('all_declared_units_parsed') is not True:
                raise ValueError('f2-capture did not parse all declared source units')
            run(label + '-fresh', out / label / 'fresh', producer, verify=True)
        for label, producer in (
                ('source-symbols', model_source_symbols), ('source-roles', model_source_roles),
                ('source-contexts', model_source_contexts), ('source-declarations', model_source_declarations),
                ('source-bindings', model_source_bindings), ('compiler-topology', model_compiler_topology),
                ('compiler-symbols', model_compiler_symbols)):
            run('f3-' + label + '-capture', out / 'f3' / label / 'capture', producer)
            run('f3-' + label + '-fresh', out / 'f3' / label / 'fresh', producer, verify=True)
        run('frontend-check', out / 'f3' / 'frontend-check', check_frontend)
        final_manifest = (own_model / 'manifest.json').read_bytes()
        read_static_program(own_model)

        parents = []
        for domain in ('expressions', 'statements', 'roots'):
            materials, fresh = out / domain / 'materials', out / domain / 'fresh'
            for directory, previous, mode in ((materials, None, 'materials'), (fresh, materials, 'fresh')):
                current = domain + '-' + mode
                unchanged()
                report = collect_source_rules(own_model, directory, domain=domain,
                    materials=previous, jobs=effective_jobs)
                seal(current, directory, report, status='LOCAL_RULES_VERIFIED')
            parents.append((domain, str(materials), str(fresh)))
        current = 'templates'
        seal(current, out / 'templates', link_source_templates(own_model, out / 'templates',
            parents, jobs=effective_jobs), status='SOURCE_INTERFACES_LINKED')
        current = 'templates-fresh'
        checked = verify_template_store(out / 'templates', jobs=effective_jobs)
        _durable_mkdir(out / 'templates-fresh')
        _durable_bytes(out / 'templates-fresh' / 'result.json', _json(checked), replace=False)
        seal(current, out / 'templates-fresh', checked, status='STORED_INTERFACES_VERIFIED')
        current = 'facts'
        facts = extract_facts(own_model, out / 'templates', out / 'facts', jobs=effective_jobs)
        seal(current, out / 'facts', facts, status='SOURCE_LINK_FACTS_EXTRACTED')
        if facts.get('schema_version') != 6:
            raise ValueError('scope-qualified schema6 source facts required')
        if (own_model / 'manifest.json').read_bytes() != final_manifest:
            raise ValueError('independent model changed during template/fact generation')
        units = []
        for row in facts['units']:
            document = json.loads(gzip.decompress((out / 'facts' / row['facts']).read_bytes()))
            units.append(dict(unit=row['unit'], path=row['path'], module=row['module'],
                root_scope=document['root_scope'], counts=row['counts']))
        unchanged()
        result = dict(schema='scar.source-dependency-frontend', schema_version=1,
            status='DEPENDENCY_SOURCE_FACTS_COMPILED', **basis, stages=stages,
            independent_model=str(own_model), independent_model_manifest_sha256=sha256(final_manifest).hexdigest(),
            facts=str(out / 'facts'), facts_result_sha256=sha256((out / 'facts' / 'result.json').read_bytes()).hexdigest(),
            units=units, source_units=len(units), counts=facts['counts'],
            original_model_unchanged=True, target_executed=False, import_choice_established=False,
            dependency_closure_complete=False, first_stage_complete=False,
            seconds=time.monotonic() - started)
        _durable_bytes(out / 'result.json', _json(result), replace=False)
        return result
    except Exception as error:
        result = dict(schema='scar.source-dependency-frontend', schema_version=1,
            status='DEPENDENCY_FRONTEND_STOPPED', **basis, stopped_stage=current, stages=stages,
            error=dict(type=type(error).__name__, detail=str(error)),
            original_model_unchanged=(model / 'manifest.json').read_bytes() == original,
            target_executed=False, first_stage_complete=False, seconds=time.monotonic() - started)
        _durable_bytes(out / 'result.json', _json(result), replace=False)
        raise


def main(argv=None):
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument('--model', required=True)
    parser.add_argument('--material-index', action='append', type=int, default=[])
    parser.add_argument('--explicit-seed',action='store_true',help='compile a fresh single-file source-only seed')
    parser.add_argument('--out', required=True)
    parser.add_argument('--jobs', type=int, default=1)
    args = parser.parse_args(argv)
    report = build_dependency_frontend(args.model, args.material_index, args.out, jobs=args.jobs,explicit_seed=args.explicit_seed)
    print(_json({key: report[key] for key in
        ('status', 'facts', 'source_units', 'original_model_unchanged', 'seconds')}).decode().strip())
    return 0


if __name__ == '__main__':
    raise SystemExit(main())


__all__ = ['build_dependency_frontend', 'main']
