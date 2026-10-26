"""Normal fresh linker over archived targets and existing external SP5s."""
from dataclasses import replace
from pathlib import Path
import hashlib,json,time
from scar.analysis.program_inventory import inventory_program
from scar.ir.program.functions import BodyLoweringProfile
from scar.analysis.compiler_witness_archives import CompilerWitnessArchives
from scar.analysis.program_composition import CompositionIndex
from scar.analysis.call_operands import link_call_operands
from scar.ir.program.python_call_targets import PythonSourcePortModel,PythonSourcePortBudget
from scar.ir.program.providers import ProviderArtifact,ProviderFactReference
from scar.ir.program.source_references import SourceArtifactLocator
from scar.analysis.call_operand_routes import _checked_formal_ports,_Boundary
from scar.ir.program.functions import FunctionSignature,BodyEntryInterface
from scar.ir.program.inventory import BodyInventory,BodyStatus
from scar.ir.program.source import LoweringMetadata
from scar.ir.program.codec import loads as load_graph
from scar.ir.record_codec import decode

ROOT=Path(__file__).resolve().parent
started=time.monotonic()
def sha(p):return hashlib.sha256(p.read_bytes()).hexdigest()
inventory=inventory_program(ROOT/'project/sample.py',project_root=ROOT/'project',calls_trace=ROOT/'capture',
    body_profile=BodyLoweringProfile.STRUCTURED_ENV)
ipath=ROOT/'inventory.json';document=json.loads(ipath.read_text());assert inventory.to_dict()==document
manifest=ROOT/'compiler/archive/manifest.json'
archives=CompilerWitnessArchives(((str(manifest.parent),sha(manifest)),))
pub=ROOT/'publication/manifest.json'
composition=CompositionIndex.from_source_entry_publication(pub,expected_sha256=sha(pub),archives=archives,max_programs=2)
artifact=ProviderArtifact(str(ipath),sha(ipath),ipath.stat().st_size,'scar.program-inventory')
catalog=ROOT/'inventory-catalog.json'
declaration=ProviderFactReference(ProviderArtifact(str(catalog),sha(catalog),catalog.stat().st_size,'scar.python-call-source-catalog/1'),'#/inventory')
locator=SourceArtifactLocator(artifact,artifact.sha256,artifact.size_bytes,'canonical-json',declaration=declaration)
captured={}
def consumer(model,check):
    for binding in model.bindings:check(binding)
    method=next(b for b in model.bindings if b.receiver is not None)
    bad=replace(method,receiver=replace(method.receiver,formal_slot=method.arguments[0].formal_slot,
        formal_value=method.arguments[0].formal_value))
    try:check(bad)
    except ValueError as error:captured['receiver_rejection']=str(error)
    else:raise AssertionError('wrong receiver formal accepted')
    captured['model']=model
report=link_call_operands(ROOT/'capture',ROOT/'project',inventory,
    python_source_port_consumer=consumer,python_source_port_budget=PythonSourcePortBudget(),
    python_source_body_composition=composition,python_source_inventory_artifact=locator)
model=captured['model'];assert PythonSourcePortModel.loads((ROOT/'model.json').read_text())==model
assert model.summary()['bound_calls']==5
# Reuse an actual saved normal body to verify the old expected-definition guard.
signature=decode(FunctionSignature,document['interfaces']['signatures'][0])
interface=next(decode(BodyEntryInterface,x) for x in document['interfaces']['bodies'] if x['definition']==document['interfaces']['signatures'][0]['definition'])
raw=next(b for f in document['files'] for b in f['bodies'] if b['definition']==document['interfaces']['signatures'][0]['definition'])
graph=load_graph(json.dumps(raw['graph']))
body=BodyInventory(signature.definition,BodyStatus.LOWERED_WITH_GAPS,graph,decode(LoweringMetadata,raw['metadata']),raw['reason'])
other=next(decode(FunctionSignature,x).definition for x in document['interfaces']['signatures'] if x['definition']!=raw['definition'])
try:_checked_formal_ports(body,interface,replace(signature,definition=other),{v.id:v for v in graph.values},
    {b.id:b for r in graph.regions for b in r.blocks},signature.definition)
except _Boundary as error:guard_rejection=error.detail
else:raise AssertionError('old expected-definition guard weakened')
paths=['scar/ir/program/python_call_targets.py','scar/analysis/python_call_targets.py','scar/analysis/call_operands.py',
    'scar/analysis/current_source_evidence.py','scar/analysis/call_edges.py','scar/analysis/call_operand_routes.py','scar/trace/call_operands.py']
result={'status':'PASS_WITH_OPEN','elapsed_seconds':time.monotonic()-started,'model_equal_before_after_lossless_archive':True,
    'ports':model.summary(),'observed':model.observed.summary(),'receiver_rejection':captured['receiver_rejection'],
    'old_expected_definition_rejection':guard_rejection,'old_report_version':report.to_dict()['schema_version'],
    'external_SP5_relowered':False,'target_or_LeWM_replayed':False,'model_sha256':sha(ROOT/'model.json'),
    'source_sha256':{p:sha(Path(p)) for p in paths}}
(ROOT/'RETAINED_RESULT.json').write_text(json.dumps(result,indent=2)+'\n');print(json.dumps(result,indent=2))
