"""One generic retained capture, normal external SP5s, fresh public linker."""
from dataclasses import replace
from pathlib import Path
import hashlib,json,time,traceback
from scar.analysis.program_inventory import inventory_program
from scar.analysis.source_layers import reconstruct_source_layers
from scar.analysis.program_composition import compose_program,CompositionIndex
from scar.analysis.dependency_sources import admit_dependency_sources
from scar.analysis.source_attachments import SourceAttachments
from scar.analysis.compiler_witness_archives import CompilerWitnessArchives,acquire_attachment_witnesses
from scar.analysis.source_entry_catalog import SourceEntryCatalog
from scar.analysis.source_frontend_worklist import SourceFrontendBudget,plan_source_entries,run_source_entries
from scar.analysis.source_program_publication import publish_source_entries
from scar.analysis.call_operands import link_call_operands
from scar.ir.program.functions import BodyLoweringProfile
from scar.ir.program.providers import ProviderArtifact,ProviderFactReference
from scar.ir.program.source_references import SourceArtifactLocator
from scar.ir.program.python_call_targets import PythonSourcePortModel,PythonSourcePortBudget
from scar.ir.record_codec import encode

ROOT=Path(__file__).resolve().parent
started=time.monotonic()
def write(path,value):
    path.write_text(json.dumps(value,sort_keys=True,ensure_ascii=False,separators=(',',':')))
def sha(path):return hashlib.sha256(path.read_bytes()).hexdigest()
try:
    inventory=inventory_program(ROOT/'project/sample.py',project_root=ROOT/'project',calls_trace=ROOT/'capture',
        body_profile=BodyLoweringProfile.STRUCTURED_ENV)
    ipath=ROOT/'inventory.json'
    assert inventory.to_dict()==json.loads(ipath.read_text()), 'normal inventory source changed'
    base=CompositionIndex(ROOT/'composition/index.json.gz')
    owner=SourceAttachments.from_admissions(ROOT/'admissions/admissions.json',
        expected_report_sha256=sha(ROOT/'admissions/admissions.json'),project_root=ROOT/'project')
    acquire_attachment_witnesses(owner,CompilerWitnessArchives(()),ROOT/'compiler',
        producer={'kind':'GENERIC_BOUND_METHOD_EXTERNAL_SOURCE_PORT_CHECK'})
    manifest=ROOT/'compiler/archive/manifest.json'
    archives=CompilerWitnessArchives(((str(manifest.parent),sha(manifest)),))
    catalog=SourceEntryCatalog(archives=archives,admissions=(owner,),projects=(base,))
    metadata=catalog.metadata();write(ROOT/'catalog.json',metadata)
    selected=tuple(c['entry_key'] for c in metadata['candidates'] if c['basis']['kind']=='DEPENDENCY_ADMISSION'
        and c['status']=='CANDIDATE_SOURCE_GRAPH_UNVERIFIED')
    assert len(selected)==2,metadata
    budget=SourceFrontendBudget(max_dispatch_bodies=2,max_source_files=1,
        max_operations_per_body=4000,max_total_operations=8000,max_output_bytes=32_000_000,max_elapsed_seconds=60)
    plan=plan_source_entries(catalog,budget=budget,eligible_entry_keys=selected)
    worker=run_source_entries(plan,ROOT/'worker',budget=budget)
    worker.require_unchanged()
    assert len(worker.owned_returns)==2 and all(r.program_reference is not None for r in worker.owned_returns),worker.document
    requests=tuple({'entry_key':r.entry.key,'source_program':r.program_reference['artifact']} for r in worker.owned_returns)
    publication=publish_source_entries(base,catalog,requests,ROOT/'publication',max_programs=2)
    body_composition=CompositionIndex.from_source_entry_publication(publication['manifest'],
        expected_sha256=publication['sha256'],archives=archives,max_programs=2)
    artifact=ProviderArtifact(str(ipath),sha(ipath),ipath.stat().st_size,'scar.program-inventory')
    cat=ROOT/'inventory-catalog.json';write(cat,{'schema':'scar.python-call-source-catalog','schema_version':1,'inventory':encode(artifact)})
    declaration=ProviderFactReference(ProviderArtifact(str(cat),sha(cat),cat.stat().st_size,'scar.python-call-source-catalog/1'),'#/inventory')
    locator=SourceArtifactLocator(artifact,artifact.sha256,artifact.size_bytes,'canonical-json',declaration=declaration)
    captured={}
    def consumer(model,check):
        for binding in model.bindings:check(binding)
        method=next(b for b in model.bindings if b.receiver is not None)
        bad=replace(method,receiver=replace(method.receiver,formal_slot=method.arguments[0].formal_slot,
            formal_value=method.arguments[0].formal_value))
        try:check(bad)
        except ValueError as error:captured['negative']=str(error)
        else:raise AssertionError('wrong receiver formal accepted')
        captured['model']=model
        write(ROOT/'model.json',model.to_dict())
        assert PythonSourcePortModel.loads((ROOT/'model.json').read_text())==model
    report=link_call_operands(ROOT/'capture',ROOT/'project',inventory,
        python_source_port_consumer=consumer,python_source_port_budget=PythonSourcePortBudget(),
        python_source_body_composition=body_composition,python_source_inventory_artifact=locator)
    model=captured['model'];assert model.summary()['bound_calls']==5,model.summary()
    assert model.summary()['receiver_ports']==2 and len(model.observed.targets)==8
    external=[b for b in model.bindings if b.callee_body.graph.artifact.schema=='scar.source-program/5']
    assert len(external)==2
    assert any(b.caller_body.graph.artifact.schema=='scar.source-program/5' for b in external)
    result={'status':'PASS_WITH_OPEN','elapsed_seconds':time.monotonic()-started,'observed':model.observed.summary(),
        'ports':model.summary(),'external_incoming_and_outgoing_calls':len(external),
        'receiver_negative':captured['negative'],'old_report_schema':report.to_dict()['schema_version'],
        'old_routing':report.routing.summary(),'external_bodies':len(worker.owned_returns),
        'new_LeWM_or_target_episode':False,'retained_generic_capture':str(ROOT/'capture'),
        'model':{'path':str(ROOT/'model.json'),'bytes':(ROOT/'model.json').stat().st_size,'sha256':sha(ROOT/'model.json')}}
    write(ROOT/'RESULT03.json',result);print(json.dumps(result,indent=2))
except BaseException as error:
    write(ROOT/'FAILURE03.json',{'type':type(error).__name__,'detail':str(error),'traceback':traceback.format_exc(),
        'elapsed_seconds':time.monotonic()-started})
    raise
