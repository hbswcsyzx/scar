"""C2a declaration stores, retaining independently owned B/C1 prerequisites."""
from __future__ import annotations

import argparse
from collections import Counter
from concurrent.futures import ProcessPoolExecutor
from hashlib import sha256
import math
import multiprocessing
import re
import time

from scar.analysis import source_context_materials as _c1, source_role_materials as _b
from scar.analysis.source_materials import _stamps
from scar.analysis.source_stage import SourceStage
from scar.analysis.source_store import (
    REQUIRED_SOURCE_ARTIFACTS, source_input_basis, read_source_prerequisites, check_replay_limit,
    read_material_manifest, pin_material_store, check_material_store, material_store_members,
)
from scar.analysis.static_program import _json, _write
from scar.analysis.static_query import _Fragments


_ARTIFACT = 'source_declarations'
_CATALOG = _ARTIFACT + '/catalog.json.gz'
_OWN_LIMITS = ('max_names', 'max_contributions', 'max_conflicts')
_DEFAULTS = dict(max_nodes=1_000_000, max_tokens=2_000_000, max_ports=1_000_000,
    max_slots=10_000_000, max_scopes=100_000, max_regions=200_000, max_boundaries=1_000_000,
    max_names=1_000_000, max_contributions=1_000_000, max_conflicts=100_000)
_TOTALS = ('names', 'ports', 'contributions', 'scopes', 'conflicts')
_FLAGS = dict(authority='SOURCE_NAME_DECLARATIONS', lookup_resolution='NOT_COMPUTED_IN_C2A')


def _input(stage, artifact, directory, basis, catalog, policy):
    """Pin one of the two concrete prerequisite stores; admission stays in its owner."""
    stored = raw = pins = None
    if directory is not None:
        root, stored, raw = read_material_manifest(directory, stage.out)
        policy._check_summary(stored, stored['results'], stored['rule_counts'], catalog['content_sha256'])
        if _json(stored.get('basis')) != _json(basis):
            raise ValueError(artifact + ' material basis differs from selected prerequisites')
        descriptors = [row['artifact'] for row in stored['results']]
        if len(descriptors) != len(basis) or any(row['unit'] != unit['key']
                or row['artifact']['path'] != 'units/' + unit['key'] + '/' + artifact + '.json.gz'
                for row, unit in zip(stored['results'], basis)):
            raise ValueError(artifact + ' original unit/path order differs from the model')
        descriptor = stored['catalog']
        pins = pin_material_store(root, [descriptor, *descriptors], raw)
    else:
        root, inventory = stage.root, stage.manifest.get(artifact)
        if type(inventory) is not dict or len(inventory.get('artifacts', ())) != 1:
            raise ValueError('C2a requires canonical ' + artifact + ' or its explicit materials store')
        descriptor = inventory['artifacts'][0]
        try:
            descriptors = [unit['artifacts'][artifact] for unit in stage.manifest['units']]
        except KeyError as exc:
            raise ValueError('canonical ' + artifact + ' unit artifact is absent') from exc
    policy._catalog_at(root, descriptor, catalog)
    return dict(root=root, stored=stored, raw=raw, pins=pins, catalog=descriptor,
        catalog_pins=_stamps(root, (descriptor,)), descriptors=descriptors, policy=policy,
        catalog_sha=catalog['content_sha256'], artifact=artifact)


def _check_input(stage, handle, rows, counts, jobs):
    policy = handle['policy']
    if handle['stored'] is not None:
        policy._check_summary(handle['stored'], rows, counts, handle['catalog_sha'])
        check_material_store(handle['root'], [handle['catalog'], *handle['descriptors']], handle['raw'], handle['pins'])
    else:
        report = policy._report(rows, counts, schema='', limits={}, jobs=jobs, catalog_sha=handle['catalog_sha'])
        expected = policy._inventory(report, handle['catalog'])
        if _json(stage.manifest[handle['artifact']]) != _json(expected):
            raise ValueError('canonical prerequisite inventory differs from freshly verified input rows')
    if _stamps(handle['root'], (handle['catalog'],)) != handle['catalog_pins']:
        raise ValueError('source prerequisite catalog changed during C2a processing')


def _with_artifacts(basis, key, descriptors):
    return [{**unit, 'artifacts': {**unit['artifacts'], key: descriptor}}
        for unit, descriptor in zip(basis, descriptors)]


def _declaration_unit(task):
    from scar.analysis.source_declarations import source_declarations_document, read_source_declarations
    model, destination, unit, role_root, role_descriptor, context_root, context_descriptor, prior_root, prior, limits, digest, independent = task
    f0, f1, f2 = read_source_prerequisites(_Fragments(model), unit, limits['max_nodes'], limits['max_tokens'])
    roles, contexts = _Fragments(role_root).read(role_descriptor), _Fragments(context_root).read(context_descriptor)
    for document, keys, stage in ((roles, ('max_ports', 'max_slots'), 'F3-B'),
            (contexts, _c1._OWN_LIMITS, 'F3-C1')):
        for key in keys:
            check_replay_limit(document, key, limits[key], stage)
    if prior is not None:
        document = _Fragments(prior_root).read(prior)
        for key in _OWN_LIMITS:
            check_replay_limit(document, key, limits[key], 'F3-C2a')
        read_source_declarations(document, f0, f1, f2, roles, contexts)
        descriptor = prior
    elif destination is None:
        raise ValueError('C2a declaration artifact is absent')
    else:
        document = source_declarations_document(f0, f1, f2, roles, contexts,
            **{key: limits[key] for key in _OWN_LIMITS})
        descriptor = None
    if document['profile']['declaration_catalog_sha256'] != digest:
        raise ValueError('C2a worker declaration catalog differs from its parent')
    if destination is not None and (independent or descriptor is None):
        relative = 'units/' + unit['key'] + '/source_declarations.json.gz'
        if (destination / relative).exists():
            raise FileExistsError('new C2a artifact collides with an existing file')
        descriptor = _write(destination, relative, document)
    row = dict(unit=unit['key'], artifact=descriptor, status=document['status'],
        **{key: len(document[key]) for key in _TOTALS},
        **{key: document[key] for key in _OWN_LIMITS}, frontiers=document['frontiers'],
        upstream_f1_status=f1['status'], upstream_f2_status=f2['status'],
        upstream_f3b_status=roles['status'], upstream_c1_status=contexts['status'])
    role_row = dict(unit=unit['key'], artifact=role_descriptor, status=roles['status'], slots=roles['slots'],
        ports=len(roles['ports']), list_items=roles['list_items'], max_ports=roles['max_ports'],
        max_slots=roles['max_slots'], upstream_f1_status=f1['status'], upstream_f2_status=f2['status'], frontiers=roles['frontiers'])
    context_row = dict(unit=unit['key'], artifact=context_descriptor, status=contexts['status'],
        **{key: len(contexts[key]) for key in ('scopes', 'regions', 'private_contexts', 'boundaries')},
        ports=len(roles['ports']) if contexts['status'] == 'CONTEXTUALIZED' else 0, slots=contexts['slots'],
        **{key: contexts[key] for key in _c1._OWN_LIMITS}, frontiers=contexts['frontiers'],
        upstream_f1_status=f1['status'], upstream_f2_status=f2['status'], upstream_f3b_status=roles['status'])
    return row, role_row, roles['counts'], context_row, contexts['counts']


def _report(rows, *, schema, limits, jobs, digest):
    covered = [row['status'] != 'BUDGET_STOPPED' and row['upstream_f1_status'] != 'BUDGET_STOPPED'
        and row['upstream_f2_status'] not in ('BUDGET_STOPPED', 'PARSER_RESOURCE_ERROR')
        and row['upstream_f3b_status'] != 'BUDGET_STOPPED' and row['upstream_c1_status'] != 'BUDGET_STOPPED' for row in rows]
    return dict(schema=schema, schema_version=1, stage='F3-C2a', input_scope='DECLARED_MODEL_SOURCE_UNITS',
        units=len(rows), covered_units=sum(covered), complete_for_declared_units=all(covered),
        all_declared_units_declared=all(row['status'] == 'DECLARED' for row in rows),
        status_counts=dict(Counter(row['status'] for row in rows)), results=rows,
        **{key: sum(row[key] for row in rows) for key in _TOTALS}, limits=limits, jobs=jobs,
        catalog_sha256=digest, symtable_executed=False, target_executed=False,
        later_stages_verified=False, whole_program_complete=False, **_FLAGS)


def _check_summary(document, rows, digest):
    limits, jobs = document.get('limits'), document.get('jobs')
    if (type(limits) is not dict or set(limits) != set(_DEFAULTS)
            or any(type(value) is not int or value < 0 for value in limits.values())
            or type(jobs) is not int or not 1 <= jobs <= 32):
        raise ValueError('invalid C2a material budgets/jobs')
    for row in rows:
        for key in _OWN_LIMITS:
            if type(row.get(key)) is not int or not 0 <= row[key] <= limits[key]:
                raise ValueError('C2a row budget exceeds stored limits')
    expected = _report(rows, schema='scar.source-declaration-materials', limits=limits, jobs=jobs, digest=digest)
    if (_json({key: document.get(key) for key in expected}) != _json(expected)
            or document.get('collect_only') is not True or document.get('canonical_model_published') is not False
            or document.get('manifest_unchanged') is not True):
        raise ValueError('C2a material summary differs from freshly verified declaration rows')
    for key in ('observed_manifest_sha256', 'prior_manifest_sha256', 'published_manifest_sha256'):
        if type(document.get(key)) is not str or re.fullmatch(r'[0-9a-f]{64}', document[key]) is None:
            raise ValueError('invalid observed C2a manifest receipt')
    if 'seconds' in document and (type(document['seconds']) not in (int, float)
            or not math.isfinite(document['seconds']) or document['seconds'] < 0):
        raise ValueError('invalid C2a observed duration')


def _catalog_at(root, descriptor, expected):
    if descriptor.get('path') != _CATALOG or _json(_Fragments(root).read(descriptor)) != _json(expected):
        raise ValueError('C2a catalog receipt/content differs from the declaration catalog')


def _inventory(report, catalog):
    keys = ('stage', 'units', *_TOTALS, 'status_counts', 'catalog_sha256', *_FLAGS,
        'later_stages_verified', 'whole_program_complete')
    return dict({key: report[key] for key in keys}, schema='scar.source-declaration-inventory', schema_version=1,
        scope='DECLARED_MODEL_SOURCE_UNITS', artifacts=[catalog])


def model_source_declarations(model, out, *, roles_materials=None, contexts_materials=None, jobs=4,
        collect_only=False, verify=False, materials=None, max_nodes=1_000_000, max_tokens=2_000_000,
        max_ports=1_000_000, max_slots=10_000_000, max_scopes=100_000, max_regions=200_000,
        max_boundaries=1_000_000, max_names=1_000_000, max_contributions=1_000_000, max_conflicts=100_000):
    from scar.analysis.source_declarations import source_declaration_catalog
    from scar.analysis.source_contexts import source_context_catalog
    from scar.analysis.source_roles import source_role_catalog
    limits = dict(max_nodes=max_nodes, max_tokens=max_tokens, max_ports=max_ports, max_slots=max_slots,
        max_scopes=max_scopes, max_regions=max_regions, max_boundaries=max_boundaries,
        max_names=max_names, max_contributions=max_contributions, max_conflicts=max_conflicts)
    if (type(jobs) is not int or not 1 <= jobs <= 32 or type(collect_only) is not bool or type(verify) is not bool
            or collect_only and verify or materials is not None and not verify
            or (roles_materials is not None or contexts_materials is not None) and not (collect_only or verify)
            or any(type(value) is not int or value < 0 for value in limits.values())):
        raise ValueError('C2a requires bounded distinct modes; external prerequisite capture is collect-only')
    started = time.monotonic()
    catalog, b_catalog, c_catalog = source_declaration_catalog(), source_role_catalog(), source_context_catalog()
    digest = catalog['content_sha256']
    with SourceStage(model, out, artifact=_ARTIFACT, verify=verify or collect_only,
            consumes=(*REQUIRED_SOURCE_ARTIFACTS, 'source_roles', 'source_contexts', _ARTIFACT)) as stage:
        basis = source_input_basis(stage.manifest['units'])
        b = _input(stage, 'source_roles', roles_materials, basis, b_catalog, _b)
        basis = _with_artifacts(basis, 'source_roles', b['descriptors'])
        c = _input(stage, 'source_contexts', contexts_materials, basis, c_catalog, _c1)
        basis = _with_artifacts(basis, 'source_contexts', c['descriptors'])
        existing, canonical_catalog = stage.manifest.get(_ARTIFACT), None
        if existing is not None:
            if type(existing.get('artifacts')) is not list or len(existing['artifacts']) != 1:
                raise ValueError('canonical C2a inventory must own one shared catalog')
            canonical_catalog = existing['artifacts'][0]
            _catalog_at(stage.root, canonical_catalog, catalog)
        canonical_pins = _stamps(stage.root, (canonical_catalog,)) if canonical_catalog else None
        stored = store_root = store_raw = store_pins = None
        if materials is not None:
            store_root, stored, store_raw = read_material_manifest(materials, stage.out)
            _check_summary(stored, stored['results'], digest)
            if _json(stored.get('basis')) != _json(basis) or len(stored['results']) != len(basis):
                raise ValueError('C2a material source/role/context basis differs from selected prerequisites')
            if any(row['unit'] != unit['key'] or row['artifact']['path'] != stage.relative(unit)
                    for row, unit in zip(stored['results'], basis)):
                raise ValueError('C2a material unit/path order differs from original model')
            _catalog_at(store_root, stored['catalog'], catalog)
            store_pins = pin_material_store(store_root, [stored['catalog'], *(row['artifact'] for row in stored['results'])], store_raw)
        destination = stage.out if collect_only else stage.staging
        if destination is not None and (collect_only or canonical_catalog is None):
            if (destination / _CATALOG).exists():
                raise FileExistsError('new C2a catalog collides with an existing file')
            descriptor = _write(destination, _CATALOG, catalog)
        else:
            descriptor = stored['catalog'] if stored else canonical_catalog
            if descriptor is None:
                raise ValueError('canonical C2a declaration catalog is absent')
        replay_limits = {key: min(value, stored['limits'][key]) for key, value in limits.items()} if stored else limits
        tasks = [(stage.root, destination, unit, b['root'], b['descriptors'][i], c['root'], c['descriptors'][i],
            store_root or stage.root, stored['results'][i]['artifact'] if stored else
            stage.manifest['units'][i]['artifacts'].get(_ARTIFACT), replay_limits, digest, collect_only)
            for i, unit in enumerate(basis)]
        rows, b_rows, c_rows = [], [], []
        b_counts = [dict(rule=rule['rule'], **{key: 0 for key in _b._COUNT_FIELDS}) for rule in b_catalog['rules']]
        c_counts = [dict(rule=rule['rule'], **{key: 0 for key in _c1._COUNT_FIELDS}) for rule in c_catalog['rules']]
        def accept(packet):
            row, b_row, b_current, c_row, c_current = packet
            rows.append(row);b_rows.append(b_row);c_rows.append(c_row)
            for total, current, fields in ((b_counts, b_current, _b._COUNT_FIELDS), (c_counts, c_current, _c1._COUNT_FIELDS)):
                if len(total) != len(current):
                    raise ValueError('C2a verified prerequisite packet has an incomplete counter denominator')
                for left, right in zip(total, current):
                    if left['rule'] != right['rule']:
                        raise ValueError('C2a verified prerequisite rule order changed')
                    for key in fields:
                        left[key] += right[key]
        if jobs == 1:
            for packet in map(_declaration_unit, tasks):accept(packet)
        else:
            with ProcessPoolExecutor(max_workers=jobs, mp_context=multiprocessing.get_context('spawn')) as pool:
                for packet in pool.map(_declaration_unit, tasks, chunksize=1):accept(packet)
        _check_input(stage, b, b_rows, b_counts, jobs)
        _check_input(stage, c, c_rows, c_counts, jobs)
        if stored is not None:
            _check_summary(stored, rows, digest)
            check_material_store(store_root, [stored['catalog'], *(row['artifact'] for row in rows)], store_raw, store_pins)
        report = _report(rows, schema=('scar.source-declaration-material-verification' if stored else
            'scar.source-declaration-verification' if verify else 'scar.source-declaration-materials' if collect_only
            else 'scar.source-declaration-gate'), limits=limits, jobs=jobs, digest=digest)
        report.update(catalog=descriptor, collect_only=collect_only, canonical_model_published=False,
            observed_manifest_sha256=sha256(stage.original).hexdigest())
        if collect_only:
            report['basis'] = basis
            material_store_members(stage.out, [descriptor, *(row['artifact'] for row in rows)], result=False)
        elif not verify and report['complete_for_declared_units']:
            stage.publish(rows, _inventory(report, descriptor));report['canonical_model_published'] = True
        elif verify and stored is None and _json(existing) != _json(_inventory(report, descriptor)):
            raise ValueError('canonical C2a inventory differs from freshly verified declarations')
        if canonical_catalog and _stamps(stage.root, (canonical_catalog,)) != canonical_pins:
            raise ValueError('canonical C2a catalog changed before publication')
        if stored is not None:
            report.update(materials=str(store_root), materials_result_sha256=sha256(store_raw).hexdigest(),
                material_source_basis_unchanged=True)
        report['seconds'] = time.monotonic() - started
        return stage.finish(report)


def main(argv=None):
    parser = argparse.ArgumentParser(prog='scar source-declarations')
    for key in ('model', 'out'):parser.add_argument('--' + key, required=True)
    for key in ('roles-materials', 'contexts-materials', 'materials'):parser.add_argument('--' + key)
    parser.add_argument('--jobs', type=int, default=4)
    parser.add_argument('--collect-only', action='store_true')
    parser.add_argument('--verify', action='store_true')
    for key, value in _DEFAULTS.items():parser.add_argument('--' + key.replace('_', '-'), type=int, default=value)
    report = model_source_declarations(**vars(parser.parse_args(argv)))
    print(_json({key: report[key] for key in ('stage', 'units', *_TOTALS, 'status_counts',
        'complete_for_declared_units', 'canonical_model_published')}).decode().strip())
    return 0 if report['complete_for_declared_units'] else 1


__all__ = ['model_source_declarations', 'main']
