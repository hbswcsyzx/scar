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
    return ModuleSourceCensus(len(context.semantic.source_atoms), len(context.semantics.operations),
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


def lower_module_entry(context,selection,*,code_evidence,max_operations=10000):
    if type(max_operations) is not int or not 1<=max_operations<=100000:
        raise ValueError('module operation budget must be in [1,100000]')
    return ModuleBuilder(context,selection,code_evidence,max_operations).run_module()
