"""Import/signature and saved static-interface API preflight, no raw replay."""
from pathlib import Path
import ast,inspect,json,hashlib,difflib
from scar.trace.native_protocol import _build_program
from scar.ir.program.model import ProgramGraph
from scar.ir.program.codec import dumps as program_dumps,loads as program_loads
from scar.ir.program.validation import require_valid as require_program_valid
from scar.ir.execution.model import ExecutionModel
from scar.ir.execution.coordinates import ProgramSnapshot
from scar.ir.execution.codec import dumps as execution_dumps,loads as execution_loads
from scar.ir.execution.validation import validate,require_valid
from scar.ir.v2.values import ValueGraph,ObjectInstance
from scar.ir.v2.evidence import EvidenceGraph
from scar.ir.program.providers import ProviderArtifact
from scar.ir.record_codec import decode,encode
from scar.trace.capture_coordinates import CaptureCoordinates
from scar.store.bundle_partitions import BundlePartitions
from scar.ir.execution.native_port_protocol import canonical
BASE=Path(__file__).resolve().parents[3];OUT=Path(__file__).parent
old=BASE/'artifacts/experiments/first_stage_native_protocol_bridge_20261023'
plan=json.loads((old/'preflight.json').read_bytes())
# This creates static schema definitions only from the retained signatures.
# It does not restore past owned source/runtime evidence or create any calls.
interfaces=[{**i,'ports':{k:i['signature'][k] for k in ('inputs','outputs')}} for i in plan['interfaces']]
c=json.loads((old/'native-coordinates.json').read_bytes())
source={'native_scope':'api-preflight-only','artifacts':{'eto':next(m['artifact'] for m in c['membership'] if m['artifact']['schema']=='pytorch.execution-trace.v1')},'run':c['run']['id']['value'],'pid':next(m['pid'] for m in c['processes'] if m['id']==c['target_process']),'max_sequences':16}
payload=canonical({'interfaces':{i['signature_id']:i['signature'] for i in interfaces}})
a=ProviderArtifact('memory:static-api-preflight',hashlib.sha256(payload).hexdigest(),len(payload),'scar.pinned-aten-protocol-interface')
graph,layout=_build_program(interfaces,source,a)
require_program_valid(graph)
wire=program_dumps(graph);restored=program_loads(wire);assert program_dumps(restored)==wire
artifact=ProviderArtifact('memory:static-api-preflight-program',hashlib.sha256(wire.encode()).hexdigest(),len(wire.encode()),'scar.program-graph')
snapshot=ProgramSnapshot(artifact,json.loads(wire)['schema_version'])
empty=ExecutionModel(snapshot);assert execution_dumps(execution_loads(execution_dumps(empty)))==execution_dumps(empty)
classes=[ProgramGraph,ExecutionModel,ProgramSnapshot,CaptureCoordinates,ProviderArtifact,BundlePartitions]
functions=[program_dumps,program_loads,require_program_valid,execution_dumps,execution_loads,validate,require_valid,decode,encode]
report={'status':'API_PREFLIGHT_PASS','source_raw_replayed':False,'owned_evidence_created':False,'actual_invocations_created':0,
 'static_interface_count':len(layout),'static_program_codec_bytes':len(wire.encode()),'static_program_codec_roundtrip':True,
 'empty_execution_record_codec_roundtrip':True,'program_snapshot_signature':str(inspect.signature(ProgramSnapshot)),
 'signatures':{f.__module__+'.'+f.__qualname__:str(inspect.signature(f)) for f in [*classes,*functions]},
 'graph_family_methods':{c.__module__+'.'+c.__qualname__:{name:hasattr(c,name) for name in ('assert_valid','validate','to_dict','as_dict','from_dict')} for c in [ProgramGraph,ExecutionModel,ProgramSnapshot,ValueGraph,EvidenceGraph,ObjectInstance]},
 'compile_witness_calls':0,'prepare_calls':0,'target_executions':0}
(OUT/'api-audit.json').write_text(json.dumps(report,sort_keys=True,indent=2)+'\n');print(json.dumps({'status':report['status'],'interfaces':len(layout),'program_codec_bytes':len(wire.encode())}))
