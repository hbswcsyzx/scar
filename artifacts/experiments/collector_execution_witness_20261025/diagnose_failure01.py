"""Read only existing closed witness and CLI coordinate metadata; no recapture."""
from pathlib import Path
from hashlib import sha256
import json
O=Path(__file__).resolve().parent
paths=list((O/'capture/trace').glob('collector-witness.*/manifest.json'));assert len(paths)==1
W=paths[0];C=O/'capture/capture-coordinates.json'
w=json.loads(W.read_text());c=json.loads(C.read_text());launch=json.loads((O/'launch.json').read_text())
comparisons=[]
for a in w['closed_metadata']:
 candidates=[m for m in c['membership'] if m['artifact']['uri']==a['uri']]
 assert len(candidates)==1
 m=candidates[0];b=m['artifact']
 comparisons.append({'witness':a,'coordinate_artifact':b,'field_equal':{k:a[k]==b[k] for k in ['uri','size_bytes','sha256','schema']},
  'coordinate_member_process':m['process'],'target_process':c['target_process'],
  'same_target_process':m['process']==c['target_process']})
assert all(all(x['field_equal'][k] for k in ['uri','size_bytes','sha256']) and x['same_target_process'] for x in comparisons)
differ=[x for x in comparisons if not x['field_equal']['schema']]
assert len(differ)==1 and differ[0]['witness']['schema']=='scar.call-edge-trace' and differ[0]['coordinate_artifact']['schema']=='scar.call-edge-meta.v1'
def r(p):
 raw=p.read_bytes();return {'path':str(p),'bytes':len(raw),'sha256':sha256(raw).hexdigest()}
d={'status':'ACTUAL_CPU_GATE_FAILED_BINDER_SCHEMA_LABEL_JOIN','root_session':19347,'gate_exit':1,'CLI_exit':launch['actual_exit'],'CLI_wall_seconds':launch['wall_seconds'],
 'witness_status':w['status'],'witness_errors':w['errors'],'witness_reader':'root gate passed before binder','registered_roles':[x['role'] for x in w['records'] if x['event']=='REGISTERED'],
 'comparisons':comparisons,'witness':r(W),'saved_CLI_coordinates':r(C),'launch':r(O/'launch.json'),
 'failure':'ValueError: witness closed metadata has no exact target-process coordinate membership',
 'root_cause':'JSON document schema scar.call-edge-trace differs from the existing coordinate protocol family label scar.call-edge-meta.v1 for exactly the same call-meta bytes/URI/process',
 'minimal_proposed_fix':'Explicit new-binder-only schema1 call-meta -> coordinate family-meta.v1 compatibility rule; retain URI/SHA/bytes/source schema checks and process_for using actual coordinate artifact. No generic schema bypass.',
 'negative_executed':False,'postcapture_bind_passed':False,'source_or_capture_changed':False,'second_CPU_capture':False,'raw_or_DB_reads':0}
with (O/'failure-diagnosis.json').open('x') as f:json.dump(d,f,indent=2,sort_keys=True);f.write('\n')
(O/'FAILURE.md').write_text('''实际唯一CPU门19347 exit1；内部CPU CLI exit0，wall26.105368s。实际hook/CPU记录/五role关闭及witness reader已通过，postcapture binder未通过，resealed-generation negative尚未执行。不能称全部链路PASS。

唯一差异是call-meta.1334231.json的schema标签：witness保JSON文档schema scar.call-edge-trace；普通coordinate membership按operand base_manifest的family=meta保scar.call-edge-meta.v1。URI、1025bytes、SHA97a5488c7c5ea26544b1294c4fb09eec49663ac3b945e97e3afe38efbb6496b2及target process全部相同。其余四个closed metadata全部四字段和target process相同。原capture_coordinates先document读call-meta，再按base_manifest覆盖其family标签，是现有协议行为，不是身份/bytes矛盾。

最小修复仅在新增binder声明版本限定的call-meta schema1→coordinate family-meta.v1映射，然后仍用准确coordinate artifact作process_for验证；不修改旧witness/coordinates，不广泛忽略schema。修复须root批准，可只读复用此次完整关闭数据验证，不能自动采第二CPU。原6source/freeze/采集/坐标均未改。PID birth join、连续篡改排除、内容/ready等仍OPEN。
''')
print(json.dumps({'status':d['status'],'difference_count':1,'FAILURE':r(O/'FAILURE.md'),'diagnosis':r(O/'failure-diagnosis.json')},indent=2))
