"""Connect constructor class inputs to guarded member bodies and source plans.

Definitions/regions remain shared. Compatible instance inputs do not prove an
exact runtime class, a namespace version, a selected descriptor or activation.
"""
import argparse
from collections import Counter, defaultdict, deque
from dataclasses import replace
from hashlib import sha256
import json
from pathlib import Path
import time

from scar.analysis.source_call_context_graph import CallContextParents, read_call_context_graph
from scar.analysis.source_constructor_contexts import constructor_context_inputs
from scar.analysis.source_declared_contexts import DeclaredResolver, expand_contexts
from scar.analysis.source_reference_slice import ReferenceSlicer
from scar.analysis.source_graph_material import source_graph_material
from scar.analysis.source_value_flow import project_value_flow, _artifact
from scar.analysis.source_world_returns import _table_ref
from scar.analysis.normal_output import write_table
from scar.analysis.source_symbol_variants import _table
from scar.analysis.source_stage import _durable_bytes, _durable_mkdir
from scar.analysis.source_template_links import _json
from scar.ir.program import declared_contexts as D, normal_targets as T, source_productions as P
from scar.ir.program import source_constructor_contexts as C, source_constructor_interfaces as I
from scar.ir.program import source_constructor_members as X, source_value_flow as V
from scar.ir.program.source_body_expansion import SharedBodyReference
from scar.ir.record_codec import encode, decode


def _guards(*groups):
    return tuple(dict.fromkeys(value for group in groups for value in group))


class ConstructorMemberResolver(DeclaredResolver):
    """Treat INSTANCE inputs as compatible classes, preserving open subclasses."""

    def __init__(self, slicer):
        super().__init__(slicer); self.open_class_receivers = []

    def bind(self, context, unit, call, access, receiver, descriptor):
        result = super().bind(context, unit, call, access, receiver, descriptor)
        if result is None: return None
        connection, inputs, proofs, conditions = result
        extra = ('PARENT_CONSTRUCTOR_CLASS_CONTEXT_AND_LOOKUP_WORLD_SELECTED',
            'CURRENT_CLASS_MEMBER_VERSION_SELECTS_RECORDED_SOURCE_WRITE',
            'CUSTOM_ATTRIBUTE_PROTOCOL_SELECTS_RECORDED_DESCRIPTOR')
        if receiver.kind is D.ClassValueKind.INSTANCE and descriptor.kind is D.DescriptorKind.FUNCTION:
            extra = (*extra, 'INSTANCE_NAMESPACE_DOES_NOT_SHADOW_SELECTED_FUNCTION_DESCRIPTOR')
        if receiver.kind is D.ClassValueKind.INSTANCE and descriptor.kind is D.DescriptorKind.CLASSMETHOD:
            # __new__ may return a subclass. Even an inherited classmethod
            # receives that actual subclass, not necessarily the requested one.
            extra = (*extra, 'BOUND_CLASS_RECEIVER_EQUALS_RECORDED_SOURCE_CLASS')
            ordinal = next(i for i, row in enumerate(unit.calls) if row == call)
            item = context, self.slicer.fact(unit, 'calls', ordinal)
            if item not in self.open_class_receivers: self.open_class_receivers.append(item)
        return replace(connection, conditions=_guards(connection.conditions, extra)), inputs, proofs, _guards(conditions, extra)


class ConstructorMemberParents:
    def __init__(self, path):
        started = time.monotonic(); self.root = Path(path).absolute()
        header = json.loads((self.root/'result.json').read_bytes())
        self.base = CallContextParents(header['body_expansion'])
        self.report, self.graph = read_call_context_graph(self.root, parents=self.base)
        self.raw = (self.root/'result.json').read_bytes()
        if json.loads(self.raw) != self.report: raise ValueError('constructor member parent changed')
        self.artifact = _artifact(self.root/'result.json', self.report['schema'])
        self.snapshot = self.base.base.values.snapshot
        self.constructors = I.ConstructorInterfaceGraph(**{name: self.graph['constructor_'+name]
            for name in ('sites', 'steps', 'entries', 'frontiers')})
        self.validate(); self.certification_seconds = time.monotonic()-started

    def validate(self):
        from scar.analysis.source_call_context_graph import _pins
        if self.raw != (self.root/'result.json').read_bytes() or self.report['pins'] != _pins():
            raise ValueError('constructor member original report or context rules changed')
        for receipt in self.report['tables'].values():
            raw = (self.root/receipt['path']).read_bytes()
            if len(raw) != receipt['bytes'] or sha256(raw).hexdigest() != receipt['sha256']:
                raise ValueError('constructor member original context table changed')
        self.base.validate()


def member_contexts(parents, limits):
    classes = constructor_context_inputs(parents.constructors)
    roots = tuple((root.context, parents.constructors.entries[root.entry].connection,
        _table_ref(parents.root, parents.report['tables']['constructor_entries'],
            'scar.constructor-body-entries', root.entry)) for root in classes.roots)
    resolver = ConstructorMemberResolver(ReferenceSlicer(parents.snapshot))
    graph = expand_contexts(resolver, roots, **limits)
    ids = {context: i for i, context in enumerate(graph.contexts)}
    extra = tuple(D.ContextFrontier(ids[context], call, 'ACTUAL_BOUND_CLASS_MAY_BE_UNRESOLVED_SUBCLASS')
        for context, call in resolver.open_class_receivers)
    graph = replace(graph, frontiers=(*graph.frontiers, *extra))
    parents.validate()
    return classes, graph, resolver.slicer


def _preload(material, roots):
    """One domain scan per source-unit batch, before projecting any body."""
    children = defaultdict(list)
    for link in material.graph.links: children[link.caller].append(link.callee)
    seen = set(roots); pending = deque(roots); keys = []
    while pending:
        key = pending.popleft(); keys.append(key)
        for child in children.get(key, ()):
            if child not in seen: seen.add(child); pending.append(child)
    material.plans(keys)


def project_member_bodies(parents, graph, slicer):
    registry = list(parents.base.bodies); ids = {body.source_function: i for i, body in enumerate(registry)}
    entered = {entry.target for entry in graph.entries if entry.connection.activation is T.FunctionActivation.NORMAL}
    entered.update(edge.target for edge in graph.edges if edge.connection.activation is T.FunctionActivation.NORMAL)
    needed = defaultdict(dict); materials = {}
    for index, context in enumerate(graph.contexts):
        if index not in entered or context.source_callable in ids: continue
        needed[context.body.unit][context.source_callable] = context
    for unit, contexts in needed.items():
        material = source_graph_material(parents.snapshot.catalog, unit); materials[unit] = material
        _preload(material, tuple(dict.fromkeys(context.body.template for context in contexts.values())))
        for point, context in contexts.items():
            ids[point] = len(registry)
            registry.append(project_value_flow(material, point, context.body))
    mapped = tuple(X.ContextBodyReference(i, ids[context.source_callable])
        for i, context in enumerate(graph.contexts) if i in entered)
    for material in materials.values(): material.validate_parents()
    parents.validate()
    return tuple(registry), mapped


def _derive(parents, limits):
    classes, graph, slicer = member_contexts(parents, limits)
    bodies, mapped = project_member_bodies(parents, graph, slicer)
    return classes, graph, bodies, mapped


def _counts(classes, graph, bodies, mapped, old_count):
    new = bodies[old_count:]
    return dict(class_roots=len(classes.roots), class_frontiers=len(classes.frontiers),
        contexts=len(graph.contexts), entries=len(graph.entries), edges=len(graph.edges),
        frontiers=len(graph.frontiers), frontier_reasons=dict(Counter(f.reason for f in graph.frontiers)),
        descriptor_kinds=dict(Counter(e.descriptor.kind.value for e in graph.edges)),
        recursive_edges=sum(e.caller == e.target for e in graph.edges), body_contexts=len(mapped),
        shared_bodies=len(bodies), reused_parent_bodies=old_count, new_bodies=len(new),
        new_operations=sum(len(b.operations) for b in new), new_calls=sum(len(b.calls) for b in new),
        new_edges=sum(len(b.edges) for b in new))


def _pins():
    from scar.analysis import source_declared_contexts, source_constructor_contexts, source_graph_material, source_value_flow
    return {name: sha256(Path(path).read_bytes()).hexdigest() for name, path in (
        ('producer', __file__), ('types', X.__file__), ('declared_types', D.__file__), ('class_types', C.__file__),
        ('declared', source_declared_contexts.__file__), ('class_inputs', source_constructor_contexts.__file__),
        ('materials', source_graph_material.__file__), ('values', source_value_flow.__file__))}


def _parent(path, parents):
    parents = parents if parents is not None else ConstructorMemberParents(path)
    if parents.root != Path(path).absolute(): raise ValueError('constructor member certified parent path differs')
    parents.validate(); return parents


def build_constructor_members(path, out, *, parents=None, max_contexts=256, max_edges=4096):
    started = time.monotonic(); pins = _pins(); out = Path(out).absolute()
    if out.exists(): raise ValueError('fresh constructor member output required')
    parents = _parent(path, parents); limits = dict(max_contexts=max_contexts, max_edges=max_edges)
    classes, graph, bodies, mapped = _derive(parents, limits)
    if pins != _pins(): raise ValueError('constructor member rules changed')
    _durable_mkdir(out); old_count = len(parents.base.bodies)
    body_table = write_table(out/'bodies.jsonl.gz', bodies[old_count:])
    references = (*parents.base.graph.references, *(SharedBodyReference(body.source_function,
        _table_ref(out, body_table, 'scar.source-value-flow-bodies', i))
        for i, body in enumerate(bodies[old_count:])))
    records = dict(class_roots=classes.roots, class_frontiers=classes.frontiers,
        **{name: getattr(graph, name) for name in ('contexts', 'entries', 'edges', 'frontiers')},
        references=references, context_bodies=mapped)
    tables = dict(bodies=body_table, **{name: write_table(out/(name+'.jsonl.gz'), rows) for name, rows in records.items()})
    report = dict(schema='scar.constructor-member-contexts', schema_version=1,
        status='CONSTRUCTOR_CLASS_INPUTS_TO_DECLARED_MEMBER_BODIES', calls=str(parents.root),
        parent=encode(parents.artifact), pins=pins, limits=limits, tables=tables,
        counts=_counts(classes, graph, bodies, mapped, old_count), loops_unrolled=False,
        runtime_class_proven=False, mro_proven=False, runtime_dispatch_proven=False,
        target_executed=False, first_stage_complete=False, seconds=time.monotonic()-started)
    _durable_bytes(out/'result.json', _json(report), replace=False); return report


def read_constructor_members(path, *, parents=None):
    path = Path(path).absolute(); raw = (path/'result.json').read_bytes(); report = json.loads(raw)
    if (report['schema'], report['schema_version']) != ('scar.constructor-member-contexts', 1) or report['pins'] != _pins():
        raise ValueError('constructor member producer differs')
    parents = _parent(report['calls'], parents)
    if report['parent'] != encode(parents.artifact): raise ValueError('constructor member parent differs')
    types = dict(class_roots=C.ConstructorClassInputRoot, class_frontiers=C.ConstructorClassInputFrontier,
        contexts=D.DeclaredContext, entries=D.DeclaredContextEntry, edges=D.DeclaredContextEdge,
        frontiers=D.ContextFrontier, references=SharedBodyReference, context_bodies=X.ContextBodyReference,
        bodies=V.SourceBodyValueFlow)
    rows = {name: tuple(decode(cls, wire, record_tags=P.PRODUCTION_RECORD_TAGS)
        for wire in _table(path, report['tables'][name])) for name, cls in types.items()}
    classes = C.ConstructorClassInputGraph(rows['class_roots'], rows['class_frontiers'])
    graph = D.DeclaredContextGraph(**{name: rows[name] for name in ('contexts', 'entries', 'edges', 'frontiers')})
    bodies = (*parents.base.bodies, *rows['bodies']); old_count = len(parents.base.bodies)
    expected = (*parents.base.graph.references, *(SharedBodyReference(body.source_function,
        _table_ref(path, report['tables']['bodies'], 'scar.source-value-flow-bodies', i))
        for i, body in enumerate(rows['bodies'])))
    if (rows['references'] != expected or (classes, graph, bodies, rows['context_bodies']) != _derive(parents, report['limits'])
            or _counts(classes, graph, bodies, rows['context_bodies'], old_count) != report['counts']):
        raise ValueError('constructor member contexts, body references or source connections differ')
    if any(report[k] is not False for k in ('loops_unrolled', 'runtime_class_proven', 'mro_proven',
            'runtime_dispatch_proven', 'target_executed', 'first_stage_complete')):
        raise ValueError('constructor member graph cannot grant runtime or exact type authority')
    parents.validate()
    if (path/'result.json').read_bytes() != raw: raise ValueError('constructor member graph changed during verification')
    return report, rows


def main():
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument('--calls'); parser.add_argument('--out'); parser.add_argument('--read')
    parser.add_argument('--max-contexts', type=int, default=256); parser.add_argument('--max-edges', type=int, default=4096)
    args = parser.parse_args()
    if args.read: report, _ = read_constructor_members(args.read)
    else:
        if not args.calls or not args.out: parser.error('--calls and --out required')
        report = build_constructor_members(args.calls, args.out, max_contexts=args.max_contexts, max_edges=args.max_edges)
    print(json.dumps(dict(status=report['status'], counts=report['counts'], seconds=report['seconds'])), flush=True)


if __name__ == '__main__': main()
