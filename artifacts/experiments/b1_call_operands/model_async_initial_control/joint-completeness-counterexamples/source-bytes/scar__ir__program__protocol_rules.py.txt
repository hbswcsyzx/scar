"""Closed first-version protocol profile and contract applicability tables.

The tables are immutable declarations. They describe which typed row shapes
can appear under a profile; graph validation still checks exact core ownership,
source inventory, control routes and state ports. A permitted rule is not proof
that a provider or runtime implements it.
"""
from __future__ import annotations

from types import MappingProxyType

from scar.ir.program.drivers import DriverReceiverKind
from scar.ir.program.protocols import (
    AdmissionPredicate, BodyStateCondition, DriverSubject, NoEntryOutcome, OperationSiteSubject, OutcomeAdapter,
    OutcomeAdapterRule, PacketConstruction, PacketRule, ProtocolCall,
    ProtocolCallRule, ProtocolClause, ProtocolProfile, RequestProcessing,
    RequestProcessingRule, ReferenceIsNoneCondition,
)
from scar.ir.program.resumption import ResumableKind
from .protocol_connections import (RequestAssociation, RequestStateCondition,
                                    ResumeSourceBinding, SessionOccupancyCondition)
from .protocol_await_records import (
    AwaitAcquisition, AwaitIteratorQualification, CoroutineAwaitWrapper,
)


PROFILE_CLAUSES = MappingProxyType({
    ProtocolProfile.GENERATOR_BODY_V1: (
        ProtocolClause.RAW_ADMISSION, ProtocolClause.REQUEST_PROCESSING,
        ProtocolClause.BODY_INGRESS, ProtocolClause.BODY_SUSPENSION,
        ProtocolClause.BODY_TERMINAL, ProtocolClause.HOST_ADAPTER,
        ProtocolClause.CLOSE_ROUTE,
    ),
    ProtocolProfile.COROUTINE_BODY_V1: (
        ProtocolClause.RAW_ADMISSION, ProtocolClause.REQUEST_PROCESSING,
        ProtocolClause.BODY_INGRESS, ProtocolClause.BODY_SUSPENSION,
        ProtocolClause.BODY_TERMINAL, ProtocolClause.AWAIT_COMPLETION_ADAPTER,
        ProtocolClause.CLOSE_ROUTE,
    ),
    ProtocolProfile.GENERATOR_COROUTINE_BODY_V1: (
        ProtocolClause.RAW_ADMISSION, ProtocolClause.REQUEST_PROCESSING,
        ProtocolClause.BODY_INGRESS, ProtocolClause.BODY_SUSPENSION,
        ProtocolClause.BODY_TERMINAL, ProtocolClause.DIRECT_HOST_ADAPTER,
        ProtocolClause.AWAIT_COMPLETION_ADAPTER, ProtocolClause.CLOSE_ROUTE,
    ),
    ProtocolProfile.ASYNC_GENERATOR_BODY_V1: (
        ProtocolClause.ASYNC_REQUEST_SOURCE, ProtocolClause.ASYNC_REQUEST_ASSOCIATE,
        ProtocolClause.ASYNC_REQUEST_DELIVERY, ProtocolClause.BODY_INGRESS,
        ProtocolClause.BODY_SUSPENSION, ProtocolClause.ASYNC_ITEM_ADAPTER,
        ProtocolClause.BODY_TERMINAL, ProtocolClause.CLOSE_ROUTE,
    ),
    ProtocolProfile.AWAIT_SITE_V1: (
        ProtocolClause.AWAIT_LOOKUP, ProtocolClause.AWAIT_CALL,
        ProtocolClause.AWAIT_RESULT_ADAPTER,
    ),
    ProtocolProfile.DELEGATION_SITE_V1: (
        ProtocolClause.DELEGATE_ITER_LOOKUP, ProtocolClause.DELEGATE_ADVANCE,
        ProtocolClause.DELEGATE_THROW, ProtocolClause.DELEGATE_CLOSE,
        ProtocolClause.DELEGATE_PARENT_OR_HOST_RESULT,
    ),
    ProtocolProfile.COROUTINE_AWAIT_WRAPPER_V1: (
        ProtocolClause.WRAPPER_LOOKUP, ProtocolClause.WRAPPER_CALL,
        ProtocolClause.WRAPPER_RESULT_ROUTE,
    ),
    ProtocolProfile.CREATED_THROW_V1: (
        ProtocolClause.RAW_ADMISSION, ProtocolClause.THROW_NORMALIZATION,
        ProtocolClause.PREENTRY_REJECT, ProtocolClause.INITIAL_THROW_DELIVERED,
        ProtocolClause.INITIAL_THROW_CONSTRUCTOR_FAILURE, ProtocolClause.HOST_TERMINAL,
    ),
    ProtocolProfile.CREATED_CLOSE_V1: (
        ProtocolClause.CREATED_CLOSE_BRANCH,
    ),
    ProtocolProfile.SUSPENDED_CLOSE_V1: (
        ProtocolClause.CLOSE_INJECTION, ProtocolClause.BODY_INGRESS,
        ProtocolClause.BODY_TERMINAL, ProtocolClause.CLOSE_HOST_ADAPTER,
    ),
    ProtocolProfile.TASK_CANCEL_EXTERNAL_V1: (
        ProtocolClause.TASK_CANCEL_REQUEST, ProtocolClause.CANCEL_DELIVERY,
        ProtocolClause.CANCEL_HANDLER_OR_TERMINAL, ProtocolClause.TASK_STATUS_ROUTE,
    ),
    ProtocolProfile.AWAIT_ACQUISITION_V1: (ProtocolClause.AWAIT_ACQUISITION,),
    ProtocolProfile.AWAIT_METHOD_IMPLEMENTATION_V1: (
        ProtocolClause.AWAIT_LOOKUP, ProtocolClause.AWAIT_CALL,
        ProtocolClause.AWAIT_ITERATOR_QUALIFICATION,
    ),
    ProtocolProfile.COROUTINE_WRAPPER_CONSTRUCTION_V1: (
        ProtocolClause.WRAPPER_CONSTRUCTION,
    ),
})

# Acquisition/construction can be modelled without its eventual consumer. A full await
# expression may additionally describe the original final extraction, in the
# same caller region.  Optional permission never removes consumer obligations.
PROFILE_OPTIONAL_CLAUSES = MappingProxyType({
    ProtocolProfile.AWAIT_ACQUISITION_V1: (ProtocolClause.AWAIT_RESULT_ADAPTER,),
    ProtocolProfile.COROUTINE_WRAPPER_CONSTRUCTION_V1: (ProtocolClause.AWAIT_RESULT_ADAPTER,),
})

PROFILE_FAMILY = MappingProxyType({
    ProtocolProfile.GENERATOR_BODY_V1: (ResumableKind.GENERATOR, DriverReceiverKind.BODY),
    ProtocolProfile.COROUTINE_BODY_V1: (ResumableKind.COROUTINE, DriverReceiverKind.BODY),
    ProtocolProfile.GENERATOR_COROUTINE_BODY_V1:
        (ResumableKind.GENERATOR_COROUTINE, DriverReceiverKind.BODY),
    ProtocolProfile.ASYNC_GENERATOR_BODY_V1:
        (ResumableKind.ASYNC_GENERATOR, DriverReceiverKind.ASYNC_REQUEST),
})

PROFILE_SUBJECT = MappingProxyType({
    profile: DriverSubject for profile in PROFILE_FAMILY
} | {
    profile: OperationSiteSubject for profile in ProtocolProfile if profile not in PROFILE_FAMILY
})


def _key(profile, clause, contract):
    return profile, clause, contract


_allowed: dict[tuple, frozenset] = {}


def _allow(profile, clauses, contract, rules=()):
    for clause in clauses:
        key = _key(profile, clause, contract)
        if key in _allowed:
            _allowed[key] = _allowed[key] | frozenset(rules)
        else:
            _allowed[key] = frozenset(rules)


_BODY_PROFILES = (
    ProtocolProfile.GENERATOR_BODY_V1,
    ProtocolProfile.COROUTINE_BODY_V1,
    ProtocolProfile.GENERATOR_COROUTINE_BODY_V1,
)
_ASYNC_PROFILE = ProtocolProfile.ASYNC_GENERATOR_BODY_V1
_CREATED_THROW = ProtocolProfile.CREATED_THROW_V1
_SUSPENDED_CLOSE = ProtocolProfile.SUSPENDED_CLOSE_V1
_DRIVER_RULES = {
    RequestProcessingRule.CHECK_NEXT, RequestProcessingRule.CHECK_SEND,
    RequestProcessingRule.CHECK_THROW, RequestProcessingRule.CHECK_CLOSE,
}
_DRIVER_NORMALIZERS = {
    RequestProcessingRule.NORMALIZE_THROW_INSTANCE,
    RequestProcessingRule.NORMALIZE_THROW_CLASS,
    RequestProcessingRule.NORMALIZE_GENERATOR_EXIT,
}

for profile in _BODY_PROFILES:
    _allow(profile, (ProtocolClause.RAW_ADMISSION,), RequestProcessing, _DRIVER_RULES)
    _allow(profile, (ProtocolClause.REQUEST_PROCESSING,), RequestProcessing,
           _DRIVER_RULES | _DRIVER_NORMALIZERS)
_allow(_ASYNC_PROFILE, (ProtocolClause.ASYNC_REQUEST_SOURCE,), RequestProcessing,
       {RequestProcessingRule.CHECK_ASYNC_REQUEST})
_allow(_ASYNC_PROFILE, (ProtocolClause.ASYNC_REQUEST_DELIVERY,), RequestProcessing,
       {RequestProcessingRule.CHECK_ASYNC_REQUEST, RequestProcessingRule.CHECK_INITIAL_ASEND,
        RequestProcessingRule.NORMALIZE_ASYNC_THROW, RequestProcessingRule.NORMALIZE_GENERATOR_EXIT})
_allow(_CREATED_THROW, (ProtocolClause.RAW_ADMISSION,), RequestProcessing,
       {RequestProcessingRule.CHECK_THROW})
_allow(_CREATED_THROW, (ProtocolClause.THROW_NORMALIZATION,), RequestProcessing,
       _DRIVER_NORMALIZERS | {RequestProcessingRule.NORMALIZE_ASYNC_THROW})
_allow(_SUSPENDED_CLOSE, (ProtocolClause.CLOSE_INJECTION,), RequestProcessing,
       {RequestProcessingRule.NORMALIZE_GENERATOR_EXIT,
        RequestProcessingRule.NORMALIZE_ASYNC_THROW})

_AWAIT_CALLS = {ProtocolCallRule.AWAIT_LOOKUP, ProtocolCallRule.AWAIT_CALL}
_DELEGATE_CALLS = {
    ProtocolCallRule.DELEGATE_ITER, ProtocolCallRule.DELEGATE_NEXT,
    ProtocolCallRule.DELEGATE_SEND, ProtocolCallRule.DELEGATE_THROW,
    ProtocolCallRule.DELEGATE_CLOSE,
}
_allow(ProtocolProfile.AWAIT_SITE_V1, (ProtocolClause.AWAIT_LOOKUP,), ProtocolCall,
       {ProtocolCallRule.AWAIT_LOOKUP})
_allow(ProtocolProfile.AWAIT_SITE_V1, (ProtocolClause.AWAIT_CALL,), ProtocolCall,
       {ProtocolCallRule.AWAIT_CALL})
_allow(ProtocolProfile.COROUTINE_AWAIT_WRAPPER_V1, (ProtocolClause.WRAPPER_LOOKUP,), ProtocolCall,
       {ProtocolCallRule.AWAIT_LOOKUP})
_allow(ProtocolProfile.COROUTINE_AWAIT_WRAPPER_V1, (ProtocolClause.WRAPPER_CALL,), ProtocolCall,
       {ProtocolCallRule.AWAIT_CALL})
_allow(ProtocolProfile.AWAIT_ACQUISITION_V1, (ProtocolClause.AWAIT_ACQUISITION,),
       AwaitAcquisition)
_allow(ProtocolProfile.AWAIT_METHOD_IMPLEMENTATION_V1, (ProtocolClause.AWAIT_LOOKUP,),
       ProtocolCall, {ProtocolCallRule.AWAIT_LOOKUP})
_allow(ProtocolProfile.AWAIT_METHOD_IMPLEMENTATION_V1, (ProtocolClause.AWAIT_CALL,),
       ProtocolCall, {ProtocolCallRule.AWAIT_CALL})
_allow(ProtocolProfile.AWAIT_METHOD_IMPLEMENTATION_V1,
       (ProtocolClause.AWAIT_ITERATOR_QUALIFICATION,), AwaitIteratorQualification)
_allow(ProtocolProfile.COROUTINE_WRAPPER_CONSTRUCTION_V1,
       (ProtocolClause.WRAPPER_CONSTRUCTION,), CoroutineAwaitWrapper)
_allow(ProtocolProfile.DELEGATION_SITE_V1, (ProtocolClause.DELEGATE_ITER_LOOKUP,), ProtocolCall,
       {ProtocolCallRule.DELEGATE_ITER})
_allow(ProtocolProfile.DELEGATION_SITE_V1, (ProtocolClause.DELEGATE_ADVANCE,), ProtocolCall,
       {ProtocolCallRule.DELEGATE_NEXT, ProtocolCallRule.DELEGATE_SEND,
        ProtocolCallRule.DELEGATE_NEXT_LOOKUP, ProtocolCallRule.DELEGATE_SEND_LOOKUP})
_allow(ProtocolProfile.DELEGATION_SITE_V1, (ProtocolClause.DELEGATE_THROW,), ProtocolCall,
       {ProtocolCallRule.DELEGATE_THROW, ProtocolCallRule.DELEGATE_THROW_LOOKUP})
_allow(ProtocolProfile.DELEGATION_SITE_V1, (ProtocolClause.DELEGATE_CLOSE,), ProtocolCall,
       {ProtocolCallRule.DELEGATE_CLOSE, ProtocolCallRule.DELEGATE_CLOSE_LOOKUP})
_allow(_ASYNC_PROFILE, (ProtocolClause.ASYNC_REQUEST_DELIVERY,), ProtocolCall,
       {ProtocolCallRule.ASYNC_REQUEST_AWAIT})
_allow(ProtocolProfile.TASK_CANCEL_EXTERNAL_V1, (ProtocolClause.TASK_CANCEL_REQUEST,), ProtocolCall,
       {ProtocolCallRule.TASK_CANCEL_CALL})
_allow(_CREATED_THROW, (ProtocolClause.THROW_NORMALIZATION,), ProtocolCall,
       {ProtocolCallRule.EXCEPTION_CONSTRUCTOR})
_allow(_SUSPENDED_CLOSE, (ProtocolClause.CLOSE_INJECTION,), ProtocolCall,
       {ProtocolCallRule.EXCEPTION_CONSTRUCTOR})

for profile in _BODY_PROFILES:
    _allow(profile, (ProtocolClause.REQUEST_PROCESSING,), PacketConstruction,
           {PacketRule.THROW_PACKET_FROM_NORMALIZED, PacketRule.FORWARD_EXISTING_PACKET})
    _allow(profile, (ProtocolClause.CLOSE_ROUTE,), PacketConstruction,
           {PacketRule.GENERATOR_EXIT_PACKET, PacketRule.FORWARD_EXISTING_PACKET})
_allow(_ASYNC_PROFILE, (ProtocolClause.ASYNC_REQUEST_DELIVERY,), PacketConstruction,
       {PacketRule.THROW_PACKET_FROM_NORMALIZED, PacketRule.FORWARD_EXISTING_PACKET})
_allow(_CREATED_THROW, (ProtocolClause.THROW_NORMALIZATION,), PacketConstruction,
       {PacketRule.THROW_PACKET_FROM_NORMALIZED, PacketRule.FORWARD_EXISTING_PACKET})
_allow(_SUSPENDED_CLOSE, (ProtocolClause.CLOSE_INJECTION,), PacketConstruction,
       {PacketRule.GENERATOR_EXIT_PACKET, PacketRule.FORWARD_EXISTING_PACKET})
_allow(ProtocolProfile.TASK_CANCEL_EXTERNAL_V1, (ProtocolClause.CANCEL_DELIVERY,), PacketConstruction,
       {PacketRule.CANCEL_PACKET_FROM_DELIVERY, PacketRule.FORWARD_EXISTING_PACKET})

_allow(ProtocolProfile.GENERATOR_BODY_V1, (ProtocolClause.HOST_ADAPTER,), OutcomeAdapter,
       {OutcomeAdapterRule.GENERATOR_RETURN_TO_STOP_ITERATION,
        OutcomeAdapterRule.GENERATOR_ESCAPE_STOPITER_TO_RUNTIME_ERROR})
_allow(ProtocolProfile.COROUTINE_BODY_V1, (ProtocolClause.AWAIT_COMPLETION_ADAPTER,), OutcomeAdapter,
       {OutcomeAdapterRule.COROUTINE_RETURN_TO_STOP_ITERATION,
        OutcomeAdapterRule.AWAIT_STOPITER_TO_EXPRESSION})
_allow(ProtocolProfile.GENERATOR_COROUTINE_BODY_V1,
       (ProtocolClause.DIRECT_HOST_ADAPTER,), OutcomeAdapter,
       {OutcomeAdapterRule.GENERATOR_RETURN_TO_STOP_ITERATION,
        OutcomeAdapterRule.GENERATOR_ESCAPE_STOPITER_TO_RUNTIME_ERROR})
_allow(ProtocolProfile.GENERATOR_COROUTINE_BODY_V1,
       (ProtocolClause.AWAIT_COMPLETION_ADAPTER,), OutcomeAdapter,
       {OutcomeAdapterRule.COROUTINE_RETURN_TO_STOP_ITERATION,
        OutcomeAdapterRule.AWAIT_STOPITER_TO_EXPRESSION})
_allow(_ASYNC_PROFILE, (ProtocolClause.ASYNC_ITEM_ADAPTER,), OutcomeAdapter,
       {OutcomeAdapterRule.ASYNCGEN_YIELD_TO_REQUEST_ITEM,
        OutcomeAdapterRule.ASYNCGEN_RETURN_TO_STOP_ASYNC_ITERATION})
_allow(ProtocolProfile.AWAIT_SITE_V1, (ProtocolClause.AWAIT_RESULT_ADAPTER,), OutcomeAdapter,
       {OutcomeAdapterRule.AWAIT_STOPITER_TO_EXPRESSION})
_allow(ProtocolProfile.AWAIT_ACQUISITION_V1,
       (ProtocolClause.AWAIT_RESULT_ADAPTER,), OutcomeAdapter,
       {OutcomeAdapterRule.AWAIT_STOPITER_TO_EXPRESSION})
_allow(ProtocolProfile.COROUTINE_WRAPPER_CONSTRUCTION_V1,
       (ProtocolClause.AWAIT_RESULT_ADAPTER,), OutcomeAdapter,
       {OutcomeAdapterRule.AWAIT_STOPITER_TO_EXPRESSION})
_allow(ProtocolProfile.COROUTINE_AWAIT_WRAPPER_V1,
       (ProtocolClause.WRAPPER_RESULT_ROUTE,), OutcomeAdapter,
       {OutcomeAdapterRule.AWAIT_STOPITER_TO_EXPRESSION})
_allow(ProtocolProfile.DELEGATION_SITE_V1,
       (ProtocolClause.DELEGATE_PARENT_OR_HOST_RESULT,), OutcomeAdapter,
       {OutcomeAdapterRule.DELEGATE_ITEM_TO_PARENT_YIELD,
        OutcomeAdapterRule.DELEGATE_STOPITER_TO_PARENT_VALUE,
        OutcomeAdapterRule.DELEGATE_ONLY_HOST_ITEM,
        OutcomeAdapterRule.DELEGATE_ONLY_HOST_EXCEPTION})
_allow(_SUSPENDED_CLOSE, (ProtocolClause.CLOSE_HOST_ADAPTER,), OutcomeAdapter,
       {OutcomeAdapterRule.CLOSE_RETURN_VALUE,
        OutcomeAdapterRule.CLOSE_IGNORED_EXIT_TO_RUNTIME_ERROR,
        OutcomeAdapterRule.ASYNCGEN_CLOSE_YIELD_ERROR})
for profile in _BODY_PROFILES:
    _allow(profile, (ProtocolClause.CLOSE_ROUTE,), OutcomeAdapter,
           {OutcomeAdapterRule.CLOSE_RETURN_VALUE,
            OutcomeAdapterRule.CLOSE_IGNORED_EXIT_TO_RUNTIME_ERROR})
_allow(_ASYNC_PROFILE, (ProtocolClause.CLOSE_ROUTE,), OutcomeAdapter,
       {OutcomeAdapterRule.CLOSE_RETURN_VALUE,
        OutcomeAdapterRule.CLOSE_IGNORED_EXIT_TO_RUNTIME_ERROR,
        OutcomeAdapterRule.ASYNCGEN_CLOSE_YIELD_ERROR})
_allow(_CREATED_THROW,
       (ProtocolClause.PREENTRY_REJECT, ProtocolClause.INITIAL_THROW_DELIVERED,
        ProtocolClause.INITIAL_THROW_CONSTRUCTOR_FAILURE), NoEntryOutcome)
_allow(ProtocolProfile.GENERATOR_BODY_V1, (ProtocolClause.RAW_ADMISSION,), AdmissionPredicate)
for profile in _BODY_PROFILES[1:]:
    _allow(profile, (ProtocolClause.RAW_ADMISSION,), AdmissionPredicate)
for profile in (*_BODY_PROFILES, _ASYNC_PROFILE, _SUSPENDED_CLOSE):
    _allow(profile, (ProtocolClause.BODY_INGRESS,), ResumeSourceBinding)
_allow(_ASYNC_PROFILE, (ProtocolClause.ASYNC_REQUEST_ASSOCIATE,), RequestAssociation)
_allow(_ASYNC_PROFILE, (ProtocolClause.ASYNC_REQUEST_SOURCE,
                       ProtocolClause.ASYNC_REQUEST_DELIVERY), AdmissionPredicate)

ALLOWED_RULES = MappingProxyType(_allowed)
del _allow
del _allowed


def required_clauses(profile: ProtocolProfile) -> tuple[ProtocolClause, ...]:
    if type(profile) is not ProtocolProfile:
        raise TypeError("profile must be exact ProtocolProfile")
    return PROFILE_CLAUSES[profile]


def profile_subject(profile: ProtocolProfile) -> type:
    if type(profile) is not ProtocolProfile:
        raise TypeError("profile must be exact ProtocolProfile")
    return PROFILE_SUBJECT[profile]


def contract_allowed(profile: ProtocolProfile, clause: ProtocolClause, contract: object) -> bool:
    """Return whether this exact contract/rule shape is fixed for this profile."""
    if type(profile) is not ProtocolProfile or type(clause) is not ProtocolClause:
        return False
    if (clause not in PROFILE_CLAUSES[profile]
            and clause not in PROFILE_OPTIONAL_CLAUSES.get(profile, ())):
        return False
    contract_type = type(contract)
    rules = ALLOWED_RULES.get(_key(profile, clause, contract_type))
    if rules is None:
        return False
    if contract_type is AdmissionPredicate:
        if profile is _ASYNC_PROFILE:
            return type(contract.subject) in (
                RequestStateCondition, SessionOccupancyCondition,
                BodyStateCondition, ReferenceIsNoneCondition)
        return ((type(contract.subject) in (RequestStateCondition, SessionOccupancyCondition)) ==
                (profile is _ASYNC_PROFILE))
    if contract_type in (NoEntryOutcome, ResumeSourceBinding, RequestAssociation,
                         AwaitAcquisition, AwaitIteratorQualification, CoroutineAwaitWrapper):
        return True
    return getattr(contract, "rule", None) in rules


__all__ = [
    "ALLOWED_RULES", "PROFILE_CLAUSES", "PROFILE_OPTIONAL_CLAUSES", "PROFILE_FAMILY", "PROFILE_SUBJECT",
    "contract_allowed", "profile_subject", "required_clauses",
]
