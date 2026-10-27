"""One retained 8-op body's new recovery codec/row projection; no owner proof."""
from pathlib import Path
import importlib.util,sys,json,time,hashlib
import scar.analysis,scar.store
ISO=Path('/home/zyf/AAA/scar-worktrees/source-entry-project')
for area,name in [('analysis','program_lowering'),('analysis','structured_lowering'),('store','source_fragments'),('analysis','source_entry_catalog'),('analysis','source_program_publication')]:
 qualified='scar.'+area+'.'+name
 spec=importlib.util.spec_from_file_location(qualified,ISO/'scar'/area/(name+'.py'))
 module=importlib.util.module_from_spec(spec);sys.modules[qualified]=module;spec.loader.exec_module(module)
from scar.analysis.source_program_publication import _EntryBodyCache,_entry_canonical,_canonical
from scar.analysis.inventory_partitions import _read_receipt
from scar.ir.record_codec import decode,encode
from scar.ir.program.codec import loads as core_loads,dumps as core_dumps
from scar.ir.program.source import LoweringMetadata
from scar.ir.program.functions import BodyLoweringProfile,BodyEntryInterface
from scar.ir.program.frames import FrameModel
from scar.ir.program.structured import StructuredBodyModel
from scar.ir.program.source_language import SourceLanguageOverlay
from scar.ir.program.source_references import SourceDefinitionReference
start=time.monotonic()
manifest=ISO/'artifacts/experiments/source_publication_shared_generic_20261026/publication/manifest.json'
row=json.loads(manifest.read_text())['bodies'][0]
original,actual=_read_receipt(row['source_program']['uri'],limit=128_000_000)
assert all(row['source_program'][k]==v for k,v in actual.items()) and _entry_canonical(original,actual)
graph=core_loads(_canonical(original['graph']).decode('utf8'))
program=_EntryBodyCache(graph,decode(LoweringMetadata,original['metadata']),BodyLoweringProfile(original['profile']),
 decode(BodyEntryInterface,original['interface']),FrameModel.from_dict(original['frame']) if original['frame'] is not None else None,
 decode(StructuredBodyModel,original['structured']),decode(SourceLanguageOverlay,original['language']))
reference=decode(SourceDefinitionReference,row['definition'])
assert len(graph.operations)==8 and program.metadata.source==reference.snapshot
assert program.interface.definition==reference.definition and program.structured.definition==reference.definition
assert program.structured.source==reference.source and program.language.namespace_root==reference.context.namespace_root
assert hashlib.sha256(_canonical(json.loads(core_dumps(graph)))).hexdigest()==row['program_graph_sha256']
for name in ('metadata','interface','structured','language'):
 assert encode(getattr(program,name))==original[name],name
checkpoint,cp_receipt=_read_receipt(row['checkpoint']['uri'],limit=128_000_000)
assert checkpoint['source_program']==row['source_program'] and checkpoint['body_identity']['entry']==program.metadata.entry
assert checkpoint['definition_reference']==row['definition'] and checkpoint['context']==encode(reference.context)
result={'status':'PASS_RETAINED_8OP_RECOVERY_CODEC_AND_ROW_FIELDS','operations':len(graph.operations),
 'original_sp5':row['source_program'],'checkpoint':row['checkpoint'],'elapsed_seconds':time.monotonic()-start,
 'qualification':'codec/API projection only; no catalog/source/code/runtime admission or lowering performed'}
Path(__file__).with_name('RECOVERY_CODEC_SMOKE.json').write_text(json.dumps(result,indent=2)+'\n')
print(json.dumps(result))
