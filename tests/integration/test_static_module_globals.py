"""Original callable identity and call-time G contents are distinct facts."""
import copy
import gzip
import hashlib
import json
import subprocess
import sys

import pytest


def _check_demand_refresh(session):
    from types import SimpleNamespace
    from scar.analysis.static_module_state import ModuleGlobalsDependencies,_context
    from scar.analysis.static_namespace import NamespaceEntryPathWitness
    modules=session._module_dependencies();dependencies=session._dependencies()
    original=session._module_state
    nested=[f for rows in original.flows.values()for f in rows if f.projection.owner_routes and not f.bridges]
    first,second=nested[:2]
    assert first.read==second.read and first.requirements!=second.requirements
    engine=ModuleGlobalsDependencies(modules=modules,incoming=dependencies.owner_activations)
    def recompute(flow):
        projection=flow.projection;r=projection.environment
        body=modules._body(flow.read.body);deps=modules.namespace_for(body)
        read=deps.by_result[flow.read.result];slot=read.owners.index(flow.read.owner)
        segment,=flow.segments
        entry=NamespaceEntryPathWitness(body.namespace.region,segment.start_block,segment.query_owner,
            segment.query_operation,segment.query_world,segment.key,segment.path,segment.intervening_operations,
            segment.conditions,read,slot,segment.start_owner)
        activation=SimpleNamespace(environment=r,state_entry=projection.state_entry,context=_context(r),
            requirements=projection.callable_source.points[0].requirements)
        return engine.sources(activation,read_body=body,read=read,slot=slot,entry_paths=(entry,))
    writes=modules.write_routes_at
    try:
        modules.write_routes_at=lambda *args,**kwargs:()
        old_first=recompute(first);old_second=recompute(second)
    finally:modules.write_routes_at=writes
    assert old_first and old_second and all(f.projection.write is None for f in (*old_first,*old_second))
    current=recompute(first)
    assert current and all(f.projection.write is not None for f in current)
    assert all(f not in engine.flows[f.read.body]for f in old_first)
    assert all(f in engine.flows[f.read.body]for f in old_second),'another context must retain its source'
    engine.incoming=lambda point:()
    assert not recompute(first)and not recompute(second)
    tokens=list(engine._demands)
    assert all(any(row.kind=='GLOBALS_OWNER_ORIGIN_OPEN'for body,row in engine._demand_frontiers[t])for t in tokens)
    engine.incoming=dependencies.owner_activations
    restored=recompute(first)
    first_token=next(t for t in tokens if t[0]==first.projection.environment)
    second_token=next(t for t in tokens if t[0]==second.projection.environment)
    assert restored and not engine._demand_frontiers[first_token]
    assert engine._demand_frontiers[second_token],'refresh must not erase another context frontier'
    def interrupted():raise TimeoutError('deliberate state-demand interruption')
    engine.check=interrupted
    with pytest.raises(TimeoutError):recompute(first)
    assert all(f in engine.flows[f.read.body]for f in restored)
    assert any(row.kind=='MODULE_GLOBALS_TIME_BUDGET_INTERRUPTED'for body,row in engine._demand_frontiers[first_token])
    engine.check=lambda:None
    assert recompute(first)and not engine._demand_frontiers[first_token]
    assert engine.fact_count==sum(len(rows)for rows in engine.flows.values())


def test_call_time_globals_follow_original_writes_and_creator_contexts(tmp_path,monkeypatch):
    from scar.analysis.static_query import query_static_program
    from scar.ir.program.static_calls import loads

    source=tmp_path/'source';source.mkdir();model=tmp_path/'model'
    provider='''def a():
    return 11
def b():
    return 22
def c():
    return 33
def read():
    return a
def inner():
    return a
def outer():
    return inner()
def make():
    def nested():
        return a
    return nested
def overwrite():
    global replaced
    replaced = c
    return replaced
'''
    other='''def foreign_first():
    return 44
a = foreign_first
def read():
    return a
'''
    application='''import a_provider as p
import b_other as q
saved = p.read
p.a = p.b
p.b = p.c
x = saved()
x()
p.read = q.read
y = p.read()
y()
p.a = p.c
z = saved()
z()
n = p.make()
v = n()
v()
v2 = n()
v2()
h = p.outer()
h()
o = p.overwrite()
o()
raise RuntimeError("SCAR must never execute this application")
'''
    provider_path=source/'a_provider.py';provider_path.write_text(provider)
    (source/'b_other.py').write_text(other)
    app=source/'z_application.py';app.write_text(application)
    result=subprocess.run([sys.executable,'-B','-m','scar.cli','static',str(source),
        '--out',str(model),'--jobs','1','--phase','bodies'],capture_output=True,text=True)
    assert result.returncode==0,result.stdout+result.stderr
    from scar.analysis.static_calls import StaticCallSession
    from scar.analysis.static_program import link_static_program
    original_recount=StaticCallSession._recount_relations
    def recount(session):
        original_recount(session)
        _check_demand_refresh(session)
    monkeypatch.setattr(StaticCallSession,'_recount_relations',recount)
    link_static_program(model)
    manifest=json.loads((model/'manifest.json').read_text());publication=manifest['static_calls']
    assert publication['schema_version']==9
    assert publication['complete'],publication['frontiers']
    names={d['wire']:b['name']for u in manifest['units']for b in u['bodies']for d in b.get('definitions',())}
    shards=[];wires=[]
    for descriptor in publication['shards']:
        wire=json.loads(gzip.decompress((model/'indexes/calls'/descriptor['artifact']['path']).read_bytes()))
        wires.append(wire);shards.append(loads(json.dumps(wire)))
    calls=[c for s in shards for c in s.calls if c.source.path==str(app)]
    lines=application.splitlines()
    for expression,target in (('x()','b'),('y()','foreign_first'),('z()','c'),
            ('v()','c'),('v2()','c'),('h()','c'),('o()','c')):
        call,=[c for c in calls if c.source.start_line==lines.index(expression)+1]
        assert {names[t.definition.definition.wire]for t in call.targets}=={'<module>.'+target},expression
    flows=[f for s in shards for f in s.module_globals_flows]
    assert flows and any(f.projection.owner_routes for f in flows),'nested creator G must have original owner routes'
    assert any(f.bridges for f in flows),'multi-layer entry/state projection must compose'
    assert any(not s.calls and s.module_globals_flows for s in shards),'zero-CALL read bodies still need state sources'
    read_flows=[f for f in flows if names[f.read.body.definition.wire]=='<module>.read'
        and f.read.body.graph.artifact.uri.endswith('.json.gz')and f.projection.key=='a']
    assert {f.projection.source_body for f in read_flows}
    overwritten=[f for f in flows if names[f.read.body.definition.wire]=='<module>.overwrite'
        and f.projection.key=='replaced']
    assert not overwritten,'callee STORE_GLOBAL must kill external entry a before its read'
    for path,name in ((app,'<module>'),(provider_path,'<module>.read'),
            (provider_path,'<module>.outer'),(provider_path,'<module>.make.nested')):
        query=query_static_program(model,file=str(path),name=name,limit=200,include_dependencies=True)
        checked=query['dependencies']['static_calls']['shards']
        assert checked and all(s['v7_module_globals_state_checked']for s in checked)

    # Valid receipts do not make forged semantic ports valid. Rewrite only
    # the relation shard and its receipts; the original program stays fixed.
    owner_index=next(i for i,s in enumerate(shards)if s.module_globals_flows)
    descriptor=publication['shards'][owner_index]['artifact']
    shard_path=model/'indexes/calls'/descriptor['path']
    original_bytes=shard_path.read_bytes();original_manifest=(model/'manifest.json').read_bytes()
    for field in ('world','source','owner'):
        wire=copy.deepcopy(wires[owner_index]);projection=wire['relations']['module_globals_flows'][0]['projection']
        if field=='world':projection['environment']['call_world']=projection['environment']['callee_use']
        elif field=='source':projection['source_payload']=projection['source_owner']
        else:projection['module']['globals_namespace']=projection['module']['locals_namespace']
        decoded=json.dumps(wire,sort_keys=True,separators=(',',':')).encode()+b'\n'
        stored=gzip.compress(decoded,mtime=0);altered=copy.deepcopy(manifest)
        replacement={**descriptor,'bytes':len(stored),'sha256':hashlib.sha256(stored).hexdigest(),
            'decoded_bytes':len(decoded),'decoded_sha256':hashlib.sha256(decoded).hexdigest()}
        altered['static_calls']['shards'][owner_index]['artifact']=replacement
        relative='indexes/calls/'+descriptor['path']
        for artifact in altered['static_calls']['artifacts']:
            if artifact['path']==relative:artifact.update({k:v for k,v in replacement.items()if k!='path'})
        try:
            shard_path.write_bytes(stored)
            (model/'manifest.json').write_text(json.dumps(altered))
            with pytest.raises((ValueError,TypeError,KeyError)):
                query_static_program(model,file=str(provider_path),name=None,limit=200,include_dependencies=True)
        finally:
            shard_path.write_bytes(original_bytes);(model/'manifest.json').write_bytes(original_manifest)
    # v6 must reject new relation tables even if empty, and supported v6
    # records migrate with explicitly absent globals state evidence.
    old=copy.deepcopy(wires[0]);old['schema_version']=6
    with pytest.raises(ValueError):loads(json.dumps(old))
    def strip_v7(value):
        if isinstance(value,dict):
            value.pop('module_globals_flows',None)
            if isinstance(value.get('conditions'),list):
                value['conditions']=[c for c in value['conditions']if c!='SOURCE_IMPORT_INITIALIZER_USES_MODULE_DICT']
            for child in value.values():strip_v7(child)
        elif isinstance(value,list):
            for child in value:strip_v7(child)
    old=copy.deepcopy(wires[0]);strip_v7(old);old['schema_version']=6
    assert not loads(json.dumps(old)).module_globals_flows
