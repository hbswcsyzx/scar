import hashlib,json,pathlib,stat
OUT=pathlib.Path(__file__).resolve().parent
MAIN=pathlib.Path('/home/zyf/AAA/scar-worktrees/structured-program-model')
CAP=MAIN/'artifacts/experiments/lewm_joint_capture_20261026/capture'
BUNDLE=MAIN/'artifacts/experiments/native_inputs_full_20261026/native-import/native/bundle-partitions/manifest.json'
COORD=MAIN/'artifacts/experiments/native_inputs_full_20261026/native-import/capture-coordinates.json'
def read(p):
 b=p.read_bytes();return json.loads(b),{'path':str(p),'bytes':len(b),'sha256':hashlib.sha256(b).hexdigest()}
a,ar=read(CAP/'archive-index.json');c,cr=read(COORD);b,br=read(BUNDLE)
bylocal={f['actual_path']:f for f in a['files']};errors=[]
for row in c['membership']:
 p=pathlib.Path(row['local_path']);s=p.lstat() if p.exists() else None
 expected=bylocal[str(p)]['compressed_bytes'] if str(p)in bylocal else row['artifact']['size_bytes']
 if s is None or not stat.S_ISREG(s.st_mode) or p.is_symlink() or s.st_size!=expected or not p.is_relative_to(CAP):
  errors.append({'path':str(p),'expected':expected,'actual':None if s is None else s.st_size})
chunks=b['graphs']['evidence']['tables']['instances']['chunks']
for d in chunks:
 p=BUNDLE.parent/d['uri'];s=p.lstat() if p.exists() else None
 if s is None or not stat.S_ISREG(s.st_mode) or p.is_symlink() or s.st_size!=d['physical_bytes']:errors.append({'path':str(p),'descriptor':d})
kineto=next(x for x in c['membership'] if x['artifact']['schema']=='pytorch.kineto.chrome-trace.v1')
report={'status':'METADATA_STAT_READY' if not errors else 'MISSING_OR_DIFFERENT','run':c['run']['id'] if 'id'in c['run'] else c['run'],'input_roots':[ar,cr,br],
'membership_stat_count':len(c['membership']),'bundle_instance_chunks_stat_count':len(chunks),'errors':errors,
'declared_bytes':{'binder_verified_raw':c['counts']['verified_raw_bytes'],'archive_all_compressed':sum(x['compressed_bytes']for x in a['files']),
'archive_all_decoded':sum(x['raw_bytes']for x in a['files']),'kineto_repeat_decoded':kineto['artifact']['size_bytes'],
'kineto_repeat_stored':bylocal[kineto['local_path']]['compressed_bytes'],'eeg_instances_stored':sum(x['physical_bytes']for x in chunks),
'eeg_instances_decoded':sum(x['decoded_bytes']for x in chunks)},
'limits':{'max_input_bytes':4000000000,'max_output_io_bytes':512000000,'max_wall_seconds':600,'max_rss_kib':2097152},
'qualification':'metadata and physical stat only; no raw payload read or new owner; ordinary binder and complete Kineto/EEG verification run during acquisition'}
(OUT/'PREFLIGHT.json').write_text(json.dumps(report,indent=2)+'\n');print(json.dumps(report,indent=2));assert not errors
