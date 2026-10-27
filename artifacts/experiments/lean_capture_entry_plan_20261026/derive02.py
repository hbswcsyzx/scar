"""One actual retained program/catalog/archive -> live plan -> readonly selector."""
from pathlib import Path
import hashlib,json,time,traceback
from scar.analysis.program_composition import CompositionIndex
from scar.analysis.source_attachments import SourceAttachments
from scar.analysis.compiler_witness_archives import CompilerWitnessArchives
from scar.analysis.source_entry_catalog import SourceEntryCatalog
from scar.analysis.source_frontend_worklist import SourceFrontendBudget,plan_source_entries
from scar.trace.lean_capture import LeanCapturePlan,read_plan
ROOT=Path(__file__).resolve().parent
OLD=Path('/home/zyf/AAA/scar-worktrees/source-entry-project/artifacts/experiments/python_call_targets_owned_20261026/case01')
started=time.monotonic()
def sha(p):return hashlib.sha256(p.read_bytes()).hexdigest()
try:
    base=CompositionIndex(OLD/'composition/index.json.gz')
    owner=SourceAttachments.from_admissions(OLD/'admissions/admissions.json',
        expected_report_sha256=sha(OLD/'admissions/admissions.json'),project_root=OLD/'project')
    manifest=OLD/'compiler/archive/manifest.json'
    archives=CompilerWitnessArchives(((str(manifest.parent),sha(manifest)),))
    catalog=SourceEntryCatalog(archives=archives,admissions=(owner,),projects=(base,))
    selected=tuple(c['entry_key'] for c in catalog.metadata()['candidates']
        if c['basis']['kind']=='DEPENDENCY_ADMISSION' and c['status']=='CANDIDATE_SOURCE_GRAPH_UNVERIFIED')
    assert len(selected)==2
    plan=plan_source_entries(catalog,budget=SourceFrontendBudget(max_dispatch_bodies=2,max_source_files=1),eligible_entry_keys=selected)
    derived=LeanCapturePlan.from_source_entry_plan(plan,namespace_root=OLD/'project')
    assert len(derived.bodies)==2 and all(body.source.path==str(OLD/'dependency/helper.py') for body in derived.bodies)
    artifact=derived.publish(ROOT,2)
    loaded=read_plan(artifact.uri,expected_sha256=artifact.sha256)
    assert loaded.to_dict()==derived.to_dict() and not loaded._memo
    try:read_plan(artifact.uri,expected_sha256='0'*64)
    except ValueError as error:
        assert 'SHA' in str(error);bad_sha=str(error)
    else:raise AssertionError('wrong plan SHA accepted')
    result={'status':'PASSED_NORMAL_LIVE_ENTRY_PLAN_SELECTOR','source_entry_plan_digest':plan.digest,
        'dispatch_entries':len(plan.dispatch),'selectors':len(derived.bodies),'profile':derived.to_dict()['profile'],
        'selector_artifact':{'path':artifact.uri,'sha256':artifact.sha256,'bytes':artifact.size_bytes},
        'source_snapshots':[{'path':b.source.path,'fingerprint':b.source.fingerprint,'code':b.code.key} for b in derived.bodies],
        'wrong_sha_rejected':bad_sha,'catalog_measurements':catalog.measurements(),
        'archive_receipts':archives.receipts(),
        'archive_activity':{catalog.store_for(catalog.resolve(row['entry_key'])).receipt()['path']:
            dict(catalog.store_for(catalog.resolve(row['entry_key'])).counts) for row in plan.dispatch},'source_prepare_or_lower':0,'target_exec':0,'new_capture':False,
        'runtime_source_compiler_qualification_granted_by_selector':False,'elapsed_seconds':time.monotonic()-started,
        'source_sha256':sha(Path('scar/trace/lean_capture.py'))}
    (ROOT/'result02.json').write_text(json.dumps(result,indent=2)+'\n');print(json.dumps(result,indent=2))
except BaseException as error:
    (ROOT/'failure02.json').write_text(json.dumps({'error':str(error),'traceback':traceback.format_exc(),'elapsed_seconds':time.monotonic()-started},indent=2)+'\n');raise
