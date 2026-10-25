"""Small receipts/stat plus code freeze; never opens retained SourcePrograms."""
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
    original=ROOT/'artifacts/experiments/module_import_prefix_g1_20261025/postflight01'
    prior=json.loads((original/'freeze.json').read_bytes())
    selection_old=json.loads((original/'selection.json').read_bytes())
    paths=['scar/analysis/program_lowering.py','scar/ir/program/source_subjects.py',
        'scar/ir/program/module_entries.py','scar/ir/program/control.py','scar/ir/program/model.py',
        'scar/ir/program/codec.py','scar/ir/program/control_validation.py']
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
    for version in (2,6,9):
        path=ROOT/('tests/fixtures/program_graph_v'+str(version)+'_frozen.json')
        measured=record(path)
        inputs.append(pin_from_receipt({'path':str(path),'stored_bytes':measured['bytes'],
            'stored_sha256':measured['sha256'],'decoded_bytes':measured['bytes'],
            'decoded_sha256':measured['sha256'],'receipt_origin':'SMALL_RETAINED_FROZEN_FIXTURE_HASH'}))
    programs=[]
    for version in (6,7):
        row=next(row for row in inputs if row['path'].endswith('/sourceprogram'+str(version)+'.json.gz'))
        programs.append({'source_schema_version':version,'uri':row['path'],
            **{key:row[key] for key in ('stored_bytes','stored_sha256','decoded_bytes','decoded_sha256')},
            'receipt_origin':('ORIGINAL_SP6_WRITER_RECEIPT' if version==6 else 'PRIOR_SP7_POSTFLIGHT_NEW_MEASUREMENT_NOT_OLD_WRITER')})
    selection={key:selection_old[key] for key in ('composition','witness_archive','archived_source','expected_unit','expected_census','files')}
    selection.update(schema='scar.frame-root-a-selection',schema_version=1,
        old_sourceprograms=programs,new_source_lowering=False,synthetic_scope='TYPE_CODEC_ONLY_NO_SOURCE_RUNTIME_PROOF')
    (BASE/'selection.json').write_bytes(raw(selection))
    runtime_paths=preload()
    runtime_paths.update(row['path'] for row in prior['runtime_sources'] if '/lib/python3.14/' in row['path'])
    runtime=[record(path) for path in sorted(runtime_paths)]
    small=[record(path) for path in (BASE/'run_gate.py',BASE/'prepare_freeze.py',BASE/'gate_guards.py',BASE/'selection.json',
        BASE.parent/'check_contract.py',BASE.parent/'check_legacy_guard.py',ROOT/'tests/fixtures/program_control_graphs.py')]
    source=[record(path) for path in sorted((ROOT/'scar').rglob('*.py'))]
    limits=dict(prior['limits'])
    freeze={'schema':'scar.frame-root-a-freeze','schema_version':1,'status':'FROZEN_NOT_RUN',
        'attempt':str(BASE/'attempt01'),'production_sources':production,'candidate_scar_sources':source,
        'runtime_sources':runtime,'small_frozen_files':small,'inputs':inputs,'limits':limits,
        'target_namespace_roots':prior['target_namespace_roots'],
        'allowed_composition_roots':prior['allowed_composition_roots'],
        'internal_check_inputs':[{'path':str(BASE/'freeze.json'),'role':'ROOT_APPROVED_FREEZE_SHA256','max_bytes':1000000}],
        'qualification':'A_SYNTHETIC_TYPES_AND_OLD_RETAINED_CONSUMERS_ONLY',
        'old_sourceprograms':programs,'whole_module_or_program_complete':False}
    guard_bytes=sum(row['bytes'] for row in source+runtime+small)
    if guard_bytes>limits['source_runtime_guard_bytes_per_pass']:raise ValueError('code guard bound')
    (BASE/'freeze.json').write_bytes(raw(freeze));frozen=record(BASE/'freeze.json')
    receipt={'status':'FROZEN_NOT_RUN','freeze':frozen,'attempt':freeze['attempt'],
        'production_sources':production,'candidate_source_files':len(source),'runtime_files':len(runtime),
        'input_stat_count':len(inputs),'guard_bytes_per_pass':guard_bytes,
        'declared_unique_stored_bytes':sum(row['stored_bytes'] for row in inputs),
        'declared_unique_gzip_decoded_bytes':sum(row['decoded_bytes'] for row in inputs if row['path'].endswith('.gz')),
        'limits':limits,'preparation_retained_graph_bodies_read':0,'new_lower_or_target':False,
        'scope':'TYPE_CODEC_AND_OLD_CONSUMER_COMPATIBILITY; NEW_MODULE_SOURCE_BODY_NOT_ATTEMPTED'}
    (BASE/'PREPARATION_RECEIPT.json').write_bytes(raw(receipt))
    print(json.dumps(receipt,indent=2))

if __name__=='__main__':main()
