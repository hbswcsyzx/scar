"""Mechanical addresses for sealed implicit class namespace operations.

Descriptors denote source environment templates, not current dictionaries or
cells. The caller retains lookup selection, frame identity and world guards;
this projection neither selects the standard builder nor enters a class body.
"""
from dataclasses import dataclass

from scar.analysis.source_namespace_interfaces import NamespacePlanView
from scar.ir.program import normal_targets as T, source_bindings as B
from scar.ir.program import source_productions as P, source_state as S


@dataclass(frozen=True, slots=True)
class ImplicitNamespaceAccess:
    kind: S.BindingAccessKind
    key: str
    descriptors: tuple[B.EnvironmentInterface, ...]
    owner_handles: tuple[T.GlobalPort | None, ...]
    payload: T.GlobalPort | None
    missing_outcome: str | None


def _at(rows, index, label):
    if type(index) is not int or not 0 <= index < len(rows):
        raise ValueError('implicit namespace invalid original '+label)
    return rows[index]


def _name(declarations, name):
    if type(name) is not B.NameRef:
        raise ValueError('implicit namespace lacks original name reference')
    if name.kind == 'SOURCE':
        return _at(declarations.names, name.index, 'name').value
    return name.symbol


def _globals(bindings, resolution_index, resolution):
    """Prefer original C2 routes, including explicit escaped-root routes."""
    found = set()
    for port in bindings.ports:
        if port.resolution != resolution_index:
            continue
        if port.source_scope != resolution.scope or port.name != resolution.name:
            raise ValueError('implicit namespace resolution/port scope or name differs')
        indices = [i for i in (port.write_target, port.delete_target) if i is not None]
        if port.read_plan is not None:
            plan = _at(bindings.plans, port.read_plan, 'lookup plan')
            indices.extend(step.interface for step in plan.steps)
        for index in indices:
            descriptor = _at(bindings.interfaces, index, 'interface')
            if descriptor.kind in ('ROOT_GLOBALS', 'ENV_GLOBALS'):
                found.add(descriptor)
    if len(found) > 1:
        raise ValueError('implicit namespace original globals routes disagree')
    if found:
        return next(iter(found))
    # C2 global_interface can redirect an escaped walrus to the root. Without
    # its original plan/target, class_scope alone cannot establish that route.
    if resolution.reason == 'ESCAPED_WALRUS_GLOBAL':
        return None
    return B.EnvironmentInterface('ENV_GLOBALS', resolution.scope)


def identify_implicit_namespace(bindings, declarations,
        context: NamespacePlanView, step) -> ImplicitNamespaceAccess | None:
    ins = step.instruction
    if type(ins) not in (P.ReadBuildClass, P.AccessClassName):
        return None
    if context.steps.get(step.id) != step:
        raise ValueError('implicit namespace step is outside its original plan')
    scope = context.owner(step.region).source_scope
    if type(scope) is not int or scope < 0:
        raise ValueError('implicit namespace lacks original source scope')
    if type(ins) is P.ReadBuildClass:
        if len(step.arguments) != 1:
            raise ValueError('implicit builder lookup world ABI differs')
        return ImplicitNamespaceAccess(S.BindingAccessKind.READ, '__build_class__',
            (B.EnvironmentInterface('BUILTINS', scope),), (None,),
            context.result(step, 0), 'RAISE_NAME_ERROR')

    if ins.interface.scope != scope or type(ins.name) is not str:
        raise ValueError('implicit class access original scope/name differs')
    if ins.action not in (P.BindingActionKind.READ, P.BindingActionKind.WRITE):
        return None
    read = ins.action is P.BindingActionKind.READ
    if len(step.arguments) != (3 if read else 4):
        raise ValueError('implicit class access environment/value/world ABI differs')
    prepared = B.EnvironmentInterface('CLASS_PREPARED_MAPPING', scope)
    builtin = B.EnvironmentInterface('BUILTINS', scope)
    missing = 'RAISE_NAME_ERROR' if read else None
    if ins.resolution is None:
        if any(r.scope == scope and _name(declarations, r.name) == ins.name
                for r in bindings.resolutions):
            raise ValueError('implicit class access omitted its original resolution')
        descriptors = ((prepared, B.EnvironmentInterface('ENV_GLOBALS', scope), builtin)
            if read else (prepared,))
    else:
        resolution = _at(bindings.resolutions, ins.resolution, 'resolution')
        if resolution.scope != scope or _name(declarations, resolution.name) != ins.name:
            raise ValueError('implicit class resolution belongs to another scope/name')
        classification = resolution.classification
        if classification in ('LOCAL', 'FREE'):
            slot = _at(bindings.bindings, resolution.binding, 'binding')
            if (_name(declarations, slot.name) != ins.name
                    or (slot.owner == scope) != (classification == 'LOCAL')
                    or slot.domain not in ('LOCAL_BINDING', 'TYPE_PARAMETER_BINDING', 'CLASS_PROTOCOL')):
                raise ValueError('implicit class cell differs from original binding')
            cell = B.EnvironmentInterface('CLASS_PROTOCOL_CELL' if slot.domain == 'CLASS_PROTOCOL'
                else 'LEXICAL_BINDING', slot.owner, resolution.binding)
            descriptors = (prepared, cell) if read and classification == 'FREE' else (cell,)
            if read:
                missing = 'RAISE_UNBOUND_FREE' if classification == 'FREE' else 'RAISE_UNBOUND_LOCAL'
        elif classification in ('CLASS_LOCAL', 'GLOBAL_IMPLICIT', 'GLOBAL_EXPLICIT'):
            if not read and classification == 'CLASS_LOCAL':
                descriptors = (prepared,)
            else:
                global_descriptor = _globals(bindings, ins.resolution, resolution)
                if global_descriptor is None:
                    return None
                descriptors = ((global_descriptor, builtin) if classification == 'GLOBAL_EXPLICIT'
                    else (prepared, global_descriptor, builtin)) if read else (global_descriptor,)
        else:
            return None
    environment = context.value(step.arguments[0])
    mapping = context.value(step.arguments[1])
    handles = tuple(mapping if d.kind == 'CLASS_PREPARED_MAPPING' else environment
        for d in descriptors)
    payload = context.result(step, 0) if read else context.value(step.arguments[2])
    return ImplicitNamespaceAccess(S.BindingAccessKind.READ if read else S.BindingAccessKind.WRITE,
        ins.name, descriptors, handles, payload, missing)
