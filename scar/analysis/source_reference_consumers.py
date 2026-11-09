"""Connect tracked source references to original argument/formal interfaces."""
import argparse
from collections import defaultdict, Counter, deque
from hashlib import sha256
import json
from pathlib import Path
import time

from scar.analysis.source_consumer_parents import ConsumerParents
from scar.analysis.source_reference_slice import ReferenceSlicer, source_port
from scar.analysis.source_address_paths import AddressResolver
from scar.analysis.source_world_material import WorldMaterial
from scar.analysis.source_world_flow import project_world_flow
from scar.analysis.source_world_returns import _table_ref
from scar.analysis.normal_output import write_table
from scar.analysis.source_symbol_variants import _table
from scar.analysis.source_template_links import _json
from scar.analysis.source_stage import _durable_bytes, _durable_mkdir
from scar.ir.program import reference_consumers as R, normal_targets as T, normal_links as F, source_productions as P
from scar.ir.program.declared_contexts import DescriptorKind, ClassValueKind
from scar.ir.program.providers import ProviderArtifact
from scar.ir.record_codec import encode, decode


def argument_points(call):
    yield R.ArgumentRole.CALLEE, 0, None, call.callee
    for i, value in enumerate(call.positional): yield R.ArgumentRole.POSITIONAL, i, None, value
    for i, (name, value) in enumerate(call.keywords): yield R.ArgumentRole.KEYWORD, i, name, value
    if call.positional_pack is not None: yield R.ArgumentRole.POSITIONAL_PACK, 0, None, call.positional_pack
    if call.keyword_pack is not None: yield R.ArgumentRole.KEYWORD_PACK, 0, None, call.keyword_pack


def collect_argument_uses(snapshot, graph):
    slicer = ReferenceSlicer(snapshot); uses = []; frontiers = []; original_calls = {}
    for node_index, node in enumerate(graph.nodes):
        if node.tracked_reference is None:
            frontiers.append(R.ConsumerFrontier(node_index, None, None, None, 'NODE_TRACKED_REFERENCE_UNRESOLVED')); continue
        unit, local = slicer.local(node.source_function)
        fn = next(f for f in unit.functions if f.value == local)
        resolver = AddressResolver(snapshot.fact_store, unit, fn.body_scope.owner)
        _, _, incoming, *_ = slicer.unit(unit.unit)
        reads = defaultdict(list)
        for attr_index, access in enumerate(unit.attributes):
            if access.action is F.AttributeAction.GET: reads[access.value].append((attr_index, access))
        for access in node.flow.accesses:
            if access.table != 'calls': continue
            ordinal = int(access.fact.locator.rsplit('/', 1)[1]); call = unit.calls[ordinal]
            if (access.fact != slicer.fact(unit, 'calls', ordinal)
                    or access.world_before != source_port(unit, call.world)
                    or access.world_after != source_port(unit, call.result_world)):
                raise ValueError('consumer input call or world differs from its original source fact')
            points = [(*value, None) for value in argument_points(call)]
            ancestors = {call.callee}; pending = deque((call.callee,))
            while pending:
                for source, _ in incoming.get(pending.popleft(), ()):
                    if source not in ancestors: ancestors.add(source); pending.append(source)
            receiver_index = 0
            for point in sorted(ancestors):
                for attr_index, attribute_row in reads.get(point, ()):
                    points.append((R.ArgumentRole.ATTRIBUTE_RECEIVER, receiver_index, None, attribute_row.receiver,
                        slicer.fact(unit, 'attributes', attr_index)))
                    receiver_index += 1
            for role, position, name, actual, attribute in points:
                point = source_port(unit, actual)
                alternatives = resolver.paths(actual, max_depth=128)
                selected = tuple(p for p in alternatives if p.root == node.tracked_reference and p.frontier is None)
                for p in alternatives:
                    if p.frontier is not None:
                        frontiers.append(R.ConsumerFrontier(node_index, None, point, None, 'ARGUMENT_SOURCE_'+p.frontier))
                if not selected: continue
                conditions = ('PARENT_WORLD_NODE_AND_REFERENCE_PATH_SELECTED',
                    'ARGUMENT_VALUE_IS_NOT_EFFECT_OR_ESCAPE_SUMMARY', 'NO_CONTENT_PRESERVATION_PROOF')
                if attribute is not None:
                    conditions = (*conditions, 'ATTRIBUTE_RECEIVER_BINDING_REQUIRES_SELECTED_DESCRIPTOR')
                use = R.ReferenceArgumentUse(node_index, access.fact, role, position, name, point, selected,
                    any(not p.selectors for p in selected), access.world_before, access.world_after, conditions, attribute)
                original_calls[len(uses)] = unit, ordinal, call
                uses.append(use)
    return tuple(uses), tuple(frontiers), original_calls


def bind_consumer_interface(slicer, use_index, use, call, link, evidence):
    """Match the original signature; keep effect and invocation guards open."""
    if link.source_callable is None or link.body is None:
        return (), 'SOURCE_TARGET_OR_NATIVE_CONTRACT_UNRESOLVED'
    if link.mode in ('SOURCE_CONSTRUCTION', 'SOURCE_INIT', 'SOURCE_NEW'):
        return (), 'CONSTRUCTOR_PROTOCOL_CONSUMER_REMAINS_EXPLICIT'
    provider, local = slicer.local(link.source_callable)
    fn = next((f for f in provider.functions if f.value == local), None)
    if fn is None or link.body != T.Body(provider.unit, fn.template, fn.body):
        return (), 'SOURCE_FUNCTION_BODY_INTERFACE_UNRESOLVED'
    activation = T.FunctionActivation.NORMAL if fn.environment.kind is P.DeferredBodyKind.FUNCTION else T.FunctionActivation.CREATE_DEFERRED_BODY
    formal_world = source_port(provider, fn.formals[-1])
    state = [r for r in link.parameters if r.kind is T.RouteKind.STATE and r.formal == formal_world
        and r.actuals == (use.world_before,)]
    if len(state) != 1: return (), 'CALLEE_WORLD_INPUT_ROUTE_UNRESOLVED'
    state_return = None
    if fn.return_world is not None:
        pair = source_port(provider, fn.return_world), use.world_after
        if pair in link.returns: state_return = pair
    data_return = None
    if fn.returns is not None:
        pair = source_port(provider, fn.returns), link.result
        if pair in link.returns: data_return = pair
    if activation is T.FunctionActivation.NORMAL and state_return is None:
        return (), 'CALLEE_NORMAL_WORLD_RETURN_UNRESOLVED'
    bindings = []
    for route in link.parameters:
        if route.actuals != (use.actual,): continue
        environment = use.role is R.ArgumentRole.CALLEE and route.kind is T.RouteKind.FUNCTION_ENVIRONMENT
        receiver = use.role is R.ArgumentRole.ATTRIBUTE_RECEIVER
        class_dependency = receiver and route.kind is T.RouteKind.CLASS_RECEIVER and link.mode == 'SOURCE_CLASS_METHOD'
        if receiver and not class_dependency:
            bound = link.mode == 'SOURCE_BOUND_METHOD' or (link.argument_packs is not None and link.argument_packs.receiver == use.actual)
            if (not bound or route.kind is not T.RouteKind.ARGUMENT
                    or route.formal != source_port(provider, fn.formals[1])): continue
        elif not environment and not class_dependency and route.kind is not T.RouteKind.ARGUMENT: continue
        allowed = (fn.formals[0],) if environment else fn.formals[1:-1]
        if route.formal not in tuple(source_port(provider, p) for p in allowed):
            raise ValueError('consumer parameter route is not an original source function formal')
        conditions = (*link.conditions, *use.conditions, 'SAME_CALL_SITE_ARGUMENT_BINDING_SELECTED',
            'ARGUMENT_PATH_GUARDS_REQUIRED', 'CALLEE_EFFECTS_AND_ESCAPES_REMAIN_OPEN')
        if activation is not T.FunctionActivation.NORMAL:
            conditions = (*conditions, 'DEFERRED_BODY_CREATION_IS_NOT_BODY_ENTRY')
        if environment: conditions = (*conditions, 'FUNCTION_ENVIRONMENT_ROUTE_NOT_OBJECT_ARGUMENT')
        if class_dependency: conditions = (*conditions, 'CLASS_RECEIVER_IS_TYPE_DEPENDENCY_NOT_REFERENCE_ALIAS')
        bindings.append(R.SourceConsumerBinding(use_index, evidence, link.source_callable, link.body, activation,
            route, state[0], data_return, state_return, conditions))
    reason = 'ATTRIBUTE_RECEIVER_NOT_PASSED_BY_SELECTED_SOURCE_DESCRIPTOR' if use.role is R.ArgumentRole.ATTRIBUTE_RECEIVER else 'ARGUMENT_PACK_OR_PROJECTED_PARAMETER_ROUTE_UNRESOLVED'
    return tuple(bindings), None if bindings else reason


def build_consumers(parents):
    uses, unresolved, original = collect_argument_uses(parents.snapshot, parents.graph)
    slicer = ReferenceSlicer(parents.snapshot); targets = defaultdict(list); bindings = []; frontiers = list(unresolved)
    wanted = {_json(encode(source_port(unit, call.result))) for unit, _, call in original.values()}
    wanted_units = {unit.unit for unit, _, _ in original.values()}
    # A single complete scan serves every selected source call and parameter.
    for ordinal, link, evidence in parents.snapshot.rows('calls', lambda w:w['result']['unit'] in wanted_units
            and _json(w['result']) in wanted, T.CallLink):
        targets[link.result].append((link, evidence, None))
    for ordinal, edge in enumerate(parents.declared_graph.edges):
        matches = [(i, call) for i, (_, _, call) in original.items()
            if uses[i].call == edge.call and parents.graph.nodes[uses[i].node].declared_context == edge.caller]
        for use_index, call in matches:
            caller = original[use_index][0]
            connection = edge.connection
            mode = 'SOURCE_CLASS_METHOD' if edge.descriptor.kind is DescriptorKind.CLASSMETHOD else (
                'SOURCE_BOUND_METHOD' if edge.descriptor.kind is DescriptorKind.FUNCTION and edge.receiver.kind is ClassValueKind.INSTANCE else 'SOURCE_FUNCTION')
            link = T.CallLink(source_port(caller, call.result), source_port(caller, call.callee), connection.source_callable,
                connection.body, mode, None, connection.parameters, connection.returns,
                connection.conditions, argument_packs=connection.argument_packs, projections=connection.projections,
                binding=connection.binding)
            evidence = _table_ref(parents.declared_root, parents.declared_report['tables']['edges'],
                'scar.declared-context-edges', ordinal)
            row = link, evidence, edge.caller
            if row not in targets[link.result]: targets[link.result].append(row)
    for i, use in enumerate(uses):
        unit, _, call = original[i]; result = source_port(unit, call.result); matched = False
        for link, evidence, context in targets.get(result, ()):
            if link.callee != source_port(unit, call.callee): continue
            if context is not None and context != parents.graph.nodes[use.node].declared_context: continue
            matched = True
            records, reason = bind_consumer_interface(slicer, i, use, call, link, evidence)
            bindings.extend(records)
            if reason: frontiers.append(R.ConsumerFrontier(use.node, i, use.actual, evidence, reason))
        if not matched: frontiers.append(R.ConsumerFrontier(use.node, i, use.actual, None, 'CALL_TARGET_INTERFACE_UNRESOLVED'))
    bodies = []; entries = []; body_ids = {}; materials = {}
    for binding_index, binding in enumerate(bindings):
        use = uses[binding.use]
        if binding.activation is not T.FunctionActivation.NORMAL:
            frontiers.append(R.ConsumerFrontier(use.node, binding.use, use.actual, binding.interface,
                'DEFERRED_BODY_CREATION_IS_NOT_BODY_ENTRY')); continue
        if binding.argument.kind is not T.RouteKind.ARGUMENT: continue
        provider, local = slicer.local(binding.source_callable)
        fn = next(f for f in provider.functions if f.value == local)
        if provider.unit in parents.snapshot.fact_store.original_source_units:
            frontiers.append(R.ConsumerFrontier(use.node, binding.use, use.actual, binding.interface,
                'COMPILED_CONSUMER_BODY_MATERIAL_ADAPTER_PENDING')); continue
        if fn.return_world is None:
            frontiers.append(R.ConsumerFrontier(use.node, binding.use, use.actual, binding.interface,
                'CONSUMER_NORMAL_EXIT_WORLD_UNRESOLVED')); continue
        if binding.source_callable not in body_ids:
            if provider.unit not in materials:
                materials[provider.unit] = WorldMaterial(parents.snapshot.catalog, provider.unit)
            function_index = next(i for i, f in enumerate(provider.functions) if f.value == local)
            declaration = slicer.fact(provider, 'functions', function_index)
            flow = project_world_flow(materials[provider.unit], binding.body, declaration,
                binding.state.formal, source_port(provider, fn.return_world))
            body_ids[binding.source_callable] = len(bodies); bodies.append(R.ConsumerBody(binding.source_callable, flow))
        entries.append(R.ConsumerBodyEntry(binding_index, body_ids[binding.source_callable], binding.argument.formal,
            (*binding.conditions, 'CALLEE_BODY_PARAMETERS_SHARE_DECLARATION_NOT_RUNTIME_INVOCATION')))
    parents.validate()
    return R.ReferenceConsumerGraph(uses, tuple(bindings), tuple(frontiers), tuple(bodies), tuple(entries))


def _artifact(path, schema):
    path = Path(path).absolute(); raw = path.read_bytes()
    return ProviderArtifact(str(path), sha256(raw).hexdigest(), len(raw), schema)


def _pins():
    from scar.analysis import source_consumer_parents, source_address_paths, source_world_flow, source_world_material
    return {name: sha256(Path(path).read_bytes()).hexdigest() for name, path in (
        ('producer', __file__), ('types', R.__file__), ('parents', source_consumer_parents.__file__),
        ('addresses', source_address_paths.__file__), ('world_flow', source_world_flow.__file__),
        ('world_material', source_world_material.__file__))}


def _counts(g):
    return dict(argument_uses=len(g.uses), direct_reference_uses=sum(u.direct_reference for u in g.uses),
        argument_roles=dict(Counter(u.role.value for u in g.uses)),
        source_parameter_bindings=len(g.bindings), bound_uses=len({b.use for b in g.bindings}),
        binding_kinds=dict(Counter(b.argument.kind.value for b in g.bindings)),
        unique_callee_functions=len({b.source_callable for b in g.bindings}), frontiers=len(g.frontiers),
        shared_consumer_bodies=len(g.bodies), body_parameter_entries=len(g.entries),
        consumer_bodies_with_normal_exit_path=sum(b.flow.anchor_reaches_exit for b in g.bodies),
        consumer_body_accesses=sum(len(b.flow.accesses) for b in g.bodies),
        frontier_reasons=dict(Counter(f.reason for f in g.frontiers)))


def build_reference_consumers(returns, out):
    started = time.monotonic(); returns = Path(returns).absolute(); out = Path(out).absolute(); pins = _pins()
    if out.exists(): raise ValueError('fresh source consumers output required')
    parent = _artifact(returns/'result.json', 'scar.world-return-graph'); parents = ConsumerParents(returns)
    g = build_consumers(parents)
    if pins != _pins() or parent != _artifact(returns/'result.json', parent.schema): raise ValueError('consumer rules or parent changed')
    _durable_mkdir(out); tables = {name: write_table(out/(name+'.jsonl.gz'), getattr(g, name))
        for name in ('uses', 'bindings', 'frontiers', 'bodies', 'entries')}
    r = dict(schema='scar.reference-consumer-graph', schema_version=1, status='CONDITIONAL_SOURCE_ARGUMENT_CONSUMERS',
        returns=str(returns), parent=encode(parent), pins=pins, tables=tables, counts=_counts(g), semantics=g.semantics,
        effects_discharged=False, runtime_dispatch_proven=False, content_versions_proven=False,
        target_executed=False, first_stage_complete=False, seconds=time.monotonic()-started)
    _durable_bytes(out/'result.json', _json(r), replace=False); return r


def read_reference_consumers(path):
    path = Path(path).absolute(); raw = (path/'result.json').read_bytes(); r = json.loads(raw)
    if (r['schema'], r['schema_version']) != ('scar.reference-consumer-graph', 1) or r['pins'] != _pins(): raise ValueError('consumer producer differs')
    if r['parent'] != encode(_artifact(Path(r['returns'])/'result.json', 'scar.world-return-graph')): raise ValueError('consumer parent differs')
    classes = dict(uses=R.ReferenceArgumentUse, bindings=R.SourceConsumerBinding, frontiers=R.ConsumerFrontier,
        bodies=R.ConsumerBody, entries=R.ConsumerBodyEntry)
    records = {name: tuple(decode(cls, w, record_tags=P.PRODUCTION_RECORD_TAGS) for w in _table(path, r['tables'][name]))
        for name, cls in classes.items()}
    g = R.ReferenceConsumerGraph(**records)
    parents = ConsumerParents(r['returns']); expected = build_consumers(parents)
    if g != expected or _counts(g) != r['counts'] or g.semantics != r['semantics']: raise ValueError('source argument routes or path witnesses differ')
    if any(r[k] is not False for k in ('effects_discharged','runtime_dispatch_proven','content_versions_proven','target_executed','first_stage_complete')):
        raise ValueError('argument consumer graph cannot grant runtime/effect authority')
    if (path/'result.json').read_bytes() != raw: raise ValueError('consumer graph changed during validation')
    return r, g


def main():
    p = argparse.ArgumentParser(description=__doc__); p.add_argument('--returns'); p.add_argument('--out'); p.add_argument('--read'); a = p.parse_args()
    if a.read: r, _ = read_reference_consumers(a.read)
    else:
        if not a.returns or not a.out: p.error('--returns and --out required')
        r = build_reference_consumers(a.returns,a.out)
    print(json.dumps(dict(status=r['status'],counts=r['counts'],seconds=r['seconds'])),flush=True)


if __name__ == '__main__': main()
