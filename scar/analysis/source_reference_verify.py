"""Check declared reference witnesses against their original receipt-bound rows.

This reader checks the supplied graph, never reconstructs reference slices or
infers current contents, scope admission, runtime identity or dispatch. Missing
producers and bounded searches remain unresolved facts.
"""
from collections import defaultdict, deque
from pathlib import Path
import re

from scar.analysis.source_reference_slice import DECLARED, ReferenceSlicer
from scar.analysis.source_relation_snapshot import _local_path
from scar.ir.program import normal_links as F, normal_targets as T
from scar.ir.program import source_reference_slices as R
from scar.ir.program.normal_graph import Port
from scar.ir.program.providers import ProviderArtifact, ProviderFactReference


_SEMANTICS = 'CONDITIONAL_DECLARED_REFERENCE_FLOW_NOT_CONTENT_OR_RUNTIME_IDENTITY'
_FRONTIERS = frozenset((
    'REFERENCE_STATE_BUDGET_FRONTIER', 'CALL_CONTEXT_DEPTH_FRONTIER',
    'NON_LEXICAL_NAMESPACE_CONTENT_UNRESOLVED',
    'CAPTURE_OR_OUTER_CALL_ENVIRONMENT_UNRESOLVED',
    'FORMAL_CALLER_OR_ENVIRONMENT_UNRESOLVED',
    'REFERENCE_PRODUCER_OR_ENVIRONMENT_UNRESOLVED',
    *('NON_REFERENCE_ARGUMENT_ROUTE_' + kind.value for kind in T.RouteKind
      if kind not in (T.RouteKind.ARGUMENT, T.RouteKind.INITIAL_DEFAULT)),
))
_CONSTRUCTOR_DATA_STAGES = frozenset((
    T.ConstructionStage.SOURCE_INIT, T.ConstructionStage.OBJECT_INIT,
    T.ConstructionStage.RETURN_FOREIGN, T.ConstructionStage.RESULT_TYPE_OPEN,
))


def _require(condition, message):
    if not condition:
        raise ValueError(message)


def _tuple(value, name):
    _require(type(value) is tuple, name + ' must retain its original tuple structure')
    return value


def _index(items, ordinal):
    _require(type(ordinal) is int and 0 <= ordinal < len(items),
             'reference graph index is outside its original table')
    return items[ordinal]


def _ordinal(locator, prefix):
    _require(type(locator) is str and locator.startswith(prefix),
             'reference locator differs from its original table')
    suffix = locator[len(prefix):]
    _require(re.fullmatch(r'0|[1-9][0-9]*', suffix) is not None,
             'reference locator needs its canonical original row ordinal')
    return int(suffix)


def _conditions(actual, required=()):
    _tuple(actual, 'reference conditions')
    _require(all(type(item) is str and item for item in actual),
             'reference conditions must be nonempty guard names')
    _require(set(required) <= set(actual), 'reference witness lost an original conditional guard')


class _ReferenceVerifier:
    def __init__(self, snapshot):
        self.snapshot = snapshot
        self.slicer = ReferenceSlicer(snapshot)
        self.locals = {}
        self.endpoints = set()
        self.fact_checks = 0
        self.artifacts = {}
        for name in ('calls', 'constructions'):
            receipt = snapshot.report.get(name)
            _require(type(receipt) is dict and all(key in receipt for key in ('path', 'sha256', 'bytes')),
                     'original reference relation table is absent: ' + name)
            self.artifacts[name] = ProviderArtifact(
                str(_local_path(Path(snapshot.path), receipt['path'])), receipt['sha256'],
                receipt['bytes'], 'scar.context.' + name)
        _require(self.artifacts['calls'].uri != self.artifacts['constructions'].uri,
                 'reference relation tables share an artifact URI')

    def local(self, port):
        _require(type(port) is T.GlobalPort and type(port.unit) is str and port.unit
                 and type(port.port) is Port, 'reference endpoint needs an original qualified source port')
        if port not in self.locals:
            try:
                self.locals[port] = self.slicer.local(port)
            except (KeyError, IndexError) as error:
                raise ValueError('reference endpoint is outside its original source facts') from error
        return self.locals[port]

    def source_class(self, port):
        unit, local = self.local(port)
        _require(any(cls.value == local for cls in unit.classes),
                 'allocation source class is not an original class definition')

    def endpoint(self, port):
        if type(port) is T.GlobalPort:
            self.local(port)
        else:
            _require(type(port) is T.ConstructionPort and type(port.role) is T.ConstructionPortKind,
                     'reference endpoint is not an original source or construction interface')
            unit, local = self.local(port.call)
            self.source_class(port.source_class)
            _require(any(call.result == local for call in unit.calls),
                     'construction interface has no original source call result')
        self.endpoints.add(port)

    def collect(self, slices):
        wanted = {name: set() for name in self.artifacts}
        for selected in slices:
            _require(type(selected) is R.ReferenceSlice and selected.semantics == _SEMANTICS,
                     'reference slice cannot grant content or runtime identity authority')
            _tuple(selected.states, 'reference states')
            _require(bool(selected.states), 'reference slice needs its original root state')
            for state in selected.states:
                _require(type(state) is R.ReferenceState, 'reference slice contains a non-state record')
                self.endpoint(state.port)
                _tuple(state.calls, 'reference call stack')
                _require(all(type(number) is int and number >= 0 for number in state.calls),
                         'reference call context needs original nonnegative call ordinals')
                wanted['calls'].update(state.calls)
            _require(selected.states[0].calls == (), 'reference root cannot invent an enclosing call context')
            for name, record_type in (('transitions', R.ReferenceTransition), ('origins', R.ReferenceOrigin)):
                for record in _tuple(getattr(selected, name), 'reference ' + name):
                    _require(type(record) is record_type, 'reference slice contains a foreign witness record')
                    _conditions(record.conditions)
                    for evidence in _tuple(record.evidence, 'reference evidence'):
                        _require(type(evidence) is ProviderFactReference
                                 and type(evidence.artifact) is ProviderArtifact,
                                 'reference evidence needs its original provider fact reference')
                        for table, artifact in self.artifacts.items():
                            if evidence.artifact.uri == artifact.uri:
                                _require(evidence.artifact == artifact,
                                         'reference evidence changed its original relation artifact receipt')
                                wanted[table].add(_ordinal(evidence.locator, '#/records/'))
            for frontier in _tuple(selected.frontiers, 'reference frontiers'):
                _require(type(frontier) is R.ReferenceFrontier, 'reference frontier has a foreign record type')
                _index(selected.states, frontier.state)
                _require(frontier.reason in _FRONTIERS,
                         'reference frontier may record only an unresolved producer, environment or budget')
        self.rows = {}
        for name, record_type in (('calls', T.CallLink), ('constructions', T.ConstructionLink)):
            # The predicate observes every wire row without decoding unwanted
            # records. RelationSnapshot still verifies the complete receipt.
            counter = -1

            def selected_row(wire):
                nonlocal counter
                counter += 1
                return counter in wanted[name]

            rows = self.snapshot.rows(name, selected_row, record_type)
            self.rows[name] = {number: (record, evidence) for number, record, evidence in rows}
            _require(set(self.rows[name]) == wanted[name],
                     'reference witness names an absent original relation row')

    def relation(self, evidence, table):
        _require(evidence.artifact == self.artifacts[table],
                 'reference witness cites a different original relation artifact')
        ordinal = _ordinal(evidence.locator, '#/records/')
        _require(ordinal in self.rows[table], 'reference witness has no selected original relation row')
        row, original = self.rows[table][ordinal]
        _require(evidence == original, 'reference witness differs from its original relation reference')
        self.fact_checks += 1
        return ordinal, row

    def fact(self, evidence, unit, table):
        prefix = self.slicer.fact(unit, table, 0).locator.rsplit('/', 1)[0] + '/'
        ordinal = _ordinal(evidence.locator, prefix)
        record = _index(getattr(unit, table), ordinal)
        _require(evidence == self.slicer.fact(unit, table, ordinal),
                 'reference witness changed its original source URI, receipt, schema or locator')
        self.fact_checks += 1
        return record

    def transition(self, selected, edge):
        down = _index(selected.states, edge.downstream)
        up = _index(selected.states, edge.upstream)
        _require(type(edge.kind) is R.ReferenceTransitionKind, 'reference transition has an unknown kind')
        _require(len(edge.evidence) == (2 if edge.kind is R.ReferenceTransitionKind.LEXICAL_MAY_BINDING else 1),
                 'reference transition lost its exact original witness arity')
        evidence = edge.evidence[0]
        if edge.kind is R.ReferenceTransitionKind.DECLARED_ALIAS:
            unit, target = self.local(down.port)
            source_unit, source = self.local(up.port)
            _require(source_unit.unit == unit.unit and tuple(self.fact(evidence, unit, 'aliases')) == (source, target),
                     'declared alias crossed its original source/target ports')
            _require(up.calls == down.calls, 'declared alias changed the invocation context')
            _conditions(edge.conditions, DECLARED)
        elif edge.kind is R.ReferenceTransitionKind.LEXICAL_MAY_BINDING:
            unit, target = self.local(down.port)
            source_unit, source = self.local(up.port)
            write = self.fact(evidence, unit, 'names')
            read = self.fact(edge.evidence[1], unit, 'names')
            _require(source_unit.unit == unit.unit and write.write is True and read.write is False
                     and write.value == source and read.value == target
                     and write.namespace == read.namespace and type(write.namespace) is F.Namespace
                     and write.namespace.kind is F.NamespaceKind.LEXICAL,
                     'lexical reference witness differs from its original namespace read/write facts')
            _require(up.calls == down.calls, 'lexical binding changed the invocation context')
            _conditions(edge.conditions, (*DECLARED, 'FLOW_INSENSITIVE_LEXICAL_BINDING_NOT_CURRENT_FRAME_VERSION'))
        elif edge.kind in (R.ReferenceTransitionKind.ARGUMENT, R.ReferenceTransitionKind.INITIAL_DEFAULT):
            ordinal, call = self.relation(evidence, 'calls')
            unit, formal = self.local(down.port)
            functions = [fn for fn in unit.functions if formal in fn.formals]
            _require(len(functions) == 1, 'argument target is not one original function formal')
            fn = functions[0]
            route_kind = T.RouteKind(edge.kind.value)
            _require(any(route.formal == down.port and route.kind is route_kind and up.port in route.actuals
                         for route in call.parameters),
                     'argument transition differs from its original formal/actual route')
            matching = bool(down.calls and self.rows['calls'][down.calls[-1]][0].body
                            == T.Body(unit.unit, fn.template, fn.body))
            required = call.conditions
            if matching:
                _require(ordinal == down.calls[-1] and up.calls == down.calls[:-1],
                         'argument transition crossed or failed to pop its matching call')
            else:
                _require(up.calls == down.calls, 'capture or unfixed caller transition popped a foreign call')
                required = (*required, 'ENCLOSING_CALL_CONTEXT_NOT_FIXED')
                if down.calls:
                    required = (*required, 'CAPTURE_CREATION_CONTEXT_NOT_PROVEN')
                    _require(any(f.state == edge.downstream
                                 and f.reason == 'CAPTURE_OR_OUTER_CALL_ENVIRONMENT_UNRESOLVED'
                                 for f in selected.frontiers),
                             'capture transition lost its unresolved enclosing environment frontier')
            if route_kind is T.RouteKind.INITIAL_DEFAULT:
                required = (*required, 'FUNCTION_DEFAULT_VERSION_MATCHES_DECLARATION')
            _conditions(edge.conditions, required)
        elif edge.kind is R.ReferenceTransitionKind.DATA_RETURN_ENTER_CALL:
            ordinal, call = self.relation(evidence, 'calls')
            data_target = (down.port == call.result or type(down.port) is T.ConstructionPort
                           and down.port.role is T.ConstructionPortKind.NEW_RESULT)
            _require(call.mode != 'SOURCE_INIT' and data_target and (up.port, down.port) in call.returns,
                     'reference return is not an original data return (init/world returns are excluded)')
            _require(up.calls == (*down.calls, ordinal), 'data return did not enter its original call context')
            _conditions(edge.conditions, call.conditions)
        else:
            _, link = self.relation(evidence, 'constructions')
            _require(link.stage in _CONSTRUCTOR_DATA_STAGES and down.port == link.result
                     and up.port in link.inputs and type(up.port) is T.ConstructionPort
                     and up.port.role is T.ConstructionPortKind.NEW_RESULT,
                     'constructor reference is not its original NEW_RESULT data input')
            _require(up.calls == down.calls, 'constructor data transition changed the invocation context')
            _conditions(edge.conditions, (*link.conditions, 'NORMAL_CONSTRUCTOR_COMPLETION_REQUIRED',
                                          'INIT_DATA_RETURN_NOT_USED'))

    def origin(self, selected, origin):
        state = _index(selected.states, origin.state)
        _require(type(origin.kind) is R.ReferenceOriginKind and len(origin.evidence) == 1,
                 'reference origin needs its exact kind and original evidence')
        evidence = origin.evidence[0]
        if origin.kind is R.ReferenceOriginKind.ALLOCATION_SITE_CANDIDATE:
            _, link = self.relation(evidence, 'constructions')
            object_new = (link.stage is T.ConstructionStage.OBJECT_NEW
                          and type(state.port) is T.ConstructionPort
                          and state.port.role is T.ConstructionPortKind.NEW_RESULT
                          and state.port.source_class == link.source_class)
            explicit = link.stage is T.ConstructionStage.EXPLICIT_OBJECT_NEW and state.port == link.result
            _require((object_new or explicit) and state.port in link.outputs
                     and origin.source_class == link.source_class,
                     'allocation candidate differs from its original object allocation output/class')
            self.source_class(origin.source_class)
            _conditions(origin.conditions, (*link.conditions, 'SOURCE_SITE_NOT_DYNAMIC_ALLOCATION_IDENTITY'))
        else:
            _require(origin.source_class is None, 'source literal/function/class origin is not an allocation')
            table = {R.ReferenceOriginKind.SOURCE_LITERAL: 'constants',
                     R.ReferenceOriginKind.FUNCTION_DEFINITION: 'functions',
                     R.ReferenceOriginKind.CLASS_DEFINITION: 'classes'}[origin.kind]
            unit, local = self.local(state.port)
            _require(self.fact(evidence, unit, table).value == local,
                     'reference origin differs from its original literal/function/class metadata')
            _conditions(origin.conditions, DECLARED)

    def graph(self, selected):
        adjacency = defaultdict(list)
        for edge in selected.transitions:
            self.transition(selected, edge)
            adjacency[edge.downstream].append(edge.upstream)
        for origin in selected.origins:
            self.origin(selected, origin)
        reached = {0}
        pending = deque((0,))
        while pending:
            for upstream in adjacency[pending.popleft()]:
                if upstream not in reached:
                    reached.add(upstream)
                    pending.append(upstream)
        _require(len(reached) == len(selected.states), 'reference slice contains a state unreachable from its root')
        terminals = {origin.state for origin in selected.origins}
        frontiers = {frontier.state for frontier in selected.frontiers}
        _require(all(index in adjacency or index in terminals or index in frontiers
                     for index in range(len(selected.states))),
                 'reference slice silently omitted an unresolved producer frontier')


def verify_reference_slices(snapshot, slices):
    """Return mechanical witness counts, preserving every unresolved obligation.

    All relation evidence and call-context ordinals are collected before each
    original relation table is scanned once. Only wanted records are decoded;
    both complete relation receipts and the snapshot's parent guards are still
    validated. Local facts are read through the original source catalog.
    """
    _tuple(slices, 'reference slices')
    snapshot.validate_parents()
    verifier = _ReferenceVerifier(snapshot)
    verifier.collect(slices)
    for selected in slices:
        verifier.graph(selected)
    parents = snapshot.validate_parents()
    return dict(reference_slices=len(slices), reference_states=sum(len(s.states) for s in slices),
                reference_transitions=sum(len(s.transitions) for s in slices),
                reference_origins=sum(len(s.origins) for s in slices),
                reference_frontiers=sum(len(s.frontiers) for s in slices),
                relation_call_rows=len(verifier.rows['calls']),
                relation_construction_rows=len(verifier.rows['constructions']),
                source_units=len(verifier.slicer.units), original_fact_reference_checks=verifier.fact_checks,
                parent_guards=parents)
