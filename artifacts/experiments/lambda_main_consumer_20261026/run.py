"""One ordinary final-main STRUCTURE consumption of the unchanged real SP5."""
from pathlib import Path
from hashlib import sha256
from io import BytesIO
import gzip,json,time,traceback
ROOT=Path(__file__).resolve().parents[3];HERE=Path(__file__).resolve().parent
original=Path('/home/zyf/AAA/scar-worktrees/source-try-model/artifacts/analysis/lambda_expression_entry_resume01_20261026/worker/attempt-00001/result.json')
started=time.monotonic()
def pins():
 return {str(p.relative_to(ROOT)):{'bytes':p.stat().st_size,'sha256':sha256(p.read_bytes()).hexdigest()}for p in sorted((ROOT/'scar').rglob('*.py'))}
before=pins();receipt={'status':'FAILED_RETAINED','source_before':before,'failure':None,'lower':0,'compile':0,'target':0,'publication':0,'currentRun_binding':0}
try:
 from scar.analysis.code_witness import CodeWitnessStore,CodeWitnessBudget
 from scar.analysis.program_lowering import SourceProgram
 from scar.ir.record_codec import decode
 from scar.ir.semantics_v2 import SourceSnapshot
 result=json.loads(original.read_bytes());artifact=result['program'];path=Path(artifact['uri'])
 assert path.stat().st_size<=16_000_000
 stored=path.read_bytes();assert len(stored)==artifact['physical_bytes'] and sha256(stored).hexdigest()==artifact['physical_sha256']
 with gzip.GzipFile(fileobj=BytesIO(stored))as stream:decoded=stream.read(64_000_001)
 assert len(decoded)==artifact['decoded_bytes'] and sha256(decoded).hexdigest()==artifact['decoded_sha256'] and len(decoded)<=64_000_000
 doc=json.loads(decoded)
 store_ref=result['code_witness']['witness']['store']
 store=CodeWitnessStore(Path(store_ref['path']).parent,budget=CodeWitnessBudget(max_compile_keys=94,max_source_files=94,max_source_bytes=8_000_000,max_module_bytes=16_000_000,max_archive_bytes=256_000_000,max_manifest_bytes=8_000_000))
 assert not store.writable and not store.compile_missing and store.receipt()==store_ref
 snapshot=decode(SourceSnapshot,result['entry_reference']['snapshot']);text=store.text(snapshot)
 read_started=time.monotonic()
 program=SourceProgram.read_structure(doc,max_operations=10000,source_texts={snapshot.path:text})
 ordinary_seconds=time.monotonic()-read_started
 assert program.graph is not None and len(program.graph.operations)==170 and len(program.graph.regions)==2
 assert len(program.language.lambda_bodies)==1
 body=program.language.lambda_bodies[0]
 child=next(r for r in program.graph.regions if r.id==body.body.region)
 child_ops=sum(len(b.operations)for b in child.blocks)
 assert child_ops==17
 receipt.update(status='MAIN_ORDINARY_STRUCTURE_READER_PASS_WITH_OPEN',program=artifact,
  original_terminal={'path':str(original),'bytes':original.stat().st_size,'sha256':sha256(original.read_bytes()).hexdigest()},
  graph_operations=170,graph_regions=2,lambda_bodies=1,expression_region_operations=17,
  ordinary_reader_seconds=ordinary_seconds,source_snapshot=result['entry_reference']['snapshot'],
  archived_text_bytes=len(text.encode()),archive=store_ref,readonly_counts=store.counts,
  stored_sp5_bytes_read=len(stored),decoded_sp5_bytes=len(decoded),
  no_new_CodeWitness_proof=True,source_code_proof_scope='STRUCTURE only; prior independent source/code consumer qualification is retained separately')
except BaseException as error:
 receipt['failure']={'type':type(error).__name__,'detail':str(error),'traceback':traceback.format_exc()}
finally:
 after=pins();receipt.update(source_after=after,source_unchanged=before==after,elapsed_seconds=time.monotonic()-started)
 if before!=after:receipt['status']='FAILED_SOURCE_CHANGED'
 with (HERE/'receipt.json').open('x')as stream:json.dump(receipt,stream,sort_keys=True,separators=(',',':'));stream.write('\n')
 print(json.dumps({k:v for k,v in receipt.items()if k not in ('source_before','source_after','archive','original_terminal','source_snapshot')},sort_keys=True),flush=True)
raise SystemExit(int(receipt['status']!='MAIN_ORDINARY_STRUCTURE_READER_PASS_WITH_OPEN'))
