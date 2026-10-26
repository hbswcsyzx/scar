"""One retained successful generic entry through the complete main shared worker."""
from pathlib import Path
import hashlib,json,time,traceback,resource,subprocess
from scar.analysis.program_composition import CompositionIndex
from scar.analysis.source_attachments import SourceAttachments
from scar.analysis.compiler_witness_archives import CompilerWitnessArchives
from scar.analysis.source_entry_catalog import SourceEntryCatalog
from scar.analysis.source_frontend_worklist import SourceFrontendBudget,plan_source_entries,run_source_entries
from scar.store.source_fragments import SourceContextSession
from scar.ir.program.source_references import SourceArtifactLocator
from scar.ir.program.providers import ProviderArtifact
from scar.ir.record_codec import encode
ROOT=Path(__file__).resolve().parent
OLD=ROOT.parent/'python_call_targets_owned_20261026/case01'
MAIN=Path('/home/zyf/AAA/scar-worktrees/structured-program-model')
start=time.monotonic()
def sha(p):return hashlib.sha256(p.read_bytes()).hexdigest()
def emit(p,v):p.write_text(json.dumps(v,indent=2,allow_nan=False)+'\n')
try:
    source_paths=tuple(MAIN/name for name in ('scar/analysis/source_frontend_worklist.py','scar/analysis/source_entry_run.py','scar/store/source_fragments.py','scar/analysis/program_lowering.py'))
    source_before={str(p):sha(p) for p in source_paths}
    old_stats={str(p):(p.stat().st_size,p.stat().st_mtime_ns,p.stat().st_ctime_ns) for p in OLD.rglob('*') if p.is_file()}
    previous=[json.loads(line) for line in (OLD/'worker/attempts.jsonl').read_text().splitlines()]
    succeeded=[row for row in previous if row['status']=='SUCCEEDED']
    chosen=min(succeeded,key=lambda row:(row['graph_operations'] if 'graph_operations' in row else row['operations_emitted'],row['entry_key']))
    base=CompositionIndex(OLD/'composition/index.json.gz')
    owner=SourceAttachments.from_admissions(OLD/'admissions/admissions.json',expected_report_sha256=sha(OLD/'admissions/admissions.json'),project_root=OLD/'project')
    manifest=OLD/'compiler/archive/manifest.json';archives=CompilerWitnessArchives(((str(manifest.parent),sha(manifest)),))
    catalog=SourceEntryCatalog(archives=archives,admissions=(owner,),projects=(base,))
    budget=SourceFrontendBudget(max_dispatch_bodies=1,max_source_files=1,max_source_bytes=65536,
        max_operations_per_body=512,max_total_operations=512,max_record_bytes=8_000_000,max_output_bytes=16_000_000,max_elapsed_seconds=60)
    plan=plan_source_entries(catalog,budget=budget,eligible_entry_keys=(chosen['entry_key'],),out_dir=ROOT/'plan')
    assert len(plan.dispatch)==1
    before={ref['path']:dict(archives.store_for(ref).counts) for ref in archives.receipts()}
    worker=run_source_entries(plan,ROOT/'worker',budget=budget,shared_context=True,progress=lambda row:print(json.dumps(row),flush=True))
    worker.require_unchanged()
    assert worker.document['counts']=={'SUCCEEDED':1},worker.document
    returned=worker.owned_returns[0];returned.require_unchanged();ref=returned.program_reference
    assert ref['pointer']=='#/program/graph' and ref['artifact']['representation']=='scar.source-body-fragment/1'
    terminal=returned._attempt_directory/'result.json';row=json.loads(terminal.read_text())
    assert row['status']=='SUCCEEDED' and row['program']==ref['artifact'] and row['public_structure_reader'] and row['independent_code_reader']
    assert Path(row['original_program']['uri'])==returned._attempt_directory/'source-program5.json.gz' and not Path(row['original_program']['uri']).exists()
    a=ref['artifact'];locator=SourceArtifactLocator(ProviderArtifact(a['uri'],a['physical_sha256'],a['physical_bytes'],a['representation']),a['decoded_sha256'],a['decoded_bytes'],'gzip-canonical-json')
    entry=returned.entry;text=catalog.store_for(entry).text(entry.reference.snapshot)
    with SourceContextSession(source_texts={entry.reference.snapshot.path:text}) as session:
        fragment=session.read(locator,namespace_root=entry.reference.context.namespace_root)
        session_costs=session.finish()
    from scar.ir.program.codec import dumps as dump_graph
    assert dump_graph(fragment.body.graph)==dump_graph(returned.result.graph) and fragment.body.metadata==returned.result.metadata
    assert fragment.body.interface==returned.result.interface and fragment.body.language==returned.result.language
    assert fragment.original.artifact.uri==row['original_program']['uri']
    unchanged={str(p):(p.stat().st_size,p.stat().st_mtime_ns,p.stat().st_ctime_ns) for p in OLD.rglob('*') if p.is_file()}
    assert unchanged==old_stats and source_before=={str(p):sha(p) for p in source_paths}
    after={ref['path']:dict(archives.store_for(ref).counts) for ref in archives.receipts()}
    activity={p:{k:after[p][k]-before[p][k] for k in before[p]} for p in before}
    assert all(row['compile_attempts']==0 for row in activity.values())
    result={'status':'PASS_COMPLETE_NORMAL_MAIN_SOURCE_ENTRY_SHARED_WORKER',
        'main_head':subprocess.check_output(['git','rev-parse','HEAD'],cwd=MAIN,text=True).strip(),
        'selected_from_original_successes':{'entry_key':chosen['entry_key'],'original_operations_emitted':chosen['operations_emitted']},
        'actual_new_lower_returns':len(worker.owned_returns),'actual_operations':len(returned.result.graph.operations),
        'worker':worker.document,'worker_terminal':{'uri':str(terminal),'sha256':sha(terminal),'bytes':terminal.stat().st_size},
        'fragment_endpoint':ref,'normal_fragment_locator':encode(locator),'session_costs':session_costs,
        'fresh_full_sp5_retired':True,'previous_inputs_unchanged':True,'main_sources_unchanged':True,
        'readonly_witness_activity':activity,'source_sha256':source_before,
        'elapsed_seconds':time.monotonic()-start,'self_maxrss_kib':resource.getrusage(resource.RUSAGE_SELF).ru_maxrss,
        'new_target_capture':False,'target_exec':False,'bootstrap_or_cp2_run':False,'whole_program_complete':False}
    emit(ROOT/'result.json',result);print(json.dumps(result,indent=2))
except BaseException as error:
    emit(ROOT/'failure.json',{'type':type(error).__name__,'detail':str(error),'traceback':traceback.format_exc(),'elapsed_seconds':time.monotonic()-start})
    raise
