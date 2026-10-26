"""Exact bound static-manifest closure availability; no source/body graph decoding."""
import gzip
import hashlib
import json
from pathlib import Path
import subprocess

HERE=Path(__file__).resolve().parent
TREE=HERE.parents[2]
OLD=TREE/'artifacts/experiments/lewm_external_entry_publication_20261026'
PRIOR=Path('/home/zyf/AAA/scar-worktrees/source858-runtime/artifacts/experiments/first_stage_source858_current_20261026/inputs.json')

def rawref(p,raw):
 return {'path':str(p),'sha256':hashlib.sha256(raw).hexdigest(),'bytes':len(raw)}
def main():
 prior=json.loads(PRIOR.read_bytes());head=subprocess.check_output(['git','rev-parse','HEAD'],cwd=TREE,text=True).strip()
 refs={};parents={};reads=[];restored=[];components=[]
 def declare(p,r,source):
  p=Path(p)
  row={'path':str(p),'sha256':r['physical_sha256'],'bytes':r['physical_bytes']}
  if str(p) in refs:assert refs[str(p)]==row,('contradictory declared receipts',str(p))
  refs[str(p)]=row;parents.setdefault(str(p),[]).append(source)
 def scan(value,root,source):
  if isinstance(value,dict):
   if {'uri','physical_sha256','physical_bytes','decoded_sha256','decoded_bytes'} <= set(value):
    p=Path(value['uri'])
    if not p.is_absolute():
     assert '..' not in p.parts
     p=root/p
    declare(p,value,source)
   for child in value.values():scan(child,root,source)
  elif isinstance(value,list):
   for child in value:scan(child,root,source)
 manifests=[x for x in prior['inputs'] if Path(x['path']).name=='manifest.json' and Path(x['path']).is_relative_to(TREE/'artifacts')]
 for original in manifests:
  p=Path(original['path']);assert p.exists(),str(p)
  raw=p.read_bytes();assert rawref(p,raw)==original
  reads.append(rawref(p,raw));doc=json.loads(raw)
  if doc.get('schema')!='scar.partitioned-program-inventory':continue
  scan(doc,p.parent,str(p))
  if 'publication' in doc.get('components',{}):
   r=doc['components']['publication'];q=Path(r['uri']) if r['external'] else p.parent/r['uri']
   data=q.read_bytes();assert len(data)==r['physical_bytes'] and hashlib.sha256(data).hexdigest()==r['physical_sha256']
   payload=gzip.decompress(data) if q.suffix=='.gz' else data
   assert len(payload)==r['decoded_bytes'] and hashlib.sha256(payload).hexdigest()==r['decoded_sha256']
   assert len(payload)<=4_000_000,('only small publication metadata authorized',str(q))
   reads.append({**rawref(q,data),'decoded_bytes':len(payload)})
   sub=json.loads(payload);scan(sub,q.parent,str(q));components.append(str(q))
 # Only exact declared missing artifacts are recovered. No graph/checkpoint content is decoded.
 for pstr,row in sorted(refs.items()):
  p=Path(pstr)
  if p.exists():continue
  assert p.is_relative_to(TREE/'artifacts') and not p.is_symlink(),('unrecoverable original URI',pstr)
  raw=subprocess.check_output(['git','show',head+':'+str(p.relative_to(TREE))],cwd=TREE)
  assert rawref(p,raw)==row,('HEAD blob differs from bound original receipt',pstr)
  p.parent.mkdir(parents=True,exist_ok=True)
  with p.open('xb') as stream:stream.write(raw)
  restored.append({**row,'declarations':parents[pstr]})
 states=[]
 for pstr,row in sorted(refs.items()):
  p=Path(pstr);assert p.is_file() and not p.is_symlink() and p.resolve(strict=True)==p
  assert p.stat().st_size==row['bytes'],('bound static artifact stat mismatch',pstr)
  s=p.stat();states.append({**row,'declarations':parents[pstr],
   'stat':[s.st_dev,s.st_ino,s.st_size,s.st_mtime_ns,s.st_ctime_ns]})
 report={'schema':'scar.external-publication-bound-static-closure-preflight/1','status':'DECLARED_STATIC_RECEIPTS_AVAILABLE_NOT_MODEL_VERIFIED',
  'original_failed_gate':str(OLD),'original_root_session':49787,'original_exit':1,'root_failure_seconds':32.7447,
  'recovery_commit':head,'restored':restored,'restored_bytes':sum(x['bytes'] for x in restored),
  'metadata_reads':reads,'metadata_stored_bytes':sum(x['bytes'] for x in reads),
  'metadata_decoded_bytes':sum(x.get('decoded_bytes',x['bytes']) for x in reads),
  'bound_static_references':states,'publication_metadata_components':components,
  'scope':'all source858-declared original inventory manifests, their exact file/component/parent refs, and nested stored receipts in small publication metadata; body/source/SP5/checkpoint payloads not decoded',
  'limit':'stat preflight is availability only; ordinary readers still validate original receipts and all model semantics',
  'old_artifacts_changed':False,'original_URI_relocated':False,'existing_payload_replaced':False}
 with (HERE/'static-closure-preflight.json').open('x') as f:json.dump(report,f,sort_keys=True,separators=(',',':'));f.write('\n')
 print(json.dumps({'references':len(states),'restored':len(restored),'restored_bytes':report['restored_bytes'],
  'metadata_stored':report['metadata_stored_bytes'],'metadata_decoded':report['metadata_decoded_bytes'],'body_payload_decodes':0}))

if __name__=='__main__':main()
