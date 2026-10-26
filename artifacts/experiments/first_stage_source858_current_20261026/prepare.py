"""Freeze consumer/source/runtime and original artifact bytes, without SCAR imports.

Hashing physical raw artifacts is not parsing/replaying observations. No graph
is decoded here. Historical producer files are their immutable archived copies.
"""
from pathlib import Path
import ast
import gzip
import json
import os
import sys
import sysconfig
from config import (HERE, ROOT, DATA_ROOT, EXPS, OLD, PRIOR_GATE, KWARGS, REMAINDER,
    DELIVERY, COMPOSITION, CAPTURE, CACHE, PROFILE, BRIDGE, ATTACHMENT, DESIGN,
    STALE_SOURCE, EXPECTED_RUN, EXPECTED_COMPOSITION_SHA, EXPECTED_MANIFEST_SHA,
    BUDGETS, FRAME_BUDGET, OPERAND_BUDGET, ROUTE_BUDGET)
from report_archive import receipt, write_json


def ordinary(path):
    path=Path(path)
    if not path.is_absolute() or path.resolve(strict=True)!=path or path.is_symlink() or not path.is_file():
        raise ValueError('not an exact canonical ordinary artifact: '+str(path))
    return path


def load(path, *, limit=BUDGETS['metadata_decoded_bytes']):
    path=ordinary(path)
    if path.stat().st_size>limit:raise ValueError('stored metadata exceeds ceiling')
    with (gzip.open(path,'rb') if path.suffix=='.gz' else path.open('rb')) as stream:
        payload=stream.read(limit+1)
    if len(payload)>limit:raise ValueError('decoded metadata exceeds ceiling')
    return json.loads(payload)


def check(row):
    path=ordinary(row['path'])
    if path.stat().st_size>BUDGETS['input_file_bytes'] or receipt(path)!=row:
        raise ValueError('fixed input differs: '+str(path))


def tree(directory):
    directory=Path(directory)
    if directory.is_symlink() or directory.resolve(strict=True)!=directory:
        raise ValueError('noncanonical input directory')
    paths=list(directory.rglob('*'))
    if any(p.is_symlink() for p in paths):raise ValueError('symlink in immutable input directory')
    return sorted(str(p)for p in paths if p.is_file())


def external_expected(ref):
    return {'path':ref['uri'],'sha256':ref['physical_sha256'],'bytes':ref['physical_bytes']}


def main():
    if (HERE/'inputs.json').exists() or (HERE/'frozen').exists():
        raise ValueError('freeze preparation must have fresh output')
    design=load(DESIGN)
    programs=design['post843_programs']
    if len(programs)!=15 or len({(r['file_index'],r['body_index'])for r in programs})!=15:
        raise ValueError('original post843 window changed')
    outside={r['source_program']['uri']for r in programs if r['batch']=='843_to_846'}
    if len(outside)!=3:raise ValueError('exact three cross-tree original artifacts required')
    paths=set();expected={}
    def add(row):
        path=ordinary(row['path'])
        if not path.is_relative_to(DATA_ROOT/'artifacts') and str(path)not in outside:
            raise ValueError('artifact outside original main data or exact three-SP5 whitelist: '+str(path))
        if row['path']in expected and expected[row['path']]!=row:raise ValueError('contradictory input receipt')
        expected[row['path']]=row;paths.add(str(path))
    prior=load(PRIOR_GATE/'inputs.json')
    for row in prior['inputs']:add(row)
    for row in programs:
        for field in ('source_program','checkpoint'):add(external_expected(row[field]))
    # New publication wrappers/components only; original program URIs stay unchanged.
    directories=(CAPTURE/'trace',CACHE,KWARGS/'result/publication',REMAINDER/'result/publication')
    for directory in directories:
        paths.update(tree(directory))
    paths.update(map(str,(COMPOSITION,KWARGS/'result/composition/index.json.gz',
        PRIOR_GATE/'inputs.json',PRIOR_GATE/'summary.json',DELIVERY/'result.json',
        DELIVERY/'terminal-receipt.json',KWARGS/'postflight01/receipt.json',DESIGN,
        OLD/'frozen/producer.json',OLD/'participating-producer.json',PROFILE,BRIDGE,ATTACHMENT)))
    for source in (OLD/'result/source',STALE_SOURCE):
        paths.update(str(source/name)for name in ('report.json','bindings.json'))
    if len(paths)>BUDGETS['input_files']:raise ValueError('fixed file-count ceiling')
    rows=[];total=0
    for path in sorted(paths):
        path=ordinary(path)
        if not path.is_relative_to(DATA_ROOT/'artifacts') and str(path)not in outside:
            raise ValueError('unlisted cross-tree artifact')
        row=receipt(path)
        if row['bytes']>BUDGETS['input_file_bytes']:raise ValueError('fixed per-file ceiling')
        if str(path)in expected and row!=expected[str(path)]:raise ValueError('saved original physical receipt changed: '+str(path))
        total+=row['bytes'];rows.append(row)
        if total>BUDGETS['input_total_bytes']:raise ValueError('fixed unique physical-input ceiling')
    if receipt(COMPOSITION)['sha256']!=EXPECTED_COMPOSITION_SHA or receipt(REMAINDER/'result/publication/manifest.json')['sha256']!=EXPECTED_MANIFEST_SHA:
        raise ValueError('formal858 root mismatch')
    # Validate small original CP2 records; do not open the SourceProgram graph payloads.
    for row in programs:
        cp=load(row['checkpoint']['uri'],limit=1_000_000)
        if cp['schema_version']!=2 or cp['source_program']!=row['source_program'] or cp['body_identity']!=row['checkpoint']['body_identity']:
            raise ValueError('original CP2/program/body identity differs')
    write_json(HERE/'inputs.json',{'schema':'scar.source858-current-inputs/1',
      'consumer_worktree':str(ROOT),'original_data_root':str(DATA_ROOT),'run':EXPECTED_RUN,
      'inputs':rows,'physical_input_bytes':total,'directories':{str(p):tree(p)for p in directories},
      'post843_programs':programs,'exact_cross_tree_program_whitelist':sorted(outside),
      'previous_source_directory':str(OLD/'result/source'),'readonly_code_witness_uri':str(CACHE),
      'coordinate_profile_uri':str(PROFILE),'dispatch_bridge_uri':str(BRIDGE),
      'published_composition_uri':str(COMPOSITION),'resume_source_directory':None,
      'budgets':BUDGETS,'frame_budget':FRAME_BUDGET,'operand_budget':OPERAND_BUDGET,'route_budget':ROUTE_BUDGET,
      'physical_raw_artifact_hashing_performed':True,'raw_observation_scan_performed':False,
      'source_prepared':False,'source_lowered':False,'code_compiled':False,'target_executed':False,
      'physical_bytes_role':'unique fixed input declarations, not cumulative all-call stored+decoded I/O',
      'cumulative_input_io':'OPEN','first_stage_complete':False})
    sources=sorted(set((ROOT/'scar').rglob('*.py'))|set(HERE.glob('*.py'))|set(HERE.glob('*.sh'))|{ROOT/'sitecustomize.py'})
    for p in HERE.glob('*.py'):ast.parse(p.read_bytes(),filename=str(p))
    modules=[receipt(ordinary(p))for p in sources]
    if sum(r['bytes']for r in modules)>BUDGETS['producer_source_bytes']:raise ValueError('consumer-source ceiling')
    # Broad stdlib closure avoids adding a missing lazy stdlib source after a long run.
    # Original prior runtime pins are location candidates only; hash current bytes.
    runtime=set()
    for row in load(DELIVERY/'freeze.json')['runtime']:
        p=Path(row['path']).resolve(strict=True)
        if p.is_file():runtime.add(p)
    stdlib=Path(sysconfig.get_path('stdlib')).resolve()
    for folder,dirs,files in os.walk(stdlib):
        dirs[:]=[d for d in dirs if d not in ('site-packages','__pycache__')]
        runtime.update((Path(folder)/name).resolve()for name in files if name.endswith('.py'))
    for module in tuple(sys.modules.values()):
        name=getattr(module,'__file__',None)
        if name and Path(name).is_file():
            p=Path(name).resolve()
            if not p.is_relative_to(ROOT):runtime.add(p)
    runtime.update(p.resolve()for p in (stdlib/'lib-dynload').glob('*.so')if p.is_file())
    runtime.add(Path(sys.executable).resolve(strict=True))
    libdir=Path(sysconfig.get_config_var('LIBDIR'))
    library=libdir/sysconfig.get_config_var('LDLIBRARY')
    if library.is_file():runtime.add(library.resolve())
    runtime_rows=[receipt(p)for p in sorted(runtime)]
    frozen=HERE/'frozen';frozen.mkdir()
    write_json(frozen/'producer.json',{'schema':'scar.source858-current-consumer-freeze/1',
      'modules':modules,'runtime':runtime_rows,'fixed_inputs':receipt(HERE/'inputs.json'),
      'python':sys.version,'python_executable':sys.executable,'consumer_worktree':str(ROOT),
      'head_label_supplied_by_root':'496302ea','head_label_role':'navigation only; exact bytes are identity',
      'current_source_count':len(list((ROOT/'scar').rglob('*.py'))),
      'source_payload_copies':False,'all_scar_candidates_frozen':True,
      'unused_candidates_not_authority':True,'historical_collector_bytes_attested':False,
      'historical_runtime_debt_closed':False,'target_executed':False,'raw_observations_scanned':False})
    print(json.dumps({'status':'PREPARED_NOT_RUN','inputs':len(rows),'unique_input_physical_bytes':total,
      'consumer_sources':len(list((ROOT/'scar').rglob('*.py'))),'runtime_files':len(runtime_rows),
      'runtime_stored_bytes':sum(r['bytes']for r in runtime_rows),
      'freeze':receipt(frozen/'producer.json'),'inputs_receipt':receipt(HERE/'inputs.json')},sort_keys=True))


if __name__=='__main__':main()
