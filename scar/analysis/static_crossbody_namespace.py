"""Compose conditional namespace dependencies across qualified call entries.

This module adds relations over original graphs. It neither executes source nor
creates operations, values, invocations, runtime identities or location aliases.
Local reachability is checked by ``NamespaceDependencies``; function environment
ports are checked by the shared factory/environment reader.
"""
from __future__ import annotations

from dataclasses import dataclass, replace

from scar.ir.record_codec import decode
from scar.ir.program.environments import EnvironmentRole
from scar.ir.program.functions import BodyEntryInterface
from scar.ir.program.model import ReferenceValue, StateVersionValue, UseRole
from scar.ir.program.queries import ProgramIndex
from scar.ir.program.static_calls import (
    NamespaceFlowCondition as C, NamespacePathStart,
    StaticCrossBodyNamespaceFlow, StaticNamespaceCallBridge, StaticNamespacePathSegment,
    StaticQualifiedFunctionCreation, StaticQualifiedNamespaceRead, StaticQualifiedNamespaceWrite,
)
from scar.analysis.static_function_environment import (
    validate_function_environment_route, validate_static_body_namespace,
)
from scar.analysis.static_namespace import NamespaceDependencies


@dataclass(frozen=True, slots=True)
class StaticNamespaceBody:
    """Already read original body and its reusable indexes, not another graph."""
    graph: object
    document: dict
    namespace: object
    index: ProgramIndex | None = None
    dependencies: NamespaceDependencies | None = None

    def __post_init__(self):
        index = ProgramIndex(self.graph) if self.index is None else self.index
        if type(index) is not ProgramIndex or index.graph is not self.graph:
            raise ValueError('cross-body namespace index belongs to another original graph')
        validate_static_body_namespace(self.graph, self.document, self.namespace)
        dependencies = self.dependencies
        if dependencies is None:
            dependencies = NamespaceDependencies(self.graph, self.document, index=index)
        if (type(dependencies) is not NamespaceDependencies or dependencies.graph is not self.graph
                or dependencies.index is not index):
            raise ValueError('cross-body namespace dependencies belong to another original graph/index')
        object.__setattr__(self, 'index', index)
        object.__setattr__(self, 'dependencies', dependencies)


def _body(bodies, namespace):
    body = bodies[namespace]
    if type(body) is not StaticNamespaceBody or body.namespace != namespace:
        raise ValueError('cross-body namespace lookup changed its qualified source body')
    return body


def _reference(body, value):
    if type(body.index.values.get(value)) is not ReferenceValue:
        raise ValueError('namespace owner is not an original reference endpoint')


def _conditions(*groups):
    # Local witness validators retain their producer's exact condition order.
    return tuple(dict.fromkeys(condition for group in groups for condition in group))


def _validate_environment(route, bodies):
    caller, callee = _body(bodies, route.caller), _body(bodies, route.callee)
    validate_function_environment_route(route,
        caller_graph=caller.graph, caller_document=caller.document, caller_namespace=caller.namespace,
        callee_graph=callee.graph, callee_document=callee.document, callee_namespace=callee.namespace,
        definition=route.creation.definition, call_operation=route.call_operation,
        callee_use=route.callee_use, creations=(),
        qualified_creations=(StaticQualifiedFunctionCreation(route.creation_body, route.creation),),
        load_creation_body=lambda namespace: _body(bodies, namespace),
        caller_index=caller.index, callee_index=callee.index)


def _validate_bridge(bridge, bodies):
    if type(bridge) is not StaticNamespaceCallBridge:
        raise TypeError('cross-body namespace composition needs typed call bridges')
    bridge.__post_init__()
    route, state = bridge.environment, bridge.state_entry
    caller, callee = _body(bodies, route.caller), _body(bodies, route.callee)
    _reference(caller, bridge.caller_owner)
    _reference(callee, bridge.callee_owner)
    _validate_environment(route, bodies)
    for incoming in bridge.caller_owner_routes:
        _validate_environment(incoming, bodies)
    site = caller.index.use_site(state.caller_use)
    before, after = caller.index.values.get(state.caller_value), callee.index.values.get(state.callee_value)
    operation = caller.index.operations[route.call_operation]
    if (site.operation != route.call_operation or site.use.value != state.caller_value
            or site.use.role is not UseRole.STATE_CONTENT or state.caller_use not in operation.invoke_arguments
            or type(before) is not StateVersionValue or type(after) is not StateVersionValue
            or before.location != state.caller_location or after.location != state.callee_location):
        raise ValueError('namespace call state bridge changed an original caller state Use/location')
    if callee.document.get('interface') is None:
        raise ValueError('namespace call bridge has no original function entry interface')
    interface = decode(BodyEntryInterface, callee.document['interface'])
    if (interface.region != callee.namespace.region or interface.world != state.callee_value
            or interface.definition != callee.namespace.definition):
        raise ValueError('namespace call state bridge does not reach the exact original callee entry world')
    environments = [environment for environment in callee.graph.environments
                    if environment.id == route.environment and environment.region == callee.namespace.region]
    if (len(environments) != 1 or route.member not in environments[0].members
            or route.member.role is not EnvironmentRole.GLOBALS_NAMESPACE):
        raise ValueError('namespace bridge changed its original callee globals environment member')


def _write_endpoint(body, access):
    if body.dependencies.writes.get(access.operation) != access:
        raise ValueError('cross-body source is not an original declared namespace write')
    return StaticQualifiedNamespaceWrite(body.namespace, access.operation, access.owners[0], access.keys[0],
        access.payload, access.world, access.normal_edge)


def _read_endpoint(body, access, slot):
    if body.dependencies.reads.get(access.operation) != access:
        raise ValueError('cross-body destination is not an original declared namespace read')
    if type(slot) is not int or not 0 <= slot < len(access.owners):
        raise ValueError('cross-body destination changed its original lookup owner position')
    return StaticQualifiedNamespaceRead(body.namespace, access.operation, access.owners[slot], access.keys[slot],
        access.world, access.normal_edge, access.normal_value, access.owners[:slot])


def _region(body):
    found = [region for region in body.graph.regions if region.id == body.namespace.region]
    if len(found) != 1:
        raise ValueError('cross-body namespace body has no unique original root region')
    return found[0]


def _guard_entry_path(dependencies, witness, entry_owner):
    """Replay the input path under the bridge's exact owner-alias premise."""
    from scar.analysis.static_namespace import NamespaceEntryPathWitness
    if type(witness) is not NamespaceEntryPathWitness:
        raise TypeError('cross-body call entry needs its typed original entry-path witness')
    dependencies.validate_entry_path(witness)
    if witness.entry_owner != entry_owner:
        if witness.entry_owner != witness.query_owner:
            raise ValueError('namespace entry witness names another explicit passed-in owner')
        # Strengthen a query-only witness and replay with both references in
        # its guarded owner class. A normal write through either one replaces
        # the incoming binding under the retained alias premise.
        witness = replace(witness, entry_owner=entry_owner,
            conditions=dependencies._conditions(alias=entry_owner != witness.query_owner,
                                                read_slot=witness.read_slot))
    dependencies.validate_entry_path(witness, entry_owner=entry_owner)
    return witness


def compose_cross_body_namespace_flow(*, write_body, binding, bridges, entry_paths,
        read_body, read, read_slot=0, bodies):
    """Compose verified local witnesses and ordered original call-entry routes.

    ``binding`` reaches the first CALL from the source write. ``entry_paths``
    has one item per bridge: callee entry to the next CALL, or the final read.
    ``bodies`` contains every qualified body used by the bridges and factories.
    """
    from scar.analysis.static_namespace import NamespaceBindingWitness
    if type(binding) is not NamespaceBindingWitness:
        raise TypeError('cross-body source requires a typed original point-binding witness')
    if (type(bridges) is not tuple or not bridges or type(entry_paths) is not tuple
            or len(entry_paths) != len(bridges)):
        raise ValueError('cross-body composition requires an ordered entry path for each call bridge')
    if _body(bodies, write_body.namespace) is not write_body or _body(bodies, read_body.namespace) is not read_body:
        raise ValueError('cross-body endpoint bodies differ from the supplied qualified body index')
    write_body.dependencies.validate_binding(binding)
    write = _write_endpoint(write_body, binding.write)
    target = _read_endpoint(read_body, read, read_slot)
    start_owner = write_body.index.use_site(write.owner).use.value
    first_conditions = _conditions(binding.conditions,
        (C.NAMESPACE_OWNERS_ALIAS,) if start_owner != binding.query_owner else ())
    segments = [StaticNamespacePathSegment(write_body.namespace, NamespacePathStart.WRITE_NORMAL,
        write_body.dependencies._edge(write.normal).block, write.operation, start_owner,
        binding.query_operation, binding.query_owner, binding.query_world, binding.key,
        binding.path, binding.intervening_operations, first_conditions)]
    for bridge, witness in zip(bridges, entry_paths):
        _validate_bridge(bridge, bodies)
        body = _body(bodies, bridge.environment.callee)
        witness = _guard_entry_path(body.dependencies, witness, bridge.callee_owner)
        segments.append(StaticNamespacePathSegment(body.namespace, NamespacePathStart.ENTRY,
            witness.entry, None, bridge.callee_owner, witness.query_operation, witness.query_owner,
            witness.query_world, witness.key, witness.path, witness.intervening_operations, witness.conditions))
    final = entry_paths[-1]
    if final.read != read or final.read_slot != read_slot:
        raise ValueError('last entry path is not the original destination read/lookup slot')
    if (read_body.dependencies._value(target.owner) != segments[-1].query_owner
            or read_body.dependencies._string(target.key) != binding.key):
        raise ValueError('cross-body final read changed the queried namespace owner/key')
    required = (C.PATH_TAKEN, C.ALL_NORMAL_NAMESPACE_STORES_COMMIT_INPUT,
                C.NORMAL_READ_RETURNS_MAPPING_BINDING, C.INTERVENING_EFFECTS_PRESERVE_BINDING)
    conditions = _conditions(required, *(segment.conditions for segment in segments),
        (C.PRIOR_LOOKUP_NAMESPACES_MISSING,) if target.prior_lookup_owners else ())
    return StaticCrossBodyNamespaceFlow(write, target, tuple(segments), bridges, conditions)


def validate_cross_body_namespace_flow(flow, *, bodies):
    """Replay qualified endpoints/CFG/factory/entry joins from original bodies."""
    from scar.analysis.static_namespace import (
        NamespaceBindingWitness, NamespaceEntryPathWitness, NamespaceOwnerRelation,
    )
    if type(flow) is not StaticCrossBodyNamespaceFlow:
        raise TypeError('cross-body namespace reader needs the typed stored relation')
    flow.__post_init__()
    source, target = _body(bodies, flow.write.body), _body(bodies, flow.read.body)
    write = source.dependencies.writes.get(flow.write.operation)
    read = target.dependencies.reads.get(flow.read.operation)
    if write is None or read is None:
        raise ValueError('cross-body namespace relation has absent original endpoints')
    if _write_endpoint(source, write) != flow.write or flow.read.owner not in read.owners:
        raise ValueError('cross-body namespace relation changed its original source/read owner endpoint')
    slot = read.owners.index(flow.read.owner)
    if _read_endpoint(target, read, slot) != flow.read:
        raise ValueError('cross-body namespace relation changed its original read ports')
    first = flow.segments[0]
    relation = (NamespaceOwnerRelation.SAME_REFERENCE if first.start_owner == first.query_owner
                else NamespaceOwnerRelation.CONDITIONAL_REFERENCE_ALIAS)
    binding = NamespaceBindingWitness(write=write, query_owner=first.query_owner,
        query_operation=first.query_operation, query_world=first.query_world, key=first.key,
        owner_relation=relation, path=first.path, intervening_operations=first.intervening_operations,
        conditions=first.conditions)
    witnesses = []
    for position, segment in enumerate(flow.segments[1:]):
        body = _body(bodies, segment.body)
        if segment.start_block != _region(body).entry:
            raise ValueError('cross-body namespace segment changed its original region entry block')
        is_last = position == len(flow.bridges) - 1
        witnesses.append(NamespaceEntryPathWitness(region=body.namespace.region, entry=segment.start_block,
            query_owner=segment.query_owner, query_operation=segment.query_operation,
            query_world=segment.query_world, key=segment.key, path=segment.path,
            intervening_operations=segment.intervening_operations, conditions=segment.conditions,
            read=read if is_last else None, read_slot=slot if is_last else None,
            entry_owner=segment.start_owner))
    replay = compose_cross_body_namespace_flow(write_body=source, binding=binding,
        bridges=flow.bridges, entry_paths=tuple(witnesses), read_body=target, read=read,
        read_slot=slot, bodies=bodies)
    if replay != flow:
        raise ValueError('cross-body namespace relation changed original ordered source/entry/path endpoints')
    return True


__all__ = ['StaticNamespaceBody', 'compose_cross_body_namespace_flow', 'validate_cross_body_namespace_flow']
