"""Codec/API only, deliberately synthetic IDs: no source/compiler/runtime proof."""
from pathlib import Path
from dataclasses import fields
import ast,hashlib,json
from scar.ir.program.module_entries import *
from scar.ir.program.call_edges import CapturedCode,CodeSourceLink,CallLinkStatus
from scar.ir.program.providers import ProviderArtifact
from scar.ir.program.inventory import SourceContextDigest
from scar.ir.program.source import LoweringMetadata
from scar.ir.semantics_v2 import SourceSnapshot
from scar.ir.v2.common import SourceReference
from scar.ir.v2.ids import SourceAtomID,OperationDefinitionID,ControlFlowSuiteID,ControlFlowNodeID,InsertionPointID
from scar.ir.program.ids import RegionID,OperationID,ValueID
from scar.analysis.program_lowering import SourceProgram
root=Path(__file__).resolve().parents[4];base=Path(__file__).resolve().parent
fingerprint='sha256:'+'1'*64;snapshot=SourceSnapshot('/fixture/module.py',fingerprint,'utf-8','3.14')
unit=ModuleUnitSource(snapshot,'/fixture',OperationDefinitionID('fixture-init'))
source=SourceReference(SourceAtomID('fixture-first'),snapshot.path,fingerprint,1,1,0,8)
tail=SourceReference(SourceAtomID('fixture-tail'),snapshot.path,fingerprint,2,2,0,4)
context=SourceContextDigest('/fixture','2'*64,'3'*64,'4'*64)
subject=ModuleStatementSlice(unit,context,(tail,),ControlFlowSuiteID('fixture-suite'),InsertionPointID('fixture-before'))
code=CapturedCode('pycode-v2:'+'5'*64,snapshot.path,'<module>',1,0,())
archive=ProviderArtifact('/fixture/manifest.json','6'*64,1,'fixture-only')
witness=ModuleCodeWitness(code,CodeSourceLink(code.key,CallLinkStatus.VERIFIED,snapshot),archive,archive,'7'*64)
declaration=ModuleEntryDeclaration(unit,witness)
interface=MappingFrameEntry(unit,RegionID('fixture-entry'),ValueID('l'),ValueID('g'),ValueID('b'),(),ValueID('w'))
prefix=ModuleImportPrefix(source,OperationDefinitionID('fixture-import'),ControlFlowNodeID('fixture-cfg'),
 RegionID('fixture-prefix'),OperationID('fixture-import-op'),OperationID('fixture-store-op'),4,6)
remaining=UnexpandedModuleSlice(subject,RegionID('fixture-rest'),OperationID('fixture-opaque'))
overlay=ModulePrefixOverlay(declaration,ModuleSourceCensus(2,2,3,2),interface,RegionID('fixture-body'),prefix,remaining,
 (ModuleFrontier(unit,'REQUIRED_EXPANSION','fixture only'),),1,(),(),(),())
wire=encode_module_prefix(overlay);assert decode_module_prefix(wire)==overlay
summary=SourceProgram(None,LoweringMetadata(unit.initializer.wire,snapshot),None,None,None,
 ModuleBodyExpansionProfile.IMPORT_PREFIX_314_V1,module=overlay).summary()
assert summary['remaining_statement_count']==1 and summary['namespace_content_established'] is False
negatives=[]
for case in ('duplicate_slice_member','discharged_expansion','extra_field'):
 bad=json.loads(json.dumps(wire))
 if case=='duplicate_slice_member':bad['remaining']['subject']['statements']*=2
 if case=='discharged_expansion':bad['remaining']['required_expansion']='COMPLETE'
 if case=='extra_field':bad['remaining']['subject']['verified']=True
 try:decode_module_prefix(bad)
 except (ValueError,TypeError):negatives.append(case)
 else:raise AssertionError(case)
names=('scar/ir/program/module_entries.py','scar/analysis/program_lowering.py',
 'scar/analysis/source_module_lowering.py','scar/analysis/source_module_validation.py')
for name in names:ast.parse((root/name).read_text(),filename=name)
report={'status':'PASSED_CODEC_API_ONLY','fixture_ids_are_synthetic':True,'grants_source_compiler_runtime_proof':False,
 'source_lowerings':0,'target_compile':0,'target_exec':0,'marshal_reads':0,'source_context_reads':0,
 'codec_roundtrip':True,'negatives':negatives,'summary_shape_checked':True,
 'field_shapes':{cls.__name__:[f.name for f in fields(cls)] for cls in
 (ModuleStatementSlice,ModuleImportPrefix,UnexpandedModuleSlice,ModulePrefixOverlay,ModulePrefixProtocol)},
 'production_sources':[{'path':str(root/name),'sha256':hashlib.sha256((root/name).read_bytes()).hexdigest(),
 'bytes':(root/name).stat().st_size} for name in names]}
(base/'receipt.json').write_text(json.dumps(report,indent=2)+'\n');print(json.dumps({'status':report['status'],'negatives':negatives}))
