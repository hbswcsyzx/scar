"""Independent finite-height scalar fields, without source-solver admission.

Only original GlobalPorts and LanguageOperationSites are referenced.  A small
retained literal set supplies conditional may witnesses; open content is a
field property, never an invented unknown object or source operation.  Worlds
remain on the original site and do not become scalar-reference aliases.
"""
from collections import defaultdict, deque
from dataclasses import dataclass, field
from itertools import product

from scar.analysis.constants_v2 import ConstantStatus
from scar.analysis.source_builtin_values import BuiltinValueEvaluator
from scar.ir.literals import PythonLiteral, _preflight_literal, literal_builtin_type
from scar.ir.program import normal_links as F, normal_targets as T, scalar_values as V


@dataclass(slots=True)
class _Field:
    literals: dict = field(default_factory=dict)
    builtin_types: set = field(default_factory=set)
    content_open: bool = False
    widened: bool = False


@dataclass(frozen=True, slots=True)
class _Junction:
    """Private transfer index; never an identity in the program graph."""
    key: object


def _requirements(values):
    # The reused kernel owns legacy report enums. Convert them at this
    # analysis boundary; the canonical IR never imports an analysis module.
    return tuple(sorted({V.ScalarRuntimeRequirement(item.value) for item in values},
                        key=lambda item: item.value))


class ScalarValueFlow:
    """Monotone bounded fields; draining proves only this agenda is empty.

    Per port, at most K literals are admitted, each with a finite set of
    runtime requirements.  Open/widened flags only grow.  Operator premises
    range over those bounded sets, so feedback such as x = x + 1 terminates.
    Source and derivation witnesses establish neither must values nor identity.
    """

    def __init__(self, *, limit=4, evaluator=None):
        if type(limit) is not int or limit < 1:
            raise ValueError('literal limit must be a positive exact integer')
        if evaluator is not None and type(evaluator) is not BuiltinValueEvaluator:
            raise TypeError('the fixed BuiltinValueEvaluator is required')
        self.limit = limit
        self.evaluator = BuiltinValueEvaluator() if evaluator is None else evaluator
        self._fields = {}
        self._junction_fields = {}
        self._groups = {}
        self._operations = {}
        self._supported = {}
        self._watch = defaultdict(set)
        self._adj = defaultdict(set)
        self._agenda = deque()
        self._queued = set()
        self._processed = defaultdict(dict)
        self._sources = {}
        self._derivations = {}
        self._obligations = {}
        self._events = 0

    def _field(self, port):
        if type(port) is not T.GlobalPort:
            raise TypeError('an original GlobalPort is required')
        return self._state(port)

    def _state(self, port):
        if type(port) is _Junction:
            return self._junction_fields[port]
        if type(port) is not T.GlobalPort:
            raise TypeError('an original GlobalPort is required')
        if port not in self._fields:
            self._fields[port] = _Field()
        return self._fields[port]

    def _enqueue(self, kind, key):
        event = kind, key
        if event not in self._queued:
            self._queued.add(event)
            self._agenda.append(event)

    def _mark_open(self, port):
        state = self._state(port)
        if state.content_open:
            return False
        state.content_open = True
        self._enqueue('port', port)
        return True

    def _accept(self, port, literal, requirements=()):
        state = self._state(port)
        builtin = literal_builtin_type(literal)
        changed = self._accept_types(port, (builtin.__module__ + '.' + builtin.__qualname__,))
        if literal in state.literals:
            previous = state.literals[literal]
            merged = frozenset((*previous, *requirements))
            if merged != previous:
                state.literals[literal] = merged
                self._enqueue('port', port)
                changed = True
            return changed
        if state.widened:
            return changed
        if len(state.literals) >= self.limit:
            state.widened = True
            self._mark_open(port)
            self._enqueue('port', port)
            if type(port) is T.GlobalPort:
                self._obligations['limit', port] = V.ScalarObligation(port,
                    V.ScalarObligationKind.LITERAL_LIMIT,
                    'per-port literal limit exceeded: ' + str(self.limit))
            return True
        state.literals[literal] = frozenset(requirements)
        self._enqueue('port', port)
        return True

    def _accept_types(self, port, types):
        state = self._state(port)
        new = set(types) - state.builtin_types
        if not new:
            return False
        state.builtin_types.update(new)
        self._enqueue('port', port)
        return True

    def offer(self, port, literal):
        """Admit a direct literal observation, not an object-identity fact."""
        if type(literal) is not PythonLiteral:
            raise TypeError('a typed PythonLiteral is required')
        _preflight_literal(literal)
        changed = self._accept(port, literal)
        if literal in self._field(port).literals:
            self._sources[port, literal] = V.ScalarLiteralSource(port, literal)
        return changed

    def open(self, port, reason):
        if type(reason) is not str or not reason:
            raise ValueError('an open scalar field needs a nonempty reason')
        self._field(port)
        self._obligations['source_open', port, reason] = V.ScalarObligation(port,
            V.ScalarObligationKind.SOURCE_OPEN, reason)
        return self._mark_open(port)

    def connect(self, source, target):
        """Forward scalar fields without asserting reference equality."""
        self._field(source)
        self._field(target)
        if source == target or target in self._adj[source]:
            return False
        self._adj[source].add(target)
        self._enqueue('port', source)
        return True

    def connect_group(self, key, group):
        """Store O(inputs + outputs), without expanding their product.

        A bounded private join shares the union of scalar alternatives. Its
        widening is propagated as open content, never as a complete value.
        """
        if type(group) is not V.ScalarTransferGroup:
            raise TypeError('a typed scalar transfer group is required')
        if not group.sources or not group.targets:
            raise ValueError('a scalar transfer group needs both endpoints')
        if key in self._groups:
            if self._groups[key] != group:
                raise ValueError('scalar transfer key selects another relation')
            return False
        for port in (*group.sources, *group.targets):
            self._field(port)
        junction = _Junction(key)
        self._junction_fields[junction] = _Field()
        self._groups[key] = group
        self._adj[junction].update(group.targets)
        for source in group.sources:
            self._adj[source].add(junction)
            self._enqueue('port', source)
        return True

    def register(self, key, site):
        if type(site) is not T.LanguageOperationSite:
            raise TypeError('an original LanguageOperationSite is required')
        if (type(site.operands) is not tuple or any(type(p) is not T.GlobalPort
                for p in (*site.operands, site.result, site.world, site.result_world))):
            raise TypeError('language operation interfaces require original GlobalPorts')
        opcode = self.evaluator.opcode_for(site.action, site.selector)
        if key in self._operations:
            if self._operations[key] != site:
                raise ValueError('scalar operation key selects another source interface')
            return False
        self._operations[key] = site
        self._field(site.result)
        for operand in site.operands:
            self._field(operand)
            self._watch[operand].add(key)
        arity = 1 if site.action is F.LanguageOperationKind.UNARY else 2
        self._supported[key] = opcode is not None and len(site.operands) == arity
        if not self._supported[key]:
            self._obligations['unsupported', key] = V.ScalarObligation(site.result,
                V.ScalarObligationKind.UNSUPPORTED_OPERATOR,
                'no fixed builtin checker for the original operator/signature',
                site=site, inputs=site.operands, status=V.ScalarEvaluationStatus.NOT_CONSTANT)
            self._mark_open(site.result)
        self._enqueue('operation', key)
        return True

    def _forward(self, source):
        state = self._state(source)
        for target in tuple(self._adj.get(source, ())):
            for literal, requirements in tuple(state.literals.items()):
                self._accept(target, literal, requirements)
            self._accept_types(target, state.builtin_types)
            if state.content_open:
                if type(target) is T.GlobalPort:
                    self._obligations['upstream', source, target] = V.ScalarObligation(target,
                        V.ScalarObligationKind.UPSTREAM_OPEN, 'upstream scalar content is open',
                        inputs=(source,) if type(source) is T.GlobalPort else ())
                self._mark_open(target)
        for key in tuple(self._watch.get(source, ())):
            self._enqueue('operation', key)

    def _evaluate(self, key):
        site = self._operations[key]
        states = tuple(self._field(p) for p in site.operands)
        if any(state.content_open for state in states):
            self._obligations['operand_open', key] = V.ScalarObligation(site.result,
                V.ScalarObligationKind.OPERAND_OPEN, 'operand scalar content is open',
                site=site, inputs=site.operands)
            self._mark_open(site.result)
        if not self._supported[key]:
            return
        if any(not state.literals for state in states):
            self._obligations['input_absent', key] = V.ScalarObligation(site.result,
                V.ScalarObligationKind.INPUT_LITERAL_ABSENT,
                'an original operand has no retained literal candidate',
                site=site, inputs=site.operands)
            return
        self._obligations.pop(('input_absent', key), None)
        for literals in product(*(tuple(state.literals) for state in states)):
            if self._field(site.result).widened and (key, literals) not in self._derivations:
                continue
            inherited = frozenset(r for state, literal in zip(states, literals)
                                 for r in state.literals[literal])
            if self._processed[key].get(literals) == inherited:
                continue
            self._processed[key][literals] = inherited
            premises = tuple(V.ScalarPremise(port, literal,
                _requirements(state.literals[literal]))
                for port, state, literal in zip(site.operands, states, literals))
            outcome = self.evaluator.evaluate(site.action, site.selector, literals)
            requirements = _requirements((*inherited, *outcome.requirements))
            if outcome.status is ConstantStatus.CONSTANT:
                self._accept(site.result, outcome.literal, requirements)
                if outcome.literal in self._field(site.result).literals:
                    self._derivations[key, literals] = V.ScalarDerivation(site,
                        premises, V.ScalarPremise(site.result, outcome.literal, requirements),
                        requirements)
            else:
                self._obligations['evaluation', key, literals] = V.ScalarObligation(site.result,
                    V.ScalarObligationKind.EVALUATION_FAILURE, outcome.reason,
                    site=site, inputs=site.operands, premises=premises,
                    status=V.ScalarEvaluationStatus(outcome.status.value), exception=outcome.exception,
                    requirements=requirements)
                if outcome.status is not ConstantStatus.KNOWN_EXCEPTION:
                    self._mark_open(site.result)

    def drain(self):
        """Reach the bounded field fixed point; obligations can remain open."""
        while self._agenda:
            event = self._agenda.popleft()
            self._queued.remove(event)
            self._events += 1
            kind, key = event
            if kind == 'port':
                self._forward(key)
            else:
                self._evaluate(key)
        return True

    def snapshot(self, port):
        state = self._field(port)
        return V.ScalarSnapshot(port, tuple(state.literals),
            tuple(sorted(state.builtin_types)), state.content_open, state.widened)

    def snapshots(self):
        """Publish original-port fields; private transfer joins stay private."""
        return (self.snapshot(port) for port in self._fields)

    def derivations(self):
        return tuple(self._derivations.values())

    def obligations(self):
        return tuple(self._obligations.values())

    def operations(self):
        return tuple(self._operations.values())

    def sources(self):
        return tuple(self._sources.values())

    def connections(self):
        return tuple(V.ScalarReferenceFlow(source, target)
            for source, targets in self._adj.items() for target in targets
            if type(source) is T.GlobalPort and type(target) is T.GlobalPort)

    def groups(self):
        return tuple(self._groups.values())

    @property
    def stats(self):
        return dict(ports=len(self._fields), operations=len(self._operations),
            connections=sum(len(v) for v in self._adj.values()),
            transfer_groups=len(self._groups), private_junctions=len(self._junction_fields),
            literals=sum(len(s.literals) for s in self._fields.values()),
            open_ports=sum(s.content_open for s in self._fields.values()),
            widened_ports=sum(s.widened for s in self._fields.values()),
            literal_limit=self.limit, events=self._events, pending=len(self._agenda),
            sources=len(self._sources), derivations=len(self._derivations),
            obligations=len(self._obligations), evaluator=self.evaluator.stats)


def collect_unit(unit: F.UnitFacts, flow=None, *, scopes=None):
    """Collect one retained unit's conditional constraints, without draining.

    Without scopes, collection does not admit or execute a body. With scopes,
    only original admitted table spans are collected, retaining row ordinals.
    Namespace joins are qualified by this unit; no cross-call inference occurs.
    Only referenced ports are decoded, with the original strict record codec.
    """
    from scar.ir.program import normal_graph as G, source_productions as P
    from scar.ir.record_codec import _decode, _record_tags

    flow = ScalarValueFlow() if flow is None else flow
    if type(flow) is not ScalarValueFlow:
        raise TypeError('a ScalarValueFlow is required')
    ports = {}
    tags = _record_tags(P.PRODUCTION_RECORD_TAGS)

    def records(table):
        rows = getattr(unit, table.value)
        if scopes is None:
            yield from enumerate(rows)
        else:
            for group in unit.scope_groups:
                if group.owner in scopes:
                    for span in group.tables:
                        if span.table is table:
                            yield from ((i, rows[i]) for i in range(span.start, span.stop))

    def gp(index):
        if type(index) is not int or not 0 <= index < len(unit.ports):
            raise ValueError('scalar fact references a port outside its original unit')
        if index not in ports:
            port = unit.ports[index]
            if type(port) is dict:
                port = _decode(G.Port, port, tags)
            elif type(port) is not G.Port:
                raise TypeError('original source port record required')
            ports[index] = T.GlobalPort(unit.unit, port)
        return ports[index]

    for _, constant in records(F.FactTable.CONSTANTS):
        flow.offer(gp(constant.value), constant.literal)
    for _, (source, target) in records(F.FactTable.ALIASES):
        flow.connect(gp(source), gp(target))
    namespaces = defaultdict(lambda: (set(), set()))
    namespace_rows = {}
    for index, access in records(F.FactTable.NAMES):
        namespace = access.namespace
        key = unit.unit, namespace.kind, namespace.owner, namespace.name
        namespaces[key][int(not access.write)].add(access.value)
        namespace_rows.setdefault(key, index)
    for key, (writes, reads) in namespaces.items():
        if writes and reads:
            kind, owner, name = key[1:]
            # Endpoint sets retain the exact relation; this private factor
            # avoids the quadratic writes x reads adjacency expansion.
            flow.connect_group(('unit.names', key), V.ScalarTransferGroup(
                'unit.names', namespace_rows[key], 'namespace/'+kind.value+'/'+str(owner)+'/'+name,
                tuple(gp(p) for p in sorted(writes)), tuple(gp(p) for p in sorted(reads)),
                ('FLOW_INSENSITIVE_SOURCE_NAMESPACE_ALTERNATIVES',
                 'SOURCE_SCOPE_AND_NAMESPACE_VERSION_SELECTION_REQUIRED')))
    for index, operation in records(F.FactTable.OPERATIONS):
        flow.register((unit.unit, index), T.LanguageOperationSite(
            operation.action, operation.selector,
            tuple(gp(p) for p in operation.operands), gp(operation.result),
            gp(operation.world), gp(operation.result_world)))
    return flow


__all__ = ['ScalarValueFlow', 'collect_unit']
