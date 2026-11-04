"""Mechanical admission of explicitly trusted historical F3 verification.

This checks bytes, typed records and the full dependency/profile footprint.
It does not call a semantic replay reader or grant a new fresh-verification
claim. The caller supplies the already accepted F3-D report's exact digest.
"""
from __future__ import annotations

from collections import Counter
from dataclasses import dataclass
from hashlib import sha256
import json
from pathlib import Path
import re

from scar.analysis import source_symbol_materials as A, source_role_materials as B
from scar.analysis import source_context_materials as C, source_declaration_materials as D
from scar.analysis import source_binding_materials as Q, compiler_topology_materials as T
from scar.analysis import compiler_symbol_materials as S, frontend_check
from scar.analysis import source_symbols, source_roles, source_contexts, source_declarations
from scar.analysis import source_bindings, compiler_topology, compiler_symbols
from scar.analysis.source_materials import _stamps, _source_envelope, _matches
from scar.analysis.source_store import (
    REQUIRED_SOURCE_ARTIFACTS, source_input_basis, read_material_manifest,
    pin_material_store, check_material_store,
)
from scar.analysis.static_program import _json, _artifacts
from scar.analysis.static_query import _Fragments
from scar.ir.record_codec import decode, encode, loads
from scar.ir.program.source_symbols import SourceSymbolsMaterial
from scar.ir.program.source_roles import SourceRolesMaterial
from scar.ir.program.source_contexts import SourceContextsMaterial
from scar.ir.program.source_declarations import SourceDeclarationsMaterial
from scar.ir.program.source_bindings import SourceBindingsMaterial
from scar.ir.program.compiler_topology import CompilerTopologyMaterial
from scar.ir.program.compiler_symbols import CompilerSymbolsMaterial


_ARTIFACTS = ('source_symbols', 'source_roles', 'source_contexts', 'source_declarations',
              'source_bindings', 'compiler_topology', 'compiler_symbols')
_OWNERS = dict(zip(_ARTIFACTS, (A, B, C, D, Q, T, S)))
_TYPES = dict(zip(_ARTIFACTS, (SourceSymbolsMaterial, SourceRolesMaterial, SourceContextsMaterial,
    SourceDeclarationsMaterial, SourceBindingsMaterial, CompilerTopologyMaterial, CompilerSymbolsMaterial)))
_PARENTS = dict(zip(_ARTIFACTS, ((), (), ('source_roles',),
    ('source_roles', 'source_contexts'), ('source_roles', 'source_contexts', 'source_declarations'),
    ('source_roles', 'source_contexts', 'source_symbols'),
    ('source_roles', 'source_contexts', 'source_symbols', 'source_declarations', 'compiler_topology'))))
_DOC_NAMES = dict(zip(_ARTIFACTS, ('f3a', 'f3b', 'c1', 'c2a', 'c2b', 'topology', 'symbols')))


@dataclass(frozen=True)
class StageInput:
    artifact: str
    root: Path
    stored: dict
    raw: bytes
    pins: dict
    catalog: dict | None
    descriptors: tuple[dict, ...]
    inventory: dict
    verification_path: Path
    verification_raw: bytes
    verification_pins: dict


@dataclass(frozen=True)
class RegistrationPlan:
    model_root: Path
    model_basis: list
    source_descriptors: tuple[dict, ...]
    source_pins: dict
    acceptance_path: Path
    acceptance_raw: bytes
    acceptance_pins: dict
    receipt_sha: str
    stages: tuple[StageInput, ...]
    out: Path


def _read_report(path):
    path = Path(path).absolute()
    if path.resolve() != path or path.is_symlink() or not path.is_file():
        raise ValueError('registration requires an explicit canonical verification report file')
    pin = _stamps(path.parent, ({'path': path.name},))
    raw = path.read_bytes()
    if _stamps(path.parent, ({'path': path.name},)) != pin:
        raise ValueError('verification report changed during registration admission')
    document = loads(raw)
    if type(document) is not dict:
        raise ValueError('verification report must be a JSON object')
    return path, document, raw, pin


def _same(actual, expected, detail):
    if _json(actual) != _json(expected):
        raise ValueError(detail)


def _digest(document):
    return sha256(json.dumps(document, sort_keys=True, separators=(',', ':'), ensure_ascii=True).encode('ascii')).hexdigest()


def _catalogs():
    return dict(source_roles=source_roles.source_role_catalog(),
        source_contexts=source_contexts.source_context_catalog(),
        source_declarations=source_declarations.source_declaration_catalog(),
        source_bindings=source_bindings.source_binding_catalog(),
        compiler_topology=compiler_topology.compiler_topology_catalog(),
        compiler_symbols=compiler_symbols.compiler_symbol_catalog())


def _summary(artifact, stored, rows, counts, catalog_sha):
    owner = _OWNERS[artifact]
    if artifact == 'source_symbols':
        owner._check_summary(stored, rows)
    elif artifact in ('source_roles', 'source_contexts'):
        owner._check_summary(stored, rows, counts, catalog_sha)
    else:
        owner._check_summary(stored, rows, catalog_sha)


def _fresh_summary(artifact, stored, fresh, rows, counts, catalog_sha, root, raw):
    owner = _OWNERS[artifact]
    schema = stored['schema'].removesuffix('materials') + 'material-verification'
    if (fresh.get('schema') != schema or fresh.get('collect_only') is not False
            or fresh.get('canonical_model_published') is not False
            or fresh.get('materials') != str(root)
            or fresh.get('materials_result_sha256') != sha256(raw).hexdigest()
            or any(fresh.get(key) is not True for key in ('manifest_unchanged',
                'material_source_basis_unchanged', 'consumed_artifacts_unchanged',
                'original_units_and_endpoints_unchanged', 'complete_for_declared_units'))):
        raise ValueError('historical fresh report does not seal the selected material store')
    _same(fresh.get('results'), rows, 'historical verification rows differ from actual material facts')
    _same(fresh.get('limits'), stored['limits'], 'historical verification limits differ from the accepted store')
    # Use the owner policy on the same semantic fields. Transport modes differ
    # between collection and verification; neither report is rewritten on disk.
    normalized = {**fresh, 'schema': stored['schema'], 'collect_only': True}
    _summary(artifact, normalized, rows, counts, catalog_sha)
    if artifact != 'source_symbols':
        _same(fresh.get('catalog'), stored['catalog'], 'historical catalog file receipt differs')


def _profiles(f0, native):
    return dict(source_symbols=source_symbols._profile(f0), source_roles=source_roles._profile(),
        source_contexts=source_contexts._profile(), source_declarations=source_declarations._profile(),
        source_bindings=source_bindings._profile(), compiler_topology=compiler_topology._profile(native),
        compiler_symbols=compiler_symbols._profile(native))


def _check_inputs(document, source, digests, *, unit, documents):
    f0, f1, f2 = source
    values = dict(digests)
    b, c, d, q, a, t, s = (documents[key] for key in frontend_check._ORDER)
    values.update(path=unit['path'], mode=f2['mode'], view_sha256=f1['view']['sha256'] if f1['view'] else None,
        f2_status=f2['status'], f3b_status=b['status'], c1_status=c['status'], c2a_status=d['status'],
        declaration_status=d['status'], f3a_status=a['status'], topology_status=t['status'],
        port_count=len(b['ports']), scope_count=len(c['scopes']), source_scope_count=len(c['scopes']),
        native_scope_count=len(a['scopes']), source_count=len(d['contributions']), block_count=len(t['blocks']),
        native_symbol_count=sum(len(scope['symbols']) for scope in a['scopes']),
        native_parameter_count=sum(len(scope['varnames']) for scope in a['scopes']))
    actual = document['input']
    if set(actual) - set(values):
        raise ValueError('unrecognized material input field during registration')
    _same(actual, {key: values[key] for key in actual}, 'material input digest/status/count differs from selected parents')


def _add_counts(total, rows):
    if len(total) != len(rows):
        raise ValueError('material rule-count denominator differs')
    for accumulated, row in zip(total, rows):
        if row['rule'] != accumulated['rule'] or set(row) != set(accumulated):
            raise ValueError('material rule-count fields/order differ')
        for key in row:
            if key != 'rule':
                accumulated[key] += row[key]


def _inventory(artifact, stored):
    if artifact == 'source_symbols':
        keys = ('stage', 'units', 'scopes', 'symbols', 'status_counts', 'authority', 'ast_join',
                'complete_lexical_scopes', 'later_stages_verified', 'whole_program_complete')
        return dict({key: stored[key] for key in keys}, schema='scar.source-symbol-inventory',
                    schema_version=1, scope='DECLARED_MODEL_SOURCE_UNITS')
    return _OWNERS[artifact]._inventory(stored, stored['catalog'])


def _preflight_targets(root, manifest, stages):
    owned = {d['path'] for d in _artifacts(manifest)}
    for item in stages:
        present = [item.artifact in unit['artifacts'] for unit in manifest['units']]
        files = (*item.descriptors, *([item.catalog] if item.catalog else []))
        if item.artifact in manifest or any(present):
            if not all(present):
                raise ValueError('registration conflicts with a partially registered stage')
            _same(manifest.get(item.artifact), item.inventory, 'registration conflicts with an existing inventory')
            for unit, descriptor in zip(manifest['units'], item.descriptors):
                _same(unit['artifacts'][item.artifact], descriptor, 'registration conflicts with an existing sidecar')
            for descriptor in files:
                _Fragments(root).read(descriptor)
        elif any(d['path'] in owned or (root / d['path']).exists() for d in files):
            raise ValueError('registration target catalog/sidecar conflicts with an existing artifact')


def _check_accepted_row(row, unit, source, documents, limits):
    f0, f1, f2 = source
    b, c, d, q, a, t, s = (documents[key] for key in frontend_check._ORDER)
    statuses = {name: doc['status'] for name, doc in zip(('F1', 'F2', *frontend_check._ORDER), (f1, f2, b, c, d, q, a, t, s))}
    fronts = {name: doc['frontiers'] for name, doc in zip(('F1', 'F2', *frontend_check._ORDER), (f1, f2, b, c, d, q, a, t, s)) if doc.get('frontiers')}
    errors = {name: doc['error'] for name, doc in zip(('F1', 'F2', *frontend_check._ORDER), (f1, f2, b, c, d, q, a, t, s)) if doc.get('error') is not None}
    counts = dict(ports=len(b['ports']), sources=len(d['contributions']), raw_events=len(s['contributions']),
        implicit=len(q['implicit']), conflicts=len(q['conflicts']))
    for key, value in dict(statuses=statuses, frontiers=fronts, upstream_errors=errors, input_counts=counts).items():
        _same(row.get(key), value, 'historical composition row differs from actual inputs: ' + key)
    only = s['status'] == 'SOURCE_ONLY_MODE'
    if row['source_only'] is not only or row['status'] != ('SOURCE_ONLY' if only else 'VERIFIED'):
        raise ValueError('historical source-only disposition differs from its material')
    expected = dict(ports=len(b['ports']), sources=len(d['contributions']), raw_events=len(s['contributions']),
        slots=len(s['slots']), facts=len(s['facts']), transforms=len(s['transforms']),
        native_symbols=sum(len(scope['symbols']) for scope in a['scopes']),
        parameters=sum(len(scope['varnames']) for scope in a['scopes']), implicit=len(q['implicit']),
        conflicts=len(q['conflicts']))
    for key, value in expected.items():
        _same(row[key], value, 'historical composition row denominator differs: ' + key)
    if row['implicit_matches'] + row['implicit_omissions'] != row['implicit']:
        raise ValueError('historical implicit disposition counts do not close')
    for key, doc in (('max_tokens', f1), ('max_nodes', f2)):
        if doc[key] > limits[key]:
            raise ValueError('source material budget exceeds its composition witness')
    for artifact, doc in documents.items():
        current_limits = ({key: doc['limits'][name] for key, name in S._LIMIT_KEYS.items()}
            if artifact == 'compiler_symbols' else {key: doc[key] for key in doc if key.startswith('max_')})
        if any(key not in limits or value > limits[key] for key, value in current_limits.items()):
            raise ValueError('material budget exceeds its composition witness')


def prepare_registration(model_root, manifest, *, acceptance, acceptance_sha256,
                         verifications: dict[str, Path], out) -> RegistrationPlan:
    """Read and pin a proof footprint; never rerun any semantic derivation."""
    root, out = Path(model_root).absolute(), Path(out).absolute()
    if (root.resolve() != root or out.resolve() != out or out.is_relative_to(root)
            or out.exists() and (not out.is_dir() or any(out.iterdir()))
            or type(verifications) is not dict or set(verifications) != set(_ARTIFACTS)
            or type(acceptance_sha256) is not str or re.fullmatch('[0-9a-f]{64}', acceptance_sha256) is None):
        raise ValueError('registration requires canonical independent paths, all seven reports and a pinned F3-D digest')
    actual = loads((root / 'manifest.json').read_bytes())
    _same(manifest, actual, 'registration caller manifest differs from current model')
    basis = source_input_basis(manifest['units'])
    if len({u['key'] for u in basis}) != len(basis):
        raise ValueError('registration requires unique source unit identities')
    source_descriptors = tuple(descriptor for unit in basis for descriptor in unit['artifacts'].values())
    source_pins = _stamps(root, source_descriptors)
    apath, accepted, araw, apins = _read_report(acceptance)
    if sha256(araw).hexdigest() != acceptance_sha256:
        raise ValueError('F3-D acceptance digest differs from the caller-pinned witness')
    if (accepted.get('schema') != 'scar.frontend-check' or accepted.get('schema_version') != 1
            or type(accepted.get('schema_version')) is not int or accepted.get('stage') != 'F3-D'
            or accepted.get('input_scope') != 'DECLARED_MODEL_SOURCE_UNITS'
            or accepted.get('units') != len(basis) or type(accepted.get('units')) is not int
            or accepted.get('canonical_model_published') is not False
            or accepted.get('target_executed') is not False or accepted.get('bytecode_generated') is not False
            or accepted.get('runtime_binding') != 'NOT_OBSERVED'
            or accepted.get('runtime_local_layout') != 'NOT_CLAIMED'
            or accepted.get('conflicts') != 0 or type(accepted.get('conflicts')) is not int
            or any(accepted.get(key) is not True for key in ('complete_for_declared_units',
                'manifest_unchanged', 'input_stores_unchanged', 'original_model_artifacts_unchanged',
                'consumed_artifacts_unchanged', 'original_units_and_endpoints_unchanged'))):
        raise ValueError('F3-D witness has an unsupported scope or incomplete accepted boundary')
    context = source_symbols.compiler_hash_context()
    if accepted.get('compiler_hash_context') != context:
        raise ValueError('registration compiler hash context differs; use the accepted analysis seed')
    implementation = accepted.get('implementation', {})
    current_implementation = frontend_check._implementation_receipts()
    if set(implementation) != set(current_implementation) or any(
            implementation[key].get('sha256') != value['sha256'] for key, value in current_implementation.items()):
        raise ValueError('accepted composition implementation differs from current code')
    if type(accepted.get('input_stores')) is not dict or set(accepted['input_stores']) != set(_ARTIFACTS):
        raise ValueError('F3-D witness must seal exactly seven input stores')
    from scar.analysis.frontend_bindings import frontend_binding_contract
    contract = frontend_binding_contract()
    _same(accepted.get('frontend_binding_contract'), contract, 'historical composition contract differs from current rules')
    if accepted.get('frontend_binding_contract_sha256') != sha256(_json(contract)).hexdigest():
        raise ValueError('historical composition contract digest differs')
    accepted_rows = accepted.get('results')
    if (type(accepted_rows) is not list or len(accepted_rows) != len(basis)
            or accepted.get('counter_scope') != 'VERIFIED_COMPOSITION_UNITS'
            or any(row.get('unit') != unit['key'] or row.get('path') != unit['path']
                or row.get('status') not in ('VERIFIED', 'SOURCE_ONLY') for unit, row in zip(basis, accepted_rows))):
        raise ValueError('historical accepted unit/path/status scope differs')
    _same(accepted.get('status_counts'), dict(Counter(row['status'] for row in accepted_rows)), 'historical accepted status counts differ')
    limits = accepted.get('limits')
    if (type(limits) is not dict or set(limits) != set(frontend_check._DEFAULTS)
            or any(type(v) is not int or v < 0 for v in limits.values())):
        raise ValueError('historical composition limit domain differs')
    rule_counts = Counter()
    for row in accepted_rows:
        if (any(type(row.get(k)) is not int or row[k] < 0 for k in frontend_check._COUNTS)
                or type(row.get('source_only')) is not bool or type(row.get('rule_counts')) is not dict
                or any(type(k) is not str or type(v) is not int or v < 0 for k, v in row['rule_counts'].items())):
            raise ValueError('historical composition row counter schema differs')
        rule_counts.update(row['rule_counts'])
    for key in frontend_check._COUNTS:
        _same(accepted.get(key), sum(row[key] for row in accepted_rows), 'historical composition total differs: ' + key)
    _same(accepted.get('rule_counts'), dict(rule_counts), 'historical composition rule counters differ')
    catalogs = _catalogs()
    stages = []
    by_artifact = {}
    for artifact in _ARTIFACTS:
        seal = accepted['input_stores'][artifact]
        if seal.get('receipt_kind') != 'RESULT_JSON' or seal.get('units') != len(basis):
            raise ValueError('F3-D input-store witness lacks its original result/unit scope')
        store_root, stored, raw = read_material_manifest(seal['root'], out)
        if store_root.is_relative_to(out) or sha256(raw).hexdigest() != seal.get('receipt_sha256'):
            raise ValueError('accepted material result differs from its F3-D seal')
        expected_basis = [{**unit, 'artifacts': {**unit['artifacts'], **{
            parent: by_artifact[parent].descriptors[index] for parent in _PARENTS[artifact]}}}
            for index, unit in enumerate(basis)]
        _same(stored.get('basis'), expected_basis, 'material basis differs from the original sources/selected parents')
        rows = stored['results']
        if len(rows) != len(basis) or any(row['unit'] != unit['key'] or
                row['artifact']['path'] != 'units/' + unit['key'] + '/' + artifact + '.json.gz'
                for row, unit in zip(rows, basis)):
            raise ValueError('material unit/path order differs from its source scope')
        descriptors = tuple(row['artifact'] for row in rows)
        catalog = stored.get('catalog')
        if (catalog['sha256'] if catalog else None) != seal.get('catalog_file_sha256') or \
                stored.get('catalog_sha256') != seal.get('catalog_sha256'):
            raise ValueError('material shared catalog differs from its F3-D witness')
        if artifact != 'source_symbols':
            _OWNERS[artifact]._catalog_at(store_root, catalog, catalogs[artifact])
        elif catalog is not None:
            raise ValueError('F3-A does not own a synthesized catalog')
        pins = pin_material_store(store_root, (*descriptors, *([catalog] if catalog else [])), raw)
        vpath, verified, vraw, vpins = _read_report(verifications[artifact])
        if out in vpath.parents or out == vpath or out in apath.parents or out == apath:
            raise ValueError('registration output cannot contain its proof input')
        _fresh_summary(artifact, stored, verified, rows, stored.get('rule_counts'), stored.get('catalog_sha256'), store_root, raw)
        item = StageInput(artifact, store_root, stored, raw, pins, catalog, descriptors,
            _inventory(artifact, stored), vpath, vraw, vpins)
        stages.append(item)
        by_artifact[artifact] = item
    _preflight_targets(root, manifest, stages)
    all_rows = {key: [] for key in _ARTIFACTS}
    b_counts = [dict(rule=i, **dict.fromkeys(B._COUNT_FIELDS, 0)) for i in range(484)]
    c_counts = [dict(rule=i, **dict.fromkeys(C._COUNT_FIELDS, 0)) for i in range(484)]
    for index, unit in enumerate(basis):
        reader = _Fragments(root)
        original = reader.read(unit['artifacts']['source'])
        source = tuple(reader.read(unit['artifacts'][key]) for key in ('source_bytes', 'source_tokens', 'source_syntax'))
        f0, f1, f2 = source
        if not _matches(unit, original, f0, _source_envelope(unit, original)):
            raise ValueError('registration requires matching original F0 bytes/source text')
        documents = {item.artifact: _Fragments(item.root).read(item.descriptors[index]) for item in stages}
        typed = {key: decode(_TYPES[key], doc) for key, doc in documents.items()}
        native = typed['source_symbols']
        if native.status == 'CAPTURED':
            source_symbols._validate_graph(native.scopes)
        profiles = _profiles(f0, native)
        digests = {name + '_document_sha256': _digest(doc) for name, doc in zip(('f0', 'f1', 'f2'), source)}
        used_parents = {parent for parents in _PARENTS.values() for parent in parents}
        digests.update({_DOC_NAMES[key] + '_document_sha256': _digest(documents[key]) for key in used_parents})
        for artifact, document in documents.items():
            _same(document['profile'], encode(profiles[artifact]), 'material profile/code/ABI/hash context differs from current policy')
            _check_inputs(document, source, digests, unit=unit, documents=documents)
        order = frontend_check._ORDER
        upstream, qrow, srow = frontend_check._rows(unit, f1, f2,
            [documents[key] for key in order], [by_artifact[key].descriptors[index] for key in order])
        b, bc, c, cc, d, a, t = upstream
        for artifact, row in zip(_ARTIFACTS, (a, b, c, d, qrow, t, srow)):
            all_rows[artifact].append(row)
        _check_accepted_row(accepted_rows[index], unit, source, documents, limits)
        _add_counts(b_counts, bc)
        _add_counts(c_counts, cc)
    for item in stages:
        counts = b_counts if item.artifact == 'source_roles' else c_counts if item.artifact == 'source_contexts' else None
        digest = item.stored.get('catalog_sha256')
        _same(item.stored['results'], all_rows[item.artifact], 'material row differs from its decoded DTO facts')
        _summary(item.artifact, item.stored, all_rows[item.artifact], counts, digest)
        _fresh_summary(item.artifact, item.stored, loads(item.verification_raw), all_rows[item.artifact], counts, digest, item.root, item.raw)
    plan = RegistrationPlan(root, basis, source_descriptors, source_pins, apath, araw,
                            apins, acceptance_sha256, tuple(stages), out)
    finish_check(plan)
    return plan


def finish_check(plan: RegistrationPlan):
    """Recheck retained inputs; registration may only add derived artifacts."""
    current = loads((plan.model_root / 'manifest.json').read_bytes())
    _same(source_input_basis(current['units']), plan.model_basis, 'source prerequisite basis changed during registration')
    if _stamps(plan.model_root, plan.source_descriptors) != plan.source_pins:
        raise ValueError('source prerequisite files changed during registration')
    for path, raw, pins in ((plan.acceptance_path, plan.acceptance_raw, plan.acceptance_pins),
            *((item.verification_path, item.verification_raw, item.verification_pins) for item in plan.stages)):
        if (path.resolve() != path or path.is_symlink()
                or _stamps(path.parent, ({'path': path.name},)) != pins or path.read_bytes() != raw):
            raise ValueError('historical verification witness changed during registration')
    for item in plan.stages:
        check_material_store(item.root, (*item.descriptors, *([item.catalog] if item.catalog else [])), item.raw, item.pins)


__all__ = ['StageInput', 'RegistrationPlan', 'prepare_registration', 'finish_check']
