"""Freeze the new compiler consumer and its exact original source workset."""
from pathlib import Path
import hashlib
import json

HERE=Path(__file__).resolve().parent
ROOT=HERE.parents[2]
G0=Path('/home/zyf/AAA/scar-worktrees/structured-program-model/artifacts/experiments/lewm_external_entry_g0_20261026')

def receipt(p):
 p=Path(p);h=hashlib.sha256();n=0
 with p.open('rb')as stream:
  while raw:=stream.read(1048576):h.update(raw);n+=len(raw)
 return {'path':str(p.resolve()),'sha256':h.hexdigest(),'bytes':n}

def main():
 assert not(HERE/'freeze.json').exists()and not(HERE/'result').exists()
 g=json.loads((G0/'freeze.json').read_bytes());work=json.loads((HERE/'workset.json').read_bytes())
 inputs={r['path']:r for r in g['inputs']}
 for p in (G0/'freeze.json',G0/'result.json',G0/'catalog.json.gz',G0/'catalog-transport.json',HERE/'workset.json'):
  inputs[str(p)]=receipt(p)
 stores={}
 for decl in g['archives']:
  directory=Path(decl['directory']);paths=sorted(str(p)for p in directory.iterdir()if p.is_file());stores[str(directory)]=paths
  for name in paths:inputs[name]=receipt(name)
 for row in inputs.values():assert receipt(row['path'])==row
 sources=[receipt(p)for p in sorted(set((ROOT/'scar').rglob('*.py'))|set(HERE.glob('*.py'))|set(HERE.glob('*.sh'))|{ROOT/'sitecustomize.py'})]
 old=json.loads((ROOT/'artifacts/experiments/first_stage_source858_current_20261026/frozen/producer.json').read_bytes())
 runtime=[receipt(r['path'])for r in old['runtime']]
 names={'source_attachments.py','code_witness.py','compiler_witness_archives.py'}
 frozen={'schema':'scar.lewm-archived-compiler-consumer-freeze/1','sources':sources,'runtime':runtime,'source_count':len(list((ROOT/'scar').rglob('*.py'))),
  'inputs':sorted(inputs.values(),key=lambda r:r['path']),'original_G0_inputs':{'continuation':g['continuation'],'archives':g['archives']},'original_archive_directory_membership':stores,
  'modified_production_sources':[r for r in sources if Path(r['path']).name in names],
  'original_11969_production_source_receipts':[r for r in old['modules']if Path(r['path']).name in names],
  'original_11969_freeze':receipt(ROOT/'artifacts/experiments/first_stage_source858_current_20261026/frozen/producer.json'),
  'base_archive_commit':'6d4338ded34470c986e78c3295a8d65bc4b6bcf3','code_and_data_URI_roles_separate':True,
  'workset':receipt(HERE/'workset.json'),'selection':'exact original G0 automatic missing16/8 window; no name rules',
  'budgets':{'outer_seconds':180,'acquisition':work['normal_plan']['budget'],'compile_keys':8,'source_files':8,'normalized_source_bytes':1_000_000,'module_bytes':8_000_000,'archive_bytes':32_000_000,'record_report_bytes':8_000_000,'metadata_stored_plus_decoded':256_000_000,'code_archive_stored_read':64_000_000,'post_stage_total_output_bytes':64_000_000,'source_control_SHA_IO':'separately counted'},
  'compiled_during_freeze':False,'source_graphs_opened':False,'old_archives_modified':False,'payload_copies':False,'whole_program_established':False}
 with(HERE/'freeze.json').open('x')as f:json.dump(frozen,f,sort_keys=True,indent=2);f.write('\n')
 print(json.dumps({'status':'PREPARED_NOT_RUN','freeze':receipt(HERE/'freeze.json'),'source_count':frozen['source_count'],'runtime_files':len(runtime),'fixed_inputs':len(inputs),'input_unique_stored_bytes':sum(r['bytes']for r in inputs.values()),'production_sources':frozen['modified_production_sources'],'workset':frozen['workset']}))

if __name__=='__main__':main()
