"""Infer field-fed method interfaces without running global entry propagation."""
from collections import deque
from types import SimpleNamespace

from scar.analysis.source_reference_slice import source_port as _gp
from scar.analysis.source_function_connections import Invocation, connect
from scar.ir.program import normal_links as F, normal_targets as T
from scar.ir.program import source_reference_slices as R


def _ancestors(incoming, point):
    seen = {point}; pending = deque((point,))
    while pending:
        for source in incoming.get(pending.popleft(), ()):
            if source not in seen:
                seen.add(source); pending.append(source)
    return seen


def discover_field_calls(unit):
    """Recognize call <- method GET <- field GET through original alias wires.

    This structural view does not infer a callable or delete unmatched calls.
    Lexical/container/call-produced receiver patterns remain in the source graph.
    """
    reads = {}; incoming = {}; cache = {}
    for source, target in unit.aliases:
        incoming.setdefault(target, []).append(source)
    def ancestors(point):
        if point not in cache:
            cache[point] = _ancestors(incoming, point)
        return cache[point]
    for ordinal, access in enumerate(unit.attributes):
        if access.action is F.AttributeAction.GET:
            reads.setdefault(access.value, []).append(ordinal)
    result = []
    for call_index, call in enumerate(unit.calls):
        for value in ancestors(call.callee):
            for method_index in reads.get(value, ()):
                method = unit.attributes[method_index]
                for receiver in ancestors(method.receiver):
                    result.extend((call_index, method_index, field_index) for field_index in reads.get(receiver, ()))
    return tuple(sorted(set(result)))


class _InterfaceOnly:
    """Reuse the original signature binder while emitting no solver transfers."""
    def __init__(self, slicer, unit, function):
        self.store = slicer.store; self.offsets = self.store.offsets
        self.functions = {self.offsets[unit.unit]+function.value: (unit, function)}
        self.containers = SimpleNamespace(invocation_arguments=lambda invocation: None,
            bind_variadic=lambda *args, **kwargs: None, project_argument=lambda *args, **kwargs: None,
            watch_invocation=lambda *args, **kwargs: None)

    def gp(self, point):
        identity, local = self.store.locate(point)
        return _gp(self.store.load(identity), local)

    def edge(self, source, target): pass
    def add(self, point, value): pass


def infer_field_method(slicer, identity, call_index, method_index, field_index, *, write_units=(), **limits):
    unit, *_ = slicer.unit(identity)
    if (call_index, method_index, field_index) not in discover_field_calls(unit):
        raise ValueError('selected call does not have the declared field/method/alias structure')
    slices, flows, domain = slicer.fields(identity, field_index, write_units=write_units, **limits)
    slices = list(slices); methods = []; pending = []
    call = unit.calls[call_index]; method = unit.attributes[method_index]
    for flow_index, flow in enumerate(flows):
        # The field is mutable. Inspect its potential assigned reference in a
        # separate slice; never install write->read as an unconditional alias.
        value_slice = slicer.slice(flow.write_site.assigned, **limits)
        value_index = len(slices); slices.append(value_slice)
        for origin_index, origin in enumerate(value_slice.origins):
            if origin.kind != 'ALLOCATION_SITE_CANDIDATE':
                continue
            owner, class_local = slicer.local(origin.source_class)
            descriptor = next((c for c in owner.classes if c.value == class_local), None)
            if descriptor is None:
                pending.append('SOURCE_CLASS_DECLARATION_UNRESOLVED'); continue
            binding = F.Namespace(F.NamespaceKind.CLASS, descriptor.scope, method.name)
            writes = [(i, access) for i, access in enumerate(owner.names) if access.write and access.namespace == binding]
            if not writes:
                pending.append('INHERITED_OR_DYNAMIC_MEMBER_DECLARATION_UNRESOLVED'); continue
            for name_index, access in writes:
                member_slice = slicer.slice(_gp(owner, access.value), **limits)
                member_index = len(slices); slices.append(member_slice)
                for member_origin_index, member_origin in enumerate(member_slice.origins):
                    if member_origin.kind != 'FUNCTION_DEFINITION':
                        continue
                    point = member_slice.states[member_origin.state].port
                    provider, local = slicer.local(point)
                    function = next(f for f in provider.functions if f.value == local)
                    mini = _InterfaceOnly(slicer, provider, function)
                    offset = slicer.store.offsets[unit.unit]
                    invocation = Invocation(offset+call.callee, tuple(offset+p for p in call.positional),
                        tuple((name, offset+p) for name, p in call.keywords), offset+call.result,
                        offset+call.world, offset+call.result_world,
                        None if call.positional_pack is None else offset+call.positional_pack,
                        None if call.keyword_pack is None else offset+call.keyword_pack)
                    conditions = (*flow.conditions, *origin.conditions, *member_origin.conditions,
                        'ASSIGNED_REFERENCE_IS_SELECTED_FIELD_CONTENT',
                        'SOURCE_CLASS_NAMESPACE_SELECTS_DECLARED_MEMBER',
                        'STANDARD_PYTHON_FUNCTION_INSTANCE_DESCRIPTOR_SELECTED',
                        'DECLARED_REFERENCE_AND_CREATION_CONTEXT_GUARDS_HOLD')
                    connection = connect(mini, mini.offsets[provider.unit]+function.value, invocation,
                        offset+method.receiver, conditions=conditions)
                    if connection is None:
                        pending.append('DECLARED_METHOD_SIGNATURE_NOT_ACCEPTED'); continue
                    methods.append(R.DeclaredMethodInterface(slicer.fact(unit, 'calls', call_index),
                        slicer.fact(unit, 'attributes', method_index), slicer.fact(owner, 'names', name_index),
                        flow_index, value_index, origin_index, member_index, member_origin_index,
                        origin.source_class, connection, conditions))
    if not flows:
        pending.append('NO_SHARED_ALLOCATION_CANDIDATE_REACHED')
    if not methods:
        pending.append('FIELD_METHOD_TARGET_REMAINS_UNRESOLVED')
    pending.extend(('FIELD_WRITER_SEARCH_DOMAIN_OPEN', 'FIELD_CONTENT_VERSION_AND_DISPATCH_NOT_PROVEN'))
    return tuple(slices), flows, tuple(methods), domain, tuple(dict.fromkeys(pending))
