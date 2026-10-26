"""Complete the same original SP5's normal readers; never lower again."""
from pathlib import Path
from hashlib import sha256
from collections import Counter
import importlib.util,json,time,traceback
HERE=Path(__file__).resolve().parent;ROOT=HERE.parents[2];started=time.monotonic()
prior=ROOT/'artifacts/analysis/source_comprehension_entry_resume02_20261026/worker/attempt-00001/result.json'
spec=importlib.util.spec_from_file_location('ordinary_inputs',Path('/home/zyf/AAA/scar-worktrees/source-try-model/artifacts/experiments/function_try_source_entries_20261026/common.py'))
common=importlib.util.module_from_spec(spec);spec.loader.exec_module(common)
pins={str(p.relative_to(ROOT)):sha256(p.read_bytes()).hexdigest()for p in sorted((ROOT/'scar').rglob('*.py'))}
record={'status':'FAILED_RETAINED','failure':None,'lower':0,'restore_owner':False,'raw':0,'compile':0,'target':0,'publication':0,'currentRun_binding':0}
try:
 r=json.loads(prior.read_bytes());ref=r['program']
 from scar.analysis.source_frontend_worklist import _read_receipt
 from scar.analysis.program_lowering import SourceProgram
 from scar.analysis.source_language import SourceCodeEvidence,SourceLanguageOptions
 from scar.analysis.structured_lowering import require_valid_structured_body
 config=json.loads(Path('/home/zyf/AAA/scar-worktrees/source209-model/artifacts/experiments/source209_resume01_20261026/inputs.json').read_bytes())
 owner,archives,catalog,metadata=common.normal_inputs(config,None)
 entry=catalog.resolve(r['entry_key']);context=catalog.prepare(entry)
 doc,physical=_read_receipt(ref['uri'],limit=128_000_000)
 assert all(physical[k]==ref[k]for k in('physical_bytes','physical_sha256','decoded_bytes','decoded_sha256'))
 program=SourceProgram.read_structure(doc,max_operations=10000,source_texts={entry.reference.snapshot.path:context.text})
 record['ordinary_structure_reader']=True
 independent=SourceCodeEvidence.from_entry(catalog,entry)
 require_valid_structured_body(program.structured,program.graph,program.interface,program.metadata,
     semantic=program.semantic,control=program.control,language=program.language,source_tree=context.tree,
     language_options=SourceLanguageOptions(program.language.capabilities,independent))
 record.update(status='INDEPENDENT_ORDINARY_SOURCE_CODE_READBACK_PASS_WITH_OPEN',independent_code_reader=True,
     program=ref,entry_key=r['entry_key'],entry_reference=r['entry_reference'],source_calls=r['source_calls'],
     original_terminal=common.receipt(prior),original_terminal_status=r['status'],
     graph_operations=len(program.graph.operations),graph_regions=len(program.graph.regions),
     protocol_counts=dict(Counter(p.kind.value for p in program.structured.protocols)),
     active_capabilities=[c.value for c in program.language.capabilities],
     readonly_counts=[s.counts for s in archives._stores.values()],
     complete_model=False,source_scope_run=272038)
except BaseException as error:
 record['failure']={'type':type(error).__name__,'detail':str(error),'traceback':traceback.format_exc()}
finally:
 record.update(elapsed_seconds=time.monotonic()-started,source_sha256=pins,source_unchanged=all(sha256((ROOT/p).read_bytes()).hexdigest()==h for p,h in pins.items()))
 common.save(HERE/'receipt.json',record)
 print(json.dumps({k:v for k,v in record.items()if k not in('source_sha256','entry_reference')},sort_keys=True),flush=True)
raise SystemExit(int(record['status']=='FAILED_RETAINED'))
