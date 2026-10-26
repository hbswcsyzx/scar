"""B preparation: only small receipts/stat/source freeze; no retained graph bodies."""
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
    original=ROOT/'artifacts/experiments/frame_root_contract_a_20261025/candidate01'
    prior=json.loads((original/'freeze.json').read_bytes())
    selection_old=json.loads((original/'selection.json').read_bytes())
    paths=['scar/analysis/program_lowering.py','scar/ir/program/module_entries.py',
        'scar/analysis/structured_lowering.py','scar/analysis/environment_lowering.py',
        'scar/analysis/source_module_lowering.py','scar/analysis/source_module_validation.py']
    production=[record(ROOT/path) for path in paths]
    baseline=BASE.parent/'baseline'
    patch=[]
    for path in paths:
        old=(baseline/path).read_text() if (baseline/path).exists() else ''
        new=(ROOT/path).read_text()
        patch.extend(difflib.unified_diff(old.splitlines(True),new.splitlines(True),fromfile='a/'+path,tofile='b/'+path))
    (BASE.parent/'PRODUCTION_A.patch').write_text(''.join(patch))
    inputs=[]
    for row in prior['inputs']:
        path=row['path']
        if '/model_run_offline_g0_20261025/' in path or path.endswith('/sourceprogram6.json.gz') or path.endswith('/sourceprogram7.json.gz'):
            inputs.append(pin_from_receipt(row))
    programs=[]
    for version in (6,7):
        row=next(row for row in inputs if row['path'].endswith('/sourceprogram'+str(version)+'.json.gz'))
        programs.append({'source_schema_version':version,'uri':row['path'],
            **{key:row[key] for key in ('stored_bytes','stored_sha256','decoded_bytes','decoded_sha256')},
            'receipt_origin':('ORIGINAL_SP6_WRITER_RECEIPT' if version==6 else 'PRIOR_SP7_POSTFLIGHT_NEW_MEASUREMENT_NOT_OLD_WRITER')})
    selection={key:selection_old[key] for key in ('composition','witness_archive','archived_source','expected_unit','expected_census','files')}
    selection.update(schema='scar.frame-root-a-selection',schema_version=1,
        old_sourceprograms=programs,new_source_lowering=True,allowed_module_lowerings=1,profile='STRUCTURED_MAPPING_314_V1',actual_runtime_binding=False)
    (BASE/'selection.json').write_bytes(raw(selection))
    runtime_paths=preload()
    runtime_paths.update(row['path'] for row in prior['runtime_sources'] if '/lib/python3.14/' in row['path'])
    runtime=[record(path) for path in sorted(runtime_paths)]
    small=[record(path) for path in (BASE/'run_gate.py',BASE/'prepare_freeze.py',BASE/'gate_guards.py',BASE/'selection.json',
        BASE.parent/'SYNTAX_API_CHECK.json')]
    source=[record(path) for path in sorted((ROOT/'scar').rglob('*.py'))]
    limits=dict(prior['limits'])
    freeze={'schema':'scar.module-prefix-b-freeze','schema_version':1,'status':'FROZEN_NOT_RUN',
        'attempt':str(BASE/'attempt01'),'production_sources':production,'candidate_scar_sources':source,
        'runtime_sources':runtime,'small_frozen_files':small,'inputs':inputs,'limits':limits,
        'target_namespace_roots':prior['target_namespace_roots'],
        'allowed_composition_roots':prior['allowed_composition_roots'],
        'internal_check_inputs':[{'path':str(BASE/'freeze.json'),'role':'ROOT_APPROVED_FREEZE_SHA256','max_bytes':1000000}],
        'qualification':'B_ONE_MODULE_SOURCE_PREFIX_AND_OLD_CONSUMERS_WITH_OPEN',
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
        'scope':'ONE_QUALIFIED_MODULE_PREFIX_SOURCE_LOWERING; ACTUAL_RUNTIME_ABI_UNPROVEN'}
    (BASE/'PREPARATION_RECEIPT.json').write_bytes(raw(receipt))
    print(json.dumps(receipt,indent=2))

if __name__=='__main__':main()
