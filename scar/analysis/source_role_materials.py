"""F3-B sparse field-role material stores, independent of symbol tables."""
from __future__ import annotations

import argparse
from collections import Counter
from concurrent.futures import ProcessPoolExecutor
from hashlib import sha256
import math
import multiprocessing
from pathlib import Path
import re
import time

from scar.analysis.source_materials import _stamps
from scar.analysis.source_stage import SourceStage
from scar.analysis.source_store import (
    REQUIRED_SOURCE_ARTIFACTS, source_input_basis, read_source_prerequisites,
    check_replay_limit, material_store_members, read_material_manifest,
    pin_material_store, check_material_store,
)
from scar.analysis.static_program import _json, _write
from scar.analysis.static_query import _Fragments


_CATALOG = 'source_roles/catalog.json.gz'
_COUNT_FIELDS = ('slots', 'absent', 'none', 'empty_list', 'values', 'list_items', 'ports')
_BOUNDARIES = dict(authority='SYNTAX_FIELD_ROLES', scope_binding='NOT_COMPUTED_IN_F3B', runtime_effects='NOT_CLAIMED')


def _catalog_at(root, descriptor, expected):
    if descriptor.get('path') != _CATALOG or _json(_Fragments(root).read(descriptor)) != _json(expected):
        raise ValueError('F3-B catalog receipt/content differs from the current field-role catalog')


def _role_unit(task):
    from scar.analysis.source_roles import source_roles_document, read_source_roles
    model, destination, unit, prior, prior_root, limits, catalog_sha, independent = task
    f0, f1, f2 = read_source_prerequisites(_Fragments(model), unit, limits['max_nodes'], limits['max_tokens'])
    if prior is not None:
        document = _Fragments(prior_root or model).read(prior)
        for name in ('max_ports', 'max_slots'):
            check_replay_limit(document, name, limits[name], 'F3-B')
        read_source_roles(document, f0, f1, f2)
        descriptor = prior
    elif destination is None:
        raise ValueError('F3-B source-role artifact is absent')
    else:
        document = source_roles_document(f0, f1, f2, max_ports=limits['max_ports'], max_slots=limits['max_slots'])
        descriptor = None
    if document['profile']['catalog_sha256'] != catalog_sha:
        raise ValueError('F3-B worker field-role catalog differs from its parent')
    if destination is not None and (independent or descriptor is None):
        relative = 'units/' + unit['key'] + '/source_roles.json.gz'
        if (destination / relative).exists():
            raise FileExistsError('new F3-B material would overwrite an existing file')
        descriptor = _write(destination, relative, document)
    row = {'unit': unit['key'], 'artifact': descriptor, 'status': document['status'],
        'slots': document['slots'], 'ports': len(document['ports']), 'list_items': document['list_items'],
        'max_ports': document['max_ports'], 'max_slots': document['max_slots'],
        'upstream_f1_status': f1['status'], 'upstream_f2_status': f2['status'],
        'frontiers': document['frontiers']}
    return row, document['counts']


def _covered(row):
    return (row['status'] != 'BUDGET_STOPPED' and row['upstream_f1_status'] != 'BUDGET_STOPPED'
        and row['upstream_f2_status'] not in ('BUDGET_STOPPED', 'PARSER_RESOURCE_ERROR'))


def _report(rows, counts, *, schema, limits, jobs, catalog_sha):
    return dict(schema=schema, schema_version=1, stage='F3-B', input_scope='DECLARED_MODEL_SOURCE_UNITS',
        units=len(rows), covered_units=sum(_covered(row) for row in rows),
        complete_for_declared_units=all(_covered(row) for row in rows),
        all_declared_units_classified=all(row['status'] == 'CLASSIFIED' for row in rows),
        status_counts=dict(Counter(row['status'] for row in rows)),
        slots=sum(row['slots'] for row in rows), ports=sum(row['ports'] for row in rows),
        list_items=sum(row['list_items'] for row in rows), rule_counts=counts, results=rows,
        limits=limits, jobs=jobs, catalog_sha256=catalog_sha, symtable_executed=False,
        target_executed=False, later_stages_verified=False, whole_program_complete=False, **_BOUNDARIES)


def _check_summary(document, rows, counts, catalog_sha):
    from scar.ir.program.source_roles import RuleCount
    from scar.ir.record_codec import decode
    limits, jobs = document.get('limits'), document.get('jobs')
    if (type(limits) is not dict or set(limits) != {'max_nodes', 'max_tokens', 'max_ports', 'max_slots'}
            or any(type(n) is not int or n < 0 for n in limits.values())
            or type(jobs) is not int or not 1 <= jobs <= 32):
        raise ValueError('invalid F3-B material limits/jobs')
    for row in rows:
        for name in ('max_ports', 'max_slots'):
            if type(row.get(name)) is not int or not 0 <= row[name] <= limits[name]:
                raise ValueError('F3-B row budget exceeds the stored material limits')
    totals = decode(tuple[RuleCount, ...], counts)
    if (tuple(item.rule for item in totals) != tuple(range(484))
            or any(sum(getattr(item, key) for item in totals) != sum(row[key] for row in rows)
                for key in ('slots', 'ports', 'list_items'))):
        raise ValueError('F3-B material rule counters differ from the declared slot/port denominator')
    expected = _report(rows, counts, schema='scar.source-role-materials', limits=limits, jobs=jobs, catalog_sha=catalog_sha)
    if (_json({key: document.get(key) for key in expected}) != _json(expected)
            or document.get('collect_only') is not True or document.get('canonical_model_published') is not False
            or document.get('manifest_unchanged') is not True):
        raise ValueError('F3-B material semantic summary differs from its field-role facts')
    for name in ('observed_manifest_sha256', 'prior_manifest_sha256', 'published_manifest_sha256'):
        if type(document.get(name)) is not str or re.fullmatch(r'[0-9a-f]{64}', document[name]) is None:
            raise ValueError('invalid observed F3-B manifest receipt')
    if 'seconds' in document and (type(document['seconds']) not in (int, float)
            or not math.isfinite(document['seconds']) or document['seconds'] < 0):
        raise ValueError('invalid observed F3-B duration')
    return limits


def _inventory(report, catalog):
    keys = ('stage', 'units', 'slots', 'ports', 'list_items', 'status_counts', 'rule_counts', 'catalog_sha256',
        'authority', 'scope_binding', 'runtime_effects', 'later_stages_verified', 'whole_program_complete')
    return dict({key: report[key] for key in keys}, schema='scar.source-role-inventory', schema_version=1,
        scope='DECLARED_MODEL_SOURCE_UNITS', artifacts=[catalog])


def model_source_roles(model, out, *, jobs=4, max_ports=1_000_000, max_slots=10_000_000,
                       max_nodes=1_000_000, max_tokens=2_000_000, verify=False,
                       collect_only=False, materials=None):
    """Capture or replay sparse F2-slot roles; never requests F3-A bindings."""
    from scar.analysis.source_roles import source_role_catalog
    limits = dict(max_ports=max_ports, max_slots=max_slots, max_nodes=max_nodes, max_tokens=max_tokens)
    if (type(jobs) is not int or not 1 <= jobs <= 32 or type(verify) is not bool
            or type(collect_only) is not bool or verify and collect_only or materials is not None and not verify
            or any(type(n) is not int or n < 0 for n in limits.values())):
        raise ValueError('F3-B requires bounded budgets and distinct capture/verification modes')
    started = time.monotonic()
    catalog = source_role_catalog()
    catalog_sha = catalog['content_sha256']
    with SourceStage(model, out, artifact='source_roles', verify=verify or collect_only,
            consumes=(*REQUIRED_SOURCE_ARTIFACTS, 'source_roles')) as stage:
        basis = source_input_basis(stage.manifest['units'])
        existing = stage.manifest.get('source_roles')
        canonical_catalog = None
        canonical_pins = None
        if existing is not None:
            descriptors = existing.get('artifacts')
            if type(descriptors) is not list or len(descriptors) != 1:
                raise ValueError('canonical F3-B inventory must own exactly one shared catalog')
            canonical_catalog = descriptors[0]
            canonical_pins = _stamps(stage.root, (canonical_catalog,))
            _catalog_at(stage.root, canonical_catalog, catalog)
        stored = store_root = store_raw = store_pins = None
        if materials is not None:
            store_root, stored, store_raw = read_material_manifest(materials, stage.out)
            _check_summary(stored, stored['results'], stored['rule_counts'], catalog_sha)
            if (_json(stored.get('basis')) != _json(basis) or len(stored['results']) != len(basis)):
                raise ValueError('F3-B material source basis differs from current prerequisite receipts')
            for row, unit in zip(stored['results'], basis):
                if row['unit'] != unit['key'] or row['artifact']['path'] != stage.relative(unit):
                    raise ValueError('F3-B material has a different original unit/path')
            _catalog_at(store_root, stored['catalog'], catalog)
            store_pins = pin_material_store(store_root,
                [stored['catalog'], *(row['artifact'] for row in stored['results'])], store_raw)
        destination = stage.out if collect_only else stage.staging
        if destination is not None:
            destination.mkdir(parents=True, exist_ok=True)
            if collect_only or canonical_catalog is None:
                if (destination / _CATALOG).exists():
                    raise FileExistsError('new F3-B catalog would overwrite an existing file')
                catalog_descriptor = _write(destination, _CATALOG, catalog)
            else:
                catalog_descriptor = canonical_catalog
        elif stored is not None:
            catalog_descriptor = stored['catalog']
        elif canonical_catalog is not None:
            catalog_descriptor = canonical_catalog
        else:
            raise ValueError('canonical F3-B shared catalog is absent')
        replay_limits = ({key: min(value, stored['limits'][key]) for key, value in limits.items()}
                         if stored is not None else limits)
        tasks = [(stage.root, destination, unit,
            stored['results'][i]['artifact'] if stored is not None else stage.manifest['units'][i]['artifacts'].get('source_roles'),
            store_root, replay_limits, catalog_sha, collect_only) for i, unit in enumerate(basis)]
        rows = []
        counts = [dict(rule=rule['rule'], **{key: 0 for key in _COUNT_FIELDS}) for rule in catalog['rules']]

        def accept(packet):
            row, per_rule = packet
            rows.append(row)
            if len(per_rule) != len(counts):
                raise ValueError('F3-B worker counter denominator differs from the catalog')
            for total, current in zip(counts, per_rule):
                if current['rule'] != total['rule']:
                    raise ValueError('F3-B worker counter order differs from the catalog')
                for key in _COUNT_FIELDS:
                    total[key] += current[key]

        if jobs == 1:
            for packet in map(_role_unit, tasks):
                accept(packet)
        else:
            with ProcessPoolExecutor(max_workers=jobs, mp_context=multiprocessing.get_context('spawn')) as pool:
                for packet in pool.map(_role_unit, tasks, chunksize=1):
                    accept(packet)
        if stored is not None:
            _check_summary(stored, rows, counts, catalog_sha)
            check_material_store(store_root, [stored['catalog'], *(row['artifact'] for row in rows)], store_raw, store_pins)
        if canonical_catalog is not None and _stamps(stage.root, (canonical_catalog,)) != canonical_pins:
            raise ValueError('canonical F3-B catalog changed during processing')
        schema = ('scar.source-role-material-verification' if stored is not None else
            'scar.source-role-verification' if verify else
            'scar.source-role-materials' if collect_only else 'scar.source-role-gate')
        report = _report(rows, counts, schema=schema, limits=limits, jobs=jobs, catalog_sha=catalog_sha)
        report.update(catalog=catalog_descriptor, collect_only=collect_only, canonical_model_published=False,
            observed_manifest_sha256=sha256(stage.original).hexdigest())
        if collect_only:
            report['basis'] = basis
            material_store_members(stage.out, [catalog_descriptor, *(row['artifact'] for row in rows)], result=False)
        elif not verify and report['complete_for_declared_units']:
            stage.publish(rows, _inventory(report, catalog_descriptor))
            report['canonical_model_published'] = True
        elif verify and stored is None and _json(existing) != _json(_inventory(report, catalog_descriptor)):
            raise ValueError('canonical F3-B inventory differs from the freshly replayed counters')
        if canonical_catalog is not None and _stamps(stage.root, (canonical_catalog,)) != canonical_pins:
            raise ValueError('canonical F3-B catalog changed before receipt publication')
        if stored is not None:
            report.update(materials=str(store_root), materials_result_sha256=sha256(store_raw).hexdigest(),
                material_source_basis_unchanged=True)
        report['seconds'] = time.monotonic() - started
        return stage.finish(report)


def main(argv=None):
    parser = argparse.ArgumentParser(prog='scar source-roles')
    parser.add_argument('--model', required=True)
    parser.add_argument('--out', required=True)
    parser.add_argument('--materials')
    parser.add_argument('--verify', action='store_true')
    parser.add_argument('--collect-only', action='store_true')
    parser.add_argument('--jobs', type=int, default=4)
    for name, default in (('ports', 1_000_000), ('slots', 10_000_000), ('nodes', 1_000_000), ('tokens', 2_000_000)):
        parser.add_argument('--max-' + name, type=int, default=default)
    args = parser.parse_args(argv)
    report = model_source_roles(args.model, args.out, jobs=args.jobs, max_ports=args.max_ports,
        max_slots=args.max_slots, max_nodes=args.max_nodes, max_tokens=args.max_tokens,
        verify=args.verify, collect_only=args.collect_only, materials=args.materials)
    print(_json({key: report[key] for key in ('stage', 'units', 'slots', 'ports', 'status_counts',
        'complete_for_declared_units', 'canonical_model_published')}).decode().strip())
    return 0 if report['complete_for_declared_units'] else 1


__all__ = ['model_source_roles', 'main']
