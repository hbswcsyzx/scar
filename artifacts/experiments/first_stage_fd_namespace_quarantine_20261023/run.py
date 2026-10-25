"""One required refusal using an existing real coverage2, no fake Base or scan."""
import ast
import copy
import hashlib
import json
import os
from pathlib import Path
import resource
import subprocess
import sys
import time

HERE=Path(__file__).resolve().parent
ROOT=HERE.parents[2]
CPU=ROOT/'artifacts/experiments/first_stage_owned_os_capture_20261023/gate-attempt02/capture'


def receipt(path):
    raw=Path(path).read_bytes()
    return {'path':str(Path(path).absolute()),'bytes':len(raw),'sha256':hashlib.sha256(raw).hexdigest()}


def write(name,value):
    with (HERE/name).open('x') as stream:json.dump(value,stream,indent=2,sort_keys=True);stream.write('\n')


def function(tree,name):
    return next(node for node in ast.walk(tree) if isinstance(node,(ast.FunctionDef,ast.AsyncFunctionDef)) and node.name==name)


def main():
    started=time.monotonic();freeze=json.loads((HERE/'static-freeze.json').read_bytes())
    for row in freeze['files']:assert receipt(ROOT/row['relative'])['sha256']==row['sha256']
    paths={'coordinates':CPU/'capture-coordinates.json','archive':CPU/'archive-index.json',
        'profile':next(CPU.glob('os-capture-coverage.*.json')),'launch':next(CPU.glob('os-capture-launch.*.json'))}
    write('producer.json',{'schema':'scar.fd-namespace-quarantine-producer','schema_version':1,
        'revision':subprocess.check_output(['git','rev-parse','HEAD'],cwd=ROOT,text=True).strip(),
        'script':receipt(__file__),'source_freeze':receipt(HERE/'static-freeze.json'),
        'inputs':{key:receipt(path) for key,path in paths.items()},
        'scope':'one same public guard using genuine retained CPU coverage; no fake Base, target, R1 or raw scan'})
    archive=json.loads(paths['archive'].read_bytes());forbidden={str(Path(row[key]).absolute()) for row in archive['files'] for key in ('logical_path','actual_path')}
    raw_attempts=[]
    def deny_raw(event,args):
        if event=='open' and isinstance(args[0],(str,bytes,os.PathLike)):
            path=str(Path(os.fsdecode(args[0])).absolute())
            if path in forbidden:raw_attempts.append(path);raise AssertionError('raw open forbidden: '+path)
    sys.addaudithook(deny_raw)
    from scar.trace.os_capture_coverage import OSCaptureCoverage
    from scar.trace.os_fd_table_contexts import FDNamespaceContinuityUnproven,require_fd_namespace_continuity
    coverage=OSCaptureCoverage.read(paths['profile'],launch=paths['launch'],coordinates=paths['coordinates'],archive=paths['archive'])
    assert coverage.profile=='STRACE_EXPLICIT_SELECTION_CAPTURE_BOUND_V2'
    run=json.loads(paths['coordinates'].read_bytes())['run']['id']
    try:require_fd_namespace_continuity(coverage,run=run,coordinates=paths['coordinates'],archive=paths['archive'])
    except FDNamespaceContinuityUnproven as error:
        rejection={'exception':type(error).__name__,'reason_code':error.reason_code,'status':error.status,'message':str(error)}
    else:raise AssertionError('selection-only input must not obtain container coidentity')
    assert rejection['status']=='OPEN' and not raw_attempts
    before=ast.parse((HERE/'preimage.py').read_bytes());after=ast.parse((ROOT/'scar/trace/os_fd_table_contexts.py').read_bytes())
    for name in ('read','build_os_fd_table_contexts'):
        assert ast.dump(function(before,name))==ast.dump(function(after,name))
    old_prepare=function(before,'_prepare');new_prepare=copy.deepcopy(function(after,'_prepare'))
    guard_calls=[node for node in ast.walk(new_prepare) if isinstance(node,ast.Call) and isinstance(node.func,ast.Name) and node.func.id=='require_fd_namespace_continuity']
    assert len(guard_calls)==1
    guard_calls[0].func.id='require_fd_continuity_coverage'
    assert ast.dump(old_prepare)==ast.dump(new_prepare)
    for row in freeze['files']:assert receipt(ROOT/row['relative'])['sha256']==row['sha256']
    write('rejection.json',rejection)
    report={'schema':'scar.fd-namespace-quarantine-check','schema_version':1,'status':'PASS_EXPECTED_NAMESPACE_REFUSAL',
        'selection_profile':coverage.profile,'namespace_continuity':rejection,'raw_open_attempts':raw_attempts,
        'public_build_and_read_bodies_unchanged':True,'shared_prepare_only_guard_call_changed':True,
        'old_schema1_reader_version_guard_unchanged':True,'FD_values_source_unchanged':'bound by static freeze; no reexecution claimed',
        'target_runs':0,'R1_imports':0,'resources_created':0,'full_execution_model_semantics':'OPEN',
        'elapsed_seconds':time.monotonic()-started,'peak_rss_kib':resource.getrusage(resource.RUSAGE_SELF).ru_maxrss}
    write('summary.json',report);print(json.dumps(report,sort_keys=True),flush=True)


if __name__=='__main__':main()
