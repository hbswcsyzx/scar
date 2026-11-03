"""One public graph view crosses original calls, state and ordered contexts."""
import ast
from pathlib import Path
import subprocess
import sys


def test_outgoing_routes_all_saved_interfaces_without_replaying_unrelated_graphs(tmp_path):
    import pytest
    from dataclasses import replace
    from scar.analysis.program_dependencies import ProgramDependencyGraph
    from scar.analysis.program_call_dependencies import StaticCallDependencyProvider
    from scar.analysis.program_dependency_session import ProgramDependencyBudget,ProgramDependencySession
    from scar.analysis.static_program import link_static_program
    from scar.ir.program.dependencies import (DependencyKind as K,DependencyPoint,GraphNamespace,
        context_frames,context_push,context_is_closed)

    source=tmp_path/'source';source.mkdir();path=source/'program.py';model=tmp_path/'model'
    path.write_text('def identity(value):\n    return value\n'
        'def caller(value):\n    return identity(value)\n'
        'def spare(value):\n    return identity(value)\nresult = caller(7)\n')
    built=subprocess.run([sys.executable,'-B','-m','scar.cli','static',str(source),'--out',str(model),
        '--jobs','1','--phase','bodies'],capture_output=True,text=True)
    assert built.returncode==0,built.stdout+built.stderr
    manifest=link_static_program(model)
    assert len(manifest['static_calls']['shards'])>=3

    def selected(session):
        namespace,=session.select_bodies(file=str(path),entry='<module>.caller')
        shard,=tuple(shard for shard,_ in session.relation_shards(namespace))
        call,=shard.calls;target,=call.targets;argument,=target.arguments
        return DependencyPoint(GraphNamespace.from_source(namespace),argument.actual_use),argument

    with ProgramDependencySession(model)as session:
        point,argument=selected(session)
        graph=ProgramDependencyGraph(session.index,providers=(StaticCallDependencyProvider(session),))
        out=graph.outgoing(point,kinds=(K.ARGUMENT,));edge,=out.edges
        assert edge.target.node==argument.formal_value and len(edge.target.context)==1
        assert out.enumerated and not any(f.kind=='OUTGOING_RELATION_INDEX_PARTIAL'for f in out.frontiers)
        assert edge in graph.incoming(edge.target,kinds=(K.ARGUMENT,)).edges
        measurements=session.measurements()
        assert measurements['routing_complete']
        assert measurements['routing_shards_read']==len(manifest['static_calls']['shards'])
        # The spare caller was routed by raw receipt, not loaded as a core graph.
        assert measurements['relationship_shards_read']<measurements['routing_shards_read']

        # A known suffix is useful navigation evidence, but it cannot select
        # a publication's closed caller requirements or become a closed root.
        open_context=context_push(None,*context_frames(edge.target.context))
        assert not context_is_closed(open_context) and open_context!=edge.target.context
        open_formal=replace(edge.target,context=open_context)
        unknown_prefix=graph.incoming(open_formal,kinds=(K.ARGUMENT,))
        assert not unknown_prefix.edges and not unknown_prefix.enumerated
        assert any(f.kind=='STATIC_RELATION_CONTEXT_PREFIX_OPEN'for f in unknown_prefix.frontiers)

    # A bounded raw prefix cannot remove the already known local interface,
    # and cannot be advertised as a closed set of potential consumers.
    with ProgramDependencySession(model,budget=ProgramDependencyBudget(max_routing_shards=1))as session:
        point,argument=selected(session)
        graph=ProgramDependencyGraph(session.index,providers=(StaticCallDependencyProvider(session),))
        out=graph.outgoing(point,kinds=(K.ARGUMENT,))
        assert any(e.target.node==argument.formal_value for e in out.edges)
        assert not out.enumerated and any(f.kind=='OUTGOING_RELATION_INDEX_PARTIAL'for f in out.frontiers)

    # Even an unrelated producer's corrupted raw shard must reject routing;
    # a receipt error is not an empty consumer list or an ordinary frontier.
    spare=next(row for row in manifest['static_calls']['shards']if row['caller']['entry']=='spare')
    descriptor=next(d for d in manifest['static_calls']['artifacts']
        if d['path'].endswith(spare['artifact_path']))
    artifact=model/descriptor['path'];original=artifact.read_bytes();artifact.write_bytes(original+b'bad')
    try:
        with pytest.raises(ValueError,match='(receipt|size|stored|SHA|bytes)'):
            with ProgramDependencySession(model)as session:
                point,_=selected(session)
                graph=ProgramDependencyGraph(session.index,providers=(StaticCallDependencyProvider(session),))
                graph.outgoing(point,kinds=(K.ARGUMENT,))
    finally:
        artifact.write_bytes(original)


def test_saved_call_relationships_are_queryable_as_one_contextual_graph(tmp_path):
    from scar.analysis.program_call_dependencies import StaticCallDependencyProvider,dependency_context
    from scar.analysis.program_dependencies import ProgramDependencyGraph
    from scar.analysis.program_dependency_session import ProgramDependencyBudget,ProgramDependencySession
    from scar.analysis.static_program import link_static_program
    from scar.ir.program.dependencies import DependencyKind as K,DependencyPoint,GraphNamespace
    from scar.ir.program.model import ExitKind,ValueKind

    # Reuse the original G-state regression's source material. Parsing this
    # test's literal data does not execute that test or either application.
    tree=ast.parse(Path(__file__).with_name('test_static_module_globals.py').read_text())
    original=next(n for n in tree.body if isinstance(n,ast.FunctionDef)
        and n.name=='test_call_time_globals_follow_original_writes_and_creator_contexts')
    sources={n.targets[0].id:n.value.value for n in original.body if isinstance(n,ast.Assign)
        and len(n.targets)==1 and isinstance(n.targets[0],ast.Name)
        and n.targets[0].id in ('provider','other','application')and isinstance(n.value,ast.Constant)}
    sources['provider']+='def relay(value):\n    return value\n'
    sources['application']=sources['application'].replace('raise RuntimeError(',
        'forward = p.relay(p.c)\nforward2 = p.relay(p.b)\nraise RuntimeError(')
    source=tmp_path/'source';source.mkdir();model=tmp_path/'model'
    for name,text in (('a_provider.py',sources['provider']),('b_other.py',sources['other']),
            ('z_application.py',sources['application'])):(source/name).write_text(text)
    build=subprocess.run([sys.executable,'-B','-m','scar.cli','static',str(source),'--out',str(model),
        '--jobs','1','--phase','bodies'],capture_output=True,text=True)
    assert build.returncode==0,build.stdout+build.stderr
    link_static_program(model)
    budget=ProgramDependencyBudget(max_seconds=240,max_graphs=64,max_shards=128)
    with ProgramDependencySession(model,budget=budget)as session:
        application,=session.select_bodies(file=str(source/'z_application.py'),entry='<module>')
        shards=list(session.relation_shards(application))
        calls=[call for shard,locator in shards for call in shard.calls]
        lines=sources['application'].splitlines()
        def call_at(text):
            call,=[call for call in calls if call.source.start_line==lines.index(text)+1]
            return call
        graph=ProgramDependencyGraph(session.index,providers=(StaticCallDependencyProvider(session),))
        saved=call_at('x = saved()');selected,=saved.targets
        completion=next(r for r in selected.completions if r.kind is ExitKind.NORMAL
            and r.value_kind is ValueKind.REFERENCE and r.completion_index==0)
        root=DependencyPoint(GraphNamespace.from_source(application),completion.landing_value)
        kinds=(K.VALUE_USE,K.RESULT,K.BLOCK_ARGUMENT,K.ARGUMENT,K.COMPLETION,K.STATE_VALUE)
        walk=graph.walk((root,),kinds=kinds,max_points=160,max_edges=320,max_depth=24)
        assert any(edge.kind is K.COMPLETION and edge.source.namespace!=edge.target.namespace for edge in walk.edges)
        globals_edges=[edge for edge in walk.edges if any(e.rule=='STATIC_MODULE_GLOBALS_VALUE_V1'for e in edge.evidence)]
        assert globals_edges,'return -> callee G read -> original caller setter must be connected'
        state_edge=globals_edges[0]
        assert state_edge.source.namespace==GraphNamespace.from_source(application)
        assert state_edge.target.context and state_edge.target.context[-1].operation==saved.operation
        source_body=session.load_body(application)
        payload=source_body.index.use_site(state_edge.source.node).use.value
        first_write_line=lines.index('p.a = p.b')+1
        assert any(flow.projection.source_payload==state_edge.source.node
            and flow.projection.write.source.start_line==first_write_line
            for shard,locator in session.relation_shards(selected.body)for flow in shard.module_globals_flows
            if flow.projection.write is not None)
        assert any(point.node==payload for point in walk.points)
        assert any(edge.kind is K.STATE_VALUE and edge.source.namespace!=edge.target.namespace for edge in walk.edges)
        assert all(evidence.sources for edge in walk.edges for evidence in edge.evidence)
        assert any(condition.name=='INTERVENING_EFFECTS_PRESERVE_BINDING'
            for edge in globals_edges for condition in edge.conditions)

        # The same original read in another real caller context has its own
        # source. An empty context does not request a union of those callers.
        other=call_at('z = saved()')
        first_context=state_edge.target.context
        other_context=tuple((*first_context[:-1],type(first_context[-1])(
            first_context[-1].caller,other.operation,other.callee_use,other.callee_value,
            first_context[-1].target,first_context[-1].definition)))
        later=graph.incoming(DependencyPoint(state_edge.target.namespace,state_edge.target.node,other_context),kinds=(K.STATE_VALUE,))
        assert later.edges and all(edge.target.context==other_context for edge in later.edges)
        assert all(edge.source.node!=state_edge.source.node for edge in later.edges)
        unbound=graph.incoming(DependencyPoint(state_edge.target.namespace,state_edge.target.node),kinds=(K.STATE_VALUE,))
        assert not unbound.edges and any(f.kind=='UNBOUND_CALL_CONTEXT'for f in unbound.frontiers)

        # Explicit actuals/formals, both exits, world and environment share
        # the same public interface and original call frame identity.
        relay1=call_at('forward = p.relay(p.c)');relay2=call_at('forward2 = p.relay(p.b)')
        provider=graph.providers[-1]
        target,=relay1.targets
        from scar.ir.program.static_calls import StaticCallContext
        context1=dependency_context((StaticCallContext(relay1.caller,relay1.operation,relay1.callee_use,
            relay1.callee_value,target.definition,target.body),))
        context2=dependency_context((StaticCallContext(relay2.caller,relay2.operation,relay2.callee_use,
            relay2.callee_value,relay2.targets[0].definition,relay2.targets[0].body),))
        formal=target.arguments[0].formal_value;namespace=GraphNamespace.from_source(target.body)
        arg1=graph.incoming(DependencyPoint(namespace,formal,context1),kinds=(K.ARGUMENT,))
        arg2=graph.incoming(DependencyPoint(namespace,formal,context2),kinds=(K.ARGUMENT,))
        assert len(arg1.edges)==len(arg2.edges)==1
        assert arg1.edges[0].source.node==target.arguments[0].actual_use
        assert arg1.edges[0].source.node!=arg2.edges[0].source.node
        assert not provider.incoming(DependencyPoint(namespace,formal)).edges
        world=graph.incoming(DependencyPoint(namespace,target.state_entry.callee_value,context1),kinds=(K.STATE_INTERFACE,))
        assert any(e.source.node==target.state_entry.caller_use for e in world.edges)
        environment=next(r for r in target.environment_routes if r.member.role.value=='GLOBALS_NAMESPACE')
        env=graph.incoming(DependencyPoint(namespace,environment.member.reference,context1),kinds=(K.ENVIRONMENT,))
        assert env.edges and all(e.source.namespace==GraphNamespace.from_source(environment.creation_body)for e in env.edges)
        for completion in target.completions:
            query=DependencyPoint(GraphNamespace.from_source(relay1.caller),completion.landing_value)
            incoming=graph.incoming(query,kinds=(K.COMPLETION,))
            assert any(edge.source.context==context1 for edge in incoming.edges)
        if not any(completion.kind is ExitKind.RAISE for completion in target.completions):
            assert any(frontier.kind in ('COMPLETION_INTERFACE_OPEN','COMPLETION_PAYLOAD_ADAPTER_REQUIRED',
                'COMPLETION_TYPE_ADAPTER_REQUIRED','CALLEE_EXIT_SITE_OPEN')for frontier in target.frontiers), 'missing raise ports require an explicit original boundary frontier'
        partial={**session.call_publication,'complete':False,'shards':[],
            'scope':{**session.call_publication.get('scope',{}),'canonical_call_denominator_complete':False}}
    # An unenumerated zero-CALL body's formal is still an actual interface.
    # Missing relationship shards cannot close it; unrelated constants stay
    # outside this provider's scope rather than inheriting every frontier.
    from scar.ir.program.model import LiteralOrigin,ReferenceValue
    with ProgramDependencySession(model,budget=budget,call_publication=partial)as session:
        namespace,=session.select_bodies(file=str(source/'a_provider.py'),entry='<module>.relay')
        body=session.load_body(namespace);provider=StaticCallDependencyProvider(session)
        formal=DependencyPoint(GraphNamespace.from_source(namespace),body.interface.parameters[0].value)
        missing=provider.incoming(formal)
        assert not missing.edges and not missing.enumerated
        assert any(f.kind=='STATIC_RELATION_SCOPE_OPEN'for f in missing.frontiers)
        namespace,=session.select_bodies(file=str(source/'z_application.py'),entry='<module>')
        body=session.load_body(namespace)
        literal=next(v for v in body.graph.values if type(v)is ReferenceValue and type(v.origin)is LiteralOrigin)
        unrelated=provider.incoming(DependencyPoint(GraphNamespace.from_source(namespace),literal.id))
        assert unrelated.enumerated and not unrelated.edges and not unrelated.frontiers
