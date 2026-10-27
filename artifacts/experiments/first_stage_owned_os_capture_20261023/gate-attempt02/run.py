"""One real opt-in CLI capture; bounded original bytes/public profile checks."""
import gzip
import hashlib
import json
import os
from pathlib import Path
import resource
import subprocess
import sys
import time


HERE=Path(__file__).resolve().parent
ROOT=HERE.parents[3]


def receipt(path):
    raw=Path(path).read_bytes()
    return {'path':str(Path(path).absolute()),'bytes':len(raw),'sha256':hashlib.sha256(raw).hexdigest()}


def write(name,value):
    with (HERE/name).open('x') as stream:json.dump(value,stream,indent=2,sort_keys=True);stream.write('\n')


def main():
    started=time.monotonic();freeze=json.loads((HERE.parent/'static-freeze-guard-revised.json').read_bytes())
    for row in freeze['files']:assert receipt(ROOT/row['relative'])['sha256']==row['sha256']
    capture=HERE/'capture'
    argv=[sys.executable,'-m','scar.cli','trace','--call-operands','--execution-evidence',
        '--project-root',str(HERE),'--out',str(capture/'trace'),'--os-capture-root',str(capture),
        '--max-call-events','20000','--max-call-bytes','16000000',
        '--max-operand-events','40000','--max-operand-bytes','32000000',
        '--max-os-bytes','64000000','--max-os-lines','200000',
        '--max-capture-bytes','128000000','--max-archive-bytes','64000000','--os-timeout','120',
        '--',sys.executable,str(HERE/'target.py')]
    env=dict(os.environ,PYTHONPATH=str(ROOT),PYTHONDONTWRITEBYTECODE='1',CUDA_VISIBLE_DEVICES='',
        OMP_NUM_THREADS='1',OPENBLAS_NUM_THREADS='1',MKL_NUM_THREADS='1')
    for key in tuple(env):
        if key.startswith('SCAR_'):env.pop(key)
    producer={'schema':'scar.owned-os-capture-gate-producer','schema_version':1,
        'revision':subprocess.check_output(['git','rev-parse','HEAD'],cwd=ROOT,text=True).strip(),
        'argv':argv,'source_freeze':receipt(HERE.parent/'static-freeze-guard-revised.json'),'script':receipt(__file__),
        'target':receipt(HERE/'target.py'),'cpu_only_environment':{key:env[key] for key in
            ('CUDA_VISIBLE_DEVICES','OMP_NUM_THREADS','OPENBLAS_NUM_THREADS','MKL_NUM_THREADS')},
        'scope':'ONE own CPU target; offline checks only; no LeWM/historical raw'}
    write('producer.json',producer)
    with (HERE/'cli.stdout.txt').open('xb') as stdout,(HERE/'cli.stderr.txt').open('xb') as stderr:
        result=subprocess.run(argv,env=env,cwd=ROOT,stdout=stdout,stderr=stderr,check=False)
    write('cli-exit.json',{'actual_exit':result.returncode})
    assert result.returncode==0,'CLI failed; preserve attempt, do not rerun target'
    coords=json.loads((capture/'capture-coordinates.json').read_bytes())
    binding=coords['os_capture_provider'];profile_path=Path(binding['profile']['uri']);launch_path=Path(binding['launch']['uri'])
    from scar.trace.os_capture_coverage import OSCaptureCoverage
    from scar.trace.os_resources import _scan
    from scar.ir.record_codec import encode
    cov=OSCaptureCoverage.read(profile_path,launch=launch_path,coordinates=capture/'capture-coordinates.json',archive=capture/'archive-index.json')
    cov.require_fd_continuity(run=coords['run']['id'],coordinates=capture/'capture-coordinates.json',archive=capture/'archive-index.json')
    profile=json.loads(profile_path.read_bytes());launch=json.loads(launch_path.read_bytes())
    assert cov.profile.endswith('V2') and launch['running_image']['status']=='OBSERVED'
    assert profile['observation_completeness']=='UNKNOWN' and profile['known_selection_gaps']==[]
    archive=json.loads((capture/'archive-index.json').read_bytes())
    raw_bytes=0;stored_bytes=0;os_lines=0;seen={key:0 for key in ('unshare','close_range')};artifact_receipts=[]
    for row in archive['files']:
        path=Path(row['actual_path']);stored=path.read_bytes();assert len(stored)==row['compressed_bytes']
        assert hashlib.sha256(stored).hexdigest()==row['gzip_sha256']
        digest=hashlib.sha256();size=0;lines=0
        with gzip.open(path,'rb') as stream:
            for line in stream:
                digest.update(line);size+=len(line);lines+=1
                if Path(row['logical_path']).parent==capture/'os':
                    for name in seen:seen[name]+=(' '+name+'(') in line.decode('utf-8')
        assert size==row['raw_bytes'] and digest.hexdigest()==row['raw_sha256']
        assert not Path(row['logical_path']).exists()
        raw_bytes+=size;stored_bytes+=len(stored)
        if Path(row['logical_path']).parent==capture/'os':os_lines+=lines
        artifact_receipts.append({'logical_path':row['logical_path'],'stored':receipt(path),'decoded_sha256':digest.hexdigest(),'decoded_bytes':size})
    assert all(count>=1 for count in seen.values())
    files,artifacts,lines,calls=_scan(capture/'os',64_000_000,200_000,interface_work=True)
    observed=[row for row in calls if row.get('interface_record')]
    outside=sum(row['legacy_outside_fd_profile'] for row in observed)
    assert outside>0 and len(lines)==os_lines
    # Necessary wrong-binding rejection: alter only a copy, never original.
    bad=dict(coords);bad['os_capture_provider']=dict(binding)
    bad['os_capture_provider']['nonce']=('1' if binding['nonce'][0]=='0' else '0')+binding['nonce'][1:]
    bad_path=HERE/'wrong-binding-coordinates.json';bad_path.write_text(json.dumps(bad))
    try:OSCaptureCoverage.read(profile_path,launch=launch_path,coordinates=bad_path,archive=capture/'archive-index.json')
    except ValueError as error:rejection={'type':type(error).__name__,'message':str(error)}
    else:raise AssertionError('wrong nonce binding was accepted')
    write('wrong-binding-rejection.json',rejection);write('raw-receipts.json',artifact_receipts)
    for row in freeze['files']:assert receipt(ROOT/row['relative'])['sha256']==row['sha256']
    imported=[{'module':name,**receipt(module.__file__)} for name,module in sorted(sys.modules.items())
        if name.startswith('scar') and getattr(module,'__file__',None) and module.__file__.endswith('.py')]
    write('actual-imports.json',imported)
    report={'schema':'scar.owned-os-capture-gate-report','schema_version':1,'status':'PASS_OWNED_LAUNCH_COVERAGE',
        'actual_cli_exit':result.returncode,'coverage_protocol':cov.profile,'running_image':launch['running_image'],
        'run':coords['run']['id'],'artifact_files':len(archive['files']),'decoded_bytes':raw_bytes,'stored_bytes':stored_bytes,
        'os_files':len(files),'os_lines':os_lines,'parsed_interface_records':len(observed),'legacy_outside_fd_profile':outside,
        'parser_frontiers':sum('parser_gap' in row for row in calls),'required_safe_calls_observed':seen,
        'coordinates_receipt':receipt(capture/'capture-coordinates.json'),'profile_receipt':receipt(profile_path),
        'launch_receipt':receipt(launch_path),'archive_receipt':receipt(capture/'archive-index.json'),
        'wrong_binding_rejected':True,'observation_completeness':'UNKNOWN','full_execution_model_semantics':'OPEN',
        'first_stage_complete':False,'elapsed_seconds':time.monotonic()-started,
        'peak_rss_kib':resource.getrusage(resource.RUSAGE_SELF).ru_maxrss,'target_runs':1,'lewm_runs':0}
    write('summary.json',report);print(json.dumps(report,sort_keys=True),flush=True)


if __name__=='__main__':main()
