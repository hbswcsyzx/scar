"""Installed ATen declarations are static materials, never target execution."""
import hashlib
from pathlib import Path
import sys
import sysconfig

import pytest

from scar.analysis.static_native_materials import NativeMaterialError, read_static_native_materials


def test_static_native_materials_exact_overloads_effects_and_isolation(tmp_path, monkeypatch):
    site = Path(sysconfig.get_paths()['purelib']).resolve()
    if not (site / 'torchgen/packaged/ATen/native/native_functions.yaml').is_file():
        pytest.skip('installed ATen build materials are unavailable')
    # A CWD module and startup path hook must not run in the tool worker.
    marker = tmp_path / 'target-was-imported'
    (tmp_path / 'torch.py').write_text('from pathlib import Path\nPath(' + repr(str(marker)) + ').touch()\nraise RuntimeError("target import")\n')
    (tmp_path / 'sitecustomize.py').write_text('raise RuntimeError("startup hook")\n')
    monkeypatch.chdir(tmp_path)
    monkeypatch.setenv('PYTHONPATH', str(tmp_path))
    before = {name for name in sys.modules if name.partition('.')[0] == 'torch'}
    selectors = ('aten::to.device', 'aten::to.dtype', 'aten::copy_', 'aten::expand',
        'aten::empty.memory_format', 'aten::empty.out')
    result = read_static_native_materials(site, selectors)
    assert tuple(row.selector for row in result.declarations) == selectors
    assert result.parser.isolated and result.parser.no_site and not result.parser.torch_imported
    assert all(name.partition('.')[0] in ('torchgen', 'yaml', 'typing_extensions') for name in result.parser.imported_tools)
    assert not any(name.startswith(('torchgen.api', 'torchgen.gen')) for name in result.parser.imported_tools)
    assert before == {name for name in sys.modules if name.partition('.')[0] == 'torch'}
    assert not marker.exists()
    rows = {row.selector: row for row in result.declarations}
    device, dtype = rows['aten::to.device'], rows['aten::to.dtype']
    assert device.overload == 'device' and dtype.overload == 'dtype'
    assert next(p for p in device.inputs if p.name == 'device').type.text == 'Device'
    assert next(p for p in device.inputs if p.name == 'copy').default == 'False'
    assert device.inputs[0].alias.before == device.outputs[0].alias.before == ('a',)
    assert not device.declared_mutable and not device.dispatch_declared
    copy = rows['aten::copy_']
    assert copy.declared_mutable and copy.inputs[0].alias.may_write and copy.outputs[0].alias.may_write
    assert copy.dispatch_declared and any('CompositeExplicitAutograd' in d.keys for d in copy.dispatch)
    expand = rows['aten::expand']
    assert expand.inputs[0].alias.before == expand.outputs[0].alias.before == ('a',)
    assert 'PHYSICAL_RESOURCES_TRANSFERS_AND_ORDER' in expand.open_fields
    empty, out = rows['aten::empty.memory_format'], rows['aten::empty.out']
    assert not empty.declared_mutable and empty.outputs[0].alias is None
    assert out.declared_mutable and out.inputs[-1].kind == 'out' and out.inputs[-1].alias.may_write
    assert any('CUDA' in d.keys for d in empty.dispatch)
    for row in result.declarations:
        for source in (row.header_source, row.yaml_source, row.schema_source):
            raw = Path(source.path).read_bytes()
            assert len(raw) == source.size_bytes and hashlib.sha256(raw).hexdigest() == source.sha256
            selected = raw[source.byte_start:source.byte_end]
            assert selected and hashlib.sha256(selected).hexdigest() == source.selection_sha256
            assert source.start_line <= source.end_line
    with pytest.raises(NativeMaterialError, match='unknown exact native schema'):
        read_static_native_materials(site, ('aten::to.not_an_overload',))
    with pytest.raises(NativeMaterialError, match='distribution is required'):
        read_static_native_materials(tmp_path, ('aten::copy_',))

    # The same real parser result becomes canonical native interface regions,
    # without a target run, invented runtime evidence, effects or device use.
    import json
    from scar.analysis.static_native_interfaces import (
        SCHEMA, native_material_document, lower_static_native_materials,
    )
    from scar.analysis.program_dependencies import ProgramDependencyGraph
    from scar.ir.program.codec import SCHEMA_VERSION, dumps, loads
    from scar.ir.program.dependencies import DependencyPoint, GraphNamespace
    from scar.ir.program.model import ReferenceValue, StateVersionValue
    from scar.ir.program.providers import ProviderArtifact
    from scar.ir.program.queries import ProgramIndex
    from scar.ir.program.source_references import SourceArtifactLocator
    raw = json.dumps(native_material_document(result), sort_keys=True, allow_nan=False).encode()
    materials_path = tmp_path / 'materials.json'
    materials_path.write_bytes(raw)
    materials_artifact = ProviderArtifact(str(materials_path), hashlib.sha256(raw).hexdigest(), len(raw), SCHEMA)
    graphs = lower_static_native_materials(result, materials_artifact)
    assert len(graphs) == len(selectors)
    for position, graph in enumerate(graphs):
        index = ProgramIndex(loads(dumps(graph)))
        boundary = graph.native_boundaries[0]
        assert graph.provider_envelopes[0].capture_scope is None
        assert not graph.resources and not graph.resource_requirements
        assert not graph.boundary_relations  # No Python/native equivalence invented.
        assert not next(op for op in graph.operations if op.completions).effects_complete
        assert len(boundary.inputs) == len(result.declarations[position].inputs)
        assert boundary.signature.locator == '#/declarations/' + str(position) + '/schema'
        assert all(slot.evidence.artifact == materials_artifact for slot in (*boundary.inputs, *boundary.outputs))
        assert type(index.entry_port(boundary.core_inputs[0].port)) is StateVersionValue
        assert {port.port.exit_name for port in boundary.core_outputs} == {'normal', 'raised'}
        # One native Tensor port stays one reference.  Alias annotations do
        # not unify input/output references or create concrete storage targets.
        for value in graph.values:
            if type(value) is ReferenceValue:
                assert value.targets is None
        graph_raw = dumps(graph).encode()
        graph_path = tmp_path / ('interface-' + str(position) + '.json')
        graph_path.write_bytes(graph_raw)
        graph_sha = hashlib.sha256(graph_raw).hexdigest()
        graph_locator = SourceArtifactLocator(ProviderArtifact(str(graph_path), graph_sha,
            len(graph_raw), 'scar.program-graph'), graph_sha, len(graph_raw), 'canonical-json')
        ns = GraphNamespace(graph_locator, 'scar.program-graph/' + str(SCHEMA_VERSION), graph.root)
        view = ProgramDependencyGraph(lambda namespace: index)
        declaration = view.outgoing(DependencyPoint(ns, boundary.id))
        assert any(edge.target.node == boundary.region for edge in declaration.edges)
        assert any(f.kind == 'NATIVE_SIGNATURE_BINDING_OPEN' for f in declaration.frontiers)
    materials_path.write_bytes(raw + b' ')
    with pytest.raises(ValueError, match='size differs'):
        lower_static_native_materials(result, materials_artifact)
