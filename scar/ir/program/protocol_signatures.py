"""Finite Python-protocol port declarations over the generic signature algebra.

These rules declare shapes and the required origins of their parameters. They
do not obtain those parameters from an operation, validate a source witness,
or grant effect/dispatch/optimization authority. In particular no display label
or observed arity participates in rule selection.
"""
from dataclasses import dataclass
from enum import Enum

from .control import ProtocolValueKind, ProtocolValueType
from .model import ExitKind, ValueKind, ValueType
from .signature_patterns import (
    Bindings, Choice, Concat, Fixed, Parameter, ParameterKind, Pattern,
    PatternCase, Repeat, ResolvedSignature, Signature, SignatureCompletion,
    SignatureError, SignatureForm, Splice, TypeKind, TypeParameter,
    instantiate_signature,
)
from .structured import PythonProtocolKind


class ExceptionABI(str, Enum):
    EXCEPTION_WORLD = 'EXCEPTION_WORLD'
    EXCEPTION_TRACEBACK_WORLD = 'EXCEPTION_TRACEBACK_WORLD'


class ProtocolStatePolicy(str, Enum):
    INVOKE_WORLD = 'INVOKE_WORLD'
    READ_WORLD = 'READ_WORLD'
    WRITE_WORLD = 'WRITE_WORLD'
    WRITE_DOMAINS = 'WRITE_DOMAINS'
    NO_STATE = 'NO_STATE'
    UNIMPLEMENTED = 'UNIMPLEMENTED'


class ParameterOrigin(str, Enum):
    STATE_DOMAIN = 'STATE_DOMAIN'
    EXCEPTION_PROFILE = 'EXCEPTION_PROFILE'
    LOCAL_BINDING = 'LOCAL_BINDING'
    FRAME_ROOTS = 'FRAME_ROOTS'
    FRAME_BINDINGS = 'FRAME_BINDINGS'
    CLEANUP_DOMAINS = 'CLEANUP_DOMAINS'
    SOURCE_PORTS = 'SOURCE_PORTS'
    UNPACK_CHILDREN = 'UNPACK_CHILDREN'
    SLICE_SHAPE = 'SLICE_SHAPE'
    CALL_SHAPE = 'CALL_SHAPE'
    FUNCTION_LAYOUT = 'FUNCTION_LAYOUT'
    CLASS_LAYOUT = 'CLASS_LAYOUT'
    CONTROL_PORT = 'CONTROL_PORT'
    COMPREHENSION_TEMPLATE = 'COMPREHENSION_TEMPLATE'


@dataclass(frozen=True, slots=True)
class ParameterRequirement:
    name: str
    origin: ParameterOrigin

    def __post_init__(self):
        if type(self.name) is not str or not self.name or type(self.origin) is not ParameterOrigin:
            raise ValueError('protocol parameter requires a name and exact origin category')


@dataclass(frozen=True, slots=True)
class ProtocolRule:
    kind: PythonProtocolKind
    signature: Signature | None
    state_policy: ProtocolStatePolicy
    requirements: tuple[ParameterRequirement, ...]

    def __post_init__(self):
        if (type(self.kind) is not PythonProtocolKind or type(self.state_policy) is not ProtocolStatePolicy
                or type(self.requirements) is not tuple
                or any(type(r) is not ParameterRequirement for r in self.requirements)):
            raise ValueError('protocol rule requires exact typed kind/state/parameter requirements')
        rejected = self.kind in (PythonProtocolKind.OPAQUE_EXPRESSION, PythonProtocolKind.OPAQUE_STATEMENT)
        if rejected:
            if self.signature is not None or self.state_policy is not ProtocolStatePolicy.UNIMPLEMENTED or self.requirements:
                raise ValueError('unimplemented protocols have no successful signature')
        elif (type(self.signature) is not Signature
                or self.state_policy is ProtocolStatePolicy.UNIMPLEMENTED
                or (self.signature.form is SignatureForm.INVOKE) != (self.state_policy is ProtocolStatePolicy.INVOKE_WORLD)
                or tuple(r.name for r in self.requirements) != tuple(p.name for p in self.signature.parameters)):
            raise ValueError('protocol signature and its ordered parameter origins disagree')


def _refs(count):
    # Fresh declarations keep callers of the public catalog independent even
    # if they deliberately mutate an otherwise frozen returned record.
    return Fixed(tuple(ValueType(ValueKind.REFERENCE) for _ in range(count)))


def _data(name, count=1):
    return Fixed(tuple(ValueType(ValueKind.DATA, data_type=name) for _ in range(count)))


def _protocol(kind):
    return Fixed((ProtocolValueType(kind),))


def _seq(*parts: Pattern):
    return Concat(tuple(parts))


def _count(name, origin):
    return Parameter(name, ParameterKind.COUNT), origin


def _type(name, sorts, origin):
    return Parameter(name, ParameterKind.TYPE, allowed_kinds=sorts), origin


def _vector(name, sorts, origin):
    return Parameter(name, ParameterKind.TYPE_VECTOR, allowed_kinds=sorts), origin


def _option(name, origin):
    parameter = Parameter(name, ParameterKind.CHOICE, choices=('ABSENT', 'PRESENT'))
    return (parameter, origin), Choice(name, (PatternCase('ABSENT', _refs(0)), PatternCase('PRESENT', _refs(1))))


def _choice(name, choices, origin):
    return Parameter(name, ParameterKind.CHOICE, choices=choices), origin


def _invoke(kind, arguments, normal, extra=(), *, abi=None):
    allowed = tuple(ExceptionABI) if abi is None else (abi,)
    parameters = (
        _type('world', (TypeKind.STATE,), ParameterOrigin.STATE_DOMAIN),
        _choice('exception_abi', tuple(a.value for a in allowed), ParameterOrigin.EXCEPTION_PROFILE),
        *extra,
    )
    raised = Choice('exception_abi', tuple(PatternCase(a.value,
        _seq(_refs(1 if a is ExceptionABI.EXCEPTION_WORLD else 2), TypeParameter('world')))
        for a in allowed))
    signature = Signature(SignatureForm.INVOKE, tuple(p for p, _ in parameters),
        _seq(arguments, TypeParameter('world')), completions=(
            SignatureCompletion(ExitKind.NORMAL, _seq(normal, TypeParameter('world'))),
            SignatureCompletion(ExitKind.RAISE, raised)))
    return ProtocolRule(kind, signature, ProtocolStatePolicy.INVOKE_WORLD,
        tuple(ParameterRequirement(p.name, origin) for p, origin in parameters))


def _ordinary(kind, arguments, results, policy, parameters=()):
    signature = Signature(SignatureForm.ORDINARY, tuple(p for p, _ in parameters), arguments, results)
    return ProtocolRule(kind, signature, policy,
        tuple(ParameterRequirement(p.name, origin) for p, origin in parameters))


def protocol_signature_catalog() -> tuple[ProtocolRule, ...]:
    """Return exactly one explicit declaration for every current protocol kind.

    Count bounds, exact literal selectors, source ownership and witness
    contents remain obligations of the named parameter-origin resolver.
    WRITE_WORLD describes a state transition, not a WHOLE footprint claim.
    """
    K, O, S = PythonProtocolKind, ParameterOrigin, ProtocolStatePolicy
    rules = {}
    def add(rule):
        if rule.kind in rules:
            raise ValueError('duplicate protocol signature catalog entry')
        rules[rule.kind] = rule

    # Fixed shapes still retain distinct kind identities. Their selector and
    # reference provenance refinements are not substituted by these arities.
    for kind, refs, outputs in (
        (K.GET_ITERATOR, 1, 1), (K.ADVANCE_ITERATOR, 1, 1), (K.MAKE_UNBOUND_LOCAL_ERROR, 0, 1),
        (K.LOOKUP_GLOBAL, 3, 1), (K.READ_FREE_CELL, 1, 1), (K.READ_LOCAL_CELL, 1, 1),
        (K.STORE_CELL, 2, 0), (K.STORE_GLOBAL, 3, 0), (K.STORE_ATTRIBUTE, 2, 0), (K.STORE_SUBSCRIPT, 3, 0),
        (K.FSTRING_CONVERT, 2, 1), (K.FSTRING_FORMAT, 2, 1),
        (K.MAP_ADD, 3, 0), (K.DICT_UPDATE, 2, 0),
        (K.EXTEND_CALL_POSITIONALS, 2, 0), (K.APPEND_CALL_POSITIONAL, 2, 0),
        (K.CALL_POSITIONALS_TO_TUPLE, 1, 1), (K.DICT_MERGE, 3, 0),
        (K.BINARY_SLICE, 3, 1), (K.STORE_SLICE, 4, 0), (K.STORE_SLICE_SUBSCRIPT, 3, 0),
        (K.SOURCE_INDEX, 2, 1), (K.STORE_NESTED_FUNCTION_CELL, 2, 0),
        (K.FUNCTION_IMPORT_NAME, 6, 1), (K.FUNCTION_IMPORT_FROM, 2, 1),
        (K.EXTEND_DISPLAY, 2, 0), (K.APPEND_DISPLAY, 2, 0), (K.DISPLAY_LIST_TO_TUPLE, 1, 1),
        (K.COMPREHENSION_BUILD, 0, 1), (K.COMPREHENSION_NEXT, 1, 1),
        (K.WITH_ENTER_CONTEXT, 1, 1), (K.WITH_EXIT_NORMAL, 3, 1), (K.WITH_EXIT_EXCEPTION, 1, 1),
    ):
        add(_invoke(kind, _refs(refs), _refs(outputs)))
    add(_invoke(K.TRUTH, _refs(1), _data('builtins.bool')))
    for kind in (K.SOURCE_BINARY, K.SOURCE_COMPARE):
        add(_invoke(kind, _seq(_refs(2), _data('builtins.str')), _refs(1)))
    for kind, refs, outputs in (
        (K.LOAD_BUILD_CLASS_314, 2, 1), (K.APPLY_CLASS_DECORATOR_314, 2, 1),
        (K.STORE_CLASS_CELL_314, 2, 0), (K.STORE_CLASS_GLOBAL_314, 3, 0),
        (K.FUNCTION_START_PROPAGATION, 1, 2), (K.FUNCTION_INPLACE_BINARY, 2, 1),
        (K.VALIDATE_EXCEPT_TYPE_314, 1, 1),
    ):
        add(_invoke(kind, _refs(refs), _refs(outputs), abi=ExceptionABI.EXCEPTION_TRACEBACK_WORLD))
    for kind, refs in ((K.GENEXPR_CONTAINS, 3), (K.GENERATOR_ESCAPE_STOPITER_TO_RUNTIME_ERROR, 1)):
        add(_invoke(kind, _refs(refs), _refs(1), abi=ExceptionABI.EXCEPTION_WORLD))
    add(_invoke(K.MAKE_UNPACK_ARITY_ERROR, _data('builtins.int', 2), _refs(1),
        abi=ExceptionABI.EXCEPTION_WORLD))

    for kind, name, origin in ((K.MAKE_CELL, 'initializer', O.FUNCTION_LAYOUT),
                               (K.MAKE_ASSERTION_ERROR, 'message', O.SOURCE_PORTS)):
        requirement, pattern = _option(name, origin)
        add(_invoke(kind, pattern, _refs(1), (requirement,)))
    for kind, refs in ((K.RERAISE, 0), (K.RAISE_EXCEPTION, 1), (K.RAISE_WITH_CAUSE, 2)):
        normal = Choice('exception_abi', tuple(PatternCase(a.value,
            _refs(1 if a is ExceptionABI.EXCEPTION_WORLD else 2)) for a in ExceptionABI))
        add(_invoke(kind, _refs(refs), normal))

    for kind in (K.BUILD_STRING, K.BUILD_CALL_POSITIONALS, K.BUILD_CALL_POSITIONAL_LIST,
                 K.BUILD_SET_DISPLAY, K.BUILD_DISPLAY_LIST):
        origin = O.CALL_SHAPE if kind in (K.BUILD_CALL_POSITIONALS, K.BUILD_CALL_POSITIONAL_LIST) else O.SOURCE_PORTS
        add(_invoke(kind, Repeat('item_count', _refs(1)), _refs(1), (_count('item_count', origin),)))
    add(_invoke(K.BUILD_MAP, Repeat('pair_count', _refs(2)), _refs(1), (_count('pair_count', O.SOURCE_PORTS),)))
    add(_invoke(K.UNPACK_FIXED, _refs(1), Repeat('child_count', _refs(1)), (_count('child_count', O.UNPACK_CHILDREN),)))
    for kind, name, origin in ((K.CALL_FUNCTION_EX, 'keyword_pack', O.CALL_SHAPE),
                               (K.BUILD_SLICE, 'slice_step', O.SLICE_SHAPE)):
        requirement, pattern = _option(name, origin)
        add(_invoke(kind, _seq(_refs(2), pattern), _refs(1), (requirement,)))

    closure = _count('closure_count', O.FUNCTION_LAYOUT)
    add(_invoke(K.MAKE_GENEXPR_FUNCTION, _seq(_refs(2), Repeat('closure_count', _refs(1))), _refs(5), (closure,)))
    add(_invoke(K.CREATE_GENEXPR, _seq(_refs(5), Repeat('closure_count', _refs(1)), _refs(1)), _refs(1), (closure,)))
    annotation, annotation_pattern = _option('annotation_code', O.FUNCTION_LAYOUT)
    add(_invoke(K.MAKE_NESTED_FUNCTION, _seq(_refs(2), Repeat('default_count', _refs(1)),
        annotation_pattern, Repeat('closure_count', _refs(1))), _refs(1),
        (_count('default_count', O.FUNCTION_LAYOUT), annotation, _count('closure_count', O.FUNCTION_LAYOUT))))
    add(_invoke(K.MAKE_LAMBDA_FUNCTION, _seq(_refs(2), Repeat('default_count', _refs(1)),
        Repeat('keyword_default_count', _refs(1)), Repeat('closure_count', _refs(1))), _refs(1),
        (_count('default_count', O.FUNCTION_LAYOUT), _count('keyword_default_count', O.FUNCTION_LAYOUT),
         _count('closure_count', O.FUNCTION_LAYOUT))))
    add(_invoke(K.MAKE_CLASS_BODY_314, _seq(_refs(2), Repeat('closure_count', _refs(1))), _refs(1),
        (_count('closure_count', O.CLASS_LAYOUT),), abi=ExceptionABI.EXCEPTION_TRACEBACK_WORLD))
    names, names_pattern = _option('keyword_names', O.CLASS_LAYOUT)
    add(_invoke(K.BUILD_CLASS_CALL_314, _seq(_refs(3), Repeat('base_count', _refs(1)),
        Repeat('keyword_count', _refs(1)), names_pattern), _refs(1),
        (_count('base_count', O.CLASS_LAYOUT), _count('keyword_count', O.CLASS_LAYOUT), names),
        abi=ExceptionABI.EXCEPTION_TRACEBACK_WORLD))
    comp_kind = _choice('comprehension_kind', ('LIST', 'SET', 'DICT'), O.COMPREHENSION_TEMPLATE)
    add(_invoke(K.COMPREHENSION_ADD, Choice('comprehension_kind', (
        PatternCase('LIST', _refs(2)), PatternCase('SET', _refs(2)), PatternCase('DICT', _refs(3)))),
        _refs(0), (comp_kind,)))

    # Ordinary reads do not manufacture a post-world result.
    for kind, refs, results in ((K.MATCH_STOP_ITERATION, 1, _data('builtins.bool')),
            (K.MATCH_EXCEPTION_BORROWED_314, 2, _data('builtins.bool')),
            (K.READ_CODE_CONSTANT, 0, _refs(1))):
        add(_ordinary(kind, _seq(_refs(refs), TypeParameter('world')), results, S.READ_WORLD,
            (_type('world', (TypeKind.STATE,), O.STATE_DOMAIN),)))

    def write(kind, prefix, parameters=()):
        add(_ordinary(kind, _seq(prefix, TypeParameter('world')), TypeParameter('world'), S.WRITE_WORLD,
            (_type('world', (TypeKind.STATE,), O.STATE_DOMAIN), *parameters)))
    write(K.FRAME_ENTER, Repeat('formal_count', _refs(1)), (_count('formal_count', O.FRAME_ROOTS),))
    write(K.FRAME_BIND, _seq(TypeParameter('binding'), _refs(1)),
        (_type('binding', (TypeKind.LOCAL_BINDING,), O.LOCAL_BINDING),))
    for kind in (K.FRAME_DISCARD, K.FRAME_HOLD_TEMPORARY, K.FRAME_RELEASE_TEMPORARY, K.FRAME_FORWARD_TEMPORARY):
        write(kind, _refs(1))
    for kind, prefix in ((K.FRAME_EXIT, _refs(1)),
                         (K.FUNCTION_FRAME_EXIT_EXCEPTION_PACKET, _protocol(ProtocolValueKind.EXCEPTION_PACKET))):
        write(kind, _seq(prefix, Splice('held_types')),
            (_vector('held_types', (TypeKind.REFERENCE, TypeKind.LOCAL_BINDING), O.FRAME_ROOTS),))
    write(K.FUNCTION_FRAME_EXIT_BINDINGS, Splice('binding_types'),
        (_vector('binding_types', (TypeKind.LOCAL_BINDING,), O.FRAME_BINDINGS),))
    write(K.FUNCTION_CLEAR_EXCEPTION_NAME, TypeParameter('binding'),
        (_type('binding', (TypeKind.LOCAL_BINDING,), O.LOCAL_BINDING),))
    container, container_pattern = _option('container', O.COMPREHENSION_TEMPLATE)
    # The original single-target producer puts its binding before the iterator;
    # scoped-target normal/failure cleanup puts references before its bindings.
    # The source resolver must supply the original vector (one legacy target)
    # and ABSENT container for the legacy branch, never infer either from uses.
    leave = Choice('comprehension_profile', (
        PatternCase('LEGACY_SINGLE_TARGET', _seq(Splice('binding_types'), _refs(1))),
        PatternCase('SCOPED_TARGETS', _seq(_refs(1), container_pattern, Splice('binding_types')))))
    write(K.COMPREHENSION_LEAVE, leave,
        (_choice('comprehension_profile', ('LEGACY_SINGLE_TARGET', 'SCOPED_TARGETS'), O.COMPREHENSION_TEMPLATE),
         container, _vector('binding_types', (TypeKind.LOCAL_BINDING,), O.COMPREHENSION_TEMPLATE)))

    add(_ordinary(K.FUNCTION_EXCEPTION_PACKET, _refs(2), _protocol(ProtocolValueKind.EXCEPTION_PACKET), S.NO_STATE))
    pending_cases = tuple(PatternCase(kind, _refs(1) if kind == 'RETURN' else
        _protocol(ProtocolValueKind.EXCEPTION_PACKET) if kind == 'RAISE' else _refs(0))
        for kind in ('FALLTHROUGH', 'RETURN', 'RAISE', 'BREAK', 'CONTINUE'))
    add(_ordinary(K.FUNCTION_PENDING_COMPLETION, Choice('completion_kind', pending_cases),
        _protocol(ProtocolValueKind.PENDING_COMPLETION), S.NO_STATE,
        (_choice('completion_kind', tuple(case.key for case in pending_cases), O.CONTROL_PORT),)))
    for kind, pending_count, saved_input, saved_result in (
        (K.FUNCTION_HANDLED_CONTEXT_ENTER, 1, False, True),
        (K.FUNCTION_CLEANUP_RESUME, 1, True, False),
        (K.FUNCTION_CLEANUP_REPLACE, 2, True, False),
    ):
        pending = Fixed(tuple(ProtocolValueType(ProtocolValueKind.PENDING_COMPLETION) for _ in range(pending_count)))
        saved = _protocol(ProtocolValueKind.SAVED_HANDLED_CONTEXT)
        arguments = _seq(pending, *([saved] if saved_input else []), Splice('state_types'))
        results = _seq(*([saved] if saved_result else []), Splice('state_types'))
        add(_ordinary(kind, arguments, results, S.WRITE_DOMAINS,
            (_vector('state_types', (TypeKind.STATE,), O.CLEANUP_DOMAINS),)))
    for kind in (K.OPAQUE_EXPRESSION, K.OPAQUE_STATEMENT):
        add(ProtocolRule(kind, None, S.UNIMPLEMENTED, ()))
    if set(rules) != set(K) or len(rules) != 88:
        raise ValueError('protocol catalog does not cover its complete declared kind domain')
    return tuple(rules[kind] for kind in K)


def protocol_signature_rule(kind: PythonProtocolKind) -> ProtocolRule:
    if type(kind) is not PythonProtocolKind or not any(kind is item for item in PythonProtocolKind):
        raise SignatureError('QUERY_ARGUMENT', 'kind', 'expected an exact declared PythonProtocolKind')
    return next(rule for rule in protocol_signature_catalog() if rule.kind is kind)


def _resolve_protocol_rule(rule: ProtocolRule, bindings: Bindings, *, max_nodes=10000, max_ports=100000) -> ResolvedSignature:
    """Resolve an internally retained rule without rebuilding the catalog.

    A body index owns its fresh catalog snapshot.  Public queries still obtain
    a fresh rule; this helper neither caches declarations nor accepts a label
    or observed operation shape in place of an explicit binding.
    """
    if rule.signature is None:
        raise SignatureError('UNIMPLEMENTED_PROTOCOL', 'kind', rule.kind.value + ' has no implemented protocol signature')
    resolved = instantiate_signature(rule.signature, bindings, max_nodes=max_nodes, max_ports=max_ports)
    if rule.kind is PythonProtocolKind.COMPREHENSION_LEAVE:
        # A source-production bound belongs to the parameter-origin resolver;
        # these two restrictions instead define this selected interface.  The
        # legacy producer has exactly one target, before its iterator, and no
        # container port.  Keeping the common vector avoids demanding a local
        # slot that does not exist in the other profile.
        by_name = {binding.name: binding for binding in bindings}
        if by_name['comprehension_profile'].choice == 'LEGACY_SINGLE_TARGET':
            if len(by_name['binding_types'].values) != 1:
                raise SignatureError('PROTOCOL_VARIANT', 'bindings.binding_types',
                    'LEGACY_SINGLE_TARGET requires exactly one local binding')
            if by_name['container'].choice != 'ABSENT':
                raise SignatureError('PROTOCOL_VARIANT', 'bindings.container',
                    'LEGACY_SINGLE_TARGET has no container port')
    return resolved


def resolve_protocol_signature(kind, bindings: Bindings, *, max_nodes=10000, max_ports=100000) -> ResolvedSignature:
    return _resolve_protocol_rule(protocol_signature_rule(kind), bindings,
        max_nodes=max_nodes, max_ports=max_ports)


__all__ = ['ExceptionABI', 'ProtocolStatePolicy', 'ParameterOrigin', 'ParameterRequirement',
    'ProtocolRule', 'protocol_signature_catalog', 'protocol_signature_rule', 'resolve_protocol_signature']
