"""Bounded actual geometry replay; no allocation/content/ready construction."""
from __future__ import annotations

from dataclasses import replace
from hashlib import sha256
import gzip
import json
from pathlib import Path
import re
import sys
import time

HERE = Path(__file__).resolve().parent
ROOT = HERE.parents[2]
NATIVE = ROOT / 'artifacts/experiments/first_stage_joined_physical_20261023/result/native'
TRACE = ROOT / 'artifacts/experiments/first_stage_lewm_physical_20261023/trace'
START = time.monotonic()
inputs = []


def exact(path, limit):
    raw = path.read_bytes()
    assert len(raw) <= limit
    inputs.append({'path': str(path), 'sha256': sha256(raw).hexdigest(), 'bytes': len(raw)})
    return json.loads(raw)


from scar.ir.provenance import _byte_bounds, Overlap, region_overlap
from scar.ir.record_codec import decode, encode
from scar.ir.v2._validation import record_errors
from scar.ir.v2.values import StorageRegion
from scar.trace.tensor_physical import PROFILE, PROVIDER_REVISION
from scar.trace.tensor_physical_import import canonical_tensor_layout

assert 'torch' not in sys.modules
freeze = exact(HERE / 'producer.json', 1000000)
for row in freeze['modules']:
    raw = Path(row['path']).read_bytes()
    assert (sha256(raw).hexdigest(), len(raw)) == (row['sha256'], row['bytes'])
manifest = exact(NATIVE / 'bundle-partitions/manifest.json', 1000000)
meta = exact(TRACE / 'tensor-physical-meta.369749.72816598bfa183a810428fe30a7873ff.json', 2000000)
assert meta['profile'] == PROFILE and meta['provider_revision'] == PROVIDER_REVISION
physical = TRACE / 'tensor-physical.369749.72816598bfa183a810428fe30a7873ff.jsonl.gz'
rows, physical_prefix = {}, bytearray()
with gzip.open(physical, 'rb') as stream:
    for line in range(1, 29):
        raw = stream.readline(500001)
        physical_prefix.extend(raw)
        assert len(raw) <= 500000 and len(physical_prefix) <= 1000000
        row = json.loads(raw); assert row['index'] == line
        rows[line] = row
eto = TRACE / 'execution-trace.369749.72816598bfa183a810428fe30a7873ff.json.gz'
with gzip.open(eto, 'rb') as stream:
    prefix = stream.read(196608)
text = prefix.decode(); decoder = json.JSONDecoder()
position = re.search(r'"nodes"\s*:\s*\[', text).end(); nodes = []
for _ in range(70):
    while text[position] in ' \r\n\t,': position += 1
    node, position = decoder.raw_decode(text, position); nodes.append(node)
ref = manifest['graphs']['values']['tables']['regions']['chunks'][0]
region_path = NATIVE / 'bundle-partitions' / ref['uri']
region_lines, region_prefix = [], bytearray()
with gzip.open(region_path, 'rb') as stream:
    for line in range(1, 17):
        raw = stream.readline(500001); region_prefix.extend(raw)
        assert len(raw) <= 500000 and len(region_prefix) <= 1000000
        region_lines.append(json.loads(raw)['record'])
selected, new_records = {}, []
for name, old_index in (('full', 2), ('first_row', 6), ('scalar', 8), ('second_row', 15)):
    old = decode(StorageRegion, region_lines[old_index])
    witness = old.metadata['physical_observation']
    match = re.fullmatch(r'sha256:([0-9a-f]{64})#line/([0-9]+)/arguments/([0-9]+)', witness)
    assert match and match[1] == meta['file']['raw_sha256']
    row, ordinal = rows[int(match[2])], int(match[3])
    tensor = row['arguments'][ordinal]['metadata']
    assert row['kind'] == 'MARKER' and tensor['status'] == 'OBSERVED' and not tensor['gaps']
    pointer = re.fullmatch(r'sha256:([0-9a-f]{64})#/nodes/([0-9]+)/inputs/values/([0-9]+)', old.metadata['eto_reference'])
    assert pointer
    node, offset_index = nodes[int(pointer[2])], int(pointer[3])
    value = node['inputs']['values'][offset_index]
    shape, strides = tensor['sizes'], tensor['strides']
    assert shape == node['inputs']['shapes'][offset_index] == list(old.shape)
    assert strides == node['inputs']['strides'][offset_index] == list(old.strides)
    assert value[2] == old.offset and value[5] == old.device == tensor['device']['text']
    assert tensor['dtype'] == old.dtype and tensor['layout'] == old.layout == 'torch.strided'
    assert tensor['provider_allocation_id'] == 2
    birth = rows[11]
    assert birth['kind'] == 'ALLOCATION' and birth['provider_allocation_id'] == 2 and birth['alloc_size'] == 640
    assert birth['ptr'] == tensor['storage_data_ptr'] and birth['device'] == tensor['device']
    epoch_hash = sha256(json.dumps(('cpu', 2),sort_keys=True,separators=(',',':')).encode()).hexdigest()
    assert old.allocation.value.endswith(':epoch:' + epoch_hash)
    new = StorageRegion(old.id, old.allocation, value[2], tuple(shape), tuple(strides), tensor['dtype'],
        tensor['device']['text'], canonical_tensor_layout(tensor['layout'], profile=meta['profile'],
                                                        provider_revision=meta['provider_revision']),
        {**old.metadata, 'provider_layout': tensor['layout'], 'layout_normalization_rule': 'PINNED_TORCH_LAYOUT_V1'})
    assert not record_errors(new, StorageRegion, name)
    assert _byte_bounds(old) is None
    assert _byte_bounds(new)[1] <= birth['alloc_size']
    assert new.id == old.id and new.allocation == old.allocation
    old_encoded, new_encoded = encode(old), encode(new)
    assert {k:v for k,v in old_encoded.items() if k not in ('layout','metadata')} == {
        k:v for k,v in new_encoded.items() if k not in ('layout','metadata')}
    assert new.metadata['logical_version'] is None and new.metadata['association_persistent'] is False
    selected[name] = new
    new_records.append({'name':name,'original_region_line':old_index+1,'old':old_encoded,'new':new_encoded,
        'byte_bounds':_byte_bounds(new),'allocation_extent_raw_source_line':11,
        'new_allocation_constructed':False})
expected = {'full':(0,640),'first_row':(0,40),'scalar':(0,4),'second_row':(40,80)}
assert {name:_byte_bounds(value)for name,value in selected.items()} == expected
assert region_overlap(selected['full'],selected['first_row']) is Overlap.OVERLAPS
assert region_overlap(selected['first_row'],selected['scalar']) is Overlap.OVERLAPS
assert region_overlap(selected['first_row'],selected['second_row']) is Overlap.DISJOINT
assert canonical_tensor_layout('torch.sparse_coo',profile=PROFILE,provider_revision=PROVIDER_REVISION)=='torch.sparse_coo'
opaque = replace(selected['full'],layout='torch.sparse_coo')
assert _byte_bounds(opaque) is None and region_overlap(opaque,selected['first_row']) is Overlap.POSSIBLE
negative=[]
for layout,profile,revision in [('torch.strided','wrong',PROVIDER_REVISION),('torch.strided',PROFILE,'0'*40),('strided',PROFILE,PROVIDER_REVISION)]:
    try:canonical_tensor_layout(layout,profile=profile,provider_revision=revision)
    except ValueError as error:negative.append({'layout':layout,'profile':profile,'revision':revision,'rejected':str(error)})
    else:raise AssertionError('unqualified source layout accepted')
scalar = nodes[1]
assert scalar['id']==6 and scalar['name']=='torchvision::_cuda_version' and scalar['outputs']['types']==['Int']
assert scalar['outputs']['values']==[13020]
report={'schema':'scar.tensor-layout-bounded-actual-gate','schema_version':1,'status':'PASS',
    'producer':freeze,'inputs':inputs,'records':new_records,'bounds':expected,'negative_profile_checks':negative,
    'overlap':{'full_first_row':'OVERLAPS','first_row_scalar':'OVERLAPS','first_second_rows':'DISJOINT',
               'unknown_layout':'POSSIBLE'},
    'bounded_prefixes':[{'path':str(p),'decoded_bytes':len(raw),'prefix_sha256':sha256(raw).hexdigest(),
                         'full_raw_or_shard_sha_revalidated':False}for p,raw in
                        [(physical,bytes(physical_prefix)),(eto,prefix),(region_path,bytes(region_prefix))]],
    'scalar_node_clarification':{'pointer':'#/nodes/1','id':scalar['id'],'name':scalar['name'],
        'types':scalar['outputs']['types'],'values':scalar['outputs']['values'],'is_process_root':False,
        'used_to_create_content':False,'next_bridge_priority':'actual ATen operation'},
    'elapsed_s':time.monotonic()-START,'new_regions':len(new_records),'new_allocations':0,'old_artifacts_modified':False,
    'new_logical_values':0,'new_versions':0,'new_provenance':0,'new_materializations':0,
    'content_or_readiness_qualification_changed':False,'full_bundle_validation_performed':False,
    'torch_imported':False,'target_executed':False,'transformation_authorized':False,'first_stage_complete':False}
(HERE/'report.json').write_text(json.dumps(report,sort_keys=True,indent=2)+'\n')
for row in freeze['modules']:
    assert sha256(Path(row['path']).read_bytes()).hexdigest()==row['sha256']
assert 'torch' not in sys.modules
print(json.dumps({k:report[k]for k in ('status','bounds','overlap','new_regions','new_allocations','elapsed_s')},sort_keys=True))
