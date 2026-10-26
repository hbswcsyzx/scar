from pathlib import Path
import hashlib,json,time,sys,importlib.util
import scar.analysis
ISO=Path('/home/zyf/AAA/scar-worktrees/source-entry-project');ROOT=Path(__file__).resolve().parent
for name in ('source_entry_catalog','source_program_publication'):
 key='scar.analysis.'+name;spec=importlib.util.spec_from_file_location(key,ISO/'scar/analysis'/(name+'.py'))
 module=importlib.util.module_from_spec(spec);sys.modules[key]=module;spec.loader.exec_module(module)
from scar.analysis.program_composition import CompositionIndex
from scar.analysis.source_attachments import SourceAttachments
from scar.analysis.compiler_witness_archives import CompilerWitnessArchives
from scar.analysis.source_entry_catalog import SourceEntryCatalog
from scar.analysis.source_program_publication import plan_source_entry_publication,publish_source_entries
start=time.monotonic();OLD=ISO/'artifacts/experiments/python_call_targets_owned_20261026/case01'
def sha(p):return hashlib.sha256(p.read_bytes()).hexdigest()
previous=[json.loads(line) for line in (OLD/'worker/attempts.jsonl').read_text().splitlines()]
selected=min([r for r in previous if r['status']=='SUCCEEDED'],key=lambda r:(r['operations_emitted'],r['entry_key']))
base=CompositionIndex(OLD/'composition/index.json.gz')
owner=SourceAttachments.from_admissions(OLD/'admissions/admissions.json',expected_report_sha256=sha(OLD/'admissions/admissions.json'),project_root=OLD/'project')
manifest=OLD/'compiler/archive/manifest.json';archives=CompilerWitnessArchives(((str(manifest.parent),sha(manifest)),))
catalog=SourceEntryCatalog(archives=archives,admissions=(owner,),projects=(base,))
requests=({'entry_key':selected['entry_key'],'source_program':selected['program']},)
with catalog._ordinary_read_session(base,controls=(requests,),share_source_context=True) as session:
 plan=plan_source_entry_publication(session.target,session.catalog,requests,max_programs=1,publication_version=2)
 publication=publish_source_entries(session.target,session.catalog,requests,ROOT/'publication',max_programs=1,plan=plan)
 costs=session.program_reader.measurements()
result={'status':'PASS_ACTUAL_NORMAL_PUBLISHER_SHARED_CONTEXT_8OP','actual_body_count':publication['body_count'],
 'selected_original_operations':selected['operations_emitted'],'publication':publication,'source_context_costs':costs,
 'readonly_activity':[dict(x.counts) for x in archives._stores.values()],'elapsed_seconds':time.monotonic()-start,
 'new_lower':0,'new_target':0,'whole_program_complete':False}
(ROOT/'result.json').write_text(json.dumps(result,indent=2)+'\n');print(json.dumps(result,indent=2))
