"""C reader-only postflight preparation; no retained graph bodies or lowering."""
import difflib
import hashlib
import json
from pathlib import Path
import sys
from run_gate import BASE, ROOT, preload, raw

def record(path):
    path=Path(path).resolve();data=path.read_bytes()
    if path.is_symlink():raise ValueError('symlink code/input')
    return {'path':str(path),'bytes':len(data),'sha256':hashlib.sha256(data).hexdigest()}

def pin_from_receipt(row):
    row=dict(row);path=Path(row['path']);stat=path.stat()
    if path.is_symlink() or stat.st_size!=row['stored_bytes']:raise ValueError('retained pin size differs')
    row.update(size=stat.st_size,mtime_ns=stat.st_mtime_ns,ctime_ns=stat.st_ctime_ns,inode=stat.st_ino,device=stat.st_dev)
    return row

def main():
    if (BASE/'freeze.json').exists():raise FileExistsError('freeze exists')
    original=ROOT/'artifacts/experiments/module_try_propagation_g1_20261026/candidate01'
    prior=json.loads((original/'freeze.json').read_bytes())
    selection_old=json.loads((original/'selection.json').read_bytes())
    paths=['scar/analysis/program_lowering.py','scar/ir/program/module_entries.py',
        'scar/analysis/structured_lowering.py','scar/analysis/source_statement_lowering.py',
        'scar/analysis/source_module_lowering.py','scar/analysis/source_module_validation.py']
    production=[record(ROOT/path) for path in paths]
    inputs=[]
    for row in prior['inputs']:
        path=row['path']
        if '/model_run_offline_g0_20261025/' in path:
            inputs.append(pin_from_receipt(row))
    receipt=json.loads((original/'attempt01/sourceprogram8-propagation-receipt.json').read_bytes())
    inputs.append(pin_from_receipt({'path':receipt['uri'],**{key:receipt[key] for key in ('stored_bytes','stored_sha256','decoded_bytes','decoded_sha256')},'receipt_origin':'ORIGINAL_C_WRITER; NOT A NEW LOWERING'}))
    programs=[{'source_schema_version':8,**receipt,'receipt_origin':'ORIGINAL_C_WRITER; NOT A NEW LOWERING'}]
    for path in (original/'freeze.json',original/'attempt01/result.json',original/'attempt01/failure.json',
        original/'attempt01/sourceprogram8-propagation-receipt.json',original/'attempt01/progress.jsonl',original/'attempt01/stderr.log'):
        measured=record(path)
        inputs.append(pin_from_receipt({'path':str(path),'stored_bytes':measured['bytes'],'stored_sha256':measured['sha256'],
            'decoded_bytes':measured['bytes'],'decoded_sha256':measured['sha256'],'receipt_origin':'PINNED_ORIGINAL_C_FAILURE_METADATA'}))
    selection={key:selection_old[key] for key in ('composition','witness_archive','archived_source','expected_unit','expected_census','files')}
    selection.update(schema='scar.module-propagation-c-postflight-selection',schema_version=1,
        old_sourceprograms=programs,new_source_lowering=False,allowed_module_lowerings=0,profile='STRUCTURED_MAPPING_PROPAGATION_314_V1',actual_runtime_binding=False)
    selection.update(original_freeze=str(original/'freeze.json'),original_freeze_sha256=hashlib.sha256((original/'freeze.json').read_bytes()).hexdigest(),
        original_result=str(original/'attempt01/result.json'),original_failure=str(original/'attempt01/failure.json'))
    (BASE/'selection.json').write_bytes(raw(selection))
    runtime_paths=preload()
    runtime_paths.update(row['path'] for row in prior['runtime_sources'] if '/lib/python3.14/' in row['path'])
    runtime=[record(path) for path in sorted(runtime_paths)]
    small=[record(path) for path in (BASE/'run_gate.py',BASE/'prepare_freeze.py',BASE/'gate_guards.py',BASE/'selection.json',
        BASE.parent/'SYNTAX_API_CHECK.json')]
    source=[record(path) for path in sorted((ROOT/'scar').rglob('*.py'))]
    limits=dict(prior['limits'])
    freeze={'schema':'scar.module-propagation-c-postflight-freeze','schema_version':1,'status':'FROZEN_NOT_RUN',
        'attempt':str(BASE/'attempt01'),'production_sources':production,'candidate_scar_sources':source,
        'runtime_sources':runtime,'small_frozen_files':small,'inputs':inputs,'limits':limits,
        'target_namespace_roots':prior['target_namespace_roots'],
        'allowed_composition_roots':prior['allowed_composition_roots'],
        'internal_check_inputs':[{'path':str(BASE/'freeze.json'),'role':'ROOT_APPROVED_FREEZE_SHA256','max_bytes':1000000}],
        'qualification':'CURRENT_C_NORMAL_READER_POSTFLIGHT_ONLY_WITH_OPEN',
        'old_sourceprograms':programs,'whole_module_or_program_complete':False}
    guard_bytes=sum(row['bytes'] for row in source+runtime+small)
    if guard_bytes>limits['source_runtime_guard_bytes_per_pass']:raise ValueError('code guard bound')
    (BASE/'freeze.json').write_bytes(raw(freeze));frozen=record(BASE/'freeze.json')
    receipt={'status':'FROZEN_NOT_RUN','freeze':frozen,'attempt':freeze['attempt'],
        'production_sources':production,'candidate_source_files':len(source),'runtime_files':len(runtime),
        'input_stat_count':len(inputs),'guard_bytes_per_pass':guard_bytes,
        'declared_unique_stored_bytes':sum(row['stored_bytes'] for row in inputs),
        'declared_unique_gzip_decoded_bytes':sum(row['decoded_bytes'] for row in inputs if row['path'].endswith('.gz')),
        'limits':limits,'preparation_retained_graph_bodies_read':0,'preparation_module_lowerings':0,'target_compile_exec_or_fresh_prepare':0,
        'scope':'CURRENT_RETAINED_C_GRAPH_READER_ONLY; ORIGINAL_EXIT1_UNCHANGED; UNRECORDED_ORIGINAL_METRICS_OPEN'}
    (BASE/'PREPARATION_RECEIPT.json').write_bytes(raw(receipt))
    print(json.dumps(receipt,indent=2))

if __name__=='__main__':main()
