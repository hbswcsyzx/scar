"""Main ordinary readonly consumption of the original16 static witnesses."""
import hashlib
import json
from pathlib import Path
import time
import traceback

HERE=Path(__file__).resolve().parent
ROOT=HERE.parents[2]
ORIGINAL=Path('/home/zyf/AAA/scar-worktrees/source858-runtime/artifacts/experiments/lewm_archived_compiler_gate_20261026')
ARCHIVE=ORIGINAL/'result/archive'
WORKSET=ORIGINAL/'workset.json'
PINS={'source_attachments.py':'1e4e7349fdb845d1defa162b705ccd23818e82b4cac04736d77005f65a39f734',
 'code_witness.py':'548890ff2c74967017466d9493994ea2733e12cd05894b079f8cebc940897ecf',
 'compiler_witness_archives.py':'0d897d5eebba5df83eb1bf728602e700466786dc9de828e4bee4859580cecef9'}
START=time.monotonic()

def receipt(p):
 p=Path(p);b=p.read_bytes();return {'path':str(p),'sha256':hashlib.sha256(b).hexdigest(),'bytes':len(b)}
def canonical(x):return json.dumps(x,sort_keys=True,separators=(',',':'),ensure_ascii=False,allow_nan=False).encode()
def need(x,msg):
 if not x:raise ValueError(msg)


def main():
 result={'status':'RUNNING','current369749_binding':False,'graph_lower_compile_target':False,'whole_first_stage_complete':False}
 try:
  need(not(HERE/'receipt.json').exists(),'fresh receipt required')
  sources=[receipt(ROOT/'scar/analysis'/n)for n in PINS]
  need(all(r['sha256']==PINS[Path(r['path']).name]for r in sources),'main3-source bytes differ from verified commit')
  workref=receipt(WORKSET);manifest=receipt(ARCHIVE/'manifest.json')
  need(workref['sha256']=='8a1f6237bf4bc535ca5cfb869902a69ef8f700736c4b1d8112568a1f01927199','original workset changed')
  need(manifest['sha256']=='d3c67c93ff2da74c3fd51bcbe235382dc09a7ca2f363b56edc158fc1004791b1','original archive manifest changed')
  work=json.loads(WORKSET.read_bytes())
  from scar.analysis.code_witness import CodeWitnessStore,CodeWitnessBudget
  from scar.ir.record_codec import decode,encode
  from scar.ir.program.call_edges import CapturedCode,CodeSourceLink
  from scar.ir.semantics_v2 import SourceSnapshot
  store=CodeWitnessStore(ARCHIVE,create=False,compile_missing=False,budget=CodeWitnessBudget(max_compile_keys=8,max_source_files=8,max_source_bytes=1_000_000,max_module_bytes=8_000_000,max_archive_bytes=32_000_000))
  declared=sum(x['artifact']['bytes']for section in ('sources','modules')for x in store.document[section].values())
  need(declared<=64_000_000,'declared readonly code/source byte working set exceeds64MB')
  checked_sources=[]
  for original in work['source_texts']:
   snap=decode(SourceSnapshot,original['snapshot']);text=store.text(snap).encode('utf-8')
   rows=[x for x in store.document['sources'].values()if x['snapshot']==original['snapshot']]
   need(len(rows)==1,'source snapshot is not unique');row=rows[0];origin=row['archived_source_origin']
   need(hashlib.sha256(text).hexdigest()==original['normalized_sha256']and len(text)==original['normalized_bytes']
    and row['original_raw_sha256']==original['raw_sha256']and row['original_encoding']==original['encoding']
    and origin['artifact']==original['locator']and origin['declaration']==original['declaration']and origin['owner']==original['owner'],
    'readonly original source text/provenance differs from verified workset')
   checked_sources.append({'snapshot':encode(snap),'normalized_sha256':original['normalized_sha256'],'bytes':len(text)})
  witnesses=[]
  for request in work['normal_plan']['requests']:
   captured=decode(CapturedCode,request['captured']);link=decode(CodeSourceLink,request['source_link'])
   _,witness=store.resolve(captured,link.snapshot,link.optimize_levels,allow_compile=False)
   witnesses.append({'origin':request['origin'],'captured':request['captured'],'witness':witness})
  need(len(witnesses)==16 and len(checked_sources)==8 and store.counts['compile_attempts']==0 and store.counts['source_bytes_read']==0,'ordinary readonly consumption counters differ')
  need(receipt(ARCHIVE/'manifest.json')==manifest and receipt(WORKSET)==workref,'original inputs changed')
  need([receipt(ROOT/'scar/analysis'/n)for n in PINS]==sources,'main source changed during readback')
  result.update(status='ORDINARY_READONLY_CONSUMED_WITH_OPEN',sources=sources,runner=receipt(Path(__file__).resolve()),original_archive=manifest,original_workset=workref,
   original_owner_inputs=work['normal_plan']['source_attachment_inputs'],source_text_checks=checked_sources,descriptor_checks=witnesses,counts=dict(store.counts),
   source_scope='original272038 static evidence; no current369749 body qualification',owner_text_check='reuse genuine writer-gate owner-verified workset; ordinary main archive text/provenance checked here, no owner/graph reconstruction',
   declared_readonly_payload_bytes=declared,budget={'metadata':256_000_000,'code_archive':64_000_000,'external_seconds':180,'enforcement':'ordinary per-API limits plus declared readonly payload set; cumulative actual I/O not separately metered'},
   archived_trailing_whitespace='five trailing-space lines in original c745 source are preserved exact bytes, not repaired',elapsed_s=time.monotonic()-START)
 except BaseException as error:
  result.update(status='FAILED_RETAINED',error={'type':type(error).__name__,'detail':str(error),'traceback':traceback.format_exc()},elapsed_s=time.monotonic()-START)
  raise
 finally:
  raw=canonical(result)+b'\n';need(len(raw)<=8_000_000,'receipt exceeds8MB')
  with(HERE/'receipt.json').open('xb')as stream:stream.write(raw)

if __name__=='__main__':main()
