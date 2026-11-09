"""Qualify declared lexical reference edges with matched control GEN/KILL.

This is a separate NORMAL_SUCCESS branch, not an overwrite of the source
declarations. Missing exception/resume paths and opaque reference sources
remain explicit frontiers. Shared loops are solved to a may fixed point;
neither source-table order nor a runtime trace selects the binding version.
"""
import argparse
from collections import Counter
from concurrent.futures import ProcessPoolExecutor
from dataclasses import replace
from hashlib import sha256
import json
import multiprocessing
from pathlib import Path
import sys
import time

from scar.analysis.source_declared_calls import DeclaredCallStore, _NoTargets, _check_targets, _folder, _flat_tables
from scar.analysis.source_graph_material import source_graph_material
from scar.analysis.source_name_access_anchors import anchor_name_accesses, _bindings
from scar.analysis.source_name_definitions import reaching_name_definitions
from scar.analysis.source_namespace_references import NamespaceReferenceResolver, _Query
from scar.analysis.source_reference_slice import source_port
from scar.analysis.source_symbol_variants import _table
from scar.analysis.source_value_flow import _artifact, project_value_flow
from scar.analysis.normal_output import write_table
from scar.analysis.source_stage import _durable_bytes, _durable_mkdir
from scar.analysis.source_template_links import _json
from scar.ir.program import source_control_namespaces as R, source_name_access_anchors as A
from scar.ir.program import source_name_definitions as D, source_namespace_references as N
from scar.ir.program import normal_links as F, normal_targets as T, source_productions as P
from scar.ir.record_codec import decode, encode


SCHEMA = 'scar.source-control-namespaces'
NO_PROOF = ('source_scopes_activated', 'runtime_dispatch_proven', 'current_binding_versions_proven',
    'tensor_content_versions_proven', 'all_exception_paths_connected', 'source_relations_rederived',
    'loops_unrolled', 'target_executed', 'first_stage_complete')
_WORKER = None


class ControlNamespaceResolver(NamespaceReferenceResolver):
    def __init__(self, snapshot, *, catalog=None, **limits):
        super().__init__(snapshot)
        self.catalog = catalog if catalog is not None else getattr(snapshot, 'catalog', snapshot)
        self.limits = limits
        self.materials = {}; self.anchors = []; self.anchor_ids = {}; self.bindings = {}
        self.tracks = []; self.track_ids = {}; self.flows = {}; self.filters = []; self.filter_ids = {}

    def _material(self, unit):
        if unit not in self.materials:
            material = source_graph_material(self.catalog, unit)
            self.materials[unit] = material
            self.anchor_ids[unit] = len(self.anchors)
            self.anchors.append(anchor_name_accesses(self.snapshot, unit, material=material))
            self.bindings[unit] = _bindings(material, {})[0]
        return self.materials[unit], self.anchors[self.anchor_ids[unit]], self.bindings[unit]

    def filter(self, unit, ordinal):
        fact = self.slicer.fact(unit, 'names', ordinal)
        if fact in self.filter_ids: return self.filter_ids[fact]
        record = unit.names[ordinal]; owners = self.unit(unit.unit)[6][ordinal]
        scope = next(iter(owners)) if len(owners) == 1 else None
        track = None; accesses = (); states = (); writers = (); open_kinds = (); applied = False
        reason = 'LEXICAL_READ_SOURCE_SCOPE_NOT_UNIQUE'
        if scope is not None:
            functions = [f for f in unit.functions if f.body_scope is not None and f.body_scope.owner == scope]
            reason = 'LEXICAL_READ_SOURCE_FUNCTION_NOT_UNIQUE'
            if len(functions) == 1:
                function = functions[0]; material, anchors, bindings = self._material(unit.unit)
                slot = bindings.bindings[record.namespace.owner]
                # Namespace.owner is a C2 BindingSlot index, not CodeScope.ordinal.
                reason = 'CAPTURE_OR_NONLOCAL_SLOT_REQUIRES_SELECTED_CREATION_FRAME'
                if slot.domain == 'LOCAL_BINDING' and slot.owner == function.environment.scope:
                    key = source_port(unit, function.value), record.namespace
                    if key not in self.track_ids:
                        if key[0] not in self.flows:
                            self.flows[key[0]] = project_value_flow(material, key[0],
                                T.Body(unit.unit, function.template, function.body))
                        self.track_ids[key] = len(self.tracks)
                        self.tracks.append(reaching_name_definitions(self.snapshot, *key,
                            material=material, anchor_graph=anchors, flow=self.flows[key[0]], **self.limits))
                    track = self.track_ids[key]; graph = self.tracks[track]
                    accesses = tuple(sorted({a.access for a in anchors.anchors if a.fact == fact and a.scope == scope}))
                    observed = [r for r in graph.reads if r.access in accesses]
                    states = tuple(sorted({r.state for r in observed}))
                    ids = sorted({d for r in observed for d in r.definitions})
                    selected = [graph.definitions[d] for d in ids]
                    writers = tuple(dict.fromkeys(e for d in selected
                        if d.kind in (D.NameDefinitionKind.FORMAL, D.NameDefinitionKind.WRITE)
                        for e in (d.evidence[:1])))
                    open_kinds = tuple(sorted({d.kind for d in selected if d.kind not in
                        (D.NameDefinitionKind.FORMAL, D.NameDefinitionKind.WRITE)}, key=lambda kind: kind.value))
                    anchored = not any(f.fact == fact for f in anchors.frontiers)
                    covered = accesses and {r.access for r in observed} == set(accesses)
                    # A missing WRITE/FORMAL anchor can omit a reaching source
                    # even when this READ and the retained CFG are complete.
                    # Only these two explicitly scoped unknown branches may
                    # coexist with exclusion in the normal control view.
                    covered_track = all(f.reason in {
                        'APPLICATION_EXCEPTION_PATHS_OUTSIDE_NORMAL_SUCCESS_VIEW',
                        'OPAQUE_CALLBACK_AND_CAPTURE_SLOT_IDENTITY_REMAIN_OPEN',
                    } for f in graph.frontiers)
                    applied = bool(anchored and covered and covered_track and ids
                        and graph.traversal_complete and graph.dataflow_complete)
                    reason = ('NORMAL_CONTROL_MAY_DEFINITIONS_JOINED' if applied else
                        'READ_ANCHOR_OR_RETAINED_CONTROL_DATAFLOW_COVERAGE_OPEN')
        value = R.NameReadFilter(fact, scope, track, accesses, states, writers, open_kinds, applied, reason)
        index = len(self.filters); self.filter_ids[fact] = index; self.filters.append(value)
        return index

    def resolve(self, point, *, max_states=4000, max_selectors=32, query=0):
        worker = _ControlQuery(self, point, max_states, max_selectors)
        reference = worker.run()
        return R.ControlNamespaceQuery(query, point, reference, tuple(sorted(worker.used_filters)), tuple(worker.excluded))


class _ControlQuery(_Query):
    def __init__(self, *args):
        super().__init__(*args); self.used_filters = set(); self.excluded = []

    def _filter(self, state, unit, ordinal):
        index = self.resolver.filter(unit, ordinal); value = self.resolver.filters[index]
        self.used_filters.add(index)
        if not value.applied:
            self.frontier(state, 'LEXICAL_NORMAL_CONTROL_FILTER_OPEN_'+value.reason, (value.read,))
        else:
            for kind in value.open_kinds:
                self.frontier(state, 'LEXICAL_REACHING_'+kind.value+'_SOURCE_OPEN', (value.read,))
            self.frontier(state, 'LEXICAL_EXCEPTION_AND_RESUME_SOURCE_BRANCH_OPEN', (value.read,))
        return index, value

    def edge(self, state, point, selectors, kind, evidence, conditions):
        if kind is N.NamespaceEdgeKind.LEXICAL_WRITE:
            writer, read = evidence
            unit, local = self.resolver.slicer.local(self.states[state].port)
            candidates = [(ordinal, namespace) for namespace, ordinal in self.resolver.unit(unit.unit)[2].get(local, ())
                if self.resolver.slicer.fact(unit, 'names', ordinal) == read]
            if len(candidates) != 1: raise ValueError('lexical edge lost its original read fact')
            index, value = self._filter(state, unit, candidates[0][0])
            if value.applied:
                if writer not in value.writers:
                    self.excluded.append(R.ExcludedNameWriter(state, writer, read, index)); return
                conditions = (*conditions, *R.NORMAL_VIEW)
        super().edge(state, point, selectors, kind, evidence, conditions)

    def run(self):
        result = super().run()
        # A lexical read without a declared writer still needs its unknown
        # entry/delete/opaque branch; do not depend on edge() being called.
        for index, state in enumerate(self.states):
            unit, local = self.resolver.slicer.local(state.port)
            for namespace, ordinal in self.resolver.unit(unit.unit)[2].get(local, ()):
                if namespace.kind is F.NamespaceKind.LEXICAL:
                    self._filter(index, unit, ordinal)
        return replace(result, frontiers=tuple(self.frontiers))


def project_control_namespaces(store, unit, *, frontier=None, **limits):
    original = store.load_unit(unit)
    resolver = ControlNamespaceResolver(store.snapshot, catalog=store.catalog, **limits)
    selected = [i for i, q in enumerate(original.queries)
        if frontier is None or any(f.reason == frontier for f in q.reference.frontiers)]
    queries = tuple(resolver.resolve(original.queries[i].callee, query=i, **store.report['limits']) for i in selected)
    store.validate()
    return _unit(unit, tuple(resolver.anchors), tuple(resolver.tracks), tuple(resolver.filters), queries)


def _unit(unit, anchors, tracks, filters, queries):
    """Intern original function control/operation records once per unit shard."""
    bodies = []; indexes = {}; shared = []
    for track in tracks:
        body = R.NameControlBody(track.source_function, track.function, track.body, track.scope,
            track.control_edges, track.operations)
        if body.source_function not in indexes:
            indexes[body.source_function] = len(bodies); bodies.append(body)
        common = bodies[indexes[body.source_function]]
        if common != body: raise ValueError('one source function has incompatible control body records')
        shared.append(replace(track, control_edges=common.control_edges, operations=common.operations))
    return R.ControlNamespaceUnit(unit, anchors, tuple(bodies), tuple(shared), filters, queries)


def _pins():
    from scar.analysis import source_name_access_anchors, source_name_definitions, source_graph_material, source_value_flow
    from scar.analysis import source_namespace_interfaces, source_world_flow, source_productions
    return dict(producer=sha256(Path(__file__).read_bytes()).hexdigest(), **{
        name: sha256(Path(module.__file__).read_bytes()).hexdigest() for name, module in (
            ('types', R), ('anchors', source_name_access_anchors), ('anchor_types', A),
            ('definitions', source_name_definitions), ('definition_types', D),
            ('materials', source_graph_material), ('value_flow', source_value_flow),
            ('namespace_interfaces', source_namespace_interfaces), ('world_flow', source_world_flow),
            ('productions', source_productions))})


def _counts(graph):
    return dict(queries=len(graph.queries), anchors=len(graph.anchors), tracks=len(graph.tracks),
        shared_bodies=len(graph.bodies), shared_body_operations=sum(len(b.operations) for b in graph.bodies),
        shared_body_control_edges=sum(len(b.control_edges) for b in graph.bodies),
        filters=len(graph.filters), applied_filters=sum(f.applied for f in graph.filters),
        excluded_writer_edges=sum(len(q.excluded) for q in graph.queries),
        namespace_states=sum(len(q.reference.states) for q in graph.queries),
        namespace_edges=sum(len(q.reference.edges) for q in graph.queries),
        control_states=sum(len(g.states) for g in graph.tracks),
        control_transitions=sum(len(g.transitions) for g in graph.tracks),
        definitions=sum(len(g.definitions) for g in graph.tracks),
        backedges=sum(sum(e.transition.value == 'BACKEDGE' for e in g.control_edges) for g in graph.tracks),
        frontier_reasons=dict(Counter(f.reason for q in graph.queries for f in q.reference.frontiers)))


def _track_rows(graph):
    for track in graph.tracks:
        anchor = next(i for i, value in enumerate(graph.anchors) if value is track.anchor_graph)
        body = next(i for i, value in enumerate(graph.bodies) if value.source_function == track.source_function)
        yield R.StoredNameDefinitionTrack(anchor, body, track.namespace, track.definitions, track.states,
            track.transitions, track.reads, track.frontiers, track.traversal_complete, track.dataflow_complete,
            track.conditions, track.loops_unrolled, track.semantics)


def _write_unit(store, unit, out, frontier, limits, pins):
    started = time.monotonic(); graph = project_control_namespaces(store, unit, frontier=frontier, **limits)
    folder = Path(out)/_folder(unit); _durable_mkdir(folder)
    tables = {name: write_table(folder/(name+'.jsonl.gz'), rows) for name, rows in (
        ('anchors', graph.anchors), ('bodies', graph.bodies), ('tracks', _track_rows(graph)),
        ('filters', graph.filters), ('queries', graph.queries))}
    if pins != _pins(): raise ValueError('control name projection rules changed during build')
    store.runtime.clear(); _check_targets()
    return dict(path=_folder(unit), tables=tables, counts=_counts(graph), seconds=time.monotonic()-started)


def _initialize(declared, out, frontier, limits, pins):
    global _WORKER
    sys.meta_path.insert(0, _NoTargets()); _check_targets()
    _WORKER = DeclaredCallStore(declared), out, frontier, limits, pins


def _worker(unit):
    store, out, frontier, limits, pins = _WORKER
    return unit, _write_unit(store, unit, out, frontier, limits, pins)


def _selected(report, units, frontier):
    selected = set(report['shards']) if not units else set(units)
    if not selected <= set(report['shards']): raise ValueError('control names unit is outside declared source selection')
    return tuple(sorted(u for u in selected if frontier is None or
        report['shards'][u]['counts']['frontier_reasons'].get(frontier, 0)))


def _totals(shards):
    counts = Counter(); reasons = Counter()
    for shard in shards.values():
        for key, value in shard['counts'].items():
            if key == 'frontier_reasons': reasons.update(value)
            else: counts[key] += value
    return dict(units=len(shards), **counts, frontier_reasons=dict(reasons))


def build_control_namespaces(declared, out, *, units=(), frontier=None, jobs=4,
        max_states=20000, max_stack=128, max_updates=1000000):
    started = time.monotonic(); pins = _pins(); out = Path(out).absolute()
    if out.exists(): raise ValueError('fresh control namespace output required')
    if type(jobs) is not int or jobs < 1: raise ValueError('control namespace jobs must be positive')
    limits = dict(max_states=max_states, max_stack=max_stack, max_updates=max_updates)
    if any(type(n) is not int or n < 1 for n in limits.values()): raise ValueError('positive control name budgets required')
    store = DeclaredCallStore(declared); selection = _selected(store.report, units, frontier)
    parent = _artifact(store.path/'result.json', store.report['schema']); _durable_mkdir(out)
    if jobs == 1:
        shards = {u: _write_unit(store, u, out, frontier, limits, pins) for u in selection}
    else:
        with ProcessPoolExecutor(max_workers=min(jobs, len(selection) or 1), mp_context=multiprocessing.get_context('spawn'),
                initializer=_initialize, initargs=(str(store.path), str(out), frontier, limits, pins)) as pool:
            shards = dict(pool.map(_worker, selection))
    store.validate()
    if pins != _pins(): raise ValueError('control namespace projection rules changed')
    report = dict(schema=SCHEMA, schema_version=2, declared=str(store.path), parent=encode(parent), pins=pins,
        selection=dict(units=list(units), frontier=frontier), limits=limits, shards=shards, tables=_flat_tables(shards),
        counts=_totals(shards), jobs=jobs, seconds=time.monotonic()-started,
        scope='RECORDED_NORMAL_CONTROL_BRANCH_ONLY_ORIGINAL_DECLARATIONS_RETAINED_IN_PARENT',
        **{name: False for name in NO_PROOF})
    _durable_bytes(out/'result.json', _json(report), replace=False)
    return report


class ControlNamespaceStore:
    def __init__(self, path):
        self.path = Path(path).absolute(); self.raw = (self.path/'result.json').read_bytes(); self.report = r = json.loads(self.raw)
        if (r['schema'], r['schema_version']) != (SCHEMA, 2) or r['pins'] != _pins():
            raise ValueError('control namespace schema or rules differ')
        self.parent = DeclaredCallStore(r['declared'])
        if encode(_artifact(self.parent.path/'result.json', self.parent.report['schema'])) != r['parent']:
            raise ValueError('control namespace declared parent differs')
        if tuple(r['shards']) != _selected(self.parent.report, **r['selection']):
            raise ValueError('control namespace source selection differs')
        if (r['tables'] != _flat_tables(r['shards']) or r['counts'] != _totals(r['shards'])
                or any(r[n] is not False for n in NO_PROOF)
                or r['scope'] != 'RECORDED_NORMAL_CONTROL_BRANCH_ONLY_ORIGINAL_DECLARATIONS_RETAINED_IN_PARENT'):
            raise ValueError('control namespace receipt index, scope or proof status differs')
        for unit, shard in r['shards'].items():
            if shard['path'] != _folder(unit) or set(shard['tables']) != {'anchors', 'bodies', 'tracks', 'filters', 'queries'}:
                raise ValueError('control namespace shard paths or tables differ')
            if any(row['path'] != name+'.jsonl.gz' for name, row in shard['tables'].items()):
                raise ValueError('control namespace table path differs')

    def read_unit(self, unit):
        if self.raw != (self.path/'result.json').read_bytes() or self.report['pins'] != _pins():
            raise ValueError('control namespace report or rules changed')
        shard = self.report['shards'][unit]; folder = self.path/shard['path']; tables = shard['tables']
        def rows(name, cls):
            return tuple(decode(cls, wire, record_tags=P.PRODUCTION_RECORD_TAGS) for wire in _table(folder, tables[name]))
        anchors = rows('anchors', A.NameAccessAnchorGraph); bodies = rows('bodies', R.NameControlBody); tracks = []
        for value in rows('tracks', R.StoredNameDefinitionTrack):
            if not 0 <= value.anchor < len(anchors) or not 0 <= value.body < len(bodies):
                raise ValueError('factored name track body/anchor reference differs')
            body = bodies[value.body]
            tracks.append(D.NameDefinitionGraph(body.source_function, body.function, body.body, body.scope,
                value.namespace, anchors[value.anchor], body.control_edges, body.operations, value.definitions,
                value.states, value.transitions, value.reads, value.frontiers, value.traversal_complete,
                value.dataflow_complete, value.conditions, value.loops_unrolled, value.semantics))
        graph = R.ControlNamespaceUnit(unit, anchors, bodies, tuple(tracks),
            rows('filters', R.NameReadFilter), rows('queries', R.ControlNamespaceQuery))
        expected = project_control_namespaces(self.parent, unit, frontier=self.report['selection']['frontier'], **self.report['limits'])
        if graph != expected or _counts(graph) != shard['counts']:
            raise ValueError('control-qualified source names differ from original control/namespace facts')
        if self.raw != (self.path/'result.json').read_bytes(): raise ValueError('control namespace report changed during read')
        return graph


def main():
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument('--declared'); parser.add_argument('--out'); parser.add_argument('--read')
    parser.add_argument('--unit', action='append', default=[]); parser.add_argument('--frontier')
    parser.add_argument('--jobs', type=int, default=4)
    args = parser.parse_args()
    if args.read:
        if len(args.unit) != 1: parser.error('--read requires one --unit to rederive')
        graph = ControlNamespaceStore(args.read).read_unit(args.unit[0])
        print(json.dumps(dict(status='CONTROL_QUALIFIED_NAMES_REDERIVED', counts=_counts(graph))), flush=True)
    else:
        if not args.declared or not args.out: parser.error('--declared and --out required')
        report = build_control_namespaces(args.declared, args.out, units=args.unit, frontier=args.frontier, jobs=args.jobs)
        print(json.dumps(dict(status='CONTROL_QUALIFIED_NAMES_BUILT', counts=report['counts'], seconds=report['seconds'])), flush=True)


if __name__ == '__main__': main()
