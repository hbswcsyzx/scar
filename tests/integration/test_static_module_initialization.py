"""Import initialization projects conditional L/G state over original ports."""
import json
import subprocess
import sys
from dataclasses import replace

import pytest


def test_import_initializer_globals_reach_shared_graph_without_alias_invention(tmp_path):
    from scar.analysis.static_program import link_static_program
    from scar.analysis.program_dependency_session import ProgramDependencySession,ProgramDependencyBudget
    from scar.analysis.program_value_analysis import ProgramValueAnalysis,ValueAnalysisBudget
    from scar.analysis.program_call_dependencies import dependency_context
    from scar.analysis.static_namespace import NamespaceDependencies
    from scar.ir.program.dependencies import DependencyPoint,GraphNamespace,DependencyKind
    from scar.ir.program.model import ExitKind,ValueKind
    from scar.ir.program.queries import ProgramIndex
    from scar.ir.program.static_calls import (ModuleFlowCondition as C,MODULE_FLOW_BASE_CONDITIONS,
        dumps,loads)
    from scar.ir.record_codec import encode
    from scar.ir.literals import PythonLiteral

    source=tmp_path/'source';source.mkdir();model=tmp_path/'model'
    (source/'a_provider.py').write_text('global value\nvalue = 1\nvalue = 11\ndef read():\n    return value\n')
    (source/'b_provider.py').write_text('value = 22\ndef read():\n    return value\n')
    application='import a_provider as p\nimport b_provider as q\nsaved = p.read\np.read = q.read\nfirst = saved()\nsecond = p.read()\n'
    (source/'z_app.py').write_text(application)
    result=subprocess.run([sys.executable,'-B','-m','scar.cli','static',str(source),'--out',str(model),
        '--jobs','1','--phase','bodies'],capture_output=True,text=True)
    assert result.returncode==0,result.stdout+result.stderr
    link_static_program(model)
    with ProgramDependencySession(model,budget=ProgramDependencyBudget(max_seconds=120,max_graphs=32))as session:
        app,=session.select_bodies(file=str(source/'z_app.py'),entry='<module>')
        calls=[call for shard,locator in session.relation_shards(app)for call in shard.calls]
        roots=[];owners=[];legacy_source=None
        for expression,filename,expected in (('first = saved()','a_provider.py',11),
                ('second = p.read()','b_provider.py',22)):
            call,=[call for call in calls if call.source.start_line==application.splitlines().index(expression)+1]
            target,=call.targets
            assert target.definition.source.path==str(source/filename)
            normal=next(c for c in target.completions if c.kind is ExitKind.NORMAL
                and c.value_kind is ValueKind.REFERENCE and c.completion_index==0)
            roots.append(DependencyPoint(GraphNamespace.from_source(app),normal.landing_value))
            flows=[flow for shard,locator in session.relation_shards(target.body)for flow in shard.module_globals_flows
                if flow.projection.key=='value'and flow.projection.environment.call_operation==call.operation]
            assert flows and all(C.SOURCE_IMPORT_INITIALIZER_USES_MODULE_DICT in f.projection.conditions for f in flows)
            for flow in flows:
                projection=flow.projection;body=session.load_body(projection.source_body)
                payload=body.index.values[body.index.use_site(projection.source_payload).use.value]
                assert payload.origin.value==expected
                assert body.index.use_site(projection.source_world).operation==projection.source_operation
                assert body.index.use_site(projection.snapshot_world).operation==projection.snapshot_operation
                owner=body.index.use_site(projection.source_owner).use.value;owners.append((filename,owner,projection))
                assert owner==(projection.module.globals_namespace if filename=='a_provider.py'
                    else projection.module.locals_namespace)
                point=DependencyPoint(GraphNamespace.from_source(flow.read.body),flow.read.result,
                    dependency_context(flow.requirements))
                incoming=session.graph().incoming(point,kinds=(DependencyKind.STATE_VALUE,))
                assert incoming.edges and not any(f.kind=='MODULE_L_G_ALIAS_CONTRACT_OPEN'for f in incoming.frontiers)
                assert any(c.name=='SOURCE_IMPORT_INITIALIZER_USES_MODULE_DICT'for e in incoming.edges for c in e.conditions)
                if filename=='b_provider.py':legacy_source=flow
        report=ProgramValueAnalysis(session,budget=ValueAnalysisBudget(max_points=256,max_edges=512)).analyze(roots)
        for root,expected in zip(roots,(11,22)):
            assert {a.value for a in report.for_point(root).scalar_constant.alternatives}=={PythonLiteral.from_python(expected)}

        # The exact conditional domain must affect kills even when the source
        # writer already uses G. A raw exec frame keeps its two owner ports
        # independent. Change only primitive declarations in this small core
        # IR variant, not the source model or any saved source receipt.
        projection=next(p for name,owner,p in owners if name=='a_provider.py')
        body=session.load_body(projection.source_body);original=NamespaceDependencies(body.graph,body.document,index=body.index)
        writes=sorted((w for w in original.writes.values()if original._string(w.keys[0])=='value'),
            key=lambda w:list(body.index.operations).index(w.operation))
        assert len(writes)==2
        L,G=projection.module.locals_namespace,projection.module.globals_namespace
        world=projection.snapshot_world;terminal=projection.snapshot_operation
        for local_index in (0,1):
            selected=writes[local_index];changed=body.index.operations[selected.operation]
            use=body.index.use_site(selected.owners[0]).use
            changed=replace(changed,uses=tuple(replace(u,value=L)if u.id==use.id else u for u in changed.uses))
            graph=replace(body.graph,operations=tuple(changed if op.id==changed.id else op for op in body.graph.operations))
            protocols=[{'operation':encode(w.operation),'kind':'STORE_NAME_314'if i==local_index else'STORE_GLOBAL'}
                for i,w in enumerate(writes)]
            dependencies=NamespaceDependencies(graph,{'module':{'protocols':protocols}},index=ProgramIndex(graph))
            combined=dependencies.bindings_at(G,'value',terminal,world,equivalent_owners=(L,G))
            assert len(combined)==1 and combined[0].write.operation==writes[-1].operation
            assert combined[0].equivalent_owners==(L,G)
            dependencies.validate_binding(combined[0])
            assert dependencies.bindings_at(L,'value',terminal,world)[0].write.operation==selected.operation
            assert dependencies.bindings_at(G,'value',terminal,world)[0].write.operation==writes[1-local_index].operation
            with pytest.raises(ValueError):dependencies.validate_binding(replace(combined[0],equivalent_owners=(G,)))

        # New contracts cannot be smuggled into v7. Legacy records retain
        # their old condition set; decoding never grants the new premise.
        shard=next(shard for shard,locator in session.relation_shards(app)if shard.module_attribute_flows)
        wire=json.loads(dumps(shard));assert wire['schema_version']==8
        wire['schema_version']=7
        with pytest.raises(ValueError,match='v8 source import initializer'):loads(json.dumps(wire))
        def legacy(item):
            if type(item)is dict:
                if type(item.get('conditions'))is list:
                    item['conditions']=[c for c in item['conditions']if c!=C.SOURCE_IMPORT_INITIALIZER_USES_MODULE_DICT.value]
                for child in item.values():legacy(child)
            elif type(item)is list:
                for child in item:legacy(child)
        legacy(wire);old=loads(json.dumps(wire))
        assert all(f.conditions==MODULE_FLOW_BASE_CONDITIONS for f in old.module_attribute_flows)
        # Replay a legacy L-only projection against original inputs. Its
        # support can carry newer independent contracts without upgrading
        # this particular old initializer premise.
        from scar.analysis.static_module_attributes import (ModuleAttributeDependencies,
            validate_module_attribute_flow)
        from scar.analysis.static_module_state import ModuleGlobalsDependencies,validate_module_globals_flow
        from scar.ir.program.static_calls import StaticModuleAttributeFlow
        saved_routes=[r for shard,locator in session.relation_shards(app)for r in shard.import_routes]
        # Replay uses saved source namespaces, not a synthesized declaration
        # for a graph which happens to have identical decoded content.
        def module_bodies(name):
            for route in saved_routes:
                if route.returned_module==name:yield session.load_body(route.module_body)
        modules=ModuleAttributeDependencies(load_body=session.load_body,source_context=session.source_context,
            module_bodies=module_bodies,namespace_for=session.namespace_for)
        engine=ModuleGlobalsDependencies(modules=modules)
        def check_support(item):
            if type(item)is StaticModuleAttributeFlow:
                return validate_module_attribute_flow(item,engine=modules,check_support=check_support)
            return validate_module_globals_flow(item,engine=engine,check_support=check_support)
        legacy_source=replace(legacy_source,projection=replace(legacy_source.projection,conditions=MODULE_FLOW_BASE_CONDITIONS))
        assert validate_module_globals_flow(legacy_source,engine=engine,check_support=check_support)
