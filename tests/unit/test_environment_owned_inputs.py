"""One private source decode, independent namespace checks, no target execution."""
import hashlib
import json
from dataclasses import replace

import pytest


def test_owned_source_inputs_reuse_without_lending_namespace_authority(monkeypatch, tmp_path):
    import scar.analysis.static_function_environment as environment
    from scar.ir.program.codec import dumps
    from scar.ir.program.functions import BodyEntryInterface, FormalPort
    from scar.ir.program.ids import BlockID, LocationID, OperationID, RegionID, UseID, ValueID
    from scar.ir.program.model import (Behavior, Block, BlockArgument, ExitKind, ExitPort,
        Operation, ProgramGraph, ReferenceValue, Region, StateLocation, StateVersionValue,
        Terminator, TerminatorKind, Use, UseRole, ValueKind, ValueType)
    from scar.ir.program.providers import ProviderArtifact, ProviderFactReference
    from scar.ir.program.queries import ProgramIndex
    from scar.ir.program.source import LoweringMetadata, SourceRole, ValueSource
    from scar.ir.program.source_call_bindings import SourceBodyNamespace
    from scar.ir.program.source_references import SourceArtifactLocator
    from scar.ir.record_codec import encode
    from scar.ir.semantics_v2 import SourceSnapshot
    from scar.ir.v2.common import SourceReference
    from scar.ir.v2.ids import OperationDefinitionID, SourceAtomID, ValueSlotID

    root, block, location = RegionID('function'), BlockID('entry'), LocationID('world')
    value, world, identity = ValueID('arg'), ValueID('world'), OperationID('return')
    uses = (Use(UseID('value'), value, UseRole.REFERENCE),
            Use(UseID('state'), world, UseRole.STATE_CONTENT))
    returned = Operation(identity, 'return', (Behavior.CONTROL,), uses, effects_complete=True,
        terminator=Terminator(TerminatorKind.RETURN, exit='normal', values=tuple(u.id for u in uses)))
    graph = ProgramGraph(root, (Region(root, 'function', block,
        (Block(block, (value, world), (identity,)),),
        (ExitPort('normal', ExitKind.NORMAL, (ValueType(ValueKind.REFERENCE),
            ValueType(ValueKind.STATE, location=location))),)),), (returned,),
        (ReferenceValue(value, root, BlockArgument(block, 0)),
         StateVersionValue(world, root, BlockArgument(block, 1), location)), (StateLocation(location, 'world'),))
    index = ProgramIndex(graph)
    fingerprint = 'sha256:' + hashlib.sha256(b'def f(x): return x\n').hexdigest()
    snapshot = SourceSnapshot(str(tmp_path / 'example.py'), fingerprint, 'utf-8', '3.14')
    source = SourceReference(SourceAtomID('function'), snapshot.path, fingerprint, 1, 1, 0, 18)
    definition = OperationDefinitionID('f')
    interface = BodyEntryInterface(definition, root, (FormalPort(ValueSlotID('x'), value),), world)
    metadata = LoweringMetadata(definition.wire, snapshot,
        value_links=(ValueSource(world, source, SourceRole.STATE),))
    document = {'schema': 'scar.static-body', 'schema_version': 1,
        'graph': json.loads(dumps(graph)), 'metadata': encode(metadata),
        'interface': encode(interface), 'module': None, 'class': None, 'structured': None}
    artifact = ProviderArtifact(str(tmp_path / 'body.json.gz'), '0' * 64, 1, 'scar.static-body/1')
    declaration = ProviderFactReference(ProviderArtifact(str(tmp_path / 'basis.json.gz'),
        '2' * 64, 1, 'scar.static-call-source-basis/1'), '#/units/0/bodies/0/artifact')
    locator = SourceArtifactLocator(artifact, '1' * 64, 100, 'gzip-canonical-json', '#/graph', declaration)
    namespace = SourceBodyNamespace(locator, 'scar.program-graph/' + str(document['graph']['schema_version']),
                                    definition, source, definition.wire, root)
    original, decoded = environment.decode, []
    def counted(kind, wire):
        if kind is LoweringMetadata:
            decoded.append(wire)
        return original(kind, wire)
    monkeypatch.setattr(environment, 'decode', counted)
    owner = environment._EnvironmentFacts()
    inputs = owner.inputs(graph, document, index=index, size_bytes=100)
    assert inputs.metadata == metadata and inputs.interface == interface
    assert owner.inputs(graph, document, index=index, size_bytes=100) is inputs
    assert owner.body(graph, document, namespace, index=index, inputs=inputs).metadata is inputs.metadata
    assert owner.body(graph, document, namespace, index=index).metadata is inputs.metadata
    with pytest.raises(ValueError, match='entry'):
        owner.body(graph, document, replace(namespace, entry='wrong'), index=index, inputs=inputs)
    with pytest.raises(ValueError, match='another owner'):
        environment._EnvironmentFacts().body(graph, document, namespace, index=index, inputs=inputs)
    with pytest.raises(ValueError, match='another owner'):
        owner.body(graph, dict(document), namespace, index=index, inputs=inputs)
    wire = document['metadata']
    document['metadata'] = dict(wire)
    with pytest.raises(ValueError, match='source inputs changed'):
        owner.body(graph, document, namespace, index=index, inputs=inputs)
    document['metadata'] = wire
    assert len(decoded) == 1
    assert environment.validate_static_body_namespace(graph, document, namespace) == metadata
    assert len(decoded) == 2  # The public fresh-check entry has no typed shortcut.
