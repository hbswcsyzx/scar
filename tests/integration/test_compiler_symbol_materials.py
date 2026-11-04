"""C3-S stores preserve eight original inputs and keep runtime layout unclaimed."""
from copy import deepcopy
from hashlib import sha256
from io import BytesIO
import json
import shutil
import tokenize

import pytest

from scar.analysis.source_materials import archive_model_source_bytes
from scar.analysis.source_lexing import model_source_tokens
from scar.analysis.source_parsing import model_source_syntax
from scar.analysis.source_role_materials import model_source_roles
from scar.analysis.source_context_materials import model_source_contexts
from scar.analysis.source_declaration_materials import model_source_declarations
from scar.analysis.source_symbol_materials import model_source_symbols
from scar.analysis.compiler_topology_materials import model_compiler_topology
from scar.analysis.static_program import _json, _write
from scar.analysis.static_query import _Fragments


def _snapshot(root):
    return {p.relative_to(root).as_posix(): p.read_bytes() for p in root.rglob('*') if p.is_file()}


def test_symbol_materials_preserve_eight_inputs_budgets_and_prior_endpoints(tmp_path, monkeypatch):
    from scar.analysis.compiler_symbol_materials import main, model_compiler_symbols, _symbol_unit
    source, model = tmp_path/'source', tmp_path/'model'
    source.mkdir();model.mkdir();units=[]
    for number,raw in enumerate((
        b'def solve(values):\n    local = 3\n    def nested(item): return local + item\n'
        b'    return [nested(x) for x in values]\n'
        b'class Owner:\n    left: int\n    def call(self, value): return value\n'
        b'raise RuntimeError("never execute")\n',
        b'from __future__ import annotations\ndef future(value: Annot) -> Other:\n    local: Local\n    return value\n',
        b'pass\n')):
        path,key=source/f'{number}.py',str(number);path.write_bytes(raw)
        encoding,_=tokenize.detect_encoding(BytesIO(raw).readline);text=raw.decode(encoding)
        envelope=dict(schema='scar.static-source-text',schema_version=1,path=str(path),namespace_root=str(source),
            raw_sha256=sha256(raw).hexdigest(),decoded_sha256=sha256(text.encode()).hexdigest(),encoding=encoding,text=text)
        old=_write(model,'units/'+key+'/old_core.json.gz',{'opaque_prior_endpoint':key})
        units.append({k:v for k,v in envelope.items() if k not in ('schema','schema_version','text')}
            |dict(key=key,source_bytes=len(raw),bodies=[dict(entry_key='old:'+key,artifact=old)],
                artifacts={'source':_write(model,'units/'+key+'/source.json.gz',envelope)}))
    (model/'manifest.json').write_bytes(_json(dict(schema='scar.static-program',schema_version=1,units=units,remaining=[],source_issues=[])))
    archive_model_source_bytes(model,tmp_path/'f0',jobs=1);model_source_tokens(model,tmp_path/'f1',jobs=1)
    model_source_syntax(model,tmp_path/'f2',jobs=1)
    b,c,d,a,t=[tmp_path/name for name in ('roles','contexts','declarations','symbols','topology')]
    br=model_source_roles(model,b,jobs=1,collect_only=True)
    cr=model_source_contexts(model,c,roles_materials=b,jobs=1,collect_only=True)
    dr=model_source_declarations(model,d,roles_materials=b,contexts_materials=c,jobs=1,collect_only=True)
    ar=model_source_symbols(model,a,jobs=1,collect_only=True)
    tr=model_compiler_topology(model,t,roles_materials=b,contexts_materials=c,symbols_materials=a,jobs=1,collect_only=True)
    before=_snapshot(model);inputs=[(b,br,'ports'),(c,cr,'scopes'),(d,dr,'contributions'),(a,ar,'symbols'),(t,tr,'blocks')]
    snapshots=[_snapshot(root) for root,_,_ in inputs]
    external=dict(roles_materials=b,contexts_materials=c,declarations_materials=d,symbols_materials=a,topology_materials=t,jobs=1)
    with pytest.raises(ValueError,match='worker hash context'):_symbol_unit((None,)*9+('0'*64,))
    with pytest.raises(ValueError,match='external.*collect-only'):
        model_compiler_symbols(model,tmp_path/'bad-canonical',**external)
    with pytest.raises(ValueError,match='canonical'):
        model_compiler_symbols(model,tmp_path/'missing-inputs',jobs=1,collect_only=True)
    for key in ('max_symbol_slots','max_symbol_steps'):
        report=model_compiler_symbols(model,tmp_path/('budget-'+key),collect_only=True,**external,**{key:0})
        assert not report['complete_for_declared_units'] and not report['canonical_model_published']
        assert _snapshot(model)==before
    store=tmp_path/'provenance'
    def no_clone(*args,**kwargs):raise AssertionError('C3-S collect-only must not clone a read-only model')
    model.chmod(0o555)
    try:
        with monkeypatch.context() as patch:
            patch.setattr(shutil,'copytree',no_clone)
            captured=model_compiler_symbols(model,store,collect_only=True,**external)
    finally:model.chmod(0o755)
    assert captured['status_counts']=={'PROJECTED':3} and captured['complete_for_declared_units']
    assert captured['symbols']==ar['symbols'] and captured['parameters']>0
    assert captured['sources']==dr['contributions'] and captured['blocks']==tr['blocks']
    assert captured['authority']=='SOURCE_COMPILER_SYMBOL_PROVENANCE'
    assert captured['runtime_binding']=='NOT_OBSERVED' and captured['runtime_local_layout']=='NOT_CLAIMED'
    assert captured['symtable_executed'] and not captured['target_executed']
    assert not captured['whole_program_complete'] and not captured['canonical_model_published'] and captured['manifest_unchanged']
    assert len(list(store.rglob('catalog.json.gz')))==1 and _snapshot(model)==before
    assert all(_snapshot(root)==saved for (root,_,_),saved in zip(inputs,snapshots))
    for i,row in enumerate(captured['results']):
        for key,report in (('source_roles',br),('source_contexts',cr),('source_declarations',dr),('source_symbols',ar),('compiler_topology',tr)):
            assert captured['basis'][i]['artifacts'][key]==report['results'][i]['artifact']
        doc=_Fragments(store).read(row['artifact'])
        assert 'nodes' not in doc and 'catalog' not in doc
        assert doc['profile']['symbol_catalog_sha256']==captured['catalog_sha256']
        assert len(doc['sources'])==doc['input']['source_count']==dr['results'][i]['contributions']
        assert len(doc['blocks'])==doc['input']['block_count']==tr['results'][i]['blocks']
        assert len(doc['symbols'])==doc['input']['native_symbol_count']==ar['results'][i]['symbols']
    fresh=model_compiler_symbols(model,tmp_path/'fresh',verify=True,materials=store,**external)
    assert fresh['complete_for_declared_units'] and fresh['material_source_basis_unchanged'] and _snapshot(model)==before
    for key in ('max_compiler_contributions','max_contributions','max_nodes','max_symbols','max_visit_steps'):
        with pytest.raises(ValueError,match='budget'):
            model_compiler_symbols(model,tmp_path/('limit-'+key),verify=True,materials=store,**external,**{key:0})
    for owner,counter in [(store,'symbols'),*((root,counter) for root,_,counter in inputs)]:
        result=owner/'result.json';original=result.read_bytes();changed=deepcopy(json.loads(original));changed[counter]+=1
        result.write_bytes(_json(changed))
        try:
            with pytest.raises(ValueError):
                model_compiler_symbols(model,tmp_path/('summary-'+owner.name),verify=True,materials=store,**external)
        finally:result.write_bytes(original)
    for owner,report in [(store,captured),(b,br),(c,cr),(d,dr),(t,tr)]:
        catalog=owner/report['catalog']['path'];original=catalog.read_bytes();catalog.write_bytes(original+b'changed')
        try:
            with pytest.raises(ValueError,match='receipt'):
                model_compiler_symbols(model,tmp_path/('catalog-'+owner.name),verify=True,materials=store,**external)
        finally:catalog.write_bytes(original)
    # Re-sign D alone so receipt verification succeeds: its strict pure reader
    # must still reject a false producer profile. T does not consume D.
    result=d/'result.json';original_result=result.read_bytes();artifact=d/dr['results'][0]['artifact']['path']
    original_artifact=artifact.read_bytes();ddoc=_Fragments(d).read(dr['results'][0]['artifact'])
    ddoc['profile']['implementation_sha256']='0'*64
    changed=json.loads(original_result);changed['results'][0]['artifact']=_write(d,artifact.relative_to(d).as_posix(),ddoc)
    result.write_bytes(_json(changed))
    try:
        with pytest.raises(ValueError):model_compiler_symbols(model,tmp_path/'strict-declarations',collect_only=True,**external)
    finally:artifact.write_bytes(original_artifact);result.write_bytes(original_result)
    note=t/'unowned.txt';note.write_text('keep me')
    try:
        with pytest.raises(ValueError,match='unowned'):
            model_compiler_symbols(model,tmp_path/'unowned',verify=True,materials=store,**external)
        assert note.read_text()=='keep me'
    finally:note.unlink()
    model_source_roles(model,tmp_path/'b-publish',jobs=1);model_source_contexts(model,tmp_path/'c-publish',jobs=1)
    model_source_declarations(model,tmp_path/'d-publish',jobs=1);model_source_symbols(model,tmp_path/'a-publish',jobs=1)
    model_compiler_topology(model,tmp_path/'t-publish',jobs=1);prior_publish=_snapshot(model)
    published=model_compiler_symbols(model,tmp_path/'publish',jobs=2)
    assert published['canonical_model_published'] and published['complete_for_declared_units']
    assert all((model/key).read_bytes()==raw for key,raw in prior_publish.items() if key!='manifest.json')
    after=json.loads((model/'manifest.json').read_bytes());assert after['compiler_symbols']['artifacts']==[published['catalog']]
    for old,new in zip(json.loads(prior_publish['manifest.json'])['units'],after['units']):
        assert {**new,'artifacts':{key:value for key,value in new['artifacts'].items() if key!='compiler_symbols'}}==old
    checked=model_compiler_symbols(model,tmp_path/'canonical-check',jobs=2,verify=True)
    assert checked['complete_for_declared_units'] and checked['manifest_unchanged']
    assert main(['--model',str(model),'--out',str(tmp_path/'cli'),'--verify','--jobs','1'])==0
