"""Static class-suite construction from its exact source/compiler interface.

The compiler stack is construction-only. Copies/borrows forward existing SSA
references; actual cell, namespace, value, factory and state operations become
canonical nodes. Unsupported control starts an exact compiler continuation,
never a replay of already evaluated source or an invented function frame.
"""
from __future__ import annotations

import ast
import dis
from dataclasses import replace
from types import CodeType

from scar.analysis.source_class_lowering import (
    _resolve_class, _class_header_inputs, _class_scope_statements, _compiler_cells,
    _frontiers, _stable_id, _node_reference,
)
from scar.ir.program.class_entries import (
    ClassSuiteOverlay,ClassSuiteProtocol,ClassSuiteInstruction,ClassSuiteCell,
    ClassSuiteConstant,ClassSuiteFactory,ClassSuiteResidual,ClassEntryResult,
    ClassFrontierKind,compiler_cell_protocol,
)
from scar.ir.program.ids import BlockID,OperationID,RegionID,ValueID,UseID,LocationID,ControlScopeID
from scar.ir.program.model import (
    AccessMode,Behavior,Block,BlockArgument,CompletionResult,CompletionSignature,
    CompletionSuccessor,ExitKind,ExitPort,LiteralOrigin,Operation,OperationResult,
    ProgramGraph,ReferenceValue,Region,Stability,StateAccess,StateLocation,
    StateVersionValue,Terminator,TerminatorKind,Use,UseRole,ValueKind,ValueType,
)
from scar.ir.program.source import (
    GapKind,LoweringGap,LoweringMetadata,OperationSource,UseSource,ValueSource,SourceRole,
)
from scar.ir.program.source_subjects import ClassFrameABI,MappingFramePorts,SourceCompilationFrameRoot,FrameKind
from scar.ir.program.control import ControlScope,ControlScopeKind
from scar.ir.semantics_v2 import Opcode
from scar.ir.v2.semantic import OperationKind
from scar.ir.program.state_addresses import (
    AddressCoverage,AddressEffect,CellContent,ExistingAccess,InvokeStateOperand,
    NamespaceKey,ObjectField,ReferenceOwner,StateAddressRefinement,
)

REF=ValueType(ValueKind.REFERENCE)
SUPPORTED=frozenset(('RESUME','COPY_FREE_VARS','MAKE_CELL','LOAD_CONST','LOAD_SMALL_INT',
    'LOAD_NAME','LOAD_GLOBAL','LOAD_LOCALS','STORE_NAME','DELETE_NAME','STORE_GLOBAL',
    'LOAD_DEREF','STORE_DEREF','LOAD_FROM_DICT_OR_DEREF','LOAD_FAST_BORROW',
    'BUILD_TUPLE','BUILD_LIST','BUILD_SET','BUILD_MAP','MAKE_FUNCTION','SET_FUNCTION_ATTRIBUTE',
    'COPY','SWAP','POP_TOP','PUSH_NULL','CALL','CALL_KW','LOAD_ATTR','BINARY_OP',
    'UNARY_NEGATIVE','UNARY_INVERT','UNARY_NOT','RETURN_VALUE','NOP','EXTENDED_ARG'))


class ClassSuiteBuilder:
    def __init__(self,prepared,definition,source,evidence,limit):
        self.prepared,self.definition,self.source,self.evidence=prepared,definition,source,evidence
        self.snapshot,self.semantic_definition,self.node=_resolve_class(prepared,definition,source)
        evidence.require_definition(self.snapshot,definition,source)
        self.code=evidence.code;self.limit=limit;self.serial=0
        self.region=self.fresh(RegionID,'class-suite');self.scope=self.fresh(ControlScopeID,'class-frame')
        self.world=self.fresh(LocationID,'class-world');self.state_type=ValueType(ValueKind.STATE,location=self.world)
        self.ops=[];self.values=[];self.blocks=[];self.block_ops={};self.args={};self.records={}
        self.op_links=[];self.value_links=[];self.use_links=[];self.addresses=[]
        self.protocols=[];self.witnesses=[];self.constants=[];self.factories=[];self.cells=[]
        self.cell_refs={};self.stack=[];self.literal_values={};self.code_refs={};self.tuple_items={};self.function_codes={};self.returned=False;self.remaining=None
        from scar.analysis.static_compilation import compile_source_unit
        self.compilation_index=compile_source_unit(prepared)
        self.instructions=tuple(dis.get_instructions(self.code,adaptive=False,show_caches=False))
        self.normal_mode=compiler_cell_protocol(self.code)[1]
        self.owner_nodes=[n for n in ast.walk(self.node) if isinstance(n,(ast.expr,ast.stmt))]
        self.decorator_offsets=set();self.unclassified_applications=set()
        for n in self.owner_nodes:
            if not isinstance(n,(ast.FunctionDef,ast.AsyncFunctionDef)):continue
            source_n=_node_reference(prepared,n)
            defs=[d for d in prepared.semantic.definitions.values()if d.code_id==source_n.atom_id.wire and d.metadata.get('phase')=='call_time']
            paths=[]
            for d in defs:
                try:proof=self.compilation_index.for_definition(d.id,source_n)
                except ValueError:continue
                if proof.code_path[:-1]==evidence.code_path:paths.append(proof.code_path)
            if len(paths)!=1:continue
            loads=[r for r in self.instructions if r.opname=='LOAD_CONST'and r.arg==paths[0][-1]and type(r.argval)is CodeType]
            binding=n.name
            if binding.startswith('__')and not binding.endswith('__')and self.node.name.lstrip('_'):
                binding='_'+self.node.name.lstrip('_')+binding
            stores=[r for r in self.instructions if r.opname=='STORE_NAME'and r.argval==binding and tuple(r.positions)==
                (n.lineno,n.end_lineno,n.col_offset,n.end_col_offset)and loads and r.offset>loads[0].offset]
            if len(loads)!=1 or len(stores)!=1:continue
            calls=[r for r in self.instructions if loads[0].offset<r.offset<stores[0].offset and r.opname in ('CALL','CALL_KW','CALL_FUNCTION_EX')]
            expected=[(d.lineno,d.end_lineno,d.col_offset,d.end_col_offset)for d in reversed(n.decorator_list)]
            if len(calls)==len(expected)and all(r.opname=='CALL'and r.arg==0 and tuple(r.positions)==s for r,s in zip(calls,expected)):
                self.decorator_offsets.update(r.offset for r in calls)
            else:self.unclassified_applications.update(r.offset for r in calls)
        refs=3+len(self.code.co_freevars)
        self.current=self.new_block((REF,)*refs+(self.state_type,));self.entry=self.current
        arguments=self.args[self.entry]
        self.namespaces=arguments[:3];self.free=dict(zip(self.code.co_freevars,arguments[3:-1]));self.state=arguments[-1]
        self.interface=ClassFrameABI(MappingFramePorts(*self.namespaces,tuple(arguments[3:-1]),self.state),
            tuple(self.code.co_freevars),tuple(self.code.co_cellvars),_compiler_cells(self.code))
        self.transition('FRAME_ENTER',tuple(arguments[:-1]),source,-1)

    def fresh(self,kind,role):
        self.serial+=1
        return kind(_stable_id(kind,'class-suite',self.definition,self.source.fingerprint,role,self.serial))

    def new_block(self,types):
        block=self.fresh(BlockID,'block');values=[]
        for index,t in enumerate(types):
            identity=self.fresh(ValueID,'argument')
            value=(ReferenceValue(identity,self.region,BlockArgument(block,index)) if t.kind is ValueKind.REFERENCE
                   else StateVersionValue(identity,self.region,BlockArgument(block,index),self.world))
            self.add_value(value,self.source,SourceRole.PARAMETER);values.append(identity)
        self.blocks.append(block);self.args[block]=tuple(values);self.block_ops[block]=[]
        return block

    def add_value(self,value,source,role=SourceRole.EXPRESSION):
        self.values.append(value);self.records[value.id]=value;self.value_links.append(ValueSource(value.id,source,role))

    def uses(self,op,values,source,roles=None,sources=None):
        result=[]
        for index,value in enumerate(values):
            identity=self.fresh(UseID,'use');record=self.records[value]
            result.append(Use(identity,value,UseRole.STATE_CONTENT if type(record)is StateVersionValue else UseRole.REFERENCE))
            self.use_links.append(UseSource(op,identity,sources[index] if sources else source,roles[index] if roles else 'operand',index))
        return tuple(result)

    def emit(self,op,source,role=SourceRole.EXPRESSION,definition=None):
        if len(self.ops)>=self.limit:raise ValueError('class suite operation budget exceeded')
        self.ops.append(op);self.block_ops[self.current].append(op.id)
        self.op_links.append(OperationSource(op.id,source,role,definition))

    def source_for(self,instruction):
        p=tuple(instruction.positions)
        exact=[n for n in self.owner_nodes if (n.lineno,n.end_lineno,n.col_offset,n.end_col_offset)==p]
        # Prefer an expression/statement's actual occurrence, never a made-up
        # AST for generated code. The containing ClassDef is the fallback.
        if exact:
            exact.sort(key=lambda n:(isinstance(n,(ast.FunctionDef,ast.AsyncFunctionDef)),isinstance(n,ast.expr)),reverse=True)
            try:return _node_reference(self.prepared,exact[0])
            except ValueError:pass
        return self.source

    def literal(self,value,source):
        identity=self.fresh(ValueID,'literal')
        self.add_value(ReferenceValue(identity,self.region,LiteralOrigin(value),targets=()),source)
        self.literal_values[identity]=value
        return identity

    def transition(self,kind,refs,source,offset):
        identity=self.fresh(OperationID,kind);uses=self.uses(identity,(*refs,self.state),source)
        after=self.fresh(ValueID,'world');self.add_value(StateVersionValue(after,self.region,OperationResult(identity,0),self.world),source,SourceRole.STATE)
        op=Operation(identity,kind,(Behavior.READ,Behavior.WRITE,Behavior.MEMORY),uses,(after,),
                     (StateAccess(self.world,uses[-1].id,AccessMode.READ_WRITE,after),),effects_complete=False)
        self.emit(op,source,SourceRole.STATE);self.protocols.append(ClassSuiteProtocol(identity,kind,source,offset));self.state=after
        return identity

    def live(self,extra=()):
        refs=(*self.namespaces,*self.free.values(),*self.cell_refs.values(),*(x for x in self.stack if x is not None),*extra)
        return tuple(dict.fromkeys(refs))

    def invoke(self,kind,operands,source,offset,results=1,address=None,definition=None,roles=None,use_sources=None):
        identity=self.fresh(OperationID,kind);uses=self.uses(identity,(*operands,self.state),source,
            (*roles,'world') if roles is not None else None,(*use_sources,source) if use_sources is not None else None)
        normal_types=(REF,)*results+(self.state_type,)
        normal=self.new_block(normal_types);failure=self.new_block((REF,REF,self.state_type))
        signatures=(CompletionSignature(ExitKind.NORMAL,normal_types),CompletionSignature(ExitKind.RAISE,(REF,REF,self.state_type)))
        op=Operation(identity,kind,(Behavior.CONTROL,Behavior.READ,Behavior.WRITE,Behavior.MEMORY),uses,
            effects_complete=False,terminator=Terminator(TerminatorKind.INVOKE,tuple(
                CompletionSuccessor(s.kind,b,tuple(CompletionResult(i)for i in range(len(s.types))))
                for s,b in zip(signatures,(normal,failure)))),completions=signatures,invoke_arguments=tuple(u.id for u in uses))
        self.emit(op,source,definition=definition);self.protocols.append(ClassSuiteProtocol(identity,kind,source,offset))
        if address:
            effects=tuple(AddressEffect(ReferenceOwner(uses[owner].id),
                (NamespaceKey(uses[key].id) if type(key)is int else key,),mode)for owner,key,mode in address)
            self.addresses.append(StateAddressRefinement(InvokeStateOperand(identity,uses[-1].id),effects,AddressCoverage.PARTIAL))
        # Frame cleanup receives the original pair and post-operation world.
        # Inputs to these compound primitives are borrowed by this interface;
        # their consuming/packing internals remain conditional frame effects.
        prior_current,prior_state=self.current,self.state
        self.current=failure;exception,traceback,self.state=self.args[failure]
        self.transition('FRAME_EXIT_EXCEPTION',(*self.live(operands),exception,traceback),source,offset)
        self.exit((exception,traceback),ExitKind.RAISE,source)
        self.current=normal;self.state=self.args[normal][-1]
        return tuple(self.args[normal][:-1]),identity

    def exit(self,payload,kind,source):
        identity=self.fresh(OperationID,'exit');uses=self.uses(identity,(*payload,self.state),source)
        self.emit(Operation(identity,'class-body-'+kind.value.lower(),(Behavior.CONTROL,),uses,
            terminator=Terminator(TerminatorKind.RETURN if kind is ExitKind.NORMAL else TerminatorKind.RAISE,
                exit=kind.value.lower(),values=tuple(u.id for u in uses))),source,
            SourceRole.RETURN if kind is ExitKind.NORMAL else SourceRole.EXCEPTION)

    def pop(self):
        if not self.stack:raise ValueError('class compiler operand stack underflow')
        return self.stack.pop()

    def handle(self,i):
        source=self.source_for(i);name=i.opname;arg=i.argval;identity=None
        if name in ('RESUME','COPY_FREE_VARS','NOP','EXTENDED_ARG'):return None
        if name=='PUSH_NULL':self.stack.append(None)
        elif name=='COPY':self.stack.append(self.stack[-i.arg])
        elif name=='SWAP':self.stack[-1],self.stack[-i.arg]=self.stack[-i.arg],self.stack[-1]
        elif name=='LOAD_FAST_BORROW':
            if arg not in self.cell_refs and arg not in self.free:raise ValueError('class borrow has no original owned/free cell')
            self.stack.append(self.cell_refs.get(arg,self.free.get(arg)))
        elif name=='LOAD_LOCALS':self.stack.append(self.namespaces[0])
        elif name=='LOAD_SMALL_INT':self.stack.append(self.literal(arg,source))
        elif name=='LOAD_CONST':
            if type(i.arg)is not int or self.code.co_consts[i.arg] is not arg:raise ValueError('class constant slot differs')
            identity=self.fresh(OperationID,'class-code-constant');before=self.uses(identity,(self.state,),source)
            value=self.fresh(ValueID,'code-reference');self.add_value(ReferenceValue(value,self.region,OperationResult(identity,0)),source)
            self.emit(Operation(identity,'READ_CODE_CONSTANT',(Behavior.READ,),before,(value,),
                (StateAccess(self.world,before[0].id,AccessMode.READ),),effects_complete=False),source)
            self.protocols.append(ClassSuiteProtocol(identity,'READ_CODE_CONSTANT',source,i.offset))
            self.constants.append(ClassSuiteConstant(identity,value,(i.arg,)));self.stack.append(value)
            if type(arg)is CodeType:self.code_refs[value]=(i.arg,arg)
            else:self.literal_values[value]=arg
        elif name=='MAKE_CELL':
            if arg not in self.code.co_cellvars or arg in self.cell_refs:raise ValueError('class own cell allocation differs')
            result,identity=self.invoke('MAKE_CELL',(),source,i.offset)
            self.cell_refs[arg]=result[0];self.cells.append(ClassSuiteCell(arg,self.code.co_cellvars.index(arg),result[0],identity))
        elif name in ('LOAD_DEREF','LOAD_FROM_DICT_OR_DEREF'):
            cell=self.cell_refs.get(arg,self.free.get(arg))
            if cell is None:raise ValueError('class deref has no declared cell')
            refs=(cell,) if name=='LOAD_DEREF' else (self.pop(),self.literal(arg,source),cell)
            addresses=((0,CellContent(),AccessMode.READ),) if name=='LOAD_DEREF' else ((0,1,AccessMode.READ),(2,CellContent(),AccessMode.READ))
            result,identity=self.invoke(name,refs,source,i.offset,address=addresses)
            self.stack.append(result[0])
        elif name=='STORE_DEREF':
            cell=self.cell_refs.get(arg,self.free.get(arg));value=self.pop()
            if cell is None:raise ValueError('class deref write has no declared cell')
            _,identity=self.invoke('STORE_CELL',(cell,value),source,i.offset,results=0,address=((0,CellContent(),AccessMode.WRITE),))
        elif name in ('LOAD_NAME','LOAD_GLOBAL'):
            key=self.literal(arg,source);refs=self.namespaces if name=='LOAD_NAME' else self.namespaces[1:]
            result,identity=self.invoke('LOAD_NAME_314' if name=='LOAD_NAME' else 'LOAD_GLOBAL',(*refs,key),source,i.offset,
                address=tuple((n,len(refs),AccessMode.READ)for n in range(len(refs))))
            self.stack.append(result[0])
            if name=='LOAD_GLOBAL' and i.arg&1:self.stack.append(None)
        elif name in ('STORE_NAME','STORE_GLOBAL','DELETE_NAME'):
            key=self.literal(arg,source);owner=self.namespaces[1] if name=='STORE_GLOBAL' else self.namespaces[0]
            refs=(owner,key) if name=='DELETE_NAME' else (owner,key,self.pop())
            _,identity=self.invoke('STORE_NAME_314' if name=='STORE_NAME' else name,refs,source,i.offset,results=0,
                address=((0,1,AccessMode.WRITE),),roles=('locals-owner','namespace-key','assigned-reference') if len(refs)==3 else None)
        elif name in ('BUILD_TUPLE','BUILD_LIST','BUILD_SET','BUILD_MAP'):
            count=i.arg*(2 if name=='BUILD_MAP' else 1);refs=tuple(self.pop()for _ in range(count))[::-1]
            result,identity=self.invoke(name,refs,source,i.offset);self.stack.append(result[0])
            if name=='BUILD_TUPLE':self.tuple_items[result[0]]=refs
        elif name=='MAKE_FUNCTION':
            code=self.pop()
            if code not in self.code_refs:raise ValueError('class factory lacks its actual child code reference')
            index,child=self.code_refs[code]
            result,identity=self.invoke('MAKE_FUNCTION_314',(code,self.namespaces[1]),source,i.offset,
                roles=('function-code','function-globals'))
            self.stack.append(result[0]);self.function_codes[result[0]]=child;definition=None
            candidates=[d for d in self.prepared.semantic.definitions.values() if d.code_id==source.atom_id.wire
                and d.metadata.get('phase')=='call_time']
            matched=[]
            for candidate in candidates:
                try:proof=self.compilation_index.for_definition(candidate.id,source)
                except ValueError:continue
                if proof.code_path==self.evidence.code_path+(index,):matched.append(candidate.id)
            if len(matched)==1:
                definition=matched[0]
                declarations=[d for d in self.prepared.semantic.definitions.values() if d.code_id==source.atom_id.wire
                    and d.metadata.get('phase')=='definition_time']
                if len(declarations)==1:
                    link_index=next(n for n,link in enumerate(self.op_links)if link.operation==identity)
                    self.op_links[link_index]=replace(self.op_links[link_index],semantic_operation=declarations[0].id)
            self.factories.append(ClassSuiteFactory(identity,result[0],code,(index,),definition,source,tuple(child.co_freevars)))
        elif name=='SET_FUNCTION_ATTRIBUTE':
            function=self.pop();value=self.pop()
            field={1:'__defaults__',2:'__kwdefaults__',4:'__annotations__',8:'__closure__',16:'__annotate__'}.get(i.arg)
            if field is None:raise ValueError('class function attribute flag unsupported')
            if function not in self.function_codes:raise ValueError('class attribute initialization lost its fresh function result')
            if field=='__closure__':
                expected=tuple(self.cell_refs.get(n,self.free.get(n))for n in self.function_codes[function].co_freevars)
                if None in expected or self.tuple_items.get(value)!=expected:
                    raise ValueError('class function closure did not capture original ordered cell references')
            _,identity=self.invoke('SET_FUNCTION_ATTRIBUTE',(function,value),source,i.offset,results=0,
                address=((0,ObjectField(field),AccessMode.WRITE),));self.stack.append(function)
        elif name=='LOAD_ATTR':
            if i.arg&1:raise ValueError('class method-lookup two-result ABI requires expansion')
            owner=self.pop();key=self.literal(arg,source)
            result,identity=self.invoke('LOAD_ATTRIBUTE',(owner,key),source,i.offset,address=((0,ObjectField(arg),AccessMode.READ),))
            self.stack.append(result[0])
        elif name in ('CALL','CALL_KW'):
            keyword=self.pop() if name=='CALL_KW' else None
            args=tuple(self.pop()for _ in range(i.arg))[::-1];receiver=self.pop();callee=self.pop()
            if callee is None:raise ValueError('class CALL lacks a callable reference')
            if receiver is not None:args=(receiver,*args)
            operands=(callee,*args,*((keyword,)if keyword is not None else ()))
            application=i.offset in self.decorator_offsets
            call_nodes=[n for n in self.owner_nodes if isinstance(n,ast.Call)and tuple(i.positions)==
                (n.lineno,n.end_lineno,n.col_offset,n.end_col_offset)]
            actual_call=call_nodes[0]if len(call_nodes)==1 and not application and i.offset not in self.unclassified_applications else None
            operand_sources=None;semantic=None;roles=('callee',*('argument'for _ in operands[1:]))
            if actual_call is not None and receiver is None and not any(isinstance(a,ast.Starred)for a in actual_call.args):
                exprs=(actual_call.func,*actual_call.args,*(k.value for k in actual_call.keywords))
                if len(exprs)==1+len(args):
                    operand_sources=tuple(_node_reference(self.prepared,n)for n in exprs)+((source,)if keyword is not None else ())
                    definitions=[d for d in self.prepared.semantic.definitions.values()if d.code_id==source.atom_id.wire
                        and d.output_slots and d.metadata.get('role')!='binding'
                        and (d.metadata.get('ast_type')=='Call' or d.id in self.prepared.semantics.operations
                             and self.prepared.semantics.operations[d.id].opcode is Opcode.CALL)]
                    if len(definitions)==1:semantic=definitions[0].id
            kind='APPLY_DECORATOR_314'if application else 'CALL'
            result,identity=self.invoke(kind,operands,source,i.offset,roles=roles,use_sources=operand_sources,definition=semantic)
            if actual_call is not None and operand_sources is not None:
                link_index=next(n for n,link in enumerate(self.op_links)if link.operation==identity)
                self.op_links[link_index]=replace(self.op_links[link_index],opcode=Opcode.CALL)
            self.stack.append(result[0])
        elif name in ('BINARY_OP','UNARY_NEGATIVE','UNARY_INVERT','UNARY_NOT'):
            refs=tuple(self.pop()for _ in range(2 if name=='BINARY_OP' else 1))[::-1]
            result,identity=self.invoke(name,refs,source,i.offset);self.stack.append(result[0])
        elif name=='POP_TOP':
            value=self.pop();identity=self.transition('FRAME_DISCARD',(value,),source,i.offset)
        elif name=='RETURN_VALUE':
            value=self.pop()
            if self.stack:raise ValueError('class normal return has leftover compiler stack')
            identity=self.transition('FRAME_EXIT_NORMAL',(*self.live(),value),source,i.offset)
            self.exit((value,),ExitKind.NORMAL,source);self.returned=True
        else:raise ValueError('unsupported class compiler instruction '+name)
        return identity

    def preflight(self,i):
        """Admission is read-only; a debt starts with the unmodified stack."""
        name,arg=i.opname,i.argval
        if name not in SUPPORTED:return 'class compiler/control protocol requires expansion'
        if name=='LOAD_ATTR'and i.arg&1:return 'method-lookup two-result ABI requires expansion'
        if name=='LOAD_FAST_BORROW'and arg not in self.cell_refs and arg not in self.free:
            return 'class compiler local borrow requires its scoped local interface'
        if name in ('LOAD_DEREF','LOAD_FROM_DICT_OR_DEREF','STORE_DEREF')and arg not in self.cell_refs and arg not in self.free:
            return 'class cell access lacks its original declared cell interface'
        if name=='MAKE_FUNCTION'and(not self.stack or self.stack[-1]not in self.code_refs):
            return 'function creation requires original compiler code-slot provenance'
        if name=='SET_FUNCTION_ATTRIBUTE':
            if len(self.stack)<2 or self.stack[-1]not in self.function_codes or i.arg not in (1,2,4,8,16):
                return 'function attribute requires its fresh factory/attribute protocol'
            if i.arg==8:
                expected=tuple(self.cell_refs.get(n,self.free.get(n))for n in self.function_codes[self.stack[-1]].co_freevars)
                if None in expected or self.tuple_items.get(self.stack[-2])!=expected:
                    return 'function closure requires exact ordered compiler cell provenance'
        if name in ('CALL','CALL_KW'):
            start=len(self.stack)-i.arg-(1 if name=='CALL_KW'else 0)-2
            if start<0 or self.stack[start]is None:return 'class CALL requires its exact callable/receiver ABI'
        return None

    def run(self):
        # This version is a linear compiler/source profile. Branches and
        # handlers stay a precise continuation instead of being executed.
        for i in self.instructions:
            before=tuple(self.stack)
            unsupported=self.preflight(i)
            if unsupported is not None:
                self.continuation(i,unsupported);break
            identity=self.handle(i)
            self.witnesses.append(ClassSuiteInstruction(i.offset,i.opname,i.arg,tuple(i.positions),
                self.source_for(i),identity,before,tuple(self.stack)))
            if self.returned:break
        if not self.returned:raise ValueError('class suite has no final continuation or normal return')
        graph=ProgramGraph(self.region,(Region(self.region,'static class suite',self.entry,
            tuple(Block(b,self.args[b],tuple(self.block_ops[b]))for b in self.blocks),
            (ExitPort('normal',ExitKind.NORMAL,(REF,self.state_type)),ExitPort('raise',ExitKind.RAISE,(REF,REF,self.state_type)))),),
            tuple(self.ops),tuple(self.values),(StateLocation(self.world,'coarse Python/external world',stability=Stability.UNKNOWN),),
            control_scopes=(ControlScope(self.scope,self.region,None,ControlScopeKind.FRAME,self.source,tuple(self.blocks)),),
            frame_roots=(SourceCompilationFrameRoot(self.scope,FrameKind.CLASS,self.evidence.to_reference(),self.interface),),
            state_address_refinements=tuple(self.addresses))
        frontiers=tuple(f for f in _frontiers(self.source,has_freevars=bool(self.free),has_class_cell='__class__'in self.cell_refs,
            has_decorators=bool(self.node.decorator_list)) if f.kind is not ClassFrontierKind.BODY_REQUIRED_EXPANSION)
        if self.remaining is not None:
            from scar.ir.program.class_entries import ClassEntryFrontier
            frontiers+=(ClassEntryFrontier(ClassFrontierKind.BODY_REQUIRED_EXPANSION,self.remaining.reason,self.remaining.statements[0].source if self.remaining.statements else self.source),)
        gaps=tuple(LoweringGap(GapKind.EFFECT_SUMMARY,f.source or self.source,f.kind.value+': '+f.detail)for f in frontiers)
        metadata=LoweringMetadata(self.definition.wire,self.snapshot,tuple(self.op_links),tuple(self.value_links),
                                 gaps=gaps,use_links=tuple(self.use_links))
        overlay=ClassSuiteOverlay(self.definition,self.semantic_definition.parent_id,self.source,self.evidence.to_reference(),
            self.scope,self.interface,_class_header_inputs(self.prepared,self.node),self.normal_mode,
            _class_scope_statements(self.prepared,self.node),tuple(self.witnesses),tuple(self.protocols),tuple(self.cells),
            tuple(self.constants),tuple(self.factories),self.remaining,frontiers,len(self.ops))
        return ClassEntryResult(graph,metadata,overlay,len(self.ops))

    def continuation(self,i,reason):
        operands=(*self.namespaces,*self.free.values(),*self.cell_refs.values(),*(v for v in self.stack if v is not None))
        results,identity=self.invoke('REQUIRED_CLASS_CONTINUATION',operands,self.source_for(i),i.offset)
        statements=_class_scope_statements(self.prepared,self.node)
        position=i.positions.lineno or self.node.lineno
        remaining=tuple(replace(row,order=n)for n,row in enumerate(
            row for row in statements if row.source.end_line>=position))
        self.remaining=ClassSuiteResidual(identity,i.offset,remaining,tuple(self.stack),reason)
        self.transition('FRAME_EXIT_NORMAL',(*self.live(),results[0]),self.source,i.offset)
        self.exit((results[0],),ExitKind.NORMAL,self.source);self.returned=True


def lower_class_suite(prepared,definition,source,*,code_evidence,max_operations=10000):
    from scar.analysis.source_language import supports_cpython_compiler
    if not supports_cpython_compiler(code_evidence):raise ValueError('class suite requires exact CPython 3.14.7 source compilation')
    result=ClassSuiteBuilder(prepared,definition,source,code_evidence,max_operations).run()
    from scar.analysis.source_class_body_validation import require_valid_class_suite
    require_valid_class_suite(prepared,definition,source,code_evidence=code_evidence,result=result)
    return result
