"""Frozen W2/W3 public CLI acceptance; preserve all original evidence."""
from __future__ import annotations
from collections import Counter
import gzip
import hashlib
import json
import os
from pathlib import Path
import subprocess
import sys
import time

BASE = Path(__file__).resolve().parent.parent
OLD = BASE.parent / 'generic_gpu'
SCAR = Path('/tmp/scar-call-windows-qx_qw6dk')
PROJECT = BASE / 'inputs/project'
EXPECTED_HEAD = '8a300eb068d992b3737eee0bdf43fa2bf8c8aea1'
EXPECTED_FP = '38dfe6c34545b405fa5e8f08e2828f7357c862527500a6a1f2b3d97072796574'
sys.path.insert(0, str(SCAR))
from scripts.run_gate import fingerprint


def save(path, document):
    path.write_text(json.dumps(document, indent=2, sort_keys=True, allow_nan=False) + '\n')


def sha(path):
    digest = hashlib.sha256()
    with path.open('rb') as stream:
        for block in iter(lambda: stream.read(1024 * 1024), b''):
            digest.update(block)
    return digest.hexdigest()


def manifest(root):
    return [{'path':str(path.relative_to(root)), 'bytes':path.stat().st_size,'sha256':sha(path)}
            for path in sorted(root.rglob('*')) if path.is_file()]


def read(path):
    with gzip.open(path, 'rt') if path.suffix == '.gz' else path.open() as stream:
        return json.load(stream)


def main():
    receipt_path = BASE / 'reports/receipt.json'
    if receipt_path.exists() or (BASE / 'raw').exists():
        raise RuntimeError('refusing to overwrite a previous acceptance run')
    environment = {key:os.environ[key] for key in ('PATH','HOME','CONDA_PREFIX','CONDA_DEFAULT_ENV','LD_LIBRARY_PATH') if key in os.environ}
    environment.update(PYTHONPATH=str(SCAR),PYTHONDONTWRITEBYTECODE='1',PYTHONUNBUFFERED='1',LANG='C.UTF-8',LC_ALL='C.UTF-8',TZ='UTC')
    receipt = {'schema':'scar.windows-gpu-acceptance','schema_version':1,'status':'INITIALIZING',
               'expected_head':EXPECTED_HEAD,'expected_source_fingerprint':EXPECTED_FP,
               'source_root':str(SCAR),'project_root':str(PROJECT),'environment':environment,
               'python':sys.version,'commands':[],'source_checks':[],
               'tensor_values_saved':False,'whole_program_complete':False,'transformation_authorized':False}
    begun = time.perf_counter()
    old_before = None

    def update():
        receipt['elapsed_seconds'] = time.perf_counter() - begun
        save(receipt_path,receipt)

    def check_source(label):
        digest, files = fingerprint()
        record={'label':label,'sha256':digest,'matches_expected':digest==EXPECTED_FP}
        receipt['source_checks'].append(record)
        save(BASE/'manifest'/('source-'+label+'.json'),{'fingerprint':digest,'files':files})
        update()
        if digest != EXPECTED_FP:
            raise RuntimeError('source fingerprint changed at '+label)

    def command(name, argv, *, cwd=SCAR):
        stdout, stderr, timing = [BASE/'logs'/(name+suffix) for suffix in ('.stdout','.stderr','.time-v.txt')]
        exact=['/usr/bin/time','-v','-o',str(timing),'--',*map(str,argv)]
        entry={'name':name,'argv':exact,'logical_argv':list(map(str,argv)),'cwd':str(cwd),'env':environment,
               'stdout':str(stdout),'stderr':str(stderr),'time_v':str(timing),'status':'RUNNING','started_unix':time.time()}
        receipt['commands'].append(entry);receipt['status']='RUNNING_'+name;update()
        start=time.perf_counter()
        with stdout.open('xb') as out, stderr.open('xb') as err:
            result=subprocess.run(exact,cwd=cwd,env=environment,stdout=out,stderr=err,timeout=180)
        entry.update(returncode=result.returncode,wall_seconds=time.perf_counter()-start,
                     stdout_bytes=stdout.stat().st_size,stderr_bytes=stderr.stat().st_size,
                     status='PASSED' if result.returncode==0 else 'FAILED')
        metrics={}
        for line in timing.read_text().splitlines():
            if ': ' in line:
                key,value=line.strip().split(': ',1);metrics[key]=value
        entry['time_v_metrics']=metrics
        update()
        if result.returncode != 0:
            raise RuntimeError(name+' failed; preserved stdout/stderr and original inputs')
        return stdout

    def cli(name,*args):
        check_source('before-'+name)
        result=command(name,[sys.executable,'-m','scar.cli',*map(str,args)])
        check_source('after-'+name)
        return result

    try:
        check_source('before')
        head=command('source-head-before',['git','rev-parse','HEAD']).read_text().strip()
        if head != EXPECTED_HEAD: raise RuntimeError('unexpected frozen HEAD')
        dirty=command('source-status-before',['git','status','--porcelain=v1']).read_text()
        if dirty: raise RuntimeError('frozen source worktree is dirty')
        old_before=manifest(OLD)
        save(BASE/'manifest/old-inputs-before.json',{'root':str(OLD),'files':old_before})
        # W2 first: independently replay original v1/raw rule without rewriting it.
        output=cli('legacy-check','check-operand-links',OLD/'reports/operands.json.gz')
        receipt['legacy_replay']=json.loads(output.read_text())
        assert receipt['legacy_replay']['status']=='REPLAYED_CONDITIONAL_ROUTES'
        save(BASE/'manifest/new-inputs.json',{'files':manifest(BASE/'inputs'),
             'program_driver_sha256':sha(BASE/'drivers/gpu_program.py'),'acceptance_driver_sha256':sha(Path(__file__))})
        command('gpu-before',['nvidia-smi','--query-gpu=index,name,uuid,memory.total,memory.used,driver_version','--format=csv,noheader'])
        untraced=command('untraced-original',[sys.executable,BASE/'drivers/gpu_program.py'])
        receipt['untraced_runtime']=json.loads(untraced.read_text().splitlines()[-1]);update()
        raw=BASE/'raw'; inventory=BASE/'reports/inventory.json.gz'; operands=BASE/'reports/operands.json.gz'
        captured=cli('trace','trace','--call-operands','--operand-capture','windows',
            '--project-root',PROJECT,'--out',raw,'--max-call-events','100000','--max-call-bytes','64000000',
            '--max-operand-events','100000','--max-operand-bytes','32000000','--',sys.executable,BASE/'drivers/gpu_program.py')
        runtime=[line for line in captured.read_text().splitlines() if 'CUDA_AUTOGRAD_COMPLETED' in line]
        assert len(runtime)==1
        receipt['traced_runtime']=json.loads(runtime[0]);update()
        cli('inventory','inventory-program',PROJECT/'entry.py','--project-root',PROJECT,'--calls',raw,'--out',inventory)
        cli('link','link-operands',raw,'--project-root',PROJECT,'--inventory',inventory,'--out',operands)
        cli('check','check-operand-links',operands)
        inv,document=read(inventory),read(operands)
        names={item['id']['wire']:item['qualname'] for file in inv['files'] for item in file['definitions']}
        analysis=document['analysis'];routing=analysis['routing']
        assert len(analysis['operand_metadata'])==1
        metadata=analysis['operand_metadata'][0]
        assert metadata['rule']=='CPYTHON_CALL_WINDOWS_V1'
        assert not metadata['errors'] and not metadata['dropped_events'] and not metadata['io_failed']
        assert not metadata['gaps']
        receipt['inventory_summary']=inv['summary'];receipt['link_summary']=analysis['summary']
        receipt['operand_metadata']=metadata
        runs=sorted([item for item in routing['returns'] if names[item['definition']['wire']]=='run'],key=lambda item:item['invocation']['invocation_id'])
        assert len(runs)==2
        queries=[]
        for mode,root in zip(('distinct','shared'),runs):
            invocation=root['invocation']
            output=cli('query-'+mode,'query-operand-refs',operands,
                '--process',invocation['process_id'],'--thread',invocation['thread_id'],'--invocation',invocation['invocation_id'])
            queried=json.loads(output.read_text());save(BASE/'reports'/('query-'+mode+'.json'),queried)
            query=queried['query']
            assert [(item['invocation'],names[item['definition']['wire']],item['formal_name']) for item in query['endpoints']]==[(invocation,'run','x')]
            assert query['conditional_only'] and len(query['conditions'])==8 and query['obligations']
            assert not any(query[key] for key in ('function_environment_established','contents_or_effects_established','world_equivalence_established','transformation_authorized'))
            assert not any(analysis[key] for key in ('target_executed_by_linker','function_environment_established','contents_or_effects_established','world_equivalence_established','whole_program_complete','transformation_authorized'))
            completions=[step['completion'] for step in query['routes'] if step['kind']=='COMPLETION']
            assert len(completions)==2
            siblings=sorted([route for route in routing['completion_routes'] if route['caller']==invocation and names[route['callee_definition']['wire']]=='relay'],key=lambda route:route['attempt']['index'])
            assert len(siblings)==2
            first,=[route for route in completions if route['caller']==invocation]
            assert first['callee']==siblings[0]['callee']
            chosen,=[route for route in completions if route['caller']==first['callee']]
            assert names[chosen['callee_definition']['wire']]=='choose'
            owners=[node['invocation'] for node in query['nodes']]
            second_choose=[route['callee'] for route in routing['completion_routes'] if route['caller']==siblings[1]['callee']]
            assert siblings[1]['callee'] not in owners and not any(owner in owners for owner in second_choose)
            queries.append({'mode':mode,'invocation':invocation,'endpoint':'run.x','selected_relay':first['callee'],
                            'selected_choose':chosen['callee'],'excluded_relay':siblings[1]['callee'],'excluded_choose':second_choose,
                            'conditions':query['conditions'],'issues':dict(Counter(issue['kind'] for issue in query['issues'])),
                            'completion_routes':len(completions),'routes':len(query['routes'])})
        choose={}
        for route in routing['argument_routes']:
            if names[route['callee_definition']['wire']]=='choose':
                key=tuple(route['callee'][name] for name in ('process_id','thread_id','invocation_id'))
                choose.setdefault(key,[]).append(route)
        assert len(choose)==4
        for routes in choose.values():
            assert len(routes)==2 and {route['actual_index'] for route in routes}=={0,1}
            assert len({route['actual_use']['wire'] for route in routes})==2
            assert len({(route['load_anchor']['index'],route['load_suboperand']) for route in routes})==2
        receipt['validation']={'queries':queries,'choose_invocations':len(choose),'choose_argument_routes':sum(map(len,choose.values())),
                               'independent_uses_and_occurrences':True,'authority_remains_false':True,'conditions_per_query':8,
                               'legacy_replay_passed':True,'inventory_schema_version':inv['schema_version']}
        receipt['raw_metadata']=[read(path) for path in sorted(raw.glob('*meta*'))]
        assert all(not meta['errors'] and not meta['dropped_events'] and not meta['io_failed'] for meta in receipt['raw_metadata'])
        assert all(meta.get('path_gaps',0)==0 and meta.get('gaps',0)==0 for meta in receipt['raw_metadata'])
        save(BASE/'manifest/new-raw.json',{'root':str(raw),'files':manifest(raw)})
        command('gpu-after',['nvidia-smi','--query-gpu=index,name,uuid,memory.total,memory.used,driver_version','--format=csv,noheader'])
        assert command('source-head-after',['git','rev-parse','HEAD']).read_text().strip()==EXPECTED_HEAD
        assert not command('source-status-after',['git','status','--porcelain=v1']).read_text()
        receipt['status']='W2_W3_PUBLIC_GPU_PASSED'
    except BaseException as error:
        receipt['status']='FAILED_RETAINED';receipt['error']=type(error).__name__+': '+str(error)
        raise
    finally:
        try:
            old_after=manifest(OLD)
            save(BASE/'manifest/old-inputs-after.json',{'root':str(OLD),'files':old_after})
            receipt['old_inputs_unchanged']=old_before is not None and old_before==old_after
            if not receipt['old_inputs_unchanged']:receipt['status']='FAILED_OLD_INPUT_CHANGE_OR_UNVERIFIED'
            check_source('after')
        except BaseException as error:
            receipt['status']='FAILED_FINAL_VERIFICATION';receipt['final_error']=type(error).__name__+': '+str(error)
        receipt['commands_total_wall_seconds']=sum(item.get('wall_seconds',0) for item in receipt['commands'])
        receipt['artifact_bytes_before_final_manifest']=sum(path.stat().st_size for path in BASE.rglob('*') if path.is_file())
        update()
        files=manifest(BASE)
        save(BASE/'manifest/all-files.json',{'files':files,'bytes_excluding_this_manifest':sum(item['bytes'] for item in files),'excludes':'manifest/all-files.json itself'})
    print(json.dumps({'status':receipt['status'],'receipt':str(receipt_path),'commands':len(receipt['commands'])}))
    if receipt['status']!='W2_W3_PUBLIC_GPU_PASSED':raise SystemExit(1)


if __name__=='__main__':main()
