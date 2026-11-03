"""Composable views of retained loop ports, without CFG or iteration copies.

Header arguments are phi-like static ports, not runtime values or iteration
identities. Forwarding a binding/reference does not preserve referent contents;
a different SSA ID does not prove a different numerical value. Source nesting
is lexical only. The owning region is the original body region, not a newly
constructed LoopRegion or a complete loop-membership/exit closure.
"""
from __future__ import annotations

from collections import defaultdict
from dataclasses import dataclass

from scar.ir.program.dependencies import GraphNamespace
from scar.ir.program.ids import BlockID, ValueID, UseID
from scar.ir.program.model import BlockArgument, CompletionResult, LocalBindingValue, StateVersionValue, value_type
from scar.ir.program.source_call_bindings import SourceBodyNamespace
from scar.ir.program.structured import ControlEdgeReference, LoopBindingPort, LoopInterface, StructuredBodyModel
from scar.ir.record_codec import decode
from scar.ir.v2.common import SourceReference
from scar.ir.v2.ids import OperationDefinitionID


class LoopViewUnavailable(ValueError):
    """A retained source body has no recorded structured-loop interface."""


def _need(ok, detail):
    if not ok:
        raise ValueError('loop template view: ' + detail)


@dataclass(frozen=True, slots=True)
class LoopSlotRoute:
    index: int
    formal: ValueID
    actual: UseID | CompletionResult
    actual_value: ValueID | None
    is_world: bool
    ssa_relation: str
    content_invariance: str = 'UNPROVED'

    def __post_init__(self):
        _need(type(self.index) is int and self.index >= 0 and type(self.formal) is ValueID
            and type(self.actual) in (UseID, CompletionResult) and type(self.is_world) is bool
            and type(self.ssa_relation) is str,
            'slot needs exact original index, formal, actual and world classification')
        if type(self.actual) is UseID:
            _need(type(self.actual_value) is ValueID and self.ssa_relation in
                ('INITIAL', 'FORWARDED', 'REDEFINED'), 'Use route lost its original value')
        else:
            _need(self.actual_value is None and self.ssa_relation == 'COMPLETION_OUTPUT',
                'a completion slot cannot be replaced by an invented SSA value')
        _need(self.content_invariance == 'UNPROVED', 'port structure cannot prove content invariance')


@dataclass(frozen=True, slots=True)
class LoopPortRoute:
    edge: ControlEdgeReference
    origin: BlockID
    target: BlockID
    slots: tuple[LoopSlotRoute, ...]

    def __post_init__(self):
        _need(type(self.edge) is ControlEdgeReference and type(self.origin) is BlockID
            and type(self.target) is BlockID and type(self.slots) is tuple
            and all(type(slot) is LoopSlotRoute for slot in self.slots), 'typed original control route required')
        self.edge.__post_init__()
        for slot in self.slots:
            slot.__post_init__()
        _need(tuple(slot.index for slot in self.slots) == tuple(range(len(self.slots)))
            and len({slot.formal for slot in self.slots}) == len(self.slots), 'header slot order changed')


@dataclass(frozen=True, slots=True)
class LoopTemplateView:
    namespace: GraphNamespace
    definition: OperationDefinitionID
    loop: LoopInterface
    initial_routes: tuple[LoopPortRoute, ...]
    backedge_routes: tuple[LoopPortRoute, ...]
    lexical_parent: SourceReference | None
    nested_sources: tuple[SourceReference, ...]
    content_invariance: str = 'UNPROVED'
    scope_complete: bool = False
    independent_loop_region: bool = False
    iterations_unrolled: bool = False

    def __post_init__(self):
        _need(type(self.namespace) is GraphNamespace and type(self.definition) is OperationDefinitionID
            and type(self.loop) is LoopInterface, 'original source namespace/definition/loop required')
        self.namespace.__post_init__(); self.loop.__post_init__()
        _need(self.namespace.source_body is not None
            and self.definition == self.namespace.source_body.definition
            and self.loop.region == self.namespace.root, 'loop changed its original owning body')
        for routes in (self.initial_routes, self.backedge_routes):
            _need(type(routes) is tuple and all(type(route) is LoopPortRoute for route in routes),
                'loop routes must be immutable original ports')
            for route in routes:
                route.__post_init__()
                _need(route.target == self.loop.header, 'route does not land at the original header')
        _need(tuple(route.edge for route in self.backedge_routes) == self.loop.backedges
            and not set(route.edge for route in self.initial_routes).intersection(self.loop.backedges),
            'initial and backedge routes changed their original partition')
        _need((self.lexical_parent is None or type(self.lexical_parent) is SourceReference)
            and type(self.nested_sources) is tuple
            and all(type(source) is SourceReference for source in self.nested_sources), 'typed lexical source references required')
        _need(self.content_invariance == 'UNPROVED' and self.scope_complete is False
            and self.independent_loop_region is False and self.iterations_unrolled is False,
            'loop interface view cannot assert content, coverage or runtime iteration proofs')


def _contains(outer, inner):
    start = lambda source: (source.start_line, source.start_column)
    end = lambda source: (source.end_line, source.end_column)
    return ((outer.path, outer.fingerprint) == (inner.path, inner.fingerprint)
        and start(outer) <= start(inner) and end(inner) <= end(outer)
        and (start(outer), end(outer)) != (start(inner), end(inner)))


def loop_template_views(body):
    """Expose every recorded loop and all its original header incoming slots.

    ``body`` is a normal session-loaded, receipt-checked source body. No source
    parsing, new ProgramIndex, CFG construction, target execution or caching is
    performed here. Missing structured evidence raises instead of meaning zero
    loops; even an empty recorded collection is not a whole-source coverage proof.
    """
    if type(body.namespace) is not SourceBodyNamespace:
        raise LoopViewUnavailable('source-body namespace is not recorded for this graph')
    if body.document.get('structured') is None:
        raise LoopViewUnavailable('structured loop interfaces are NOT_RECORDED for this body')
    model = decode(StructuredBodyModel, body.document['structured'])
    namespace = GraphNamespace.from_source(body.namespace)
    index = body.index
    _need(index.graph is body.graph and model.definition == body.namespace.definition
        and model.region == body.namespace.region == body.graph.root,
        'structured definition, region and index differ from the original body')
    _need(body.namespace.source is None or model.source == body.namespace.source,
        'structured source differs from the original body declaration')
    _need(len({loop.header for loop in model.loops}) == len(model.loops)
        and len({loop.source for loop in model.loops}) == len(model.loops), 'duplicate loop interface')
    headers = {loop.header for loop in model.loops}
    incoming = defaultdict(dict)
    for operation in body.graph.operations:
        if operation.terminator is None:
            continue
        for ordinal, successor in enumerate(operation.terminator.successors):
            if successor.block in headers:
                incoming[successor.block][ControlEdgeReference(operation.id, ordinal)] = (operation, successor)

    def route(loop, edge, operation, successor, backedge):
        origin = index._operation_blocks[operation.id]
        _need(index._blocks[origin] == index._blocks.get(loop.header) == loop.region
            and successor.block == loop.header, 'header incoming edge crosses another region')
        formals = index._block_records[loop.header].arguments
        _need(len(formals) == len(successor.arguments), 'header incoming arity differs')
        slots = []
        for position, (formal, actual) in enumerate(zip(formals, successor.arguments)):
            value = index.values[formal]
            _need(type(value.origin) is BlockArgument and value.origin.block == loop.header
                and value.origin.index == position, 'formal is not its original ordered header argument')
            actual_value = None
            if type(actual) is UseID:
                use = index.use_site(actual)
                _need(use.operation == operation.id, 'incoming Use belongs to another operation')
                actual_value = use.use.value
                _need(value_type(index.values[actual_value]) == value_type(value), 'incoming Use type differs')
                relation = ('FORWARDED' if actual_value == formal else 'REDEFINED') if backedge else 'INITIAL'
            else:
                _need(type(actual) is CompletionResult, 'unsupported non-Use header input')
                signatures = [item for item in operation.completions if item.kind == successor.kind]
                _need(len(signatures) == 1 and actual.index < len(signatures[0].types)
                    and signatures[0].types[actual.index] == value_type(value), 'completion slot/type differs')
                relation = 'COMPLETION_OUTPUT'
            slots.append(LoopSlotRoute(position, formal, actual, actual_value,
                type(value) is StateVersionValue, relation))
        return LoopPortRoute(edge, origin, successor.block, tuple(slots))

    result = []
    for loop in model.loops:
        _need(loop.region == model.region and index._blocks.get(loop.header) == loop.region
            and all(index._blocks.get(block) == loop.region for block in
                (loop.body_entry, loop.natural_exit, *((loop.after,) if loop.after is not None else ()))),
            'loop control ports are not in their original region')
        _need((loop.source.path, loop.source.fingerprint) == (model.source.path, model.source.fingerprint)
            and _contains(model.source, loop.source), 'loop source is outside its original body')
        arcs = incoming[loop.header]
        formals = tuple(index.values[value] for value in index._block_records[loop.header].arguments)
        _need(loop.bindings == tuple(LoopBindingPort(value.slot, value.id) for value in formals
            if type(value) is LocalBindingValue), 'declared local binding ports differ from the header')
        _need(set(loop.backedges) <= arcs.keys(), 'declared backedge is not an original header incoming edge')
        initial = tuple(route(loop, edge, *ports, False) for edge, ports in arcs.items() if edge not in loop.backedges)
        carried = tuple(route(loop, edge, *arcs[edge], True) for edge in loop.backedges)
        parents = [other.source for other in model.loops if _contains(other.source, loop.source)]
        parent = min(parents, key=lambda source: (-source.start_line, -source.start_column,
            source.end_line, source.end_column)) if parents else None
        result.append((loop, initial, carried, parent))
    return tuple(LoopTemplateView(namespace, model.definition, loop, initial, carried, parent,
        tuple(child.source for child, _, _, owner in result if owner == loop.source))
        for loop, initial, carried, parent in result)


__all__ = ['LoopViewUnavailable', 'LoopSlotRoute', 'LoopPortRoute', 'LoopTemplateView', 'loop_template_views']
