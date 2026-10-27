"""Small metadata/stat preparation only; big inputs are checked by the real gate."""
from pathlib import Path
import ast
import hashlib
import json
import os
import stat
import sys
import sysconfig

from config import HERE, ROOT, ORIGINAL_GATE, BUDGETS, EXPECTED_RUN, CACHE
from report_archive import receipt, write_json


def main():
    if (HERE/'inputs.json').exists() or (HERE/'frozen').exists():
        raise ValueError('fresh preparation output required')
    original=json.loads((ORIGINAL_GATE/'inputs.json').read_bytes())
    expected={r['path']:r for r in original['inputs']}
    for name in ('inputs.json','summary.json','run.py','config.py','prepare.py','audit.py','report_archive.py'):
        r=receipt(ORIGINAL_GATE/name)
        expected[r['path']]=r
    missing=[]
    for r in expected.values():
        p=Path(r['path'])
        if not p.is_file():
            missing.append(r);continue
        if p.is_symlink() or p.resolve()!=p or p.stat().st_size!=r['bytes']:
            raise ValueError('noncanonical path or changed input stat: '+str(p))
    if missing:
        write_json(HERE/'PREPARATION_BLOCKED.json',{'status':'INPUT_MATERIALIZATION_REQUIRED',
            'missing':missing,'no_big_input_read':True})
        raise ValueError('required original pins absent: '+str(len(missing)))
    # Existing private CodeWitness archive must already meet its normal guard.
    # No permissions are changed here: approved original 700/600 is left alone.
    archive=[CACHE]+sorted(CACHE.iterdir())
    modes=[]
    for p in archive:
        st=p.lstat();wanted=0o700 if p.is_dir() else 0o600
        if st.st_uid!=os.geteuid() or stat.S_IMODE(st.st_mode)!=wanted or p.is_symlink():
            raise ValueError('required private archive mode/owner is not already strict: '+str(p))
        modes.append({'path':str(p),'mode':oct(wanted),'uid':st.st_uid,'bytes':st.st_size,
            'permission_mutated':False,'ctime_ns':st.st_ctime_ns})
    write_json(HERE/'ARCHIVE_PERMISSION_CHECK.json',{'checks':modes,'chmod_calls':0,
        'existing_qualified_files_left_unchanged':True})
    original.update(schema='scar.source-call-port-gate-inputs/1',consumer_worktree=str(ROOT),
        original_recipe=str(ORIGINAL_GATE),inputs=sorted(expected.values(),key=lambda r:r['path']),
        physical_input_bytes=sum(r['bytes'] for r in expected.values()),budgets=BUDGETS,
        preparation_mode='stat only for original data; SHA validation in start/final fixed-input guards',
        physical_raw_artifact_hashing_performed=False,raw_observation_scan_performed=False,
        cumulative_input_io='OPEN; 8GB ceiling applies to unique physical declarations, not stored+decoded IO')
    if original['physical_input_bytes']>BUDGETS['input_total_bytes']:
        raise ValueError('unique physical declarations exceed inherited 8GB ceiling')
    write_json(HERE/'inputs.json',original)
    sources=sorted(set((ROOT/'scar').rglob('*.py'))|set(HERE.glob('*.py'))|set(HERE.glob('*.sh'))|{ROOT/'sitecustomize.py'})
    for p in HERE.glob('*.py'):
        ast.parse(p.read_bytes(),filename=str(p))
    modules=[receipt(p) for p in sources]
    if sum(r['bytes'] for r in modules)>BUDGETS['producer_source_bytes']:
        raise ValueError('source freeze exceeds inherited source ceiling')
    prior=json.loads((ORIGINAL_GATE/'frozen/producer.json').read_bytes())
    runtime={Path(r['path']).resolve(strict=True) for r in prior['runtime']}
    stdlib=Path(sysconfig.get_path('stdlib')).resolve()
    for folder,dirs,files in os.walk(stdlib):
        dirs[:]=[d for d in dirs if d not in ('site-packages','__pycache__')]
        runtime.update((Path(folder)/name).resolve() for name in files if name.endswith('.py'))
    runtime.update(p.resolve() for p in (stdlib/'lib-dynload').glob('*.so') if p.is_file())
    runtime.add(Path(sys.executable).resolve(strict=True))
    library=Path(sysconfig.get_config_var('LIBDIR'))/sysconfig.get_config_var('LDLIBRARY')
    if library.is_file():runtime.add(library.resolve())
    runtime_rows=[receipt(p) for p in sorted(runtime)]
    frozen=HERE/'frozen';frozen.mkdir()
    write_json(frozen/'producer.json',{'schema':'scar.source-call-port-gate-freeze/1',
        'modules':modules,'runtime':runtime_rows,'fixed_inputs':receipt(HERE/'inputs.json'),
        'python':sys.version,'python_executable':sys.executable,'consumer_worktree':str(ROOT),
        'head_label_supplied_by_root':'e0a8e21ec2e014187e0957b4e05f2b7a02a57bbe',
        'head_label_role':'baseline navigation only; exact source bytes are identity',
        'all_scar_candidates_frozen':True,'unused_candidates_not_authority':True,
        'historical_collector_bytes_attested':False,'historical_runtime_debt_closed':False})
    report={'status':'FROZEN_NOT_RUN','producer':receipt(frozen/'producer.json'),
        'inputs':receipt(HERE/'inputs.json'),'source_files':len(modules),'runtime_files':len(runtime_rows),
        'unique_input_physical_bytes':original['physical_input_bytes'],'original_input_members':len(original['inputs']),
        'raw_scanned':False,'graphs_opened':False,'target_executed':False,'source_lowered':False,
        'source_prepared':False,'historical_capture_requalified':False,
        'launch_command':'bash '+str(HERE/'run.sh')}
    write_json(HERE/'PREPARATION_RECEIPT.json',report)
    print(json.dumps(report,sort_keys=True))


if __name__=='__main__':main()
