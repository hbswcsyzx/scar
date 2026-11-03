"""F3-C1 context sidecars over original F2 and independently owned F3-B inputs."""
from __future__ import annotations

import argparse
from collections import Counter
from concurrent.futures import ProcessPoolExecutor
from hashlib import sha256
import math
import multiprocessing
import re
from pathlib import Path
import time

from scar.analysis.source_materials import _stamps
from scar.analysis.source_role_materials import (
    _catalog_at as _roles_catalog_at, _check_summary as _check_roles_summary,
    _COUNT_FIELDS as _ROLE_COUNT_FIELDS, _report as _role_report, _inventory as _role_inventory,
)
from scar.analysis.source_stage import SourceStage
from scar.analysis.source_store import (
    REQUIRED_SOURCE_ARTIFACTS, source_input_basis, read_source_prerequisites,
    check_replay_limit, material_store_members, read_material_manifest,
    pin_material_store, check_material_store,
)
from scar.analysis.static_program import _json, _write
from scar.analysis.static_query import _Fragments


_CATALOG = 'source_contexts/catalog.json.gz'
_OWN_LIMITS = ('max_scopes', 'max_regions', 'max_boundaries', 'max_slots')
_TOTALS = ('scopes', 'regions', 'private_contexts', 'boundaries', 'ports', 'slots')
_COUNT_FIELDS = ('slots', 'absent', 'none', 'empty_list', 'values', 'boundaries')
_FLAGS = dict(authority='SOURCE_CONTEXT_TEMPLATES', compiler_projection='NOT_COMPUTED_IN_C1',
    runtime_frames='NOT_RECORDED')


def _context_unit(task):
    from scar.analysis.source_contexts import source_contexts_document, read_source_contexts
    model, destination, unit, role_root, role_descriptor, prior_root, prior, limits, catalog_sha, independent = task
    f0, f1, f2 = read_source_prerequisites(_Fragments(model), unit, limits['max_nodes'], limits['max_tokens'])
    roles = _Fragments(role_root).read(role_descriptor)
    for key in ('max_ports', 'max_slots'):
        check_replay_limit(roles, key, limits[key], 'F3-B')
    if prior is not None:
        document = _Fragments(prior_root).read(prior)
        for key in _OWN_LIMITS:
            check_replay_limit(document, key, limits[key], 'F3-C1')
        read_source_contexts(document, f0, f1, f2, roles)
        descriptor = prior
    elif destination is None:
        raise ValueError('F3-C1 context sidecar is absent')
    else:
        document = source_contexts_document(f0, f1, f2, roles, **{key: limits[key] for key in _OWN_LIMITS})
        descriptor = None
    if document['profile']['context_catalog_sha256'] != catalog_sha:
        raise ValueError('F3-C1 worker context catalog differs from its parent')
    if destination is not None and (independent or descriptor is None):
        relative = 'units/' + unit['key'] + '/source_contexts.json.gz'
        if (destination / relative).exists():
            raise FileExistsError('new F3-C1 material would overwrite a file')
        descriptor = _write(destination, relative, document)
    row = dict(unit=unit['key'], artifact=descriptor, status=document['status'],
        **{key: len(document[key]) for key in ('scopes', 'regions', 'private_contexts', 'boundaries')},
        ports=len(roles['ports']) if document['status'] == 'CONTEXTUALIZED' else 0, slots=document['slots'],
        **{key: document[key] for key in _OWN_LIMITS}, frontiers=document['frontiers'],
        upstream_f1_status=f1['status'], upstream_f2_status=f2['status'], upstream_f3b_status=roles['status'])
    role_row = dict(unit=unit['key'], artifact=role_descriptor, status=roles['status'], slots=roles['slots'],
        ports=len(roles['ports']), list_items=roles['list_items'], max_ports=roles['max_ports'],
        max_slots=roles['max_slots'], upstream_f1_status=f1['status'], upstream_f2_status=f2['status'],
        frontiers=roles['frontiers'])
    return row, document['counts'], role_row, roles['counts']


def _covered(row):
    return (row['status'] != 'BUDGET_STOPPED' and row['upstream_f1_status'] != 'BUDGET_STOPPED'
        and row['upstream_f2_status'] not in ('BUDGET_STOPPED', 'PARSER_RESOURCE_ERROR')
        and row['upstream_f3b_status'] != 'BUDGET_STOPPED')


def _report(rows, counts, *, schema, limits, jobs, catalog_sha):
    return dict(schema=schema, schema_version=1, stage='F3-C1', input_scope='DECLARED_MODEL_SOURCE_UNITS',
        units=len(rows), covered_units=sum(_covered(row) for row in rows),
        complete_for_declared_units=all(_covered(row) for row in rows),
        all_declared_units_routed=all(row['status'] == 'CONTEXTUALIZED' for row in rows),
        status_counts=dict(Counter(row['status'] for row in rows)), results=rows, rule_counts=counts,
        **{key: sum(row[key] for row in rows) for key in _TOTALS}, limits=limits, jobs=jobs,
        catalog_sha256=catalog_sha, symtable_executed=False, target_executed=False,
        later_stages_verified=False, whole_program_complete=False, **_FLAGS)


def _check_summary(document, rows, counts, catalog_sha):
    limits, jobs = document.get('limits'), document.get('jobs')
    if (type(limits) is not dict or set(limits) != {*_OWN_LIMITS, 'max_nodes', 'max_tokens', 'max_ports'}
            or any(type(n) is not int or n < 0 for n in limits.values())
            or type(jobs) is not int or not 1 <= jobs <= 32):
        raise ValueError('invalid F3-C1 material budgets/jobs')
    for row in rows:
        for key in _OWN_LIMITS:
            if type(row.get(key)) is not int or not 0 <= row[key] <= limits[key]:
                raise ValueError('F3-C1 row budget exceeds the stored limits')
    from scar.ir.program.source_contexts import RuleContextCount
    from scar.ir.record_codec import decode
    totals = decode(tuple[RuleContextCount, ...], counts)
    if (tuple(item.rule for item in totals) != tuple(range(484))
            or sum(item.slots for item in totals) != sum(row['slots'] for row in rows)
            or sum(item.boundaries for item in totals) != sum(row['boundaries'] for row in rows)):
        raise ValueError('F3-C1 counter denominator differs from its context rows')
    expected = _report(rows, counts, schema='scar.source-context-materials', limits=limits, jobs=jobs, catalog_sha=catalog_sha)
    if (_json({key: document.get(key) for key in expected}) != _json(expected)
            or document.get('collect_only') is not True or document.get('canonical_model_published') is not False
            or document.get('manifest_unchanged') is not True):
        raise ValueError('F3-C1 material summary differs from its freshly verified rows')
    for key in ('observed_manifest_sha256', 'prior_manifest_sha256', 'published_manifest_sha256'):
        if type(document.get(key)) is not str or re.fullmatch(r'[0-9a-f]{64}', document[key]) is None:
            raise ValueError('invalid observed F3-C1 manifest receipt')
    if 'seconds' in document and (type(document['seconds']) not in (int, float)
            or not math.isfinite(document['seconds']) or document['seconds'] < 0):
        raise ValueError('invalid F3-C1 observed duration')
    return limits


def _catalog_at(root, descriptor, expected):
    if descriptor.get('path') != _CATALOG or _json(_Fragments(root).read(descriptor)) != _json(expected):
        raise ValueError('F3-C1 catalog receipt/content differs from the current context catalog')


def _inventory(report, catalog):
    keys = ('stage', 'units', *_TOTALS, 'status_counts', 'catalog_sha256', *_FLAGS,
        'rule_counts', 'later_stages_verified', 'whole_program_complete')
    return dict({key: report[key] for key in keys}, schema='scar.source-context-inventory', schema_version=1,
        scope='DECLARED_MODEL_SOURCE_UNITS', artifacts=[catalog])


def model_source_contexts(model, out, *, roles_materials=None, jobs=4, verify=False, collect_only=False,
                          materials=None, max_nodes=1_000_000, max_tokens=2_000_000, max_ports=1_000_000,
                          max_slots=10_000_000, max_scopes=100_000, max_regions=200_000, max_boundaries=1_000_000):
    """Route source fields; external F3-B inputs never silently publish into a model."""
    from scar.analysis.source_contexts import source_context_catalog
    from scar.analysis.source_roles import source_role_catalog
    limits = dict(max_nodes=max_nodes, max_tokens=max_tokens, max_ports=max_ports, max_slots=max_slots,
        max_scopes=max_scopes, max_regions=max_regions, max_boundaries=max_boundaries)
    if (type(jobs) is not int or not 1 <= jobs <= 32 or type(verify) is not bool or type(collect_only) is not bool
            or verify and collect_only or materials is not None and not verify
            or roles_materials is not None and not (collect_only or verify)
            or any(type(n) is not int or n < 0 for n in limits.values())):
        raise ValueError('F3-C1 requires bounded distinct modes; external F3-B capture is collect-only')
    started = time.monotonic()
    catalog, role_catalog = source_context_catalog(), source_role_catalog()
    catalog_sha = catalog['content_sha256']
    with SourceStage(model, out, artifact='source_contexts', verify=verify or collect_only,
            consumes=(*REQUIRED_SOURCE_ARTIFACTS, 'source_roles', 'source_contexts')) as stage:
        base = source_input_basis(stage.manifest['units'])
        role_store = role_raw = role_pins = None
        if roles_materials is not None:
            role_root, role_store, role_raw = read_material_manifest(roles_materials, stage.out)
            _check_roles_summary(role_store, role_store['results'], role_store['rule_counts'], role_catalog['content_sha256'])
            if _json(role_store.get('basis')) != _json(base):
                raise ValueError('external F3-B source basis differs from the model')
            role_descriptors = [row['artifact'] for row in role_store['results']]
            if len(role_descriptors) != len(base) or any(row['unit'] != unit['key']
                    or row['artifact']['path'] != 'units/' + unit['key'] + '/source_roles.json.gz'
                    for row, unit in zip(role_store['results'], base)):
                raise ValueError('external F3-B unit/path order differs from the model')
            role_catalog_descriptor = role_store['catalog']
            role_pins = pin_material_store(role_root, [role_catalog_descriptor, *role_descriptors], role_raw)
        else:
            role_root = stage.root
            inventory = stage.manifest.get('source_roles')
            if type(inventory) is not dict or len(inventory.get('artifacts', ())) != 1:
                raise ValueError('F3-C1 requires canonical F3-B or explicit --roles-materials')
            role_catalog_descriptor = inventory['artifacts'][0]
            try:
                role_descriptors = [unit['artifacts']['source_roles'] for unit in stage.manifest['units']]
            except KeyError as exc:
                raise ValueError('canonical F3-B unit sidecar is absent') from exc
        _roles_catalog_at(role_root, role_catalog_descriptor, role_catalog)
        role_catalog_pins = _stamps(role_root, (role_catalog_descriptor,))
        basis = [{**unit, 'artifacts': {**unit['artifacts'], 'source_roles': role}}
            for unit, role in zip(base, role_descriptors)]
        existing = stage.manifest.get('source_contexts')
        canonical_catalog = None
        if existing is not None:
            if type(existing.get('artifacts')) is not list or len(existing['artifacts']) != 1:
                raise ValueError('canonical F3-C1 must own exactly one shared catalog')
            canonical_catalog = existing['artifacts'][0]
            _catalog_at(stage.root, canonical_catalog, catalog)
        canonical_pins = _stamps(stage.root, (canonical_catalog,)) if canonical_catalog else None
        stored = store_root = store_raw = store_pins = None
        if materials is not None:
            store_root, stored, store_raw = read_material_manifest(materials, stage.out)
            _check_summary(stored, stored['results'], stored['rule_counts'], catalog_sha)
            if _json(stored.get('basis')) != _json(basis) or len(stored['results']) != len(basis):
                raise ValueError('F3-C1 material source/role basis differs from current inputs')
            for row, unit in zip(stored['results'], basis):
                if row['unit'] != unit['key'] or row['artifact']['path'] != stage.relative(unit):
                    raise ValueError('F3-C1 material unit/path differs from the model')
            _catalog_at(store_root, stored['catalog'], catalog)
            store_pins = pin_material_store(store_root,
                [stored['catalog'], *(row['artifact'] for row in stored['results'])], store_raw)
        destination = stage.out if collect_only else stage.staging
        if destination is not None:
            destination.mkdir(parents=True, exist_ok=True)
            if collect_only or canonical_catalog is None:
                if (destination / _CATALOG).exists():
                    raise FileExistsError('new F3-C1 catalog collides with an existing file')
                descriptor = _write(destination, _CATALOG, catalog)
            else:
                descriptor = canonical_catalog
        else:
            descriptor = stored['catalog'] if stored is not None else canonical_catalog
            if descriptor is None:
                raise ValueError('canonical F3-C1 context catalog is absent')
        replay_limits = {key: min(value, stored['limits'][key]) for key, value in limits.items()} if stored else limits
        tasks = [(stage.root, destination, unit, role_root, role_descriptors[i], store_root or stage.root,
            stored['results'][i]['artifact'] if stored else stage.manifest['units'][i]['artifacts'].get('source_contexts'),
            replay_limits, catalog_sha, collect_only) for i, unit in enumerate(base)]
        rows, role_rows = [], []
        counts = [dict(rule=rule['rule'], **{key: 0 for key in _COUNT_FIELDS}) for rule in catalog['rules']]
        role_counts = [dict(rule=rule['rule'], **{key: 0 for key in _ROLE_COUNT_FIELDS}) for rule in role_catalog['rules']]
        def accept(packet):
            row, current_counts, role_row, current_roles = packet
            rows.append(row)
            role_rows.append(role_row)
            for totals, current, fields in ((counts, current_counts, _COUNT_FIELDS),
                    (role_counts, current_roles, _ROLE_COUNT_FIELDS)):
                if len(current) != len(totals):
                    raise ValueError('fresh context/role packet has an incomplete rule denominator')
                for total, item in zip(totals, current):
                    if total['rule'] != item['rule']:
                        raise ValueError('fresh context/role packet has a changed rule order')
                    for key in fields:
                        total[key] += item[key]
        if jobs == 1:
            for packet in map(_context_unit, tasks):
                accept(packet)
        else:
            with ProcessPoolExecutor(max_workers=jobs, mp_context=multiprocessing.get_context('spawn')) as pool:
                for packet in pool.map(_context_unit, tasks, chunksize=1):
                    accept(packet)
        if role_store is not None:
            _check_roles_summary(role_store, role_rows, role_counts, role_catalog['content_sha256'])
            check_material_store(role_root, [role_catalog_descriptor, *role_descriptors], role_raw, role_pins)
        else:
            role_report = _role_report(role_rows, role_counts, schema='', limits={}, jobs=jobs,
                catalog_sha=role_catalog['content_sha256'])
            if _json(stage.manifest['source_roles']) != _json(_role_inventory(role_report, role_catalog_descriptor)):
                raise ValueError('canonical F3-B inventory differs from freshly verified role inputs')
        if _stamps(role_root, (role_catalog_descriptor,)) != role_catalog_pins:
            raise ValueError('F3-B catalog changed during C1 processing')
        if stored is not None:
            _check_summary(stored, rows, counts, catalog_sha)
            check_material_store(store_root, [stored['catalog'], *(row['artifact'] for row in rows)], store_raw, store_pins)
        report = _report(rows, counts, schema=('scar.source-context-material-verification' if stored else
            'scar.source-context-verification' if verify else 'scar.source-context-materials' if collect_only
            else 'scar.source-context-gate'), limits=limits, jobs=jobs, catalog_sha=catalog_sha)
        report.update(catalog=descriptor, collect_only=collect_only, canonical_model_published=False,
            observed_manifest_sha256=sha256(stage.original).hexdigest(), roles_materials=str(role_root) if role_store else None)
        if collect_only:
            report['basis'] = basis
            material_store_members(stage.out, [descriptor, *(row['artifact'] for row in rows)], result=False)
        elif not verify and report['complete_for_declared_units']:
            stage.publish(rows, _inventory(report, descriptor))
            report['canonical_model_published'] = True
        elif verify and stored is None and _json(existing) != _json(_inventory(report, descriptor)):
            raise ValueError('canonical F3-C1 inventory differs from freshly replayed contexts')
        if canonical_catalog and _stamps(stage.root, (canonical_catalog,)) != canonical_pins:
            raise ValueError('canonical F3-C1 catalog changed before publication')
        if stored is not None:
            report.update(materials=str(store_root), materials_result_sha256=sha256(store_raw).hexdigest(),
                material_source_basis_unchanged=True)
        report['seconds'] = time.monotonic() - started
        return stage.finish(report)


def main(argv=None):
    parser = argparse.ArgumentParser(prog='scar source-contexts')
    for key in ('model', 'out'):
        parser.add_argument('--' + key, required=True)
    parser.add_argument('--roles-materials')
    parser.add_argument('--materials')
    parser.add_argument('--collect-only', action='store_true')
    parser.add_argument('--verify', action='store_true')
    parser.add_argument('--jobs', type=int, default=4)
    for key, default in (('nodes', 1_000_000), ('tokens', 2_000_000), ('ports', 1_000_000),
            ('slots', 10_000_000), ('scopes', 100_000), ('regions', 200_000), ('boundaries', 1_000_000)):
        parser.add_argument('--max-' + key, type=int, default=default)
    args = vars(parser.parse_args(argv))
    report = model_source_contexts(**args)
    print(_json({key: report[key] for key in ('stage', 'units', 'scopes', 'regions', 'boundaries',
        'status_counts', 'complete_for_declared_units', 'canonical_model_published')}).decode().strip())
    return 0 if report['complete_for_declared_units'] else 1


__all__ = ['model_source_contexts', 'main']
