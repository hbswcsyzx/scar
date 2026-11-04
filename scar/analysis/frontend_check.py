"""Read-only F3 composition checks over independently owned material stores."""
from __future__ import annotations

import argparse
from collections import Counter
from concurrent.futures import ProcessPoolExecutor
from hashlib import sha256
import multiprocessing
from pathlib import Path
import time

from scar.analysis import compiler_symbol_materials as _s, source_binding_materials as _q
from scar.analysis.source_materials import _stamps
from scar.analysis.source_stage import SourceStage
from scar.analysis.source_store import (
    REQUIRED_SOURCE_ARTIFACTS, source_input_basis, read_source_prerequisites,
    check_replay_limit, read_material_manifest, pin_material_store,
)
from scar.analysis.static_program import _json
from scar.analysis.static_query import _Fragments

_d, _t = _s._d, _s._t
_DEFAULTS = {**_s._DEFAULTS, **_q._OWN_DEFAULTS}
_COUNTS = ('ports', 'sources', 'raw_events', 'slots', 'facts', 'transforms',
    'native_symbols', 'parameters', 'implicit', 'implicit_matches', 'implicit_omissions',
    'synthetic_implicit', 'conflicts')
_ORDER = ('source_roles', 'source_contexts', 'source_declarations', 'source_bindings',
          'source_symbols', 'compiler_topology', 'compiler_symbols')


class _ScalarPolicy:
    """The existing checker protocol, adapted only for Q/S scalar summaries."""
    def __init__(self, owner):
        self.owner = owner
        self._catalog_at = owner._catalog_at
        self._inventory = owner._inventory

    def _check_summary(self, document, rows, counts, digest):
        return self.owner._check_summary(document, rows, digest)

    def _report(self, rows, counts, *, schema, limits, jobs, catalog_sha):
        return self.owner._report(rows, schema=schema, limits=limits, jobs=jobs, digest=catalog_sha)


def _scalar_input(stage, artifact, directory, basis, catalog, owner):
    policy = _ScalarPolicy(owner)
    if directory is None:
        return _d._input(stage, artifact, None, basis, catalog, policy)
    root, stored, raw = read_material_manifest(directory, stage.out)
    owner._check_summary(stored, stored['results'], catalog['content_sha256'])
    descriptors = [row['artifact'] for row in stored['results']]
    if (_json(stored.get('basis')) != _json(basis) or len(descriptors) != len(basis)
            or any(row['unit'] != unit['key']
                or row['artifact']['path'] != 'units/' + unit['key'] + '/' + artifact + '.json.gz'
                for row, unit in zip(stored['results'], basis))):
        raise ValueError(artifact + ' original basis/unit/path order differs from selected inputs')
    descriptor = stored['catalog']
    pins = pin_material_store(root, [descriptor, *descriptors], raw)
    owner._catalog_at(root, descriptor, catalog)
    return dict(root=root, stored=stored, raw=raw, pins=pins, catalog=descriptor,
        catalog_pins=_stamps(root, (descriptor,)), descriptors=descriptors,
        policy=policy, catalog_sha=catalog['content_sha256'], artifact=artifact)


def _rows(unit, f1, f2, documents, descriptors):
    b, c, d, q, a, t, s = documents
    upstream = _s._upstream_rows(unit, f1, f2, b, c, d, a, t,
        [descriptors[i] for i in (0, 1, 2, 4, 5)])
    common = dict(unit=unit['key'], upstream_f1_status=f1['status'], upstream_f2_status=f2['status'],
        upstream_f3b_status=b['status'], upstream_c1_status=c['status'], upstream_c2a_status=d['status'])
    q_row = dict(common, artifact=descriptors[3], status=q['status'],
        **{key: len(q[key]) for key in _q._TABLES},
        steps=sum(len(plan['steps']) for plan in q['plans']), search_steps=q['search_steps'],
        **{key: q[key] for key in _q._OWN_DEFAULTS}, frontiers=q['frontiers'])
    s_row = dict(common, artifact=descriptors[6], status=s['status'],
        **{key: len(s[key]) for key in _s._TABLES}, steps=s['steps'],
        **{key: s['limits'][name] for key, name in _s._LIMIT_KEYS.items()}, frontiers=s['frontiers'],
        upstream_f3a_status=a['status'], upstream_topology_status=t['status'])
    return upstream, q_row, s_row


def _implementation_receipts():
    from scar.analysis import frontend_bindings
    return {name: dict(path=str(path), sha256=sha256(path.read_bytes()).hexdigest())
        for name, path in (('query', Path(frontend_bindings.__file__)), ('driver', Path(__file__)))}


def _check_unit(task):
    from scar.analysis.frontend_bindings import FrontendError, read_frontend_bindings
    from scar.analysis.source_symbols import compiler_hash_context
    model, unit, inputs, limits, expected_context, implementation = task
    if compiler_hash_context() != expected_context:
        raise ValueError('frontend worker hash context differs; start analysis with fixed PYTHONHASHSEED')
    if _implementation_receipts() != implementation:
        raise ValueError('frontend worker implementation differs from its parent')
    f0, f1, f2 = read_source_prerequisites(_Fragments(model), unit, limits['max_nodes'], limits['max_tokens'])
    documents = [_Fragments(root).read(descriptor) for root, descriptor in inputs]
    b, c, d, q, a, t, s = documents
    for doc, keys, label in ((b, ('max_ports', 'max_slots'), 'F3-B'),
            (c, _d._c1._OWN_LIMITS, 'F3-C1'), (d, _d._OWN_LIMITS, 'F3-C2a'),
            (q, _q._OWN_DEFAULTS, 'F3-C2b'), (a, ('max_scopes', 'max_symbols'), 'F3-A'),
            (t, _t._OWN_DEFAULTS, 'F3-C3T')):
        for key in keys:
            check_replay_limit(doc, key, limits[key], label)
    for key, name in _s._LIMIT_KEYS.items():
        check_replay_limit(s['limits'], name, limits[key], 'F3-C3S')
    statuses = {name: doc['status'] for name, doc in zip(('F1', 'F2', *_ORDER), (f1, f2, *documents))}
    frontiers = {name: doc.get('frontiers', []) for name, doc in
                 zip(('F1', 'F2', *_ORDER), (f1, f2, *documents)) if doc.get('frontiers')}
    input_counts = dict(ports=len(b['ports']), sources=len(d['contributions']),
        raw_events=len(s['contributions']), implicit=len(q['implicit']), conflicts=len(q['conflicts']))
    errors = {name: doc['error'] for name, doc in
              zip(('F1', 'F2', *_ORDER), (f1, f2, *documents)) if doc.get('error') is not None}
    try:
        view = read_frontend_bindings(f0, f1, f2, b, c, d, q, a, t, s)
    except FrontendError as error:
        if error.code != 'UPSTREAM_NOT_ACCEPTED':
            raise
        row = dict(unit=unit['key'], path=unit['path'], status='UPSTREAM_NOT_READY',
            statuses=statuses, frontiers=frontiers, input_counts=input_counts, upstream_errors=errors, error=dict(code=error.code, detail=str(error)),
            source_only=False, rule_counts={}, **dict.fromkeys(_COUNTS, 0))
    else:
        counts = view.verify()  # The factory's immutable verification summary is cached.
        if set(counts) != {*_COUNTS, 'source_only', 'rule_counts'}:
            raise ValueError('frontend verifier returned an incomplete count schema')
        if (any(type(counts[key]) is not int or counts[key] < 0 for key in _COUNTS)
                or type(counts['source_only']) is not bool or type(counts['rule_counts']) is not dict
                or any(type(key) is not str or type(value) is not int or value < 0
                    for key, value in counts['rule_counts'].items())):
            raise ValueError('frontend verifier returned invalid counters')
        row = dict(unit=unit['key'], path=unit['path'],
            status='SOURCE_ONLY' if counts['source_only'] else 'VERIFIED',
            statuses=statuses, frontiers=frontiers, input_counts=input_counts, upstream_errors=errors, **counts)
    return row, *_rows(unit, f1, f2, documents, [item[1] for item in inputs])


def check_frontend(model, out, *, roles_materials=None, contexts_materials=None,
        declarations_materials=None, bindings_materials=None, symbols_materials=None,
        topology_materials=None, compiler_symbols_materials=None, jobs=1,
        max_nodes=1_000_000, max_tokens=2_000_000):
    from scar.analysis.frontend_bindings import frontend_binding_contract
    from scar.analysis.compiler_symbols import compiler_symbol_catalog
    from scar.analysis.compiler_topology import compiler_topology_catalog
    from scar.analysis.source_bindings import source_binding_catalog
    from scar.analysis.source_contexts import source_context_catalog
    from scar.analysis.source_declarations import source_declaration_catalog
    from scar.analysis.source_roles import source_role_catalog
    from scar.analysis.source_symbols import compiler_hash_context
    if (type(jobs) is not int or not 1 <= jobs <= 32
            or any(type(value) is not int or value < 0 for value in (max_nodes, max_tokens))):
        raise ValueError('frontend check requires bounded jobs and nonnegative replay budgets')
    limits = {**_DEFAULTS, 'max_nodes': max_nodes, 'max_tokens': max_tokens}
    started = time.monotonic()
    expected_context = compiler_hash_context()
    implementation = _implementation_receipts()
    contract = frontend_binding_contract()
    # verify=True admits a read-only model; no staging, capture or publication.
    with SourceStage(model, out, artifact='compiler_symbols', verify=True,
            consumes=(*REQUIRED_SOURCE_ARTIFACTS, *_ORDER)) as stage:
        model_pins = _stamps(stage.root, stage.prior)
        base = source_input_basis(stage.manifest['units'])
        bc, cc = source_role_catalog(), source_context_catalog()
        b = _d._input(stage, 'source_roles', roles_materials, base, bc, _d._b)
        b_basis = _d._with_artifacts(base, 'source_roles', b['descriptors'])
        c = _d._input(stage, 'source_contexts', contexts_materials, b_basis, cc, _d._c1)
        c_basis = _d._with_artifacts(b_basis, 'source_contexts', c['descriptors'])
        d = _q._declaration_input(stage, declarations_materials, c_basis, source_declaration_catalog())
        q_basis = _d._with_artifacts(c_basis, 'source_declarations', d['descriptors'])
        q = _scalar_input(stage, 'source_bindings', bindings_materials, q_basis, source_binding_catalog(), _q)
        a = _t._symbols_input(stage, symbols_materials, base)
        a_basis = _d._with_artifacts(c_basis, 'source_symbols', a['descriptors'])
        t = _s._topology_input(stage, topology_materials, a_basis, compiler_topology_catalog())
        s_basis = _d._with_artifacts(_d._with_artifacts(a_basis, 'source_declarations', d['descriptors']),
                                    'compiler_topology', t['descriptors'])
        s = _scalar_input(stage, 'compiler_symbols', compiler_symbols_materials, s_basis,
                          compiler_symbol_catalog(), _s)
        handles = (b, c, d, q, a, t, s)
        input_stores = {name: dict(root=str(handle['root']),
            receipt_kind='RESULT_JSON' if handle['stored'] is not None else 'CANONICAL_MANIFEST',
            receipt_sha256=sha256(handle['raw'] if handle['stored'] is not None else stage.original).hexdigest(),
            catalog_sha256=handle.get('catalog_sha'),
            catalog_file_sha256=handle.get('catalog', {}).get('sha256'),
            units=len(handle['descriptors'])) for name, handle in zip(_ORDER, handles)}
        tasks = [(stage.root, unit, [(item['root'], item['descriptors'][i]) for item in handles],
                  limits, expected_context, implementation) for i, unit in enumerate(base)]
        rows = []
        stored_rows = [[] for _ in handles]
        b_counts = [dict(rule=rule['rule'], **dict.fromkeys(_d._b._COUNT_FIELDS, 0)) for rule in bc['rules']]
        c_counts = [dict(rule=rule['rule'], **dict.fromkeys(_d._c1._COUNT_FIELDS, 0)) for rule in cc['rules']]

        def accept(packet):
            row, upstream, q_row, s_row = packet
            b_row, b_current, c_row, c_current, d_row, a_row, t_row = upstream
            rows.append(row)
            for target, current in zip(stored_rows, (b_row, c_row, d_row, q_row, a_row, t_row, s_row)):
                target.append(current)
            for total, current, fields in ((b_counts, b_current, _d._b._COUNT_FIELDS),
                                           (c_counts, c_current, _d._c1._COUNT_FIELDS)):
                if len(total) != len(current):
                    raise ValueError('frontend prerequisite rule denominator differs')
                for left, right in zip(total, current):
                    if left['rule'] != right['rule']:
                        raise ValueError('frontend prerequisite rule order differs')
                    for key in fields:
                        left[key] += right[key]

        if jobs == 1:
            for packet in map(_check_unit, tasks):
                accept(packet)
        else:
            with ProcessPoolExecutor(max_workers=jobs, mp_context=multiprocessing.get_context('spawn')) as pool:
                for packet in pool.map(_check_unit, tasks, chunksize=1):
                    accept(packet)
        for i in (0, 1, 2, 3, 5, 6):
            counts = b_counts if i == 0 else c_counts if i == 1 else None
            _d._check_input(stage, handles[i], stored_rows[i], counts, jobs)
        _t._check_symbols(stage, a, stored_rows[4], jobs)
        if _stamps(stage.root, stage.prior) != model_pins:
            raise ValueError('frontend original model artifacts changed during verification')
        if _implementation_receipts() != implementation:
            raise ValueError('frontend implementation changed during verification')
        rule_counts = Counter()
        for row in rows:
            rule_counts.update(row['rule_counts'])
        report = dict(schema='scar.frontend-check', schema_version=1, stage='F3-D',
            input_scope='DECLARED_MODEL_SOURCE_UNITS', counter_scope='VERIFIED_COMPOSITION_UNITS', units=len(rows), results=rows,
            status_counts=dict(Counter(row['status'] for row in rows)),
            complete_for_declared_units=all(row['status'] in ('VERIFIED', 'SOURCE_ONLY') for row in rows),
            **{key: sum(row[key] for row in rows) for key in _COUNTS}, rule_counts=dict(rule_counts),
            jobs=jobs, limits=limits, compiler_hash_context=expected_context, input_stores=input_stores,
            implementation=implementation, frontend_binding_contract=contract,
            frontend_binding_contract_sha256=sha256(_json(contract)).hexdigest(),
            seconds=time.monotonic() - started, input_stores_unchanged=True,
            original_model_artifacts_unchanged=True, canonical_model_published=False,
            new_materials_written=False, target_executed=False, bytecode_generated=False,
            authority='SOURCE_COMPILER_CORRESPONDENCE', runtime_binding='NOT_OBSERVED',
            runtime_local_layout='NOT_CLAIMED', later_stages_verified=False, whole_program_complete=False)
        return stage.finish(report)


def main(argv=None):
    parser = argparse.ArgumentParser(description='Verify original F3 source/compiler composition without publishing graph copies')
    parser.add_argument('--model', required=True)
    parser.add_argument('--out', required=True)
    for name in ('roles', 'contexts', 'declarations', 'bindings', 'symbols', 'topology', 'compiler-symbols'):
        parser.add_argument('--' + name + '-materials')
    parser.add_argument('--jobs', type=int, default=1)
    parser.add_argument('--max-nodes', type=int, default=1_000_000)
    parser.add_argument('--max-tokens', type=int, default=2_000_000)
    args = vars(parser.parse_args(argv))
    report = check_frontend(**args)
    print(_json(report).decode('ascii'))
    return 0 if report['complete_for_declared_units'] else 1


if __name__ == '__main__':
    raise SystemExit(main())


__all__ = ['check_frontend', 'main']
