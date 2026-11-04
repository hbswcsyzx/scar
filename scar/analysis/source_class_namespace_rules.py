"""Ordered class namespace operations; custom mappings keep their effects."""
from scar.analysis.source_expression_rules import _REF,_BOOL
from scar.analysis.source_root_interfaces import clean_docstring
from scar.ir.program import source_productions as P
from scar.ir.program.control import LanguageCompletionKind as C
from scar.ir.program.signature_patterns import CountBinding
from scar.ir.program.structured import PythonProtocolKind as K


def access(b,region,interface,name,world,environment,namespace,value=None):
    action=P.BindingActionKind.READ if value is None else P.BindingActionKind.WRITE
    instruction=b.rules.source.class_names.access(interface,name,action)
    return b.emit(region,instruction,(environment,namespace,*(() if value is None else (value,)),world),
        (_REF,b.world) if value is None else (b.world,))


def protocol(b,region,interface,binding,action,world,environment,value=None):
    return b.emit(region,P.AccessClassProtocol(interface,binding,action),
        (environment,*(() if value is None else (value,)),world),
        (_REF,b.world) if value is None else (b.world,),may_raise=action is P.ClassProtocolActionKind.WRITE_VALUE)


def _constant_store(b,region,interface,name,value,world,environment,namespace):
    reference,world=b.literal(region,value,world)
    world,=access(b,region,interface,name,world,environment,namespace,reference)
    world,=b.protocol(region,K.FRAME_RELEASE_TEMPORARY,(reference,),world)
    return world


def initialize(b,body,interface,world,environment,namespace):
    facts=b.rules.source.class_names
    value,world=access(b,body,interface,'__name__',world,environment,namespace)
    world,=access(b,body,interface,'__module__',world,environment,namespace,value)
    world,=b.protocol(body,K.FRAME_RELEASE_TEMPORARY,(value,),world)
    world=_constant_store(b,body,interface,'__qualname__',facts.qualname(interface.scope),world,environment,namespace)
    world=_constant_store(b,body,interface,'__firstlineno__',facts.first_line(interface.scope),world,environment,namespace)
    if interface.type_parameters is not None:
        value,world=b.emit(body,P.ReadClassTypeParameters(interface),(environment,world),(_REF,b.world),may_raise=False)
        world,=access(b,body,interface,'__type_params__',world,environment,namespace,value)
        world,=b.protocol(body,K.FRAME_RELEASE_TEMPORARY,(value,),world)
    dictionary=facts.protocol(interface,'__classdict__')
    if dictionary is not None:
        world,=protocol(b,body,interface,dictionary,P.ClassProtocolActionKind.WRITE_VALUE,world,environment,namespace)
    conditional=facts.protocol(interface,'__conditional_annotations__')
    if conditional is not None:
        value,world=b.protocol(body,K.BUILD_SET_DISPLAY,(),world,(CountBinding('item_count',0),))
        world,=protocol(b,body,interface,conditional,P.ClassProtocolActionKind.WRITE_VALUE,world,environment,value)
        world,=b.protocol(body,K.FRAME_RELEASE_TEMPORARY,(value,),world)
    if facts.annotations[interface.scope] and b.rules.source.roots.future:
        world,=b.emit(body,P.ApplyNamespaceAction(P.NamespaceActionKind.ENSURE_ANNOTATIONS,interface.exception_abi),
            (namespace,world),(b.world,))
    if interface.docstring is not None:
        enabled,=b.emit(body,P.ReadCompilationOption(P.CompilationOption.DOCSTRINGS_ENABLED),(),(_BOOL,),may_raise=False)
        yes=b.region(interface.docstring,(_REF,_REF,b.world),body);no=b.region(interface.docstring,(b.world,),body)
        raw=b.value(interface.docstring).scalar.to_python()
        current=_constant_store(b,yes,interface,'__doc__',clean_docstring(raw),b.parameter(yes,2),b.parameter(yes,0),b.parameter(yes,1))
        b.finish(yes,(current,),(b.world,));b.finish(no,(b.parameter(no,0),),(b.world,))
        world,=b.control(body,P.BranchControl(P.ProductionRegionCall(yes.id,(environment,namespace,world)),
            P.ProductionRegionCall(no.id,(world,))),(enabled,),b.union(b.completions(yes),b.completions(no)))
    return world


def finalize(b,region,interface,world,environment,namespace):
    facts=b.rules.source.class_names
    if facts.deferred_annotations(interface.scope):
        from scar.analysis.source_evaluation_rules import build_request_body
        request=b.rules.source.scope_annotations.interface(interface.scope)
        body=build_request_body(b,region,request);owner=P.ProductionOccurrence(facts.scopes[interface.scope].owner.occurrence)
        globals_ref,world=b.environment(region,P.GlobalsEnvironment(interface.globals_scope),world,source=owner)
        cells=[]
        for relay in request.captures:
            cell,world=b.environment(region,P.ClosureEnvironment(relay),world,source=owner);cells.append(cell)
        value,world=b.emit(region,P.BuildClassAnnotations(interface,request,body.id),(globals_ref,*cells,world),(_REF,b.world))
        world,=access(b,region,interface,'__annotate_func__',world,environment,namespace,value)
        world,=b.protocol(region,K.FRAME_RELEASE_TEMPORARY,(value,),world)
    plain,with_asserts=facts.attributes(interface.scope)
    if plain==with_asserts:
        world=_constant_store(b,region,interface,'__static_attributes__',plain,world,environment,namespace)
    else:
        enabled,=b.emit(region,P.ReadCompilationOption(P.CompilationOption.ASSERTIONS_ENABLED),(),(_BOOL,),may_raise=False)
        branches=[];regions=[]
        for values in (with_asserts,plain):
            child=b.region(region.source,(_REF,_REF,b.world),region)
            state=_constant_store(b,child,interface,'__static_attributes__',values,b.parameter(child,2),b.parameter(child,0),b.parameter(child,1))
            b.finish(child,(state,),(b.world,));regions.append(child)
            branches.append(P.ProductionRegionCall(child.id,(environment,namespace,world)))
        world,=b.control(region,P.BranchControl(*branches),(enabled,),b.union(*(b.completions(child) for child in regions)))
    dictionary=facts.protocol(interface,'__classdict__')
    if dictionary is not None:
        value,world=protocol(b,region,interface,dictionary,P.ClassProtocolActionKind.CELL_REFERENCE,world,environment)
        world,=access(b,region,interface,'__classdictcell__',world,environment,namespace,value)
        world,=b.protocol(region,K.FRAME_RELEASE_TEMPORARY,(value,),world)
    class_cell=facts.protocol(interface,'__class__')
    if class_cell is not None:
        returned,world=protocol(b,region,interface,class_cell,P.ClassProtocolActionKind.CELL_REFERENCE,world,environment)
        world,=access(b,region,interface,'__classcell__',world,environment,namespace,returned)
    else:returned,world=b.literal(region,None,world)
    b.transfer(region,C.RETURN,(returned,world),(_REF,b.world))
