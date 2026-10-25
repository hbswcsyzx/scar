"""Opt-in mapping entry with a conservative, recursively refinable body Region.

The body interface consumes borrowed namespaces and the whole coarse world;
normal/raise worlds are separate. Its original SG/CFG and required-expansion
record remain present. No import/try/other statement execution is invented.
"""
from __future__ import annotations

import ast
from dataclasses import replace
import hashlib
import sys

from scar.analysis.program_lowering import _Unsupported, _key, _REF, LoweringMetadata, SourceProgram
from scar.analysis.structured_lowering import StructuredBuilder
from scar.analysis.source_language import SourceCodeEvidence
from scar.ir.program.ids import RegionID, OperationID, UseID
from scar.ir.program.model import (Behavior, ExitKind, Operation, ReferenceValue, StateVersionValue,
    Terminator, TerminatorKind, Use, UseRole)
from scar.ir.program.module_entries import (ModuleUnitSource, ModuleCodeWitness, ModuleEntryDeclaration,
    ModuleBodyOverlay, ModuleBodyStatus, MappingFrameEntry, ModuleFrontier, ModuleSourceCensus,
    ModuleOperationSource, ModuleValueSource, ModuleUseSource, ModuleProtocol, ModuleProtocolKind,
    ModuleEntryProfile, UnexpandedModuleBody)
from scar.ir.program.inventory import SourceContextDigest
from scar.ir.program.providers import ProviderArtifact
from scar.ir.program.source import SourceRole, GapKind
from scar.ir.program.structured import PythonProtocolKind
from scar.ir.record_codec import encode
from scar.ir.v2.semantic import OperationKind


def module_source_census(context):
    return ModuleSourceCensus(len(context.semantic.source_atoms), len(context.semantic.definitions),
                              len(context.control.nodes), len(context.control.edges))


def module_source_context(context):
    from scar.analysis.source_layers import _digest
    return SourceContextDigest(str(context.root), _digest(context.semantic.to_dict()),
        _digest(context.semantics.to_dict()), _digest(context.control.to_dict()))


def module_unit(context):
    matches = [row for row in context.semantic.modules.values() if row.path == str(context.path)]
    if len(matches) != 1:
        raise ValueError('module source requires one original module declaration')
    module = matches[0]
    definition = context.semantic.definitions.get(module.initializer)
    if definition is None or definition.kind is not OperationKind.MODULE:
        raise ValueError('module source initializer is not the existing MODULE definition')
    snapshot = context.semantics.sources[str(context.path)]
    if module.fingerprint != snapshot.fingerprint:
        raise ValueError('module declaration/source fingerprint differs')
    return ModuleUnitSource(snapshot, str(context.root), module.initializer)


def require_root_evidence(unit, evidence):
    if type(evidence) is not SourceCodeEvidence:
        raise TypeError('module construction requires existing read-only SourceCodeEvidence')
    if sys.implementation.name != 'cpython' or sys.version_info[:2] != (3,14):
        raise ValueError('mapping entry capability requires its CPython3.14 compiler context')
    link, witness = evidence.source_link, evidence.witness
    row = evidence.store.document['modules'].get(witness['module_key'])
    if (link.snapshot != unit.snapshot or evidence.captured.filename != unit.snapshot.path
            or witness['constant_path'] != [] or row is None or row['compile_key']['mode'] != 'exec'
            or row['module_descriptor'] != encode(evidence.captured) or row['snapshot'] != encode(unit.snapshot)):
        raise ValueError('module entry requires the exact exec compiler root, not a code-name match')
    import inspect
    suspended = inspect.CO_GENERATOR | inspect.CO_COROUTINE | inspect.CO_ASYNC_GENERATOR | inspect.CO_ITERABLE_COROUTINE
    if (evidence.code.co_freevars or evidence.code.co_cellvars or evidence.captured.parameters
            or evidence.code.co_flags & suspended):
        raise ValueError('mapping-root closure/formal/resumable environment is unsupported by this capability')
    manifest, artifact = evidence.store.receipt(), row['artifact']
    return ModuleCodeWitness(evidence.captured, link,
        ProviderArtifact(manifest['path'], manifest['sha256'], manifest['bytes'], 'scar.code-witness-store/1'),
        ProviderArtifact(str(evidence.store.root/artifact['path']), artifact['sha256'], artifact['bytes'],
                         'cpython.marshal/5'), witness['module_key'])


class ModuleBuilder(StructuredBuilder):
    def __init__(self, context, selection, evidence, max_operations):
        self.unit = module_unit(context)
        if type(selection) is not ModuleUnitSource or selection != self.unit:
            raise ValueError('selected module differs from the exact prepared source unit')
        if ('sha256:'+hashlib.sha256(context.text.encode()).hexdigest() != self.unit.snapshot.fingerprint
                or ast.dump(context.tree,include_attributes=True) != ast.dump(
                    ast.parse(context.text,filename=str(context.path)),include_attributes=True)):
            raise ValueError('prepared module AST/text differs from the original snapshot')
        self.declaration = ModuleEntryDeclaration(self.unit, require_root_evidence(self.unit,evidence))
        self.prepared_source, self.evidence = context,evidence
        self.module_frontiers = []
        super().__init__(context,self.unit.initializer.wire,max_operations=max_operations)
        self.wrapper_region = RegionID(_key('mapping-frame',self.unit.initializer.wire,self.unit.snapshot.fingerprint))
        self.body_region = RegionID(_key('mapping-unexpanded-body',self.unit.initializer.wire,self.unit.snapshot.fingerprint))
        self.function_definition = context.semantic.definitions[self.unit.initializer]
        self.locals=set();self.reference_candidates={};self.entry_references=()

    def source(self,node):
        return self.unit if isinstance(node,ast.Module) else super().source(node)

    def gap(self,kind,node,detail):
        self.module_frontiers.append(ModuleFrontier(self.source(node),kind.value,detail))

    def emit(self,cursor,operation,node,role,old=None):
        if self.operations_emitted >= self.max_operations:
            raise _Unsupported(GapKind.BUDGET,node,'module entry construction budget exceeded')
        self.operations_emitted+=1;self.operations.append(operation)
        self.block_operations[cursor.block].append(operation.id);self.operation_records[operation.id]=operation
        self.operation_links.append(ModuleOperationSource(operation.id,self.source(node),role,
            old.operation if old else None,old.opcode if old else None))

    def link_value(self,value,node,role,*,slot=None,semantic_value=None):
        link=ModuleValueSource(value.id,self.source(node),role,slot,semantic_value)
        if link not in self.value_link_set:self.value_links.append(link);self.value_link_set.add(link)

    def use(self,operation,value,node,role,index,*,semantic_value=None):
        record=self.values_by_id[value]
        use_role=(UseRole.REFERENCE if type(record) is ReferenceValue else
                  UseRole.STATE_CONTENT if type(record) is StateVersionValue else UseRole.DATA)
        use=Use(self.fresh(UseID,'module-use'),value,use_role)
        self.use_links.append(ModuleUseSource(operation,use.id,self.source(node),role,index,semantic_value))
        return use

    def protocol(self,operation,kind,node):
        self.protocols.append(ModuleProtocol(operation,kind,self.source(node)))

    def frame_exit_references(self,cursor,node,value):
        refs=super().frame_exit_references(cursor,node,value)
        refs.extend((reference,self.tree,'held-namespace') for reference in self.entry_references)
        return refs

    def body_exit(self,cursor,payload,kind):
        """Child Region completion is not another Python frame entry/exit."""
        identity=self.fresh(OperationID,'module-body-completion')
        uses=(self.use(identity,payload,self.tree,'body-payload',0),
              self.use(identity,cursor.state,self.tree,'body-post-world',0))
        self.emit(cursor,Operation(identity,'unexpanded-body-completion',(Behavior.CONTROL,),uses,
            terminator=Terminator(TerminatorKind.RETURN if kind is ExitKind.NORMAL else TerminatorKind.RAISE,
                exit=kind.value.lower(),values=tuple(use.id for use in uses))),self.tree,SourceRole.CONTROL)

    def run_module(self):
        # First build the child interface. It denotes all original statements;
        # no statement lowerer or target is invoked to populate its interior.
        self.function_context=self.body_region;self.function_blocks=[]
        child=self.new_block(self.tree,extra_types=(_REF,_REF,_REF))
        child_world=child.state;child_refs=self.block_arguments[child.block][:-1]
        normal,_,opaque=self.invoke_results(child,self.tree,
            tuple((value,self.tree,'borrowed-body-namespace',index,None) for index,value in enumerate(child_refs)),
            result_types=(),failure_handler=lambda cursor,error:self.body_exit(cursor,error,ExitKind.RAISE))
        self.protocol(opaque,ModuleProtocolKind.UNEXPANDED_BODY,self.tree)
        self.body_exit(normal,self.literal(self.tree,None),ExitKind.NORMAL)
        self.regions.append(replace(self.assemble_region(child_world),
            label='unexpanded module source body',parent=self.wrapper_region))
        body=UnexpandedModuleBody(self.unit,module_source_context(self.prepared_source),self.body_region,opaque)
        # The outer Region owns the one Python mapping frame retention rule.
        self.function_context=self.wrapper_region;self.function_blocks=[]
        cursor=self.new_block(self.tree,extra_types=(_REF,_REF,_REF))
        self.entry_references=self.block_arguments[cursor.block][:-1]
        self.interface=MappingFrameEntry(self.unit,self.wrapper_region,*self.entry_references,(),cursor.state)
        self.frame_transition(cursor,self.tree,
            tuple((value,self.tree,'borrowed-namespace') for value in self.entry_references),PythonProtocolKind.FRAME_ENTER)
        normal,payload,call=self.invoke(cursor,self.tree,
            tuple((value,self.tree,'body-entry-namespace',index,None) for index,value in enumerate(self.entry_references)))
        operation=replace(self.operation_records[call],callee=self.body_region)
        self.operations[self.operations.index(self.operation_records[call])]=operation;self.operation_records[call]=operation
        self.protocol(call,ModuleProtocolKind.INVOKE_MODULE_BODY,self.tree)
        self.finish_exit(normal,self.tree,payload,ExitKind.NORMAL)
        self.regions.append(self.assemble_region(self.interface.world))
        graph=self.make_graph()
        frontiers=(ModuleFrontier(self.unit,'REQUIRED_EXPANSION',
            'entire original module body remains unexpanded at its exact source context; all namespace operations/import/try/cleanup/effects remain OPEN'),
            ModuleFrontier(self.unit,'MODULE_INITIALIZER_BODY_NOT_RECOVERED',
            'entry and conservative body interface are connected; original statement internals have not been recovered'),
            ModuleFrontier(self.unit,'ENTRY_PROTOCOL_UNPROVEN',
            'actual namespace alias, builtins origin, import/__main__/exec entering protocol, sys.modules and activation binding are unobserved'))
        overlay=ModuleBodyOverlay(self.declaration,ModuleBodyStatus.PARTIAL,
            module_source_census(self.prepared_source),self.interface,frontiers,self.operations_emitted,
            tuple(self.operation_links),tuple(self.value_links),tuple(self.use_links),tuple(self.protocols),
            unexpanded_body=body)
        result=SourceProgram(graph,LoweringMetadata(self.entry,self.snapshot),self.semantic,self.semantics,self.control,
            ModuleEntryProfile.EXEC_MAPPING_314_V1,module=overlay)
        from scar.analysis.source_module_validation import require_valid_module_program
        require_valid_module_program(result,source_texts={str(self.prepared_source.path):self.prepared_source.text},
                                     code_evidence=self.evidence,max_operations=self.max_operations)
        return result


def lower_module_entry(context,selection,*,code_evidence,max_operations=10000,profile=ModuleEntryProfile.EXEC_MAPPING_314_V1):
    if type(max_operations) is not int or not 1<=max_operations<=100000:
        raise ValueError('module operation budget must be in [1,100000]')
    from scar.ir.program.module_entries import ModuleBodyExpansionProfile,FrameBodyProfile
    if profile is FrameBodyProfile.STRUCTURED_MAPPING_314_V1:
        return StructuredModuleBuilder(context,selection,code_evidence,max_operations).run_module()
    if profile is ModuleBodyExpansionProfile.IMPORT_PREFIX_314_V1:
        return ModulePrefixBuilder(context,selection,code_evidence,max_operations).run_module()
    if profile is not ModuleEntryProfile.EXEC_MAPPING_314_V1:
        raise ValueError('unsupported explicit module entry/body capability')
    return ModuleBuilder(context,selection,code_evidence,max_operations).run_module()


def _module_statement_ref(context,node):
    matches=[atom.reference for atom in context.semantic.source_atoms.values()
        if atom.kind==type(node).__name__ and atom.reference.path==str(context.path)
        and (atom.reference.start_line,atom.reference.end_line,atom.reference.start_column,atom.reference.end_column)
        ==(node.lineno,node.end_lineno,node.col_offset,node.end_col_offset)]
    if len(matches)!=1:raise ValueError('module statement has no unique original SourceAtom')
    return matches[0]


def first_import_selection(context,code_evidence=None):
    """Mechanical first statement, original SG/CFG and an exact residual suffix."""
    from scar.ir.control_flow_v2 import SuiteKind,NodeKind,InsertionKind
    from scar.ir.program.module_entries import ModuleStatementSlice
    unit=module_unit(context);nodes=context.tree.body
    if (len(nodes)<2 or not isinstance(nodes[0],ast.Import) or len(nodes[0].names)!=1
            or '.' in nodes[0].names[0].name):
        raise ValueError('IMPORT_PREFIX_SHAPE_UNSUPPORTED: first stmt must be one plain import with a nonempty tail')
    node=nodes[0];alias=node.names[0];source=_module_statement_ref(context,node)
    definitions=[row for row in context.semantic.definitions.values()
        if row.code_id==source.atom_id.wire and row.parent_id==unit.initializer
        and row.source_file==unit.snapshot.path and row.kind is OperationKind.IMPORT
        and row.metadata.get('requested_module')==alias.name and row.metadata.get('symbol') is None]
    if len(definitions)!=1 or len(definitions[0].output_slots)!=1:
        raise ValueError('first import has no unique original SG definition/output')
    definition=definitions[0]
    suites=[row for row in context.control.suites.values()
        if row.kind is SuiteKind.MODULE and row.scope==unit.initializer and row.parent is None]
    if len(suites)!=1:raise ValueError('module has no unique original source MODULE suite')
    suite=suites[0]
    cfg=[row for row in context.control.nodes.values() if row.suite==suite.id
         and row.kind is NodeKind.STATEMENT and row.source==source and definition.id in row.operations]
    if len(cfg)!=1:raise ValueError('first import has no unique original CFG statement')
    remaining=tuple(_module_statement_ref(context,child) for child in nodes[1:])
    before=[point for point in context.control.insertions.values()
            if point.kind is InsertionKind.BEFORE and point.suite==suite.id and point.source==remaining[0]]
    if len(before)!=1:raise ValueError('remaining statements have no unique original BEFORE boundary')
    anchor=context.control.nodes.get(before[0].anchor)
    if anchor is None or anchor.source!=remaining[0] or anchor.scope!=unit.initializer:
        raise ValueError('remaining source-control anchor differs')
    subject=ModuleStatementSlice(unit,module_source_context(context),remaining,suite.id,before[0].id)
    offsets=None
    if code_evidence is not None:
        require_root_evidence(unit,code_evidence)
        import dis
        instructions=list(dis.get_instructions(code_evidence.code,adaptive=False,show_caches=False))
        candidates=[i for i,ins in enumerate(instructions) if ins.opname=='IMPORT_NAME']
        if not candidates:raise ValueError('readonly root compiler has no first import')
        i=candidates[0]
        if i<2 or i+1>=len(instructions):raise ValueError('readonly first import instruction window incomplete')
        level,fromlist,imp,store=instructions[i-2:i+2]
        if (level.opname not in ('LOAD_CONST','LOAD_SMALL_INT') or type(level.argval) is not int or level.argval!=0
                or fromlist.opname!='LOAD_CONST' or fromlist.argval is not None or imp.argval!=alias.name
                or store.opname!='STORE_NAME' or store.argval!=(alias.asname or alias.name)):
            raise ValueError('readonly whole-root import/STORE_NAME operands or order differ')
        offsets=(imp.offset,store.offset)
    return node,source,definition.id,cfg[0].id,subject,offsets


class ModulePrefixBuilder(ModuleBuilder):
    """One source import protocol and attempted store, then exact opaque suffix."""
    def protocol(self,operation,kind,node):
        from scar.ir.program.module_entries import ModulePrefixProtocol
        self.protocols.append(ModulePrefixProtocol(operation,kind,self.source(node)))

    def _start_region(self,identity):
        self.function_context=identity;self.function_blocks=[]
        cursor=self.new_block(self.tree,extra_types=(_REF,_REF,_REF))
        return cursor,self.block_arguments[cursor.block][:-1]

    def _callee_invoke(self,cursor,callee,refs,kind):
        normal,result,identity=self.invoke(cursor,self.tree,
            tuple((value,self.tree,'namespace',index,None) for index,value in enumerate(refs)),
            failure_handler=lambda failed,error:self.body_exit(failed,error,ExitKind.RAISE))
        original=self.operation_records[identity];operation=replace(original,callee=callee)
        self.operations[self.operations.index(original)]=operation;self.operation_records[identity]=operation
        self.protocol(identity,kind,self.tree)
        return normal,result,identity

    def run_module(self):
        from scar.ir.program.module_entries import (ModulePrefixProtocolKind as K,ModuleImportPrefix,
            UnexpandedModuleSlice,ModulePrefixOverlay,ModuleBodyExpansionProfile)
        from scar.ir.program.state_addresses import (StateAddressRefinement,InvokeStateOperand,AddressEffect,
            ReferenceOwner,NamespaceKey,AddressCoverage)
        from scar.ir.program.model import AccessMode
        node,source,sg,cfg,subject,offsets=first_import_selection(self.prepared_source,self.evidence)
        prefix_region=RegionID(_key('module-import-prefix',self.unit.initializer.wire,source.atom_id.wire))
        remaining_region=RegionID(_key('module-statement-suffix',self.unit.initializer.wire,
            *(ref.atom_id.wire for ref in subject.statements)))
        addresses=[]
        # Import is a computation Region, not a Python function/frame. Its
        # primitive encompasses saved-builtins lookup and fast/custom dispatch.
        cursor,refs=self._start_region(prefix_region);initial=cursor.state
        values=(refs[2],refs[1],refs[0],self.literal(node,node.names[0].name),
                self.literal(node,0),self.literal(node,None),self.literal(node,'__import__'))
        normal,imported,import_op=self.invoke(cursor,node,
            tuple((value,node,'import-input',index,None) for index,value in enumerate(values)),
            failure_handler=lambda failed,error:self.body_exit(failed,error,ExitKind.RAISE))
        self.protocol(import_op,K.IMPORT_NAME_314,node)
        op=self.operation_records[import_op]
        addresses.append(StateAddressRefinement(InvokeStateOperand(import_op,op.uses[-1].id),
            (AddressEffect(ReferenceOwner(op.uses[0].id),(NamespaceKey(op.uses[6].id),),AccessMode.READ),),
            AddressCoverage.PARTIAL))
        self.body_exit(normal,imported,ExitKind.NORMAL)
        self.regions.append(replace(self.assemble_region(initial),label='first source Import interface',parent=self.body_region))
        # Opaque remainder denotes exactly module.body[1:], never the whole unit.
        cursor,refs=self._start_region(remaining_region);initial=cursor.state
        normal,_,opaque=self.invoke_results(cursor,self.tree,
            tuple((value,self.tree,'residual-namespace',index,None) for index,value in enumerate(refs)),
            result_types=(),failure_handler=lambda failed,error:self.body_exit(failed,error,ExitKind.RAISE))
        self.protocol(opaque,K.UNEXPANDED_SLICE,self.tree)
        self.body_exit(normal,self.literal(self.tree,None),ExitKind.NORMAL)
        self.regions.append(replace(self.assemble_region(initial),label='exact unexpanded module statement suffix',parent=self.body_region))
        # Refine the same existing body Region. The store opcode owns its stack
        # input across its attempted mapping write, consuming it on BOTH exits.
        # This is not a claim of object reclamation, successful content, or free.
        cursor,refs=self._start_region(self.body_region);initial=cursor.state
        normal,imported,prefix_call=self._callee_invoke(cursor,prefix_region,refs,K.INVOKE_IMPORT_PREFIX)
        key=self.literal(node,node.names[0].asname or node.names[0].name)
        store_inputs=(refs[0],key,imported)
        normal,_,store=self.invoke(normal,node,
            tuple((value,node,'store-input',index,None) for index,value in enumerate(store_inputs)),result_type=None,
            failure_handler=lambda failed,error:self.body_exit(failed,error,ExitKind.RAISE))
        self.protocol(store,K.STORE_NAME_314,node)
        op=self.operation_records[store]
        addresses.append(StateAddressRefinement(InvokeStateOperand(store,op.uses[-1].id),
            (AddressEffect(ReferenceOwner(op.uses[0].id),(NamespaceKey(op.uses[1].id),),AccessMode.WRITE),),
            AddressCoverage.PARTIAL))
        normal,payload,residual_call=self._callee_invoke(normal,remaining_region,refs,K.INVOKE_REMAINING)
        self.body_exit(normal,payload,ExitKind.NORMAL)
        self.regions.append(replace(self.assemble_region(initial),label='source module body with first import prefix',parent=self.wrapper_region))
        # Unchanged mapping-frame ABI and conditional retention, outside all
        # computational child Regions. No child activation is invented.
        cursor,refs=self._start_region(self.wrapper_region);self.entry_references=refs
        self.interface=MappingFrameEntry(self.unit,self.wrapper_region,*refs,(),cursor.state)
        self.frame_transition(cursor,self.tree,tuple((value,self.tree,'borrowed-namespace') for value in refs),PythonProtocolKind.FRAME_ENTER)
        normal,payload,call=self.invoke(cursor,self.tree,
            tuple((value,self.tree,'namespace',index,None) for index,value in enumerate(refs)))
        original=self.operation_records[call];operation=replace(original,callee=self.body_region)
        self.operations[self.operations.index(original)]=operation;self.operation_records[call]=operation
        self.protocol(call,ModuleProtocolKind.INVOKE_MODULE_BODY,self.tree)
        self.finish_exit(normal,self.tree,payload,ExitKind.NORMAL)
        self.regions.append(self.assemble_region(self.interface.world))
        graph=replace(self.make_graph(),state_address_refinements=tuple(addresses))
        prefix=ModuleImportPrefix(source,sg,cfg,prefix_region,import_op,store,*offsets)
        remaining=UnexpandedModuleSlice(subject,remaining_region,opaque)
        frontiers=(ModuleFrontier(self.unit,'REQUIRED_EXPANSION','the exact remaining source statement suffix is unexpanded'),
            ModuleFrontier(source,'IMPORT_INTERNALS_REQUIRED_EXPANSION','saved-builtins mapping lookup/importer dispatch/import internals retain arbitrary effects and may not complete'),
            ModuleFrontier(source,'NAMESPACE_CONTENT_UNPROVEN','STORE_NAME is an attempted protocol write; normal does not prove a stored value or object reclamation'),
            ModuleFrontier(self.unit,'ENTRY_PROTOCOL_UNPROVEN','runtime namespace alias, entry mode, sys.modules, ModuleObject and activation binding remain unobserved'),
            ModuleFrontier(self.unit,'MODULE_INITIALIZER_BODY_NOT_RECOVERED','one original statement interface is expanded; residual statements/outer cleanup/effects remain OPEN'))
        overlay=ModulePrefixOverlay(self.declaration,module_source_census(self.prepared_source),self.interface,
            self.body_region,prefix,remaining,frontiers,self.operations_emitted,tuple(self.operation_links),
            tuple(self.value_links),tuple(self.use_links),tuple(self.protocols))
        result=SourceProgram(graph,LoweringMetadata(self.entry,self.snapshot),self.semantic,self.semantics,self.control,
            ModuleBodyExpansionProfile.IMPORT_PREFIX_314_V1,module=overlay)
        from scar.analysis.source_module_validation import require_valid_module_prefix
        require_valid_module_prefix(result,source_texts={str(self.prepared_source.path):self.prepared_source.text},
                                    code_evidence=self.evidence,max_operations=self.max_operations)
        return result


def frame_statement_slice(context, owner, field, nodes):
    """A source collection with an original boundary, or its explicit absence."""
    from scar.ir.program.module_entries import FrameStatementSlice,SourceControlBoundary
    from scar.ir.control_flow_v2 import InsertionKind
    unit=module_unit(context)
    refs=tuple(_module_statement_ref(context,node) for node in nodes)
    if not refs:raise ValueError('frame statement slice must be nonempty')
    matches=[point for point in context.control.insertions.values()
        if point.kind is InsertionKind.BEFORE and point.source==refs[0]]
    if len(matches)>1:raise ValueError('frame source boundary is ambiguous')
    point=matches[0] if matches else None
    return FrameStatementSlice(unit,module_source_context(context),owner,field,refs,
        SourceControlBoundary.EXACT_OLD_ANCHOR if point else SourceControlBoundary.NO_EXACT_OLD_ANCHOR,
        point.suite if point else None,point.id if point else None)


def mapping_prefix_selection(context, evidence):
    """Maximal contiguous supported statements; no workload/name allowlist."""
    unit=module_unit(context);require_root_evidence(unit,evidence)
    import dis
    instructions=tuple(dis.get_instructions(evidence.code,adaptive=False,show_caches=False))
    def positioned(node,opnames):
        span=(node.lineno,node.end_lineno,node.col_offset,node.end_col_offset)
        return [row for row in instructions if row.opname in opnames and tuple(row.positions)==span]
    def expression(node):
        try:
            source=_module_statement_ref(context,node)
        except ValueError:
            return False
        definitions=[row for row in context.semantic.definitions.values()
            if row.code_id==source.atom_id.wire and source.atom_id in row.source_atoms
            and row.output_slots and row.metadata.get('role')!='binding'
            and row.kind not in (OperationKind.FUNCTION,OperationKind.METHOD)]
        if len(definitions)!=1:return False
        if isinstance(node,ast.Name):
            return len([row for row in positioned(node,('LOAD_NAME',)) if row.argval==node.id])==1
        if isinstance(node,ast.Constant):
            import math
            return (node.value is None or type(node.value) in (bool,int,str)
                or type(node.value) is float and math.isfinite(node.value))
        if isinstance(node,ast.Tuple):
            if len(positioned(node,('LOAD_CONST',)))==1:
                return type(positioned(node,('LOAD_CONST',))[0].argval) is tuple
            return all(expression(child) for child in node.elts)
        if isinstance(node,ast.List):return all(expression(child) for child in node.elts)
        if isinstance(node,ast.Attribute):return not (node.attr.startswith('__') and not node.attr.endswith('__')) and expression(node.value)
        if isinstance(node,ast.Subscript):return not isinstance(node.slice,ast.Slice) and expression(node.value) and expression(node.slice)
        if isinstance(node,ast.BinOp):return expression(node.left) and expression(node.right)
        if isinstance(node,ast.UnaryOp):return expression(node.operand)
        if isinstance(node,ast.Compare):return len(node.ops)==1 and expression(node.left) and expression(node.comparators[0])
        if isinstance(node,ast.Call):return (not any(isinstance(arg,ast.Starred) for arg in node.args)
            and all(keyword.arg is not None for keyword in node.keywords)
            and all(expression(child) for child in (node.func,*node.args,*(keyword.value for keyword in node.keywords))))
        return False
    def target(node):return isinstance(node,ast.Name) and len([row for row in positioned(node,('STORE_NAME',)) if row.argval==node.id])==1
    def statement(node):
        if isinstance(node,ast.Import):return bool(node.names) and all('.' not in alias.name for alias in node.names)
        if isinstance(node,ast.ImportFrom):return bool(node.names) and all(alias.name!='*' for alias in node.names)
        if isinstance(node,ast.Assign):return len(node.targets)==1 and target(node.targets[0]) and expression(node.value)
        if isinstance(node,ast.Expr):return expression(node.value)
        if isinstance(node,ast.For):return target(node.target) and expression(node.iter) and all(statement(child) for child in (*node.body,*node.orelse))
        return isinstance(node,ast.Pass)
    end=0
    for node in context.tree.body:
        if not statement(node):break
        end+=1
    return tuple(context.tree.body[:end]),tuple(context.tree.body[end:])


class StructuredModuleBuilder(ModuleBuilder):
    """One actual mapping frame; existing expression/loop rules, no fast locals."""
    def __init__(self,context,selection,evidence,max_operations):
        super().__init__(context,selection,evidence,max_operations)
        from scar.analysis.source_language import SourceLanguageOptions
        from scar.ir.program.source_language import SourceLanguageCapability
        from scar.ir.program.ids import ControlScopeID
        self.language_options=SourceLanguageOptions((SourceLanguageCapability.SLICE_KEYS,),evidence)
        self.instructions=None;self.address_refinements=[];self.statement_expansions=[]
        self.root_scope=ControlScopeID(_key('module-frame-scope',self.unit.initializer.wire,self.unit.snapshot.fingerprint))
        self.frame_region=RegionID(_key('module-structured-frame',self.unit.initializer.wire,self.unit.snapshot.fingerprint))
        self.prefix_nodes,self.remaining_nodes=mapping_prefix_selection(context,evidence)

    def old_operation(self,node):
        rows=self.old_by_atom.get(self.source(node).atom_id,())
        if len(rows)>1:raise _Unsupported(GapKind.SOURCE_MAPPING,node,'module expression has ambiguous computational records')
        return rows[0] if rows else None

    def literal(self,node,value):
        from scar.ir.program.model import LiteralOrigin
        from scar.ir.program.ids import ValueID
        record=ReferenceValue(self.fresh(ValueID,'mapping-literal'),self.function_context,LiteralOrigin(value),targets=())
        self.add_value(record);old=self.old_operation(node) if isinstance(node,ast.Constant) else None
        self.link_value(record,node,SourceRole.EXPRESSION,semantic_value=old.result if old else None)
        return record.id

    def protocol(self,operation,kind,node):
        from scar.ir.program.module_entries import FrameBodyProtocol
        self.protocols.append(FrameBodyProtocol(operation,kind,self.source(node)))

    def _addresses(self,operation_id,effects):
        from scar.ir.program.state_addresses import StateAddressRefinement,InvokeStateOperand,AddressCoverage
        operation=self.operation_records[operation_id]
        self.address_refinements.append(StateAddressRefinement(InvokeStateOperand(operation_id,operation.uses[-1].id),tuple(effects),AddressCoverage.PARTIAL))

    def read_source_name(self,node,cursor,old=None):
        from scar.ir.program.module_entries import FrameBodyProtocolKind as K
        from scar.ir.program.state_addresses import AddressEffect,ReferenceOwner,NamespaceKey
        from scar.ir.program.model import AccessMode
        key=self.literal(node,node.id)
        cursor,value,identity=self.invoke(cursor,node,tuple((ref,node,role,index,None)
            for index,(ref,role) in enumerate(zip((*self.entry_references,key),('locals-owner','globals-owner','saved-builtins-owner','namespace-key')))),old=old)
        self.protocol(identity,K.LOAD_NAME_314,node)
        operation=self.operation_records[identity]
        self._addresses(identity,tuple(AddressEffect(ReferenceOwner(operation.uses[index].id),
            (NamespaceKey(operation.uses[3].id),),AccessMode.READ) for index in range(3)))
        if old is None:self.associate_expression(identity,node,None)
        self.gap(GapKind.EFFECT_SUMMARY,node,'LOAD_NAME: missing-only locals/globals/saved-builtins fallback; mapping effects/content/activation remain open')
        return cursor,value

    def store_name(self,node,name,value,cursor):
        from scar.ir.program.module_entries import FrameBodyProtocolKind as K
        from scar.ir.program.state_addresses import AddressEffect,ReferenceOwner,NamespaceKey
        from scar.ir.program.model import AccessMode
        key=self.literal(node,name)
        cursor,_,identity=self.invoke(cursor,node,((self.entry_references[0],node,'locals-owner',0,None),
            (key,node,'namespace-key',0,None),(value,node,'assigned-reference',0,None)),result_type=None)
        self.protocol(identity,K.STORE_NAME_314,node);operation=self.operation_records[identity]
        self._addresses(identity,(AddressEffect(ReferenceOwner(operation.uses[0].id),
            (NamespaceKey(operation.uses[1].id),),AccessMode.WRITE),))
        self.gap(GapKind.EFFECT_SUMMARY,node,'STORE_NAME is a partial mapping attempt; normal completion grants no stored-content or disjointness proof')
        return cursor

    def store(self,target,value,cursor):
        if not isinstance(target,ast.Name):raise _Unsupported(GapKind.UNSUPPORTED_SYNTAX,target,'mapping profile supports only compiler STORE_NAME targets')
        return self.store_name(target,target.id,value,cursor)

    def ordered_expression_inputs(self,node,children,old):
        if old is not None:return super().ordered_expression_inputs(node,children,old)
        from scar.analysis.source_heap_lowering import _source_definition
        _source_definition(self,node)
        if isinstance(node,ast.Call):
            roles=[('callee',0)]+[('argument',i) for i in range(len(node.args))]+[('keyword:'+kw.arg,i) for i,kw in enumerate(node.keywords)]
        elif isinstance(node,ast.Attribute):roles=[('receiver',0)]
        elif isinstance(node,ast.Subscript):roles=[('receiver',0),('index',0)]
        else:roles=[('operand',i) for i in range(len(children))]
        return None,tuple((child,role,index,None) for child,(role,index) in zip(children,roles))

    def associate_expression(self,operation,node,old):
        if old is not None:return
        from scar.analysis.source_heap_lowering import _source_definition,_associate
        from scar.ir.semantics_v2 import Opcode
        definition=_source_definition(self,node)
        opcode=(Opcode.READ if isinstance(node,ast.Name) else Opcode.CALL if isinstance(node,ast.Call)
            else Opcode.ATTRIBUTE if isinstance(node,ast.Attribute) else Opcode.INDEX if isinstance(node,ast.Subscript)
            else Opcode.BUILD_TUPLE if isinstance(node,ast.Tuple) else Opcode.BUILD_LIST if isinstance(node,ast.List)
            else Opcode.OPAQUE)
        if isinstance(node,(ast.BinOp,ast.UnaryOp)):
            from scar.analysis.source_semantics_v2 import _BINARY,_UNARY
            opcode=getattr(Opcode,(_BINARY if isinstance(node,ast.BinOp) else _UNARY).get(type(node.op),'OPAQUE'))
        _associate(self,operation,node,definition,opcode)

    def expr(self,node,cursor):
        from scar.analysis.environment_lowering import dispatch_source_expression
        if isinstance(node,ast.Tuple):
            from scar.analysis.source_slice_lowering import _instructions,_constant
            if any(row.opname=='LOAD_CONST' and type(row.argval) is tuple for row in _instructions(self,node)):
                return _constant(self,node,cursor)
        result=dispatch_source_expression(self,node,cursor)
        return super().expr(node,cursor) if result is NotImplemented else result

    def condition(self,node,cursor):
        from scar.analysis.environment_lowering import dispatch_source_condition
        result=dispatch_source_condition(self,node,cursor)
        return super().condition(node,cursor) if result is NotImplemented else result

    def import_statement(self,node,cursor):
        from scar.ir.program.module_entries import FrameBodyProtocolKind as K
        from scar.ir.program.state_addresses import AddressEffect,ReferenceOwner,NamespaceKey
        from scar.ir.program.model import AccessMode
        from scar.analysis.source_slice_lowering import _constant
        imports=node.names if isinstance(node,ast.Import) else (None,)
        for alias in imports:
            name=alias.name if alias is not None else (node.module or '')
            requested=self.literal(node,name);level=self.literal(node,0 if alias is not None else node.level)
            if alias is None:cursor,fromlist=_constant(self,node,cursor)
            else:fromlist=self.literal(node,None)
            lookup=self.literal(node,'__import__')
            inputs=(*reversed(self.entry_references),requested,level,fromlist,lookup)
            cursor,imported,identity=self.invoke(cursor,node,tuple((value,node,'import-input',index,None) for index,value in enumerate(inputs)))
            self.protocol(identity,K.IMPORT_NAME_314,node);operation=self.operation_records[identity]
            self._addresses(identity,(AddressEffect(ReferenceOwner(operation.uses[0].id),
                (NamespaceKey(operation.uses[6].id),),AccessMode.READ),))
            if alias is not None:
                cursor=self.store_name(node,alias.asname or alias.name,imported,cursor)
            else:
                self.frame_transition(cursor,node,((imported,node,'import-from-owner'),),PythonProtocolKind.FRAME_HOLD_TEMPORARY)
                self.active_temporaries.append(imported)
                for member in node.names:
                    key=self.literal(node,member.name)
                    cursor,value,identity=self.invoke(cursor,node,((imported,node,'from-owner',0,None),(key,node,'from-key',0,None)))
                    self.protocol(identity,K.IMPORT_FROM_314,node)
                    cursor=self.store_name(node,member.asname or member.name,value,cursor)
                self.active_temporaries.pop()
                self.frame_transition(cursor,node,((imported,node,'import-from-owner'),),PythonProtocolKind.FRAME_RELEASE_TEMPORARY)
            self.gap(GapKind.EFFECT_SUMMARY,node,'import lookup/call/from access internals and runtime objects/effects require expansion')
        return cursor

    def statements(self,nodes,cursor):
        from scar.ir.program.module_entries import FrameStatementExpansion,StatementSequenceField as F
        for node in nodes:
            if cursor is None:raise _Unsupported(GapKind.CONTROL_FLOW,node,'mapping prefix lost its normal continuation')
            start=len(self.operations);entry=cursor.block
            if isinstance(node,(ast.Import,ast.ImportFrom)):cursor=self.import_statement(node,cursor)
            else:cursor=super().statements((node,),cursor)
            children=tuple(frame_statement_slice(self.prepared_source,self.source(node),field,getattr(node,name))
                for name,field in (('body',F.BODY),('orelse',F.ORELSE)) if isinstance(node,ast.For) and getattr(node,name))
            self.statement_expansions.append(FrameStatementExpansion(self.source(node),self.frame_region,entry,cursor.block if cursor else None,
                tuple(operation.id for operation in self.operations[start:]),children))
        return cursor

    def run_module(self):
        from scar.ir.program.module_entries import (FrameBodyProfile,StructuredFrameBodyOverlay,
            FrameBodyProtocolKind as K,StatementSequenceField as F,UnexpandedFrameSlice)
        from scar.ir.program.source_subjects import FrameRoot,FrameKind,MappingFramePorts
        from scar.ir.program.control import ControlScope,ControlScopeKind
        remaining=None
        if self.remaining_nodes:
            self.function_context=RegionID(_key('module-exact-suffix',self.unit.initializer.wire,
                _module_statement_ref(self.prepared_source,self.remaining_nodes[0]).atom_id.wire))
            self.function_blocks=[];child=self.new_block(self.tree,extra_types=(_REF,_REF,_REF));child_world=child.state
            refs=self.block_arguments[child.block][:-1]
            normal,_,identity=self.invoke_results(child,self.tree,tuple((value,self.tree,'borrowed-slice-namespace',i,None) for i,value in enumerate(refs)),
                result_types=(),failure_handler=lambda failed,error:self.body_exit(failed,error,ExitKind.RAISE))
            self.protocol(identity,K.UNEXPANDED_SLICE,self.tree);self.body_exit(normal,self.literal(self.tree,None),ExitKind.NORMAL)
            self.regions.append(replace(self.assemble_region(child_world),label='exact required module statement slice',parent=self.frame_region))
            remaining=UnexpandedFrameSlice(frame_statement_slice(self.prepared_source,self.unit,F.BODY,self.remaining_nodes),self.function_context,identity)
        self.function_context=self.frame_region;self.function_blocks=[]
        cursor=self.new_block(self.tree,extra_types=(_REF,_REF,_REF));entry_world=cursor.state
        self.entry_references=self.block_arguments[cursor.block][:-1]
        abi=MappingFramePorts(*self.entry_references,(),entry_world)
        self.frame_transition(cursor,self.tree,tuple((value,self.tree,'borrowed-namespace') for value in self.entry_references),PythonProtocolKind.FRAME_ENTER)
        cursor=self.statements(self.prefix_nodes,cursor)
        if remaining is not None:
            cursor,payload,identity=self.invoke(cursor,self.tree,tuple((value,self.tree,'slice-namespace',i,None) for i,value in enumerate(self.entry_references)))
            operation=replace(self.operation_records[identity],callee=remaining.region)
            self.operations[self.operations.index(self.operation_records[identity])]=operation;self.operation_records[identity]=operation
            self.protocol(identity,K.INVOKE_REMAINING,self.tree)
        else:payload=self.literal(self.tree,None)
        self.finish_exit(cursor,self.tree,payload,ExitKind.NORMAL)
        self.regions.append(self.assemble_region(entry_world))
        graph=replace(self.make_graph(),root=self.frame_region,state_address_refinements=tuple(self.address_refinements),
            control_scopes=(ControlScope(self.root_scope,self.frame_region,None,ControlScopeKind.FRAME,self.unit,tuple(self.function_blocks)),),
            frame_roots=(FrameRoot(self.root_scope,FrameKind.MODULE,self.evidence.captured,abi),))
        self.module_frontiers.extend((ModuleFrontier(self.unit,'ENTRY_PROTOCOL_UNPROVEN','declared source ABI is not an actual namespace/activation/import binding'),
            ModuleFrontier(self.unit,'NAMESPACE_CONTENT_UNPROVEN','mapping access attempts do not establish stored content or alias/effect completeness')))
        if remaining is not None:self.module_frontiers.append(ModuleFrontier(self.source(self.remaining_nodes[0]),'REQUIRED_EXPANSION',
            'exact remaining statement collection starts at unsupported '+type(self.remaining_nodes[0]).__name__))
        overlay=StructuredFrameBodyOverlay(self.declaration,module_source_census(self.prepared_source),self.root_scope,
            frame_statement_slice(self.prepared_source,self.unit,F.BODY,self.prefix_nodes) if self.prefix_nodes else None,
            tuple(self.statement_expansions),remaining,tuple(self.module_frontiers),self.operations_emitted,
            tuple(self.operation_links),tuple(self.value_links),tuple(self.use_links),tuple(self.protocols),tuple(self.loops),tuple(self.language_constants))
        result=SourceProgram(graph,LoweringMetadata(self.entry,self.snapshot),self.semantic,self.semantics,self.control,
            FrameBodyProfile.STRUCTURED_MAPPING_314_V1,module=overlay)
        from scar.analysis.source_module_validation import require_valid_structured_module_program
        require_valid_structured_module_program(result,source_texts={str(self.prepared_source.path):self.prepared_source.text},code_evidence=self.evidence,max_operations=self.max_operations)
        return result
