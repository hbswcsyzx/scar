"""Build bounded, balanced reference slices from shared source interfaces.

Local source facts are declarations, including scopes not yet admitted by an
entry solver. Interface witnesses retain their original snapshot and guards.
Only matched call returns/arguments cross invocation boundaries. Lexical
bindings, mutable field contents and allocation candidates stay distinct.
"""
from collections import defaultdict, deque
from pathlib import Path

from scar.analysis.source_template_links import _json
from scar.ir.program import normal_links as F, normal_targets as T
from scar.ir.program import source_reference_slices as R
from scar.ir.program.providers import ProviderArtifact, ProviderFactReference
from scar.ir.record_codec import encode, decode


def source_port(unit, index):
    """Qualify an original source-fact port without interpreting its value."""
    raw = unit.ports[index]
    return T.GlobalPort(unit.unit, decode(T.Port, raw) if type(raw) is dict else raw)


_gp = source_port


DECLARED = ('SOURCE_REFERENCE_CONSTRAINT_IF_OWNING_SCOPE_ENTERED',)
FIELD_CONDITIONS = (
    'SOURCE_ACCESS_SCOPES_ENTERED',
    'COMPATIBLE_REFERENCE_PATH_AND_CALL_CONTEXTS_SELECTED',
    'SAME_DYNAMIC_RECEIVER_INSTANCE_AND_INVOCATION_SELECTED',
    'DEFAULT_INSTANCE_ATTRIBUTE_SLOT_ADMISSION',
    'CURRENT_CLASS_MRO_HAS_NO_SELECTED_DATA_DESCRIPTOR',
    'INSTANCE_DICTIONARY_PATH_SELECTED',
    'MAY_REACHING_STORE_NOT_SELECTED_STATE_VERSION',
    'NO_SOURCE_ORDER_OR_RUNTIME_IDENTITY_PROOF',
)


class ReferenceSlicer:
    def __init__(self, snapshot):
        self.snapshot = snapshot
        self.store = snapshot.fact_store
        self.units = {}; self.indexed = set()
        self.calls = {}; self.constructions = set()
        self.arguments = defaultdict(list); self.returns = defaultdict(list)
        self.construct_returns = defaultdict(list); self.allocations = defaultdict(list)

    def unit(self, identity):
        if identity in self.units:
            return self.units[identity]
        unit = self.store.load(identity)
        ports = {_json(raw if type(raw) is dict else encode(raw)): i for i, raw in enumerate(unit.ports)}
        aliases = defaultdict(list); reads = defaultdict(list); writes = defaultdict(list)
        for i, (source, target) in enumerate(unit.aliases):
            aliases[target].append((source, i))
        for i, access in enumerate(unit.names):
            if access.write:
                writes[access.namespace].append((access.value, i))
            else:
                reads[access.value].append((access.namespace, i))
        formals = {p: fn for fn in unit.functions for p in fn.formals}
        terminals = {c.value: ('SOURCE_LITERAL', 'constants', i) for i, c in enumerate(unit.constants)}
        terminals.update((f.value, ('FUNCTION_DEFINITION', 'functions', i)) for i, f in enumerate(unit.functions))
        terminals.update((c.value, ('CLASS_DEFINITION', 'classes', i)) for i, c in enumerate(unit.classes))
        self.units[identity] = (unit, ports, aliases, reads, writes, formals, terminals)
        return self.units[identity]

    def local(self, port):
        unit, ports, *_ = self.unit(port.unit)
        try:
            return unit, ports[_json(encode(port.port))]
        except KeyError:
            raise ValueError('reference endpoint is outside its original source port table') from None

    def fact(self, unit, table, ordinal):
        row = self.store.rows[unit.unit]
        path = Path(row['facts'])
        if not path.is_absolute():
            path = self.store._source_parents[unit.unit].path/path
        artifact = ProviderArtifact(str(path), row['sha256'], row['bytes'], 'scar.source-facts-unit')
        prefix = '#/records/0/' if row.get('facts_format') == 'COMPILE_CONTEXT_F4_JSONL' else '#/'
        return ProviderFactReference(artifact, prefix+table+'/'+str(ordinal))

    def interfaces(self, identity):
        if identity in self.indexed:
            return
        self.indexed.add(identity)
        def selected(w):
            return (w['result']['unit'] == identity
                or (w.get('body') is not None and w['body']['unit'] == identity)
                or (w.get('source_callable') is not None and w['source_callable']['unit'] == identity))
        for ordinal, call, evidence in self.snapshot.rows('calls', selected, T.CallLink):
            if ordinal in self.calls:
                continue
            self.calls[ordinal] = call
            for route in call.parameters:
                self.arguments[route.formal].append((ordinal, route, evidence))
            for source, target in call.returns:
                # Never confuse the state result or discarded init data with
                # the Python data result. SOURCE_NEW returns to NEW_RESULT.
                data = (target == call.result or isinstance(target, T.ConstructionPort)
                    and target.role is T.ConstructionPortKind.NEW_RESULT)
                if data and call.mode != 'SOURCE_INIT':
                    self.returns[target].append((source, ordinal, evidence))
        for ordinal, link, evidence in self.snapshot.rows('constructions', selected, T.ConstructionLink):
            if ordinal in self.constructions:
                continue
            self.constructions.add(ordinal)
            if link.stage is T.ConstructionStage.OBJECT_NEW:
                for output in link.outputs:
                    if isinstance(output, T.ConstructionPort) and output.role is T.ConstructionPortKind.NEW_RESULT:
                        self.allocations[output].append((link.source_class, evidence, link.conditions))
            elif link.stage is T.ConstructionStage.EXPLICIT_OBJECT_NEW:
                if link.result in link.outputs:
                    self.allocations[link.result].append((link.source_class, evidence, link.conditions))
            if link.stage in (T.ConstructionStage.SOURCE_INIT, T.ConstructionStage.OBJECT_INIT,
                    T.ConstructionStage.RETURN_FOREIGN, T.ConstructionStage.RESULT_TYPE_OPEN):
                for source in link.inputs:
                    if isinstance(source, T.ConstructionPort) and source.role is T.ConstructionPortKind.NEW_RESULT:
                        self.construct_returns[link.result].append((source, evidence, link.conditions))

    def slice(self, port, *, max_states=20_000, max_call_depth=32):
        states = [R.ReferenceState(port)]; ids = {states[0]: 0}; pending = deque((0,))
        edges = []; origins = []; frontiers = []; frontier_set = set()
        def frontier(state, reason):
            if (state, reason) not in frontier_set:
                frontier_set.add((state, reason)); frontiers.append(R.ReferenceFrontier(state, reason))
        def step(downstream, point, stack, kind, evidence, conditions=()):
            state = R.ReferenceState(point, stack)
            if state not in ids:
                if len(states) >= max_states:
                    frontier(downstream, 'REFERENCE_STATE_BUDGET_FRONTIER'); return
                ids[state] = len(states); states.append(state); pending.append(ids[state])
            edges.append(R.ReferenceTransition(downstream, ids[state], R.ReferenceTransitionKind(kind),
                tuple(evidence), tuple(conditions)))
        while pending:
            index = pending.popleft(); state = states[index]; point = state.port; stack = state.calls
            self.interfaces(point.unit)
            before = len(edges); terminal = False
            for source_class, evidence, conditions in self.allocations.get(point, ()):
                origins.append(R.ReferenceOrigin(index, R.ReferenceOriginKind.ALLOCATION_SITE_CANDIDATE, source_class,
                    (evidence,), (*conditions, 'SOURCE_SITE_NOT_DYNAMIC_ALLOCATION_IDENTITY')))
                terminal = True
            for source, evidence, conditions in self.construct_returns.get(point, ()):
                step(index, source, stack, 'CONSTRUCTOR_DATA_FROM_NEW_RESULT', (evidence,),
                    (*conditions, 'NORMAL_CONSTRUCTOR_COMPLETION_REQUIRED', 'INIT_DATA_RETURN_NOT_USED'))
            for source, ordinal, evidence in self.returns.get(point, ()):
                if len(stack) >= max_call_depth:
                    frontier(index, 'CALL_CONTEXT_DEPTH_FRONTIER'); continue
                step(index, source, (*stack, ordinal), 'DATA_RETURN_ENTER_CALL', (evidence,), self.calls[ordinal].conditions)
            if isinstance(point, T.GlobalPort):
                unit, local = self.local(point)
                _, _, aliases, reads, writes, formals, terminals = self.unit(point.unit)
                for source, ordinal in aliases.get(local, ()):
                    step(index, _gp(unit, source), stack, 'DECLARED_ALIAS', (self.fact(unit, 'aliases', ordinal),), DECLARED)
                for namespace, ordinal in reads.get(local, ()):
                    if namespace.kind is not F.NamespaceKind.LEXICAL:
                        frontier(index, 'NON_LEXICAL_NAMESPACE_CONTENT_UNRESOLVED'); continue
                    for source, writer in writes.get(namespace, ()):
                        step(index, _gp(unit, source), stack, 'LEXICAL_MAY_BINDING',
                            (self.fact(unit, 'names', writer), self.fact(unit, 'names', ordinal)),
                            (*DECLARED, 'FLOW_INSENSITIVE_LEXICAL_BINDING_NOT_CURRENT_FRAME_VERSION'))
                if local in formals:
                    fn = formals[local]; matching = None; foreign = False
                    if stack:
                        top = self.calls[stack[-1]]
                        matching = stack[-1] if top.body == T.Body(unit.unit, fn.template, fn.body) else None
                        foreign = matching is None
                        if foreign:
                            frontier(index, 'CAPTURE_OR_OUTER_CALL_ENVIRONMENT_UNRESOLVED')
                    candidates = self.arguments.get(point, ())
                    if not candidates:
                        frontier(index, 'FORMAL_CALLER_OR_ENVIRONMENT_UNRESOLVED')
                    for ordinal, route, evidence in candidates:
                        if matching is not None and ordinal != matching:
                            continue
                        if route.kind not in (T.RouteKind.ARGUMENT, T.RouteKind.INITIAL_DEFAULT):
                            frontier(index, 'NON_REFERENCE_ARGUMENT_ROUTE_'+route.kind.value); continue
                        for source in route.actuals:
                            conditions = self.calls[ordinal].conditions
                            if matching is None:
                                conditions = (*conditions, 'ENCLOSING_CALL_CONTEXT_NOT_FIXED')
                            if foreign:
                                conditions = (*conditions, 'CAPTURE_CREATION_CONTEXT_NOT_PROVEN')
                            if route.kind is T.RouteKind.INITIAL_DEFAULT:
                                conditions = (*conditions, 'FUNCTION_DEFAULT_VERSION_MATCHES_DECLARATION')
                            step(index, source, stack[:-1] if matching is not None else stack,
                                route.kind.value, (evidence,), conditions)
                if local in terminals:
                    kind, table, ordinal = terminals[local]
                    origins.append(R.ReferenceOrigin(index, R.ReferenceOriginKind(kind), None,
                        (self.fact(unit, table, ordinal),), DECLARED))
                    terminal = True
            if len(edges) == before and not terminal:
                frontier(index, 'REFERENCE_PRODUCER_OR_ENVIRONMENT_UNRESOLVED')
        self.snapshot.validate_parents()
        return R.ReferenceSlice(tuple(states), tuple(edges), tuple(origins), tuple(frontiers))

    def attribute_site(self, unit, ordinal):
        access = unit.attributes[ordinal]
        return T.AttributeSite(T.AttributeOrigin.ATTRIBUTE, access.action, _gp(unit, access.receiver), access.name,
            _gp(unit, access.value) if access.action is F.AttributeAction.GET else None,
            _gp(unit, access.value) if access.action is F.AttributeAction.SET else None,
            _gp(unit, access.world), _gp(unit, access.result_world))

    def fields(self, read_unit, read_ordinal, *, write_units=(), **limits):
        unit, *_ = self.unit(read_unit); access = unit.attributes[read_ordinal]
        if access.action is not F.AttributeAction.GET:
            raise ValueError('field slice requires an original attribute GET')
        read_slice = self.slice(_gp(unit, access.receiver), **limits)
        slices = [read_slice]; flows = []
        roots = [o for o in read_slice.origins if o.kind == 'ALLOCATION_SITE_CANDIDATE']
        domain = {read_unit, *write_units, *(o.source_class.unit for o in roots)}
        for identity in sorted(domain):
            writer, *_ = self.unit(identity)
            for ordinal, write in enumerate(writer.attributes):
                if write.action is not F.AttributeAction.SET or write.name != access.name:
                    continue
                selected = self.slice(_gp(writer, write.receiver), **limits)
                number = len(slices); slices.append(selected)
                for wi, origin in enumerate(selected.origins):
                    if origin.kind != 'ALLOCATION_SITE_CANDIDATE':
                        continue
                    for ri, read_origin in enumerate(read_slice.origins):
                        if (read_origin.kind == 'ALLOCATION_SITE_CANDIDATE'
                                and selected.states[origin.state].port == read_slice.states[read_origin.state].port
                                and origin.source_class == read_origin.source_class):
                            flows.append(R.ConditionalFieldFlow(self.fact(writer, 'attributes', ordinal),
                                self.fact(unit, 'attributes', read_ordinal), self.attribute_site(writer, ordinal),
                                self.attribute_site(unit, read_ordinal), selected.states[origin.state].port,
                                origin.source_class, number, 0, wi, ri,
                                (*FIELD_CONDITIONS, *origin.conditions, *read_origin.conditions)))
        return tuple(slices), tuple(flows), tuple(sorted(domain))
