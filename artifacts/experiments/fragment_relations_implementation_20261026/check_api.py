"""Necessary type/codec/API checks only; no graph, producer, target or index."""
from pathlib import Path
import ast
from dataclasses import replace
import hashlib
import json
from scar.ir.execution.fragment_relations import *
from scar.ir.execution.fragment_relations_codec import to_dict, from_dict, loads
from scar.analysis.fragment_relations import _static_locator
from scar.analysis.source_native_composition import QualifiedOccurrenceRef as Reexport
from scar.ir.record_codec import decode

ROOT=Path(__file__).resolve().parents[3]
BASE=Path(__file__).resolve().parent
checks=[]
def ok(name,value):
    assert value,name
    checks.append(name)
def reject(name,action):
    try:action()
    except (ValueError,TypeError):checks.append(name)
    else:raise AssertionError(name)
paths=['scar/ir/execution/fragment_relations.py','scar/ir/execution/fragment_relations_codec.py',
       'scar/store/fragment_relations.py','scar/analysis/fragment_relations.py','scar/analysis/source_native_composition.py']
for path in paths:ast.parse((ROOT/path).read_text(),filename=path)
ok('five_file_syntax',True)
ok('same_class_reexport',Reexport is QualifiedOccurrenceRef)
meta=json.loads((ROOT/'artifacts/analysis/execution_snapshot_composition_connection_20261026/GPU_METADATA_RECEIPT.json').read_bytes())
first=meta['first_shard'];receipt=meta['first_source_receipt']
rootrow=meta['roots'][1]
manifest=ProviderArtifact(rootrow['path'],rootrow['sha256'],rootrow['bytes'],'scar.native-activity-work-report')
a=first['work_records'];artifact=ProviderArtifact(a['uri'],a['stored_sha256'],a['stored_bytes'],'scar.native-activity-work.rows')
loc=FragmentLocator(artifact,a['decoded_sha256'],a['decoded_bytes'],Encoding.GZIP_JSONL,1,'#/submission',ProviderFactReference(manifest,'#/shards/0/work_records'))
work=WorkTicketRef(loc,decode(WorkTicketID,receipt['ticket']))
ok('real_metadata_reference_roundtrip',from_dict(to_dict(work))==work)
coords=replace(decode(ProviderArtifact,meta['coordinates']),uri='/home/zyf/AAA/scar-worktrees/structured-program-model/artifacts/experiments/first_stage_current_source_gate_20261023/result/capture-coordinates.json')
scope=RuntimeScope(decode(RunID,meta['run']),decode(ProcessInstanceID,meta['process']),coords)
raworiginal=receipt['original_locator'];desc=raworiginal['artifact'];bundle=meta['original_eeg_manifest']
bundleartifact=ProviderArtifact(bundle['path'],bundle['sha256'],bundle['bytes'],'scar.partitioned-ir-bundle')
original=FragmentLocator(ProviderArtifact(str(Path(bundle['path']).parent/desc['uri']),desc['physical_sha256'],desc['physical_bytes'],'scar.original-eeg-instances.jsonl'),desc['decoded_sha256'],desc['decoded_bytes'],Encoding.GZIP_JSONL,raworiginal['line'],'#/record',ProviderFactReference(bundleartifact,'#/graphs/evidence/tables/instances/chunks/63'))
instance=OperationInstanceID('native:2a622492625eb1b2a7a105036e0ac792b5a6249fc60cf111443bf7fe53140d88:kineto:'+str(receipt['raw_ordinal']))
e=first['evidence'];projection=ProviderArtifact(e['uri'],e['stored_sha256'],e['stored_bytes'],'scar.ir.v2.evidence')
r=first['source_receipts'];receiptloc=FragmentLocator(ProviderArtifact(r['uri'],r['stored_sha256'],r['stored_bytes'],'scar.native-activity-work.receipts'),r['decoded_sha256'],r['decoded_bytes'],Encoding.GZIP_JSONL,1,'#',ProviderFactReference(manifest,'#/shards/0/source_receipts'))
link=WorkActivityProjectionLink(scope,work,replace(loc,pointer='#/binding'),LegacyOperationRef(projection,instance),EvidenceInstanceRef(original,instance),receiptloc)
gap=RelationGap('HOST_RELATION_UNRESOLVED',ProviderFactReference(artifact,'#/lines/1/submission'),'TYPE CHECK ONLY; original work row is not opened',0)
row=WorkRelations(link,(),(),(),(gap,))
ok('record_roundtrip',from_dict(to_dict(row))==row)
ok('assessment_does_not_change_member_id',replace(row,gaps=(replace(gap,detail='different assessment',candidates=None),)).id==row.id)
ok('distinct_logical_namespace_not_sha_merge',replace(work,locator=replace(loc,artifact=replace(artifact,uri=artifact.uri+'.distinct')))!=work)
reject('missing_host_requires_debt',lambda:replace(row,gaps=()))
wire=to_dict(row)
reject('unknown_field',lambda:from_dict({**wire,'trusted':True}))
reject('boolean_version',lambda:from_dict({**wire,'schema_version':True}))
reject('forged_relation_id',lambda:from_dict({**wire,'relation_id':'work_relation:'+'0'*64}))
reject('duplicate_json_key',lambda:loads('{"schema":1,"schema":2}'))
reject('line_encoding_mismatch',lambda:replace(loc,encoding=Encoding.GZIP_JSON))
# An actual current inventory witness descriptor, not a made-up enum/format.
raw=json.loads((BASE/'actual_inventory_locator.json').read_bytes())
converted=_static_locator(raw['locator'],decode(ProviderFactReference,raw['declaration']))
ok('actual_inventory_locator_contract',type(converted) is FragmentLocator and converted.artifact.sha256==raw['locator']['artifact']['physical_sha256'])
reject('inventory_descriptor_unknown_field',lambda:_static_locator({**raw['locator'],'verified':True},decode(ProviderFactReference,raw['declaration'])))
result={'status':'PASSED','qualification':'TYPE_CODEC_API_ONLY_NOT_GRAPH_SOURCE_OR_RUNTIME_PROOF','assertions':checks,
        'assertion_count':len(checks),'real_work_bodies_read':0,'real_eeg_chunks_read':0,'producer_index_runs':0,'target_executions':0,
        'sources':[{'path':p,'bytes':len(data),'sha256':hashlib.sha256(data).hexdigest()} for p in paths for data in [(ROOT/p).read_bytes()]]}
(BASE/'API_CHECK.json').write_text(json.dumps(result,indent=2)+'\n')
print(json.dumps({'status':result['status'],'assertions':len(checks),'qualification':result['qualification']}))
