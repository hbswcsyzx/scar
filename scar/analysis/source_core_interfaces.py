"""Core source port contracts; variable counts come from original F2 fields.

Shape-only specimens may omit a profile. Every source-bound recipe must
declare one. No runtime value, observed arity or display label proves a source
parameter. These contracts do not prove effects, cleanup or native admission.
"""
from scar.ir.program import source_productions as P
from scar.ir.program.control import LanguageCompletionKind as C
from scar.ir.program.model import ValueKind, ValueType
from scar.ir.program.protocol_signatures import ExceptionABI
from scar.ir.program.signature_patterns import ChoiceBinding


REF = ValueType(ValueKind.REFERENCE)
BOOL = ValueType(ValueKind.DATA, 'builtins.bool')
CORE_INSTRUCTIONS = (P.EvaluateChild, P.ApplyLanguageAction, P.AccessBinding, P.ConstructValue, P.DefineLiteral)
_ACTION_COUNTS = {
    P.LanguageActionKind.UNARY: (1, 1), P.LanguageActionKind.BINARY: (2, 1),
    P.LanguageActionKind.COMPARE: (2, 1), P.LanguageActionKind.CALL: (None, 1),
    P.LanguageActionKind.ATTRIBUTE_GET: (1, 1), P.LanguageActionKind.ATTRIBUTE_SET: (2, 0),
    P.LanguageActionKind.ATTRIBUTE_DELETE: (1, 0), P.LanguageActionKind.ITEM_GET: (2, 1),
    P.LanguageActionKind.ITEM_SET: (3, 0), P.LanguageActionKind.ITEM_DELETE: (2, 0),
    P.LanguageActionKind.TRUTH: (1, 'BOOL'), P.LanguageActionKind.SET_INSERT: (2, 0),
    P.LanguageActionKind.SET_UPDATE: (2, 0), P.LanguageActionKind.UNPACK_EXTENDED: (1, None),
    P.LanguageActionKind.STRING_JOIN: (1, 1),
}
_CONSTRUCTION_COUNTS = {
    P.ConstructionKind.LITERAL: 0, P.ConstructionKind.SLICE: None,
    P.ConstructionKind.TUPLE: None, P.ConstructionKind.INTERPOLATION: 3,
    P.ConstructionKind.TEMPLATE_STRING: 2,
}


def _require(condition, path, detail):
    if not condition:
        from scar.analysis.source_productions import ProductionError
        raise ProductionError('SOURCE_CORE_INTERFACE', str(path), detail)


def _field(source, site, name, constructor=None):
    field, value = source.roles.locate(site)
    _require(site.group == 'FIELD' and field.name == name and not site.item_path
        and (constructor is None or source.context.syntax.nodes[site.occurrence].constructor == constructor),
        site, 'parameter must reference its original typed source field')
    return value


def _variable_counts(source, instruction):
    """Return input/result reference counts, without inspecting plan ports."""
    if type(instruction) is P.ApplyLanguageAction:
        if instruction.action is P.LanguageActionKind.CALL:
            _require(len(instruction.selectors) == 2, 'CALL', 'call needs original args and keywords fields')
            owner = instruction.selectors[0].occurrence
            kind = source.context.syntax.nodes[owner].constructor
            _require(kind in ('Call', 'ClassDef'), 'CALL', 'call needs an expression or class-builder source')
            field = 'args' if kind == 'Call' else 'bases'
            args, keywords = (_field(source, site, name, kind) for site, name in zip(instruction.selectors, (field, 'keywords')))
            _require(instruction.selectors[0].occurrence == instruction.selectors[1].occurrence
                and args.kind == keywords.kind == 'LIST', 'CALL', 'call fields must belong to the same original call')
            _require(all(source.context.syntax.nodes[v.reference].constructor != 'Starred' for v in args.items)
                and all(source.roles.field(v.reference, 'arg').kind == 'SCALAR'
                    and source.roles.field(v.reference, 'arg').scalar.to_python() is not None for v in keywords.items),
                'CALL', 'expanded arguments require their explicit call protocol')
            hidden = 0 if kind == 'Call' else 2 + int(bool(source.roles.field(owner, 'type_params').items))
            return 1 + hidden + len(args.items) + len(keywords.items), 1
        if instruction.action is P.LanguageActionKind.UNPACK_EXTENDED:
            _require(len(instruction.selectors) == 2, 'UNPACK_EXTENDED', 'unpack needs original targets and starred slot')
            site, star = instruction.selectors
            items = _field(source, site, 'elts')
            _require(source.context.syntax.nodes[site.occurrence].constructor in ('List', 'Tuple') and items.kind == 'LIST'
                and star.occurrence == site.occurrence and star.group == site.group and star.ordinal == site.ordinal
                and len(star.item_path) == 1, site, 'unpack selectors must identify one original target list')
            stars = [i for i, v in enumerate(items.items) if source.context.syntax.nodes[v.reference].constructor == 'Starred']
            _require(stars == [star.item_path[0]], star, 'unpack requires its unique original starred target')
            return 1, len(items.items)
    elif type(instruction) is P.ConstructValue and instruction.construction is P.ConstructionKind.SLICE:
        _require(len(instruction.payload) == 3, 'SLICE', 'slice needs its three original component slots')
        values = tuple(_field(source, site, name, 'Slice') for site, name in
            zip(instruction.payload, ('lower', 'upper', 'step')))
        _require(len({site.occurrence for site in instruction.payload}) == 1
            and all(v.kind == 'NODE' or v.kind == 'SCALAR' and v.scalar.to_python() is None for v in values),
            'SLICE', 'slice components must be original expressions or explicit None')
        return sum(v.kind == 'NODE' for v in values), 1
    elif type(instruction) is P.ConstructValue and instruction.construction is P.ConstructionKind.TUPLE:
        layout = instruction.tuple_layout
        _require(bool(instruction.payload), 'TUPLE', 'tuple needs its original field')
        site = instruction.payload[0]
        if layout is P.TupleConstructionLayout.ITEMS:
            items = _field(source, site, 'elts', 'Tuple')
            _require(items.kind == 'LIST' and all(source.context.syntax.nodes[v.reference].constructor != 'Starred' for v in items.items),
                site, 'starred tuple uses a separate display protocol')
            return len(items.items), 1
        items = _field(source, site, 'values', 'TemplateStr')
        _require(items.kind == 'LIST', site, 'template components must be an original list')
        kinds = tuple(source.context.syntax.nodes[v.reference].constructor for v in items.items)
        _require(all(k in ('Constant', 'Interpolation') for k in kinds), site, 'invalid template component')
        interpolations = kinds.count('Interpolation')
        if layout is P.TupleConstructionLayout.TEMPLATE_INTERPOLATIONS:
            return interpolations, 1
        _require(layout is P.TupleConstructionLayout.TEMPLATE_STRINGS, site, 'tuple layout is required')
        # Empty literal separators are compiler-known input values, not new
        # dynamic components. Keep constant runs just as the source recipe does.
        previous = True; count = 0
        for kind in kinds:
            if kind == 'Interpolation':
                count += int(previous); previous = True
            else:
                count += 1; previous = False
        return count + int(previous), 1
    return None


def _contract(instruction, source):
    """(input refs, output refs or BOOL, may raise); None counts stay symbolic."""
    if type(instruction) is P.ApplyLanguageAction:
        _require(instruction.action in _ACTION_COUNTS, instruction.action, 'no source production declares this action')
        inputs, outputs = _ACTION_COUNTS[instruction.action]
        if source is not None and (inputs is None or outputs is None):
            inputs, outputs = _variable_counts(source, instruction)
        return inputs, outputs, True
    if type(instruction) is P.ConstructValue:
        _require(instruction.construction in _CONSTRUCTION_COUNTS, instruction.construction, 'no source production declares this construction')
        inputs = _CONSTRUCTION_COUNTS[instruction.construction]
        _require((instruction.construction is P.ConstructionKind.TUPLE) == (instruction.tuple_layout is not None),
            instruction.construction, 'only a tuple construction has a required tuple layout')
        if source is not None and inputs is None:
            inputs, _ = _variable_counts(source, instruction)
        return inputs, 1, True
    if type(instruction) is P.DefineLiteral:
        return 0, 1, False
    if type(instruction) is P.AccessBinding:
        return int(instruction.action is P.BindingActionKind.WRITE), int(instruction.action is P.BindingActionKind.READ), True
    if type(instruction) is P.EvaluateChild:
        purposes = {P.ProductionPurpose.VALUE: (0, 1), P.ProductionPurpose.CONDITION: (0, 'BOOL'),
            P.ProductionPurpose.STORE: (1, 0), P.ProductionPurpose.DELETE: (0, 0), P.ProductionPurpose.STATEMENT: (0, None)}
        _require(instruction.purpose in purposes, instruction.purpose, 'child has no declared evaluation interface')
        if source is not None:
            _, value = source.roles.locate(instruction.field)
            _require(value.kind == 'NODE', instruction.field, 'child entry needs one original occurrence, not a descriptor list')
        inputs, outputs = purposes[instruction.purpose]
        return inputs, outputs, True


def validate_core_interfaces(plan, source=None):
    profile = plan.profile
    if source is not None:
        _require(profile is not None, 'profile', 'source recipes require a declared state domain and exception ABI')
    if profile is None:
        return 0
    world = profile.world
    _require(type(world) is ValueType and world.kind is ValueKind.STATE, 'profile.world', 'world must be an abstract state domain')
    raised = (REF, world) if profile.exception_abi is ExceptionABI.EXCEPTION_WORLD else (REF, REF, world)
    regions = {r.id: r for r in plan.regions}; steps = {s.id: s for s in plan.steps}; checked = 0
    for region in plan.regions:
        _require(all(t.kind is not ValueKind.STATE or t == world for t in region.parameters if type(t) is ValueType),
            region.id, 'region uses another state domain')
    for step in plan.steps:
        instruction = step.instruction
        for owner in (instruction, getattr(instruction, 'environment', None), getattr(instruction, 'interface', None),
                getattr(instruction, 'publication', None), getattr(getattr(instruction, 'parameter', None), 'publication', None)):
            abi = getattr(owner, 'exception_abi', profile.exception_abi)
            _require(abi is profile.exception_abi, step.id, 'instruction exception ABI differs from its recipe profile')
        if type(instruction) in (P.ApplyPythonProtocol, P.ApplyDelegationProtocol):
            _require(all(b.choice == profile.exception_abi.value for b in instruction.bindings
                if type(b) is ChoiceBinding and b.name == 'exception_abi'), step.id, 'protocol ABI differs from its recipe profile')
        for completion in step.completions:
            _require(all(t.kind is not ValueKind.STATE or t == world for t in completion.types if type(t) is ValueType),
                step.id, 'result uses another state domain')
            if completion.kind is C.RAISE:
                _require(completion.types == raised, step.id, 'exception payload differs from the recipe profile')
        if type(instruction) not in CORE_INSTRUCTIONS:
            continue
        checked += 1
        def value_type(value):
            if type(value) is P.ProductionParameter:
                return regions[value.region].parameters[value.index]
            outputs = next(c.types for c in steps[value.step].completions if c.kind is C.FALLTHROUGH)
            return outputs[value.index]
        args = tuple(value_type(v) for v in step.arguments)
        inputs, outputs, may_raise = _contract(instruction, source)
        _require(bool(args) and args[-1] == world and all(t == REF for t in args[:-1])
            and (inputs is None or len(args) == inputs + 1), step.id, 'core operand count/types differ from its declared source contract')
        if type(instruction) is P.EvaluateChild and instruction.purpose is P.ProductionPurpose.STATEMENT:
            continue  # Existing statement checker proves the source completion set.
        exits = {(c.kind, c.target): c.types for c in step.completions}
        normal = exits.get((C.FALLTHROUGH, None))
        wanted = (BOOL,) if outputs == 'BOOL' else None if outputs is None else (REF,) * outputs
        _require(normal is not None and normal[-1:] == (world,)
            and (normal[:-1] == wanted if wanted is not None else all(t == REF for t in normal[:-1])),
            step.id, 'core result count/types differ from its declared source contract')
        wanted_exits = {(C.FALLTHROUGH, None)}
        if may_raise:
            wanted_exits.add((C.RAISE, None))
        _require(set(exits) == wanted_exits,
            step.id, 'core completion set differs from its declared source contract')
    return checked
