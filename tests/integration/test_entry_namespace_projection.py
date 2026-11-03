"""Entry state is conditional provenance, independent of resolved calls."""
import hashlib
import json
import subprocess
import sys
from dataclasses import replace

import pytest


def test_entry_globals_reach_initializer_without_call_publication_and_respect_overwrites(tmp_path):
    from scar.analysis.program_dependency_session import ProgramDependencySession, ProgramDependencyBudget
    from scar.analysis.static_class_publication import link_static_class_program
    from scar.analysis.static_crossbody_namespace import StaticNamespaceBody
    from scar.analysis.static_entry_namespace import validate_entry_namespace_projection
    from scar.ir.program.dependencies import DependencyPoint as P, DependencyKind as K, GraphNamespace
    from scar.ir.program.entry_namespaces import EntryNamespaceOwnerMode as Mode, EntryNamespaceProjection
    from scar.ir.program.model import LiteralOrigin
    from scar.ir.record_codec import decode, encode

    source=tmp_path/'source';source.mkdir();path=source/'application.py';model=tmp_path/'model'
    text=('A = 7\nglobal B\nB = 1\nB = 9\nC = 8\n'
        'class Box:\n    def read(self):\n        return A\n'
        '    def changed(self):\n        global C\n        C = 99\n        return C\n'
        '    def separate(self):\n        return B\n')
    path.write_text(text)
    built=subprocess.run([sys.executable,'-B','-m','scar.cli','static',str(source),'--out',str(model),
        '--jobs','1','--phase','bodies'],capture_output=True,text=True)
    assert built.returncode==0,built.stdout+built.stderr
    link_static_class_program(model)
    manifest=json.loads((model/'manifest.json').read_bytes())
    assert 'static_calls'not in manifest
    originals={row['artifact']['path']:hashlib.sha256((model/row['artifact']['path']).read_bytes()).hexdigest()
        for unit in manifest['units']for row in unit['bodies']if 'artifact'in row}
    with ProgramDependencySession(model,budget=ProgramDependencyBudget(max_seconds=180,max_graphs=12,
            max_cached_bytes=256*1024**2))as session:
        def read_point(name,key):
            namespace,=session.select_bodies(file=str(path),entry='<module>.Box.'+name)
            body=session.load_body(namespace)
            value,=[value for value,read in body.dependencies.by_result.items()
                if body.dependencies._string(read.keys[0])==key]
            return body,P(GraphNamespace.from_source(namespace),value)
        body,point=read_point('read','A')
        projections=tuple(session.entry_namespace_projections(point))
        assert projections and all(p.target==point for p in projections)
        assert all(p.owner_mode is Mode.CONDITIONAL_L_G_ALIAS for p in projections)
        assert all(p.source.context is None for p in projections)
        assert all(p.entry_world!=p.snapshot_world for p in projections)
        assert all(any(c.name=='MODULE_INITIALIZER_LOCALS_ALIASES_GLOBALS'and len(c.operands)>=4
            for c in p.conditions)for p in projections)
        incoming=session.graph().incoming(point,kinds=(K.STATE_VALUE,))
        assert all(p.dependency_edge()in incoming.edges for p in projections)
        assert not incoming.enumerated
        for projection in projections:
            assert decode(EntryNamespaceProjection,encode(projection))==projection
            module=session.load(projection.source.namespace)
            source_value=module.index.values[module.index.use_site(projection.source.node).use.value]
            assert type(source_value.origin)is LiteralOrigin and source_value.origin.value==7
            provider=session._entry_namespace_provider
            def namespace_body(original):
                return StaticNamespaceBody(original.graph,original.document,original.namespace,
                    original.index,original.dependencies)
            options=dict(entry=namespace_body(body),module=namespace_body(module),load_index=session.index,
                validate_owner_edge=provider._validate_owner_edge,check=session.check,
                allow_module_owner_alias=True,initialization_contract=False)
            assert validate_entry_namespace_projection(projection,**options)
            with pytest.raises(ValueError):
                validate_entry_namespace_projection(replace(projection,snapshot_world=projection.entry_world),**options)
        changed,changed_point=read_point('changed','C')
        assert not tuple(session.entry_namespace_projections(changed_point))
        # The old entry source is killed; the real same-body writer remains.
        local=session.graph().incoming(changed_point,kinds=(K.STATE_VALUE,))
        assert any(edge.source.namespace==changed_point.namespace for edge in local.edges)
        separate,separate_point=read_point('separate','B')
        other=tuple(session.entry_namespace_projections(separate_point))
        assert other and any(p.owner_mode is Mode.GLOBALS_ONLY for p in other)
        for p in other:
            module=session.load(p.source.namespace)
            assert module.index.values[module.index.use_site(p.source.node).use.value].origin.value==9
            assert p.read.body!=projections[0].read.body
        assert all(not p.initialization_contract for p in (*projections,*other))
    assert path.read_text()==text
    assert all(hashlib.sha256((model/name).read_bytes()).hexdigest()==value for name,value in originals.items())


def test_contextual_call_solver_consumes_entry_and_import_sources_with_guarded_interfaces(tmp_path):
    from scar.analysis.static_calls import StaticCallSession
    from scar.analysis.static_class_publication import link_static_class_program
    from scar.ir.program.contextual_calls import ContextualCallTarget
    from scar.ir.program.dependencies import OpenDependencyContext, DependencyKind as K, DependencyPoint as P, GraphNamespace
    from scar.ir.record_codec import decode, encode

    source=tmp_path/'source';source.mkdir();model=tmp_path/'model'
    provider=source/'library.py';provider.write_text('def choose(value):\n    return value\n')
    application=source/'program.py'
    application.write_text('from library import choose\nclass Box:\n    def solve(self, x):\n        return choose(x)\n')
    built=subprocess.run([sys.executable,'-B','-m','scar.cli','static',str(source),'--out',str(model),
        '--jobs','1','--phase','bodies'],capture_output=True,text=True)
    assert built.returncode==0,built.stdout+built.stderr
    link_static_class_program(model)
    assert 'static_calls'not in json.loads((model/'manifest.json').read_bytes())
    with StaticCallSession(model,out=tmp_path/'relations')as owner:
        number=next(i for i,u in enumerate(owner.units)if u['path']==str(application))
        position,row=next((i,r)for i,r in enumerate(owner.units[number]['bodies'])if r['name']=='<module>.Box.solve')
        body=owner._body(owner._unit(number),position,row)
        resolutions=tuple(owner.resolve_contextual_calls(body,context=None))
        assert len(resolutions)==1
        resolution=resolutions[0]
        assert resolution.targets and not resolution.enumerated
        resolver=owner.contextual_resolver()
        loaded=resolver.session.load_body(body.namespace)
        assert loaded.graph is body.graph and loaded.index is body.index and loaded.document is body.document
        assert owner._interprocedural is None and not owner._call_records
        for target in resolution.targets:
            assert target.interface.definition.source.path==str(provider)
            assert target.call.context is None and target.source.factory.context is None
            assert type(target.callee_context)is OpenDependencyContext
            assert any(e.kind is K.STATE_VALUE and any(c.domain=='scar.entry-namespace'for c in e.conditions)
                for e in target.source.path)
            assert any(e.kind is K.STATE_VALUE and any(p.rule=='CONTEXTUAL_MODULE_TEMPLATE_INSTANTIATION_V1'
                for p in e.evidence)for e in target.source.path)
            assert target.argument_edges() and target.normal_completion_edges()
            for edge in target.dependency_edges():
                assert set(target.source.conditions)<=set(edge.conditions)
                graph=resolver.session.graph()
                assert edge in graph.incoming(edge.target,kinds=(edge.kind,)).edges
                assert edge in graph.outgoing(edge.source,kinds=(edge.kind,)).edges
            assert decode(ContextualCallTarget,encode(target))==target
            assert resolver.validate_target(target)
            with pytest.raises(ValueError):
                resolver.validate_target(replace(target,conditions=()))
            formal=P(GraphNamespace.from_source(target.interface.body),target.interface.arguments[0].formal_value,None)
            unbound=resolver.session.graph().incoming(formal,kinds=(K.ARGUMENT,))
            assert not unbound.enumerated and any(f.kind=='CONTEXTUAL_CALL_ENTRY_CONTEXT_OPEN'for f in unbound.frontiers)
            terminal=P(GraphNamespace.from_source(target.interface.body),target.interface.normal_returns[0].use,None)
            unbound=resolver.session.graph().outgoing(terminal,kinds=(K.COMPLETION,))
            assert not unbound.enumerated and any(f.kind=='CONTEXTUAL_CALL_RETURN_CONTEXT_OPEN'for f in unbound.frontiers)
