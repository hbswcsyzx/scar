"""Independent recipe specimens, not proof of Python constructor lowering."""
from copy import deepcopy
from dataclasses import replace

import pytest

from scar.analysis import source_productions as A
from scar.ir.program import source_productions as P
from scar.ir.program.control import LanguageCompletionKind as C
from scar.ir.program.model import ValueKind, ValueType
from scar.ir.program.source_contexts import ContextState, OwnerRef


INT = ValueType(ValueKind.DATA, 'builtins.int')
BOOL = ValueType(ValueKind.DATA, 'builtins.bool')
REF = ValueType(ValueKind.REFERENCE)
SOURCE = P.ProductionOccurrence(0)
CONTEXT = ContextState(OwnerRef(0, 'ROOT'), 0, 0, 0)
BASIS = P.ProductionInput('/source/test.py', '/source', *('a' * 64 for _ in range(5)))


def normal(*types):
    return (P.ProductionCompletion(C.FALLTHROUGH, types),)


def region(name, *, parent=None, kind=P.ProductionRegionKind.EXECUTION, parameters=(INT,), outputs=None, steps=()):
    return P.ProductionRegion(P.ProductionRegionID(name), parent, kind, SOURCE, CONTEXT,
        parameters, normal(INT) if outputs is None else outputs, tuple(P.ProductionStepID(s) for s in steps))


def step(name, owner, instruction, args=(), outputs=None):
    return P.ProductionStep(P.ProductionStepID(name), owner.id, SOURCE, instruction,
        args, normal(INT) if outputs is None else outputs)


def parameter(owner, index=0):
    return P.ProductionParameter(owner.id, index)


def plan(regions, steps):
    return P.SourceProductionPlan(BASIS, SOURCE, P.ProductionPurpose.VALUE,
        regions[0].id, tuple(regions), tuple(steps), ())


def identity():
    root = region('root', steps=('return',))
    return plan((root,), (step('return', root, P.TransferCompletion(C.FALLTHROUGH), (parameter(root),)),))


def request_specimen(root,source,scope,captures,default,world,abi):
    environment=P.EvaluationRequestEnvironment(source,scope,0,captures,default,world,abi)
    body=region('request',parent=root.id,kind=P.ProductionRegionKind.DEFERRED,
        parameters=(REF,REF,world),outputs=(P.ProductionCompletion(C.RETURN,(REF,world)),),steps=('admit','return-request'))
    admit=step('admit',body,P.EnterEvaluationRequest(environment),tuple(parameter(body,i) for i in range(3)),normal(world))
    returned=step('return-request',body,P.TransferCompletion(C.RETURN),
        (parameter(body,1),P.ProductionResult(admit.id,0)),(P.ProductionCompletion(C.RETURN,(REF,world)),))
    return body,(admit,returned)


def test_closed_grammar_exact_records_strict_codec_and_budgets():
    value = identity()
    summary = A.validate_production_plan(value)
    assert summary['steps'] == summary['regions'] == 1
    assert summary['source_rules_replayed'] is False
    assert summary['control_semantics_checked'] is False
    assert A.read_production_plan(A.production_plan_document(value)) == value
    catalog = A.production_type_catalog()
    assert catalog['counts'] == dict(records=104, fields=272, identifiers=4, enums=26, enum_members=240, unions=21)
    assert set(catalog['instruction_variants']) == {
        'EvaluateChild', 'ApplyLanguageAction', 'ReadCompilationOption', 'ApplyInplaceOperator', 'PublishAnnotation',
        'ImportRequest', 'ImportMember', 'ImportStar',
        'BuildFunctionAnnotations', 'BuildFunction', 'ApplyDecorator', 'TranslateEscapingException',
        'EnterTypeParameters', 'InvokeTypeParameterFactory', 'BuildLazyExpression', 'CreateTypeParameter',
        'SetTypeParameterDefault', 'BindTypeParameter', 'AttachTypeParameters',
        'DeferClassBody','EnterClassBody','AccessClassName','AccessClassProtocol','ReadClassTypeParameters','BuildClassAnnotations',
        'ReadBuildClass','BuildClassBody','BuildGenericBase','BuildTypeAlias',
        'ReadContextMethod','InvokeContextMethod','ContextAwaitable','EnterHandledException',
        'RestoreHandledException','ContextExceptionArguments','PrepareReraise',
        'MatchExceptionType','DeleteExceptionBinding',
        'ReferenceIsNone','ReferenceIdentical','ApplyPatternAction','InvertCondition','SplitExceptionGroup','MergeExceptionGroup',
        'EnterRootBody','ApplyNamespaceAction','BuildScopeAnnotations','DisplayExpression',
        'EnterEvaluationRequest','ApplyImplicitComparison','ReadCommonConstant','DefineAnnotationString',
        'ApplyPythonProtocol', 'ApplyDelegationProtocol', 'AccessBinding', 'ConstructValue', 'DefineLiteral', 'ApplyRegion',
        'BranchControl', 'LoopControl', 'DeferRegion', 'ReferenceEnvironment', 'EnterDeferredBody', 'HandleCompletions',
        'TransferCompletion', 'SuspendExecution'}
    assert A.read_production_type_catalog(deepcopy(catalog)) == catalog
    # bool must not silently pass as an int, and unregistered subclasses fail.
    malformed = replace(value, source=replace(SOURCE, occurrence=True))
    with pytest.raises(A.ProductionError, match='TYPE_MISMATCH'):
        A.validate_production_plan(malformed)
    class Extended(P.ProductionOccurrence):
        pass
    with pytest.raises(A.ProductionError, match='TYPE_MISMATCH'):
        A.validate_production_plan(replace(value, source=Extended(0)))
    with pytest.raises(A.ProductionError, match='BUDGET_FRONTIER'):
        A.validate_production_plan(value, max_visits=0)
    wire = A.production_plan_document(value)
    wire['unexpected'] = True
    with pytest.raises(A.ProductionError, match='WIRE_SCHEMA'):
        A.read_production_plan(wire)
    cyclic = []
    cyclic.append(cyclic)
    with pytest.raises(A.ProductionError, match='VALUE_CYCLE'):
        A.read_production_plan(cyclic)
    with pytest.raises(A.ProductionError, match='BUDGET_FRONTIER'):
        A.read_production_plan([0] * 10_000, max_visits=4)


def test_compilation_inplace_and_annotation_interfaces_are_explicit_and_closed():
    from scar.ir.program.ids import LocationID
    from scar.ir.program.protocol_signatures import ExceptionABI
    world = ValueType(ValueKind.STATE, location=LocationID('atomic-interface-world'))
    for abi in ExceptionABI:
        raised = (REF, world) if abi is ExceptionABI.EXCEPTION_WORLD else (REF, REF, world)
        for instruction in (P.ApplyInplaceOperator(P.SlotRef(0, 'FIELD', 0), abi),
                P.PublishAnnotation(P.SlotRef(0, 'FIELD', 0), P.SlotRef(1, 'FIELD', 0),
                    P.AnnotationPublicationKind.DEFERRED, False, abi),
                P.PublishAnnotation(P.SlotRef(0, 'FIELD', 0), P.SlotRef(1, 'FIELD', 0),
                    P.AnnotationPublicationKind.DEFERRED, True, abi),
                P.PublishAnnotation(P.SlotRef(0, 'FIELD', 0), P.SlotRef(1, 'FIELD', 0),
                    P.AnnotationPublicationKind.STRINGIZED, False, abi)):
            inplace = type(instruction) is P.ApplyInplaceOperator
            parameters = (REF, REF, world) if inplace else (world,)
            result = (REF, world) if inplace else (world,)
            may_raise = inplace or instruction.publication is P.AnnotationPublicationKind.STRINGIZED or instruction.conditional_registration
            outputs = (*normal(*result), *((P.ProductionCompletion(C.RAISE, raised),) if may_raise else ()))
            root = region('root', parameters=parameters, outputs=outputs, steps=('apply', 'done'))
            apply = step('apply', root, instruction, tuple(parameter(root, i) for i in range(len(parameters))), outputs)
            done = step('done', root, P.TransferCompletion(C.FALLTHROUGH),
                tuple(P.ProductionResult(apply.id, i) for i in range(len(result))), normal(*result))
            specimen = plan((root,), (apply, done))
            A.validate_production_plan(specimen)
            assert A.read_production_plan(A.production_plan_document(specimen)) == specimen
            with pytest.raises(A.ProductionError, match='PORT_TYPES'):
                A.validate_production_plan(replace(specimen, steps=(replace(apply, arguments=()), done)))
    root = region('option', parameters=(), outputs=normal(BOOL), steps=('read',))
    read = step('read', root, P.ReadCompilationOption(P.CompilationOption.ASSERTIONS_ENABLED), (), normal(BOOL))
    A.validate_production_plan(plan((root,), (read,)))
    with pytest.raises(A.ProductionError, match='COMPILATION_OPTION'):
        A.validate_production_plan(plan((replace(root, parameters=(world,)),),
            (replace(read, arguments=(parameter(root),)),)))


def test_import_request_member_and_star_have_distinct_typed_interfaces():
    from scar.ir.program.ids import LocationID
    from scar.ir.program.protocol_signatures import ExceptionABI
    world=ValueType(ValueKind.STATE,location=LocationID('import-interface-world'))
    site=P.SlotRef(0,'FIELD',0)
    for abi in ExceptionABI:
        raised=(REF,world) if abi is ExceptionABI.EXCEPTION_WORLD else (REF,REF,world)
        for instruction in (P.ImportRequest(site,None,None,0,abi,'module',None,0),
                P.ImportRequest(site,(site,),site,0,abi,'module',('member',),1),
                P.ImportMember(site,None,abi,'member'),P.ImportMember(site,1,abi,'part'),P.ImportStar(site,0,abi)):
            request=type(instruction) is P.ImportRequest
            star=type(instruction) is P.ImportStar
            arguments=(world,) if request else (REF,world)
            result=(world,) if star else (REF,world)
            outputs=(*normal(*result),P.ProductionCompletion(C.RAISE,raised))
            root=region('import',parameters=arguments,outputs=outputs,steps=('apply','done'))
            apply=step('apply',root,instruction,tuple(parameter(root,i) for i in range(len(arguments))),outputs)
            done=step('done',root,P.TransferCompletion(C.FALLTHROUGH),
                tuple(P.ProductionResult(apply.id,i) for i in range(len(result))),normal(*result))
            specimen=plan((root,),(apply,done))
            A.validate_production_plan(specimen)
            assert A.read_production_plan(A.production_plan_document(specimen))==specimen
            with pytest.raises(A.ProductionError,match='IMPORT_INTERFACE'):
                A.validate_production_plan(replace(specimen,steps=(replace(apply,arguments=()),done)))
            if request:
                with pytest.raises(A.ProductionError,match='IMPORT_INTERFACE'):
                    A.validate_production_plan(replace(specimen,steps=(replace(apply,
                        instruction=replace(instruction,fromlist=(),level=site)),done)))
            elif not star:
                with pytest.raises(A.ProductionError,match='IMPORT_INTERFACE'):
                    A.validate_production_plan(replace(specimen,steps=(replace(apply,
                        instruction=replace(instruction,component=0)),done)))


def test_function_creation_annotations_decorators_and_escape_interfaces():
    from scar.ir.program.ids import LocationID
    from scar.ir.program.protocol_signatures import ExceptionABI
    world=ValueType(ValueKind.STATE,location=LocationID('function-interface-world'))
    site=P.SlotRef(0,'FIELD',0)
    annotation=P.FunctionAnnotationInterface(2,(7,), (P.FunctionAnnotationEntry(site,'parameter',site),),False)
    for abi in ExceptionABI:
        raised=(REF,world) if abi is ExceptionABI.EXCEPTION_WORLD else (REF,REF,world)
        env=P.DeferredEnvironment(1,0,(P.DeferredParameter(P.DeferredParameterKind.POSITIONAL_ONLY,site,0,site),),
            (3,),P.DeferredBodyKind.FUNCTION,world,abi)
        cases=[(P.BuildFunction(env,None,None),(REF,REF,REF,REF,world),(REF,world)),
            (P.BuildFunction(env,annotation,site),(REF,REF,REF,REF,REF,world),(REF,world)),
            (P.BuildFunctionAnnotations(annotation,abi,P.ProductionRegionID('request')),(REF,REF,world),(REF,world)),
            (P.ApplyDecorator(site,abi),(REF,REF,world),(REF,world)),
            *((P.TranslateEscapingException(kind,abi),raised,raised) for kind in (
                P.DeferredBodyKind.GENERATOR,P.DeferredBodyKind.COROUTINE,P.DeferredBodyKind.ASYNC_GENERATOR))]
        for instruction,arguments,result in cases:
            outputs=(*normal(*result),P.ProductionCompletion(C.RAISE,raised))
            root=region('function',parameters=arguments,outputs=outputs,steps=('apply','done'))
            apply=step('apply',root,instruction,tuple(parameter(root,i) for i in range(len(arguments))),outputs)
            done=step('done',root,P.TransferCompletion(C.FALLTHROUGH),
                tuple(P.ProductionResult(apply.id,i) for i in range(len(result))),normal(*result))
            specimen=plan((root,),(apply,done))
            if type(instruction) is P.BuildFunctionAnnotations:
                body,body_steps=request_specimen(root,site,annotation.scope,annotation.captures,None,world,abi)
                specimen=plan((root,body),(apply,done,*body_steps))
            A.validate_production_plan(specimen)
            assert A.read_production_plan(A.production_plan_document(specimen))==specimen
            with pytest.raises(A.ProductionError,match='FUNCTION_INTERFACE'):
                A.validate_production_plan(replace(specimen,steps=(replace(apply,arguments=()),*specimen.steps[1:])))
            if type(instruction) is P.TranslateEscapingException:
                with pytest.raises(A.ProductionError,match='FUNCTION_INTERFACE'):
                    A.validate_production_plan(replace(specimen,steps=(replace(apply,
                        instruction=replace(instruction,kind=P.DeferredBodyKind.FUNCTION)),done)))


def test_type_parameter_action_interfaces_and_unambiguous_wire_kinds():
    from scar.ir.program.ids import LocationID
    from scar.ir.program.protocol_signatures import ExceptionABI
    world=ValueType(ValueKind.STATE,location=LocationID('type-parameter-interface-world'))
    site=P.SlotRef(0,'FIELD',0)
    lazy=P.LazyExpressionInterface(site,2,(4,),False)
    parameter=P.TypeParameterSpec(site,P.TypeParameterKind.TYPE_VAR,0,lazy,lazy,False)
    for abi in ExceptionABI:
        raised=(REF,world) if abi is ExceptionABI.EXCEPTION_WORLD else (REF,REF,world)
        cases=[(P.BuildLazyExpression(lazy,abi,P.ProductionRegionID('request')),(REF,REF,world),(REF,world)),
            (P.CreateTypeParameter(parameter,abi),(REF,world),(REF,world)),
            (P.SetTypeParameterDefault(parameter,abi),(REF,REF,world),(world,)),
            (P.BindTypeParameter(parameter,abi),(REF,world),(world,)),
            (P.AttachTypeParameters(site,abi),(REF,REF,world),(world,))]
        for instruction,arguments,result in cases:
            outputs=(*normal(*result),P.ProductionCompletion(C.RAISE,raised))
            root=region('type-parameter',parameters=arguments,outputs=outputs,steps=('apply','done'))
            apply=step('apply',root,instruction,tuple(P.ProductionParameter(root.id,i) for i in range(len(arguments))),outputs)
            done=step('done',root,P.TransferCompletion(C.FALLTHROUGH),
                tuple(P.ProductionResult(apply.id,i) for i in range(len(result))),normal(*result))
            specimen=plan((root,),(apply,done))
            if type(instruction) is P.BuildLazyExpression:
                body,body_steps=request_specimen(root,site,lazy.scope,lazy.captures,1,world,abi)
                specimen=plan((root,body),(apply,done,*body_steps))
            A.validate_production_plan(specimen)
            wire=A.production_plan_document(specimen)
            assert wire['steps'][0]['instruction']['record_kind']==type(instruction).__name__
            assert A.read_production_plan(wire)==specimen
            with pytest.raises(A.ProductionError,match='TYPE_PARAMETER_INTERFACE'):
                A.validate_production_plan(replace(specimen,steps=(replace(apply,arguments=()),*specimen.steps[1:])))
    assert set(P.ProductionInstruction.__args__) <= set(P.PRODUCTION_RECORD_TAGS)


def test_class_and_alias_action_ports_preserve_namespace_and_exception_interfaces():
    from scar.ir.program.ids import LocationID
    from scar.ir.program.protocol_signatures import ExceptionABI
    world=ValueType(ValueKind.STATE,location=LocationID('definition-interface-world'))
    site=P.SlotRef(0,'FIELD',0)
    for abi in ExceptionABI:
        raised=(REF,world) if abi is ExceptionABI.EXCEPTION_WORLD else (REF,REF,world)
        interface=P.ClassBodyInterface(1,0,(2,),(3,),None,site,world,abi)
        alias=P.BuildTypeAlias(site,P.LazyExpressionInterface(site,2,(),False),site,abi)
        cases=[(P.ReadBuildClass(abi),(world,),(REF,world)),
            (P.BuildClassBody(interface),(REF,REF,REF,REF,world),(REF,world)),
            (P.AccessClassName(interface,'__name__',P.BindingActionKind.READ,None),(REF,REF,world),(REF,world)),
            (P.AccessClassName(interface,'__module__',P.BindingActionKind.WRITE,None),(REF,REF,REF,world),(world,)),
            (P.AccessClassProtocol(interface,3,P.ClassProtocolActionKind.WRITE_VALUE),(REF,REF,world),(world,)),
            (P.AccessClassProtocol(interface,3,P.ClassProtocolActionKind.CELL_REFERENCE),(REF,world),(REF,world)),
            (P.ReadClassTypeParameters(interface),(REF,world),(REF,world)),
            (P.BuildClassAnnotations(interface),(REF,world),(REF,world)),
            (P.BuildGenericBase(abi),(REF,world),(REF,world)),
            (alias,(REF,REF,world),(REF,world)),
            (replace(alias,type_parameters=None),(REF,world),(REF,world))]
        for instruction,arguments,result in cases:
            may_raise=not (type(instruction) is P.ReadClassTypeParameters or type(instruction) is P.AccessClassProtocol
                and instruction.action is P.ClassProtocolActionKind.CELL_REFERENCE)
            outputs=(*normal(*result),*((P.ProductionCompletion(C.RAISE,raised),) if may_raise else ()))
            root=region('definition',parameters=arguments,outputs=outputs,steps=('apply','done'))
            apply=step('apply',root,instruction,tuple(parameter(root,i) for i in range(len(arguments))),outputs)
            done=step('done',root,P.TransferCompletion(C.FALLTHROUGH),
                tuple(P.ProductionResult(apply.id,i) for i in range(len(result))),normal(*result))
            specimen=plan((root,),(apply,done))
            assert A.read_production_plan(A.production_plan_document(specimen))==specimen
            with pytest.raises(A.ProductionError,match='DEFINITION_INTERFACE|CLASS_NAMESPACE_INTERFACE'):
                A.validate_production_plan(replace(specimen,steps=(replace(apply,arguments=()),done)))


def test_context_manager_interfaces_require_method_phase_current_world_and_exception_payload():
    from scar.ir.program.ids import LocationID
    from scar.ir.program.protocol_signatures import ExceptionABI
    world=ValueType(ValueKind.STATE,location=LocationID('context-interface-world'))
    site=P.SlotRef(0,'FIELD',0)
    for abi in ExceptionABI:
        packet=(REF,world) if abi is ExceptionABI.EXCEPTION_WORLD else (REF,REF,world)
        cases=[(P.EnterHandledException(abi),packet,(REF,world),False),
            (P.RestoreHandledException(),(REF,world),(world,),False),
            (P.ContextExceptionArguments(abi),packet,(REF,REF,REF,world),False),
            (P.PrepareReraise(abi),(REF,world),packet,False)]
        for method in P.ContextMethodKind:
            cases.append((P.ReadContextMethod(site,method,abi),(REF,world),(REF,world),True))
            exit_method=method in (P.ContextMethodKind.EXIT,P.ContextMethodKind.ASYNC_EXIT)
            cases.append((P.InvokeContextMethod(site,method,abi),(*(REF for _ in range(4 if exit_method else 1)),world),(REF,world),True))
            if method in (P.ContextMethodKind.ASYNC_ENTER,P.ContextMethodKind.ASYNC_EXIT):
                cases.append((P.ContextAwaitable(site,method,abi),(REF,world),(REF,world),True))
        for instruction,arguments,result,may_raise in cases:
            outputs=(*normal(*result),*((P.ProductionCompletion(C.RAISE,packet),) if may_raise else ()))
            root=region('context',parameters=arguments,outputs=outputs,steps=('apply','done'))
            apply=step('apply',root,instruction,tuple(parameter(root,i) for i in range(len(arguments))),outputs)
            done=step('done',root,P.TransferCompletion(C.FALLTHROUGH),
                tuple(P.ProductionResult(apply.id,i) for i in range(len(result))),normal(*result))
            specimen=plan((root,),(apply,done))
            assert A.read_production_plan(A.production_plan_document(specimen))==specimen
            with pytest.raises(A.ProductionError,match='CONTEXT_INTERFACE'):
                A.validate_production_plan(replace(specimen,steps=(replace(apply,arguments=()),done)))
            if type(instruction) is P.ContextAwaitable:
                with pytest.raises(A.ProductionError,match='CONTEXT_INTERFACE'):
                    A.validate_production_plan(replace(specimen,steps=(replace(apply,instruction=replace(instruction,method=P.ContextMethodKind.ENTER)),done)))


def test_exception_match_and_generated_delete_interfaces_require_explicit_source_and_world():
    from scar.ir.program.ids import LocationID
    from scar.ir.program.protocol_signatures import ExceptionABI
    world=ValueType(ValueKind.STATE,location=LocationID('except-interface-world'))
    for abi in ExceptionABI:
        raised=(REF,world) if abi is ExceptionABI.EXCEPTION_WORLD else (REF,REF,world)
        for instruction,arguments,result in ((P.MatchExceptionType(P.SlotRef(0,'FIELD',0),abi),(REF,REF,world),(BOOL,world)),
                (P.DeleteExceptionBinding(0,abi),(world,),(world,))):
            outputs=(*normal(*result),P.ProductionCompletion(C.RAISE,raised))
            root=region('except',parameters=arguments,outputs=outputs,steps=('apply','done'))
            apply=step('apply',root,instruction,tuple(parameter(root,i) for i in range(len(arguments))),outputs)
            done=step('done',root,P.TransferCompletion(C.FALLTHROUGH),
                tuple(P.ProductionResult(apply.id,i) for i in range(len(result))),normal(*result))
            specimen=plan((root,),(apply,done))
            assert A.read_production_plan(A.production_plan_document(specimen))==specimen
            with pytest.raises(A.ProductionError,match='EXCEPT_INTERFACE'):
                A.validate_production_plan(replace(specimen,steps=(replace(apply,arguments=()),done)))


def test_exception_group_and_none_identity_interfaces_keep_data_and_state_separate():
    from scar.ir.program.ids import LocationID
    from scar.ir.program.protocol_signatures import ExceptionABI
    world=ValueType(ValueKind.STATE,location=LocationID('group-interface-world'));site=P.SlotRef(0,'FIELD',0)
    for abi in ExceptionABI:
        raised=(REF,world) if abi is ExceptionABI.EXCEPTION_WORLD else (REF,REF,world)
        cases=((P.SplitExceptionGroup(site,abi),(REF,REF,world),(REF,REF,world)),
            (P.MergeExceptionGroup(site,abi),(REF,REF,world),(REF,world)),
            (P.ReferenceIsNone(),(REF,),(BOOL,)))
        for instruction,arguments,result in cases:
            predicate=type(instruction) is P.ReferenceIsNone
            outputs=(*normal(*result),*((P.ProductionCompletion(C.RAISE,raised),) if not predicate else ()))
            root=region('group',parameters=arguments,outputs=outputs,steps=('apply','done'))
            apply=step('apply',root,instruction,tuple(parameter(root,i) for i in range(len(arguments))),outputs)
            done=step('done',root,P.TransferCompletion(C.FALLTHROUGH),tuple(P.ProductionResult(apply.id,i) for i in range(len(result))),normal(*result))
            specimen=plan((root,),(apply,done))
            assert A.read_production_plan(A.production_plan_document(specimen))==specimen
            with pytest.raises(A.ProductionError,match='IDENTITY_INTERFACE' if predicate else 'EXCEPT_INTERFACE'):
                A.validate_production_plan(replace(specimen,steps=(replace(apply,arguments=()),done)))


def test_condition_interfaces_distinguish_control_booleans_from_object_references():
    from scar.ir.program.ids import LocationID
    world=ValueType(ValueKind.STATE,location=LocationID('condition-interface-world'))
    outputs=(*normal(BOOL,world),P.ProductionCompletion(C.RAISE,(REF,world)))
    root=region('condition',parameters=(world,),outputs=outputs,steps=('condition','done'))
    apply=step('condition',root,P.EvaluateChild(P.SlotRef(0,'FIELD',0),P.ProductionPurpose.CONDITION),(parameter(root),),outputs)
    done=step('done',root,P.TransferCompletion(C.FALLTHROUGH),(P.ProductionResult(apply.id,0),P.ProductionResult(apply.id,1)),normal(BOOL,world))
    specimen=replace(plan((root,),(apply,done)),purpose=P.ProductionPurpose.CONDITION)
    assert A.read_production_plan(A.production_plan_document(specimen))==specimen
    with pytest.raises(A.ProductionError,match='CONDITION_INTERFACE'):
        A.validate_production_plan(replace(specimen,regions=(replace(root,completions=normal(REF,world)),)))
    root=region('invert',parameters=(BOOL,),outputs=normal(BOOL),steps=('invert',))
    action=step('invert',root,P.InvertCondition(),(parameter(root),),normal(BOOL))
    specimen=plan((root,),(action,))
    assert A.read_production_plan(A.production_plan_document(specimen))==specimen
    with pytest.raises(A.ProductionError,match='CONDITION_INTERFACE'):
        A.validate_production_plan(replace(specimen,steps=(replace(action,arguments=()),)))


def test_pattern_native_ports_and_failure_do_not_fabricate_capture_references():
    from scar.ir.program.ids import LocationID
    from scar.ir.program.protocol_signatures import ExceptionABI
    world=ValueType(ValueKind.STATE,location=LocationID('pattern-interface-world'))
    for abi in ExceptionABI:
        raised=(REF,world) if abi is ExceptionABI.EXCEPTION_WORLD else (REF,REF,world)
        for kind in P.PatternActionKind:
            predicate=kind in (P.PatternActionKind.SEQUENCE_TEST,P.PatternActionKind.MAPPING_TEST,P.PatternActionKind.LENGTH_TEST)
            arity=2 if kind in (P.PatternActionKind.EQUAL,P.PatternActionKind.CLASS_EXTRACT,P.PatternActionKind.KEYS_EXTRACT) else 1
            count=0 if predicate else 3 if kind in (P.PatternActionKind.SEQUENCE_UNPACK,P.PatternActionKind.TUPLE_UNPACK) else 1
            args=(*(REF for _ in range(arity)),world)
            result=(BOOL,world) if predicate else (*(REF for _ in range(count)),world)
            may_raise=kind not in (P.PatternActionKind.SEQUENCE_TEST,P.PatternActionKind.MAPPING_TEST,P.PatternActionKind.TUPLE_UNPACK)
            outputs=(*normal(*result),*((P.ProductionCompletion(C.RAISE,raised),) if may_raise else ()))
            root=region('pattern-action',parameters=args,outputs=outputs,steps=('apply',))
            apply=step('apply',root,P.ApplyPatternAction(kind,SOURCE,count,abi),tuple(parameter(root,i) for i in range(len(args))),outputs)
            specimen=plan((root,),(apply,))
            assert A.read_production_plan(A.production_plan_document(specimen))==specimen
            with pytest.raises(A.ProductionError,match='PATTERN_INTERFACE'):
                A.validate_production_plan(replace(specimen,steps=(replace(apply,arguments=apply.arguments[:-1]),)))
    failed=(P.ProductionCompletion(P.PatternCompletionKind.FAIL,(world,)),)
    root=region('failure',parameters=(world,),outputs=failed,steps=('fail',))
    specimen=plan((root,),(step('fail',root,P.TransferCompletion(P.PatternCompletionKind.FAIL),(parameter(root),),failed),))
    assert A.read_production_plan(A.production_plan_document(specimen))==specimen
    with pytest.raises(A.ProductionError,match='PATTERN_INTERFACE'):
        A.validate_production_plan(replace(specimen,regions=(replace(root,completions=(
            P.ProductionCompletion(P.PatternCompletionKind.FAIL,(REF,world)),)),)))
    root=region('identity',parameters=(REF,REF),outputs=normal(BOOL),steps=('is',))
    specimen=plan((root,),(step('is',root,P.ReferenceIdentical(),(parameter(root),parameter(root,1)),normal(BOOL)),))
    assert A.read_production_plan(A.production_plan_document(specimen))==specimen


def test_shared_template_calls_keep_explicit_ports_and_lexical_activation_boundaries():
    root=region('root',steps=('left','right'))
    left=region('left',parent=root.id,steps=('invoke-left',))
    right=region('right',parent=root.id,steps=('invoke-right',))
    shared=region('shared',parent=root.id,kind=P.ProductionRegionKind.SHARED,steps=('shared-done',))
    value=plan((root,left,right,shared),(
        step('left',root,P.ApplyRegion(P.ProductionRegionCall(left.id,(parameter(root),)))),
        step('right',root,P.ApplyRegion(P.ProductionRegionCall(right.id,(P.ProductionResult(P.ProductionStepID('left'),0),)))),
        step('invoke-left',left,P.ApplyRegion(P.ProductionRegionCall(shared.id,(parameter(left),)))),
        step('invoke-right',right,P.ApplyRegion(P.ProductionRegionCall(shared.id,(parameter(right),)))),
        step('shared-done',shared,P.TransferCompletion(C.FALLTHROUGH),(parameter(shared),))))
    assert A.read_production_plan(A.production_plan_document(value))==value
    for regions in ((root,replace(left,kind=P.ProductionRegionKind.DEFERRED),right,shared),
            (root,left,right,replace(shared,parent=right.id)),
            (root,left,right,replace(shared,context=replace(CONTEXT,environment=1)))):
        with pytest.raises(A.ProductionError,match='SHARED_REGION'):
            A.validate_production_plan(replace(value,regions=regions))


def test_ordered_values_shared_subregion_and_invalid_local_edges():
    root = region('root', steps=('first', 'second'))
    shared = region('shared', parent=root.id, steps=('shared_return',))
    first = step('first', root, P.ApplyRegion(P.ProductionRegionCall(shared.id, (parameter(root),))))
    second = step('second', root, P.ApplyRegion(P.ProductionRegionCall(shared.id, (P.ProductionResult(first.id, 0),))))
    value = plan((root, shared), (first, second,
        step('shared_return', shared, P.TransferCompletion(C.FALLTHROUGH), (parameter(shared),))))
    assert A.validate_production_plan(value)['regions'] == 2  # one shared region, two uses
    for changed in (
        replace(value, regions=(replace(root, steps=tuple(reversed(root.steps))), shared)),
        replace(value, steps=(replace(first, instruction=P.ApplyRegion(P.ProductionRegionCall(shared.id,
            (parameter(shared),)))), *value.steps[1:])),
        replace(value, steps=(replace(first, instruction=P.ApplyRegion(P.ProductionRegionCall(shared.id,
            (P.ProductionResult(second.id, 0),)))), *value.steps[1:])),
        replace(value, regions=(root, replace(shared, parent=shared.id))),
        replace(value, steps=(*value.steps, first)),
    ):
        with pytest.raises(A.ProductionError):
            A.validate_production_plan(changed)


def test_early_exception_is_preserved_when_normal_path_has_a_later_return():
    exits = (*normal(INT), P.ProductionCompletion(C.RAISE, (REF,)))
    root = region('root', steps=('invoke', 'finish'), outputs=exits)
    invoke = step('invoke', root, P.ApplyLanguageAction(P.LanguageActionKind.CALL),
        (parameter(root),), exits)
    finish = step('finish', root, P.TransferCompletion(C.FALLTHROUGH),
        (P.ProductionResult(invoke.id, 0),))
    value = plan((root,), (invoke, finish))
    assert A.validate_production_plan(value)['regions'] == 1
    with pytest.raises(A.ProductionError, match='REGION_EXIT'):
        A.validate_production_plan(replace(value, regions=(replace(root, completions=normal(INT)),)))


def test_existing_protocol_signatures_are_mandatory_for_recipe_protocol_steps():
    from scar.ir.program.ids import LocationID
    from scar.ir.program.signature_patterns import CountBinding, ChoiceBinding, TypeBinding
    from scar.ir.program.structured import PythonProtocolKind as K
    world = ValueType(ValueKind.STATE, location=LocationID('world'))
    exits = (*normal(REF, world), P.ProductionCompletion(C.RAISE, (REF, world)))
    root = region('root', parameters=(REF, REF, world), outputs=exits, steps=('pack',))
    bindings = (TypeBinding('world', world), ChoiceBinding('exception_abi', 'EXCEPTION_WORLD'),
                CountBinding('item_count', 2))
    pack = step('pack', root, P.ApplyPythonProtocol(K.BUILD_CALL_POSITIONALS, bindings),
        tuple(parameter(root, i) for i in range(3)), exits)
    value = plan((root,), (pack,))
    assert A.validate_production_plan(value)['protocol_signature_checks'] == 1
    assert A.read_production_plan(A.production_plan_document(value)) == value
    for instruction in (
        replace(pack.instruction, bindings=(*bindings[:2], CountBinding('item_count', 1))),
        replace(pack.instruction, protocol=K.OPAQUE_EXPRESSION),
        replace(pack.instruction, bindings=(bindings[0], ChoiceBinding('exception_abi', 'EXCEPTION_TRACEBACK_WORLD'), bindings[2])),
    ):
        with pytest.raises(A.ProductionError):
            A.validate_production_plan(replace(value, steps=(replace(pack, instruction=instruction),)))


def test_delegation_boundaries_have_closed_signatures_and_distinct_send_outcomes():
    from scar.ir.program.ids import LocationID
    from scar.ir.program.protocol_signatures import ExceptionABI
    from scar.ir.program.signature_patterns import ChoiceBinding, TypeBinding
    from scar.ir.program.delegation_signatures import delegation_signature_catalog
    world = ValueType(ValueKind.STATE, location=LocationID('world'))
    assert set(delegation_signature_catalog()) == set(P.DelegationProtocolKind)
    for abi in ExceptionABI:
        raised = P.ProductionCompletion(C.RAISE, (*(REF for _ in range(
            1 if abi is ExceptionABI.EXCEPTION_WORLD else 2)), world))
        for kind in P.DelegationProtocolKind:
            ordinary = kind in (P.DelegationProtocolKind.STOP_ITERATION_VALUE, P.DelegationProtocolKind.MATCH_STOP_ASYNC_ITERATION)
            args = (*(REF for _ in range(2 if kind is P.DelegationProtocolKind.SEND else 1)), world)
            result = (BOOL if kind is P.DelegationProtocolKind.MATCH_STOP_ASYNC_ITERATION else REF,) if ordinary else (
                (BOOL, REF, world) if kind is P.DelegationProtocolKind.SEND else (REF, world))
            outputs = (*normal(*result), *((raised,) if not ordinary else ()))
            root = region('root', parameters=args, outputs=outputs, steps=('delegate',))
            instruction = P.ApplyDelegationProtocol(kind, (TypeBinding('world', world),
                *((ChoiceBinding('exception_abi', abi.value),) if not ordinary else ())))
            value = plan((root,), (step('delegate', root, instruction,
                tuple(parameter(root, i) for i in range(len(args))), outputs),))
            assert A.validate_production_plan(value)['delegation_signature_checks'] == 1
            assert A.read_production_plan(A.production_plan_document(value)) == value
            with pytest.raises(A.ProductionError, match='PORT_TYPES'):
                A.validate_production_plan(replace(value, steps=(replace(value.steps[0],
                    arguments=value.steps[0].arguments[:-1]),)))


def test_implicit_literals_keep_exact_values_without_asserting_identity_or_allocation():
    from scar.ir.literals import PythonLiteral
    for literal in (None, '', (), ('nested', 7)):
        root = region('root', parameters=(), outputs=normal(REF), steps=('literal',))
        instruction = P.DefineLiteral(PythonLiteral.from_python(literal))
        value = plan((root,), (step('literal', root, instruction, outputs=normal(REF)),))
        result = A.read_production_plan(A.production_plan_document(value))
        assert result.steps[0].instruction.value.to_python() == literal


def test_iterator_loop_passes_items_to_body_without_artificial_carried_values():
    from scar.ir.program.ids import LocationID
    from scar.ir.program.signature_patterns import ChoiceBinding, TypeBinding
    from scar.ir.program.structured import PythonProtocolKind as K
    world = ValueType(ValueKind.STATE, location=LocationID('world'))
    raised = P.ProductionCompletion(C.RAISE, (REF, world))
    loop = region('loop', kind=P.ProductionRegionKind.LOOP, parameters=(REF, REF, world),
        outputs=(*normal(world), raised), steps=('drive',))
    advance = region('advance', parent=loop.id, kind=P.ProductionRegionKind.LOOP_CONDITION,
        parameters=(REF, world), outputs=(*normal(REF, world), raised), steps=('next',))
    matcher = region('matcher', parent=loop.id, kind=P.ProductionRegionKind.HANDLER,
        parameters=(REF, world), outputs=normal(BOOL), steps=('match',))
    body = region('body', parent=loop.id, kind=P.ProductionRegionKind.LOOP_BODY,
        parameters=(REF, REF, world, REF), outputs=normal(world), steps=('done',))
    condition = P.IterationCondition(P.ProductionRegionCall(advance.id,
        (parameter(loop), parameter(loop, 2))), matcher.id, 2)
    value = plan((loop, advance, matcher, body), (
        step('drive', loop, P.LoopControl(condition, body.id, invariant_count=2),
            tuple(parameter(loop, i) for i in range(3)), loop.completions),
        step('next', advance, P.ApplyPythonProtocol(K.COMPREHENSION_NEXT,
            (TypeBinding('world', world), ChoiceBinding('exception_abi', 'EXCEPTION_WORLD'))),
            (parameter(advance), parameter(advance, 1)), advance.completions),
        step('match', matcher, P.ApplyPythonProtocol(K.MATCH_STOP_ITERATION, (TypeBinding('world', world),)),
            (parameter(matcher), parameter(matcher, 1)), normal(BOOL)),
        step('done', body, P.TransferCompletion(C.FALLTHROUGH), (parameter(body, 2),), normal(world))))
    assert A.read_production_plan(A.production_plan_document(value)) == value
    for changed in (
        replace(value, regions=(*value.regions[:3], replace(body, parameters=(REF, REF, world)))),
        replace(value, steps=(replace(value.steps[0], instruction=P.LoopControl(replace(condition, world_parameter=0), body.id,
            invariant_count=2)), *value.steps[1:])),
        replace(value, steps=(replace(value.steps[0], completions=normal(world)), *value.steps[1:])),
    ):
        with pytest.raises(A.ProductionError):
            A.validate_production_plan(changed)


def test_branch_has_boolean_decision_explicit_capture_ports_and_completion_union():
    root = region('root', parameters=(BOOL, INT), steps=('branch',))
    yes = region('yes', parent=root.id, kind=P.ProductionRegionKind.ALTERNATIVE, steps=('yes_return',))
    no = region('no', parent=root.id, kind=P.ProductionRegionKind.ALTERNATIVE, steps=('no_return',))
    branch = step('branch', root, P.BranchControl(
        P.ProductionRegionCall(yes.id, (parameter(root, 1),)),
        P.ProductionRegionCall(no.id, (parameter(root, 1),))), (parameter(root),))
    value = plan((root, yes, no), (branch,
        step('yes_return', yes, P.TransferCompletion(C.FALLTHROUGH), (parameter(yes),)),
        step('no_return', no, P.TransferCompletion(C.FALLTHROUGH), (parameter(no),))))
    assert A.read_production_plan(A.production_plan_document(value)) == value
    with pytest.raises(A.ProductionError, match='PORT_TYPES'):
        A.validate_production_plan(replace(value, steps=(replace(branch, arguments=(parameter(root, 1),)), *value.steps[1:])))


def test_loop_template_carries_ports_without_iterations_or_cross_region_value_edges():
    root = region('loop', kind=P.ProductionRegionKind.LOOP, parameters=(REF, INT), steps=('drive',))
    condition = region('condition', parent=root.id, kind=P.ProductionRegionKind.LOOP_CONDITION,
        parameters=(REF, INT), outputs=normal(BOOL, INT), steps=('test', 'condition_return'))
    body = region('body', parent=root.id, parameters=(REF, INT),
        kind=P.ProductionRegionKind.LOOP_BODY, steps=('body_return',))
    test = step('test', condition, P.ApplyLanguageAction(P.LanguageActionKind.TRUTH), (parameter(condition, 1),), normal(BOOL))
    value = plan((root, condition, body), (
        step('drive', root, P.LoopControl(condition.id, body.id, invariant_count=1),
            (parameter(root), parameter(root, 1))), test,
        step('condition_return', condition, P.TransferCompletion(C.FALLTHROUGH),
            (P.ProductionResult(test.id, 0), parameter(condition, 1)), normal(BOOL, INT)),
        step('body_return', body, P.TransferCompletion(C.FALLTHROUGH), (parameter(body, 1),))))
    assert A.validate_production_plan(value)['regions'] == 3
    assert 'iteration' not in str(A.production_plan_document(value)).lower()
    with pytest.raises(A.ProductionError, match='LOOP_INTERFACE'):
        A.validate_production_plan(replace(value, regions=(root, condition, replace(body, parameters=(BOOL,)))))
    raised = P.ProductionCompletion(C.RAISE, (REF,))
    failing = step('may_raise', body, P.ApplyLanguageAction(P.LanguageActionKind.CALL),
        (parameter(body, 1),), (*normal(INT), raised))
    failures = replace(value, regions=(replace(root, completions=(*root.completions, raised)), condition,
        replace(body, steps=(failing.id, *body.steps), completions=(*body.completions, raised))),
        steps=(replace(value.steps[0], completions=(*value.steps[0].completions, raised)),
            *value.steps[1:], failing))
    assert A.validate_production_plan(failures)['regions'] == 3
    with pytest.raises(A.ProductionError, match='LOOP_INTERFACE'):
        A.validate_production_plan(replace(failures, regions=(root, *failures.regions[1:]),
            steps=(value.steps[0], *failures.steps[1:])))


def test_deferred_body_separates_code_creation_and_admitted_entry_state():
    from scar.ir.program.ids import LocationID
    from scar.ir.program.protocol_signatures import ExceptionABI
    world = ValueType(ValueKind.STATE, location=LocationID('world'))
    env = P.DeferredEnvironment(1, 0, (P.DeferredParameter(P.DeferredParameterKind.POSITIONAL_ONLY,
        P.SlotRef(2, 'FIELD', 0), 3),), (5,), P.DeferredBodyKind.FUNCTION, world, ExceptionABI.EXCEPTION_WORLD)
    outer = region('outer', parameters=(), outputs=normal(REF), steps=('defer',))
    returned = P.ProductionCompletion(C.RETURN, (REF, world))
    deferred = region('deferred', parent=outer.id, kind=P.ProductionRegionKind.DEFERRED,
        parameters=(REF, REF, world), outputs=(returned,), steps=('enter', 'later_return'))
    declaration = step('defer', outer, P.DeferRegion(deferred.id, env), outputs=normal(REF))
    enter = step('enter', deferred, P.EnterDeferredBody(env),
        tuple(parameter(deferred, i) for i in range(3)), normal(world))
    delayed = plan((outer, deferred), (declaration, enter,
        step('later_return', deferred, P.TransferCompletion(C.RETURN),
            (parameter(deferred, 1), P.ProductionResult(enter.id, 0)), (returned,))))
    assert A.read_production_plan(A.production_plan_document(delayed)) == delayed
    for changed in (
        replace(delayed, steps=(replace(declaration, arguments=(parameter(outer),)), *delayed.steps[1:])),
        replace(delayed, steps=(replace(declaration, instruction=replace(declaration.instruction,
            environment=replace(env, captures=(5, 5)))), *delayed.steps[1:])),
        replace(delayed, steps=(declaration, replace(enter, arguments=(parameter(deferred, 1),
            parameter(deferred), parameter(deferred, 2))), delayed.steps[2])),
        replace(delayed, regions=(outer, replace(deferred, parameters=(REF, world)))),
    ):
        with pytest.raises(A.ProductionError):
            A.validate_production_plan(changed)


def test_unconditional_loop_has_no_invented_predicate_or_normal_exit():
    loop = region('loop', kind=P.ProductionRegionKind.LOOP, outputs=(), steps=('drive',))
    backedge = P.ProductionCompletion(C.CONTINUE, (INT,), loop.id)
    body = region('body', parent=loop.id, kind=P.ProductionRegionKind.LOOP_BODY,
        outputs=(backedge,), steps=('continue',))
    drive = step('drive', loop, P.LoopControl(P.RepeatCondition(), body.id), (parameter(loop),), ())
    jump = step('continue', body, P.TransferCompletion(C.CONTINUE, loop.id), (parameter(body),), (backedge,))
    value = plan((loop, body), (drive, jump))
    assert A.read_production_plan(A.production_plan_document(value)) == value
    assert A.validate_production_plan(value)['steps'] == 2
    with pytest.raises(A.ProductionError, match='LOOP_INTERFACE'):
        A.validate_production_plan(replace(value, regions=(replace(loop, completions=normal(INT)), body),
            steps=(replace(drive, completions=normal(INT)), jump)))


def test_exception_payload_enters_handler_ports_instead_of_normal_value_edges():
    root = region('root', steps=('handle',))
    protected = region('protected', parent=root.id, steps=('invoke',), outputs=(
        *normal(INT), P.ProductionCompletion(C.RAISE, (REF,))))
    handler = region('handler', parent=root.id, kind=P.ProductionRegionKind.HANDLER,
        parameters=(REF, INT), steps=('recovered',))
    value = plan((root, protected, handler), (
        step('handle', root, P.HandleCompletions(P.ProductionRegionCall(protected.id, (parameter(root),)),
            (P.CompletionRoute(C.RAISE, None, handler.id, (parameter(root),)),))),
        step('invoke', protected, P.ApplyLanguageAction(P.LanguageActionKind.CALL), (parameter(protected),),
            protected.completions),
        step('recovered', handler, P.TransferCompletion(C.FALLTHROUGH), (parameter(handler, 1),))))
    assert A.read_production_plan(A.production_plan_document(value)) == value
    with pytest.raises(A.ProductionError, match='PORT_TYPES'):
        A.validate_production_plan(replace(value, regions=(root, protected, replace(handler, parameters=(INT, REF)))))
    with pytest.raises(A.ProductionError, match='VALUE_ORDER'):
        A.validate_production_plan(replace(value, steps=(*value.steps[:2], replace(value.steps[2],
            arguments=(P.ProductionResult(value.steps[1].id, 0),)))))


@pytest.mark.parametrize('traceback', (False, True))
def test_suspension_exports_state_and_receives_distinct_later_delivery_ports(traceback):
    from scar.ir.program.ids import LocationID
    from scar.ir.program.protocol_signatures import ExceptionABI
    world = ValueType(ValueKind.STATE, location=LocationID('world'))
    abi = ExceptionABI.EXCEPTION_TRACEBACK_WORLD if traceback else ExceptionABI.EXCEPTION_WORLD
    raised = (*(REF for _ in range(2 if traceback else 1)), world)
    outputs = (*normal(REF, world), P.ProductionCompletion(C.RAISE, raised))
    root = region('root', parameters=(REF, world, INT), outputs=outputs, steps=('suspend',))
    sent = region('sent', parent=root.id, kind=P.ProductionRegionKind.RESUME,
        parameters=(REF, world, INT), outputs=normal(REF, world), steps=('sent_return',))
    thrown = region('thrown', parent=root.id, kind=P.ProductionRegionKind.RESUME,
        parameters=(*raised, INT), outputs=(outputs[1],), steps=('throw',))
    suspension = P.SuspendExecution(P.SuspensionKind.YIELD, abi, (
        P.ProductionResumeRoute(C.FALLTHROUGH, sent.id), P.ProductionResumeRoute(C.RAISE, thrown.id)),
        (parameter(root, 2),))
    value = plan((root, sent, thrown), (
        step('suspend', root, suspension, (parameter(root), parameter(root, 1)), outputs),
        step('sent_return', sent, P.TransferCompletion(C.FALLTHROUGH),
            (parameter(sent), parameter(sent, 1)), normal(REF, world)),
        step('throw', thrown, P.TransferCompletion(C.RAISE),
            tuple(parameter(thrown, i) for i in range(len(raised))), (outputs[1],))))
    assert A.read_production_plan(A.production_plan_document(value)) == value
    for kind in (P.SuspensionKind.AWAIT, P.SuspensionKind.YIELD_FROM):
        delegated = replace(value, steps=(replace(value.steps[0], instruction=replace(suspension,
            suspension=kind, delegate=parameter(root))), *value.steps[1:]))
        assert A.read_production_plan(A.production_plan_document(delegated)) == delegated
    for instruction in (
        replace(suspension, suspension=P.SuspensionKind.YIELD_FROM),
        replace(suspension, delegate=parameter(root)),
        replace(suspension, saved=(parameter(root, 1),)),  # stale world is never a saved capture
        replace(suspension, routes=suspension.routes[:1]),
        replace(suspension, routes=(suspension.routes[0], suspension.routes[0])),
        replace(suspension, routes=(replace(suspension.routes[0], kind=C.RETURN), suspension.routes[1])),
    ):
        with pytest.raises(A.ProductionError, match='SUSPEND_INTERFACE'):
            A.validate_production_plan(replace(value, steps=(replace(value.steps[0], instruction=instruction), *value.steps[1:])))
    for changed in (
        replace(value, regions=(root, replace(sent, parameters=(REF, INT, world)), thrown)),
        replace(value, steps=(replace(value.steps[0], completions=normal(REF, world)), *value.steps[1:])),
        replace(value, steps=(replace(value.steps[0], arguments=(parameter(root, 1), parameter(root))), *value.steps[1:])),
    ):
        with pytest.raises(A.ProductionError, match='SUSPEND_INTERFACE'):
            A.validate_production_plan(changed)
    # The earlier handoff world cannot be captured by a later region's result.
    with pytest.raises(A.ProductionError, match='VALUE_SCOPE'):
        A.validate_production_plan(replace(value, steps=(value.steps[0], replace(value.steps[1],
            arguments=(parameter(sent), parameter(root, 1))), value.steps[2])))
    with pytest.raises(A.ProductionError, match='SCHEMA'):
        A.validate_production_plan(replace(value, schema_version=1))


def test_original_source_inputs_fields_contexts_and_binding_ports():
    # Reuse official static material factories; the target text is not run.
    from scar.analysis.source_bytes import source_bytes_document
    from scar.analysis.source_tokens import source_tokens_document
    from scar.analysis.source_syntax import source_syntax_document
    from scar.analysis.source_roles import source_roles_document
    from scar.analysis.source_contexts import source_contexts_document
    from scar.analysis.source_declarations import source_declarations_document
    from scar.analysis.source_bindings import source_bindings_document
    from scar.analysis.source_symbols import source_symbols_document
    from scar.analysis.compiler_topology import compiler_topology_document
    from scar.analysis.compiler_symbols import compiler_symbols_document
    from scar.analysis.frontend_bindings import read_frontend_bindings
    from scar.analysis.source_context_view import SourceContextView
    from scar.ir.program.source_syntax import SourceSyntaxMaterial
    from scar.ir.record_codec import decode

    f0 = source_bytes_document(b'x = 3\ny = x.attr\n', path='/source/test.py', namespace_root='/source')
    f1 = source_tokens_document(f0)
    f2 = source_syntax_document(f0, f1)
    b = source_roles_document(f0, f1, f2)
    c = source_contexts_document(f0, f1, f2, b)
    d = source_declarations_document(f0, f1, f2, b, c)
    q = source_bindings_document(f0, f1, f2, b, c, d)
    a = source_symbols_document(f0, f1, f2)
    t = compiler_topology_document(f0, f1, f2, b, c, a)
    s = compiler_symbols_document(f0, f1, f2, b, c, d, a, t)
    frontend = read_frontend_bindings(f0, f1, f2, b, c, d, q, a, t, s)
    context = SourceContextView(decode(SourceSyntaxMaterial, f2), frontend.roles, frontend.contexts)
    index = A.ProductionSourceIndex(f0, context, frontend)
    names = [i for i, n in enumerate(context.syntax.nodes)
        if n.constructor == 'Name' and context.role_view.context(i) == 'Load']
    assert len(names) == 1
    occurrence = names[0]
    site = P.SlotRef(occurrence, 'FIELD', context.role_view.fields['Name']['id'])
    port = next(i for i, p in enumerate(frontend.roles.ports) if p.site == site)
    root = replace(region('name', parameters=(), outputs=normal(REF), steps=('read',)),
        source=P.ProductionOccurrence(occurrence), context=context.entry_context(occurrence))
    read = replace(step('read', root, P.AccessBinding(P.BindingActionKind.READ, port), outputs=normal(REF)), source=root.source)
    value = replace(plan((root,), (read,)), input=index.input, source=root.source,
        slots=(P.ProductionSlotDisposition(site, P.ProductionDispositionKind.ROLE_PORT),))
    result = index.match(value)
    assert result['original_source_references_checked'] is True
    assert result['upstream_fresh_replayed'] is result['source_rules_replayed'] is False
    bad_port = next(i for i, p in enumerate(frontend.roles.ports) if p.site.occurrence != occurrence)
    for changed, code in (
        (replace(value, input=replace(index.input, f2_sha256='b' * 64)), 'INPUT_LINEAGE'),
        (replace(value, regions=(replace(root, context=replace(root.context, region=99)),)), 'SOURCE_CONTEXT'),
        (replace(value, steps=(replace(read, instruction=P.AccessBinding(P.BindingActionKind.READ, bad_port)),)), 'SOURCE_PORT'),
        (replace(value, slots=(P.ProductionSlotDisposition(replace(site, ordinal=999),
            P.ProductionDispositionKind.METADATA),)), 'SOURCE_REFERENCE'),
    ):
        with pytest.raises(A.ProductionError, match=code):
            index.match(changed)
    # Attribute labels are original role ports, but are not namespace reads.
    label_port = next(i for i, p in enumerate(frontend.roles.ports)
        if context.syntax.nodes[p.site.occurrence].constructor == 'Attribute')
    label = frontend.roles.ports[label_port].site
    attribute_root = replace(root, source=label, context=context.context_at_slot(label).state)
    attribute_step = replace(read, source=label, instruction=P.AccessBinding(P.BindingActionKind.READ, label_port))
    attribute_plan = replace(value, source=label, regions=(attribute_root,), steps=(attribute_step,), slots=())
    with pytest.raises(A.ProductionError, match='SOURCE_PORT'):
        index.match(attribute_plan)
