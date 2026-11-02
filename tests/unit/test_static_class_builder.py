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
    model = tmp_path / 'model'
    build_static_program(source_root, out=model, jobs=1, phase='graph')
    refine_static_program(model)
    expand_static_bodies(model, jobs=1)
    before_manifest = (model / 'manifest.json').read_bytes()
    publication = build_static_class_links(model, tmp_path / 'class-index')
    assert publication['counts']['connected_class_constructions'] == 1
    assert publication['counts']['shared_provider_graphs'] == 1
    assert publication['scope']['enumeration_complete'] is True
    assert publication['scope']['whole_program_model_complete'] is False
    reread = read_static_class_links(model, publication)
    assert len(reread) == 1
    assert reread[0].provider.freevars == ('x',)
    assert (model / 'manifest.json').read_bytes() == before_manifest

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
