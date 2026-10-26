"""Small retained metadata/sample audit, not another capture or graph import."""
from pathlib import Path
import gzip,hashlib,json,shutil,stat
from scar.trace.collector_execution_witness import read_collector_execution_witness

CONTROL=Path(__file__).resolve().parent
command=json.loads((CONTROL/'COMMAND.json').read_text())
root=Path(command['capture_root']);trace=root/'trace'
archive=json.loads((root/'archive-index.json').read_text())
coordinates=json.loads((root/'capture-coordinates.json').read_text())
small=CONTROL/'small-inputs';small.mkdir()
receipts=[]
def save(logical,raw,physical=None):
    destination=small/Path(logical).name
    destination.write_bytes(raw)
    receipts.append({'original_uri':str(logical),'retained_physical_uri':str(physical or logical),
        'copy':str(destination),'bytes':len(raw),'sha256':hashlib.sha256(raw).hexdigest()})
for pattern in ('call-meta.*.json','call-operand-meta.*.json','python-call-target-meta.*.json',
                'function-environment-meta.*.json','execution-evidence.*.json','dispatch-meta.*.json','tensor-physical-meta.*.json'):
    for path in trace.glob(pattern):
        assert path.stat().st_size<2_000_000
        save(path,path.read_bytes())
events=None
for row in archive['files']:
    if Path(row['logical_path']).name.startswith(('call-operands.','python-call-targets.')):
        assert row['raw_bytes']<2_000_000
        raw=gzip.decompress(Path(row['actual_path']).read_bytes())
        assert (len(raw),hashlib.sha256(raw).hexdigest())==(row['raw_bytes'],row['raw_sha256'])
        save(row['logical_path'],raw,row['actual_path'])
        if Path(row['logical_path']).name.startswith('call-operands.'):
            events=[json.loads(line) for line in raw.splitlines()]
gap=events[-1]
assert gap['index']==104 and gap['reason']=='INSTRUCTION_FRAME_UNAVAILABLE'
witness_ref=coordinates['collector_execution_membership']['manifest']
witness=read_collector_execution_witness(witness_ref['uri'],expected_sha256=witness_ref['sha256'])
save(witness_ref['uri'],Path(witness_ref['uri']).read_bytes())
images=json.loads(Path(witness['process_image_receipts']['uri']).read_text())
topology=json.loads(Path(witness['resource_topology']['uri']).read_text())
pid=coordinates['target_process']['pid']
target_os=next(row for row in archive['files'] if Path(row['logical_path']).name=='syscalls.'+str(pid))
sample=None;read_bytes=0
with gzip.open(target_os['actual_path'],'rb') as stream:
    for number,line in enumerate(stream,1):
        read_bytes+=len(line)
        if read_bytes>1_000_000:break
        if any(call in line for call in (b'newfstatat(',b'fstat(',b'statx(',b'stat(')) and b'st_ino=' in line and b'st_dev=' in line:
            sample={'logical_uri':target_os['logical_path'],'line_number':number,
                'line_sha256':hashlib.sha256(line).hexdigest(),'line':line.decode('utf-8','replace'),
                'prefix_bytes_read':read_bytes,'archive_declaration':target_os,
                'qualification':'bounded real sample from ordinary CLI roundtrip-verified archive; full OS stream not rescanned'}
            break
assert sample is not None,'no full stat record in the bounded original prefix'
(CONTROL/'STAT_SAMPLE.json').write_text(json.dumps(sample,indent=2)+'\n')
calls=json.loads(next(trace.glob('call-meta.*.json')).read_text())
operands=json.loads(next(trace.glob('call-operand-meta.*.json')).read_text())
targets=json.loads(next(trace.glob('python-call-target-meta.*.json')).read_text())
physical_files=[p for p in Path(command['payload_directory']).rglob('*') if p.is_file() and not p.is_symlink()]
summary={'status':'ACTUAL_CAPTURE_TRANSPORT_PASSED_OPERAND_COVERAGE_OPEN',
    'run':coordinates['run'],'cli_terminal':json.loads((CONTROL/'ACTUAL_TERMINAL.json').read_text()),
    'normal_archive_and_coordinate_reader':'ordinary main CLI returned 0 after both publishers/readers',
    'coordinate_counts':coordinates['counts'],'archive_io':archive['io_accounting'],
    'archive_members':len(archive['files']),'physical_file_bytes':sum(p.stat().st_size for p in physical_files),
    'physical_allocated_bytes':sum(p.stat().st_blocks*512 for p in physical_files),'disk_free_bytes':shutil.disk_usage(root).free,
    'calls':{k:calls[k] for k in ('events','invocations','codes','dropped_events','dropped_codes','errors','io_failed','open_invocations')},
    'operands':{k:operands[k] for k in ('events','call_attempts','handshakes','gaps','dropped_events','errors','io_failed')},
    'operand_last_gap':gap,'operand_stopped_field_present':'stopped' in operands,
    'python_targets':{'counts':targets['counts'],'own_stopped':targets['stopped'],
        'coordinate_membership':coordinates['python_call_target_membership'],'parent_operand_complete':False},
    'collector_witness':{'normal_reader':'PASS','manifest':witness_ref,'status':witness['status'],'errors':witness['errors'],
        'process_image_profile':images['profile'],'process_image_phases':[s['phase'] for s in images['snapshots']],
        'resource_topology':witness['resource_topology'],'resource_topology_status':topology['status']},
    'resource_utilization_sampler_enabled':False,'resource_sampler_files':[str(p) for p in trace.glob('resources*')],
    'native_tensor_input_chunks':len(coordinates['native_tensor_input_membership']['chunks']),
    'stat_sample_found':True,'whole_model_complete':False,'source_lowering_or_native_full_import_run':False}
(CONTROL/'POSTFLIGHT.json').write_text(json.dumps(summary,indent=2)+'\n')
(CONTROL/'SMALL_INPUT_RECEIPTS.json').write_text(json.dumps(receipts,indent=2)+'\n')
(CONTROL/'SOURCE_RECEIPTS.json').write_text(json.dumps(command['source_receipts'],indent=2)+'\n')
print(json.dumps({'status':summary['status'],'physical_file_bytes':summary['physical_file_bytes'],
    'allocated_bytes':summary['physical_allocated_bytes'],'disk_free_bytes':summary['disk_free_bytes'],
    'stat_line':sample['line_number'],'witness_reader':'PASS','native_input_chunks':summary['native_tensor_input_chunks']},indent=2))
