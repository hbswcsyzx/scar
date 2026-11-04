"""Finite port-type patterns, independent of operations and authorization.

Both public validators recheck exact records, including mutated frozen values.
``max_nodes`` bounds declaration/pattern/binding record occurrences (all choice
branches); ``max_ports`` separately bounds inspected ground-type inputs and the
total resolved ports. No count is inferred from an observed operation.
"""
from __future__ import annotations

from dataclasses import dataclass
from enum import Enum

from .control import ProtocolValueKind
from .ids import LocationID
from .model import ExitKind, LocalBindingType, ProtocolValueType, ValueKind, ValueType
from scar.ir.v2.ids import ValueSlotID


GroundType = ValueType | LocalBindingType | ProtocolValueType


class ParameterKind(str, Enum):
    COUNT = 'COUNT'
    CHOICE = 'CHOICE'
    TYPE = 'TYPE'
    TYPE_VECTOR = 'TYPE_VECTOR'


class TypeKind(str, Enum):
    DATA = 'DATA'
    REFERENCE = 'REFERENCE'
    STATE = 'STATE'
    LOCAL_BINDING = 'LOCAL_BINDING'
    PROTOCOL = 'PROTOCOL'


class SignatureForm(str, Enum):
    ORDINARY = 'ORDINARY'
    INVOKE = 'INVOKE'


@dataclass(frozen=True, slots=True)
class Parameter:
    name: str
    kind: ParameterKind
    choices: tuple[str, ...] = ()
    allowed_kinds: tuple[TypeKind, ...] = ()


@dataclass(frozen=True, slots=True)
class CountBinding:
    name: str
    count: int


@dataclass(frozen=True, slots=True)
class ChoiceBinding:
    name: str
    choice: str


@dataclass(frozen=True, slots=True)
class TypeBinding:
    name: str
    value: GroundType


@dataclass(frozen=True, slots=True)
class TypesBinding:
    name: str
    values: tuple[GroundType, ...]


Binding = CountBinding | ChoiceBinding | TypeBinding | TypesBinding
Bindings = tuple[Binding, ...]


@dataclass(frozen=True, slots=True)
class Fixed:
    types: tuple[GroundType, ...]


@dataclass(frozen=True, slots=True)
class TypeParameter:
    name: str


@dataclass(frozen=True, slots=True)
class Concat:
    parts: tuple[Pattern, ...]


@dataclass(frozen=True, slots=True)
class Repeat:
    count_parameter: str
    body: Pattern


@dataclass(frozen=True, slots=True)
class PatternCase:
    key: str
    pattern: Pattern


@dataclass(frozen=True, slots=True)
class Choice:
    choice_parameter: str
    cases: tuple[PatternCase, ...]


@dataclass(frozen=True, slots=True)
class Splice:
    types_parameter: str


Pattern = Fixed | TypeParameter | Concat | Repeat | Choice | Splice


@dataclass(frozen=True, slots=True)
class SignatureCompletion:
    kind: ExitKind
    results: Pattern


@dataclass(frozen=True, slots=True)
class Signature:
    form: SignatureForm
    parameters: tuple[Parameter, ...]
    args: Pattern
    results: Pattern | None = None
    completions: tuple[SignatureCompletion, ...] = ()


@dataclass(frozen=True, slots=True)
class ResolvedCompletion:
    kind: ExitKind
    types: tuple[GroundType, ...]


@dataclass(frozen=True, slots=True)
class ResolvedSignature:
    form: SignatureForm
    arguments: tuple[GroundType, ...]
    results: tuple[GroundType, ...] | None = None
    completions: tuple[ResolvedCompletion, ...] = ()


SIGNATURE_RECORD_TAGS = {cls: ('record_kind', cls.__name__) for cls in (
    Parameter, CountBinding, ChoiceBinding, TypeBinding, TypesBinding, Fixed,
    TypeParameter, Concat, Repeat, PatternCase, Choice, Splice, SignatureCompletion,
    Signature, ResolvedCompletion, ResolvedSignature)}


class SignatureError(ValueError):
    def __init__(self, code, path, detail):
        self.code, self.path, self.detail = code, path, detail
        super().__init__(code + ' at ' + path + ': ' + detail)


def _at(path, suffix):
    # Keep deep traversal paths linear in memory; materialize only on failure.
    return path, suffix


def _fail(code, path, detail):
    suffixes = []
    while type(path) is tuple:
        path, suffix = path
        suffixes.append(suffix)
    raise SignatureError(code, path + ''.join(reversed(suffixes)), detail)


def _exact(value, kind, path):
    if type(value) is not kind:
        _fail('UNREGISTERED_VARIANT', path, 'expected exact ' + kind.__name__)


def _enum(value, kind, path):
    if type(value) is not kind or not any(value is member for member in kind):
        _fail('UNREGISTERED_VARIANT', path, 'expected a declared ' + kind.__name__)


def _name(value, path):
    if type(value) is not str or not value:
        _fail('INVALID_NAME', path, 'expected an exact nonempty string')


def _identifier(value, kind, path, ancestors):
    if id(value) in ancestors:
        _fail('VALUE_CYCLE', path, 'cyclic ground-type value')
    _exact(value, kind, path)
    if id(value.value) in (*ancestors, id(value)):
        _fail('VALUE_CYCLE', _at(path, '.value'), 'cyclic identifier payload')
    _name(value.value, _at(path, '.value'))
    if type(value.prefix) is not str or value.prefix != kind.prefix:
        _fail('INVALID_GROUND_TYPE', path, 'identifier prefix differs from its declared type')


def _ground(value, path):
    if type(value) is ValueType:
        for field in ('kind', 'data_type', 'location'):
            if getattr(value, field) is value:
                _fail('VALUE_CYCLE', _at(path, '.' + field), 'cyclic ground-type value')
        _enum(value.kind, ValueKind, _at(path, '.kind'))
        if value.kind is ValueKind.DATA:
            _name(value.data_type, _at(path, '.data_type'))
            if value.location is not None:
                _fail('INVALID_GROUND_TYPE', path, 'DATA forbids a state location')
            return TypeKind.DATA
        if value.kind is ValueKind.STATE:
            _identifier(value.location, LocationID, _at(path, '.location'), (id(value),))
            if value.data_type is not None:
                _fail('INVALID_GROUND_TYPE', path, 'STATE forbids a data-type field')
            return TypeKind.STATE
        if value.data_type is not None or value.location is not None:
            _fail('INVALID_GROUND_TYPE', path, 'REFERENCE has neither data-type nor location')
        return TypeKind.REFERENCE
    if type(value) is LocalBindingType:
        _identifier(value.slot, ValueSlotID, _at(path, '.slot'), (id(value),))
        return TypeKind.LOCAL_BINDING
    if type(value) is ProtocolValueType:
        if value.protocol is value:
            _fail('VALUE_CYCLE', _at(path, '.protocol'), 'cyclic ground-type value')
        _enum(value.protocol, ProtocolValueKind, _at(path, '.protocol'))
        return TypeKind.PROTOCOL
    _fail('UNREGISTERED_VARIANT', path, 'expected a registered exact ground type')


class _Budget:
    def __init__(self, max_nodes, max_ports):
        for name, value in (('max_nodes', max_nodes), ('max_ports', max_ports)):
            if type(value) is not int or value < 0:
                _fail('QUERY_ARGUMENT', name, 'expected an exact nonnegative integer')
        self.max_nodes, self.max_ports, self.nodes, self.inputs = max_nodes, max_ports, 0, 0

    def reserve(self, count, path):
        if count > self.max_nodes - self.nodes:
            _fail('BUDGET_FRONTIER', path, 'signature node budget exceeded')
        self.nodes += count

    def ground_tuple(self, values, path, allowed=None):
        _exact(values, tuple, path)
        if len(values) > self.max_ports - self.inputs:
            _fail('BUDGET_FRONTIER', path, 'ground-type input/port budget exceeded')
        self.inputs += len(values)
        for i, value in enumerate(values):
            sort = _ground(value, _at(path, '[' + str(i) + ']'))
            if allowed is not None and sort not in allowed:
                _fail('TYPE_SORT', _at(path, '[' + str(i) + ']'), 'ground type is outside the declared sort')


def _form(value, completion_type, budget):
    _enum(value.form, SignatureForm, 'signature.form')
    _exact(value.completions, tuple, 'signature.completions')
    budget.reserve(len(value.completions), 'signature.completions')
    if value.form is SignatureForm.ORDINARY:
        if value.results is None or value.completions:
            _fail('SIGNATURE_FORM', 'signature', 'ORDINARY requires results and no completions')
    elif value.results is not None or not value.completions:
        _fail('SIGNATURE_FORM', 'signature', 'INVOKE requires completions and no ordinary results')
    kinds = set()
    for i, completion in enumerate(value.completions):
        path = 'signature.completions[' + str(i) + ']'
        _exact(completion, completion_type, path)
        _enum(completion.kind, ExitKind, path + '.kind')
        if completion.kind in kinds:
            _fail('DUPLICATE_COMPLETION', path, 'completion kinds must be unique')
        kinds.add(completion.kind)


def _declarations(signature, budget):
    _exact(signature, Signature, 'signature')
    budget.reserve(1, 'signature')
    _form(signature, SignatureCompletion, budget)
    _exact(signature.parameters, tuple, 'signature.parameters')
    budget.reserve(len(signature.parameters), 'signature.parameters')
    declared = {}
    for i, parameter in enumerate(signature.parameters):
        path = 'signature.parameters[' + str(i) + ']'
        _exact(parameter, Parameter, path)
        _name(parameter.name, path + '.name')
        _enum(parameter.kind, ParameterKind, path + '.kind')
        _exact(parameter.choices, tuple, path + '.choices')
        _exact(parameter.allowed_kinds, tuple, path + '.allowed_kinds')
        budget.reserve(len(parameter.choices) + len(parameter.allowed_kinds), path)
        if parameter.name in declared:
            _fail('DUPLICATE_PARAMETER', path, 'parameter name is already declared')
        declared[parameter.name] = parameter
        if parameter.kind is ParameterKind.CHOICE:
            if not parameter.choices or parameter.allowed_kinds:
                _fail('PARAMETER_DOMAIN', path, 'CHOICE needs choices and forbids type sorts')
            if any(type(key) is not str for key in parameter.choices) or len(set(parameter.choices)) != len(parameter.choices):
                _fail('PARAMETER_DOMAIN', path, 'choices must be exact unique strings')
        elif parameter.kind in (ParameterKind.TYPE, ParameterKind.TYPE_VECTOR):
            if parameter.choices or not parameter.allowed_kinds:
                _fail('PARAMETER_DOMAIN', path, 'TYPE/TYPE_VECTOR need sorts and forbid choices')
            for kind in parameter.allowed_kinds:
                _enum(kind, TypeKind, path + '.allowed_kinds')
            if len(set(parameter.allowed_kinds)) != len(parameter.allowed_kinds):
                _fail('PARAMETER_DOMAIN', path, 'allowed sorts must be unique')
        elif parameter.choices or parameter.allowed_kinds:
            _fail('PARAMETER_DOMAIN', path, 'COUNT forbids choices and type sorts')
    roots = [(signature.args, 'signature.args')]
    if signature.results is not None:
        roots.append((signature.results, 'signature.results'))
    roots.extend((c.results, 'signature.completions[' + str(i) + '].results')
        for i, c in enumerate(signature.completions))
    return declared, roots


def _reference(name, expected, declared, path):
    _name(name, path)
    if name not in declared:
        _fail('UNDECLARED_PARAMETER', path, 'pattern references an undeclared parameter')
    if declared[name].kind is not expected:
        _fail('PARAMETER_KIND', path, 'pattern reference has the wrong parameter kind')
    return declared[name]


def _check_patterns(roots, declared, budget):
    budget.reserve(len(roots), 'signature')
    pending = [(False, node, path) for node, path in reversed(roots)]
    active = set()
    while pending:
        leaving, node, path = pending.pop()
        if leaving:
            active.remove(id(node))
            continue
        if type(node) not in (Fixed, TypeParameter, Concat, Repeat, Choice, Splice):
            _fail('UNREGISTERED_VARIANT', path, 'expected an exact registered port pattern')
        if id(node) in active:
            _fail('VALUE_CYCLE', path, 'cyclic pattern declaration')
        active.add(id(node))
        pending.append((True, node, path))
        children = ()
        if type(node) is Fixed:
            budget.ground_tuple(node.types, _at(path, '.types'))
        elif type(node) is TypeParameter:
            _reference(node.name, ParameterKind.TYPE, declared, _at(path, '.name'))
        elif type(node) is Splice:
            _reference(node.types_parameter, ParameterKind.TYPE_VECTOR, declared, _at(path, '.types_parameter'))
        elif type(node) is Repeat:
            _reference(node.count_parameter, ParameterKind.COUNT, declared, _at(path, '.count_parameter'))
            children = ((node.body, _at(path, '.body')),)
        elif type(node) is Concat:
            _exact(node.parts, tuple, _at(path, '.parts'))
            budget.reserve(len(node.parts), path)
            children = tuple((part, _at(path, '.parts[' + str(i) + ']')) for i, part in enumerate(node.parts))
        else:
            parameter = _reference(node.choice_parameter, ParameterKind.CHOICE, declared, _at(path, '.choice_parameter'))
            _exact(node.cases, tuple, _at(path, '.cases'))
            budget.reserve(len(node.cases), path)  # PatternCase records.
            keys = []
            for i, case in enumerate(node.cases):
                _exact(case, PatternCase, _at(path, '.cases[' + str(i) + ']'))
                if type(case.key) is not str:
                    _fail('CHOICE_CASES', path, 'case key must be an exact string')
                keys.append(case.key)
            if len(set(keys)) != len(keys) or set(keys) != set(parameter.choices):
                _fail('CHOICE_CASES', path, 'case keys must exactly cover declared choices')
            budget.reserve(len(node.cases), path)  # Each branch pattern.
            children = tuple((case.pattern, _at(path, '.cases[' + str(i) + '].pattern')) for i, case in enumerate(node.cases))
        if type(node) is Repeat:
            budget.reserve(1, path)
        # Concat/Choice reserved before allocating their child task arrays.
        pending.extend((False, child, child_path) for child, child_path in reversed(children))


def _bindings(bindings, declared, budget):
    _exact(bindings, tuple, 'bindings')
    budget.reserve(len(bindings), 'bindings')
    bound = {}
    kinds = {CountBinding: ParameterKind.COUNT, ChoiceBinding: ParameterKind.CHOICE,
        TypeBinding: ParameterKind.TYPE, TypesBinding: ParameterKind.TYPE_VECTOR}
    for i, binding in enumerate(bindings):
        path = 'bindings[' + str(i) + ']'
        if type(binding) not in kinds:
            _fail('UNREGISTERED_VARIANT', path, 'expected an exact registered parameter binding')
        _name(binding.name, path + '.name')
        parameter = _reference(binding.name, kinds[type(binding)], declared, path + '.name')
        if binding.name in bound:
            _fail('DUPLICATE_BINDING', path, 'parameter is already bound')
        bound[binding.name] = binding
        if type(binding) is CountBinding:
            if type(binding.count) is not int or binding.count < 0:
                _fail('COUNT_BINDING', path, 'count must be an exact nonnegative integer')
        elif type(binding) is ChoiceBinding:
            if type(binding.choice) is not str or binding.choice not in parameter.choices:
                _fail('CHOICE_BINDING', path, 'choice is outside the declared finite domain')
        elif type(binding) is TypeBinding:
            budget.ground_tuple((binding.value,), path + '.value', parameter.allowed_kinds)
        else:
            budget.ground_tuple(binding.values, path + '.values', parameter.allowed_kinds)
    if set(bound) != set(declared):
        _fail('MISSING_BINDING', 'bindings', 'every declared parameter needs one explicit binding')
    return bound


def _plans(roots, bound, max_ports):
    # Ropes discard empty children and collapse unary structure. Thus emitting
    # an empty huge Repeat is O(1), and repeated empty prefixes never cause an
    # enormous control traversal. No expanded tuple is built during planning.
    plans = {}
    for root, root_path in roots:
        pending = [(False, root, root_path)]
        while pending:
            leaving, node, path = pending.pop()
            if id(node) in plans:
                continue
            cls = type(node)
            if cls is Choice:
                children = (next(case.pattern for case in node.cases if case.key == bound[node.choice_parameter].choice),)
            elif cls is Concat:
                children = node.parts
            elif cls is Repeat:
                children = (node.body,) if bound[node.count_parameter].count else ()
            else:
                children = ()
            if children and not leaving:
                pending.append((True, node, path))
                pending.extend((False, child, path) for child in reversed(children))
                continue
            if cls in (Fixed, TypeParameter, Splice):
                values = (node.types if cls is Fixed else (bound[node.name].value,) if cls is TypeParameter
                    else bound[node.types_parameter].values)
                plan = (len(values), 'LEAF', values) if values else None
            elif cls is Choice:
                plan = plans[id(children[0])]
            elif cls is Repeat:
                count = bound[node.count_parameter].count
                child = plans[id(node.body)] if count else None
                if child is None:
                    plan = None
                else:
                    if count > max_ports // child[0]:
                        _fail('BUDGET_FRONTIER', path, 'expanded port budget exceeded before allocation')
                    plan = child if count == 1 else (count * child[0], 'REPEAT', (count, child))
            else:
                parts = tuple(plans[id(child)] for child in children if plans[id(child)] is not None)
                total = 0
                for part in parts:
                    if part[0] > max_ports - total:
                        _fail('BUDGET_FRONTIER', path, 'expanded port budget exceeded before allocation')
                    total += part[0]
                plan = None if not parts else parts[0] if len(parts) == 1 else (total, 'CONCAT', parts)
            plans[id(node)] = plan
    total = 0
    for node, path in roots:
        plan = plans[id(node)]
        size = plan[0] if plan else 0
        if size > max_ports - total:
            _fail('BUDGET_FRONTIER', path, 'total resolved port budget exceeded before allocation')
        total += size
    return plans


def _emit(plan):
    result, pending = [], [plan] if plan else []
    while pending:
        _, kind, payload = pending.pop()
        if kind == 'LEAF':
            result.extend(payload)
        elif kind == 'CONCAT':
            pending.extend(reversed(payload))
        else:
            count, child = payload
            pending.extend(child for _ in range(count))
    return tuple(result)


def validate_resolved_signature(resolved, *, max_nodes=10000, max_ports=100000) -> None:
    try:
        budget = _Budget(max_nodes, max_ports)
        _exact(resolved, ResolvedSignature, 'signature')
        budget.reserve(1, 'signature')
        _form(resolved, ResolvedCompletion, budget)
        budget.ground_tuple(resolved.arguments, 'signature.arguments')
        if resolved.results is not None:
            budget.ground_tuple(resolved.results, 'signature.results')
        for i, completion in enumerate(resolved.completions):
            budget.ground_tuple(completion.types, 'signature.completions[' + str(i) + '].types')
    except AttributeError as error:
        raise SignatureError('MALFORMED_RECORD', 'signature', 'required record field is missing') from error


def instantiate_signature(signature, bindings, *, max_nodes=10000, max_ports=100000) -> ResolvedSignature:
    try:
        budget = _Budget(max_nodes, max_ports)
        declared, roots = _declarations(signature, budget)
        _check_patterns(roots, declared, budget)
        bound = _bindings(bindings, declared, budget)
        plans = _plans(roots, bound, max_ports)
        resolved = ResolvedSignature(signature.form, _emit(plans[id(signature.args)]),
            _emit(plans[id(signature.results)]) if signature.results is not None else None,
            tuple(ResolvedCompletion(c.kind, _emit(plans[id(c.results)])) for c in signature.completions))
        validate_resolved_signature(resolved, max_nodes=max_nodes, max_ports=max_ports)
        return resolved
    except AttributeError as error:
        raise SignatureError('MALFORMED_RECORD', 'signature', 'required record field is missing') from error


__all__ = ['GroundType', 'ParameterKind', 'TypeKind', 'SignatureForm', 'Parameter',
    'CountBinding', 'ChoiceBinding', 'TypeBinding', 'TypesBinding', 'Binding', 'Bindings',
    'Fixed', 'TypeParameter', 'Concat', 'Repeat', 'PatternCase', 'Choice', 'Splice', 'Pattern',
    'SignatureCompletion', 'Signature', 'ResolvedCompletion', 'ResolvedSignature',
    'SIGNATURE_RECORD_TAGS', 'SignatureError', 'instantiate_signature', 'validate_resolved_signature']
