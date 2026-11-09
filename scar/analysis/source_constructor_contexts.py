"""Project constructor class alternatives without rebinding or entering bodies.

A compatible init receiver may belong to a subclass of the requested class.
Original entry/step references and connection guards remain the authority for
each alternative; shared source definitions do not identify runtime objects.
"""
from scar.ir.program import declared_contexts as D, normal_targets as T
from scar.ir.program import source_constructor_contexts as X, source_constructor_interfaces as C


_GUARDS = (
    'PARENT_CONSTRUCTOR_ENTRY_AND_STAGE_ALTERNATIVE_SELECTED',
    'MRO_DESCRIPTOR_AND_OVERRIDE_SELECTION_NOT_ESTABLISHED',
    'CLASS_INPUT_IS_NOT_EXACT_RUNTIME_CLASS_OR_OBJECT_IDENTITY_PROOF',
    'SHARED_SOURCE_DEFINITION_NOT_SELECTED_RUNTIME_INVOCATION',
    'SOURCE_NEW_DOES_NOT_ESTABLISH_ALLOCATION_OR_INITIALIZATION',
)


def _index(rows, ordinal):
    if type(ordinal) is not int or not 0 <= ordinal < len(rows):
        raise ValueError('constructor context index is outside its original parent table')
    return rows[ordinal]


def constructor_context_inputs(graph):
    """Retain every normal source entry and its provable single-argument shape.

    Root.entry and frontier.entry select the original parent entries table,
    whose step retains source_class, evidence, original site and connection.
    No original stage, object reference, world or parameter route is replaced.
    """
    if type(graph) is not C.ConstructorInterfaceGraph:
        raise TypeError('constructor class inputs require the original typed interface graph')
    roots = []; frontiers = []; frontier_ids = set()

    def frontier(entry, reason):
        if (entry, reason) not in frontier_ids:
            frontier_ids.add((entry, reason)); frontiers.append(X.ConstructorClassInputFrontier(entry, reason))

    for ordinal, entry in enumerate(graph.entries):
        step = _index(graph.steps, entry.step)
        _index(graph.sites, step.site)
        link = step.link; connection = entry.connection
        if link.stage not in (T.ConstructionStage.SOURCE_NEW, T.ConstructionStage.SOURCE_INIT):
            frontier(ordinal, 'NON_SOURCE_CONSTRUCTOR_STAGE_HAS_NO_SOURCE_CLASS_BODY_ENTRY')
            continue
        if link.connection != connection:
            raise ValueError('constructor class entry changed its original stage function connection')
        if connection.activation is not T.FunctionActivation.NORMAL:
            frontier(ordinal, 'DEFERRED_BODY_CREATION_IS_NOT_BODY_ENTRY')
            continue
        if (type(link.source_class) is not T.GlobalPort
                or connection.body.unit != connection.source_callable.unit):
            raise ValueError('constructor class or source body lacks its original qualified identity')
        new = link.stage is T.ConstructionStage.SOURCE_NEW
        required = 'NEW_RECEIVES_SOURCE_CLASS' if new else 'NEW_RESULT_IS_REQUESTED_CLASS_INSTANCE'
        if required not in link.conditions or required not in connection.conditions:
            raise ValueError('constructor class compatibility lost its original stage guard')
        source = link.source_class if new else T.ConstructionPort(
            link.result, link.source_class, T.ConstructionPortKind.NEW_RESULT)
        kind = D.ClassValueKind.CLASS_OBJECT if new else D.ClassValueKind.INSTANCE
        inputs = []
        for route in connection.parameters:
            if route.kind in (T.RouteKind.PACK_POSITIONALS, T.RouteKind.PACK_KEYWORDS):
                # Unrelated argument packs remain in the parent interface;
                # they are not missing evidence for this known class source.
                if source in route.actuals:
                    frontier(ordinal, route.kind.value+'_IS_PACK_DEPENDENCY_NOT_SINGLE_CLASS_REFERENCE')
                continue
            if route.kind is T.RouteKind.CLASS_RECEIVER:
                if source in route.actuals:
                    frontier(ordinal, 'CLASS_RECEIVER_IS_TYPE_PROJECTION_NOT_ARGUMENT_REFERENCE')
                continue
            if route.kind is not T.RouteKind.ARGUMENT:
                if source in route.actuals:
                    frontier(ordinal, 'CLASS_SOURCE_REQUIRES_ARGUMENT_ROUTE_NOT_'+route.kind.value)
                continue
            if len(route.actuals) > 1:
                if source in route.actuals:
                    frontier(ordinal, 'MULTI_ACTUAL_ARGUMENT_ROUTE_IS_NOT_SINGLE_CLASS_REFERENCE')
                continue
            if route.actuals != (source,):
                continue
            if type(route.formal) is not T.GlobalPort or route.formal.unit != connection.body.unit:
                raise ValueError('constructor class input formal belongs to a different original body')
            value = D.ClassInput(route.formal, link.source_class, kind)
            if value not in inputs:
                inputs.append(value)
        if not inputs:
            frontier(ordinal, 'CONSTRUCTOR_CLASS_SOURCE_NOT_BOUND_BY_SINGLE_ARGUMENT_ROUTE')
        context = D.DeclaredContext(connection.source_callable, connection.body, tuple(inputs))
        extra = ('REQUESTED_CLASS_COMPATIBILITY_DOES_NOT_ESTABLISH_EXACT_RETURNED_CLASS',) if not new else (
            'SOURCE_CLASS_OBJECT_ARGUMENT_IS_NOT_ALLOCATED_INSTANCE',)
        roots.append(X.ConstructorClassInputRoot(ordinal, context,
            (*link.conditions, *connection.conditions, *_GUARDS, *extra)))
    return X.ConstructorClassInputGraph(tuple(roots), tuple(frontiers))
