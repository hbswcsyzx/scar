"""C2b source namespace-template stores over the existing declaration ledger."""
from __future__ import annotations

import argparse
from collections import Counter
from concurrent.futures import ProcessPoolExecutor
from hashlib import sha256
import math
import multiprocessing
import re
import time

from scar.analysis import source_declaration_materials as _d
from scar.analysis.source_materials import _stamps
from scar.analysis.source_stage import SourceStage
from scar.analysis.source_store import (
    REQUIRED_SOURCE_ARTIFACTS, source_input_basis, read_source_prerequisites, check_replay_limit,
    read_material_manifest, pin_material_store, check_material_store, material_store_members,
)
from scar.analysis.static_program import _json, _write
from scar.analysis.static_query import _Fragments


_ARTIFACT = 'source_bindings'
_CATALOG = _ARTIFACT + '/catalog.json.gz'
_OWN_DEFAULTS = dict(max_bindings=1_000_000, max_interfaces=1_000_000, max_plans=1_000_000,
    max_plan_steps=4_000_000, max_captures=2_000_000, max_relays=2_000_000,
    max_search_steps=10_000_000, max_conflicts=100_000)
_DEFAULTS = {**_d._DEFAULTS, **_OWN_DEFAULTS}
_TABLES = ('ports', 'scopes', 'bindings', 'interfaces', 'plans', 'resolutions', 'captures',
    'relays', 'root_globals', 'implicit', 'conflicts')
_TOTALS = (*_TABLES, 'steps', 'search_steps')
_FLAGS = dict(authority='SOURCE_NAMESPACE_TEMPLATES', runtime_binding='NOT_OBSERVED',
    compiler_projection='NOT_COMPUTED_IN_C2B')


class _DeclarationPolicy:
    """Bridge the C2a row summary, which has no per-rule counter array."""
    _catalog_at = staticmethod(_d._catalog_at)
    _inventory = staticmethod(_d._inventory)

    @staticmethod
    def _check_summary(document, rows, counts, digest):
        _d._check_summary(document, rows, digest)

    @staticmethod
    def _report(rows, counts, *, schema, limits, jobs, catalog_sha):
        return _d._report(rows, schema=schema, limits=limits, jobs=jobs, digest=catalog_sha)


def _declaration_input(stage, directory, basis, catalog):
    """C2a owns scalar table totals; B/C1 use their existing rule-counter loader."""
    if directory is None:
        return _d._input(stage, 'source_declarations', None, basis, catalog, _DeclarationPolicy)
    root, stored, raw = read_material_manifest(directory, stage.out)
    _d._check_summary(stored, stored['results'], catalog['content_sha256'])
    if _json(stored.get('basis')) != _json(basis):
        raise ValueError('C2a source/role/context basis differs from selected prerequisites')
    descriptors = [row['artifact'] for row in stored['results']]
    if len(descriptors) != len(basis) or any(row['unit'] != unit['key']
            or row['artifact']['path'] != 'units/' + unit['key'] + '/source_declarations.json.gz'
            for row, unit in zip(stored['results'], basis)):
        raise ValueError('C2a original unit/path order differs from the model')
    descriptor = stored['catalog']
    pins = pin_material_store(root, [descriptor, *descriptors], raw)
    _d._catalog_at(root, descriptor, catalog)
    return dict(root=root, stored=stored, raw=raw, pins=pins, catalog=descriptor,
        catalog_pins=_stamps(root, (descriptor,)), descriptors=descriptors,
        policy=_DeclarationPolicy, catalog_sha=catalog['content_sha256'], artifact='source_declarations')


def _upstream_rows(unit, f1, f2, roles, contexts, declarations, descriptors):
    common = dict(unit=unit['key'], upstream_f1_status=f1['status'], upstream_f2_status=f2['status'])
    b = dict(common, artifact=descriptors[0], status=roles['status'], slots=roles['slots'],
        ports=len(roles['ports']), list_items=roles['list_items'], max_ports=roles['max_ports'],
        max_slots=roles['max_slots'], frontiers=roles['frontiers'])
    c = dict(common, artifact=descriptors[1], status=contexts['status'],
        **{key: len(contexts[key]) for key in ('scopes', 'regions', 'private_contexts', 'boundaries')},
        ports=len(roles['ports']) if contexts['status'] == 'CONTEXTUALIZED' else 0, slots=contexts['slots'],
        **{key: contexts[key] for key in _d._c1._OWN_LIMITS}, frontiers=contexts['frontiers'], upstream_f3b_status=roles['status'])
    d = dict(common, artifact=descriptors[2], status=declarations['status'],
        **{key: len(declarations[key]) for key in _d._TOTALS},
        **{key: declarations[key] for key in _d._OWN_LIMITS}, frontiers=declarations['frontiers'],
        upstream_f3b_status=roles['status'], upstream_c1_status=contexts['status'])
    return b, c, d


def _binding_unit(task):
    from scar.analysis.source_bindings import source_bindings_document, read_source_bindings
    model, destination, unit, inputs, prior_root, prior, limits, digest, independent = task
    f0, f1, f2 = read_source_prerequisites(_Fragments(model), unit, limits['max_nodes'], limits['max_tokens'])
    roles, contexts, declarations = [_Fragments(root).read(descriptor) for root, descriptor in inputs]
    for doc, keys, label in ((roles, ('max_ports', 'max_slots'), 'F3-B'),
            (contexts, _d._c1._OWN_LIMITS, 'F3-C1'), (declarations, _d._OWN_LIMITS, 'F3-C2a')):
        for key in keys:check_replay_limit(doc, key, limits[key], label)
    if prior is not None:
        document = _Fragments(prior_root).read(prior)
        for key in _OWN_DEFAULTS:check_replay_limit(document, key, limits[key], 'F3-C2b')
        read_source_bindings(document, f0, f1, f2, roles, contexts, declarations)
        descriptor = prior
    elif destination is None:
        raise ValueError('C2b binding artifact is absent')
    else:
        document = source_bindings_document(f0, f1, f2, roles, contexts, declarations,
            **{key: limits[key] for key in _OWN_DEFAULTS})
        descriptor = None
    if document['profile']['binding_catalog_sha256'] != digest:
        raise ValueError('C2b worker binding catalog differs from its parent')
    if destination is not None and (independent or descriptor is None):
        relative = 'units/' + unit['key'] + '/source_bindings.json.gz'
        if (destination / relative).exists():
            raise FileExistsError('new C2b artifact collides with an existing file')
        descriptor = _write(destination, relative, document)
    row = dict(unit=unit['key'], artifact=descriptor, status=document['status'],
        **{key: len(document[key]) for key in _TABLES},
        steps=sum(len(plan['steps']) for plan in document['plans']), search_steps=document['search_steps'],
        **{key: document[key] for key in _OWN_DEFAULTS}, frontiers=document['frontiers'],
        upstream_f1_status=f1['status'], upstream_f2_status=f2['status'], upstream_f3b_status=roles['status'],
        upstream_c1_status=contexts['status'], upstream_c2a_status=declarations['status'])
    b, c, d = _upstream_rows(unit, f1, f2, roles, contexts, declarations, [item[1] for item in inputs])
    return row, b, roles['counts'], c, contexts['counts'], d


def _report(rows, *, schema, limits, jobs, digest):
    covered = [row['status'] != 'BUDGET_STOPPED' and row['upstream_f1_status'] != 'BUDGET_STOPPED'
        and row['upstream_f2_status'] not in ('BUDGET_STOPPED', 'PARSER_RESOURCE_ERROR')
        and all(row[key] != 'BUDGET_STOPPED' for key in ('upstream_f3b_status', 'upstream_c1_status', 'upstream_c2a_status'))
        for row in rows]
    return dict(schema=schema, schema_version=1, stage='F3-C2b', input_scope='DECLARED_MODEL_SOURCE_UNITS',
        units=len(rows), covered_units=sum(covered), complete_for_declared_units=all(covered),
        all_declared_units_resolved=all(row['status'] in ('RESOLVED', 'RESOLVED_WITH_CONFLICTS') for row in rows),
        status_counts=dict(Counter(row['status'] for row in rows)), results=rows,
        **{key: sum(row[key] for row in rows) for key in _TOTALS}, limits=limits, jobs=jobs,
        catalog_sha256=digest, symtable_executed=False, target_executed=False,
        later_stages_verified=False, whole_program_complete=False, **_FLAGS)


def _check_summary(document, rows, digest):
    limits, jobs = document.get('limits'), document.get('jobs')
    if (type(limits) is not dict or set(limits) != set(_DEFAULTS)
            or any(type(value) is not int or value < 0 for value in limits.values())
            or type(jobs) is not int or not 1 <= jobs <= 32):
        raise ValueError('invalid C2b material budgets/jobs')
    for row in rows:
        for key in _OWN_DEFAULTS:
            if type(row.get(key)) is not int or not 0 <= row[key] <= limits[key]:
                raise ValueError('C2b row budget exceeds stored limits')
    expected = _report(rows, schema='scar.source-binding-materials', limits=limits, jobs=jobs, digest=digest)
    if (_json({key: document.get(key) for key in expected}) != _json(expected)
            or document.get('collect_only') is not True or document.get('canonical_model_published') is not False
            or document.get('manifest_unchanged') is not True):
        raise ValueError('C2b material summary differs from freshly verified binding rows')
    for key in ('observed_manifest_sha256', 'prior_manifest_sha256', 'published_manifest_sha256'):
        if type(document.get(key)) is not str or re.fullmatch(r'[0-9a-f]{64}', document[key]) is None:
            raise ValueError('invalid observed C2b manifest receipt')
    if 'seconds' in document and (type(document['seconds']) not in (int, float)
            or not math.isfinite(document['seconds']) or document['seconds'] < 0):
        raise ValueError('invalid C2b observed duration')


def _catalog_at(root, descriptor, expected):
    if descriptor.get('path') != _CATALOG or _json(_Fragments(root).read(descriptor)) != _json(expected):
        raise ValueError('C2b catalog receipt/content differs from the binding catalog')


def _inventory(report, catalog):
    keys = ('stage', 'units', *_TOTALS, 'status_counts', 'catalog_sha256', *_FLAGS,
        'later_stages_verified', 'whole_program_complete')
    return dict({key: report[key] for key in keys}, schema='scar.source-binding-inventory', schema_version=1,
        scope='DECLARED_MODEL_SOURCE_UNITS', artifacts=[catalog])


def model_source_bindings(model, out, *, roles_materials=None, contexts_materials=None, declarations_materials=None,
        jobs=4, collect_only=False, verify=False, materials=None, max_nodes=1_000_000, max_tokens=2_000_000,
        max_ports=1_000_000, max_slots=10_000_000, max_scopes=100_000, max_regions=200_000,
        max_boundaries=1_000_000, max_names=1_000_000, max_contributions=1_000_000,
        max_bindings=1_000_000, max_interfaces=1_000_000, max_plans=1_000_000, max_plan_steps=4_000_000,
        max_captures=2_000_000, max_relays=2_000_000, max_search_steps=10_000_000, max_conflicts=100_000):
    from scar.analysis.source_bindings import source_binding_catalog
    from scar.analysis.source_declarations import source_declaration_catalog
    from scar.analysis.source_contexts import source_context_catalog
    from scar.analysis.source_roles import source_role_catalog
    limits = {key: value for key, value in locals().items() if key in _DEFAULTS}
    external = (roles_materials, contexts_materials, declarations_materials)
    if (type(jobs) is not int or not 1 <= jobs <= 32 or type(collect_only) is not bool or type(verify) is not bool
            or collect_only and verify or materials is not None and not verify
            or any(value is not None for value in external) and not (collect_only or verify)
            or any(type(value) is not int or value < 0 for value in limits.values())):
        raise ValueError('C2b requires bounded distinct modes; external prerequisite capture is collect-only')
    started = time.monotonic()
    catalog = source_binding_catalog();digest = catalog['content_sha256']
    with SourceStage(model, out, artifact=_ARTIFACT, verify=verify or collect_only,
            consumes=(*REQUIRED_SOURCE_ARTIFACTS, 'source_roles', 'source_contexts', 'source_declarations', _ARTIFACT)) as stage:
        basis = source_input_basis(stage.manifest['units'])
        b_catalog, c_catalog, d_catalog = source_role_catalog(), source_context_catalog(), source_declaration_catalog()
        b = _d._input(stage, 'source_roles', roles_materials, basis, b_catalog, _d._b)
        basis = _d._with_artifacts(basis, 'source_roles', b['descriptors'])
        c = _d._input(stage, 'source_contexts', contexts_materials, basis, c_catalog, _d._c1)
        basis = _d._with_artifacts(basis, 'source_contexts', c['descriptors'])
        d = _declaration_input(stage, declarations_materials, basis, d_catalog)
        basis = _d._with_artifacts(basis, 'source_declarations', d['descriptors'])
        existing, canonical_catalog = stage.manifest.get(_ARTIFACT), None
        if existing is not None:
            if type(existing.get('artifacts')) is not list or len(existing['artifacts']) != 1:
                raise ValueError('canonical C2b inventory must own one shared catalog')
            canonical_catalog = existing['artifacts'][0];_catalog_at(stage.root, canonical_catalog, catalog)
        canonical_pins = _stamps(stage.root, (canonical_catalog,)) if canonical_catalog else None
        stored = store_root = store_raw = store_pins = None
        if materials is not None:
            store_root, stored, store_raw = read_material_manifest(materials, stage.out)
            _check_summary(stored, stored['results'], digest)
            if _json(stored.get('basis')) != _json(basis) or len(stored['results']) != len(basis):
                raise ValueError('C2b material basis differs from selected source prerequisites')
            if any(row['unit'] != unit['key'] or row['artifact']['path'] != stage.relative(unit)
                    for row, unit in zip(stored['results'], basis)):
                raise ValueError('C2b original unit/path order differs from the model')
            _catalog_at(store_root, stored['catalog'], catalog)
            store_pins = pin_material_store(store_root, [stored['catalog'], *(row['artifact'] for row in stored['results'])], store_raw)
        destination = stage.out if collect_only else stage.staging
        if destination is not None and (collect_only or canonical_catalog is None):
            if (destination / _CATALOG).exists():raise FileExistsError('new C2b catalog collides with an existing file')
            descriptor = _write(destination, _CATALOG, catalog)
        else:
            descriptor = stored['catalog'] if stored else canonical_catalog
            if descriptor is None:raise ValueError('canonical C2b binding catalog is absent')
        replay_limits = {key: min(value, stored['limits'][key]) for key, value in limits.items()} if stored else limits
        tasks = [(stage.root, destination, unit, [(item['root'], item['descriptors'][i]) for item in (b, c, d)],
            store_root or stage.root, stored['results'][i]['artifact'] if stored else stage.manifest['units'][i]['artifacts'].get(_ARTIFACT),
            replay_limits, digest, collect_only) for i, unit in enumerate(basis)]
        rows, b_rows, c_rows, d_rows = [], [], [], []
        b_counts = [dict(rule=rule['rule'], **{key: 0 for key in _d._b._COUNT_FIELDS}) for rule in b_catalog['rules']]
        c_counts = [dict(rule=rule['rule'], **{key: 0 for key in _d._c1._COUNT_FIELDS}) for rule in c_catalog['rules']]
        def accept(packet):
            row, b_row, b_current, c_row, c_current, d_row = packet
            rows.append(row);b_rows.append(b_row);c_rows.append(c_row);d_rows.append(d_row)
            for total, current, fields in ((b_counts, b_current, _d._b._COUNT_FIELDS), (c_counts, c_current, _d._c1._COUNT_FIELDS)):
                if len(total) != len(current):raise ValueError('C2b prerequisite rule denominator is incomplete')
                for left, right in zip(total, current):
                    if left['rule'] != right['rule']:raise ValueError('C2b prerequisite rule order changed')
                    for key in fields:left[key] += right[key]
        if jobs == 1:
            for packet in map(_binding_unit, tasks):accept(packet)
        else:
            with ProcessPoolExecutor(max_workers=jobs, mp_context=multiprocessing.get_context('spawn')) as pool:
                for packet in pool.map(_binding_unit, tasks, chunksize=1):accept(packet)
        for handle, upstream_rows, counts in ((b, b_rows, b_counts), (c, c_rows, c_counts), (d, d_rows, None)):
            _d._check_input(stage, handle, upstream_rows, counts, jobs)
        if stored is not None:
            _check_summary(stored, rows, digest)
            check_material_store(store_root, [stored['catalog'], *(row['artifact'] for row in rows)], store_raw, store_pins)
        report = _report(rows, schema=('scar.source-binding-material-verification' if stored else
            'scar.source-binding-verification' if verify else 'scar.source-binding-materials' if collect_only
            else 'scar.source-binding-gate'), limits=limits, jobs=jobs, digest=digest)
        report.update(catalog=descriptor, collect_only=collect_only, canonical_model_published=False,
            observed_manifest_sha256=sha256(stage.original).hexdigest())
        if collect_only:
            report['basis'] = basis;material_store_members(stage.out, [descriptor, *(row['artifact'] for row in rows)], result=False)
        elif not verify and report['complete_for_declared_units']:
            stage.publish(rows, _inventory(report, descriptor));report['canonical_model_published'] = True
        elif verify and stored is None and _json(existing) != _json(_inventory(report, descriptor)):
            raise ValueError('canonical C2b inventory differs from freshly verified namespace templates')
        if canonical_catalog and _stamps(stage.root, (canonical_catalog,)) != canonical_pins:
            raise ValueError('canonical C2b catalog changed before publication')
        if stored is not None:
            report.update(materials=str(store_root), materials_result_sha256=sha256(store_raw).hexdigest(),
                material_source_basis_unchanged=True)
        report['seconds'] = time.monotonic() - started
        return stage.finish(report)


def main(argv=None):
    parser = argparse.ArgumentParser(prog='scar source-bindings')
    for key in ('model', 'out'):parser.add_argument('--' + key, required=True)
    for key in ('roles-materials', 'contexts-materials', 'declarations-materials', 'materials'):parser.add_argument('--' + key)
    parser.add_argument('--jobs', type=int, default=4)
    parser.add_argument('--collect-only', action='store_true');parser.add_argument('--verify', action='store_true')
    for key, value in _DEFAULTS.items():parser.add_argument('--' + key.replace('_', '-'), type=int, default=value)
    report = model_source_bindings(**vars(parser.parse_args(argv)))
    print(_json({key: report[key] for key in ('stage', 'units', 'bindings', 'plans', 'captures', 'status_counts',
        'complete_for_declared_units', 'canonical_model_published')}).decode().strip())
    return 0 if report['complete_for_declared_units'] else 1


__all__ = ['model_source_bindings', 'main']
