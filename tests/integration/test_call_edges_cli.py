"""Public automatic trace -> source/core call links -> reference traversal."""
from copy import deepcopy
import gzip
import json
import os
from pathlib import Path
import subprocess
import sys

import pytest


REPOSITORY=Path(__file__).resolve().parents[2]


def cli(*arguments,cwd=None):
    env=dict(os.environ,PYTHONPATH=str(REPOSITORY))
    for name in ('SCAR_TRACE_DIR','SCAR_TRACE_CALL_EDGES','SCAR_CALL_TRACE_OWNER_PID'):
        env.pop(name,None)
    return subprocess.run([sys.executable,'-m','scar.cli',*map(str,arguments)],
        cwd=cwd or REPOSITORY,env=env,capture_output=True,text=True,timeout=60)


def read(path):
    with gzip.open(path,'rt') if path.suffix=='.gz' else path.open() as stream:
        return json.load(stream)


@pytest.fixture
def linked(tmp_path):
    project=tmp_path/'project'
    project.mkdir()
    (project/'helper.py').write_text('def identity(value):\n    return value\ndef relay(value):\n    return identity(value)\n')
    entry=project/'entry.py'
    entry.write_text('from helper import relay\nclass Token: pass\ndef run(left,right):\n    a=relay(left); b=relay(right)\n    return a\nleft=Token()\nright=Token()\nassert run(left,right) is left\nprint("completed")\n')
    inventory=tmp_path/'inventory.json.gz'
    generated=cli('inventory-program',entry,'--project-root',project,'--out',inventory)
    assert generated.returncode==0,generated.stdout+generated.stderr
    trace=tmp_path/'trace'
    captured=cli('trace','--calls-only','--project-root',project,'--out',trace,'--',sys.executable,entry,cwd=project)
    assert captured.returncode==0,captured.stdout+captured.stderr
    assert 'completed' in captured.stdout
    report=tmp_path/'calls.json.gz'
    connected=cli('link-calls',trace,'--project-root',project,'--inventory',inventory,'--out',report)
    assert connected.returncode==0,connected.stdout+connected.stderr
    return project,entry,inventory,trace,report


def test_public_source_core_connections_and_reference_query_binding_boundary(linked):
    _,_,_,trace,path=linked
    assert not (trace/'events.jsonl').exists()
    assert not (trace/'entities.jsonl').exists()
    document=read(path)
    model=document['analysis']['model']
    summary=document['analysis']['summary']
    assert summary['direct_core_call_observations']>=4
    assert summary['reference_routes']>0
    assert not summary['contents_or_effects_established']
    checked=cli('check-call-links',path)
    assert checked.returncode==0,checked.stdout+checked.stderr
    assert json.loads(checked.stdout)['status']=='REPLAYED'
    codes={item['code']['key']:item['code'] for item in model['codes']}
    run,= [edge for edge in model['edges'] if codes[edge['entry']['code']]['qualname']=='run']
    invocation=run['entry']['invocation']
    queried=cli('query-call-refs',path,'--process',invocation['process_id'],
        '--thread',invocation['thread_id'],'--invocation',invocation['invocation_id'])
    assert queried.returncode==0,queried.stdout+queried.stderr
    query=json.loads(queried.stdout)['query']
    endpoints=[r[end] for r in query['routes'] for end in ('destination','source')]
    input_names={p['name'] for p in endpoints if p['owner']==invocation and p['role']=='PARAMETER'}
    # A source signature cannot prove the actual calling convention: a Name
    # can hold a bound method/partial with extra receiver/default inputs.
    # This limited evidence gate must stop rather than invent the outer input.
    assert input_names==set()
    assert len({p['owner']['invocation_id'] for p in endpoints if p['owner']})>=3
    assert 'ARGUMENT_ROUTING_UNVERIFIED' in {issue['kind'] for issue in query['issues']}
    assert query['identity_only'] and not query['content_or_effect_equivalence_established']


@pytest.mark.parametrize('tamper',('position','condition','inventory','summary'))
def test_public_replay_rejects_modified_claims(linked,tmp_path,tamper):
    *_,path=linked
    doc=deepcopy(read(path))
    model=doc['analysis']['model']
    if tamper=='position':
        edge=next(e for e in model['edges'] if e['path'])
        edge['path'][0]['site']['offset']+=2
    elif tamper=='condition':
        model['edges'][0]['conditions']=[]
    elif tamper=='inventory':
        doc['inventory']['sha256']='0'*64
    else:
        doc['analysis']['summary']['contents_or_effects_established']=True
    changed=tmp_path/'tampered.json'
    changed.write_text(json.dumps(doc))
    rejected=cli('check-call-links',changed)
    assert rejected.returncode==2,rejected.stdout+rejected.stderr
    assert json.loads(rejected.stdout)['status']=='INVALID'


def test_public_output_protection_and_fresh_capture_directory(linked):
    project,entry,inventory,trace,_=linked
    captured=cli('trace','--calls-only','--project-root',project,'--out',trace,'--',sys.executable,entry)
    assert captured.returncode!=0
    assert 'fresh' in captured.stderr
    before=inventory.read_bytes()
    rejected=cli('link-calls',trace,'--project-root',project,'--inventory',inventory,'--out',inventory)
    assert rejected.returncode==2
    assert inventory.read_bytes()==before
