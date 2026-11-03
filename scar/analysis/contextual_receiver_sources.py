"""Independent receiver-source traversals over the shared reference graph.

These walks explain the operand of an attribute request. They never extend a
callable's identity path and do not select a descriptor, class or method.
"""
from __future__ import annotations

from collections import deque
from dataclasses import dataclass

from scar.analysis.program_dependencies import DependencyWalk
from scar.ir.program.dependencies import (
    DependencyFrontier as Frontier, DependencyPoint as Point, GraphNamespace,
)
from scar.ir.program.ids import ValueID
from scar.ir.program.model import ExactLiteralOrigin, LiteralOrigin
from scar.ir.program.static_calls import StaticAttributeAccess, StaticImportFromRead


@dataclass(frozen=True, slots=True)
class ReceiverEvidence:
    lookup: StaticAttributeAccess
    walk: DependencyWalk

    def __post_init__(self):
        if type(self.lookup) is not StaticAttributeAccess or type(self.walk) is not DependencyWalk:
            raise TypeError('receiver evidence needs an original attribute read and dependency walk')
        if (self.lookup.result is None or self.walk.direction != 'incoming'
                or len(self.walk.roots) != 1 or self.walk.roots[0].node != self.lookup.receiver
                or self.walk.roots[0].namespace != GraphNamespace.from_source(self.lookup.body)):
            raise ValueError('receiver evidence must start at the original receiver Use')


def attribute_read_at(resolver, point):
    """Reuse the original per-body source index; IMPORT_FROM is not Attribute."""
    if type(point.node) is not ValueID or point.namespace.source_body is None:
        return None
    body = resolver._body(point.namespace)
    read = resolver.modules._index(body).reads.get(point.node)
    return read if type(read) is StaticAttributeAccess else None


def _stop(resolver, point):
    """Classify only an endpoint with no legal incoming reference route."""
    if type(point.node) is not ValueID:
        return ('RECEIVER_REFERENCE_SOURCE_RULE_OPEN',
            'No legal original reference-source route is available for this receiver endpoint.')
    index = resolver.session.index(point.namespace)
    value = index.values[point.node]
    if type(value.origin) in (LiteralOrigin, ExactLiteralOrigin):
        return ('RECEIVER_LITERAL_SOURCE',
            'The original endpoint has a literal origin; this does not resolve its attribute dispatch.')
    if point.namespace.source_body is None:
        return ('RECEIVER_REFERENCE_SOURCE_RULE_OPEN',
            'This original provider endpoint has no selected further reference-source route.')
    body = resolver._body(point.namespace)
    interface = body.interface
    if interface is not None:
        formals = [port for port in interface.parameters if port.value == point.node]
        if formals:
            port, = formals
            definition = body.context.definitions.get(interface.definition)
            signature = definition[1] if definition is not None else None
            names = [parameter.name for parameter in signature.parameters
                     if parameter.slot == port.slot] if signature is not None else []
            return ('RECEIVER_ENTRY_FORMAL_UNBOUND',
                'Original formal slot ' + port.slot.wire +
                (' (' + names[0] + ')' if len(names) == 1 else '') +
                ' has no legal selected caller source; its spelling proves no receiver type.')
    facts = resolver.modules._index(body)
    producer = facts.normal_producers.get(point.node)
    if type(facts.reads.get(point.node)) is StaticAttributeAccess:
        return ('RECEIVER_ATTRIBUTE_RESULT_RULE_OPEN',
            'The receiver is another original attribute-read result; descriptor/lookup selection is not established.')
    if type(facts.reads.get(point.node)) is StaticImportFromRead:
        return ('RECEIVER_IMPORT_FROM_RESULT_RULE_OPEN',
            'The original FROM member-read result has no further selected legal source; import fallback and binding state remain open.')
    if producer in facts.imports or producer in facts.from_requests:
        return ('RECEIVER_IMPORT_MODULE_SOURCE',
            'The endpoint is an original import-request result; module selection, hooks and current state remain conditional.')
    if producer in resolver._calls(body):
        return ('RECEIVER_CALL_RESULT_ORIGIN_OPEN',
            'The original CALL normal result has no further selected legal return-reference route; no result type is inferred.')
    if facts.protocols.get(producer) in ('MAKE_FUNCTION_314', 'MAKE_NESTED_FUNCTION'):
        return ('RECEIVER_FUNCTION_FACTORY_SOURCE',
            'The endpoint is an original function-factory result; no receiver class or attribute dispatch follows from that source.')
    return ('RECEIVER_REFERENCE_SOURCE_RULE_OPEN',
        'The original receiver producer is retained, but no legal reference-source transfer is available at this endpoint.')


def walk_reference_sources(resolver, root, initial_frontiers=()):
    """One reference traversal for lookup operands, retaining bounded prefixes."""
    from scar.analysis.contextual_call_resolution import REFERENCE_KINDS
    if type(root) is not Point or type(initial_frontiers) is not tuple or any(
            type(frontier) is not Frontier for frontier in initial_frontiers):
        raise TypeError('reference walk needs an original root and typed initial frontiers')
    pending = deque((root,))
    seen, edges, notes = {}, {}, dict.fromkeys(initial_frontiers)
    exhausted = True
    limit = resolver.owner.budget.max_resolution_steps

    def note(point, kind, detail):
        item = Frontier(point, kind, detail)
        notes[item] = None

    while pending:
        point = pending.popleft()
        if point in seen:
            continue
        if len(seen) >= limit:
            note(point, 'RECEIVER_REFERENCE_POINT_BUDGET',
                'Additional receiver-source endpoints remain beyond the shared resolution-step ceiling.')
            exhausted = False
            break
        seen[point] = None
        try:
            resolver.owner._check()
            neighborhood = resolver.session.graph().incoming(point, kinds=REFERENCE_KINDS)
            exhausted = exhausted and neighborhood.enumerated
            notes.update((item, None) for item in neighborhood.frontiers)
            parents = []
            edge_budget = False
            for edge in neighborhood.edges:
                if not resolver._transport(edge):
                    continue
                if edge not in edges and len(edges) >= 4 * limit:
                    note(point, 'RECEIVER_REFERENCE_EDGE_BUDGET',
                        'Additional original receiver-source edges exceed the bounded traversal ceiling.')
                    exhausted = False
                    pending.clear()
                    edge_budget = True
                    break
                edges[edge] = None
                parents.append(edge.source)
            if edge_budget:
                break
            if parents:
                pending.extend(parent for parent in parents if parent not in seen)
            else:
                kind, detail = _stop(resolver, point)
                note(point, kind, detail)
        except (OverflowError, TimeoutError) as error:
            note(point, 'RECEIVER_REFERENCE_BUDGET', type(error).__name__ + ': ' + str(error))
            exhausted = False
            break
    # Enum order gives stable standard exports while keeping the actual edges
    # and their conditions/evidence/context objects unchanged.
    from scar.ir.program.dependencies import DependencyKind
    return DependencyWalk((root,), tuple(seen), tuple(edges), tuple(notes), 'incoming', exhausted,
        tuple(kind for kind in DependencyKind if kind in REFERENCE_KINDS))


def collect_receiver_evidence(resolver, lookup, context):
    """Explain an Attribute receiver without treating it as the lookup value."""
    if type(lookup) is not StaticAttributeAccess or lookup.result is None:
        raise TypeError('receiver demand requires an actual original attribute read')
    namespace = GraphNamespace.from_source(lookup.body)
    root = Point(namespace, lookup.receiver, context)
    initial = (Frontier(Point(namespace, lookup.result, context), 'ATTRIBUTE_DISPATCH_RULE_OPEN',
        'Receiver evidence is an independent operand query for source spelling ' +
        repr(lookup.field) + '; it is not a callable-identity edge, actual private lookup name, '
        'receiver type or descriptor-selection proof.'),)
    walk = walk_reference_sources(resolver, root, initial)
    return ReceiverEvidence(lookup, walk)


__all__ = ['ReceiverEvidence', 'attribute_read_at', 'collect_receiver_evidence', 'walk_reference_sources']
