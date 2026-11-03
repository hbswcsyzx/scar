"""Automatic environment ports and state dependencies from ordinary source.

No test imports or executes the application module.  Runtime object identities,
cell contents and whole-program coverage are deliberately not inferred here.
"""
import ast
from dataclasses import replace

import pytest

from scar.analysis.environment_lowering import StructuredEnvironmentBuilder, captured_cell_slot
from scar.analysis.program_lowering import SourceProgram, lower_source, prepare_source
from scar.ir.program.environments import EnvironmentRole
from scar.ir.program.functions import BodyLoweringProfile
from scar.ir.program.model import (
    Behavior, BlockArgument, LocalBindingValue, ReferenceValue, StateVersionValue,
    TerminatorKind,
)
from scar.ir.program.state_addresses import (
    AddressCoverage, CellContent, NamespaceKey, ReferenceOwner,
)
from scar.ir.program.structured import PythonProtocolKind
from scar.ir.program.validation import require_valid


def _lower(tmp_path, text, name):
    path = tmp_path / "application.py"
    path.write_text(text)
    context = prepare_source(path)
    nodes = [node for node in ast.walk(context.tree)
             if isinstance(node, (ast.FunctionDef, ast.AsyncFunctionDef)) and node.name == name]
    assert len(nodes) == 1
    node = nodes[0]
    matches = [atom.reference for atom in context.semantic.source_atoms.values()
               if atom.kind == type(node).__name__
               and (atom.reference.start_line, atom.reference.end_line,
                    atom.reference.start_column, atom.reference.end_column)
               == (node.lineno, node.end_lineno, node.col_offset, node.end_col_offset)]
    assert len(matches) == 1
    result = StructuredEnvironmentBuilder(context, name, source=matches[0]).run()
    return result, context


def _indexes(body):
    graph = body.graph
    assert graph is not None
    require_valid(graph)
    return ({operation.id: operation for operation in graph.operations},
            {value.id: value for value in graph.values},
            {protocol.operation: protocol.kind for protocol in body.structured.protocols})


def _protocol_operations(body, kind):
    operations = {operation.id: operation for operation in body.graph.operations}
    return [operations[protocol.operation] for protocol in body.structured.protocols if protocol.kind is kind]


def _reference_uses(operation, values):
    return [use for use in operation.uses if isinstance(values[use.value], ReferenceValue)]


def test_factory_entry_origins_are_conditional_reference_ports_without_call_or_state(tmp_path):
    import subprocess
    import sys
    from copy import deepcopy
    from scar.analysis.static_program import link_static_program
    from scar.analysis.program_dependency_session import ProgramDependencySession
    from scar.analysis.static_function_origins import (
        derive_factory_entry_origins,validate_factory_entry_origin,factory_entry_origin_evidence,factory_entry_origin_ports,
    )
    from scar.analysis.program_function_origin_dependencies import FactoryEntryOriginDependencyProvider
    from scar.ir.program.dependencies import DependencyPoint,DependencyStrength,GraphNamespace
    from scar.ir.record_codec import decode,encode

    source=tmp_path/'source';source.mkdir();path=source/'application.py';model=tmp_path/'model'
    text=('G = 1\ndef f(x):\n    return G + x\ndef sibling(x):\n    return x\n'
        'class Box:\n    def method(self, x):\n        return G + x\n'
        'answer = f(2)\nraise RuntimeError("never execute")\n')
    path.write_text(text)
    built=subprocess.run([sys.executable,'-B','-m','scar.cli','static',str(source),'--out',str(model),
        '--jobs','1','--phase','bodies'],capture_output=True,text=True)
    assert built.returncode==0,built.stdout+built.stderr
    link_static_program(model)
    with ProgramDependencySession(model)as session:
        namespace,=session.select_bodies(file=str(path),entry='<module>')
        shard,=tuple(shard for shard,_ in session.relation_shards(namespace))
        call=next(call for call in shard.calls if call.source.start_line==text.splitlines().index('answer = f(2)')+1)
        target,=call.targets
        creation=next(row for row in call.function_creations if row.definition==target.definition)
        creator=session.load_body(call.caller);body=session.load_body(target.body)
        inputs=dict(creator_graph=creator.graph,creator_document=creator.document,creator_namespace=creator.namespace,
            body_graph=body.graph,body_document=body.document,body_namespace=body.namespace,
            creator_index=creator.index,body_index=body.index,source_text=text)
        origins=derive_factory_entry_origins(creation=creation,**inputs)
        assert {origin.member.role for origin in origins}=={EnvironmentRole.FUNCTION_OBJECT,EnvironmentRole.GLOBALS_NAMESPACE}
        for origin in origins:
            assert validate_factory_entry_origin(origin,**inputs)
            assert decode(type(origin),encode(origin))==origin
            assert not any(hasattr(origin,name)for name in('caller','call_operation','context','entry_world','factory_post_world'))
        globals_origin=next(origin for origin in origins if origin.member.role is EnvironmentRole.GLOBALS_NAMESPACE)
        replays=[]
        def validate(origin):
            replays.append(origin)
            return validate_factory_entry_origin(origin,**inputs)
        def scope(point,outgoing):
            original=creator if point.namespace==GraphNamespace.from_source(creator.namespace)else body
            ports=factory_entry_origin_ports(graph=original.graph,document=original.document,
                namespace=original.namespace,index=original.index)
            return point.node in ports[1 if outgoing else 0]
        provider=FactoryEntryOriginDependencyProvider(origins_for=lambda point:((origin,
            factory_entry_origin_evidence(origin,creator_document=creator.document,body_document=body.document))
            for origin in origins),load_index=session.index,validate_origin=validate,interface_scope=scope)
        point=DependencyPoint(GraphNamespace.from_source(body.namespace),globals_origin.member.reference)
        incoming=provider.incoming(point);edge,=incoming.edges
        assert edge.strength is DependencyStrength.MAY and edge.source.node==globals_origin.source_use
        assert edge.source.context is None and edge.target==point and not incoming.enumerated
        assert any(frontier.kind=='FUNCTION_ENTRY_ORIGIN_SET_OPEN'for frontier in incoming.frontiers)
        selected=next(c for c in edge.conditions if c.name=='ENTRY_CALLABLE_FROM_THIS_FACTORY_OCCURRENCE')
        callable_member=next(m for m in body.graph.environments[0].members if m.role is EnvironmentRole.FUNCTION_OBJECT)
        assert selected.subject.node==callable_member.reference and selected.subject.context==point.context
        assert tuple(p.node for p in selected.operands)==(creation.normal_value,creation.factory)
        from scar.analysis.static_namespace import normal_reference,protocol_kinds
        other_factory=next(op for op in creator.graph.operations if op.id!=creation.factory
            and protocol_kinds(creator.document).get(op.id)=='MAKE_FUNCTION_314')
        _,other_normal=normal_reference(creator.index,other_factory.id)
        other_guard=replace(selected,operands=(DependencyPoint(edge.source.namespace,other_normal,None),
            DependencyPoint(edge.source.namespace,other_factory.id,None)))
        assert other_guard.subject==selected.subject and len({other_guard,selected})==2
        from scar.analysis.program_dependencies import DependencyWalk
        from scar.analysis.program_dependency_export import export_dependency_walk
        from scar.ir.program.dependencies import DependencyKind
        wire=export_dependency_walk(DependencyWalk((point,),(point,edge.source),(edge,),incoming.frontiers,
            'incoming',False,(DependencyKind.ENVIRONMENT,)))
        guard=next(c for c in wire['conditions']if c['name']==selected.name)
        assert [wire['points'][i]['node']for i in guard['operands']]==[
            creation.normal_value.wire,creation.factory.wire]
        assert all('/origins'not in locator.pointer for locator in edge.evidence[0].sources)
        reverse=provider.outgoing(edge.source)
        assert reverse.edges and all(row.target.context is None for row in reverse.edges)
        assert len(replays)==2  # Only the two queried relations were replayed.
        provider.incoming(point)
        assert len(replays)==3  # A repeated query must not reuse a cached PASS.
        empty=FactoryEntryOriginDependencyProvider(origins_for=lambda point:(),load_index=session.index,
            validate_origin=validate,interface_scope=scope)
        unknown=empty.outgoing(DependencyPoint(GraphNamespace.from_source(creator.namespace),creation.normal_value,None))
        assert not unknown.edges and not unknown.enumerated
        assert any(f.kind=='FUNCTION_ENTRY_ORIGIN_SET_OPEN'for f in unknown.frontiers)
        literal=next(v for v in creator.graph.values if type(v)is ReferenceValue
            and hasattr(v.origin,'value')and v.id!=creation.normal_value)
        unrelated=empty.outgoing(DependencyPoint(GraphNamespace.from_source(creator.namespace),literal.id,None))
        assert unrelated.enumerated and not unrelated.frontiers
        builtins=next(member for member in body.graph.environments[0].members if member.role is EnvironmentRole.BUILTINS_NAMESPACE)
        assert not provider.incoming(DependencyPoint(point.namespace,builtins.reference)).edges
        assert not provider.incoming(DependencyPoint(point.namespace,body.interface.world)).edges
        with pytest.raises(ValueError,match='only FUNCTION_OBJECT'):
            replace(globals_origin,member=builtins)
        with pytest.raises(ValueError,match='captured/member'):
            validate_factory_entry_origin(replace(globals_origin,source_use=creation.code_use,
                source_value=creator.index.use_site(creation.code_use).use.value),**inputs)
        from scar.ir.program.queries import ProgramIndex
        factory_op=creator.index.operations[creation.factory]
        frame_builtins=creator.graph.frame_roots[0].entry.builtins_namespace
        wrong=replace(factory_op,uses=tuple(replace(use,value=frame_builtins)
            if use.id==globals_origin.source_use else use for use in factory_op.uses))
        bad_graph=replace(creator.graph,operations=tuple(wrong if op.id==wrong.id else op for op in creator.graph.operations))
        with pytest.raises(ValueError,match='authoritative globals'):
            derive_factory_entry_origins(creation=creation,**{**inputs,'creator_graph':bad_graph,'creator_index':ProgramIndex(bad_graph)})
        with pytest.raises(ValueError,match='retained text'):
            derive_factory_entry_origins(creation=creation,**{**inputs,'source_text':text.replace('G = 1','G = 2')})
        bad=deepcopy(body.document);bad['static_compilation']['code_path']=[999999]
        with pytest.raises(ValueError,match='compiler path'):
            derive_factory_entry_origins(creation=creation,**{**inputs,'body_document':bad})

        # Class creators use their original ClassSuite constants/CodeRef and
        # an ordered operand ABI.  They do not have a function language overlay.
        from scar.analysis.static_calls import StaticCallSession
        from scar.analysis.static_namespace import normal_reference
        from scar.ir.program.class_entries import decode_class_entry_overlay
        from scar.ir.program.static_calls import StaticFunctionCreationRoute
        class_ns,=session.select_bodies(file=str(path),entry='<module>.Box')
        method_ns,=session.select_bodies(file=str(path),entry='<module>.Box.method')
        class_body=session.load_body(class_ns);method_body=session.load_body(method_ns)
        overlay=decode_class_entry_overlay(class_body.document['class'])
        factory=next(row for row in overlay.factories if row.definition==method_ns.definition)
        code_use=next(row.use for row in class_body.metadata.use_links
            if row.operation==factory.operation and row.role=='function-code')
        constant_op=class_body.index.values[class_body.index.use_site(code_use).use.value].origin.operation
        constant=next(row for row in overlay.constants if row.operation==constant_op)
        edge,value=normal_reference(class_body.index,factory.operation)
        with StaticCallSession(model,out=tmp_path/'origin-source-basis')as original_source:
            qualified=original_source._unit(0).definitions[method_ns.definition][0]
            class_creation=StaticFunctionCreationRoute(factory.operation,edge,value,code_use,
                constant.operation,overlay.compilation.code_layout_key,constant.constant_path,qualified)
            class_inputs=dict(creator_graph=class_body.graph,creator_document=class_body.document,
                creator_namespace=class_ns,creator_index=class_body.index,body_graph=method_body.graph,
                body_document=method_body.document,body_namespace=method_ns,body_index=method_body.index,source_text=text)
            class_origins=derive_factory_entry_origins(creation=class_creation,**class_inputs)
            assert len(class_origins)==2
            for origin in class_origins:assert validate_factory_entry_origin(origin,**class_inputs)
            bad=deepcopy(class_body.document)
            capture=next(row for row in bad['metadata']['use_links']
                if row['operation']==encode(factory.operation)and row['role']=='function-globals')
            assert capture['index']==1
            capture['index']=0
            with pytest.raises(ValueError,match='role index'):
                derive_factory_entry_origins(creation=class_creation,**{**class_inputs,'creator_document':bad})


def test_session_discovers_factory_origins_without_call_targets_and_keeps_open_class_path(tmp_path, monkeypatch):
    import hashlib
    import json
    import subprocess
    import sys
    from scar.analysis.program_dependency_session import ProgramDependencySession
    from scar.analysis.static_class_publication import link_static_class_program
    from scar.analysis.program_dependency_export import export_dependency_walk
    from scar.ir.program.dependencies import (
        DependencyKind as K, DependencyPoint as P, DependencyStrength, GraphNamespace,
        OpenDependencyContext, context_frames,
    )

    source=tmp_path/'source';source.mkdir();path=source/'application.py';model=tmp_path/'model'
    text=('G = 7\ndef direct(x):\n    return G + x\n'
        'def outer(x):\n    def inner(y):\n        return G + x + y\n    return inner\n'
        'class Box:\n    def method(self, x: int):\n        return G + x\n'
        'raise RuntimeError("application must never execute")\n')
    path.write_text(text)
    built=subprocess.run([sys.executable,'-B','-m','scar.cli','static',str(source),'--out',str(model),
        '--jobs','1','--phase','bodies'],capture_output=True,text=True)
    assert built.returncode==0,built.stdout+built.stderr
    manifest=json.loads((model/'manifest.json').read_bytes())
    assert 'static_calls' not in manifest and 'static_classes' not in manifest
    original_graphs={row['artifact']['path']:hashlib.sha256((model/row['artifact']['path']).read_bytes()).hexdigest()
        for unit in manifest['units']for row in unit['bodies']if 'artifact'in row}

    # Ordinary callers provide only a body/port. No source definition,
    # factory, origin list or target publication is supplied by the test.
    with ProgramDependencySession(model)as session:
        graph=session.graph()
        for name in ('<module>.direct','<module>.outer.inner','<module>.Box.method'):
            namespace,=session.select_bodies(file=str(path),entry=name)
            body=session.load_body(namespace)
            definition=session.source_definition_reference(namespace)
            assert definition.definition==namespace.definition
            assert definition.root.representation=='canonical-json'
            assert session.validate_source_definition_reference(definition,namespace)
            with pytest.raises(ValueError):
                session.validate_source_definition_reference(replace(definition,
                    graph=replace(definition.graph,pointer='#/definitions/999999')),namespace)
            member=next(member for env in body.graph.environments for member in env.members
                if member.role is EnvironmentRole.GLOBALS_NAMESPACE)
            point=P(GraphNamespace.from_source(namespace),member.reference)
            neighborhood=graph.incoming(point,kinds=(K.ENVIRONMENT,))
            origins=[edge for edge in neighborhood.edges if any(e.rule=='STATIC_FACTORY_ENTRY_REFERENCE_ORIGIN_V1'
                for e in edge.evidence)]
            assert origins,name
            assert all(edge.strength is DependencyStrength.MAY and edge.target==point for edge in origins)
            assert all(edge.source.context is None for edge in origins)
            for edge in origins:
                reverse=graph.outgoing(edge.source,kinds=(K.ENVIRONMENT,))
                assert any(other.source==edge.source and other.target.namespace==edge.target.namespace
                    and other.target.node==edge.target.node and other.target.context is None
                    for other in reverse.edges)
            assert not neighborhood.enumerated
        assert not (model/'indexes/calls').exists()
        assert session.measurements()['relationship_shards_read']==0

        # A query budget must preserve the already emitted prefix, and a
        # failure before direction discovery must retain its actual reason.
        from scar.analysis.program_function_origin_dependencies import FactoryEntryOriginDependencyProvider
        discovery=session._origin_discovery
        selected_source=origins[0].source
        def prefix_then_budget(point):
            for item in discovery.origins_for(point):
                yield item
                raise OverflowError('controlled discovery budget after a known relation')
        limited=FactoryEntryOriginDependencyProvider(origins_for=prefix_then_budget,load_index=session.index,
            validate_origin=discovery.validate_origin,interface_scope=discovery.interface_scope,
            contexts_for=discovery.contexts_for)
        prefix=limited.outgoing(selected_source)
        assert prefix.edges and not prefix.enumerated
        assert any(f.kind=='FACTORY_ORIGIN_QUERY_BUDGET'for f in prefix.frontiers)
        def unavailable_body(namespace):
            raise OverflowError('controlled budget before discovery determines direction')
        early=FactoryEntryOriginDependencyProvider(origins_for=discovery.origins_for,load_index=session.index,
            validate_origin=discovery.validate_origin,interface_scope=lambda point,outgoing:True,
            contexts_for=discovery.contexts_for,discovery_frontiers=discovery.frontiers_for)
        with monkeypatch.context()as patch:
            patch.setattr(discovery,'_body',unavailable_body)
            stopped=early.outgoing(selected_source)
        assert not stopped.edges and not stopped.enumerated
        assert any(f.kind=='FACTORY_ORIGIN_QUERY_BUDGET'for f in stopped.frontiers)

    # Existing class interfaces give the known suffix. Their unknown outer
    # prefix stays unknown all the way back to the original module G port.
    link_static_class_program(model)
    with ProgramDependencySession(model)as session:
        namespace,=session.select_bodies(file=str(path),entry='<module>.Box.method')
        body=session.load_body(namespace)
        member=next(member for env in body.graph.environments for member in env.members
            if member.role is EnvironmentRole.GLOBALS_NAMESPACE)
        root=P(GraphNamespace.from_source(namespace),member.reference)
        module_namespace,=session.select_bodies(file=str(path),entry='<module>')
        module_body=session.load_body(module_namespace)
        destination=P(GraphNamespace.from_source(module_namespace),module_body.graph.frame_roots[0].entry.globals_namespace,None)
        graph=session.graph();walk=graph.walk((root,),kinds=(K.ENVIRONMENT,K.ARGUMENT,K.VALUE_USE),
            max_points=48,max_edges=96,max_depth=16)
        assert destination in walk.points
        assert any(type(point.context)is OpenDependencyContext and len(context_frames(point.context))==2
            for point in walk.points)
        assert any(type(point.context)is OpenDependencyContext and len(context_frames(point.context))==1
            for point in walk.points)
        assert not walk.dependence_closed
        exported=export_dependency_walk(walk)
        assert exported['schema_version']==3
        assert any(row['unknown_prefix'] for row in exported['contexts'])
        assert any(not row['unknown_prefix'] for row in exported['contexts'])
        assert any(point['context'] is None for point in exported['points'])
    assert all(hashlib.sha256((model/name).read_bytes()).hexdigest()==sha
        for name,sha in original_graphs.items())


def test_environment_entry_is_complete_and_free_cells_have_their_own_interface_slots(tmp_path):
    body, context = _lower(tmp_path,
        "must_never_execute_source()\n"
        "def outer(z, a):\n"
        "    def inner(x):\n"
        "        return z + a + x\n"
        "    return inner\n", "inner")
    _, values, _ = _indexes(body)
    environment, = body.graph.environments
    layout, = body.graph.function_entries
    assert tuple(member.role for member in environment.members[:5]) == (
        EnvironmentRole.FUNCTION_OBJECT, EnvironmentRole.GLOBALS_NAMESPACE,
        EnvironmentRole.BUILTINS_NAMESPACE, EnvironmentRole.DEFAULTS,
        EnvironmentRole.KEYWORD_DEFAULTS)
    cells = environment.members[5:]
    assert tuple(member.cell_slot for member in cells) == tuple(
        captured_cell_slot(body.interface.definition, name) for name in ("a", "z"))
    assert tuple(member.cell_position for member in cells) == (0, 1)
    outer_slots = {slot.slot_id for slot in context.semantic.slots.values() if slot.name in {"a", "z"}}
    assert not outer_slots.intersection(member.cell_slot for member in cells)
    region, = body.graph.regions
    entry = next(block for block in region.blocks if block.id == region.entry)
    assert entry.arguments == tuple(member.reference for member in environment.members) + (
        body.interface.parameters[0].value, body.interface.world)
    assert layout.parameters == body.interface.parameters
    for index, identity in enumerate(entry.arguments):
        assert values[identity].origin == BlockArgument(entry.id, index)
    frame_enter, = _protocol_operations(body, PythonProtocolKind.FRAME_ENTER)
    assert tuple(use.value for use in _reference_uses(frame_enter, values)) == entry.arguments[:-1]
    assert all(member.locations == (values[body.interface.world].location,) for member in environment.members)


def test_free_cell_reads_keep_owner_world_and_exception_paths(tmp_path):
    body, _ = _lower(tmp_path,
        "def outer(shared):\n"
        "    def inner(mutate):\n"
        "        return shared + mutate() + shared\n"
        "    return inner\n", "inner")
    _, values, _ = _indexes(body)
    reads = _protocol_operations(body, PythonProtocolKind.READ_FREE_CELL)
    assert len(reads) == 2
    owner = body.graph.environments[0].members[5].reference
    addresses = {row.site.operation: row for row in body.graph.state_address_refinements}
    before_values = []
    for operation in reads:
        assert operation.uses[0].value == owner
        assert operation.terminator.kind is TerminatorKind.INVOKE
        assert {signature.kind.value for signature in operation.completions} == {"NORMAL", "RAISE"}
        assert not operation.effects_complete
        address = addresses[operation.id]
        assert address.coverage is AddressCoverage.PARTIAL
        assert address.site.state_use == operation.uses[-1].id
        effect, = address.effects
        assert effect.owner == ReferenceOwner(operation.uses[0].id)
        assert effect.path == (CellContent(),)
        assert isinstance(values[operation.uses[-1].value], StateVersionValue)
        before_values.append(operation.uses[-1].value)
    assert before_values[0] != before_values[1]
    assert not _protocol_operations(body, PythonProtocolKind.LOOKUP_GLOBAL)


def test_nonlocal_write_uses_the_captured_cell_instead_of_a_local_token(tmp_path):
    body, _ = _lower(tmp_path,
        "def outer(shared):\n"
        "    def inner(value):\n"
        "        nonlocal shared\n"
        "        shared = value\n"
        "        return shared\n"
        "    return inner\n", "inner")
    _, values, _ = _indexes(body)
    store, = _protocol_operations(body, PythonProtocolKind.STORE_CELL)
    read, = _protocol_operations(body, PythonProtocolKind.READ_FREE_CELL)
    cell = body.graph.environments[0].members[5].reference
    assert store.uses[0].value == read.uses[0].value == cell
    assert store.uses[1].value != cell
    assert not _protocol_operations(body, PythonProtocolKind.STORE_GLOBAL)
    assert len(next(signature for signature in store.completions if signature.kind.value == "NORMAL").types) == 1
    assert all(not isinstance(value, LocalBindingValue) or value.slot != captured_cell_slot(
        body.interface.definition, "shared") for value in values.values())
    assert all(link.source.start_line != 3 for link in body.metadata.operation_links)


def test_global_lookup_uses_saved_builtins_and_explicit_name_key(tmp_path):
    body, _ = _lower(tmp_path,
        "G = 1\n"
        "def f(x):\n"
        "    global G\n"
        "    G = x\n"
        "    return len(G)\n", "f")
    _, values, _ = _indexes(body)
    environment = body.graph.environments[0]
    globals_ref, builtins_ref = environment.members[1].reference, environment.members[2].reference
    lookups = _protocol_operations(body, PythonProtocolKind.LOOKUP_GLOBAL)
    assert len(lookups) == 2
    assert {values[operation.uses[2].value].origin.value for operation in lookups} == {"len", "G"}
    rows = {row.site.operation: row for row in body.graph.state_address_refinements}
    for operation in lookups:
        assert tuple(use.value for use in operation.uses[:2]) == (globals_ref, builtins_ref)
        row = rows[operation.id]
        assert row.coverage is AddressCoverage.PARTIAL
        assert tuple(effect.owner for effect in row.effects) == tuple(
            ReferenceOwner(operation.uses[index].id) for index in (0, 1))
        assert all(effect.path == (NamespaceKey(operation.uses[2].id),) for effect in row.effects)
    store, = _protocol_operations(body, PythonProtocolKind.STORE_GLOBAL)
    assert store.uses[0].value == globals_ref
    assert values[store.uses[1].value].origin.value == "G"
    assert not _protocol_operations(body, PythonProtocolKind.MAKE_CELL)


def test_own_formal_cell_is_created_per_invocation_and_not_a_captured_port(tmp_path):
    body, _ = _lower(tmp_path,
        "def outer(x):\n"
        "    x = x + 1\n"
        "    return x\n"
        "    def inner():\n"
        "        return x\n", "outer")
    _, values, _ = _indexes(body)
    assert len(body.graph.environments[0].members) == 5
    make, = _protocol_operations(body, PythonProtocolKind.MAKE_CELL)
    assert Behavior.MEMORY in make.behaviors
    assert make.uses[0].value == body.interface.parameters[0].value
    reads = _protocol_operations(body, PythonProtocolKind.READ_LOCAL_CELL)
    store, = _protocol_operations(body, PythonProtocolKind.STORE_CELL)
    owners = {operation.uses[0].value for operation in (*reads, store)}
    assert len(owners) == 1
    cell = owners.pop()
    assert cell != body.interface.parameters[0].value
    assert isinstance(values[cell], ReferenceValue)
    assert not _protocol_operations(body, PythonProtocolKind.READ_FREE_CELL)
    formal_slot = body.interface.parameters[0].slot
    assert not any(isinstance(value, LocalBindingValue) and value.slot == formal_slot for value in values.values())
    exits = _protocol_operations(body, PythonProtocolKind.FRAME_EXIT)
    assert any(cell in {use.value for use in operation.uses} for operation in exits)


def test_uninitialized_local_cell_is_not_initialized_to_none(tmp_path):
    body, _ = _lower(tmp_path,
        "def outer():\n"
        "    return x\n"
        "    x = None\n"
        "    def inner():\n"
        "        return x\n", "outer")
    _, values, _ = _indexes(body)
    make, = _protocol_operations(body, PythonProtocolKind.MAKE_CELL)
    assert not _reference_uses(make, values)
    assert len(_protocol_operations(body, PythonProtocolKind.READ_LOCAL_CELL)) == 1
    assert not _protocol_operations(body, PythonProtocolKind.READ_FREE_CELL)


def test_address_owner_must_be_an_operation_owned_reference_use(tmp_path):
    body, _ = _lower(tmp_path, "def f():\n    return missing\n", "f")
    _indexes(body)
    row = body.graph.state_address_refinements[0]
    operation = next(operation for operation in body.graph.operations if operation.id == row.site.operation)
    bad_effect = replace(row.effects[0], owner=ReferenceOwner(operation.uses[-1].id))
    corrupted = replace(body.graph, state_address_refinements=(replace(row, effects=(bad_effect,)),))
    with pytest.raises(ValueError):
        require_valid(corrupted)


def test_source_program_v4_round_trip_does_not_reinterpret_structured_v1(tmp_path):
    path = tmp_path / "application.py"
    path.write_text("def f(x):\n    return external(x)\n")
    current = lower_source(path, "f", profile=BodyLoweringProfile.STRUCTURED_ENV)
    document = current.to_dict()
    assert document["schema_version"] == 4
    assert document["profile"] == "STRUCTURED_ENV_V1"
    assert document["summary"]["whole_program_coverage_established"] is False
    assert SourceProgram.from_dict(document).to_dict() == document
    historical = lower_source(path, "f", profile=BodyLoweringProfile.STRUCTURED_BODY)
    assert historical.to_dict()["schema_version"] == 3
    assert not historical.graph.environments
    assert not historical.graph.state_address_refinements
    assert SourceProgram.from_dict(historical.to_dict()).to_dict() == historical.to_dict()


@pytest.mark.parametrize("text", [
    "def f():\n    yield missing\n",
    "async def f():\n    return missing\n",
    "def f():\n    def nested():\n        return missing\n    return nested\n",
])
def test_unimplemented_body_protocols_remain_coverage_failures(tmp_path, text):
    body, _ = _lower(tmp_path, text, "f")
    assert body.graph is None
    assert body.interface is None
    assert body.metadata.gaps
