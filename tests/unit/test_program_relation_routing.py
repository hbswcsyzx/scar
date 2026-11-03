"""Raw routing reuses only the full exact wire within one shard scan."""
from copy import deepcopy

import pytest


def test_exact_namespace_wire_reuse_preserves_validation_budget_and_foreign_routes(tmp_path, monkeypatch):
    from scar.analysis import program_relation_routing as routing
    from scar.ir.program.dependencies import GraphNamespace
    from scar.ir.program.ids import RegionID
    from scar.ir.program.providers import ProviderArtifact, ProviderFactReference
    from scar.ir.program.source_call_bindings import SourceBodyNamespace
    from scar.ir.program.source_references import SourceArtifactLocator
    from scar.ir.record_codec import encode
    from scar.ir.v2.common import SourceReference
    from scar.ir.v2.ids import OperationDefinitionID, SourceAtomID

    def namespace(label):
        artifact = ProviderArtifact(str(tmp_path / (label + '.json.gz')), 'a' * 64, 100, 'scar.static-body/1')
        basis = ProviderArtifact(str(tmp_path / 'basis.json.gz'), 'b' * 64, 100, 'scar.static-call-source-basis/1')
        locator = SourceArtifactLocator(artifact, 'c' * 64, 200, 'gzip-canonical-json', '#/graph',
            ProviderFactReference(basis, '#/units/0/bodies/0/artifact'))
        source = SourceReference(SourceAtomID(label), str(tmp_path / 'program.py'), 'sha256:' + 'd' * 64,
            1, 2, 0, 8)
        return SourceBodyNamespace(locator, 'scar.program-graph/32', OperationDefinitionID(label),
            source, label, RegionID(label))

    primary, foreign = namespace('primary'), namespace('foreign')
    wire = encode(primary)
    original_decode = routing.decode
    decoded = []

    def counted_decode(kind, record):
        decoded.append(record)
        return original_decode(kind, record)

    monkeypatch.setattr(routing, 'decode', counted_decode)
    expected = {GraphNamespace.from_source(primary).identity}
    assert routing._namespace_identities({'repeated': [deepcopy(wire) for _ in range(32)]}, lambda: None) == expected
    assert len(decoded) == 1
    assert routing._namespace_identities({'another_shard': wire}, lambda: None) == expected
    assert len(decoded) == 2  # no successful validation survives the shard scan

    # The graph identity is unchanged, but malformed source metadata cannot
    # borrow a prior full-record validation. Traversal visits the valid one first.
    invalid = deepcopy(wire)
    invalid['source']['start_line'] = 0
    decoded.clear()
    with pytest.raises(ValueError):
        routing._namespace_identities([invalid, wire], lambda: None)
    assert len(decoded) == 2

    relations = {'source_model': {'receipt': 'original-basis'}, 'caller': wire,
        'calls': [{'foreign_witness': [encode(foreign) for _ in range(12)]}],
        'import_routes': [], 'module_attribute_flows': [], 'module_frontiers': [], 'module_globals_flows': []}
    document = {'schema': 'scar.static-calls', 'schema_version': 9, 'relations': relations}
    options = dict(items={'one': {'caller': wire}}, source_model=relations['source_model'], version=9,
        read=lambda uri: document, check=lambda: None, max_shards=1)
    complete = routing.RawCallRelationRouting(**options, max_references=2)
    result = complete.lookup(GraphNamespace.from_source(foreign))
    assert result.complete and result.uris == ('one',)
    assert complete.references == 2 and complete.shards == 1
    bounded = routing.RawCallRelationRouting(**options, max_references=1)
    prefix = bounded.lookup(GraphNamespace.from_source(foreign))
    assert not prefix.complete and prefix.uris == ()
    assert 'reference budget exhausted' in prefix.issue
    assert bounded.references == bounded.shards == 0  # no half-shard commit

