"""Ordered payload versions share files across distinct package instances."""
from pathlib import Path
from types import SimpleNamespace

from scar.analysis.source_configuration_composition import _Builder,_package
from scar.ir.program.configuration_composition import ConfigurationStepKind


def test_nested_group_uses_group_base_not_choice_directory_and_shares_materials(tmp_path):
    root=tmp_path/'configs';root.mkdir()
    (root/'main.yaml').write_text('defaults:\n  - _self_\n  - engine: deep/base\n'
        '  - /group@_here_: item\n  - engine@copy: deep/base\nseed: 1\n')
    (root/'engine/deep').mkdir(parents=True)
    (root/'engine/deep/base.yaml').write_text('defaults:\n  - child: leaf\nvalue: 2\n')
    (root/'engine/child').mkdir()
    (root/'engine/child/leaf.yaml').write_text('leaf: true\n')
    (root/'group').mkdir()
    (root/'group/item.yaml').write_text('# @package _global_.stage\nvalue: 3\n')
    out=tmp_path/'graph';out.mkdir()
    candidate=SimpleNamespace(root=str(root),resource=str(root/'main.yaml'),conditions=('FILE_SELECTED',))
    request=SimpleNamespace(id='fixture',conditions=('CALL_SELECTED',))
    graph=_Builder(request,candidate,0,out,None,(),16).build()
    materials={m.id:m for m in graph.materials}
    merges=[s for s in graph.steps if s.kind is ConfigurationStepKind.MERGE_MATERIAL]
    assert [(Path(materials[s.material].source.uri).name,s.package) for s in merges]==[
        ('main.yaml',()),('leaf.yaml',('engine','child')),('base.yaml',('engine',)),
        ('item.yaml',()),('leaf.yaml',('copy','child')),('base.yaml',('copy',))]
    # Explicit @_here_ outranks the child's absolute package header.
    assert len(materials)==4 and merges[2].material==merges[5].material
    assert merges[1].material==merges[4].material
    assert all(s.previous==s.ordinal-1 for s in graph.steps[1:])
    assert len({s.instance for s in merges})==6
    assert all(s.exclude_root_keys==('defaults',) for s in merges)
    packages={s.instance:'.'.join(s.package) for s in merges}
    assert all(d.package==packages[d.child_instance] for d in graph.dependencies if d.child_instance is not None)
    assert _package('foo','bar','_group_',None,'foo/bar')=='foo.bar'
    assert {o.code for o in graph.obligations}=={
        'IMPLICIT_LIBRARY_ROOT_PROVIDER_PENDING','CLI_OVERRIDES_AND_LAZY_REFERENCES_PENDING',
        'APPLICATION_MATCHED_SCHEMA_LOOKUP_PENDING'}
