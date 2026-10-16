"""Record a bounded, unchanged external command on an explicitly frozen SCAR."""
import argparse
import hashlib
import json
import os
from pathlib import Path
import re
import runpy
import subprocess
import sys
import time


def write(path, value):
    path.write_text(json.dumps(value, indent=2, sort_keys=True) + '\n')


def git_state(root):
    return {name:subprocess.check_output(['git',*argv],cwd=root,text=True).strip()
            for name,argv in [('head',['rev-parse','HEAD']),('status',['status','--porcelain=v1'])]}


def tracked_python(root):
    paths=subprocess.check_output(['git','ls-files','-z','--','*.py'],cwd=root).split(b'\0')
    return {os.fsdecode(path):hashlib.sha256((root/os.fsdecode(path)).read_bytes()).hexdigest()
            for path in paths if path}


def main():
    parser=argparse.ArgumentParser()
    for name in ('scar-root','project-root','out'):
        parser.add_argument('--'+name,type=Path,required=True)
    parser.add_argument('--source-sha',required=True)
    parser.add_argument('command',nargs=argparse.REMAINDER)
    args=parser.parse_args()
    scar,project,out=(value.resolve() for value in (args.scar_root,args.project_root,args.out))
    command=args.command[1:] if args.command[:1]==['--'] else args.command
    if not command:raise ValueError('original command required')
    fingerprint=runpy.run_path(str(scar/'scripts/run_gate.py'))['fingerprint']
    before=fingerprint()
    if before[0]!=args.source_sha:raise ValueError('frozen source fingerprint differs')
    target_before=git_state(project)
    source_before=tracked_python(project)
    if target_before['status']:raise ValueError('target differs from recorded clean baseline')
    out.mkdir(parents=True,exist_ok=False)
    trace=out/'trace'
    environment=dict(os.environ,PYTHONPATH=str(scar),PYTHONDONTWRITEBYTECODE='1')
    for name in list(environment):
        if name.startswith('SCAR_'):environment.pop(name)
    argv=[sys.executable,'-m','scar.cli','trace','--call-operands','--operand-capture','windows',
          '--project-root',str(project),'--out',str(trace),'--max-call-events','250000',
          '--max-call-bytes','256000000','--max-operand-events','2000000',
          '--max-operand-bytes','1200000000','--resources','--resource-interval','0.5',
          '--',*command]
    write(out/'invocation.json',{'schema':'scar.b1-external-capture','schema_version':1,
        'command':argv,'cwd':str(project),'source_sha256_before':before[0],
        'scar_revision':subprocess.check_output(['git','rev-parse','HEAD'],cwd=scar,text=True).strip(),
        'target_before':target_before,'source_files_before':source_before,
        'environment':{name:environment[name] for name in ('PYTHONPATH','PYTHONDONTWRITEBYTECODE',
            'LEWM_CHECKPOINT_ROOT','LEWM_OUTPUT_ROOT','LEWM_RUN_NAME') if name in environment},
        'measurement_scope':'instrumented capture; not a clean A/B benchmark'})
    started=time.perf_counter()
    with (out/'capture.stdout.log').open('w') as stdout,(out/'capture.stderr.log').open('w') as stderr:
        completed=subprocess.run(['/usr/bin/time','-v','-o',str(out/'capture.time'),*argv],
            cwd=project,env=environment,stdout=stdout,stderr=stderr)
    elapsed=time.perf_counter()-started
    after=fingerprint()
    target_after=git_state(project)
    rss=re.search(r'Maximum resident set size \(kbytes\): (\d+)',(out/'capture.time').read_text())
    metadata=[json.loads(path.read_text()) for path in sorted(trace.glob('call-operand-meta.*.json'))]
    capture_lost=not metadata or any(meta['dropped_events'] or meta['errors'] or meta['io_failed']
                                   or meta['previous_profile'] for meta in metadata)
    report={'schema':'scar.b1-external-capture-result','schema_version':1,
        'returncode':completed.returncode,'wall_seconds':elapsed,'peak_rss_kib':int(rss[1]) if rss else None,
        'source_sha256_after':after[0],'scar_source_unchanged':before==after,
        'target_after':target_after,'target_git_unchanged':target_before==target_after,
        'target_tracked_python_unchanged':source_before==tracked_python(project),
        'operand_metadata':metadata,'capture_coverage_status':'FAILED_COLLECTION' if capture_lost else 'NEEDS_READER_REVIEW',
        'files':{path.name:path.stat().st_size for path in sorted(trace.iterdir()) if path.is_file()},
        'whole_program_complete':False,'transformation_authorized':False}
    write(out/'capture-result.json',report)
    print(json.dumps({key:value for key,value in report.items() if key not in ('operand_metadata','files')}),flush=True)
    return 0 if completed.returncode==0 and not capture_lost and before==after and target_before==target_after and report['target_tracked_python_unchanged'] else 2


if __name__=='__main__':
    raise SystemExit(main())
