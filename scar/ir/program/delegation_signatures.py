"""Source delegation boundaries using the existing finite signature algebra.

SEND's bool discriminates PYGEN_RETURN (true) from PYGEN_NEXT (false); the
reference is respectively the final value or the next exported item. Error
remains a separate completion. These declarations neither run a delegate nor
prove frame/driver acquisition, native implementations or callback effects.
"""
from .model import ExitKind, ValueKind, ValueType
from .protocol_signatures import ExceptionABI
from .signature_patterns import (Choice, Concat, Fixed, Parameter, ParameterKind,
    PatternCase, Signature, SignatureCompletion, SignatureForm, TypeKind,
    TypeParameter, instantiate_signature)
from .source_productions import DelegationProtocolKind as K


REF = ValueType(ValueKind.REFERENCE)
BOOL = ValueType(ValueKind.DATA, 'builtins.bool')
WORLD = TypeParameter('world')
_STATE = Parameter('world', ParameterKind.TYPE, allowed_kinds=(TypeKind.STATE,))
_ABI = Parameter('exception_abi', ParameterKind.CHOICE, choices=tuple(a.value for a in ExceptionABI))


def delegation_signature_catalog():
    rows = {}
    raised = Choice('exception_abi', tuple(PatternCase(abi.value, Concat((
        Fixed((REF,) * (1 if abi is ExceptionABI.EXCEPTION_WORLD else 2)), WORLD))) for abi in ExceptionABI))
    for kind in K:
        if kind in (K.STOP_ITERATION_VALUE, K.MATCH_STOP_ASYNC_ITERATION):
            rows[kind] = Signature(SignatureForm.ORDINARY, (_STATE,),
                Concat((Fixed((REF,)), WORLD)), results=Fixed((
                    BOOL if kind is K.MATCH_STOP_ASYNC_ITERATION else REF,)))
        else:
            send = kind is K.SEND
            rows[kind] = Signature(SignatureForm.INVOKE, (_STATE, _ABI),
                Concat((Fixed((REF,) * (2 if send else 1)), WORLD)), completions=(
                    SignatureCompletion(ExitKind.NORMAL, Concat((Fixed((BOOL, REF) if send else (REF,)), WORLD))),
                    SignatureCompletion(ExitKind.RAISE, raised)))
    return rows


def resolve_delegation_signature(kind, bindings, *, max_nodes=10_000, max_ports=100_000):
    if type(kind) is not K or not any(kind is member for member in K):
        raise ValueError('expected an exact delegation protocol kind')
    return instantiate_signature(delegation_signature_catalog()[kind], bindings,
        max_nodes=max_nodes, max_ports=max_ports)
