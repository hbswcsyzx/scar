"""Pure interpretation of a pinned provider's exact builtin scalar subset.

This module does not own captures, read artifacts, create graph records or grant
native-port correspondence. The owned caller must independently replay the
original slot, schema path and occurrence before using this local result.
"""
from __future__ import annotations

from dataclasses import dataclass
from enum import Enum
import math

from scar.ir.literals import PythonLiteral, require_exact_literal
from scar.trace.native_schema import PROVIDER_REVISION

PINNED_SCALAR_PROVIDER_REVISION = 'cf30153c4c131c8164ee7798e5022d810682e2cb'
SCALAR_CONTENT_PROFILE_V1 = 'SCAR_NATIVE_SCALAR_OBSERVED_ROOT_V1'
SCALAR_CONTENT_PROFILE_V2 = 'SCAR_NATIVE_SCALAR_OBSERVED_ROOT_V2'


class ScalarFrontier(str, Enum):
    PROVIDER_REVISION = 'SCALAR_PROVIDER_REVISION_UNSUPPORTED'
    TENSOR_REFERENCE = 'TENSOR_REFERENCE_IS_NOT_SCALAR_CONTENT'
    SYMBOLIC = 'SYMBOLIC_SCALAR_CONTENT_UNESTABLISHED'
    NON_BUILTIN_FORMAL = 'ENUM_OR_NONBUILTIN_SCALAR_FORMAL'
    FORMAL_KIND = 'SCALAR_FORMAL_LEAF_KIND_MISMATCH'
    PROVIDER_TAG = 'UNSUPPORTED_PROVIDER_SCALAR_TAG'
    CONTAINER = 'CONTAINER_OR_TRUNCATED_LEAF_IS_NOT_SCALAR'
    PAYLOAD_TYPE = 'SCALAR_BUILTIN_PAYLOAD_TYPE_MISMATCH'
    INT64_RANGE = 'SCALAR_INTEGER_OUTSIDE_PROVIDER_INT64'
    NONE_SENTINEL = 'SCALAR_NONE_PROVIDER_SENTINEL_MISMATCH'
    DOUBLE_STRINGIFIED = 'DOUBLE_STRINGIFIED_OR_NONFINITE_CONTENT'
    NONFINITE = 'NONFINITE_SCALAR_CONTENT_UNESTABLISHED'
    DOUBLE_PRECISION = 'DOUBLE_SERIALIZATION_NOT_PROVEN_LOSSLESS'
    STRING_ENCODING = 'NONASCII_PROVIDER_STRING_CONTENT_UNESTABLISHED'
    PAYLOAD_BUDGET = 'SCALAR_EXACT_LITERAL_PAYLOAD_BUDGET'
    NUMBER_TAG = 'NUMBER_FORMAL_PROVIDER_TAG_UNSUPPORTED'


@dataclass(frozen=True, slots=True)
class ScalarDecode:
    """Local decode result, not an IR record or an evidence capability.

    builtin_type names the normalized PythonLiteral representation, never the
    class of an original Python object before provider conversion.
    """

    literal: PythonLiteral | None
    builtin_type: str | None
    frontier: ScalarFrontier | None

    def __post_init__(self):
        if self.literal is None:
            if self.builtin_type is not None or type(self.frontier) is not ScalarFrontier:
                raise ValueError('unconverted scalar requires exactly one concrete frontier')
        else:
            if type(self.literal) is not PythonLiteral or self.frontier is not None:
                raise TypeError('decoded scalar requires an original exact PythonLiteral')
            require_exact_literal(self.literal)
            expected = {'none': 'builtins.NoneType', 'bool': 'builtins.bool',
                'int': 'builtins.int', 'str': 'builtins.str'}.get(self.literal.kind.value)
            if self.builtin_type != expected or expected is None:
                raise ValueError('decoded scalar builtin type differs from its literal kind')


_PRIMITIVE_KINDS = {'NoneType', 'OptionalType', 'BoolType', 'IntType', 'FloatType', 'StringType'}
_SYMBOLIC_KINDS = {'SymIntType', 'SymBoolType', 'SymFloatType'}
_SCALAR_KINDS = {'None': {'NoneType', 'OptionalType'}, 'Bool': {'BoolType'},
    'Int': {'IntType'}, 'Double': {'FloatType'}, 'String': {'StringType'}}
_BUILTIN_TYPES = {type(None): 'builtins.NoneType', bool: 'builtins.bool',
    int: 'builtins.int', str: 'builtins.str'}


def _gap(frontier):
    return ScalarDecode(None, None, frontier)


def decode_pinned_scalar(provider_revision: str, provider_type: str,
                         formal_kind: str, value: object, *,
                         formal_real_kind: str,
                         profile: str = SCALAR_CONTENT_PROFILE_V1) -> ScalarDecode:
    """Decode one already selected leaf without coercing type or ownership.

    ``formal_kind`` and ``formal_real_kind`` are the exact leaf ``kind()`` values
    from the pinned schema's type and real_type. The latter is required: SymInt
    may print as int and expose IntType through type while retaining SymIntType
    through real_type. For a None leaf keep the original OptionalType rather
    than pretending its absent value is the optional element's builtin type.

    A supported result is abstract builtin content under this provider contract,
    not evidence of a Python object's class, identity, origin or constancy.
    The explicit V2 profile additionally interprets actual Int/Bool IValues at
    a NumberType formal. Earlier enum/symbolic conversions remain unknown.
    """
    if type(profile) is not str or profile not in (SCALAR_CONTENT_PROFILE_V1, SCALAR_CONTENT_PROFILE_V2):
        raise ValueError('unsupported scalar content profile')
    for name, item, maximum in (('provider_revision', provider_revision, 128),
            ('provider_type', provider_type, 4096), ('formal_kind', formal_kind, 128),
            ('formal_real_kind', formal_real_kind, 128)):
        if type(item) is not str or not item or len(item) > maximum:
            raise ValueError(name + ' requires a bounded exact nonempty string')
    if (provider_revision != PINNED_SCALAR_PROVIDER_REVISION
            or PROVIDER_REVISION != PINNED_SCALAR_PROVIDER_REVISION):
        return _gap(ScalarFrontier.PROVIDER_REVISION)
    if provider_type == 'Tensor' or provider_type.startswith('Tensor('):
        return _gap(ScalarFrontier.TENSOR_REFERENCE)
    if provider_type.startswith(('Tuple[', 'List[', 'GenericList', 'GenericDict', 'Dict[')):
        return _gap(ScalarFrontier.CONTAINER)
    if provider_type in ('SymInt', 'SymFloat', 'SymBool') or (
            formal_kind in _SYMBOLIC_KINDS or formal_real_kind in _SYMBOLIC_KINDS):
        return _gap(ScalarFrontier.SYMBOLIC)
    number = (profile == SCALAR_CONTENT_PROFILE_V2
              and formal_kind == formal_real_kind == 'NumberType')
    if number:
        # The original formal remains NumberType. Never replace it with a
        # guessed primitive formal or infer a pre-conversion Python type.
        if provider_type not in ('Int', 'Bool'):
            return _gap(ScalarFrontier.NUMBER_TAG)
    else:
        if formal_kind not in _PRIMITIVE_KINDS or formal_real_kind not in _PRIMITIVE_KINDS:
            return _gap(ScalarFrontier.NON_BUILTIN_FORMAL)
        kinds = _SCALAR_KINDS.get(provider_type)
        if kinds is None:
            return _gap(ScalarFrontier.PROVIDER_TAG)
        if formal_kind != formal_real_kind or formal_kind not in kinds:
            return _gap(ScalarFrontier.FORMAL_KIND)
    if provider_type == 'None':
        # The pinned getScalarValue fallback serializes this exact tag sentinel.
        if type(value) is not str or value != '<None>':
            return _gap(ScalarFrontier.NONE_SENTINEL)
        decoded = None
    elif provider_type == 'Bool':
        if type(value) is not bool:
            return _gap(ScalarFrontier.PAYLOAD_TYPE)
        decoded = value
    elif provider_type == 'Int':
        if type(value) is not int:
            return _gap(ScalarFrontier.PAYLOAD_TYPE)
        if not -(2**63) <= value < 2**63:
            return _gap(ScalarFrontier.INT64_RANGE)
        decoded = value
    elif provider_type == 'Double':
        if type(value) is str:
            return _gap(ScalarFrontier.DOUBLE_STRINGIFIED)
        if type(value) is not float:
            return _gap(ScalarFrontier.PAYLOAD_TYPE)
        if not math.isfinite(value):
            return _gap(ScalarFrontier.NONFINITE)
        # Decimal std::to_string is not a lossless binary64 payload contract.
        return _gap(ScalarFrontier.DOUBLE_PRECISION)
    else:
        if type(value) is not str:
            return _gap(ScalarFrontier.PAYLOAD_TYPE)
        # ASCII needs no assumptions about provider char signedness, arbitrary
        # string bytes or Unicode normalization. Non-ASCII stays a frontier.
        from scar.ir.literals import MAX_LITERAL_PAYLOAD_BYTES
        if len(value) > MAX_LITERAL_PAYLOAD_BYTES:
            return _gap(ScalarFrontier.PAYLOAD_BUDGET)
        if not value.isascii():
            return _gap(ScalarFrontier.STRING_ENCODING)
        decoded = value
    literal = PythonLiteral.from_python(decoded, exact=True)
    return ScalarDecode(literal, _BUILTIN_TYPES[type(decoded)], None)


__all__ = ['ScalarDecode', 'ScalarFrontier', 'decode_pinned_scalar', 'PINNED_SCALAR_PROVIDER_REVISION',
           'SCALAR_CONTENT_PROFILE_V1', 'SCALAR_CONTENT_PROFILE_V2']
