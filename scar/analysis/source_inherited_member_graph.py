"""Store conditional inherited-member contexts and shared source body plans.

Base queries and descriptor paths keep their original local indices. Source
plans remain shared; neither a selected declaration nor a stored body plan
proves runtime class, MRO, dispatch, activation or current namespace contents.
"""
import argparse
from collections import Counter
from dataclasses import replace
from hashlib import sha256
import json
from pathlib import Path
import time

from scar.analysis.source_constructor_members import ConstructorMemberParents, project_member_bodies
from scar.analysis.source_constructor_contexts import constructor_context_inputs
from scar.analysis.source_declared_contexts import expand_contexts
from scar.analysis.source_inherited_members import InheritedMemberResolver
from scar.analysis.source_reference_slice import ReferenceSlicer
from scar.analysis.source_world_returns import _table_ref
from scar.analysis.source_symbol_variants import _table
from scar.analysis.normal_output import write_table
from scar.analysis.source_stage import _durable_bytes, _durable_mkdir
from scar.analysis.source_template_links import _json
from scar.ir.program import declared_contexts as D, source_constructor_contexts as C
from scar.ir.program import source_class_bases as B, source_inherited_members as I
from scar.ir.program import source_constructor_members as X, source_value_flow as V, source_productions as P
from scar.ir.program.source_body_expansion import SharedBodyReference
from scar.ir.record_codec import decode, encode


SCHEMA = 'scar.source-inherited-member-contexts'
SEMANTICS = 'CONDITIONAL_SOURCE_BASE_PATHS_AND_BODY_PLANS_NOT_RUNTIME_MRO_DISPATCH_OR_ACTIVATION'
INHERITED_LIMITS = dict(max_classes=256, max_depth=32, max_states=4000)
NO_PROOF = ('loops_unrolled', 'runtime_class_proven', 'runtime_bases_proven', 'mro_proven',
    'runtime_dispatch_proven', 'runtime_activation_proven', 'current_namespace_versions_proven',
    'target_executed', 'first_stage_complete')
CLASSES = dict(class_roots=C.ConstructorClassInputRoot, class_frontiers=C.ConstructorClassInputFrontier,
    contexts=D.DeclaredContext, entries=D.DeclaredContextEntry, edges=D.DeclaredContextEdge,
    frontiers=D.ContextFrontier, base_queries=B.ClassBaseGraph, descriptors=I.InheritedDescriptor,
    inheritance_frontiers=I.InheritedMemberFrontier, references=SharedBodyReference,
    context_bodies=X.ContextBodyReference, bodies=V.SourceBodyValueFlow)


def _limits(max_contexts, max_edges):
    if any(type(n) is not int or n < 1 for n in (max_contexts, max_edges)):
        raise ValueError('inherited member contexts require positive context and edge budgets')
    return dict(max_contexts=max_contexts, max_edges=max_edges)


def _parent(path, parents):
    parents = parents if parents is not None else ConstructorMemberParents(path)
    if not isinstance(parents, ConstructorMemberParents) or parents.root != Path(path).absolute():
        raise ValueError('inherited member certified constructor parent differs')
    parents.validate()
    return parents


def _edge_records(graph, inheritance):
    """Check the exact descriptor record selected by each declared edge."""
    records = {row.descriptor: row for row in inheritance.descriptors}
    if len(records) != len(inheritance.descriptors):
        raise ValueError('inherited descriptor alternatives lost their distinct selection records')
    for ordinal, row in enumerate(inheritance.descriptors):
        if InheritedMemberResolver.record_guard(ordinal) not in row.descriptor.conditions:
            raise ValueError('inherited descriptor record selection index differs')
    selected = []
    for edge in graph.edges:
        row = records.get(edge.descriptor)
        if (row is None or row.receiver_class != edge.receiver.source_class
                or not set(row.descriptor.conditions) <= set(edge.conditions)
                or not set(row.descriptor.conditions) <= set(edge.connection.conditions)):
            raise ValueError('declared edge lost its original receiver or inherited lookup conditions')
        selected.append(row)
    return tuple(selected)


def _derive(parents, limits):
    classes = constructor_context_inputs(parents.constructors)
    roots = tuple((root.context, parents.constructors.entries[root.entry].connection,
        _table_ref(parents.root, parents.report['tables']['constructor_entries'],
            'scar.constructor-body-entries', root.entry)) for root in classes.roots)
    resolver = InheritedMemberResolver(ReferenceSlicer(parents.snapshot), **INHERITED_LIMITS)
    graph = expand_contexts(resolver, roots, **limits)
    ids = {context: ordinal for ordinal, context in enumerate(graph.contexts)}
    extra = tuple(D.ContextFrontier(ids[context], call, 'ACTUAL_BOUND_CLASS_MAY_BE_UNRESOLVED_SUBCLASS')
        for context, call in resolver.open_class_receivers)
    graph = replace(graph, frontiers=(*graph.frontiers, *extra))
    inheritance = resolver.graph(); _edge_records(graph, inheritance)
    bodies, mapped = project_member_bodies(parents, graph, resolver.slicer)
    parents.validate()
    return classes, graph, inheritance, bodies, mapped


def _counts(classes, graph, inheritance, bodies, mapped, old_count):
    from scar.analysis.source_constructor_members import _counts as member_counts
    counts = member_counts(classes, graph, bodies, mapped, old_count)
    selected = _edge_records(graph, inheritance)
    counts.update(base_queries=len(inheritance.base_queries),
        base_classes=sum(len(q.declarations) for q in inheritance.base_queries),
        base_slots=sum(len(q.slots) for q in inheritance.base_queries),
        descriptor_alternatives=len(inheritance.descriptors),
        inherited_descriptor_alternatives=sum(bool(row.path) for row in inheritance.descriptors),
        direct_edges=sum(not row.path for row in selected), inherited_edges=sum(bool(row.path) for row in selected),
        max_base_path=max((len(row.path) for row in inheritance.descriptors), default=0),
        inheritance_frontiers=len(inheritance.frontiers),
        inheritance_frontier_reasons=dict(Counter(row.reason for row in inheritance.frontiers)))
    return counts


def _pins():
    from scar.analysis import source_constructor_members, source_inherited_members, source_class_bases
    from scar.analysis import source_namespace_references, source_address_paths, source_reference_slice
    from scar.analysis import source_function_connections, source_field_interfaces, source_graph_material
    from scar.analysis import source_value_flow, source_world_material, normal_output
    from scar.ir.program import source_namespace_references as N, source_address_paths as A
    from scar.ir.program import normal_links as F, normal_targets as T, normal_graph as G
    from scar.ir.program import source_body_expansion as E, source_template_links as L, providers as R
    from scar.ir import record_codec
    pins = dict(producer=sha256(Path(__file__).read_bytes()).hexdigest())
    pins.update({name: sha256(Path(module.__file__).read_bytes()).hexdigest() for name, module in (
        ('inherited', source_inherited_members), ('inherited_types', I),
        ('bases', source_class_bases), ('base_types', B),
        ('namespaces', source_namespace_references), ('namespace_types', N),
        ('addresses', source_address_paths), ('address_types', A),
        ('references', source_reference_slice), ('connections', source_function_connections),
        ('interface_adapter', source_field_interfaces), ('materials', source_graph_material),
        ('source_materials', source_world_material), ('fact_types', F), ('target_types', T), ('graph_types', G),
        ('template_types', L), ('provider_types', R), ('shared_body_types', E),
        ('output', normal_output), ('codec', record_codec), ('production_types', P))})
    pins.update({'constructor_'+name: value for name, value in source_constructor_members._pins().items()})
    pins.update({'value_'+name: value for name, value in source_value_flow._pins().items()})
    return pins


def _records(classes, graph, inheritance, mapped):
    return dict(class_roots=classes.roots, class_frontiers=classes.frontiers,
        **{name: getattr(graph, name) for name in ('contexts', 'entries', 'edges', 'frontiers')},
        base_queries=inheritance.base_queries, descriptors=inheritance.descriptors,
        inheritance_frontiers=inheritance.frontiers, context_bodies=mapped)


def _references(parents, root, receipt, bodies):
    return (*parents.base.graph.references, *(SharedBodyReference(body.source_function,
        _table_ref(root, receipt, 'scar.source-value-flow-bodies', ordinal))
        for ordinal, body in enumerate(bodies)))


def build_inherited_members(path, out, *, parents=None, max_contexts=256, max_edges=4096):
    started = time.monotonic(); pins = _pins(); out = Path(out).absolute()
    if out.exists(): raise ValueError('fresh inherited member output required')
    parents = _parent(path, parents); limits = _limits(max_contexts, max_edges)
    classes, graph, inheritance, bodies, mapped = _derive(parents, limits)
    parents.validate()
    if pins != _pins(): raise ValueError('inherited member rules changed during derivation')
    old_count = len(parents.base.bodies); additional = bodies[old_count:]
    _durable_mkdir(out); body_table = write_table(out/'bodies.jsonl.gz', additional)
    records = _records(classes, graph, inheritance, mapped)
    records['references'] = _references(parents, out, body_table, additional)
    tables = dict(bodies=body_table, **{name: write_table(out/(name+'.jsonl.gz'), rows)
        for name, rows in records.items()})
    report = dict(schema=SCHEMA, schema_version=1,
        status='CONDITIONAL_INHERITED_SOURCE_MEMBER_CONTEXTS_AND_SHARED_BODIES', semantics=SEMANTICS,
        calls=str(parents.root), parent=encode(parents.artifact), pins=pins, limits=limits,
        inherited_limits=dict(INHERITED_LIMITS), tables=tables,
        counts=_counts(classes, graph, inheritance, bodies, mapped, old_count),
        parent_entry_world_ports_retained=True, source_body_plans_are_conditional=True,
        **{name: False for name in NO_PROOF}, seconds=time.monotonic()-started)
    _durable_bytes(out/'result.json', _json(report), replace=False)
    return report


def read_inherited_members(path, *, parents=None):
    path = Path(path).absolute(); raw = (path/'result.json').read_bytes(); report = json.loads(raw)
    if ((report['schema'], report['schema_version']) != (SCHEMA, 1) or report['pins'] != _pins()
            or report['semantics'] != SEMANTICS or report['inherited_limits'] != INHERITED_LIMITS):
        raise ValueError('inherited member producer, semantics or lookup budgets differ')
    if set(report['limits']) != {'max_contexts', 'max_edges'}:
        raise ValueError('inherited member context budgets differ')
    limits = _limits(**report['limits']); parents = _parent(report['calls'], parents)
    if report['parent'] != encode(parents.artifact): raise ValueError('inherited member parent differs')
    if set(report['tables']) != set(CLASSES): raise ValueError('inherited member table set differs')
    rows = {name: tuple(decode(cls, wire, record_tags=P.PRODUCTION_RECORD_TAGS)
        for wire in _table(path, report['tables'][name])) for name, cls in CLASSES.items()}
    classes = C.ConstructorClassInputGraph(rows['class_roots'], rows['class_frontiers'])
    graph = D.DeclaredContextGraph(**{name: rows[name] for name in ('contexts', 'entries', 'edges', 'frontiers')})
    inheritance = I.InheritedMemberGraph(rows['base_queries'], rows['descriptors'], rows['inheritance_frontiers'])
    bodies = (*parents.base.bodies, *rows['bodies']); old_count = len(parents.base.bodies)
    if (rows['references'] != _references(parents, path, report['tables']['bodies'], rows['bodies'])
            or (classes, graph, inheritance, bodies, rows['context_bodies']) != _derive(parents, limits)
            or _counts(classes, graph, inheritance, bodies, rows['context_bodies'], old_count) != report['counts']):
        raise ValueError('inherited paths, receiver/signature contexts or shared source bodies differ')
    if (any(report[name] is not False for name in NO_PROOF)
            or report['parent_entry_world_ports_retained'] is not True
            or report['source_body_plans_are_conditional'] is not True):
        raise ValueError('inherited source graph cannot grant runtime or current namespace authority')
    parents.validate()
    if report['pins'] != _pins(): raise ValueError('inherited member rules changed during verification')
    if raw != (path/'result.json').read_bytes(): raise ValueError('inherited member graph changed during verification')
    return report, rows


def main():
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument('--calls'); parser.add_argument('--out'); parser.add_argument('--read')
    parser.add_argument('--max-contexts', type=int, default=256)
    parser.add_argument('--max-edges', type=int, default=4096)
    args = parser.parse_args()
    if args.read: report, _ = read_inherited_members(args.read)
    else:
        if not args.calls or not args.out: parser.error('--calls and --out required')
        report = build_inherited_members(args.calls, args.out,
            max_contexts=args.max_contexts, max_edges=args.max_edges)
    print(json.dumps(dict(status=report['status'], counts=report['counts'], seconds=report['seconds'])), flush=True)


if __name__ == '__main__':
    main()
