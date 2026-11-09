"""Closed mechanical classification of the original F4 instruction types.

Labels denote source capabilities/requests only. This catalog neither reads
world inputs to infer purity nor resolves functions by names. Unknown types,
including subclasses of supported records, fail instead of becoming OPAQUE.
"""
from dataclasses import fields
from types import MappingProxyType

from scar.ir.effects import ActionLabel as L
from scar.ir.program import source_productions as P
from scar.ir.program.source_effects import EffectFamily as F, EffectResolution as R, FamilyRule


def _build():
    rules = {}

    def add(family, labels, resolution, rows):
        for cls, dispatch in rows:
            if cls in rules:
                raise AssertionError('duplicate source effect instruction: '+cls.__name__)
            declared = {field.name for field in fields(cls)}
            if len(dispatch) != len(set(dispatch)) or not set(dispatch) <= declared:
                raise AssertionError('effect dispatch field differs from source record: '+cls.__name__)
            rules[cls] = FamilyRule(cls.__name__, family, labels, resolution, dispatch)

    add(F.REGION_CONTROL, (L.CTRL, L.STATE), R.REGION_COMPOSITION, (
        (P.EvaluateChild, ('purpose',)),
        (P.ApplyRegion, ('invocation',)),
        (P.InvokeTypeParameterFactory, ('invocation', 'environment')),
        (P.BranchControl, ('on_true', 'on_false')),
        (P.LoopControl, ('condition', 'body', 'otherwise')),
        (P.HandleCompletions, ('protected', 'routes')),
        (P.TransferCompletion, ('kind', 'target')),
    ))
    add(F.SUSPENSION, (L.CTRL, L.STATE), R.DYNAMIC_TARGET_OR_PROTOCOL, (
        (P.SuspendExecution, ('suspension', 'routes', 'delegate')),
    ))
    add(F.COMPILATION_INPUT, (L.VAL, L.REP), R.COMPILE_INPUT, (
        (P.ReadCompilationOption, ('option',)),
        (P.ReadCompilationAnnotationIndex, ('parameter',)),
    ))
    add(F.IDENTITY_BOOLEAN, (L.VAL,), R.LOCAL_INTRINSIC, (
        (P.ReferenceIsNone, ()), (P.ReferenceIdentical, ()), (P.InvertCondition, ()),
    ))
    add(F.LITERAL_REPRESENTATION, (L.VAL, L.REP), R.LOCAL_INTRINSIC, (
        (P.DefineLiteral, ('value',)), (P.DefineAnnotationString, ()),
        (P.ReadCommonConstant, ('constant',)),
    ))
    add(F.BINDING_NAMESPACE, (L.STATE,), R.ADDRESS_RULE, (
        (P.AccessBinding, ('action', 'port')),
        (P.ApplyNamespaceAction, ('kind',)),
        (P.BindTypeParameter, ('parameter',)),
        (P.DeleteExceptionBinding, ('port',)),
    ))
    add(F.ENVIRONMENT_ENTRY, (L.STATE, L.CTRL), R.INSTANCE_CONDITION, (
        (P.ReferenceEnvironment, ('source',)),
        (P.EnterRootBody, ('interface',)),
        (P.EnterDeferredBody, ('environment',)),
        (P.EnterClassBody, ('interface',)),
        (P.EnterTypeParameters, ('environment',)),
        (P.EnterEvaluationRequest, ('environment',)),
    ))
    add(F.CLASS_ACCESS, (L.STATE, L.VAL), R.ADDRESS_RULE, (
        (P.AccessClassName, ('action', 'resolution', 'interface')),
        (P.AccessClassProtocol, ('action', 'binding')),
        (P.ReadClassTypeParameters, ('interface',)),
    ))
    add(F.CODE_DECLARATION, (L.REP,), R.DEFERRED_DECLARATION, (
        (P.DeferRegion, ('environment',)), (P.DeferClassBody, ('interface',)),
    ))
    add(F.CALLABLE_CONSTRUCTION, (L.REP, L.MEM, L.STATE), R.INSTANCE_CONDITION, (
        (P.BuildFunctionAnnotations, ('annotations',)),
        (P.BuildFunction, ('environment', 'annotations')),
        (P.BuildLazyExpression, ('expression',)),
        (P.BuildClassAnnotations, ('interface', 'annotations')),
        (P.BuildClassBody, ('interface',)),
        (P.BuildScopeAnnotations, ('interface', 'annotations')),
        (P.BuildTypeAlias, ('expression', 'type_parameters')),
    ))
    add(F.VALUE_TYPE_CONSTRUCTION, (L.VAL, L.REP, L.MEM, L.STATE), R.INSTANCE_CONDITION, (
        (P.ConstructValue, ('construction', 'tuple_layout')),
        (P.CreateTypeParameter, ('parameter',)),
    ))
    add(F.VALUE_TYPE_CONSTRUCTION, (L.VAL, L.REP, L.MEM, L.STATE), R.DYNAMIC_TARGET_OR_PROTOCOL, (
        (P.BuildGenericBase, ()),
    ))
    add(F.TYPE_PARAMETER_UPDATE, (L.STATE,), R.ADDRESS_RULE, (
        (P.SetTypeParameterDefault, ('parameter',)), (P.AttachTypeParameters, ()),
    ))
    add(F.ANNOTATION_STATE, (L.STATE,), R.ADDRESS_RULE, (
        (P.ReadAnnotationRegistration, ('access', 'registration')),
        (P.ReadAnnotationNamespace, ('access',)),
        (P.AddAnnotationIndex, ('publication', 'parameter')),
    ))
    add(F.PYTHON_PROTOCOL, (L.VAL, L.MEM, L.STATE, L.CTRL), R.DYNAMIC_TARGET_OR_PROTOCOL, (
        (P.ApplyLanguageAction, ('action',)),
        (P.ApplyPythonProtocol, ('protocol', 'bindings')),
        (P.ApplyInplaceOperator, ('operator',)),
        (P.ApplyDecorator, ()),
        (P.ApplyImplicitComparison, ('operator',)),
        (P.ApplyPatternAction, ('kind',)),
    ))
    add(F.SPECIAL_METHOD_PROTOCOL, (L.VAL, L.STATE, L.CTRL), R.DYNAMIC_TARGET_OR_PROTOCOL, (
        (P.ApplyDelegationProtocol, ('protocol', 'bindings')),
        (P.ReadContextMethod, ('method',)), (P.InvokeContextMethod, ('method',)),
        (P.ContextAwaitable, ('method',)),
    ))
    add(F.IMPORT_PROTOCOL, (L.REP, L.STATE, L.CTRL, L.IO), R.DYNAMIC_TARGET_OR_PROTOCOL, (
        (P.ImportRequest, ('from_names', 'relative_level')),
        (P.ImportMember, ('component',)), (P.ImportStar, ('environment',)),
    ))
    add(F.EXCEPTION_STATE, (L.STATE, L.CTRL), R.ADDRESS_RULE, (
        (P.EnterHandledException, ('exception_abi',)),
        (P.RestoreHandledException, ()),
        (P.ContextExceptionArguments, ('exception_abi',)),
        (P.PrepareReraise, ('exception_abi',)),
    ))
    add(F.EXCEPTION_PROCESSING, (L.VAL, L.REP, L.MEM, L.STATE, L.CTRL), R.DYNAMIC_TARGET_OR_PROTOCOL, (
        (P.TranslateEscapingException, ('kind',)),
        (P.MatchExceptionType, ('exception_abi',)),
        (P.SplitExceptionGroup, ('exception_abi',)),
        (P.MergeExceptionGroup, ('exception_abi',)),
    ))
    add(F.CLASS_BUILDER_LOOKUP, (L.VAL, L.STATE), R.ADDRESS_RULE, (
        (P.ReadBuildClass, ()),
    ))
    add(F.INTERACTIVE_DISPLAY, (L.IO, L.STATE, L.CTRL), R.DYNAMIC_TARGET_OR_PROTOCOL, (
        (P.DisplayExpression, ()),
    ))
    expected = P.ProductionInstruction.__args__
    if (len(expected) != len(set(expected)) or len(rules) != len(expected)
            or set(rules) != set(expected) or {rule.family for rule in rules.values()} != set(F)):
        raise AssertionError('source effect catalog does not cover the exact original instruction/family domains')
    return MappingProxyType(rules)


_RULES = _build()


def catalog():
    """Return all rules once in the original ProductionInstruction order."""
    expected = P.ProductionInstruction.__args__
    if (len(expected) != len(set(expected)) or set(expected) != set(_RULES)
            or len({rule.instruction for rule in _RULES.values()}) != len(_RULES)):
        raise AssertionError('source instruction coverage or duplicate declarations changed')
    return tuple(_RULES[cls] for cls in expected)


def classify_instruction(ins):
    """Classify only exact supported record types, without executing values."""
    try:
        return _RULES[type(ins)]
    except KeyError:
        raise TypeError('unsupported source instruction type: '+type(ins).__name__) from None
