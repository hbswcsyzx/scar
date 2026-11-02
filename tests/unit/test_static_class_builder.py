"""A standard-builder alternative connects original ports without executing it."""
from dataclasses import replace
import hashlib
import json

import pytest

from scar.analysis.program_lowering import prepare_source_text
from scar.analysis.source_class_body_lowering import lower_class_suite
from scar.analysis.source_language import SourceLanguageOptions
from scar.analysis.static_class_builder import (
    build_class_provider, connect_class_suite, validate_class_builder_expansion,
)
from scar.analysis.static_compilation import compile_source_unit
from scar.analysis.static_lexical import inspect_lexical
from scar.analysis.static_rules import plan_static_entry
from scar.ir.program.class_builder import ClassBuilderExpansion, ClassBuilderStageKind as K
from scar.ir.program.class_entries import ClassNormalPayloadKind
from scar.ir.program.codec import SCHEMA_VERSION, dumps, loads
from scar.ir.program.functions import BodyLoweringProfile
from scar.ir.program.providers import ProviderArtifact, ProviderFactReference
from scar.ir.program.source_call_bindings import SourceBodyNamespace
from scar.ir.program.source_language import SourceLanguageCapability
from scar.ir.program.source_references import SourceArtifactLocator
from scar.ir.record_codec import decode, encode
from scar.ir.v2.common import SourceReference
from scar.ir.v2.ids import OperationDefinitionID


SOURCE = """def outer(x):
    @decorate
    class C(Base, metaclass=Meta, flag=x):
        value = x
        def method(self):
            return __class__
    return C
raise RuntimeError('the target application must not run')
"""


def _namespace(directory, label, graph, definition, source, entry):
    payload = dumps(graph).encode()
    path = directory / (label + '.json')
    path.write_bytes(payload)
    sha = hashlib.sha256(payload).hexdigest()
    artifact = ProviderArtifact(str(path), sha, len(payload), 'scar.program-graph')
    declaration = directory / (label + '-declaration.json')
    declaration_bytes = json.dumps({'graph': encode(artifact)}).encode()
    declaration.write_bytes(declaration_bytes)
    receipt = ProviderArtifact(str(declaration), hashlib.sha256(declaration_bytes).hexdigest(),
        len(declaration_bytes), 'test.original-graph-declaration')
    locator = SourceArtifactLocator(artifact, sha, len(payload), 'canonical-json',
        declaration=ProviderFactReference(receipt, '#/graph'))
    return SourceBodyNamespace(locator, 'scar.program-graph/' + str(SCHEMA_VERSION),
        definition, source, entry, graph.root)


def test_class_builder_connects_prepared_mapping_current_environment_and_shared_suite(tmp_path):
    path = tmp_path / 'never_executed.py'
    prepared = prepare_source_text(path, SOURCE, project_root=tmp_path, root_is_package=False)
    fingerprint = prepared.semantics.sources[str(path)].fingerprint
    catalog = inspect_lexical(prepared.tree, path=str(path), namespace_root=str(tmp_path),
        fingerprint=fingerprint, semantic=prepared.semantic, source_text=SOURCE)
    parent_entry = next(e for e in catalog['entries'] if e['kind'] == 'FUNCTION' and e['name'] == 'outer')
    suite_entry = next(e for e in catalog['entries'] if e['kind'] == 'CLASS')
    compilation = compile_source_unit(prepared)
    parent_definition = decode(OperationDefinitionID, parent_entry['semantic_definition_ids'][0])
    parent_source = decode(SourceReference, parent_entry['source_ref'])
    parent_evidence = compilation.for_definition(parent_definition, parent_source)
    plan = plan_static_entry(prepared.tree, parent_entry, path=str(path), fingerprint=fingerprint)
    parent = prepared.seal_for_lowering().lower(parent_entry['name'], source=parent_source,
        expand_candidates=False, profile=BodyLoweringProfile.STRUCTURED_ENV,
        language_options=SourceLanguageOptions(tuple(SourceLanguageCapability(c) for c in plan['capabilities']),
            parent_evidence))
    assert parent.graph is not None, parent.metadata.gaps
    construction, = parent.language.class_constructions
    suite_definition = decode(OperationDefinitionID, suite_entry['semantic_definition_ids'][0])
    suite_source = decode(SourceReference, suite_entry['source_ref'])
    suite = lower_class_suite(prepared, suite_definition, suite_source,
        code_evidence=compilation.for_definition(suite_definition, suite_source))
    assert suite.overlay.remaining is None
    assert suite.overlay.interface.co_freevars == ('x',)
    assert suite.overlay.normal_payload is ClassNormalPayloadKind.CLASS_CELL
    parent_ns = _namespace(tmp_path, 'parent', parent.graph, parent_definition,
        parent_source, parent.metadata.entry)
    suite_ns = _namespace(tmp_path, 'suite', suite.graph, suite_definition,
        suite_source, suite.metadata.entry)
    original_parent_wire = dumps(parent.graph)
    expansion = connect_class_suite(parent_namespace=parent_ns, parent_graph=parent.graph,
        construction=construction, suite_namespace=suite_ns, suite_graph=suite.graph, suite_overlay=suite.overlay)
    validate_class_builder_expansion(expansion, parent_graph=parent.graph,
        suite_graph=suite.graph, suite_overlay=suite.overlay)
    provider = expansion.provider
    stages = {s.kind: s for s in provider.stages}
    prepared_namespace, = stages[K.PREPARE_NAMESPACE].results
    environment = stages[K.READ_FUNCTION_FRAME].results
    suite_ports = {p.role: p for p in expansion.suite_inputs}
    assert suite_ports['locals'].actual_value == prepared_namespace
    assert suite_ports['globals'].actual_value == environment[1]
    assert suite_ports['builtins'].actual_value == environment[2]
    assert suite_ports['closure'].actual_value == environment[3]
    assert suite_ports['locals'].formal == suite.overlay.interface.mapping.locals_namespace
    assert suite_ports['world'].actual_value == stages[K.READ_FUNCTION_FRAME].normal_world
    assert expansion.suite_completions[0].provider_values[0] == stages[K.EVAL_SUITE].results[0]
    assert stages[K.EVAL_SUITE].results != stages[K.CALL_METACLASS].results
    assert expansion.completions[0].parent_values[0] == construction.builder_call.result
    assert provider.effects_complete is False and expansion.original_builder_retained is True
    assert dumps(parent.graph) == original_parent_wire
    assert loads(dumps(provider.graph)) == provider.graph
    assert build_class_provider(base_count=provider.base_count, keyword_names=provider.keyword_names,
        freevars=provider.freevars) == provider
    assert decode(ClassBuilderExpansion, encode(expansion)) == expansion

    # A well-typed but wrong B/G/namespace mapping must not pass by shape.
    wrong_builtin = replace(suite_ports['builtins'], actual_value=suite_ports['globals'].actual_value)
    bad = replace(expansion, suite_inputs=tuple(wrong_builtin if p.role == 'builtins' else p
        for p in expansion.suite_inputs))
    with pytest.raises(ValueError, match='mappings differ'):
        validate_class_builder_expansion(bad, parent_graph=parent.graph,
            suite_graph=suite.graph, suite_overlay=suite.overlay)
    bad_provider = replace(provider, graph=replace(provider.graph,
        operations=tuple(replace(o, effects_complete=True) if o.id == stages[K.EVAL_SUITE].operation else o
            for o in provider.graph.operations)))
    with pytest.raises(ValueError, match='mappings differ'):
        validate_class_builder_expansion(replace(expansion, provider=bad_provider), parent_graph=parent.graph,
            suite_graph=suite.graph, suite_overlay=suite.overlay)
    with pytest.raises(ValueError, match='unknown builder'):
        replace(expansion, original_builder_retained=False)
    assert not path.exists()

    # The same rule must enumerate ordinary saved source catalogs and persist
    # shared provider shards, not require hand-picking a particular class.
    from scar.analysis.static_program import build_static_program, refine_static_program
    from scar.analysis.static_body import expand_static_bodies
    from scar.analysis.static_class_links import build_static_class_links, read_static_class_links
    source_root = tmp_path / 'application'
    source_root.mkdir()
    (source_root / 'app.py').write_text(SOURCE)
    (source_root / 'other.py').write_text(SOURCE.replace('class C(', 'class D(').replace('return C\n', 'return D\n'))
    (source_root / 'declarations.pyi').write_text('class DeclaredOnly:\n    value: int\n')
    model = tmp_path / 'model'
    build_static_program(source_root, out=model, jobs=1, phase='graph')
    refine_static_program(model)
    expand_static_bodies(model, jobs=1)
    before_manifest = (model / 'manifest.json').read_bytes()
    publication = build_static_class_links(model, tmp_path / 'class-index')
    assert publication['counts']['connected_class_constructions'] == 2
    assert publication['counts']['shared_provider_graphs'] == 1
    assert publication['scope']['enumeration_complete'] is True
    assert publication['scope']['whole_program_model_complete'] is False
    assert publication['counts']['declared_class_bodies'] == 3
    assert publication['counts']['frontier_CLASS_STUB_DECLARATION_ONLY'] == 1
    reread = read_static_class_links(model, publication)
    assert len(reread) == 2
    assert reread[0].provider.freevars == ('x',)
    assert (model / 'manifest.json').read_bytes() == before_manifest

    # A single view combines ordinary core edges with both original class
    # interfaces. The implementation graph is shared; its contexts are not.
    from scar.analysis.program_dependencies import ProgramDependencyGraph
    from scar.analysis.program_dependency_session import ProgramDependencySession
    from scar.analysis.program_class_dependencies import ClassDependencyProvider, class_dependency_frames
    from scar.ir.program.dependencies import DependencyKind as DK, DependencyPoint, GraphNamespace
    with ProgramDependencySession(model, class_publication=publication,
            class_index_directory=tmp_path / 'class-index') as session:
        adapter = ClassDependencyProvider(session.class_bindings_for, session.index, session.load_provider)
        view = ProgramDependencyGraph(session.index, providers=(adapter,))
        selected = []
        for expanded in reread:
            parent_namespace = GraphNamespace.from_source(expanded.parent)
            query = DependencyPoint(parent_namespace, expanded.construction.builder_call.operation)
            binding, _ = next(session.class_bindings_for(query))
            provider = session.load_provider(binding.provider)
            parent_ns, provider_ns, suite_ns, outer, inner = class_dependency_frames(binding, provider, session.index)
            selected.append((binding, provider, parent_ns, provider_ns, suite_ns, outer, inner))
            input_mapping = binding.inputs[0]
            parent_operand = DependencyPoint(parent_ns, input_mapping.actual_use)
            provider_formal = DependencyPoint(provider_ns, input_mapping.formal, (outer,))
            assert any(e.target == provider_formal and e.kind is DK.ARGUMENT
                for e in view.outgoing(parent_operand).edges)
            assert any(e.source == parent_operand for e in view.incoming(provider_formal).edges)
            locals_mapping = next(m for m in binding.suite_inputs if m.role == 'locals')
            eval_operand = DependencyPoint(provider_ns, locals_mapping.actual_use, (outer,))
            suite_formal = DependencyPoint(suite_ns, locals_mapping.formal, (outer, inner))
            assert any(e.target == suite_formal and e.conditions for e in view.outgoing(eval_operand).edges)
            assert any(e.source == eval_operand for e in view.incoming(suite_formal).edges)
            # The same graph API also supplies the existing local Value->Use
            # edge feeding that cross-fragment interface.
            assert any(e.source == DependencyPoint(provider_ns, locals_mapping.actual_value, (outer,))
                and e.kind is DK.VALUE_USE for e in view.incoming(eval_operand).edges)
            normal_cell = DependencyPoint(provider_ns, binding.suite_completions[0].provider_values[0], (outer,))
            assert any(e.source.namespace == suite_ns and e.source.context == (outer, inner)
                and e.kind is DK.COMPLETION for e in view.incoming(normal_cell).edges)
            normal_class = DependencyPoint(parent_ns, binding.construction.builder_call.result)
            assert any(e.source.namespace == provider_ns and e.source.context == (outer,)
                and e.kind is DK.COMPLETION for e in view.incoming(normal_class).edges)
            world = DependencyPoint(parent_ns, binding.construction.builder_call.normal_world)
            assert any(e.kind is DK.STATE_OUTPUT for e in view.incoming(world).edges)
            unbound = view.incoming(DependencyPoint(suite_ns, locals_mapping.formal))
            assert not any(e.kind is DK.ENVIRONMENT for e in unbound.edges)
            assert any(f.kind == 'CLASS_INTERFACE_CONTEXT_UNBOUND' for f in unbound.frontiers)
        left, right = selected
        assert left[3] == right[3]  # Same graph namespace, not merely same shape.
        assert left[5] != right[5]
        left_locals = next(m for m in left[0].suite_inputs if m.role == 'locals')
        neighbors = view.outgoing(DependencyPoint(left[3], left_locals.actual_use, (left[5],)))
        assert any(e.target.namespace == left[4] for e in neighbors.edges)
        assert not any(e.target.namespace == right[4] for e in neighbors.edges)

    # Publish into the one owned model and read through its manifest registry.
    # A preexisting call index and every original graph remain unchanged.
    from scar.analysis.static_program import link_static_program, read_static_program, _artifacts
    from scar.analysis.static_class_publication import link_static_class_program
    from scar.analysis.static_calls import input_basis_unit
    from scar.analysis.static_jobs import read_static_link_task
    called = link_static_program(model)
    calls_before = called['static_calls']
    basis_before = [input_basis_unit(unit) for unit in called['units']]
    original_receipts = {descriptor['path']: hashlib.sha256((model / descriptor['path']).read_bytes()).hexdigest()
                         for descriptor in _artifacts(called)}
    published = link_static_class_program(model)
    assert published['static_calls'] == calls_before
    assert [input_basis_unit(unit) for unit in published['units']] == basis_before
    assert published['static_classes']['counts']['published_bindings'] == 2
    assert published['static_classes']['counts']['frontier_CLASS_STUB_DECLARATION_ONLY'] == 1
    assert all(hashlib.sha256((model / name).read_bytes()).hexdigest() == sha
               for name, sha in original_receipts.items())
    read_static_program(model, verify=False)
    assert read_static_link_task(tmp_path / 'static-class-link-task.json')['observed_state'] == 'PUBLISHED'
    with ProgramDependencySession(model) as session:
        original = reread[0]
        # Resolve the same original ID through the current session declaration;
        # the earlier external publication's basis is not registered here.
        current_parents = [decode(SourceBodyNamespace, item['parent'])
            for item in published['static_classes']['shards']]
        current_parent, = [parent for parent in current_parents
            if GraphNamespace.from_source(parent) == GraphNamespace.from_source(original.parent)]
        query = DependencyPoint(GraphNamespace.from_source(current_parent), original.construction.builder_call.operation)
        binding, _ = next(session.class_bindings_for(query))
        argument = binding.inputs[0]
        point = DependencyPoint(GraphNamespace.from_source(binding.parent), argument.actual_use)
        assert any(edge.kind is DK.ARGUMENT and edge.target.namespace.representation == 'scar.static-class-provider/1:ProgramGraph'
                   for edge in session.graph().outgoing(point).edges)
        # A publication can lack this original mapping even when some other
        # classes were published. Missing edges then remain an open interface,
        # rather than an exhausted empty neighborhood.
        from scar.analysis.program_class_dependencies import ClassDependencyProvider
        omitted = ClassDependencyProvider(lambda p: (), session.index, session.load_provider,
            coverage=session._class_relation_coverage)
        missing = omitted.outgoing(point)
        assert not missing.enumerated
        assert any(f.kind == 'CLASS_RELATION_INTERFACE_OPEN' for f in missing.frontiers)
        complete = session._class_relation_coverage(point, incoming=False, bindings=(binding,))
        assert complete.enumerated and not complete.frontiers

    # Recomputed physical receipts cannot legalize a wrong stored relationship.
    import gzip
    descriptor = publication['shards'][0]['artifact']
    shard_path = tmp_path / 'class-index' / descriptor['path']
    document = json.loads(gzip.decompress(shard_path.read_bytes()))
    record = document['bindings'][0]
    ports = {p['role']: p for p in record['suite_inputs']}
    ports['builtins']['actual_value'] = ports['globals']['actual_value']
    payload = json.dumps(document, sort_keys=True, separators=(',', ':')).encode() + b'\n'
    stored = gzip.compress(payload, mtime=0)
    shard_path.write_bytes(stored)
    descriptor.update(sha256=hashlib.sha256(stored).hexdigest(), bytes=len(stored),
        decoded_sha256=hashlib.sha256(payload).hexdigest(), decoded_bytes=len(payload))
    with pytest.raises(ValueError, match='mappings differ'):
        read_static_class_links(model, publication)
