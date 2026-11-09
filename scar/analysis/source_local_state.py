"""Select local binding analyses from original access/owner types, not names."""
from scar.analysis.source_reference_slice import source_port
from scar.ir.program import normal_links as F, source_state as S


def local_read_tracks(state):
    """Return every function/slot pair this intraprocedural model can track.

    A capture is still an address interface: it is not silently analyzed as
    a slot of the reading activation. Different function creations can select
    the same body, so all original creation endpoints are retained.
    """
    functions = {}
    for function in state.source.facts.functions:
        if function.body_scope is not None:
            functions.setdefault((function.body_scope.owner, function.environment.scope), []).append(function)
    selected = {}
    for access in state.accesses:
        if access.kind is not S.BindingAccessKind.READ: continue
        for alternative in access.alternatives:
            descriptor = state.locations[alternative.location].interface
            if descriptor.kind != 'LEXICAL_BINDING': continue
            slot = state.bindings.bindings[descriptor.binding]
            if slot.domain != 'LOCAL_BINDING': continue
            namespace = F.Namespace(F.NamespaceKind.LEXICAL, descriptor.binding, state._name(slot.name))
            for function in functions.get((access.scope, slot.owner), ()):
                endpoint = source_port(state.source.facts, function.value)
                selected.setdefault((endpoint, namespace), None)
    return tuple(selected)


def track_local_reads(state, **limits):
    """Solve each selected pair once, sharing the provider's anchors/bodies."""
    selected = local_read_tracks(state)
    for function, namespace in selected: state.track(function, namespace, **limits)
    return selected
