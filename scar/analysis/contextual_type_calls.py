"""Conditional class-call implementations in the existing dependency view.

Class-statement provenance does not prove a runtime class or selected native
implementation. Original calls remain alternatives; native callbacks and
physical argument carriers stay explicit open boundaries.
"""
from __future__ import annotations

from collections import defaultdict
from dataclasses import dataclass
import hashlib
import json

from scar.ir.program.class_call_sources import ContextualClassStatementSource
from scar.ir.program.codec import dumps
from scar.ir.program.dependencies import (
    DependencyCondition as Condition, DependencyEdge as Edge,
    DependencyEvidence as Evidence, DependencyFrame as Frame,
    DependencyFrontier as Frontier, DependencyKind as K, DependencyMeaning as M,
    DependencyNeighborhood as Neighborhood, DependencyPoint as Point,
    DependencyStrength as Strength, GraphNamespace, context_push,
)
from scar.ir.program.ids import OperationID, UseID, ValueID
from scar.ir.program.model import (CompletionResult, ExitKind, ReferenceValue,
    StateVersionValue, TerminatorKind, value_type)
from scar.ir.program.native import ExitPortRef
from scar.ir.program.providers import ProviderArtifact
from scar.ir.program.source_references import SourceArtifactLocator
from scar.ir.program.type_calls import TypeCallOperand
from scar.ir.record_codec import decode, encode


@dataclass(frozen=True, slots=True)
class ContextualTypeCall:
    call: Point
    source: ContextualClassStatementSource
    provider: GraphNamespace
    frame: Frame
    edges: tuple[Edge, ...]
    conditions: tuple[Condition, ...]
    evidence: tuple[Evidence, ...]
    original_invocation_retained: bool = True
    runtime_class_verified: bool = False
    physical_abi_mapping_complete: bool = False
    python_callbacks_connected: bool = False

    def __post_init__(self):
        if (type(self.call) is not Point or type(self.call.node) is not OperationID
                or type(self.source) is not ContextualClassStatementSource
                or self.source.call != self.call or type(self.provider) is not GraphNamespace
                or self.provider.source_body is not None or type(self.frame) is not Frame
                or self.frame.caller != self.call.namespace or self.frame.operation != self.call.node
                or self.frame.target != self.provider):
            raise ValueError('type-call alternative changed its original call/source or implementation frame')
        if any(type(value) is not bool or value is not expected for value, expected in (
                (self.original_invocation_retained, True), (self.runtime_class_verified, False),
                (self.physical_abi_mapping_complete, False), (self.python_callbacks_connected, False))):
            raise ValueError('conditional construction cannot assert runtime dispatch, ABI or callbacks')
        for rows, kind in ((self.edges, Edge), (self.conditions, Condition), (self.evidence, Evidence)):
            if type(rows) is not tuple or any(type(row) is not kind for row in rows):
                raise TypeError('type-call relations require immutable qualified records')


class ContextualTypeCallImplementations:
    relation_kinds = frozenset((K.IMPLEMENTATION, K.ARGUMENT, K.COMPLETION, K.STATE_INTERFACE))

    def __init__(self, resolver):
        self.resolver = resolver
        self.session, self.owner = resolver.session, resolver.owner
        self._providers = {}
        self._provider_ports = {}
        self._before, self._after = defaultdict(dict), defaultdict(dict)
        self._alternatives, self._notes = {}, {}
        self._last = None
        self._edge_count = 0

    def for_call(self, call):
        return self._last[1] if self._last is not None and self._last[0] == call else None

    def frontiers_for(self, call):
        return self._notes.get(call, ())

    def _provider(self, types, layout, exception_arity):
        key = types, layout, exception_arity
        found = self._providers.get(key)
        if found is not None:
            return found
        from scar.analysis.static_type_call import build_type_call_provider, validate_type_call_provider
        provider = build_type_call_provider(types, layout, exception_arity)
        validate_type_call_provider(provider)
        record = encode(provider)
        record.pop('graph')
        document = {'schema': 'scar.conditional-type-call-provider', 'schema_version': 1,
            'graph': json.loads(dumps(provider.graph)), 'provider': record,
            'target_executed': False, 'transformation_authorized': False}
        raw = json.dumps(document, sort_keys=True, ensure_ascii=False,
            separators=(',', ':'), allow_nan=False).encode()
        digest = hashlib.sha256(raw).hexdigest()
        descriptor = self.owner._write('type-call-providers/' + digest + '.json.gz', raw)
        # The CLI owns this physical output for the whole query lifetime.
        # Registration rechecks its stored/decoded receipts through the same reader.
        uri = str(self.owner.out / descriptor['path'])
        locator = SourceArtifactLocator(ProviderArtifact(uri, descriptor['sha256'], descriptor['bytes'],
            'scar.conditional-type-call-provider/1'), descriptor['decoded_sha256'],
            descriptor['decoded_bytes'], 'gzip-canonical-json', '#/graph')
        namespace = self.session.register_implementation_graph(locator,
            'scar.conditional-type-call/1:ProgramGraph', provider.graph)
        # Keep only routing/configuration IDs here; graphs/indexes use the metered LRU.
        index = self.session.index(namespace)
        ports = {namespace.root, *provider.inputs, provider.world}
        for region_exit in index.regions[namespace.root].exits:
            for slot in range(len(region_exit.types)):
                ports.update(site.use.id for site in index.exit_port_uses(
                    ExitPortRef(namespace.root, region_exit.name, slot)))
        self._provider_ports[namespace] = frozenset(ports)
        found = namespace, provider.inputs, provider.world, provider.guards, provider.argument_view
        self._providers[key] = found
        return found

    @staticmethod
    def _completion(body, operation, kind):
        rows = [(number, edge) for number, edge in enumerate(operation.terminator.successors)
            if edge.kind is kind]
        if len(rows) != 1:
            raise ValueError('original CALL needs one normal and one raise outcome')
        number, edge = rows[0]
        block = body.index._block_records[edge.block]
        slots = {}
        for value, actual in zip(block.arguments, edge.arguments):
            if type(actual) is not CompletionResult or actual.index in slots:
                raise ValueError('original CALL completion lost its produced slot')
            slots[actual.index] = value
        if set(slots) != set(range(len(edge.arguments))):
            raise ValueError('original CALL completion slots are incomplete')
        return number, tuple(slots[i] for i in range(len(slots)))

    def _connect(self, source):
        call = source.call
        body = self.resolver._body(call.namespace)
        operation = body.index.operations[call.node]
        if operation.terminator is None or operation.terminator.kind is not TerminatorKind.INVOKE:
            raise ValueError('class invocation must retain the actual original CALL INVOKE')
        owned = {use.id: use for use in operation.uses}
        actuals = [owned[identity] for identity in operation.invoke_arguments]
        worlds = [use for use in actuals if type(body.index.values[use.value]) is StateVersionValue]
        if len(worlds) != 1 or source.callable.node not in owned:
            raise ValueError('class invocation lost its original callee/world')
        world, = worlds
        callee = owned[source.callable.node]
        actuals = [callee, *(use for use in actuals if use.id not in (callee.id, world.id))]
        links = {row.use: row for row in body.uses_by_op.get(call.node, ())}
        call_link = self.resolver._calls(body)[call.node]
        arguments, _ = self.owner._actuals(body, operation, body.context.call_nodes.get(call_link.source.atom_id))
        argument_by_use = {argument.use: argument for argument in arguments if argument.use is not None}
        layout = [TypeCallOperand('callee')]
        for use in actuals[1:]:
            row = links.get(use.id)
            argument = argument_by_use.get(use.id)
            layout.append(TypeCallOperand(row.role if row is not None else 'original-operand-role-open',
                row.index if row is not None else None, argument.keyword if argument is not None else None))
        types = tuple(value_type(body.index.values[use.value]) for use in actuals)
        normal_index, normal = self._completion(body, operation, ExitKind.NORMAL)
        raised_index, raised = self._completion(body, operation, ExitKind.RAISE)
        if (len(normal) != 2 or type(body.index.values[normal[0]]) is not ReferenceValue
                or type(body.index.values[normal[-1]]) is not StateVersionValue
                or type(body.index.values[raised[-1]]) is not StateVersionValue
                or len(raised) not in (2, 3)
                or any(type(body.index.values[value]) is not ReferenceValue for value in raised[:-1])):
            raise ValueError('class invocation original object/exception/world ABI is unsupported')
        namespace, formals, provider_world, guards, argument_view = self._provider(types, tuple(layout), len(raised) - 1)
        frame = Frame(call.namespace, call.node, callee.id, callee.value, namespace, entry=namespace.root)
        inner = context_push(call.context, frame)
        anchor = (call, source.callable, Point(call.namespace, world.id, call.context), source.source)
        operand_points = tuple(Point(call.namespace, actual.id, call.context) for actual in actuals)
        formal_points = tuple(Point(namespace, formal, inner) for formal in formals)
        view = Point(namespace, argument_view, inner)
        conditions = tuple(dict.fromkeys((*source.conditions, *(Condition('scar.type-call', guard.value,
            call, operands=tuple(dict.fromkeys((*anchor[1:], *operand_points, *formal_points, view)))) for guard in guards))))
        evidence = (*source.evidence, Evidence('CONDITIONAL_STANDARD_TYPE_CALL_PROTOCOL_V1',
            (call.namespace.graph, source.locator, namespace.graph),
            tuple(dict.fromkeys((*anchor, *operand_points, *formal_points, view)))))
        edges = []
        def edge(before, after, kind, meaning, extra=()):
            edges.append(Edge(before, after, kind, meaning, evidence,
                tuple(dict.fromkeys((*conditions, *extra))), Strength.MAY))
        edge(call, Point(namespace, namespace.root, inner), K.IMPLEMENTATION, M.STRUCTURE)
        for actual, formal in zip(actuals, formals):
            meaning = M.REFERENCE if type(body.index.values[actual.value]) is ReferenceValue else M.VALUE
            edge(Point(call.namespace, actual.id, call.context), Point(namespace, formal, inner), K.ARGUMENT, meaning)
        edge(Point(call.namespace, world.id, call.context), Point(namespace, provider_world, inner),
            K.STATE_INTERFACE, M.STATE_INTERFACE)
        index = self.session.index(namespace)
        for kind, ordinal, targets in ((ExitKind.NORMAL, normal_index, normal),
                                       (ExitKind.RAISE, raised_index, raised)):
            exit_name = 'normal' if kind is ExitKind.NORMAL else 'raise'
            selection = Condition('canonical', 'SUCCESSOR_SELECTED', call, ordinal)
            for slot, target in enumerate(targets):
                state = type(body.index.values[target]) is StateVersionValue
                for terminal in index.exit_port_uses(ExitPortRef(namespace.root, exit_name, slot)):
                    terminal_point = Point(namespace, terminal.operation, inner)
                    taken = Condition('scar.type-call', 'ORIGINAL_IMPLEMENTATION_RETURN_SITE_SELECTED', terminal_point)
                    edge(Point(namespace, terminal.use.id, inner), Point(call.namespace, target, call.context),
                        K.STATE_INTERFACE if state else K.COMPLETION,
                        M.STATE_INTERFACE if state else M.REFERENCE, (selection, taken))
        return ContextualTypeCall(call, source, namespace, frame, tuple(edges), conditions, evidence)

    def observe(self, call, sources):
        accepted, notes = [], {}
        for source in sources:
            try:
                self.owner._check()
                key = source
                alternative = self._alternatives.get(key)
                if alternative is None:
                    alternative = self._connect(source)
                    if self._edge_count + len(alternative.edges) > self.owner.budget.max_namespace_facts:
                        raise OverflowError('conditional implementation interface relation budget exhausted')
                    self._alternatives[key] = alternative
                    self._edge_count += len(alternative.edges)
                    for edge in alternative.edges:
                        self._before[edge.target][edge] = None
                        self._after[edge.source][edge] = None
                accepted.append(alternative)
                notes[Frontier(call, 'TYPE_CALL_PHYSICAL_ABI_AND_CALLBACKS_OPEN',
                    'The conditional standard protocol preserves logical operands/world; physical ABI '
                    'materialization, native-slot targets and Python callback bindings are not established.')] = None
            except (OverflowError, TimeoutError) as error:
                notes[Frontier(call, 'TYPE_CALL_IMPLEMENTATION_BUDGET', type(error).__name__ + ': ' + str(error))] = None
                break
        self._notes[call] = tuple(notes)
        self._last = call, tuple(accepted)

    def _neighbors(self, point, outgoing):
        rows = self._after if outgoing else self._before
        edges = tuple(rows.get(point, ()))
        notes = self._notes.get(point, ())
        if (not edges and point.node in self._provider_ports.get(point.namespace, ())):
            notes = (*notes, Frontier(point, 'TYPE_CALL_IMPLEMENTATION_CONTEXT_OPEN',
                'This original implementation interface has no matching selected class-call frame '
                'in the supplied context; no actual argument or result absence is proved.'))
        return Neighborhood(edges, notes, not notes)

    def incoming(self, point):
        return self._neighbors(point, False)

    def outgoing(self, point):
        return self._neighbors(point, True)

    def measurements(self):
        return {'implementation_graphs': len(self._providers), 'invocation_alternatives': len(self._alternatives),
            'interface_edges': self._edge_count, 'target_executed': False,
            'physical_abi_mapping_complete': False, 'python_callbacks_connected': False}

    def clear(self):
        self._providers.clear(); self._before.clear(); self._after.clear()
        self._provider_ports.clear()
        self._alternatives.clear(); self._notes.clear(); self._last = None


def validate_type_call_alternative(resolver, alternative):
    """Fresh source/protocol checks and original input/return relation replay."""
    from scar.analysis.contextual_class_sources import validate_class_statement_source
    from scar.analysis.static_type_call import validate_type_call_provider
    from scar.ir.program.type_calls import TypeCallProvider
    if type(alternative) is not ContextualTypeCall:
        raise TypeError('expected a conditional type-call alternative')
    alternative.__post_init__()
    validate_class_statement_source(resolver, alternative.source)
    body = resolver.session.load(alternative.provider)
    metadata = dict(body.document['provider'])
    metadata['graph'] = encode(body.graph)
    validate_type_call_provider(decode(TypeCallProvider, metadata))
    expected = resolver.type_calls._connect(alternative.source)
    if expected != alternative:
        raise ValueError('type-call alternative differs from its original source, protocol or port mapping')
    return True


__all__ = ['ContextualTypeCall', 'ContextualTypeCallImplementations', 'validate_type_call_alternative']
