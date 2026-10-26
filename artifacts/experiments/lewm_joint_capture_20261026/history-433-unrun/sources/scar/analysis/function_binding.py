"""Conditional binding of explicit actuals to a source function signature.

This module does not resolve a live callable or evaluate an argument.  Every
result retains the requirements that connect the raw source signature to a
runtime function and its current default state.  In particular, INCOMPATIBLE
does not establish that executing the call raises TypeError.
"""
from __future__ import annotations

from scar.ir.program.functions import (
    ArgumentKind, BindingIssue, BindingIssueKind, BindingOrigin, CallArgument,
    CallBindingStatus, CandidateBinding, FunctionKind, FunctionSignature,
    ParameterBinding, ParameterKind,
)
from scar.ir.v2.common import SourceReference
from scar.ir.v2.ids import OperationDefinitionID


def bind_call(
    signature: FunctionSignature | None,
    *,
    call: OperationDefinitionID,
    target: OperationDefinitionID,
    source: SourceReference,
    arguments: tuple[CallArgument, ...],
) -> CandidateBinding:
    """Describe compatibility with the declared, undecorated signature.

    Argument indices identify source operands, without claiming their runtime
    evaluation order.  Default routes read function state; their source spans
    identify the declaration, never a freshly evaluated default expression.
    Variadic routes describe tuple/dict packing, including empty containers.
    Actual expansion and suspended or decorated targets remain incomplete.
    """
    if signature is not None and signature.definition != target:
        raise ValueError("binding target differs from the source signature")
    if tuple(argument.index for argument in arguments) != tuple(range(len(arguments))):
        raise ValueError("call argument indices must be contiguous and ordered")

    issues = []
    if signature is None:
        issues.append(BindingIssue(
            BindingIssueKind.NO_SIGNATURE,
            "the source candidate has no available raw function signature",
        ))
    else:
        if signature.decorators:
            issues.append(BindingIssue(
                BindingIssueKind.DECORATED_TARGET,
                "decorator application can replace the raw source function",
            ))
        if signature.kind is not FunctionKind.SYNC:
            issues.append(BindingIssue(
                BindingIssueKind.SUSPENDED_BODY,
                "async and generator creation/resumption have no binding rule here",
            ))
    for argument in arguments:
        if argument.kind in (ArgumentKind.STARRED, ArgumentKind.DOUBLE_STARRED):
            issues.append(BindingIssue(
                BindingIssueKind.EXPANDED_ARGUMENT,
                "starred actual expansion and its effects have not been established",
                argument_indices=(argument.index,),
            ))
    if issues:
        return CandidateBinding(
            call, target, source, CallBindingStatus.INCOMPLETE, arguments,
            issues=tuple(issues),
        )

    # A signature is available after the incomplete-interface checks above.
    assert signature is not None
    positional = tuple(parameter for parameter in signature.parameters
                       if parameter.kind in (ParameterKind.POSITIONAL_ONLY,
                                             ParameterKind.POSITIONAL))
    keyword_parameters = {parameter.name: parameter for parameter in signature.parameters
                          if parameter.kind in (ParameterKind.POSITIONAL,
                                                ParameterKind.KEYWORD_ONLY)}
    positional_only = {parameter.name: parameter for parameter in positional
                       if parameter.kind is ParameterKind.POSITIONAL_ONLY}
    var_positional = next((parameter for parameter in signature.parameters
                           if parameter.kind is ParameterKind.VAR_POSITIONAL), None)
    var_keyword = next((parameter for parameter in signature.parameters
                        if parameter.kind is ParameterKind.VAR_KEYWORD), None)
    actual_positional = tuple(argument for argument in arguments
                              if argument.kind is ArgumentKind.POSITIONAL)
    routes = {}
    for parameter, argument in zip(positional, actual_positional):
        routes[parameter.slot] = ParameterBinding(
            parameter.slot, BindingOrigin.ARGUMENT, (argument.index,),
        )
    extra_positional = tuple(argument.index for argument in actual_positional[len(positional):])
    if extra_positional and var_positional is None:
        issues.append(BindingIssue(
            BindingIssueKind.TOO_MANY_POSITIONAL,
            "explicit positional operands exceed the raw source signature",
            argument_indices=extra_positional,
        ))

    keyword_indices = []
    seen_keywords = {}
    for argument in arguments:
        if argument.kind is not ArgumentKind.KEYWORD:
            continue
        name = argument.keyword
        if name in seen_keywords:
            parameter = keyword_parameters.get(name) or var_keyword or positional_only.get(name)
            issues.append(BindingIssue(
                BindingIssueKind.DUPLICATE_ARGUMENT,
                "the same explicit keyword occurs more than once",
                parameter.slot if parameter is not None else None,
                (seen_keywords[name], argument.index),
            ))
            continue
        seen_keywords[name] = argument.index
        parameter = keyword_parameters.get(name)
        if parameter is not None:
            if parameter.slot in routes:
                issues.append(BindingIssue(
                    BindingIssueKind.DUPLICATE_ARGUMENT,
                    "a raw source parameter receives both positional and keyword operands",
                    parameter.slot,
                    routes[parameter.slot].argument_indices + (argument.index,),
                ))
            else:
                routes[parameter.slot] = ParameterBinding(
                    parameter.slot, BindingOrigin.ARGUMENT, (argument.index,),
                )
        elif var_keyword is not None:
            # A positional-only name is permitted as a distinct **kwargs key.
            keyword_indices.append(argument.index)
        elif name in positional_only:
            issues.append(BindingIssue(
                BindingIssueKind.POSITIONAL_ONLY_KEYWORD,
                "a positional-only source parameter cannot be supplied by keyword",
                positional_only[name].slot,
                (argument.index,),
            ))
        else:
            issues.append(BindingIssue(
                BindingIssueKind.UNEXPECTED_KEYWORD,
                "an explicit keyword has no route in the raw source signature",
                argument_indices=(argument.index,),
            ))

    for parameter in signature.parameters:
        if parameter.kind is ParameterKind.VAR_POSITIONAL:
            routes[parameter.slot] = ParameterBinding(
                parameter.slot, BindingOrigin.VAR_POSITIONAL_PACK, extra_positional,
            )
        elif parameter.kind is ParameterKind.VAR_KEYWORD:
            routes[parameter.slot] = ParameterBinding(
                parameter.slot, BindingOrigin.VAR_KEYWORD_PACK, tuple(keyword_indices),
            )
        elif parameter.slot not in routes:
            if parameter.default_source is not None:
                routes[parameter.slot] = ParameterBinding(
                    parameter.slot, BindingOrigin.DEFAULT_STATE,
                    default_source=parameter.default_source,
                )
            else:
                issues.append(BindingIssue(
                    BindingIssueKind.MISSING_REQUIRED,
                    "a required raw source parameter has no explicit operand or declared default",
                    parameter.slot,
                ))

    if issues:
        return CandidateBinding(
            call, target, source, CallBindingStatus.INCOMPATIBLE, arguments,
            issues=tuple(issues),
        )
    return CandidateBinding(
        call, target, source, CallBindingStatus.CONDITIONAL, arguments,
        routes=tuple(routes[parameter.slot] for parameter in signature.parameters),
    )


__all__ = ["bind_call"]
