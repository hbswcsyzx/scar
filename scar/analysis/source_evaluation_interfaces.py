"""Deferred request interfaces and native compiler queries over original F2.

Stringization restores only the requested subtree into a controlled synthetic
annotation wrapper and calls compile, never eval/exec. Wrapper code objects
are compiler-query output, not identities joined to target code by names/lines.
"""
import ast
import __future__
from dataclasses import replace
from types import CodeType
from scar.ir.program import source_productions as P
from scar.analysis.source_syntax import _restore_ast


def _require(condition,path,detail):
    if not condition:
        from scar.analysis.source_productions import ProductionError
        raise ProductionError('EVALUATION_REQUEST_INTERFACE',str(path),detail)


class EvaluationInterfaceIndex:
    def __init__(self,source):
        self.source=source;self._strings={}

    def environment(self,request,world,abi):
        if type(request) is P.FunctionAnnotationInterface:
            anchor=request.entries[0].value;scope=request.scope;captures=request.captures;default=None
        elif type(request) is P.ScopeAnnotationInterface:
            anchor=request.source;scope=request.scope;captures=request.captures;default=None
        else:
            _require(type(request) is P.LazyExpressionInterface,'request','expected an original function annotation or lazy expression interface')
            anchor=request.source;scope=request.scope;captures=request.captures;default=request.format_default
        return P.EvaluationRequestEnvironment(anchor,scope,self.source.context.material.root_context.environment,
            captures,default,world,abi,self.source.capture_paths.owned_cells(scope))

    def expected(self,environment):
        source=self.source;anchor=environment.source;scope=source.context.material.scopes[environment.scope]
        if scope.kind=='ANNOTATION' and scope.owner.kind=='VARIABLE_ANNOTATIONS':
            request=source.scope_annotations.request(environment.scope)
        elif scope.kind in ('TYPE_PARAMETER_EVALUATOR','TYPE_ALIAS'):
            request=source.type_parameters.lazy(anchor,allow_starred=True)
        else:
            _require(scope.kind=='ANNOTATION' and scope.owner.kind=='HEADER_ANNOTATIONS',anchor,
                'request must use an original evaluator/function-annotation scope')
            owner=scope.owner.occurrence
            # C1 owns function annotations at the FunctionDef, not at each arg.
            request=source.deferred.annotations(owner)
        _require(request is not None,anchor,'request has no original source interface')
        return self.environment(request,environment.world,environment.exception_abi)

    def stringize(self,site):
        if site in self._strings:return self._strings[site]
        source=self.source;_,selected=source.roles.locate(site)
        state=source.context.context_at_slot(site).state
        region=source.context.material.regions[state.region]
        _require(selected.kind=='NODE' and region.suppression_reason=='FUTURE_ANNOTATION_STRINGIZED',site,
            'compiler stringization needs an original future annotation expression')
        nodes=source.context.syntax.nodes;order=[];seen=set();pending=[selected.reference]
        def references(value):
            if value.kind=='NODE':return (value.reference,)
            if value.kind=='LIST':return tuple(r for item in value.items for r in references(item))
            return ()
        while pending:
            current=pending.pop()
            if current in seen:continue
            seen.add(current);order.append(current)
            pending.extend(reversed(tuple(r for value in (*nodes[current].fields,*nodes[current].attributes) for r in references(value))))
        remap={original:i for i,original in enumerate(order)}
        def value(item):
            return replace(item,reference=remap[item.reference]) if item.kind=='NODE' else (
                replace(item,items=tuple(value(v) for v in item.items)) if item.kind=='LIST' else item)
        subset=tuple(replace(nodes[o],fields=tuple(value(v) for v in nodes[o].fields),
            attributes=tuple(value(v) for v in nodes[o].attributes)) for o in order)
        expression=_restore_ast(0,subset)
        argument=ast.arg(arg='_value',annotation=expression)
        arguments=ast.arguments(posonlyargs=[],args=[],vararg=argument,kwonlyargs=[],kw_defaults=[],kwarg=None,defaults=[])
        function=ast.FunctionDef(name='_scar_annotation_query',args=arguments,body=[ast.Pass()],
            decorator_list=[],returns=None,type_comment=None,type_params=[])
        wrapper=ast.fix_missing_locations(ast.Module(body=[function],type_ignores=[]))
        code=compile(wrapper,'<scar-static-annotation-string>', 'exec',
            flags=__future__.annotations.compiler_flag,dont_inherit=True,optimize=0)
        # This wrapper has one compiler-created annotation callable and a pass
        # function. Its single map entry loads the fixed key before the string.
        callbacks=[c for c in code.co_consts if type(c) is CodeType and c.co_name=='__annotate__']
        _require(len(callbacks)==1,site,'controlled compiler wrapper annotation shape differs')
        strings=[v for v in callbacks[0].co_consts if type(v) is str]
        _require(1<=len(strings)<=2 and strings[0]=='_value',site,'controlled compiler wrapper constant order differs')
        self._strings[site]=strings[-1]
        return strings[-1]
