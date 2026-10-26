"""Closed capture namespace and stored-byte checks only, before composition IO.

Uses the normal _Files resolver. No raw gzip stream is decompressed here; logical
raw identities are compared with the original archive declarations, not restored.
"""
from pathlib import Path, PurePosixPath
import hashlib,json,re
from config import HERE,CAPTURE,PROFILE
from report_archive import receipt
from scar.trace.capture_coordinates import _Files,_json


def check_capture():
    previous=json.loads((HERE.parent/'candidate02/inputs.json').read_bytes())
    expected={r['path']:r for r in previous['inputs']}
    pins={};measurements={};metadata={};relations=[];missing=[]
    root=CAPTURE.resolve(strict=True)
    def stored(path,row):
        path=Path(path)
        if str(path) in measurements:return
        pins[str(path)]=row
        if not path.is_file():missing.append(row);return
        if path.is_symlink() or path.resolve()!=path or not path.is_relative_to(root):
            raise ValueError('capture preflight: physical URI escapes closed capture namespace '+str(path))
        if receipt(path)!=row:raise ValueError('capture preflight: original stored receipt differs '+str(path))
        measurements[str(path)]=row
    def plain_document(path):
        path=Path(path);row=expected.get(str(path))
        if row is None:raise ValueError('capture preflight: metadata has no original physical receipt '+str(path))
        stored(path,row)
        if not path.is_file():return None
        if row['bytes']>2_000_000:raise ValueError('capture preflight: metadata ceiling '+str(path))
        value=_json(path.read_bytes());metadata[str(path)]=row
        return value
    archive_path=root/'archive-index.json'
    archive=plain_document(archive_path)
    if archive is None:raise ValueError('capture preflight: original archive root absent')
    if (archive.get('schema'),archive.get('schema_version'),archive.get('verified_roundtrip'))!=('scar.lossless-capture-archive',1,True):
        raise ValueError('capture preflight: unsupported original archive')
    manifests=sorted((root/'trace').glob('execution-evidence.*.json'))
    if len(manifests)!=1:raise ValueError('capture preflight: ambiguous native manifest')
    native=plain_document(manifests[0])
    if native is None:raise ValueError('capture preflight: native manifest absent')
    eto=PurePosixPath(native['artifacts']['execution_trace']['path'])
    original_root=eto.parent.parent
    files=_Files(root,original_root,archive,2_000_000_000)
    # Every declared physical mapping, including every OS thread archive.
    for logical,entry in files.entries.items():
        actual=PurePosixPath(entry['actual_path'])
        selected=root/str(actual.relative_to(original_root))
        row={'path':str(selected),'sha256':entry['gzip_sha256'],'bytes':entry['compressed_bytes']}
        stored(selected,row)
        if selected.is_file():
            local,normal_entry=files.local(logical)
            if local!=selected or normal_entry!=entry:raise ValueError('capture preflight: normal resolver differs')
        relations.append({'logical_uri':logical,'physical':row,'raw_sha256':entry['raw_sha256'],'raw_bytes':entry['raw_bytes']})
    def logical(logical_uri,*,raw_sha=None,raw_bytes=None,basis):
        logical_uri=str(logical_uri);lp=PurePosixPath(logical_uri)
        if not lp.is_relative_to(original_root) or '..' in lp.parts:
            raise ValueError('capture preflight: declaration escapes original capture namespace '+logical_uri)
        entry=files.entries.get(logical_uri)
        if entry is not None:
            if raw_sha is not None and raw_sha!=entry['raw_sha256']:raise ValueError('capture preflight: declared raw SHA differs '+logical_uri)
            if raw_bytes is not None and raw_bytes!=entry['raw_bytes']:raise ValueError('capture preflight: declared raw bytes differ '+logical_uri)
        else:
            selected=root/str(lp.relative_to(original_root));row=expected.get(str(selected))
            if row is None:raise ValueError('capture preflight: plain declaration lacks original physical receipt '+str(selected))
            if raw_sha is not None and raw_sha!=row['sha256']:raise ValueError('capture preflight: plain declaration raw SHA differs')
            if raw_bytes is not None and raw_bytes!=row['bytes']:raise ValueError('capture preflight: plain declaration raw bytes differ')
            stored(selected,row)
        selected=(root/str(PurePosixPath(entry['actual_path']).relative_to(original_root))) if entry else root/str(lp.relative_to(original_root))
        if selected.is_file():files.local(logical_uri)
        return {'logical_uri':logical_uri,'physical_uri':str(selected),'basis':basis}
    def raw_declarations(value,basis):
        if isinstance(value,list):
            for item in value:raw_declarations(item,basis)
        elif isinstance(value,dict):
            if {'path','raw_sha256','raw_bytes'}<=value.keys():
                if PurePosixPath(value['path']).is_absolute():
                    relations.append(logical(value['path'],raw_sha=value['raw_sha256'],raw_bytes=value['raw_bytes'],basis=basis))
            for child in value.values():raw_declarations(child,basis)
    for path in sorted((root/'trace').glob('*.json')):
        document=plain_document(path)
        if document is None:continue
        raw_declarations(document,str(path))
    trace=original_root/'trace';pid=native['pid']
    for name in (f'call-meta.{pid}.json',f'call-operand-meta.{pid}.json','run.json'):
        relations.append(logical(trace/name,basis='normal required call/operand/command metadata'))
    for name in (f'call-codes.{pid}.jsonl',f'call-events.{pid}.jsonl',f'call-operands.{pid}.jsonl'):
        relations.append(logical(trace/name,basis='normal required frame/code/operand families'))
    env_events,env_meta=trace/f'function-environments.{pid}.jsonl',trace/f'function-environment-meta.{pid}.json'
    if files.contains(env_events)!=files.contains(env_meta):raise ValueError('capture preflight: unmatched environment pair')
    if files.contains(env_events):
        relations.extend(logical(p,basis='normal paired environment family') for p in (env_events,env_meta))
    for label,ref in native['artifacts'].items():
        if label in ('execution_trace','kineto'):
            relations.append(logical(ref['path'],raw_bytes=ref['size_bytes'],basis='native artifact '+label))
    for name in ('dispatch_observations','tensor_physical_observations','native_tensor_input_observations'):
        config=native.get('configuration',{}).get(name)
        if config is not None:
            for field in ('events','metadata','manifest'):
                if field in config:relations.append(logical(config[field],basis='native configuration '+name+'.'+field))
    profile=json.loads(PROFILE.read_bytes())
    for os_logical in files.os_names():
        # Coordinate construction also reads launcher OS artifacts. These
        # need not themselves be target-process Run membership entries.
        relations.append(logical(os_logical,basis='normal os_names exact enumeration; independent of selected Run membership'))
    for member in profile['membership']:
        artifact=member['artifact']
        relations.append(logical(member['logical_path'],raw_sha=artifact['sha256'],raw_bytes=artifact['size_bytes'],basis='original coordinate profile membership'))
    return {'schema':'scar.capture-local-closed-preflight/1','status':'PASS_PHYSICAL_NAMESPACE_AND_STORED_SHA_ONLY' if not missing else 'MISSING_PHYSICAL_MEMBERS',
        'archive_uri':str(archive_path),'capture_root':str(root),'original_capture_root':str(original_root),
        'archive_mappings':len(files.entries),'physical_inputs':sorted(pins.values(),key=lambda r:r['path']),
        'physical_stored_bytes':sum(r['bytes'] for r in pins.values()),'metadata_inputs':sorted(metadata.values(),key=lambda r:r['path']),
        'declaration_relations':relations,'missing':missing,'normal_local_resolver_used':True,
        'raw_decompressed_or_parsed':False,'raw_SHA_reverified':False,'source_port_capability_exercised':False,
        'qualification':'existence, closed local namespace and original stored SHA only; normal coordinate raw EOF/SHA and source-port semantics remain to actual gate'}


if __name__=='__main__':
    result=check_capture()
    with (HERE/'CAPTURE_PREFLIGHT.json').open('x') as stream:json.dump(result,stream,indent=2);stream.write('\n')
    print(json.dumps({k:result[k] for k in ('status','archive_mappings','physical_stored_bytes','raw_decompressed_or_parsed')}))
    if result['missing']:raise ValueError('capture preflight: physical mapping members missing')
