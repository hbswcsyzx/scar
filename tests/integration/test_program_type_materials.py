"""Shared structural grammar stores are exact, fresh and never execution proof."""
from copy import deepcopy
from hashlib import sha256
import json

import pytest

from scar.analysis.static_program import _json, _write
from scar.analysis.static_query import _Fragments


def _snapshot(root):
    return {path.relative_to(root).as_posix():path.read_bytes() for path in root.rglob('*') if path.is_file()}


def _digest(document):
    return sha256(json.dumps(document,sort_keys=True,separators=(',',':'),ensure_ascii=True,
        allow_nan=False).encode('ascii')).hexdigest()


def test_shared_type_materials_fresh_read_preserves_inputs_and_rejects_changes(tmp_path):
    from scar.analysis.program_type_materials import program_types
    store,fresh=tmp_path/'materials',tmp_path/'fresh'
    captured=program_types(store)
    assert captured['schema']=='scar.program-type-materials' and captured['stage']=='F4-A'
    assert captured['complete'] and captured['source_constructors']==113 and captured['source_slots']==484
    assert captured['target_counts']['records']>0 and captured['target_counts']['fields']>0
    assert not any(captured[key] for key in ('target_executed','canonical_model_published',
        'graph_realized','operation_semantics_closed','whole_program_complete'))
    assert set(captured['artifacts'])=={'source','target'}
    before=_snapshot(store)
    assert set(before)=={'result.json','source_types.json.gz','program_types.json.gz'}
    for key in ('source','target'):
        doc=_Fragments(store).read(captured['artifacts'][key])
        assert doc['content_sha256']==captured[key+'_catalog_sha256']
    verified=program_types(fresh,materials=store)
    assert verified['schema']=='scar.program-type-verification' and verified['complete']
    assert verified['input_unchanged'] is True and verified['input_materials']==str(store)
    assert verified['input_summary_sha256']==sha256(before['result.json']).hexdigest()
    assert verified['artifacts']==captured['artifacts'] and _snapshot(store)==before
    assert set(_snapshot(fresh))=={'result.json'}
    for out in (store,fresh):
        prior=_snapshot(out)
        with pytest.raises(FileExistsError):program_types(out,materials=None if out==store else store)
        assert _snapshot(out)==prior and _snapshot(store)==before
    summary_path=store/'result.json';original_summary=summary_path.read_bytes()
    # Identical duplicate values still violate the closed JSON record grammar.
    summary_path.write_bytes(b'{"schema_version":1,'+original_summary.lstrip()[1:])
    try:
        with pytest.raises(ValueError):program_types(tmp_path/'duplicate-header',materials=store)
    finally:summary_path.write_bytes(original_summary)
    assert _snapshot(store)==before
    # True must not be accepted as the integer schema_version=1. The other
    # mutations protect declared counts and non-execution authority flags.
    mutations=(
        lambda doc:doc.update(schema_version=True),
        lambda doc:doc.update(source_constructors=True),
        lambda doc:doc['target_counts'].update(records=True),
        lambda doc:doc.update(target_executed=True),
        lambda doc:doc.update(extra_header='unregistered'),
    )
    for index,mutation in enumerate(mutations):
        changed=deepcopy(json.loads(original_summary));mutation(changed);summary_path.write_bytes(_json(changed))
        try:
            with pytest.raises(ValueError):program_types(tmp_path/('bad-summary-'+str(index)),materials=store)
        finally:summary_path.write_bytes(original_summary)
        assert _snapshot(store)==before
    # Re-sign both the artifact receipt and content hash. Matching stored
    # hashes do not authorize new source/target declaration semantics.
    for key in ('source','target'):
        descriptor=captured['artifacts'][key];artifact=store/descriptor['path'];original_artifact=artifact.read_bytes()
        document=_Fragments(store).read(descriptor)
        if key=='source':document['execution_semantics']='CLOSED'
        else:document['claims']['operation_semantics_closed']=True
        document['content_sha256']=_digest({name:value for name,value in document.items() if name!='content_sha256'})
        changed=deepcopy(json.loads(original_summary))
        changed['artifacts'][key]=_write(store,descriptor['path'],document)
        changed[key+'_catalog_sha256']=document['content_sha256']
        summary_path.write_bytes(_json(changed))
        try:
            with pytest.raises(ValueError):program_types(tmp_path/('re-signed-'+key),materials=store)
        finally:artifact.write_bytes(original_artifact);summary_path.write_bytes(original_summary)
        assert _snapshot(store)==before
    unowned=store/'unowned.txt';unowned.write_text('retain this user file')
    try:
        with pytest.raises(ValueError,match='unowned'):program_types(tmp_path/'unowned-check',materials=store)
        assert unowned.read_text()=='retain this user file'
    finally:unowned.unlink()
    assert _snapshot(store)==before
