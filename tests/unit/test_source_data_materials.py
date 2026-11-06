"""Shared/cyclic data references keep occurrence spans and raw bytes."""
from scar.analysis.source_data_materials import parse_yaml_material
from scar.analysis.source_data_material_store import DataMaterialStore,write_data_material
from scar.ir.program.data_materials import DataNodeKind


def test_yaml_representation_graph_shares_nodes_without_constructing_containers(tmp_path):
    path=tmp_path/'data.yaml'
    raw=('root: &r\r\n  标记: ???\r\n  ref: ${root.标记}\r\n'
        '  loop: *r\r\nagain: *r\r\nitems: [1, true, null]\r\n').encode('utf-8')
    path.write_bytes(raw)
    material,captured=parse_yaml_material(path)
    assert captured==raw and not material.obligations
    aliases=[ref for ref in material.references if ref.alias]
    assert len(aliases)==2 and aliases[0].target==aliases[1].target
    assert all(raw[ref.span.byte_start:ref.span.byte_end]==b'*r' for ref in aliases)
    shared=material.nodes[aliases[0].target]
    assert shared.kind is DataNodeKind.MAPPING and shared.anchor=='r'
    assert any(material.references[entry.value].target==shared.ordinal for entry in shared.entries)
    assert [n.representation_literal.to_python() for n in material.nodes
        if n.scalar_text in ('???','${root.标记}')]==['???','${root.标记}']
    output=tmp_path/'material'
    manifest=write_data_material(material,raw,output)
    store=DataMaterialStore(output)
    assert store.read()==material and store.raw()==raw
    assert manifest['configuration_composed'] is False and manifest['target_executed'] is False
    assert len(material.references)>len(material.nodes)
