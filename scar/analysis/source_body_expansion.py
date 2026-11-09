"""Expand ordinary/compiled source call interfaces into shared body graphs.

Only source function declarations are expanded. Native contracts, activation
selection, captures, effects and dynamic dispatch retain their own boundaries.
"""
import argparse
from collections import Counter
from hashlib import sha256
import json
from pathlib import Path
import time

from scar.analysis.source_value_interface_graph import ValueInterfaceParents, read_value_interface_graph
from scar.analysis.source_graph_material import source_graph_material
from scar.analysis.source_reference_slice import ReferenceSlicer, source_port
from scar.analysis.source_value_flow import project_value_flow, data_reach, _artifact
from scar.analysis.source_world_returns import _table_ref
from scar.analysis.normal_output import write_table
from scar.analysis.source_stage import _durable_bytes, _durable_mkdir
from scar.analysis.source_symbol_variants import _table
from scar.analysis.source_template_links import _json
from scar.ir.program import source_body_expansion as X, source_value_flow as V
from scar.ir.program import reference_consumers as R, normal_targets as T, source_productions as P, normal_graph as G
from scar.ir.program.providers import ProviderFactReference
from scar.ir.record_codec import encode, decode


class ExpansionParents:
    """Certify the source/compiled catalog and interface parent once per session."""

    def __init__(self, path):
        started = time.monotonic(); self.root = Path(path).absolute()
        report = json.loads((self.root/'result.json').read_bytes())
        self.values = ValueInterfaceParents(report['values'])
        self.report, self.graph = read_value_interface_graph(self.root, parents=self.values)
        self.raw = (self.root/'result.json').read_bytes()
        if json.loads(self.raw) != self.report: raise ValueError('body expansion parent changed')
        self.artifact = _artifact(self.root/'result.json', self.report['schema'])
        self.validate()
        self.certification_seconds = time.monotonic()-started

    def validate(self):
        from scar.analysis.source_value_interface_graph import _pins
        if self.raw != (self.root/'result.json').read_bytes() or self.report['pins'] != _pins():
            raise ValueError('body expansion original interface parent or rules changed')
        # Parent tables are small. Check their exact compressed receipts on
        # every reuse instead of re-running the whole ancestor derivation.
        for receipt in self.report['tables'].values():
            raw = (self.root/receipt['path']).read_bytes()
            if len(raw) != receipt['bytes'] or sha256(raw).hexdigest() != receipt['sha256']:
                raise ValueError('body expansion interface table changed')
        self.values.validate()


def expand_bodies(parents):
    """Return a shared registry and entry queries; never unroll a body or loop."""
    source = parents.values
    slicer = ReferenceSlicer(source.snapshot)
    registry = list(source.bodies); ids = {b.source_function: i for i, b in enumerate(registry)}
    entries = []; frontiers = []; materials = {}
    for ordinal, binding in enumerate(parents.graph.bindings):
        if binding.activation is not T.FunctionActivation.NORMAL:
            frontiers.append(X.BodyExpansionFrontier(ordinal, 'DEFERRED_BODY_CREATION_IS_NOT_BODY_ENTRY')); continue
        if binding.argument.kind is not T.RouteKind.ARGUMENT:
            frontiers.append(X.BodyExpansionFrontier(ordinal, 'NON_ARGUMENT_ROUTE_NOT_USED_AS_DATA_BODY_ENTRY')); continue
        unit, local = slicer.local(binding.source_callable)
        fn = next(f for f in unit.functions if f.value == local)
        if (binding.body != T.Body(unit.unit, fn.template, fn.body)
                or binding.argument.formal not in tuple(source_port(unit, p) for p in fn.formals[1:-1])
                or binding.state.formal != source_port(unit, fn.formals[-1])):
            raise ValueError('expanded body parameters or world differ from original source interface')
        if binding.source_callable not in ids:
            if unit.unit not in materials:
                materials[unit.unit] = source_graph_material(source.catalog, unit.unit)
            body = project_value_flow(materials[unit.unit], binding.source_callable, binding.body)
            ids[binding.source_callable] = len(registry); registry.append(body)
        entries.append(R.ConsumerBodyEntry(ordinal, ids[binding.source_callable], binding.argument.formal,
            (*binding.conditions, 'SOURCE_BODY_EXPANSION_IS_NOT_SELECTED_RUNTIME_ACTIVATION')))
    # Multiple arguments/callers share one body. Their entry conditions remain
    # on entries; data_reach remains an unbalanced syntactic may approximation.
    reaches = tuple(data_reach(registry[e.body], e.formal, i, e.body,
        source.catalog.fact_store.load(e.formal.unit)) for i, e in enumerate(entries))
    for material in materials.values(): material.validate_parents()
    parents.validate()
    return tuple(registry), tuple(entries), reaches, tuple(frontiers)


def _pins():
    from scar.analysis import source_graph_material as materials, source_value_flow, source_value_interface_graph
    return {name: sha256(Path(path).read_bytes()).hexdigest() for name, path in (
        ('producer', __file__), ('types', X.__file__), ('materials', materials.__file__),
        ('values', source_value_flow.__file__), ('interfaces', source_value_interface_graph.__file__))}


def _counts(registry, entries, reaches, frontiers, parent_count, catalog):
    new = registry[parent_count:]
    return dict(shared_bodies=len(registry), reused_parent_bodies=parent_count, new_bodies=len(new),
        compiled_bodies=sum(b.body.unit in catalog.fact_store.original_source_units for b in new),
        entries=len(entries), frontiers=len(frontiers),
        new_operations=sum(len(b.operations) for b in new), new_edges=sum(len(b.edges) for b in new),
        new_calls=sum(len(b.calls) for b in new), new_backedges=sum(
            e.transition is G.Transition.BACKEDGE for b in new for e in b.edges),
        dependent_call_inputs=sum(len(r.call_inputs) for r in reaches),
        frontier_reasons=dict(Counter(f.reason for f in frontiers)))


def _parent(path, parents):
    parents = parents if parents is not None else ExpansionParents(path)
    if parents.root != Path(path).absolute(): raise ValueError('body expansion certified parent path differs')
    parents.validate()
    return parents


def build_body_expansion(path, out, *, parents=None):
    started = time.monotonic(); pins = _pins(); out = Path(out).absolute()
    if out.exists(): raise ValueError('fresh body expansion output required')
    parents = _parent(path, parents)
    registry, entries, reaches, frontiers = expand_bodies(parents)
    parent_count = len(parents.values.bodies)
    if pins != _pins(): raise ValueError('body expansion producer changed')
    _durable_mkdir(out)
    bodies = write_table(out/'bodies.jsonl.gz', registry[parent_count:])
    parent_root = parents.values.root
    references = tuple(X.SharedBodyReference(body.source_function,
        _table_ref(parent_root, parents.values.report['tables']['bodies'], 'scar.source-value-flow-bodies', i)
        if i < parent_count else _table_ref(out, bodies, 'scar.source-value-flow-bodies', i-parent_count))
        for i, body in enumerate(registry))
    tables = dict(bodies=bodies, **{name: write_table(out/(name+'.jsonl.gz'), records) for name, records in (
        ('references', references), ('entries', entries), ('reaches', reaches), ('frontiers', frontiers))})
    report = dict(schema='scar.source-body-expansion', schema_version=1,
        status='SHARED_SOURCE_AND_COMPILED_BODY_EXPANSION', interfaces=str(parents.root),
        parent=encode(parents.artifact), pins=pins, tables=tables,
        counts=_counts(registry, entries, reaches, frontiers, parent_count, parents.values.catalog),
        source_bodies_shared=True, loops_unrolled=False, runtime_activation_proven=False,
        content_versions_proven=False, target_executed=False, first_stage_complete=False,
        seconds=time.monotonic()-started)
    _durable_bytes(out/'result.json', _json(report), replace=False)
    return report


def read_body_expansion(path, *, parents=None):
    path = Path(path).absolute(); raw = (path/'result.json').read_bytes(); report = json.loads(raw)
    if (report['schema'], report['schema_version']) != ('scar.source-body-expansion', 1) or report['pins'] != _pins():
        raise ValueError('body expansion producer differs')
    parents = _parent(report['interfaces'], parents)
    if report['parent'] != encode(parents.artifact): raise ValueError('body expansion parent receipt differs')
    classes = dict(bodies=V.SourceBodyValueFlow, references=X.SharedBodyReference, entries=R.ConsumerBodyEntry,
        reaches=V.SourceDataReach, frontiers=X.BodyExpansionFrontier)
    graph = X.SourceBodyExpansion(**{name: tuple(decode(cls, row, record_tags=P.PRODUCTION_RECORD_TAGS)
        for row in _table(path, report['tables'][name])) for name, cls in classes.items()})
    parent_count = len(parents.values.bodies); registry = (*parents.values.bodies, *graph.bodies)
    expected = tuple(X.SharedBodyReference(body.source_function,
        _table_ref(parents.values.root, parents.values.report['tables']['bodies'], 'scar.source-value-flow-bodies', i)
        if i < parent_count else _table_ref(path, report['tables']['bodies'], 'scar.source-value-flow-bodies', i-parent_count))
        for i, body in enumerate(registry))
    if (graph.references != expected
            or (registry, graph.entries, graph.reaches, graph.frontiers) != expand_bodies(parents)
            or _counts(registry, graph.entries, graph.reaches, graph.frontiers, parent_count,
                parents.values.catalog) != report['counts']):
        raise ValueError('body expansion differs from original shared source plans or parameter entries')
    if (report['source_bodies_shared'] is not True or any(report[k] is not False for k in (
            'loops_unrolled', 'runtime_activation_proven', 'content_versions_proven', 'target_executed', 'first_stage_complete'))):
        raise ValueError('body expansion cannot grant runtime or state-version authority')
    parents.validate()
    if (path/'result.json').read_bytes() != raw: raise ValueError('body expansion changed during verification')
    return report, graph


def main():
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument('--interfaces'); parser.add_argument('--out'); parser.add_argument('--read')
    args = parser.parse_args()
    if args.read: report, _ = read_body_expansion(args.read)
    else:
        if not args.interfaces or not args.out: parser.error('--interfaces and --out required')
        report = build_body_expansion(args.interfaces, args.out)
    print(json.dumps(dict(status=report['status'], counts=report['counts'], seconds=report['seconds'])), flush=True)


if __name__ == '__main__': main()
