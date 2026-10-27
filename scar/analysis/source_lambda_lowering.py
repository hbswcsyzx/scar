"""Lambda creation plus its original, deferred expression-body Region.

One creation interface references original child code/defaults/cells. A
separate ordinary Region evaluates the original Lambda.body and returns its
reference/world; creation never CALLs that Region. No synthesized source AST,
captured CodeID, runtime callable, frozen cell contents or execution is added.
"""
from __future__ import annotations

import ast
import dis
from dataclasses import replace
from types import CodeType

from scar.analysis.program_lowering import _Unsupported, _REF, _key
from scar.analysis.environment_lowering import captured_cell_slot, _PREFIX
from scar.analysis.source_generator_lowering import _Nested
from scar.analysis.source_function_definition_lowering import _code_reference, _hold
from scar.analysis.source_heap_lowering import _source_definition, _associate, _hold as hold_expression
from scar.analysis.source_slice_lowering import _invoke
from scar.analysis.source_mapping_lowering import _transfer
from scar.analysis.structured_lowering import StructuredBuilder
from scar.analysis.function_interfaces import formal_nodes
from scar.ir.program.environments import EnvironmentInterface, EnvironmentMember, EnvironmentRole, FunctionEntryLayout
from scar.ir.program.functions import BodyEntryInterface, BodyLoweringProfile, FormalPort
from scar.ir.program.ids import EnvironmentInterfaceID, OperationID, RegionID, ValueID
from scar.ir.program.lambda_bodies import LambdaBodyDefinition, LambdaCapture, LambdaEnvironmentField
from scar.ir.program.model import (Behavior, Block, BlockArgument, ExitKind, ExitPort, LiteralOrigin,
    Operation, ReferenceValue, Region, Terminator, TerminatorKind)
from scar.ir.program.source import GapKind, SourceRole
from scar.ir.program.structured import PythonProtocolKind as K
from scar.ir.semantics_v2 import Opcode
from scar.ir.v2.semantic import OperationKind

VERSION = 'PYTHON_LAMBDA_EXPRESSION_314_V1'


def span(node):
    return node.lineno, node.end_lineno, node.col_offset, node.end_col_offset


def compiler_lambda(node, code):
    rows = tuple(dis.get_instructions(code))
    loads = [r for r in rows if r.opname == 'LOAD_CONST' and type(r.argval) is CodeType
             and r.argval.co_name == '<lambda>' and tuple(r.positions) == span(node)]
    if not loads or len({r.arg for r in loads}) != 1:
        raise _Unsupported(GapKind.CODE_VERSION,node,'LAMBDA_ORIGINAL_CONSTANT_SLOT_AMBIGUOUS')
    index = loads[0].arg; child = code.co_consts[index]
    names = tuple(a.arg for a, _ in formal_nodes(node))
    parameters = (*node.args.posonlyargs,*node.args.args,*node.args.kwonlyargs)
    if (any(r.argval is not child for r in loads) or child.co_firstlineno != node.lineno
            or child.co_qualname != code.co_qualname + '.<locals>.<lambda>'
            or child.co_argcount != len(node.args.posonlyargs)+len(node.args.args)
            or child.co_posonlyargcount != len(node.args.posonlyargs)
            or child.co_kwonlyargcount != len(node.args.kwonlyargs)
            or bool(child.co_flags & 4) != (node.args.vararg is not None)
            or bool(child.co_flags & 8) != (node.args.kwarg is not None)
            or set(child.co_varnames[:len(names)]) != set(names)):
        raise _Unsupported(GapKind.CODE_VERSION,node,'LAMBDA_ORIGINAL_PARAMETER_CODE_INTERFACE_DIFFERS')
    for load in loads:
        at=rows.index(load)
        if at+1>=len(rows) or rows[at+1].opname!='MAKE_FUNCTION':
            raise _Unsupported(GapKind.CODE_VERSION,node,'LAMBDA_ORIGINAL_FACTORY_INTERFACE_UNRECOVERED')
        if child.co_freevars:
            prefix=rows[at-len(child.co_freevars)-1:at]
            if (len(prefix)!=len(child.co_freevars)+1 or prefix[-1].opname!='BUILD_TUPLE'
                    or prefix[-1].arg!=len(child.co_freevars)
                    or tuple(r.argval for r in prefix[:-1])!=child.co_freevars
                    or any(r.opname not in ('LOAD_FAST','LOAD_FAST_BORROW')for r in prefix[:-1])
                    or rows[at+2].opname!='SET_FUNCTION_ATTRIBUTE' or rows[at+2].arg!=8):
                raise _Unsupported(GapKind.CODE_VERSION,node,'LAMBDA_ORIGINAL_CELL_CAPTURE_INTERFACE_DIFFERS')
    return loads[0], child


class _ExpressionBody(_Nested):
    """Original expression adapter with ordinary function ABI, not a driver."""
    def fresh(self, cls, tag):
        return self.owner.fresh(cls,'lambda-'+tag)

    def emit(self, cursor, operation, node, role, old=None):
        # Bypass a parent's active Try scope: the deferred child frame owns
        # these blocks, and cannot accidentally enter a creating frame's except.
        # Buffers and the construction budget belong to the creating builder;
        # the child owns only its Region. Bypass Try.emit without copying the
        # integer budget counter into the child.
        StructuredBuilder.emit(self.owner,cursor,operation,node,role,old=old)

    def expr(self,node,cursor):
        definition=_source_definition(self,node)
        if isinstance(node,ast.Name):
            cursor,value=self.read_source_name(node,cursor,None)
            if cursor is not None:
                from scar.analysis.source_heap_lowering import _normal_producer
                record=self.values_by_id[value]
                if isinstance(record.origin,BlockArgument):
                    producers=[o.id for o in self.operations if o.terminator is not None
                        and o.terminator.kind is TerminatorKind.INVOKE
                        and any(e.kind is ExitKind.NORMAL and e.block==record.origin.block for e in o.terminator.successors)]
                    identity,=producers
                else:identity=record.origin.operation
                _associate(self,identity,node,definition,Opcode.READ)
            return cursor,value
        if isinstance(node,ast.Constant):
            try:origin=LiteralOrigin(node.value)
            except (TypeError,ValueError) as error:
                raise _Unsupported(GapKind.UNSUPPORTED_SYNTAX,node,'LAMBDA_LITERAL_INTERFACE_UNIMPLEMENTED: '+str(error))
            value=ReferenceValue(self.fresh(ValueID,'literal'),self.function_context,origin,targets=())
            self.add_value(value);self.link_value(value,node,SourceRole.EXPRESSION)
            return cursor,value.id
        if isinstance(node,ast.Dict):
            if len(node.keys)>15 or any(k is None for k in node.keys):
                raise _Unsupported(GapKind.UNSUPPORTED_SYNTAX,node,'LAMBDA_DICT_EXPANSION_OR_INCREMENTAL_INTERFACE_UNIMPLEMENTED')
            from scar.analysis.source_mapping_lowering import lower_dictionary
            return lower_dictionary(self,node,cursor)
        if isinstance(node,ast.Call) and not any(isinstance(a,ast.Starred)for a in node.args) and all(k.arg is not None for k in node.keywords):
            children=[(node.func,'callee',0),*((n,'argument',i)for i,n in enumerate(node.args)),
                      *((k.value,'keyword:'+k.arg,i)for i,k in enumerate(node.keywords))]
            opcode=Opcode.CALL
        elif isinstance(node,ast.Attribute) and not (node.attr.startswith('__')and not node.attr.endswith('__')):
            children=[(node.value,'receiver',0)];opcode=Opcode.ATTRIBUTE
        elif isinstance(node,ast.Subscript) and not isinstance(node.slice,(ast.Slice,ast.Tuple)):
            children=[(node.value,'receiver',0),(node.slice,'index',1)];opcode=Opcode.INDEX
        else:
            raise _Unsupported(GapKind.UNSUPPORTED_SYNTAX,node,'LAMBDA_EXPRESSION_INTERFACE_UNIMPLEMENTED: '+type(node).__name__)
        baseline=len(self.active_temporaries);held=[];inputs=[]
        try:
            for child,role,index in children:
                cursor,value=self.expr(child,cursor)
                if cursor is None:return None,None
                hold_expression(self,cursor,child,value);held.append((child,value));inputs.append((value,child,role,index,None))
            cursor,result,identity=_invoke(self,cursor,node,inputs,tuple(held))
            _associate(self,identity,node,definition,opcode)
            self.link_value(self.values_by_id[result],node,SourceRole.EXPRESSION)
            if opcode is Opcode.CALL:
                self.pending_targets.append((identity,inputs[0][0],None,node))
            if opcode is Opcode.INDEX:
                from scar.ir.program.state_addresses import AddressEffect,Element,ReferenceOwner
                from scar.ir.program.model import AccessMode
                uses=self.operation_records[identity].uses
                self._addresses(identity,(AddressEffect(ReferenceOwner(uses[0].id),(Element(uses[1].id),),AccessMode.READ),))
            return cursor,result
        finally:del self.active_temporaries[baseline:]

    def terminal(self,cursor,results,kind=ExitKind.NORMAL):
        identity=self.fresh(OperationID,'return'if kind is ExitKind.NORMAL else'raise')
        uses=tuple(self.use(identity,value,self.node.body,'result',index)for index,value in enumerate((*results,cursor.state)))
        self.emit(cursor,Operation(identity,kind.value,(Behavior.CONTROL,),uses,
            terminator=Terminator(TerminatorKind.RETURN if kind is ExitKind.NORMAL else TerminatorKind.RAISE,
                exit=kind.value.lower(),values=tuple(u.id for u in uses))),self.node.body,SourceRole.RETURN)
        return identity


def _expression_body(owner,node,definition,code,index):
    if code.co_cellvars:
        raise _Unsupported(GapKind.UNSUPPORTED_SYNTAX,node,'LAMBDA_EXPRESSION_OWN_CELL_ALLOCATION_UNIMPLEMENTED')
    region=RegionID(_key('lambda-expression-body',definition.id.wire,owner.language_options.code_evidence.code_layout_key,index,VERSION))
    b=_ExpressionBody(owner,node,region,definition);b.language_options=None
    parameters=tuple(a for a,_ in formal_nodes(node));b.locals={a.arg for a in parameters}
    b.free_cells=frozenset(code.co_freevars);b.global_names=set(code.co_names)
    cursor,refs=b.ports((_REF,)*(len(_PREFIX)+len(code.co_freevars)+len(parameters)))
    env_refs=refs[:len(_PREFIX)+len(code.co_freevars)];actual=refs[len(env_refs):]
    members=[EnvironmentMember(role,value,(b.world,))for role,value in zip(_PREFIX,env_refs)]
    for position,name in enumerate(code.co_freevars):
        members.append(EnvironmentMember(EnvironmentRole.CAPTURED_CELL,env_refs[len(_PREFIX)+position],(b.world,),
            captured_cell_slot(definition.id,name),position))
    b.environment_references=dict(zip(_PREFIX,env_refs));b.cell_references=dict(zip(code.co_freevars,env_refs[len(_PREFIX):]))
    ports=tuple(FormalPort(b.slots[definition.id,arg.arg],value)for arg,value in zip(parameters,actual))
    for parameter,port in zip(parameters,ports):
        b.link_value(b.values_by_id[port.value],parameter,SourceRole.PARAMETER,slot=port.slot)
    interface=BodyEntryInterface(definition.id,region,ports,cursor.state,BodyLoweringProfile.STRUCTURED_ENV)
    b.interface=interface
    environment=EnvironmentInterface(EnvironmentInterfaceID(_key('lambda-environment',region.wire)),region,definition.id,tuple(members))
    entry=cursor.block
    b.frame_transition(cursor,node,tuple((v,node,'environment-reference')for v in env_refs)
        +tuple((v,a,'formal-reference')for a,v in zip(parameters,actual)),K.FRAME_ENTER)
    for parameter,value in zip(parameters,actual):b.define_binding(parameter.arg,cursor,parameter,value)
    cursor,result=b.expr(node.body,cursor)
    if cursor is not None:b.finish_exit(cursor,node.body,result,ExitKind.NORMAL)
    blocks=tuple(Block(key,b.block_arguments[key],tuple(b.block_operations[key]))for key in b.function_blocks)
    b.regions.append(Region(region,'lambda expression',entry,blocks,
        (ExitPort('normal',ExitKind.NORMAL,(_REF,b.state_type)),ExitPort('raise',ExitKind.RAISE,(_REF,b.state_type))),
        parent=owner.function_context))
    owner.lambda_environments.append(environment);owner.lambda_entries.append(FunctionEntryLayout(environment.id,ports))
    return interface,environment


def lower_lambda(builder,node,cursor):
    evidence=builder.language_options.code_evidence
    if evidence is None:
        raise _Unsupported(GapKind.CODE_VERSION,node,'LAMBDA_READONLY_PARENT_CODE_REQUIRED')
    load,code=compiler_lambda(node,evidence.code)
    declaration=_source_definition(builder,node)
    bodies=[d for d in builder.by_atom.get(builder.source(node).atom_id.wire,())
            if d.metadata.get('phase')=='call_time'and d.kind in(OperationKind.FUNCTION,OperationKind.METHOD)]
    if declaration.metadata.get('phase')!='definition_time' or len(bodies)!=1:
        raise _Unsupported(GapKind.SOURCE_MAPPING,node,'LAMBDA_ORIGINAL_DECLARATION_OR_BODY_MISSING')
    if any(n not in builder.cell_references for n in code.co_freevars):
        raise _Unsupported(GapKind.SOURCE_MAPPING,node,'LAMBDA_CAPTURE_HAS_NO_ACTUAL_PARENT_CELL')
    if not hasattr(builder,'lambda_bodies'):
        builder.lambda_bodies=[];builder.lambda_environments=[];builder.lambda_entries=[]
    body,environment=_expression_body(builder,node,bodies[0],code,load.arg)
    baseline=len(builder.active_temporaries);defaults=[];inputs=[]
    try:
        from scar.analysis.source_heap_lowering import expression_for_heap_target
        for index,source in enumerate(node.args.defaults):
            cursor,value=expression_for_heap_target(builder,source,cursor)
            if cursor is None:return None,None
            _hold(builder,cursor,source,value,'default');defaults.append((source,value))
            inputs.append((value,source,'lambda-default',index,None))
        for index,(argument,source)in enumerate(zip(node.args.kwonlyargs,node.args.kw_defaults)):
            if source is None:continue
            cursor,value=expression_for_heap_target(builder,source,cursor)
            if cursor is None:return None,None
            _hold(builder,cursor,source,value,'keyword-default');defaults.append((source,value))
            inputs.append((value,source,'lambda-keyword-default:'+argument.arg,index,None))
        code_ref=_code_reference(builder,node,cursor,load,'lambda code')
        read=builder.values_by_id[code_ref].origin.operation
        prefix=[(code_ref,node,'lambda-code',0,None),
                (builder.environment_references[EnvironmentRole.GLOBALS_NAMESPACE],node,'lambda-globals',0,None)]
        inputs=prefix+inputs+[(builder.cell_references[name],node,'lambda-closure-cell',i,None)for i,name in enumerate(code.co_freevars)]
        def failed(failure,error):
            pending=tuple(builder.active_temporaries)
            try:
                _transfer(builder,tuple(defaults),node);builder.finish_exit(failure,node,error,ExitKind.RAISE)
            finally:builder.active_temporaries[:]=pending
        cursor,results,identity=builder.invoke_results(cursor,node,tuple(inputs),result_types=(_REF,),failure_handler=failed)
        builder.protocol(identity,K.MAKE_LAMBDA_FUNCTION,node)
        _associate(builder,identity,node,declaration,None);_transfer(builder,tuple(defaults),node)
        uses=builder.operation_records[identity].uses
        original=builder.operation_records[identity]
        marked=replace(original,behaviors=original.behaviors+(Behavior.MEMORY,))
        builder.operations[builder.operations.index(original)]=marked;builder.operation_records[identity]=marked
        function=results[0]
        # A constructor's initialized fields are a conditional state summary,
        # not extra runtime returns and not analyzer-invented target reads.
        captures=(LambdaCapture(environment.members[0].reference,normal_result=0),
                  LambdaCapture(environment.members[1].reference,source_use=uses[1].id))
        captures+=tuple(LambdaCapture(member.reference,created_field=field)
                       for member,field in zip(environment.members[2:5],LambdaEnvironmentField))
        closure=[u for u in uses if any(s.operation==identity and s.use==u.id and s.role=='lambda-closure-cell'for s in builder.use_links)]
        captures+=tuple(LambdaCapture(member.reference,source_use=use.id)for member,use in zip(environment.members[5:],closure))
        builder.lambda_bodies.append(LambdaBodyDefinition(identity,builder.source(node),read,body,environment.id,captures))
        builder.link_value(builder.values_by_id[function],node,SourceRole.EXPRESSION)
        builder.gap(GapKind.CODE_VERSION,node,'Lambda creation and expression body use the original child code/source; runtime callable/code identity and execution remain unproved')
        builder.gap(GapKind.EFFECT_SUMMARY,node,'Lambda defaults are evaluated only at creation; cells remain references read at invocation, and dynamic dispatch/finalizers/contents remain incomplete')
        return cursor,function
    finally:del builder.active_temporaries[baseline:]


def assemble_lambda_bodies(builder,graph):
    return replace(graph,environments=(*graph.environments,*builder.lambda_environments),
        function_entries=(*graph.function_entries,*builder.lambda_entries))


__all__=['lower_lambda','assemble_lambda_bodies','compiler_lambda']
