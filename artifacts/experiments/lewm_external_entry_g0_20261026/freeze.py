"""Pin the small G0 inputs and current consumer bytes; no SCAR imports."""
import hashlib
import json
from pathlib import Path

HERE=Path(__file__).resolve().parent
ROOT=HERE.parents[2]
EXPS=ROOT/'artifacts/experiments'
CONT=EXPS/'first_stage_dependency_continuation_20261023/result/continuation.json'
STORES=(EXPS/'first_stage_partitioned_operand_routes_20261023/result/code-witnesses',
 EXPS/'model_run_dependency_gate_20261025/model/attempts/1792957279902353768-1410025/02-dependency-witness/archive')

def receipt(p):
 p=Path(p);h=hashlib.sha256();size=0
 with p.open('rb')as s:
  while b:=s.read(1048576):h.update(b);size+=len(b)
 return {'path':str(p.resolve()),'sha256':h.hexdigest(),'bytes':size}

def main():
 assert not(HERE/'freeze.json').exists()and not(HERE/'result.json').exists()
 assert CONT.stat().st_size<=8_000_000
 d=json.loads(CONT.read_bytes());parent=Path(d['parent']['directory'])/d['parent']['path']
 assert receipt(CONT)['sha256']=='c9ff2f87a0e90ee42297501d256d9d24aeeab60273c6172fe692c0323207173e'
 assert receipt(parent)['sha256']==d['parent']['raw_sha256']
 metadata={CONT,parent,*(s/'manifest.json'for s in STORES)};aux={}
 for row in d['source_files']:
  locators=[row['snapshot_artifact']]
  for provider in row['providers']:
   if provider['kind']=='INSTALLED_DISTRIBUTION':locators.extend((provider['metadata_artifact'],provider['record_artifact']))
  for locator in locators:
   if locator is None:continue
   artifact=locator['artifact'];base=parent.parent if locator['origin']=='PARENT'else CONT.parent
   assert locator['origin']in('PARENT','CONTINUATION')
   p=base/artifact['path'];assert p.is_file()and not p.is_symlink()and p.resolve()==p
   assert artifact['path'].split('/')[0]in('sources','providers')
   assert p.stat().st_size==artifact['compressed_bytes']
   aux[str(p)]={'path':str(p),'declared_decoded_bytes':artifact['canonical_bytes'],'canonical_sha256':artifact['canonical_sha256']}
   metadata.add(p)
 assert len(aux)==144
 inputs=[receipt(p)for p in sorted(metadata)]
 sources=[receipt(p)for p in sorted(set((ROOT/'scar').rglob('*.py'))|set(HERE.glob('*.py'))|set(HERE.glob('*.sh'))|{ROOT/'sitecustomize.py'})]
 result={'schema':'scar.lewm-external-entry-g0-freeze/1','sources':sources,'source_count':len(list((ROOT/'scar').rglob('*.py'))),
  'inputs':inputs,'auxiliary_metadata':list(aux.values()),'continuation':receipt(CONT),
  'archives':[{'directory':str(s),'manifest':receipt(s/'manifest.json')}for s in STORES],
  'budgets':{'actual_metadata_stored_plus_decoded':128_000_000,'single_metadata_record':8_000_000,'total_output_bytes':8_000_000,'wall_seconds':180},
  'unique_source_and_control_declared_bytes_at_prepare':sum(x['bytes']for x in sources+inputs),
  'source_payload_copies':False,'graph_payloads_hashed_or_decoded':False,'raw_read':False,'compile_lower_target':False}
 with(HERE/'freeze.json').open('x')as f:json.dump(result,f,sort_keys=True,indent=2);f.write('\n')
 print(json.dumps({'status':'PREPARED_NOT_RUN','freeze':receipt(HERE/'freeze.json'),'sources':result['source_count'],'metadata_files':len(inputs),'metadata_unique_stored_bytes':sum(x['bytes']for x in inputs),'auxiliary_metadata':len(aux)}))

if __name__=='__main__':main()
