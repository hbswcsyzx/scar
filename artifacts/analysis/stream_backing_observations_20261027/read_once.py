"""Read the single shared CPU file+pipe capture through ordinary readers."""
from pathlib import Path
from hashlib import sha256
import json,time,stat,resource
from scar.trace.stream_interfaces import read_stream_interfaces
from scar.analysis.source_stream_interfaces import stream_resource_interface
from scar.ir.record_codec import encode

HERE=Path(__file__).resolve().parent;ROOT=HERE.parents[2]
metadata=Path('/home/zyf/AAA/scar-worktrees/program-ports-capture/artifacts/experiments/program_ports_cpu_20261027/capture/trace/stream-interface-meta.2026697.json')
started=time.monotonic();meta=metadata.read_bytes();digest=sha256(meta).hexdigest();closed=json.loads(meta)
preparation=json.loads((HERE/'PREPARATION.json').read_bytes())
assert all(sha256((ROOT/r['path']).read_bytes()).hexdigest()==r['sha256']for r in preparation['source_files'])
observed=read_stream_interfaces(metadata,expected_sha256=digest,max_bytes=1_000_000)
interfaces=tuple(stream_resource_interface(row)for row in observed['calls'])
assert not observed['stopped'] and not observed['errors']
assert len(interfaces)==observed['counts']['BEGIN']==7
regular=[i for i in interfaces if i.backing.stat is not None and stat.S_ISREG(i.backing.stat.mode)]
pipes=[i for i in interfaces if i.backing.stat is not None and stat.S_ISFIFO(i.backing.stat.mode)]
failed=[i for i in interfaces if i.backing.status.value=='FILENO_FAILED']
assert regular and pipes and len(failed)==1
assert failed[0].backing.failure.stage=='FILENO' and failed[0].backing.failure.exception_type=='ValueError'
assert all(i.backing_source.artifact.sha256==closed['file']['sha256']for i in interfaces)
# Original BEGIN/CALL coordinates and completion are independently verified by
# read_stream_interfaces. Preserve those exact anchors in the query receipt.
rows=[]
for original,interface in zip(observed['calls'],interfaces):
 rows.append({'attempt_index':original['attempt_index'],'invocation':original['invocation'],
              'site':original['site'],'attempt_source':original['attempt_source'],
              'completion':original['completion'],'resource':encode(interface)})
actual_input_refs=[closed['file'],next(r for r in closed['legacy_inputs']if r['family']=='operands')]
inputs=[]
for ref in actual_input_refs:
 logical=Path(ref.get('uri',ref.get('path')));physical=logical if logical.is_file()else Path(str(logical)+'.gz')
 inputs.append({'logical_uri':str(logical),'physical_uri':str(physical),'stored_bytes':physical.stat().st_size,
     'decoded_bytes':ref.get('size_bytes',ref.get('raw_bytes')),'decoded_sha256':ref.get('sha256',ref.get('raw_sha256'))})
result={'schema':'scar.stream-backing-readback-receipt','schema_version':1,
    'actual_exit_code':0,'capture_session':9810,'capture_actual_exit_code':0,'capture_seconds_reported_by_owner':33.73,
    'normal_read_seconds':time.monotonic()-started,'max_rss_kib':resource.getrusage(resource.RUSAGE_SELF).ru_maxrss,
    'metadata':{'uri':str(metadata),'bytes':len(meta),'sha256':digest},'counts':observed['counts'],
    'backing_counts':observed['backing_counts'],'regular_file_observations':len(regular),'fifo_observations':len(pipes),
    'fileno_failures':len(failed),'reader_inputs':inputs,
    'normal_reader_decoded_input_bytes':len(meta)+sum(r['decoded_bytes']for r in inputs),
    'normal_reader_stored_input_bytes':len(meta)+sum(r['stored_bytes']for r in inputs),
    'calls':rows,'producer_source_files':preparation['source_files'],
    'logical_identity_or_contents_or_lifetime_established':False,'whole_model_established':False}
assert all(sha256((ROOT/r['path']).read_bytes()).hexdigest()==r['sha256']for r in preparation['source_files'])
(HERE/'READBACK.json').write_text(json.dumps(result,sort_keys=True,indent=2)+'\n')
print(json.dumps({k:v for k,v in result.items()if k not in ('calls','producer_source_files','reader_inputs')},indent=2))
