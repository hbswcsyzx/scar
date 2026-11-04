"""Closed source-recipe shapes and local graph references.

This is the input grammar for source lowering. Acceptance here does not prove
that a recipe implements its Python constructor, effects or cleanup semantics.
The canonical program graph remains the later lowering target.
"""
from dataclasses import fields
from hashlib import sha256
import json
from pathlib import Path, PurePosixPath
import sys

from scar.analysis.program_types import _build_types
from scar.ir.program import source_productions as P
from scar.ir.program.control import LanguageCompletionKind as C
from scar.ir.program.model import ValueKind, ValueType, ExitKind
from scar.ir.program.protocol_signatures import ExceptionABI, protocol_signature_catalog, _resolve_protocol_rule
from scar.ir.program.signature_patterns import SignatureError, SignatureForm
from scar.ir.program.delegation_signatures import resolve_delegation_signature
from scar.ir.record_codec import decode, encode
from scar.analysis.source_deferred_interfaces import DeferredInterfaceIndex
from scar.analysis.source_statement_interfaces import SourceStatementInterfaceIndex
from scar.analysis.source_type_parameter_interfaces import TypeParameterInterfaceIndex
from scar.analysis.source_definition_interfaces import DefinitionInterfaceIndex


class ProductionError(ValueError):
    def __init__(self, code, path, detail):
        self.code, self.path, self.detail = code, path, detail
        super().__init__(code + ' at ' + path + ': ' + detail)


def _require(condition, code, path, detail):
    if not condition:
        raise ProductionError(code, path, detail)


def _digest(value):
    return sha256(json.dumps(value, sort_keys=True, separators=(',', ':'),
        ensure_ascii=True, allow_nan=False).encode('ascii')).hexdigest()


def _record_children(members, value, path):
    for member in members:
        _require(hasattr(value, member['name']), 'RECORD_FIELD', path, 'missing declared field')
        yield member['type'], getattr(value, member['name']), path + '.' + member['name']


def _tuple_children(expressions, values, path, variadic):
    for index, value in enumerate(values):
        yield expressions[0] if variadic else expressions[index], value, path + '[' + str(index) + ']'


def production_type_catalog():
    root, rows, registry, counts = _build_types(P.SourceProductionPlan)
    modules = {cls.__module__: sha256(Path(sys.modules[cls.__module__].__file__).read_bytes()).hexdigest()
        for cls in registry.values()}
    modules[__name__] = sha256(Path(__file__).read_bytes()).hexdigest()
    for name in ('scar.analysis.program_types', 'scar.ir.record_codec', 'scar.ir.program.protocol_signatures',
                 'scar.ir.program.delegation_signatures', 'scar.analysis.source_deferred_interfaces',
                 'scar.analysis.source_statement_interfaces', 'scar.analysis.source_type_parameter_interfaces',
                 'scar.analysis.source_definition_interfaces'):
        modules[name] = sha256(Path(sys.modules[name].__file__).read_bytes()).hexdigest()
    payload = dict(schema='scar.source-production-type-catalog', schema_version=1,
        root=root, types=rows, counts=counts, modules=dict(sorted(modules.items())),
        instruction_variants=[kind.__name__ for kind in P.ProductionInstruction.__args__],
        authority='SOURCE_RECIPE_SHAPE_ONLY',
        source_rule_semantics_closed=False, canonical_graph_generated=False)
    return {**payload, 'content_sha256': _digest(payload)}


def read_production_type_catalog(document):
    expected = production_type_catalog()
    _require(_digest(document) == _digest(expected), 'CATALOG_MISMATCH', 'catalog', 'type declarations or source pins differ')
    return expected


def _shape(plan, max_visits):
    """Exact nominal walk over the generated finite grammar, never recursion."""
    _require(type(max_visits) is int and max_visits >= 0, 'QUERY_ARGUMENT', 'max_visits',
             'expected an exact nonnegative integer')
    root, declarations, registry, _ = _build_types(P.SourceProductionPlan)
    rows = {row['key']: row for row in declarations}
    atoms = {'NoneType': type(None), 'bool': bool, 'int': int, 'float': float, 'str': str, 'bytes': bytes}

    def accepts(expr, value):
        if expr['kind'] == 'REF':
            return type(value) is registry[expr['name']]
        if expr['kind'] == 'ATOM':
            return type(value) is atoms[expr['name']]
        return expr['kind'] in ('TUPLE', 'FIXED_TUPLE') and type(value) is tuple

    pending, active, visits = [('ENTER', root, plan, 'plan')], set(), 0
    while pending:
        action, expr, value, path = pending.pop()
        if action == 'LEAVE':
            active.remove(id(value))
            if expr is not None and hasattr(expr, '__post_init__'):
                try:
                    expr.__post_init__(value)
                except (ValueError, TypeError, AttributeError) as error:
                    raise ProductionError('CONSTRUCTOR_INVARIANT', path, str(error)) from error
            continue
        if action == 'CHILDREN':
            child = next(value, None)
            if child is not None:
                pending.append(('CHILDREN', None, value, path))
                pending.append(('ENTER', *child))
            continue
        _require(visits < max_visits, 'BUDGET_FRONTIER', path, 'recipe shape traversal limit')
        visits += 1
        if expr['kind'] == 'UNION':
            choices = [arg for arg in expr['args'] if accepts(arg, value)]
            _require(len(choices) == 1, 'TYPE_MISMATCH', path, 'expected one exact declared variant')
            expr = choices[0]
        _require(accepts(expr, value), 'TYPE_MISMATCH', path, 'value is outside its exact declared type')
        if expr['kind'] == 'ATOM':
            continue
        constructor = None
        if expr['kind'] == 'REF':
            cls, row = registry[expr['name']], rows[expr['name']]
            if row['kind'] == 'ENUM':
                _require(any(value is member for member in cls), 'TYPE_MISMATCH', path,
                         'enum must be a declared singleton')
                continue
            if row['kind'] == 'IDENTIFIER':
                _require(type(getattr(value, 'value', None)) is str and bool(value.value)
                    and type(value.prefix) is str and value.prefix == row['prefix'],
                         'IDENTIFIER_PAYLOAD', path, 'identifier payload or namespace differs')
                continue
            # Check fields first, then the reviewed original constructor.
            constructor = cls
            children = _record_children(row['fields'], value, path)
        else:
            variadic = expr['kind'] == 'TUPLE'
            _require(variadic or len(value) == len(expr['args']), 'TYPE_MISMATCH', path, 'fixed tuple length differs')
            children = _tuple_children(expr['args'], value, path, variadic)
        _require(id(value) not in active, 'VALUE_CYCLE', path, 'use graph IDs rather than cyclic value objects')
        active.add(id(value))
        pending.extend((('LEAVE', constructor, value, path), ('CHILDREN', None, children, path)))
    return visits


def validate_production_plan(plan, *, max_visits=1_000_000):
    """Check recipe structure, ownership, ordered values and local interfaces.

    Source field existence/context, constructor recipes, effect signatures and
    full control/cleanup semantics require separate source-rule replay.
    """
    visits = _shape(plan, max_visits)
    _require((plan.schema, plan.schema_version, plan.authority) == (
        'scar.source-production-plan', 13, 'SOURCE_RECIPE_SHAPE_ONLY'),
        'SCHEMA', 'plan', 'unsupported recipe schema or authority')
    source = plan.input
    _require(bool(source.path) and bool(source.namespace_root), 'INPUT', 'plan.input', 'source paths must be nonempty')
    _require(PurePosixPath(source.path).is_absolute() and PurePosixPath(source.namespace_root).is_absolute()
        and PurePosixPath(source.path).is_relative_to(source.namespace_root)
        and '..' not in PurePosixPath(source.path).parts
        and '..' not in PurePosixPath(source.namespace_root).parts,
        'INPUT', 'plan.input', 'original path must be within the absolute source namespace')
    for field in fields(source):
        if field.name.endswith('_sha256'):
            digest = getattr(source, field.name)
            _require(len(digest) == 64 and all(char in '0123456789abcdef' for char in digest),
                     'INPUT', 'plan.input.' + field.name, 'expected a lowercase SHA-256')
    regions, steps = {}, {}
    for table, rows in ((regions, plan.regions), (steps, plan.steps)):
        for row in rows:
            _require(row.id not in table, 'DUPLICATE_ID', str(row.id), 'duplicate local record identity')
            table[row.id] = row
    _require(plan.root in regions, 'DANGLING_REGION', 'plan.root', 'missing root region')
    _require(regions[plan.root].source == plan.source, 'SOURCE', 'plan.root', 'root and plan source differ')
    done = {plan.root}
    _require(regions[plan.root].parent is None, 'REGION_PARENT', 'plan.root', 'root must have no parent')
    for region in plan.regions:
        chain, active, current = [], set(), region.id
        while current not in done:
            _require(current in regions, 'DANGLING_REGION', str(region.id), 'unknown lexical parent')
            _require(current not in active, 'REGION_CYCLE', str(region.id), 'cyclic lexical ownership')
            chain.append(current)
            active.add(current)
            current = regions[current].parent
        done.update(chain)

    # One ownership index also proves loop-target ancestry, without repeated
    # scans of deep parent chains or expanding any loop iterations.
    children = {r.id: [] for r in plan.regions}
    for region in plan.regions:
        if region.parent is not None:
            children[region.parent].append(region.id)
    intervals, boundaries, clock = {}, {}, 0
    pending = [('ENTER', plan.root, None)]
    while pending:
        action, identity, boundary = pending.pop()
        if action == 'LEAVE':
            intervals[identity] = (intervals[identity][0], clock)
            continue
        if regions[identity].kind in (P.ProductionRegionKind.DEFERRED,P.ProductionRegionKind.TYPE_PARAMETERS):
            boundary = identity
        boundaries[identity] = boundary
        intervals[identity] = (clock, None)
        clock += 1
        pending.append(('LEAVE', identity, boundary))
        pending.extend(('ENTER', child, boundary) for child in reversed(children[identity]))

    def completions(rows, owner, path):
        result = {}
        # An empty interface declares no eventual completion, e.g. an
        # unconditional continue loop. It is not a fabricated return edge.
        for row in rows:
            key = row.kind, row.target
            _require(key not in result, 'COMPLETION', path, 'duplicate completion kind/target')
            if row.kind in (C.BREAK, C.CONTINUE):
                if type(row.target) is P.SourceLoopTarget:
                    _require(row.target.occurrence >= 0, 'COMPLETION', path, 'negative source loop target')
                    result[key] = row.types
                    continue  # original lexical target is checked by the source index
                _require(row.target in regions and regions[row.target].kind is P.ProductionRegionKind.LOOP,
                         'COMPLETION', path, 'break/continue must target a declared loop')
                start, end = intervals[row.target]
                _require(owner in intervals and start <= intervals[owner][0] < end
                    and boundaries[owner] == boundaries[row.target],
                    'COMPLETION', path, 'loop target must enclose the region without crossing deferred code')
            else:
                _require(row.target is None, 'COMPLETION', path, 'only break/continue carry a loop target')
            result[key] = row.types
        return result

    _require(all(s.region in regions for s in plan.steps), 'STEP_OWNER', 'plan.steps', 'unknown region owner')
    region_outputs = {r.id: completions(r.completions, r.id, str(r.id)) for r in plan.regions}
    step_outputs = {s.id: completions(s.completions, s.region, str(s.id)) for s in plan.steps}
    protocols = ({r.kind: r for r in protocol_signature_catalog()}
        if any(type(s.instruction) is P.ApplyPythonProtocol for s in plan.steps) else {})

    def deferred_ports(environment):
        _require(type(environment.world) is ValueType and environment.world.kind is ValueKind.STATE,
            'DEFERRED_INTERFACE', 'environment.world', 'a deferred activation requires an explicit state domain')
        _require(environment.scope >= 0 and environment.globals_scope >= 0
            and all(c >= 0 for c in environment.captures) and len(set(environment.captures)) == len(environment.captures),
            'DEFERRED_INTERFACE', 'environment', 'original scopes/capture references must be distinct and nonnegative')
        rank, prior, singletons = list(P.DeferredParameterKind), -1, set()
        sources, bindings = set(), set()
        for p in environment.parameters:
            current = rank.index(p.kind)
            _require(current >= prior and p.source not in sources, 'DEFERRED_INTERFACE', 'parameters',
                'formals must have distinct source binders in declared source-group order')
            prior = current; sources.add(p.source)
            _require(p.default_source is None or p.kind in (P.DeferredParameterKind.POSITIONAL_ONLY,
                P.DeferredParameterKind.POSITIONAL_OR_KEYWORD, P.DeferredParameterKind.KEYWORD_ONLY),
                'DEFERRED_INTERFACE', 'parameters', 'variadic/iterator inputs cannot have source defaults')
            if p.kind in (P.DeferredParameterKind.VAR_POSITIONAL, P.DeferredParameterKind.VAR_KEYWORD):
                _require(p.kind not in singletons, 'DEFERRED_INTERFACE', 'parameters', 'variadic formal may occur only once')
                singletons.add(p.kind)
            if p.kind is P.DeferredParameterKind.INITIAL_ITERATOR:
                _require(len(environment.parameters) == 1 and p.binding_port is None
                    and environment.kind in (P.DeferredBodyKind.GENERATOR, P.DeferredBodyKind.ASYNC_GENERATOR),
                    'DEFERRED_INTERFACE', 'parameters', 'initial iterator is a distinct sole generator input')
            else:
                _require(p.binding_port is not None and p.binding_port >= 0 and p.binding_port not in bindings,
                    'DEFERRED_INTERFACE', 'parameters', 'formal requires one distinct original binding port')
                bindings.add(p.binding_port)
        return (ValueType(ValueKind.REFERENCE), *(ValueType(ValueKind.REFERENCE) for _ in environment.parameters), environment.world)

    def annotation_ports(annotations):
        _require(annotations.scope >= 0 and bool(annotations.entries)
            and all(c >= 0 for c in annotations.captures) and len(set(annotations.captures)) == len(annotations.captures),
            'FUNCTION_INTERFACE', 'annotations', 'annotation scope/entries/capture references must be explicit')
        _require(all(e.name for e in annotations.entries) and len({e.value for e in annotations.entries}) == len(annotations.entries),
            'FUNCTION_INTERFACE', 'annotations', 'annotation entries require names and distinct original value sources')

    def lazy_interface(expression):
        _require(expression.scope >= 0 and expression.format_default == 1
            and all(c >= 0 for c in expression.captures) and len(set(expression.captures)) == len(expression.captures),
            'TYPE_PARAMETER_INTERFACE','lazy','lazy evaluator scope/capture/default-format interface differs')

    def type_parameter(parameter):
        _require(parameter.binding_port >= 0,'TYPE_PARAMETER_INTERFACE','parameter','negative source interface port')
        _require(parameter.kind is P.TypeParameterKind.TYPE_VAR or parameter.bound is None,
            'TYPE_PARAMETER_INTERFACE','parameter','only TypeVar has a bound/constraints evaluator')
        _require(not parameter.constraints or parameter.bound is not None,'TYPE_PARAMETER_INTERFACE','parameter','constraints require an evaluator')
        for expression in (parameter.bound,parameter.default):
            if expression is not None:lazy_interface(expression)
        _require(parameter.bound is None or not parameter.bound.unpack_starred,
            'TYPE_PARAMETER_INTERFACE','parameter','bound evaluator does not unpack a starred result')
        _require(parameter.default is None or not parameter.default.unpack_starred or parameter.kind is P.TypeParameterKind.TYPE_VAR_TUPLE,
            'TYPE_PARAMETER_INTERFACE','parameter','only TypeVarTuple default may unpack a starred result')

    def type_parameter_ports(environment):
        _require(type(environment.world) is ValueType and environment.world.kind is ValueKind.STATE
            and environment.scope >= 0 and bool(environment.parameters)
            and len(set(environment.captures)) == len(environment.captures) and all(c >= 0 for c in environment.captures)
            and len(set(environment.inputs)) == len(environment.inputs),
            'TYPE_PARAMETER_INTERFACE','environment','type-parameter scope/input/capture domain differs')
        _require(len({p.name for p in environment.parameters}) == len(environment.parameters)
            and len({p.binding_port for p in environment.parameters}) == len(environment.parameters),
            'TYPE_PARAMETER_INTERFACE','environment','type parameters require distinct source interfaces')
        seen=False
        for p in environment.parameters:
            type_parameter(p)
            _require(not seen or p.default is not None,'TYPE_PARAMETER_INTERFACE','environment','non-default parameter follows default')
            seen|=p.default is not None
        return (*(ValueType(ValueKind.REFERENCE) for _ in range(len(environment.captures)+len(environment.inputs))),environment.world)

    def class_ports(interface):
        _require(type(interface.world) is ValueType and interface.world.kind is ValueKind.STATE
            and interface.scope >= 0 and interface.globals_scope >= 0
            and all(c >= 0 for c in (*interface.captures,*interface.protocol_bindings))
            and len(set(interface.captures)) == len(interface.captures)
            and len(set(interface.protocol_bindings)) == len(interface.protocol_bindings),
            'CLASS_INTERFACE','interface','class namespace/capture/protocol domain differs')
        reference=ValueType(ValueKind.REFERENCE)
        return (reference,reference,interface.world)
    claimed, referenced_regions = set(), {plan.root}
    for region in plan.regions:
        _require(bool(region.steps), 'REGION_EXIT', str(region.id), 'region needs an explicit result/transfer step')
        available, escaping = {}, {}

        def value_type(value):
            if type(value) is P.ProductionParameter:
                _require(value.region == region.id and 0 <= value.index < len(region.parameters),
                         'VALUE_SCOPE', str(region.id), 'parameter belongs to another region or ordinal')
                return region.parameters[value.index]
            _require(value.step in available, 'VALUE_ORDER', str(region.id),
                     'value must be defined earlier in the same region')
            types = available[value.step].get((C.FALLTHROUGH, None), ())
            _require(0 <= value.index < len(types), 'VALUE_ORDINAL', str(value.step), 'missing normal result ordinal')
            return types[value.index]

        def child(identity, kind=None):
            _require(identity in regions and regions[identity].parent == region.id,
                     'REGION_REFERENCE', str(region.id), 'nested template must be owned by this region')
            target = regions[identity]
            referenced_regions.add(identity)
            _require(kind is None or target.kind is kind, 'REGION_KIND', str(identity), 'wrong nested region kind')
            return target

        def invoke(call, *, shared=False):
            _require(call.region in regions,'DANGLING_REGION',str(call.region),'missing region template')
            target=regions[call.region]
            if shared and target.kind is P.ProductionRegionKind.SHARED:
                owner=region.id
                while owner is not None and owner!=target.parent:owner=regions[owner].parent
                _require(owner is not None and boundaries[target.id]==boundaries[region.id]
                    and target.context.environment==region.context.environment,
                    'SHARED_REGION',str(call.region),'shared call must stay under its lexical owner in the same activation/namespace')
                referenced_regions.add(target.id)
            else:
                target=child(call.region)
            _require(tuple(value_type(v) for v in call.arguments) == target.parameters,
                     'PORT_TYPES', str(call.region), 'region call arguments differ from declared parameters')
            return region_outputs[target.id]

        for ordinal, identity in enumerate(region.steps):
            _require(identity in steps, 'DANGLING_STEP', str(region.id), 'owned step is missing')
            _require(identity not in claimed and steps[identity].region == region.id,
                     'STEP_OWNER', str(identity), 'step must be owned exactly once')
            claimed.add(identity)
            step, outputs = steps[identity], step_outputs[identity]
            args = tuple(value_type(v) for v in step.arguments)
            instruction = step.instruction
            if type(instruction) is P.EvaluateChild and instruction.purpose is P.ProductionPurpose.STATEMENT:
                _require(len(args) == 1 and type(args[0]) is ValueType and args[0].kind is ValueKind.STATE,
                    'PORT_TYPES', str(identity), 'statement child requires one explicit world input')
                for (kind, _), types in outputs.items():
                    reference = ValueType(ValueKind.REFERENCE)
                    accepted = (((reference, args[0]), (reference, reference, args[0])) if kind is C.RAISE else
                        ((reference, args[0]),) if kind is C.RETURN else ((args[0],),))
                    _require(types in accepted,
                        'PORT_TYPES', str(identity), 'statement completion payload differs from its world/exception interface')
            elif type(instruction) is P.ReadCompilationOption:
                _require(not args and outputs == {(C.FALLTHROUGH, None): (ValueType(ValueKind.DATA, 'builtins.bool'),)},
                    'COMPILATION_OPTION', str(identity), 'compilation option produces only one symbolic boolean')
            elif type(instruction) is P.EnterTypeParameters:
                environment=instruction.environment
                _require(region.kind is P.ProductionRegionKind.TYPE_PARAMETERS and ordinal==0
                    and args==region.parameters==type_parameter_ports(environment)
                    and step.arguments==tuple(P.ProductionParameter(region.id,i) for i in range(len(region.parameters)))
                    and outputs=={(C.FALLTHROUGH,None):(environment.world,)},
                    'TYPE_PARAMETER_INTERFACE',str(identity),'type-parameter activation must admit its exact source inputs first')
            elif type(instruction) is P.InvokeTypeParameterFactory:
                environment=instruction.environment
                target=child(instruction.invocation.region,P.ProductionRegionKind.TYPE_PARAMETERS)
                _require(not args and target.parameters==type_parameter_ports(environment)
                    and target.steps and type(steps[target.steps[0]].instruction) is P.EnterTypeParameters
                    and steps[target.steps[0]].instruction.environment==environment,
                    'TYPE_PARAMETER_INTERFACE',str(identity),'factory body must activate its original type-parameter interface')
                body_outputs=invoke(instruction.invocation)
                reference=ValueType(ValueKind.REFERENCE)
                raised=(reference,environment.world) if environment.exception_abi is ExceptionABI.EXCEPTION_WORLD else (reference,reference,environment.world)
                allowed={(C.FALLTHROUGH,None):(reference,environment.world),(C.RAISE,None):raised}
                _require(all(k in allowed and allowed[k]==v for k,v in body_outputs.items())
                    and outputs=={**body_outputs,(C.RAISE,None):raised},
                    'TYPE_PARAMETER_INTERFACE',str(identity),'factory must preserve body results and creation/entry failure')
            elif type(instruction) in (P.BuildLazyExpression,P.CreateTypeParameter,P.SetTypeParameterDefault,P.BindTypeParameter,P.AttachTypeParameters):
                _require(bool(args) and type(args[-1]) is ValueType and args[-1].kind is ValueKind.STATE,
                    'TYPE_PARAMETER_INTERFACE',str(identity),'type-parameter action needs an explicit world')
                reference=ValueType(ValueKind.REFERENCE);world=args[-1]
                if type(instruction) is P.BuildLazyExpression:
                    lazy_interface(instruction.expression)
                    count=1+len(instruction.expression.captures)
                elif type(instruction) is P.AttachTypeParameters:
                    count=2
                else:
                    type_parameter(instruction.parameter)
                    if type(instruction) is P.CreateTypeParameter:count=int(instruction.parameter.bound is not None)
                    elif type(instruction) is P.SetTypeParameterDefault:
                        _require(instruction.parameter.default is not None,'TYPE_PARAMETER_INTERFACE',str(identity),'default setter needs an original default evaluator')
                        count=2
                    else:count=1
                normal=(reference,world) if type(instruction) in (P.BuildLazyExpression,P.CreateTypeParameter) else (world,)
                raised=(reference,world) if instruction.exception_abi is ExceptionABI.EXCEPTION_WORLD else (reference,reference,world)
                _require(args==(*(reference for _ in range(count)),world)
                    and outputs=={(C.FALLTHROUGH,None):normal,(C.RAISE,None):raised},
                    'TYPE_PARAMETER_INTERFACE',str(identity),'type-parameter action ports differ from its source contract')
            elif type(instruction) in (P.BuildFunctionAnnotations,P.BuildFunction,P.ApplyDecorator,P.TranslateEscapingException):
                _require(bool(args) and type(args[-1]) is ValueType and args[-1].kind is ValueKind.STATE,
                    'FUNCTION_INTERFACE', str(identity), 'function operation requires an explicit state domain')
                world, reference = args[-1], ValueType(ValueKind.REFERENCE)
                if type(instruction) is P.BuildFunction:
                    env = instruction.environment
                    deferred_ports(env)
                    _require(world == env.world, 'FUNCTION_INTERFACE', str(identity), 'function creation world differs from entry contract')
                    defaults = sum(p.default_source is not None for p in env.parameters)
                    count = 2 + defaults + len(env.captures) + (instruction.annotations is not None)
                    if instruction.annotations is not None:
                        annotation_ports(instruction.annotations)
                    abi = env.exception_abi
                    expected_args = (*(reference for _ in range(count)),world)
                elif type(instruction) is P.BuildFunctionAnnotations:
                    annotation_ports(instruction.annotations)
                    abi = instruction.exception_abi
                    expected_args = (*(reference for _ in range(1+len(instruction.annotations.captures))),world)
                elif type(instruction) is P.ApplyDecorator:
                    abi = instruction.exception_abi
                    expected_args = (reference,reference,world)
                else:
                    _require(instruction.kind in (P.DeferredBodyKind.GENERATOR,P.DeferredBodyKind.COROUTINE,P.DeferredBodyKind.ASYNC_GENERATOR),
                        'FUNCTION_INTERFACE', str(identity), 'ordinary functions do not translate escaping StopIteration')
                    abi = instruction.exception_abi
                    expected_args = ((reference,world) if abi is ExceptionABI.EXCEPTION_WORLD else (reference,reference,world))
                raised = (reference,world) if abi is ExceptionABI.EXCEPTION_WORLD else (reference,reference,world)
                normal = raised if type(instruction) is P.TranslateEscapingException else (reference,world)
                _require(args == expected_args and outputs == {(C.FALLTHROUGH,None):normal,(C.RAISE,None):raised},
                    'FUNCTION_INTERFACE', str(identity), 'function operation input/completion interface differs from source contract')
            elif type(instruction) is P.DeferClassBody:
                interface=instruction.interface
                body=child(instruction.body,P.ProductionRegionKind.DEFERRED)
                reference=ValueType(ValueKind.REFERENCE)
                raised=(reference,interface.world) if interface.exception_abi is ExceptionABI.EXCEPTION_WORLD else (reference,reference,interface.world)
                allowed={(C.RETURN,None):(reference,interface.world),(C.RAISE,None):raised}
                _require(not args and outputs=={(C.FALLTHROUGH,None):(reference,)}
                    and body.parameters==class_ports(interface)
                    and body.steps and type(steps[body.steps[0]].instruction) is P.EnterClassBody
                    and steps[body.steps[0]].instruction.interface==interface
                    and all(k in allowed and allowed[k]==v for k,v in region_outputs[body.id].items()),
                    'CLASS_INTERFACE',str(identity),'class callback must admit its builder namespace and only return/raise')
            elif type(instruction) is P.EnterClassBody:
                interface=instruction.interface
                _require(region.kind is P.ProductionRegionKind.DEFERRED and ordinal==0
                    and args==region.parameters==class_ports(interface)
                    and step.arguments==tuple(P.ProductionParameter(region.id,i) for i in range(len(region.parameters)))
                    and outputs=={(C.FALLTHROUGH,None):(interface.world,)},
                    'CLASS_INTERFACE',str(identity),'class activation must consume the exact environment/namespace/world first')
            elif type(instruction) in (P.ReadBuildClass,P.BuildClassBody,P.InitializeClassNamespace,
                    P.FinalizeClassNamespace,P.BuildGenericBase,P.BuildTypeAlias):
                _require(bool(args) and type(args[-1]) is ValueType and args[-1].kind is ValueKind.STATE,
                    'DEFINITION_INTERFACE',str(identity),'definition action requires an explicit world')
                world=args[-1];reference=ValueType(ValueKind.REFERENCE)
                count=0;normal=(reference,world)
                if type(instruction) in (P.BuildClassBody,P.InitializeClassNamespace,P.FinalizeClassNamespace):
                    interface=instruction.interface
                    class_ports(interface)
                    _require(world==interface.world,'CLASS_INTERFACE',str(identity),'class action world differs')
                    abi=interface.exception_abi
                    count=2+len(interface.captures)+int(interface.type_parameters is not None) if type(instruction) is P.BuildClassBody else 2
                    if type(instruction) is P.InitializeClassNamespace:normal=(world,)
                else:
                    abi=instruction.exception_abi
                    if type(instruction) is P.BuildGenericBase:count=1
                    elif type(instruction) is P.BuildTypeAlias:
                        lazy_interface(instruction.expression)
                        _require(not instruction.expression.unpack_starred,'DEFINITION_INTERFACE',str(identity),'alias value is not a starred parameter default')
                        count=1+int(instruction.type_parameters is not None)
                raised=(reference,world) if abi is ExceptionABI.EXCEPTION_WORLD else (reference,reference,world)
                _require(args==(*(reference for _ in range(count)),world)
                    and outputs=={(C.FALLTHROUGH,None):normal,(C.RAISE,None):raised},
                    'DEFINITION_INTERFACE',str(identity),'definition action ports differ from the declared source contract')
            elif type(instruction) in (P.ReadContextMethod,P.InvokeContextMethod,P.ContextAwaitable,
                    P.EnterHandledException,P.RestoreHandledException,P.ContextExceptionArguments,P.PrepareReraise):
                _require(bool(args) and type(args[-1]) is ValueType and args[-1].kind is ValueKind.STATE,
                    'CONTEXT_INTERFACE',str(identity),'context operation requires an explicit world')
                world=args[-1];reference=ValueType(ValueKind.REFERENCE)
                raised=None
                if type(instruction) is P.RestoreHandledException:
                    expected=(reference,world);normal=(world,)
                else:
                    abi=instruction.exception_abi
                    packet=(reference,world) if abi is ExceptionABI.EXCEPTION_WORLD else (reference,reference,world)
                    if type(instruction) in (P.EnterHandledException,P.ContextExceptionArguments,P.PrepareReraise):
                        expected=packet
                        normal=(reference,world) if type(instruction) is P.EnterHandledException else (
                            (reference,reference,reference,world) if type(instruction) is P.ContextExceptionArguments else packet)
                    else:
                        exit_method=instruction.method in (P.ContextMethodKind.EXIT,P.ContextMethodKind.ASYNC_EXIT)
                        _require(type(instruction) is not P.ContextAwaitable or instruction.method in (
                            P.ContextMethodKind.ASYNC_ENTER,P.ContextMethodKind.ASYNC_EXIT),
                            'CONTEXT_INTERFACE',str(identity),'only an async context method acquires an await iterator')
                        expected=(*(reference for _ in range(4 if type(instruction) is P.InvokeContextMethod and exit_method else 1)),world)
                        normal=(reference,world);raised=packet
                wanted={(C.FALLTHROUGH,None):normal}
                if raised is not None:wanted[(C.RAISE,None)]=raised
                _require(args==expected and outputs==wanted,'CONTEXT_INTERFACE',str(identity),
                    'context operation input/completion ports differ from its language contract')
            elif type(instruction) in (P.MatchExceptionType,P.DeleteExceptionBinding):
                _require(bool(args) and type(args[-1]) is ValueType and args[-1].kind is ValueKind.STATE,
                    'EXCEPT_INTERFACE',str(identity),'exception matching/cleanup requires an explicit world')
                world=args[-1];reference=ValueType(ValueKind.REFERENCE)
                match=type(instruction) is P.MatchExceptionType
                if not match:_require(instruction.port>=0,'EXCEPT_INTERFACE',str(identity),'negative source exception binding port')
                normal=(ValueType(ValueKind.DATA,'builtins.bool'),world) if match else (world,)
                raised=(reference,world) if instruction.exception_abi is ExceptionABI.EXCEPTION_WORLD else (reference,reference,world)
                _require(args==((reference,reference,world) if match else (world,))
                    and outputs=={(C.FALLTHROUGH,None):normal,(C.RAISE,None):raised},
                    'EXCEPT_INTERFACE',str(identity),'exception matching/cleanup ports differ from the language contract')
            elif type(instruction) in (P.ImportRequest, P.ImportMember, P.ImportStar):
                _require(bool(args) and type(args[-1]) is ValueType and args[-1].kind is ValueKind.STATE,
                    'IMPORT_INTERFACE', str(identity), 'import requires one explicit source world')
                world, reference = args[-1], ValueType(ValueKind.REFERENCE)
                member = type(instruction) is P.ImportMember
                _require(args == ((reference, world) if member or type(instruction) is P.ImportStar else (world,)),
                    'IMPORT_INTERFACE', str(identity), 'import request/member/star arguments differ')
                if not member:
                    _require(instruction.environment >= 0, 'IMPORT_INTERFACE', str(identity), 'negative source namespace')
                    if type(instruction) is P.ImportRequest:
                        _require((instruction.fromlist is None) == (instruction.level is None)
                            and (instruction.fromlist is None or bool(instruction.fromlist)),
                            'IMPORT_INTERFACE', str(identity), 'source from-import requires nonempty names and an explicit level')
                        _require((instruction.fromlist is None) == (instruction.from_names is None)
                            and instruction.relative_level >= 0
                            and (instruction.fromlist is not None and len(instruction.from_names) == len(instruction.fromlist)
                                or instruction.fromlist is None and instruction.relative_level == 0),
                            'IMPORT_INTERFACE', str(identity), 'resolved source import fields disagree with selector shape')
                else:
                    _require(instruction.component is None or instruction.component >= 1,
                        'IMPORT_INTERFACE', str(identity), 'dotted import component must exclude the head')
                raised = (reference, world) if instruction.exception_abi is ExceptionABI.EXCEPTION_WORLD else (reference, reference, world)
                expected = {(C.FALLTHROUGH, None): (world,) if type(instruction) is P.ImportStar else (reference, world),
                    (C.RAISE, None): raised}
                _require(outputs == expected, 'IMPORT_INTERFACE', str(identity), 'import completions differ from its source ABI')
            elif type(instruction) in (P.ApplyInplaceOperator, P.PublishAnnotation):
                _require(bool(args) and type(args[-1]) is ValueType and args[-1].kind is ValueKind.STATE,
                    'PORT_TYPES', str(identity), 'source protocol requires an explicit world')
                world, reference = args[-1], ValueType(ValueKind.REFERENCE)
                inplace = type(instruction) is P.ApplyInplaceOperator
                _require(args == ((reference, reference, world) if inplace else (world,)),
                    'PORT_TYPES', str(identity), 'source protocol argument interface differs')
                expected = {(C.FALLTHROUGH, None): (reference, world) if inplace else (world,)}
                may_raise = inplace or instruction.publication is P.AnnotationPublicationKind.STRINGIZED or instruction.conditional_registration
                if may_raise:
                    expected[(C.RAISE, None)] = ((reference, world) if instruction.exception_abi is ExceptionABI.EXCEPTION_WORLD
                        else (reference, reference, world))
                _require(outputs == expected, 'PORT_TYPES', str(identity), 'source protocol completion interface differs')
            elif type(instruction) is P.AccessBinding:
                _require(instruction.port >= 0, 'SOURCE_PORT', str(identity), 'source port must be nonnegative')
            elif type(instruction) is P.ApplyPythonProtocol:
                try:
                    signature = _resolve_protocol_rule(protocols[instruction.protocol], instruction.bindings,
                        max_nodes=max_visits, max_ports=max_visits)
                except SignatureError as error:
                    raise ProductionError('PROTOCOL_SIGNATURE', str(identity), str(error)) from error
                expected = ({(C.FALLTHROUGH, None): signature.results} if signature.form is SignatureForm.ORDINARY else {
                    (C.FALLTHROUGH if c.kind is ExitKind.NORMAL else C.RAISE, None): c.types
                    for c in signature.completions})
                _require(signature.arguments == args and expected == outputs, 'PORT_TYPES', str(identity),
                         'protocol ports/completions differ from the declared signature and explicit parameters')
            elif type(instruction) is P.ApplyDelegationProtocol:
                try:
                    signature = resolve_delegation_signature(instruction.protocol, instruction.bindings,
                        max_nodes=max_visits, max_ports=max_visits)
                except (SignatureError, ValueError) as error:
                    raise ProductionError('DELEGATION_SIGNATURE', str(identity), str(error)) from error
                expected = ({(C.FALLTHROUGH, None): signature.results} if signature.form is SignatureForm.ORDINARY else {
                    (C.FALLTHROUGH if c.kind is ExitKind.NORMAL else C.RAISE, None): c.types
                    for c in signature.completions})
                _require(signature.arguments == args and expected == outputs, 'PORT_TYPES', str(identity),
                         'delegation ports/completions differ from the explicit signature')
            elif type(instruction) is P.ApplyRegion:
                _require(not args and invoke(instruction.invocation,shared=True) == outputs, 'PORT_TYPES', str(identity),
                         'region application completions differ or duplicate explicit call arguments')
            elif type(instruction) is P.HandleCompletions:
                _require(not args and bool(instruction.routes), 'COMPLETION_ROUTE', str(identity),
                         'handler control uses explicit call/capture arguments and nonempty routes')
                protected = invoke(instruction.protected,shared=True)
                merged, routed = {}, set()
                for route in instruction.routes:
                    key = route.kind, route.target
                    _require(key in protected and key not in routed, 'COMPLETION_ROUTE', str(identity),
                             'route must select one distinct declared protected completion')
                    routed.add(key)
                    handler = child(route.handler, P.ProductionRegionKind.HANDLER)
                    _require(handler.parameters == (*protected[key], *(value_type(v) for v in route.captures)),
                             'PORT_TYPES', str(identity), 'handler inputs must be payload followed by captures')
                    for result, types in region_outputs[handler.id].items():
                        _require(result not in merged or merged[result] == types, 'PORT_TYPES', str(identity),
                                 'handler completion interfaces disagree')
                        merged[result] = types
                for key, types in protected.items():
                    if key not in routed:
                        _require(key not in merged or merged[key] == types, 'PORT_TYPES', str(identity),
                                 'unhandled completion interface disagrees with handler output')
                        merged[key] = types
                _require(merged == outputs, 'PORT_TYPES', str(identity), 'handled completion union differs')
            elif type(instruction) is P.BranchControl:
                _require(args == (ValueType(ValueKind.DATA, 'builtins.bool'),), 'PORT_TYPES', str(identity),
                         'branch requires exactly one boolean decision')
                alternatives = {}
                for call in (instruction.on_true, instruction.on_false):
                    for key, types in invoke(call).items():
                        _require(key not in alternatives or alternatives[key] == types,
                                 'PORT_TYPES', str(identity), 'alternative completion interfaces disagree')
                        alternatives[key] = types
                _require(alternatives == outputs, 'PORT_TYPES', str(identity), 'branch completion union differs')
            elif type(instruction) is P.LoopControl:
                _require(region.kind is P.ProductionRegionKind.LOOP and args == region.parameters,
                         'LOOP_INTERFACE', str(identity), 'loop control needs its carried parameter interface')
                _require(0 <= instruction.invariant_count <= len(args), 'LOOP_INTERFACE', str(identity),
                         'invariant prefix must fit the explicit input interface')
                carried = args[instruction.invariant_count:]
                targets = (region.id,) + (() if instruction.source_loop is None else (instruction.source_loop,))
                local_jumps = tuple((kind, target) for target in targets for kind in (C.BREAK, C.CONTINUE))
                consumed = ((C.FALLTHROUGH, None), *local_jumps)
                def has_break():
                    return any((C.BREAK, target) in region_outputs[instruction.body] for target in targets)
                body = child(instruction.body, P.ProductionRegionKind.LOOP_BODY)
                if type(instruction.condition) is P.IterationCondition:
                    iteration = instruction.condition
                    _require(instruction.invariant_count <= iteration.world_parameter < len(args)
                        and type(args[iteration.world_parameter]) is ValueType
                        and args[iteration.world_parameter].kind is ValueKind.STATE,
                        'LOOP_INTERFACE', str(identity), 'iterator advancement must replace an explicit carried state port')
                    child(iteration.advance.region, P.ProductionRegionKind.LOOP_CONDITION)
                    advance_outputs = invoke(iteration.advance)
                    _require(advance_outputs.get((C.FALLTHROUGH, None)) == (
                        ValueType(ValueKind.REFERENCE), args[iteration.world_parameter])
                        and set(advance_outputs) == {(C.FALLTHROUGH, None), (C.RAISE, None)},
                        'LOOP_INTERFACE', str(identity), 'advance returns one transient item/current world or raises')
                    raised = advance_outputs[(C.RAISE, None)]
                    _require(raised and raised[-1] == args[iteration.world_parameter],
                        'LOOP_INTERFACE', str(identity), 'advance exception must carry its current world')
                    matcher = child(iteration.exhausted, P.ProductionRegionKind.HANDLER)
                    _require(matcher.parameters == raised and region_outputs[matcher.id] == {
                        (C.FALLTHROUGH, None): (ValueType(ValueKind.DATA, 'builtins.bool'),)},
                        'LOOP_INTERFACE', str(identity), 'exhaustion predicate consumes the original exception payload')
                    _require(body.parameters == (*region.parameters, ValueType(ValueKind.REFERENCE)),
                        'LOOP_INTERFACE', str(identity), 'iterator item is a transient body port, not a carried value')
                    escaped = {(C.RAISE, None): raised}
                    for key, types in region_outputs[body.id].items():
                        if key not in consumed:
                            _require(key not in escaped or escaped[key] == types, 'LOOP_INTERFACE', str(identity),
                                     'iterator/body escaping completion interfaces differ')
                            escaped[key] = types
                    if instruction.otherwise is None:
                        escaped[(C.FALLTHROUGH, None)] = carried
                    else:
                        otherwise = child(instruction.otherwise, P.ProductionRegionKind.ALTERNATIVE)
                        for key, types in region_outputs[otherwise.id].items():
                            _require(key not in escaped or escaped[key] == types, 'LOOP_INTERFACE', str(identity),
                                     'iterator otherwise completion interfaces differ')
                            escaped[key] = types
                        if has_break():
                            _require((C.FALLTHROUGH, None) not in escaped or escaped[(C.FALLTHROUGH, None)] == carried,
                                     'LOOP_INTERFACE', str(identity), 'break and otherwise result interfaces differ')
                            escaped[(C.FALLTHROUGH, None)] = carried
                    _require(outputs == escaped, 'LOOP_INTERFACE', str(identity), 'iterator loop dropped or invented a completion')
                elif type(instruction.condition) is P.RepeatCondition:
                    _require(body.parameters == region.parameters and instruction.otherwise is None,
                        'LOOP_INTERFACE', str(identity), 'unconditional repetition has no condition/otherwise evaluation')
                    escaped = {key: types for key, types in region_outputs[body.id].items() if key not in consumed}
                    if has_break():
                        escaped[(C.FALLTHROUGH, None)] = carried
                    _require(outputs == escaped, 'LOOP_INTERFACE', str(identity),
                        'unconditional loop may complete normally only through its body break')
                else:
                    condition = child(instruction.condition, P.ProductionRegionKind.LOOP_CONDITION)
                    _require(condition.parameters == body.parameters == region.parameters,
                             'LOOP_INTERFACE', str(identity), 'loop condition/body carry ports differ')
                    _require(region_outputs[condition.id].get((C.FALLTHROUGH, None)) == (
                        ValueType(ValueKind.DATA, 'builtins.bool'), *carried),
                        'LOOP_INTERFACE', str(identity), 'loop condition returns decision then carried values')
                    _require(not any(key in region_outputs[condition.id] for key in local_jumps),
                        'LOOP_INTERFACE', str(identity), 'condition cannot break/continue its own loop')
                    escaped = {}
                    for row in (condition, body):
                        for key, types in region_outputs[row.id].items():
                            if key not in consumed:
                                _require(key not in escaped or escaped[key] == types, 'LOOP_INTERFACE', str(identity),
                                    'condition/body escaping completion interfaces differ')
                                escaped[key] = types
                    if instruction.otherwise is None:
                        escaped[(C.FALLTHROUGH, None)] = carried
                    else:
                        otherwise = child(instruction.otherwise, P.ProductionRegionKind.ALTERNATIVE)
                        for key, types in region_outputs[otherwise.id].items():
                            _require(key not in escaped or escaped[key] == types, 'LOOP_INTERFACE', str(identity),
                                'loop otherwise completion interfaces differ')
                            escaped[key] = types
                        if has_break():
                            _require((C.FALLTHROUGH, None) not in escaped or escaped[(C.FALLTHROUGH, None)] == carried,
                                'LOOP_INTERFACE', str(identity), 'break and otherwise result interfaces differ')
                            escaped[(C.FALLTHROUGH, None)] = carried
                    _require(outputs == escaped, 'LOOP_INTERFACE', str(identity), 'loop dropped or invented a completion')
                for key in consumed:
                    if key in region_outputs[body.id]:
                        _require(region_outputs[body.id][key] == carried,
                                 'LOOP_INTERFACE', str(identity), 'loop body backedge/exit carry ports differ')
                if instruction.otherwise is not None:
                    otherwise = child(instruction.otherwise, P.ProductionRegionKind.ALTERNATIVE)
                    _require(otherwise.parameters == region.parameters, 'LOOP_INTERFACE', str(identity),
                             'loop otherwise carry ports differ')
            elif type(instruction) is P.DeferRegion:
                body = child(instruction.body, P.ProductionRegionKind.DEFERRED)
                environment = instruction.environment
                _require(not args and outputs == {(C.FALLTHROUGH, None): (ValueType(ValueKind.REFERENCE),)},
                    'DEFERRED_INTERFACE', str(identity), 'code declaration has no eager execution/capture arguments')
                _require(body.parameters == deferred_ports(environment), 'DEFERRED_INTERFACE', str(identity),
                    'later entry requires environment, source-order admitted values and a fresh world')
                _require(body.steps and body.steps[0] in steps and type(steps[body.steps[0]].instruction) is P.EnterDeferredBody
                    and steps[body.steps[0]].instruction.environment == environment,
                    'DEFERRED_INTERFACE', str(identity), 'body must start with its declared activation')
                raised = (*((ValueType(ValueKind.REFERENCE),) * (1 if environment.exception_abi is ExceptionABI.EXCEPTION_WORLD else 2)), environment.world)
                allowed = {(C.RETURN, None): (ValueType(ValueKind.REFERENCE), environment.world), (C.RAISE, None): raised}
                _require(all(k in allowed and allowed[k] == v for k, v in region_outputs[body.id].items()),
                    'DEFERRED_INTERFACE', str(identity), 'deferred body may return/raise with its declared world, not fall through')
            elif type(instruction) is P.ReferenceEnvironment:
                reference = instruction.source
                _require((reference.scope if type(reference) is P.GlobalsEnvironment else reference.relay) >= 0,
                    'DEFERRED_INTERFACE', str(identity), 'environment handle reference must be nonnegative')
                _require(len(args) == 1 and type(args[0]) is ValueType and args[0].kind is ValueKind.STATE
                    and outputs == {(C.FALLTHROUGH, None): (ValueType(ValueKind.REFERENCE), args[0])},
                    'DEFERRED_INTERFACE', str(identity), 'environment reference retains a handle, not cell contents')
            elif type(instruction) is P.EnterDeferredBody:
                _require(region.kind is P.ProductionRegionKind.DEFERRED and ordinal == 0
                    and args == deferred_ports(instruction.environment)
                    and step.arguments == tuple(P.ProductionParameter(region.id, i) for i in range(len(region.parameters)))
                    and outputs == {(C.FALLTHROUGH, None): (instruction.environment.world,)},
                    'DEFERRED_INTERFACE', str(identity), 'activation must consume the exact admitted entry ports first')
            elif type(instruction) is P.SuspendExecution:
                _require(len(args) == 2 and args[0] == ValueType(ValueKind.REFERENCE)
                    and type(args[1]) is ValueType and args[1].kind is ValueKind.STATE,
                    'SUSPEND_INTERFACE', str(identity), 'handoff must export a reference and its current world')
                delegated = instruction.suspension in (P.SuspensionKind.AWAIT, P.SuspensionKind.YIELD_FROM)
                _require((instruction.delegate is not None) == delegated, 'SUSPEND_INTERFACE', str(identity),
                    'await/yield-from require an explicit delegate; ordinary yield must not have one')
                if delegated:
                    _require(value_type(instruction.delegate) == ValueType(ValueKind.REFERENCE),
                        'SUSPEND_INTERFACE', str(identity), 'delegate must be a visible reference operand')
                saved = tuple(value_type(v) for v in instruction.saved)
                _require(not any(type(t) is ValueType and t.kind is ValueKind.STATE for t in saved),
                    'SUSPEND_INTERFACE', str(identity), 'state must enter afresh, never through a saved value')
                _require(len(instruction.routes) == 2 and {r.kind for r in instruction.routes} == {C.FALLTHROUGH, C.RAISE}
                    and len({r.region for r in instruction.routes}) == 2,
                    'SUSPEND_INTERFACE', str(identity), 'one distinct normal and exceptional temporal ingress is required')
                merged = {}
                for route in instruction.routes:
                    target = child(route.region, P.ProductionRegionKind.RESUME)
                    count = (1 if route.kind is C.FALLTHROUGH
                        or instruction.exception_abi is ExceptionABI.EXCEPTION_WORLD else 2)
                    payload = (*(ValueType(ValueKind.REFERENCE) for _ in range(count)), args[1])
                    _require(target.parameters == (*payload, *saved), 'SUSPEND_INTERFACE', str(identity),
                        'resumption requires normalized delivery/current world followed by saved values')
                    for key, types in region_outputs[target.id].items():
                        _require(key not in merged or merged[key] == types, 'SUSPEND_INTERFACE', str(identity),
                            'temporal route completion interfaces disagree')
                        merged[key] = types
                _require(merged == outputs, 'SUSPEND_INTERFACE', str(identity),
                    'suspension must preserve all eventual route completions')
            elif type(instruction) is P.TransferCompletion:
                _require(outputs == {(instruction.kind, instruction.target): args}
                    and region_outputs[region.id].get((instruction.kind, instruction.target)) == args,
                    'COMPLETION', str(identity), 'explicit transfer differs from region/step completion')
                _require(ordinal == len(region.steps) - 1, 'VALUE_ORDER', str(identity), 'transfer must end its region')
            if (C.FALLTHROUGH, None) not in outputs:
                _require(ordinal == len(region.steps) - 1, 'VALUE_ORDER', str(identity), 'no step may follow terminal control')
            for key, types in outputs.items():
                if key != (C.FALLTHROUGH, None) or ordinal == len(region.steps) - 1:
                    _require(key not in escaping or escaping[key] == types, 'REGION_EXIT', str(region.id),
                             'escaping completion interfaces disagree')
                    escaping[key] = types
            available[identity] = outputs
        _require(escaping == region_outputs[region.id], 'REGION_EXIT', str(region.id),
                 'normal result and all escaping completions must match the region interface')
    _require(claimed == set(steps), 'STEP_OWNER', 'plan.steps', 'unowned steps remain')
    _require(referenced_regions == set(regions), 'REGION_REFERENCE', 'plan.regions', 'unreferenced region templates remain')
    sites = [item.field for item in plan.slots]
    _require(len(set(sites)) == len(sites), 'SOURCE_SLOT', 'plan.slots', 'each source slot gets one disposition')
    # Every source reference is nonnegative even when original material is not attached.
    for row in (*plan.regions, *plan.steps):
        if type(row.source) is P.ProductionOccurrence:
            _require(row.source.occurrence >= 0, 'SOURCE', str(row.id), 'negative source occurrence')
    return dict(complete=True, visits=visits, regions=len(regions), steps=len(steps),
        recipe_shape_checked=True, local_references_checked=True, source_rules_replayed=False,
        protocol_signature_checks=sum(type(s.instruction) is P.ApplyPythonProtocol for s in plan.steps),
        delegation_signature_checks=sum(type(s.instruction) is P.ApplyDelegationProtocol for s in plan.steps),
        operation_signatures_checked=False, control_semantics_checked=False, rewrite_authorized=False)


class ProductionSourceIndex:
    """Reuse accepted F2/F3 views; do not parse, copy ASTs or replay F3 per plan.

    Construction checks input identity, not fresh upstream acceptance. Callers
    must obtain the views from the existing strict parent readers.
    """
    def __init__(self, f0, context_view, frontend_view):
        from scar.analysis.frontend_bindings import FrontendBindingView
        from scar.analysis.source_context_view import SourceContextView
        _require(type(context_view) is SourceContextView and type(frontend_view) is FrontendBindingView,
                 'INPUT', 'views', 'expected original typed F2/F3 views')
        syntax = context_view.syntax
        _require(type(f0) is dict and syntax.input.f0_document_sha256 == _digest(f0)
            and syntax.input.path == f0.get('path') and context_view.roles == frontend_view.roles
            and context_view.material == frontend_view.contexts,
            'INPUT_LINEAGE', 'views', 'views do not share the original source/context material')
        self.context, self.frontend = context_view, frontend_view
        self.roles = context_view.role_view
        self._deferred = None
        self._statements = None
        self._type_parameters = None
        self._definitions = None
        self._role_sites = frozenset(port.site for port in frontend_view.roles.ports)
        self.input = P.ProductionInput(f0['path'], f0['namespace_root'], _digest(encode(syntax)),
            _digest(encode(context_view.roles)), _digest(encode(context_view.material)),
            _digest(encode(frontend_view.declarations)), _digest(encode(frontend_view.bindings)))

    @property
    def deferred(self):
        if self._deferred is None:
            self._deferred = DeferredInterfaceIndex(self)
        return self._deferred

    @property
    def statements(self):
        if self._statements is None:
            self._statements = SourceStatementInterfaceIndex(self)
        return self._statements

    @property
    def type_parameters(self):
        if self._type_parameters is None:self._type_parameters=TypeParameterInterfaceIndex(self)
        return self._type_parameters

    @property
    def definitions(self):
        if self._definitions is None:self._definitions=DefinitionInterfaceIndex(self)
        return self._definitions

    def match(self, plan, *, max_visits=1_000_000):
        summary = validate_production_plan(plan, max_visits=max_visits)
        _require(plan.input == self.input, 'INPUT_LINEAGE', 'plan.input', 'recipe refers to different F2/F3 materials')

        def source(ref):
            if type(ref) is P.ProductionOccurrence:
                _require(0 <= ref.occurrence < len(self.context.syntax.nodes), 'SOURCE_REFERENCE', 'source',
                         'occurrence outside original F2')
                return self.context.entry_context(ref.occurrence)
            return self.context.context_at_slot(ref).state

        try:
            region_index = {r.id: r for r in plan.regions}
            for region in plan.regions:
                _require(region.context == source(region.source), 'SOURCE_CONTEXT', str(region.id),
                         'region context differs from its original F2/F3 source reference')
                if region.kind is P.ProductionRegionKind.TYPE_PARAMETERS:
                    scope=self.context.material.scopes[region.context.environment]
                    parent=region_index.get(region.parent)
                    _require(scope.kind=='TYPE_PARAMETERS' and region.source==scope.anchor
                        and parent is not None and scope.parent==parent.context.environment,
                        'SOURCE_TYPE_PARAMETERS',str(region.id),'factory scope must connect its original creator namespace')
                for completion in region.completions:
                    if type(completion.target) is P.SourceLoopTarget:
                        _require(completion.target == self.statements.active_loop(region.source),
                            'SOURCE_LOOP', str(region.id), 'escaping loop completion has a different lexical target')
                if region.kind is P.ProductionRegionKind.COMPREHENSION:
                    parent = region_index.get(region.parent)
                    scope = self.context.material.scopes[region.context.environment]
                    _require(parent is not None and scope.kind == 'COMPREHENSION'
                        and scope.parent == parent.context.environment,
                        'SOURCE_SCOPE', str(region.id), 'comprehension activation must use its original child namespace')
            for step in plan.steps:
                source(step.source)
                for completion in step.completions:
                    if type(completion.target) is P.SourceLoopTarget:
                        _require(completion.target == self.statements.active_loop(step.source),
                            'SOURCE_LOOP', str(step.id), 'child/transfer completion has a different lexical loop target')
                instruction = step.instruction
                if type(instruction) is P.MatchExceptionType:
                    site=instruction.source
                    field,value=self.roles.locate(site)
                    parent=self.roles.parents.get(site.occurrence)
                    _require(step.source==site and site.group=='FIELD' and not site.item_path and field.name=='type'
                        and value.kind=='NODE' and self.context.syntax.nodes[site.occurrence].constructor=='ExceptHandler'
                        and parent is not None and self.context.syntax.nodes[parent.occurrence].constructor=='Try',
                        'SOURCE_EXCEPT',str(step.id),'ordinary exception matching requires its original Try handler type')
                elif type(instruction) is P.DeleteExceptionBinding:
                    _require(type(step.source) is P.SlotRef and self.roles.locate(step.source)[0].name=='name'
                        and instruction.port==self.statements.exception_binding(step.source.occurrence),
                        'SOURCE_EXCEPT',str(step.id),'cleanup deletion requires its original exception binding and cleanup policy')
                elif type(instruction) in (P.ReadContextMethod,P.InvokeContextMethod,P.ContextAwaitable):
                    site=instruction.source
                    field,value=self.roles.locate(site)
                    parent=self.roles.parents.get(site.occurrence)
                    _require(site.group=='FIELD' and not site.item_path and field.name=='context_expr'
                        and value.kind=='NODE' and self.context.syntax.nodes[site.occurrence].constructor=='withitem'
                        and parent is not None and self.roles.locate(parent)[0].name=='items'
                        and self.context.syntax.nodes[parent.occurrence].constructor in ('With','AsyncWith')
                        and step.source==site,
                        'SOURCE_CONTEXT_MANAGER',str(step.id),'context method requires its original withitem expression')
                    asynchronous=self.context.syntax.nodes[parent.occurrence].constructor=='AsyncWith'
                    _require(asynchronous==(instruction.method in (P.ContextMethodKind.ASYNC_ENTER,P.ContextMethodKind.ASYNC_EXIT)),
                        'SOURCE_CONTEXT_MANAGER',str(step.id),'context method phase differs from its original sync/async declaration')
                elif type(instruction) in (P.EnterTypeParameters,P.InvokeTypeParameterFactory):
                    environment=instruction.environment
                    scope=self.context.material.scopes[environment.scope]
                    _require(environment==self.type_parameters.environment(scope.owner.occurrence,environment.world,environment.exception_abi),
                        'SOURCE_TYPE_PARAMETERS',str(step.id),'factory interface differs from original source scope/parameters/defaults/captures')
                elif type(instruction) in (P.DeferClassBody,P.EnterClassBody,P.BuildClassBody,P.InitializeClassNamespace,P.FinalizeClassNamespace):
                    interface=instruction.interface
                    scope=self.context.material.scopes[interface.scope]
                    owner=scope.owner.occurrence
                    _require(interface==self.definitions.class_body(owner,interface.world,interface.exception_abi),
                        'SOURCE_CLASS',str(step.id),'class interface differs from original scope/captures/protocol bindings')
                    creator=type(instruction) in (P.DeferClassBody,P.BuildClassBody)
                    _require(region_index[step.region].context.environment==(scope.parent if creator else interface.scope),
                        'SOURCE_CLASS',str(step.id),'class operation crossed its original creator/body namespace')
                    if creator:
                        _require(step.source==P.ProductionOccurrence(owner),'SOURCE_CLASS',str(step.id),'class creation requires its original definition')
                    if type(instruction) is P.DeferClassBody:
                        body=region_index[instruction.body]
                        _require(body.source==P.SlotRef(owner,'FIELD',self.roles.fields['ClassDef']['body'])
                            and body.context.environment==interface.scope,
                            'SOURCE_CLASS',str(step.id),'class callback must retain its original body scope')
                elif type(instruction) in (P.ReadBuildClass,P.BuildGenericBase,P.BuildTypeAlias):
                    _require(type(step.source) is P.ProductionOccurrence,'SOURCE_DEFINITION',str(step.id),'definition action requires its source owner')
                    owner=step.source.occurrence
                    if type(instruction) is P.BuildTypeAlias:
                        _require(instruction==self.definitions.alias(owner,instruction.exception_abi),
                            'SOURCE_DEFINITION',str(step.id),'alias differs from original binder/evaluator/type parameters')
                        scope=self.context.material.scopes[instruction.expression.scope]
                    else:
                        _require(self.context.syntax.nodes[owner].constructor=='ClassDef'
                            and (type(instruction) is not P.BuildGenericBase or bool(self.roles.field(owner,'type_params').items)),
                            'SOURCE_DEFINITION',str(step.id),'builder or generic base requires its original class declaration')
                        scope=self.context.material.scopes[self.definitions.classes[owner]]
                    _require(region_index[step.region].context.environment==scope.parent,
                        'SOURCE_DEFINITION',str(step.id),'definition action crossed its original creation namespace')
                elif type(instruction) is P.BuildLazyExpression:
                    expression=instruction.expression
                    field,_=self.roles.locate(expression.source)
                    allow=self.context.syntax.nodes[expression.source.occurrence].constructor=='TypeVarTuple' and field.name=='default_value'
                    scope=self.context.material.scopes[expression.scope]
                    _require(expression==self.type_parameters.lazy(expression.source,allow_starred=allow)
                        and step.source==expression.source and region_index[step.region].context.environment==scope.parent,
                        'SOURCE_TYPE_PARAMETERS',str(step.id),'lazy evaluator source or creation namespace differs')
                elif type(instruction) in (P.CreateTypeParameter,P.SetTypeParameterDefault,P.BindTypeParameter):
                    parameter=instruction.parameter
                    _require(parameter==self.type_parameters.spec(parameter.name.occurrence)
                        and step.source==P.ProductionOccurrence(parameter.name.occurrence)
                        and region_index[step.region].context.environment==self.context.entry_context(parameter.name.occurrence).environment,
                        'SOURCE_TYPE_PARAMETERS',str(step.id),'type parameter differs from its original source interface/namespace')
                elif type(instruction) is P.AttachTypeParameters:
                    scope=self.context.material.scopes[region_index[step.region].context.environment]
                    _require(step.source==instruction.source and scope.kind=='TYPE_PARAMETERS'
                        and scope.anchor==instruction.source,
                        'SOURCE_TYPE_PARAMETERS',str(step.id),'type tuple association requires its original factory scope')
                elif type(instruction) is P.EvaluateChild:
                    _, value = self.roles.locate(instruction.field)
                    _require(instruction.field.group == 'FIELD' and value.kind in ('NODE', 'LIST'),
                             'SOURCE_REFERENCE', str(step.id), 'evaluated child must be an original child field')
                    if instruction.purpose is P.ProductionPurpose.STATEMENT:
                        _require(value.kind == 'NODE'
                            and {(c.kind, c.target) for c in step.completions}
                                == set(self.statements.completions(value.reference)),
                            'STATEMENT_INTERFACE', str(step.id), 'statement child must retain its source completion obligations')
                elif type(instruction) is P.ApplyInplaceOperator:
                    site = instruction.operator
                    _, value = self.roles.locate(site)
                    _require(site.group == 'FIELD' and not site.item_path
                        and step.source == P.ProductionOccurrence(site.occurrence)
                        and self.context.syntax.nodes[site.occurrence].constructor == 'AugAssign'
                        and site.ordinal == self.roles.fields['AugAssign']['op'] and value.kind == 'NODE'
                        and self.context.syntax.nodes[value.reference].constructor in ('Add', 'Sub', 'Mult', 'MatMult',
                            'Div', 'Mod', 'Pow', 'LShift', 'RShift', 'BitOr', 'BitXor', 'BitAnd', 'FloorDiv'),
                        'SOURCE_OPERATOR', str(step.id), 'inplace operator must retain its original AugAssign selector')
                elif type(instruction) is P.PublishAnnotation:
                    _require(type(step.source) is P.ProductionOccurrence
                        and instruction == self.statements.annotation_publication(step.source.occurrence, instruction.exception_abi),
                        'SOURCE_ANNOTATION', str(step.id), 'annotation publication differs from original scope/phase/name')
                elif type(instruction) in (P.BuildFunction,P.BuildFunctionAnnotations):
                    _require(type(step.source) is P.ProductionOccurrence, 'SOURCE_FUNCTION', str(step.id), 'function creation requires its original definition')
                    owner = step.source.occurrence
                    annotations = self.deferred.annotations(owner)
                    _require(instruction.annotations == annotations, 'SOURCE_FUNCTION', str(step.id), 'function annotations differ from original scope/source/captures')
                    if type(instruction) is P.BuildFunction:
                        _require(instruction.environment == self.deferred.interface(owner,instruction.environment.world,instruction.environment.exception_abi)
                            and instruction.docstring == self.statements.function_docstring(owner),
                            'SOURCE_FUNCTION', str(step.id), 'function creation differs from original entry/docstring metadata')
                    if annotations is not None:
                        _require(self.context.material.scopes[annotations.scope].parent == region_index[step.region].context.environment,
                            'SOURCE_FUNCTION', str(step.id), 'annotation creation crossed its original parent namespace')
                elif type(instruction) is P.ApplyDecorator:
                    site = instruction.source
                    field,value = self.roles.locate(site)
                    _require(step.source == site and site.group == 'FIELD' and len(site.item_path) == 1
                        and field.name == 'decorator_list' and value.kind == 'NODE'
                        and self.context.syntax.nodes[site.occurrence].constructor in ('FunctionDef','AsyncFunctionDef','ClassDef'),
                        'SOURCE_FUNCTION', str(step.id), 'decorator application requires its original source list item')
                elif type(instruction) is P.TranslateEscapingException:
                    _require(type(step.source) is P.SlotRef and step.source.group == 'FIELD'
                        and self.roles.locate(step.source)[0].name in ('body','elt')
                        and instruction.kind == self.deferred.kind(step.source.occurrence)
                        and region_index[step.region].context.environment == self.deferred.scopes[step.source.occurrence],
                        'SOURCE_FUNCTION', str(step.id), 'exception translation differs from its original deferred body kind')
                elif type(instruction) in (P.ImportRequest, P.ImportMember, P.ImportStar):
                    _require(type(step.source) is P.ProductionOccurrence, 'SOURCE_IMPORT', str(step.id), 'import needs an original occurrence anchor')
                    occurrence = step.source.occurrence
                    if type(instruction) is P.ImportRequest:
                        if self.context.syntax.nodes[occurrence].constructor == 'alias':
                            parent = self.roles.parents[occurrence]
                            expected = self.statements.import_request(parent.occurrence, instruction.exception_abi, occurrence)
                        else:
                            expected = self.statements.import_request(occurrence, instruction.exception_abi)
                    elif type(instruction) is P.ImportMember:
                        expected = self.statements.import_member(occurrence, instruction.component, instruction.exception_abi)
                    else:
                        expected = self.statements.import_star(occurrence, instruction.exception_abi)
                    _require(instruction == expected, 'SOURCE_IMPORT', str(step.id), 'import source selectors/namespace differ from original references')
                elif type(instruction) is P.LoopControl and instruction.source_loop is not None:
                    target = instruction.source_loop.occurrence
                    _require(0 <= target < len(self.context.syntax.nodes)
                        and self.context.syntax.nodes[target].constructor in ('For', 'While', 'AsyncFor')
                        and region_index[step.region].source == P.ProductionOccurrence(target),
                        'SOURCE_LOOP', str(step.id), 'shared loop template must name its original loop occurrence')
                elif type(instruction) in (P.ApplyLanguageAction, P.ApplyPythonProtocol):
                    for site in instruction.selectors:
                        self.roles.locate(site)
                elif type(instruction) is P.ConstructValue:
                    for site in instruction.payload:
                        self.roles.locate(site)
                elif type(instruction) is P.AccessBinding:
                    _require(0 <= instruction.port < len(self.frontend.roles.ports),
                             'SOURCE_PORT', str(step.id), 'port outside original F3 role table')
                    site = self.frontend.roles.ports[instruction.port].site
                    _require(site == step.source if type(step.source) is P.SlotRef else
                        site.occurrence == step.source.occurrence,
                        'SOURCE_PORT', str(step.id), 'binding port is from another source occurrence/slot')
                    binding = self.frontend.bindings.ports[instruction.port]
                    field = {P.BindingActionKind.READ: 'read_plan', P.BindingActionKind.WRITE: 'write_target',
                             P.BindingActionKind.DELETE: 'delete_target'}[instruction.action]
                    _require(getattr(binding, field) is not None, 'SOURCE_PORT', str(step.id),
                             'role port has no declared namespace access for this action')
                elif type(instruction) in (P.DeferRegion, P.EnterDeferredBody):
                    environment = instruction.environment
                    scope = self.context.material.scopes[environment.scope]
                    expected = self.deferred.interface(scope.owner.occurrence, environment.world, environment.exception_abi)
                    _require(environment == expected, 'SOURCE_DEFERRED', str(step.id),
                        'parameters/cells/kind differ from the original source binding/forwarding interface')
                    if type(instruction) is P.DeferRegion:
                        constructor = self.context.syntax.nodes[scope.owner.occurrence].constructor
                        anchor = P.SlotRef(scope.owner.occurrence, 'FIELD', self.roles.fields[constructor][
                            'elt' if constructor == 'GeneratorExp' else 'body'])
                        _require(region_index[instruction.body].context.environment == environment.scope
                            and region_index[step.region].context.environment == scope.parent
                            and step.source == P.ProductionOccurrence(scope.owner.occurrence)
                            and region_index[instruction.body].source == anchor,
                            'SOURCE_DEFERRED', str(step.id), 'definition/body must connect original parent/child namespaces')
                    else:
                        _require(region_index[step.region].context.environment == environment.scope,
                            'SOURCE_DEFERRED', str(step.id), 'entry activation moved to another source scope')
                elif type(instruction) is P.ReferenceEnvironment:
                    handle = instruction.source
                    if type(handle) is P.GlobalsEnvironment:
                        _require(handle.scope == self.context.material.root_context.environment,
                            'SOURCE_DEFERRED', str(step.id), 'globals reference must name the original root namespace')
                    else:
                        _require(0 <= handle.relay < len(self.frontend.bindings.relays),
                            'SOURCE_DEFERRED', str(step.id), 'cell handle lacks an original forwarding hop')
                        relay = self.frontend.bindings.relays[handle.relay]
                        scope = self.context.material.scopes[relay.scope]
                        _require(handle.relay in self.deferred.captures[relay.scope]
                            and region_index[step.region].context.environment == scope.parent
                            and step.source == P.ProductionOccurrence(scope.owner.occurrence),
                            'SOURCE_DEFERRED', str(step.id), 'cell retention must use an active original child capture path')
            for disposition in plan.slots:
                self.roles.locate(disposition.field)
                if disposition.disposition is P.ProductionDispositionKind.ROLE_PORT:
                    _require(disposition.field in self._role_sites, 'SOURCE_PORT', 'plan.slots',
                             'role disposition must refer to an original F3 role port')
        except ProductionError:
            raise
        except (ValueError, TypeError, KeyError, IndexError) as error:
            raise ProductionError('SOURCE_REFERENCE', 'plan', str(error)) from error
        return {**summary, 'original_source_references_checked': True,
                'upstream_fresh_replayed': False}


def production_plan_document(plan, *, max_visits=1_000_000):
    validate_production_plan(plan, max_visits=max_visits)
    return encode(plan, record_tags=P.PRODUCTION_RECORD_TAGS)


def read_production_plan(document, *, max_visits=1_000_000):
    # Bound/cycle-check the untrusted wire before the recursive strict codec.
    _require(type(max_visits) is int and max_visits >= 0, 'QUERY_ARGUMENT', 'max_visits',
             'expected an exact nonnegative integer')
    pending, active, visits = [('ENTER', document)], set(), 0
    while pending:
        action, value = pending.pop()
        if action == 'LEAVE':
            active.remove(id(value))
            continue
        if action == 'CHILDREN':
            sentinel = object()
            child = next(value, sentinel)
            if child is not sentinel:
                pending.extend((('CHILDREN', value), ('ENTER', child)))
            continue
        _require(visits < max_visits, 'BUDGET_FRONTIER', 'document', 'wire traversal limit')
        visits += 1
        if type(value) not in (dict, list):
            _require(value is None or type(value) in (bool, int, str), 'WIRE_TYPE', 'document', 'unsupported wire scalar')
            continue
        _require(id(value) not in active, 'VALUE_CYCLE', 'document', 'cyclic wire object')
        active.add(id(value))
        children = _wire_children(value)
        pending.extend((('LEAVE', value), ('CHILDREN', children)))
    try:
        plan = decode(P.SourceProductionPlan, document, record_tags=P.PRODUCTION_RECORD_TAGS)
    except (ValueError, TypeError, AttributeError, RecursionError) as error:
        raise ProductionError('WIRE_SCHEMA', 'document', str(error)) from error
    validate_production_plan(plan, max_visits=max_visits)
    return plan


def _wire_children(value):
    if type(value) is dict:
        for key, child in value.items():
            _require(type(key) is str, 'WIRE_TYPE', 'document', 'non-string key')
            yield key
            yield child
    else:
        yield from value
