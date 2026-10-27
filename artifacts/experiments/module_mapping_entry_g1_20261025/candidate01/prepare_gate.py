"""Freeze small headers, source code, dependency files and original input stat.

Does not construct CompositionIndex, open source layers/marshal, parse target,
compile, lower, execute, or prepare target source.
"""
import gzip
import hashlib
import json
from pathlib import Path
import sys
import run_gate

BASE=Path(__file__).resolve().parent
ROOT=BASE.parents[3]
MAIN=Path('/home/zyf/AAA/scar-worktrees/structured-program-model')

def raw(value):return (json.dumps(value,sort_keys=True,ensure_ascii=False,separators=(',',':'),allow_nan=False)+'\n').encode()
def sha(value):return hashlib.sha256(value).hexdigest()
def receipt(path):
    p=Path(path).resolve();b=p.read_bytes();return {'path':str(p),'bytes':len(b),'sha256':sha(b)}
def stat_row(path,stored_sha,decoded_bytes=None,decoded_sha=None):
    p=Path(path).resolve();s=p.stat()
    if p.is_symlink():raise ValueError('symlink input')
    return {'path':str(p),'size':s.st_size,'stored_bytes':s.st_size,'stored_sha256':stored_sha,
        'decoded_bytes':decoded_bytes,'decoded_sha256':decoded_sha,
        'mtime_ns':s.st_mtime_ns,'ctime_ns':s.st_ctime_ns,'inode':s.st_ino,'device':s.st_dev}

def main():
    if (BASE/'freeze.json').exists():raise ValueError('fresh candidate required; never overwrite freeze')
    design=json.loads((ROOT/'artifacts/analysis/module_mapping_entry_design_20261025/SOURCE_RECEIPTS.json').read_bytes())
    roots={Path(row['uri']).name:row for row in design['small_inputs']}
    composition=Path(roots['index.json.gz']['uri']);comp=json.loads(gzip.decompress(composition.read_bytes()))
    inventory=Path(comp['inventory']['path']);inv=json.loads(gzip.decompress(inventory.read_bytes()))
    layer_index=Path(comp['source_layers']['path']);layers=json.loads(layer_index.read_bytes())
    if len(comp['files'])!=1 or len(comp['files'][0]['module_roots'])!=1 or len(layers['files'])!=1:raise ValueError('one original module unit required')
    f=comp['files'][0];layer=layers['files'][0]
    witness_manifest=Path(roots['manifest.json']['uri']);witness=json.loads(witness_manifest.read_bytes())
    retention=MAIN/'artifacts/experiments/model_run_offline_g1_20261025/RETENTION.json';ret=json.loads(retention.read_bytes())
    retained={}
    def walk(value):
        if isinstance(value,dict):
            if {'uri','sha256','size_bytes'}<=set(value):retained[value['uri']]=value
            for child in value.values():walk(child)
        elif isinstance(value,list):
            for child in value:walk(child)
    walk(ret)
    archive=layer_index.parent/layer['archive'];old=retained[str(archive)]
    if old['size_bytes']!=layer['compressed_bytes']:raise ValueError('source archive stored header differs')
    inputs=[]
    for row in design['small_inputs']:
        inputs.append(stat_row(row['uri'],row['stored_sha256'],row['decoded_bytes'],row['decoded_sha256']))
    inputs.append(stat_row(layer_index,comp['source_layers']['raw_sha256'],comp['source_layers']['decoded_bytes'],comp['source_layers']['raw_sha256']))
    inputs.append(stat_row(archive,old['sha256'],layer['canonical_bytes'],layer['canonical_sha256']))
    counts=f['counts']
    expected_unit={'snapshot':f['snapshot'],'namespace_root':f['context']['namespace_root'],
        'initializer':{'kind':'opdef','value':f['module_roots'][0].removeprefix('opdef:'),'wire':f['module_roots'][0]}}
    selection={'schema':'scar.module-mapping-entry-selection','schema_version':1,
        'composition':str(composition),'witness_archive':str(witness_manifest.parent),
        'archived_source':roots[next(name for name in roots if name.endswith('.source.utf8'))]['uri'],
        'expected_unit':expected_unit,'expected_census':{'source_atoms':counts['source_atoms'],
            'semantic_operations':counts['semantic_operations'],'cfg_nodes':counts['cfg_nodes'],'cfg_edges':counts['cfg_edges']},
        'original_denominators':{'source':receipt(retention),'source_reread':False,'dynamic_raw_reread':False,
            'groups':9,'calls':design['original_counts']['all_calls'],'module_calls':design['observed_module']['call_weight'],
            'other_dynamic_domains_not_reclassified':True},
        'files':{'0':{'source_path':f['snapshot']['path'],'snapshot':f['snapshot']}}}
    (BASE/'selection.json').write_bytes(raw(selection))
    runtime=run_gate.preload()
    sources=[receipt(p) for p in sorted((ROOT/'scar').rglob('*.py'))]
    runtime=[receipt(p) for p in sorted(runtime)]
    production_names=('scar/analysis/program_lowering.py','scar/analysis/structured_lowering.py',
        'scar/analysis/source_frontend_worklist.py','scar/ir/program/module_entries.py',
        'scar/analysis/source_module_lowering.py','scar/analysis/source_module_validation.py')
    production=[receipt(ROOT/name) for name in production_names]
    small=[receipt(BASE/name) for name in ('run_gate.py','gate_guards.py','prepare_gate.py','selection.json')]
    guard_total=sum(row['bytes'] for row in sources+runtime+small)
    if guard_total>128_000_000:raise ValueError('freeze guard bound')
    freeze={'schema':'scar.module-mapping-entry-freeze','schema_version':1,'status':'FROZEN_NOT_RUN',
        'attempt':str(BASE/'attempt01'),'production_sources':production,'candidate_scar_sources':sources,
        'runtime_sources':runtime,'small_frozen_files':small,'inputs':inputs,
        'internal_check_inputs':[{'path':str(BASE/'freeze.json'),'role':'ROOT_APPROVED_FREEZE_SHA256','max_bytes':1000000}],
        'allowed_composition_roots':[str(composition)],'target_namespace_roots':[f['context']['namespace_root']],
        'limits':{'total_input_bytes':32_000_000,'record_context_bytes':4_000_000,'composition_root_bytes':4_000_000,
            'source_runtime_guard_bytes_per_pass':128_000_000,'source_files':1,'source_bytes':1_000_000,
            'operations_per_body':4000,'total_operations':4000,'worker_seconds':180,'outer_seconds':240,'output_bytes':16_000_000},
        'retained_input_io_scope':'every stored plus gzip-decoded byte, repeats included; code/runtime guard bytes separate and reported',
        'guard_bytes_per_pass':guard_total,'namespace_alias_established':False,'new_episode':False,
        'body_or_whole_program_completeness_established':False}
    data=raw(freeze);(BASE/'freeze.json').write_bytes(data)
    report={'status':'FROZEN_NOT_RUN','freeze_sha256':sha(data),'scar_source_files':len(sources),
        'runtime_files':len(runtime),'input_roots':len(inputs),'guard_bytes_per_pass':guard_total,
        'preparation_reads':'small composition/inventory/layer/witness/retention metadata and producer/runtime source hashes only; no source-layer archive/marshal opened',
        'actual_target_prepare':0,'actual_lower':0,'actual_target_compile':0,'actual_target_exec':0,
        'input_metadata_decoded_bytes':len(raw(comp))+len(raw(inv))+len(raw(layers))+len(raw(witness))+len(raw(ret))}
    (BASE/'PREPARATION_RECEIPT.json').write_bytes(raw(report));print(json.dumps(report,indent=2))
if __name__=='__main__':main()
