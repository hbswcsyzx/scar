"""Bounded existing92-op STRUCTURE readback; no body lowering or target code."""
import gzip
import hashlib
import io
import json
from pathlib import Path
import sys
import time

from scar.analysis.program_lowering import SourceProgram
from gate_guards import GateGuards

BASE=Path(__file__).resolve().parent
ROOT=BASE.parents[3]
OLD=BASE.parent/'candidate02'
MAIN=Path('/home/zyf/AAA/scar-worktrees/structured-program-model')

def receipt(path):
    data=path.read_bytes();s=path.stat()
    return {'path':str(path.resolve()),'stored_bytes':len(data),'stored_sha256':hashlib.sha256(data).hexdigest(),
            'decoded_bytes':None,'decoded_sha256':None,'size':s.st_size,'mtime_ns':s.st_mtime_ns,'ctime_ns':s.st_ctime_ns,'inode':s.st_ino,'device':s.st_dev}

start=time.monotonic()
selection=json.loads((OLD/'selection.json').read_bytes())
old_freeze=json.loads((OLD/'freeze.json').read_bytes())
program=OLD/'attempt02/body-01-source-program5.json.gz'
source=Path(selection['files'][str(selection['selected'][0]['file_index'])]['utf8_path'])
old_inputs=OLD/'attempt02/body-01-inputs.json'
inputs=[receipt(path) for path in (program,source,OLD/'freeze.json',old_inputs)]
# Independent local bound: actual physical+decoded16MB, no context or marshal.
freeze={'production_sources':old_freeze['production_sources'],'inputs':inputs,'small_frozen_files':[],
        'target_namespace_roots':old_freeze['target_namespace_roots'],'allowed_composition_roots':[],
        'limits':{'total_input_bytes':16_000_000,'record_context_bytes':64_000_000,'composition_root_bytes':96_000_000}}
# Pin the new reader bytes before installing read guards.
reader_path=ROOT/'scar/analysis/program_lowering.py';reader=receipt(reader_path)
producer_freeze_receipt=inputs[2]
guard=GateGuards(freeze,selection,BASE);guard.install()
stored=program.read_bytes()
with gzip.GzipFile(fileobj=io.BytesIO(stored)) as stream:payload=stream.read(64_000_001)
if len(payload)>64_000_000:raise ValueError('record64MB')
document=json.loads(payload)
text=source.read_bytes().decode('utf8')
path=document['metadata']['source']['path']
if hashlib.sha256(text.encode()).hexdigest()!=document['metadata']['source']['fingerprint'].removeprefix('sha256:'):
    raise ValueError('retained UTF8 fingerprint differs')
provenance=json.loads(old_inputs.read_bytes())
if document['interface']['definition']!=provenance['selection']['definition']['id'] or document['metadata']['source']!=provenance['selection']['snapshot']:
    raise ValueError('old artifact selected subject differs')
loaded=SourceProgram.read_structure(document,max_operations=4000,source_texts={path:text})
if loaded.to_dict()!=document or len(loaded.graph.operations)!=92:raise ValueError('old92-op public structure roundtrip differs')
# Cheap API-mode rejection only; the valid graph is not replayed a second time.
try:SourceProgram.from_dict(document,verification='SOURCE_REPLAY',source_texts={path:text})
except ValueError as error:
    if 'only supported for STRUCTURE' not in str(error):raise
else:raise AssertionError('SOURCE_REPLAY silently accepted retained source_texts')
value={'schema':'scar.kwargs-candidate03-existing-artifact-readback','schema_version':1,'status':'READBACK_VALID_WITH_OPEN',
       'artifact':inputs[0],'operations':92,'old_producer_freeze':producer_freeze_receipt,
       'old_producer_sources':old_freeze['production_sources'],'old_program_lowering_source':[r for r in old_freeze['candidate_scar_sources'] if r['path']==str(reader_path)][0],
       'new_reader_source':reader,'wire_roundtrip_unchanged':True,'semantics_and_control_validators':'original validators with explicit sources; fingerprint and recomputation retained',
       'mode':'STRUCTURE_WITH_EXPLICIT_RETAINED_SOURCE_TEXTS','default_filesystem_source_replay':False,
       'code_witness_checked_in_this_readback':False,'local_cleanup_and_outer_prefix_verified':False,
       'guard':guard.receipt(),'body_lowerings':0,'target_executions':0,'new_compiles':0,'new_source_prepares':0,
       'source_replay_mode_parameter_rejected':True,'elapsed_s':time.monotonic()-start}
with (BASE/'readback-receipt.json').open('x') as f:json.dump(value,f,ensure_ascii=False,sort_keys=True,indent=2);f.write('\n')
print(json.dumps({'status':value['status'],'operations':92,'actual_input_bytes':guard.counts['actual_input_bytes'],'elapsed_s':value['elapsed_s'],'new_reader_sha256':reader['stored_sha256']},sort_keys=True))
