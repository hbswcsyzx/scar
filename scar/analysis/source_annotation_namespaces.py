"""Original annotation namespace/cell lookup interfaces, without registry replay.

The creator namespace and deferred request scope remain separate. Registration
returns a boolean, not the intermediate registry reference. Registry contains
and all exceptional effects stay on the original composite instruction.
"""
from scar.analysis.source_implicit_namespaces import ImplicitNamespaceAccess, _at, _name
from scar.analysis.source_namespace_interfaces import NamespacePlanView
from scar.ir.program import source_bindings as B, source_productions as P, source_state as S
from scar.ir.program.control import LanguageCompletionKind as C
from scar.ir.program.model import ValueKind, ValueType


def _lookup(bindings, index):
    plan = _at(bindings.plans, index, 'annotation read plan')
    if not plan.steps or plan.missing_outcome not in ('RAISE_NAME_ERROR', 'RAISE_UNBOUND_FREE', 'RAISE_UNBOUND_LOCAL'):
        raise ValueError('annotation lookup has no supported original missing outcome')
    for ordinal, step in enumerate(plan.steps):
        missing = plan.missing_outcome if ordinal == len(plan.steps) - 1 else 'NEXT'
        if (step.on_hit != 'RETURN_VALUE' or step.on_miss != missing
                or step.on_exception != 'PROPAGATE'):
            raise ValueError('annotation lookup original branch/exception protocol differs')
    return tuple(_at(bindings.interfaces, s.interface, 'annotation interface') for s in plan.steps), plan.missing_outcome


def identify_annotation_namespace(bindings, declarations, root_scopes: set[int],
        class_scopes: set[int], context: NamespacePlanView, step) -> ImplicitNamespaceAccess | None:
    ins = step.instruction
    if type(ins) not in (P.ReadAnnotationNamespace, P.ReadAnnotationRegistration):
        return None
    if context.steps.get(step.id) != step:
        raise ValueError('annotation lookup step is outside its original plan')
    access = ins.access; creator = access.scope
    if (type(creator) is not int or creator < 0 or type(access.name) is not P.AnnotationStateName
            or type(access.lookup) is not P.AnnotationLookupKind):
        raise ValueError('annotation lookup lacks its typed original scope/name/kind')
    if creator in root_scopes and creator in class_scopes:
        raise ValueError('annotation creator is both a root and class scope')
    registration = type(ins) is P.ReadAnnotationRegistration
    current = context.owner(step.region).source_scope
    if current != (ins.registration.scope if registration else creator):
        raise ValueError('annotation lookup crossed its original request/publication scope')
    if registration and (access.name is not P.AnnotationStateName.CONDITIONAL
            or access.lookup not in (P.AnnotationLookupKind.GLOBALS_CHAIN, P.AnnotationLookupKind.CLASS_PROTOCOL_CELL)):
        raise ValueError('registration lookup must read the declared conditional registry')
    normal = [c for c in step.completions if c.kind is C.FALLTHROUGH]
    reference = ValueType(ValueKind.REFERENCE)
    payload_type = ValueType(ValueKind.DATA, 'builtins.bool') if registration else reference
    args = tuple(context.emitter.value(v)[1] for v in step.arguments)
    if (len(args) != (2 if registration else 1) or len(normal) != 1
            or type(args[-1]) is not ValueType or args[-1].kind is not ValueKind.STATE
            or registration and args[0] != reference
            or normal[0].types != (payload_type, args[-1])):
        raise ValueError('annotation lookup original environment/result/world ABI differs')
    context.worlds(step)
    if creator not in root_scopes and creator not in class_scopes:
        return None
    key = access.name.value
    missing = 'RAISE_NAME_ERROR'
    linked = (access.binding, access.implicit_requirement, access.read_plan)
    if access.lookup is P.AnnotationLookupKind.CLASS_PROTOCOL_CELL:
        if creator not in class_scopes or access.name is not P.AnnotationStateName.CONDITIONAL:
            raise ValueError('annotation protocol cell is outside its original class registry')
        implicit = _at(bindings.implicit, access.implicit_requirement, 'annotation implicit requirement')
        slot = _at(bindings.bindings, access.binding, 'annotation protocol binding')
        if (implicit.scope != creator or _name(declarations, implicit.name) != key
                or implicit.rule != 'CONDITIONAL_ANNOTATION_REQUIREMENT'
                or implicit.binding != access.binding or implicit.read_plan != access.read_plan
                or slot.owner != creator or slot.domain != 'CLASS_PROTOCOL'
                or _name(declarations, slot.name) != key):
            raise ValueError('annotation cell lost its original implicit/binding/read-plan chain')
        descriptors, missing = _lookup(bindings, access.read_plan)
        if (descriptors != (B.EnvironmentInterface('CLASS_PROTOCOL_CELL', creator, access.binding),)
                or missing != 'RAISE_UNBOUND_FREE'):
            raise ValueError('annotation cell lookup differs from its original protocol route')
    else:
        if any(value is not None for value in linked):
            raise ValueError('annotation namespace chain cannot borrow protocol-cell IDs')
        globals_ = B.EnvironmentInterface('ROOT_GLOBALS' if creator in root_scopes else 'ENV_GLOBALS', creator)
        builtin = B.EnvironmentInterface('BUILTINS', creator)
        if access.lookup is P.AnnotationLookupKind.LOCALS_CHAIN:
            local = B.EnvironmentInterface('ROOT_LOCALS' if creator in root_scopes else 'CLASS_PREPARED_MAPPING', creator)
            descriptors = (local, globals_, builtin)
        elif access.lookup is P.AnnotationLookupKind.GLOBALS_CHAIN:
            if creator not in root_scopes:
                return None
            # The implicit root plan describes the deferred globals read, not
            # publication's distinct LOCALS_CHAIN, even for the same key.
            rows = [row for row in bindings.implicit if row.scope == creator
                and row.rule == 'CONDITIONAL_ANNOTATION_REQUIREMENT'
                and _name(declarations, row.name) == key]
            if any(row.binding is not None or row.read_plan is None for row in rows):
                raise ValueError('root annotation requirement lacks its original globals plan')
            plans = {row.read_plan for row in rows}
            if len(plans) > 1:
                raise ValueError('root annotation requirements disagree on their original read plan')
            descriptors = (globals_, builtin)
            if plans:
                descriptors, missing = _lookup(bindings, next(iter(plans)))
                if descriptors != (globals_, builtin) or missing != 'RAISE_NAME_ERROR':
                    raise ValueError('root annotation globals plan contains a different namespace route')
        else:
            return None
    owner = context.value(step.arguments[0]) if registration else None
    payload = None if registration else context.result(step, 0)
    return ImplicitNamespaceAccess(S.BindingAccessKind.READ, key, descriptors,
        (owner,) * len(descriptors), payload, missing)
