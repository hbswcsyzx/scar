"""Module values cross real import/field ports; applications never execute."""
import gzip
import json
import subprocess
import sys
import copy
import hashlib
from pathlib import Path
from tempfile import TemporaryDirectory

import pytest


def _check_read_frontier_recomputation(root,model,application):
    from scar.analysis.static_calls import StaticCallSession
    from scar.ir.program.static_calls import StaticCallContext,StaticReferencePoint

    with StaticCallSession(model,out=root/'frontier-check')as session:
        number=next(n for n,u in enumerate(session.units)if u['path']==str(application))
        unit=session.units[number];context=session._unit(number)
        position,row=next((n,b)for n,b in enumerate(unit['bodies'])if b['name']=='<module>.select')
        body=session._body(context,position,row)
        position,row=next((n,b)for n,b in enumerate(unit['bodies'])if b['kind']=='MODULE')
        caller=session._body(context,position,row)
        # Enumerate an original source CALL without admitting its argument/
        # return facts yet. These are real static ports, never invocations.
        call=next(c for c in session._calls(caller)if any(t.body==body.namespace for t in c.targets))
        target=next(t for t in call.targets if t.body==body.namespace)
        selected=StaticCallContext(call.caller,call.operation,call.callee_use,call.callee_value,
            target.definition,target.body)
        engine=session._module_dependencies();value=next(iter(engine._index(body).reads))
        generic=StaticReferencePoint(body.namespace,value)
        concrete=StaticReferencePoint(body.namespace,value,(selected,))
        def kinds(point):return {row.kind for row in engine._read_frontiers.get(point,{}).values()}
        assert not engine.sources(body,value)
        assert not engine.sources(body,value,(selected,))
        missing='MODULE_ATTRIBUTE_RECEIVER_UNCONNECTED'
        assert missing in kinds(generic)and missing in kinds(concrete)
        original_check=engine.check
        def interrupted():raise TimeoutError('deliberate static-analysis budget interruption')
        engine.check=interrupted
        with pytest.raises(TimeoutError):engine.sources(body,value,(selected,))
        engine.check=original_check
        assert missing in kinds(concrete)and 'MODULE_READ_TIME_BUDGET_INTERRUPTED'in kinds(concrete)
        session._store_call(call)
        assert engine.sources(body,value,(selected,))
        assert missing not in kinds(concrete)and 'MODULE_READ_TIME_BUDGET_INTERRUPTED'not in kinds(concrete)
        assert missing in kinds(generic)  # Another context has not been recomputed.
        assert engine.sources(body,value)
        assert missing not in kinds(generic)
        assert not any(row.kind==missing for row in engine.frontiers[body.namespace].values())
        assert not engine._pending_read_frontiers and not engine._active


def test_static_module_attributes_preserve_sources_and_caller_overwrites():
    from scar.ir.program.static_calls import loads
    from scar.analysis.static_query import query_static_program

    provider='NUMBER = 7\ndef a():\n    return 11\ndef b():\n    return 22\ndef identity(value):\n    return value\n'
    application='''import provider as p  # type: ignore[import-not-found]
x = p.identity(p.a)
x()
p.a = p.b
y = p.a
y()
def use(module, callback):
    return module.identity(callback)
z = use(p, p.b)
z()
def select(module):
    value = module.b
    return value
w = select(p)
w()
raise RuntimeError("this application must never execute")
'''
    with TemporaryDirectory(prefix='scar-static-module-') as temporary:
        root=Path(temporary);source=root/'source';source.mkdir();model=root/'model'
        (source/'provider.py').write_text(provider)
        app=source/'application.py';app.write_text(application)
        values=source/'only_values.py';values.write_text('import provider as p\nsaved = p.NUMBER\n')
        for args in (('--phase','bodies'),('--link-calls',)):
            result=subprocess.run([sys.executable,'-B','-m','scar.cli','static',str(source),
                '--out',str(model),'--jobs','1',*args],capture_output=True,text=True)
            assert result.returncode==0,result.stdout+result.stderr
            if args==('--phase','bodies'):_check_read_frontier_recomputation(root,model,app)
        manifest=json.loads((model/'manifest.json').read_text());publication=manifest['static_calls']
        assert publication['schema_version']==9
        assert publication['complete'],publication['frontiers']
        names={d['wire']:b['name']for u in manifest['units']for b in u['bodies']for d in b.get('definitions',())}
        shards=[];wires=[]
        for descriptor in publication['shards']:
            wire=gzip.decompress((model/'indexes/calls'/descriptor['artifact']['path']).read_bytes()).decode()
            shards.append(loads(wire));wires.append(json.loads(wire))
        calls=[call for shard in shards for call in shard.calls if call.source.path==str(app)]
        lines=application.splitlines()
        for expression,target in (('x = p.identity(p.a)','identity'),('x()','a'),('y()','b'),('z()','b'),('w()','b')):
            selected=[call for call in calls if call.source.start_line==lines.index(expression)+1]
            assert len(selected)==1
            assert {names[t.definition.definition.wire]for t in selected[0].targets}=={'<module>.'+target}
        value_shards=[s for s in shards if s.caller.graph.artifact.uri in {
            str(model/b['artifact']['path'])for u in manifest['units']if u['path']==str(values)for b in u['bodies']}]
        assert len(value_shards)==1 and not value_shards[0].calls
        assert value_shards[0].import_routes and value_shards[0].module_attribute_flows
        for path in (app,values):
            query=query_static_program(model,file=str(path),name='<module>',limit=100,include_dependencies=True)
            checked=query['dependencies']['static_calls']['shards']
            assert checked and all(s['v6_module_provenance_checked']for s in checked)
        query=query_static_program(model,file=str(app),name='<module>.select',limit=100,include_dependencies=True)
        assert any(s['module_attribute_flows']['items']for s in query['dependencies']['static_calls']['shards'])
        owner_index=next(i for i,s in enumerate(shards)if any(f.read.field=='identity'for f in s.module_attribute_flows))
        flow_index=next(i for i,f in enumerate(shards[owner_index].module_attribute_flows)if f.read.field=='identity')
        descriptor=publication['shards'][owner_index]['artifact']
        relative='indexes/calls/'+descriptor['path']; shard_path=model/relative
        original_bytes=shard_path.read_bytes();original_manifest=(model/'manifest.json').read_bytes()
        for field in ('field','receiver','world'):
            wire=copy.deepcopy(wires[owner_index])
            read=wire['relations']['module_attribute_flows'][flow_index]['read']
            read[field]='b'if field=='field'else read['world'if field=='receiver'else'receiver']
            decoded=json.dumps(wire,sort_keys=True,separators=(',',':')).encode()+b'\n'
            stored=gzip.compress(decoded,mtime=0)
            altered=copy.deepcopy(manifest)
            replacement={**descriptor,'bytes':len(stored),'sha256':hashlib.sha256(stored).hexdigest(),
                'decoded_bytes':len(decoded),'decoded_sha256':hashlib.sha256(decoded).hexdigest()}
            altered['static_calls']['shards'][owner_index]['artifact']=replacement
            for row in altered['static_calls']['artifacts']:
                if row['path']==relative:row.update({k:v for k,v in replacement.items()if k!='path'})
            shard_path.write_bytes(stored);(model/'manifest.json').write_text(json.dumps(altered))
            with pytest.raises(ValueError):
                query_static_program(model,file=str(app),name='<module>',limit=100,include_dependencies=True)
            shard_path.write_bytes(original_bytes);(model/'manifest.json').write_bytes(original_manifest)
        old=wires[0];old['schema_version']=5
        with pytest.raises(ValueError):loads(json.dumps(old))
        def remove_v7(value):
            if type(value)is dict:
                if 'request'in value:
                    assert value.pop('request')is None
                value.pop('module_globals_flows',None)
                if type(value.get('conditions'))is list:
                    value['conditions']=[c for c in value['conditions']if c!='SOURCE_IMPORT_INITIALIZER_USES_MODULE_DICT']
                for child in value.values():remove_v7(child)
            elif type(value)is list:
                for child in value:remove_v7(child)
        remove_v7(old)
        for field in ('import_routes','module_attribute_flows','module_frontiers'):old['relations'].pop(field)
        migrated=loads(json.dumps(old))
        assert not migrated.import_routes and not migrated.module_attribute_flows
        assert app.read_text()==application


def test_from_imports_keep_original_requests_member_ports_and_conditional_sources(tmp_path):
    from dataclasses import replace
    from scar.analysis.static_program import link_static_program
    from scar.analysis.program_dependency_session import ProgramDependencySession
    from scar.analysis.static_query import query_static_program
    from scar.analysis.static_module_attributes import ModuleAttributeDependencies, validate_module_attribute_flow
    from scar.ir.program.static_calls import (
        StaticImportFromRead, ModuleFlowCondition as C, dumps, loads,
    )
    from scar.ir.program.dependencies import DependencyPoint as P, GraphNamespace, DependencyKind as K

    source=tmp_path/'source';source.mkdir();model=tmp_path/'model'
    provider=source/'provider.py'
    provider.write_text('NUMBER = 7\ndef selected(value):\n    return value\n')
    package=source/'package';package.mkdir()
    (package/'__init__.py').write_text('def selected(value):\n    return None\n')
    (package/'member.py').write_text('def selected(value):\n    return value\n')
    app=source/'application.py'
    application=('from provider import selected as renamed, NUMBER\nfirst = renamed(1)\n'
        'def local():\n    from provider import selected as callback\n    return callback(2)\n'
        'second = local()\nfrom package.member import selected as nested\nthird = nested(3)\n'
        'raise RuntimeError("application must never execute")\n')
    app.write_text(application)
    built=subprocess.run([sys.executable,'-B','-m','scar.cli','static',str(source),'--out',str(model),
        '--jobs','1','--phase','bodies'],capture_output=True,text=True)
    assert built.returncode==0,built.stdout+built.stderr
    manifest=json.loads((model/'manifest.json').read_bytes())
    originals={row['artifact']['path']:hashlib.sha256((model/row['artifact']['path']).read_bytes()).hexdigest()
        for unit in manifest['units']for row in unit['bodies']if 'artifact'in row}
    manifest=link_static_program(model)
    assert manifest['static_calls']['schema_version']==9
    with ProgramDependencySession(model)as session:
        module,=session.select_bodies(file=str(app),entry='<module>')
        local,=session.select_bodies(file=str(app),entry='<module>.local')
        shards=[shard for namespace in (module,local)for shard,_ in session.relation_shards(namespace)]
        lines=application.splitlines()
        for expression,filename in (('first = renamed(1)',provider),
                ('    return callback(2)',provider),('third = nested(3)',package/'member.py')):
            call,=[call for shard in shards for call in shard.calls
                if call.source.start_line==lines.index(expression)+1]
            assert {t.definition.source.path for t in call.targets}=={str(filename)}
        flows=[flow for shard in shards for flow in shard.module_attribute_flows
            if type(flow.read)is StaticImportFromRead]
        assert flows and {f.read.field for f in flows}>={'selected','NUMBER'}
        assert any(f.read.member_index==1 and f.read.field=='NUMBER'for f in flows)
        assert any(f.module.returned_module=='package.member'for f in flows)
        assert all(f.module.request is not None and C.IMPORT_FROM_FALLBACKS_NOT_SELECTED in f.conditions
            for f in flows)
        flow=next(f for f in flows if f.read.field=='NUMBER')
        incoming=session.graph().incoming(P(GraphNamespace.from_source(flow.read.body),flow.read.result),
            kinds=(K.STATE_VALUE,))
        assert any(e.source.node==flow.source_payload and any(
            ev.rule=='STATIC_MODULE_IMPORT_FROM_VALUE_V1'for ev in e.evidence)for e in incoming.edges)
        assert any(f.kind=='NAMESPACE_STATE_CLOSURE_OPEN'for f in incoming.frontiers)
        routes=[r for shard in shards for r in shard.import_routes]
        def module_bodies(name):
            yield from (session.load_body(r.module_body)for r in routes if r.returned_module==name)
        engine=ModuleAttributeDependencies(load_body=session.load_body,source_context=session.source_context,
            module_bodies=module_bodies,namespace_for=session.namespace_for)
        assert validate_module_attribute_flow(flow,engine=engine,check_support=lambda support:None)
        with pytest.raises(ValueError):
            validate_module_attribute_flow(replace(flow,read=replace(flow.read,member_index=0)),
                engine=engine,check_support=lambda support:None)
        shard=next(shard for shard in shards if flow in shard.module_attribute_flows)
        assert loads(dumps(shard))==shard
        old=json.loads(dumps(shard));old['schema_version']=8
        with pytest.raises(ValueError,match='v9'):
            loads(json.dumps(old))
    result=query_static_program(model,file=str(app),name='<module>',limit=100,include_dependencies=True)
    checked=result['dependencies']['static_calls']['shards']
    assert checked and all(s['v9_from_import_ports_and_constants_checked']for s in checked)
    assert app.read_text()==application
    assert all(hashlib.sha256((model/path).read_bytes()).hexdigest()==digest for path,digest in originals.items())
