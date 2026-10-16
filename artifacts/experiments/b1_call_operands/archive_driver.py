"""Archive only terminal call files owned by the given capture experiment."""
import argparse
import gzip
import hashlib
import json
from pathlib import Path
import re
import subprocess
import time


def main():
    parser=argparse.ArgumentParser()
    parser.add_argument('capture',type=Path)
    args=parser.parse_args()
    base=args.capture.resolve()
    repository=Path('/home/zyf/AAA/scar')
    assert base.is_relative_to(repository/'artifacts/experiments/b1_call_operands')
    result=json.loads((base/'capture-result.json').read_text())
    assert result['returncode']==0 and result['scar_source_unchanged']
    assert result['target_git_unchanged'] and result['target_tracked_python_unchanged']
    receipt=base/'archive-result.json'
    assert not receipt.exists()
    trace=base/'trace'
    metadata=[json.loads(path.read_text()) for path in trace.glob('call-operand-meta.*.json')]
    assert metadata
    expected={(item['process_id'],item['family']):item for meta in metadata for item in meta['base_manifest']}
    meta_by_pid={meta['process_id']:meta for meta in metadata}
    before=time.perf_counter()
    rows=[]
    for path in sorted(trace.glob('call-*.jsonl')):
        match=re.fullmatch(r'call-(codes|events|operands)\.([1-9][0-9]*)\.jsonl',path.name)
        assert match is not None and not path.is_symlink()
        family,pid=match.group(1),int(match.group(2))
        tracked=subprocess.run(['git','ls-files','--error-unmatch','--',str(path.relative_to(repository))],
            cwd=repository,capture_output=True)
        assert tracked.returncode!=0,'never remove a tracked raw file'
        original=path.stat()
        target=path.with_name(path.name+'.gz')
        assert not target.exists()
        raw_hash=hashlib.sha256()
        count=lines=0
        with path.open('rb') as source,target.open('xb') as raw:
            with gzip.GzipFile(fileobj=raw,mode='wb',filename='',mtime=0,compresslevel=1) as output:
                while chunk:=source.read(1_000_000):
                    raw_hash.update(chunk)
                    count+=len(chunk)
                    lines+=chunk.count(b'\n')
                    output.write(chunk)
        if family=='operands':
            assert count==meta_by_pid[pid]['bytes'] and lines==meta_by_pid[pid]['events']
        else:
            bound=expected[pid,family]
            assert (count,lines,raw_hash.hexdigest())==(bound['raw_bytes'],bound['lines'],bound['raw_sha256'])
        checked=hashlib.sha256()
        decoded=0
        with gzip.open(target,'rb') as source:
            while chunk:=source.read(1_000_000):
                checked.update(chunk)
                decoded+=len(chunk)
        assert count==decoded==original.st_size and checked.digest()==raw_hash.digest()
        current=path.stat()
        assert (current.st_ino,current.st_size,current.st_mtime_ns)==(original.st_ino,original.st_size,original.st_mtime_ns)
        with target.open('rb') as source:
            compressed_hash=hashlib.file_digest(source,'sha256').hexdigest()
        row={'logical_path':str(path),'retained_path':str(target),'raw_bytes':count,
             'raw_lines':lines,'raw_sha256':raw_hash.hexdigest(),'compressed_bytes':target.stat().st_size,
             'compressed_sha256':compressed_hash,'allocated_bytes_before':original.st_blocks*512,
             'verified_decompression':True}
        path.unlink()
        row['plain_removed']=True
        rows.append(row)
    report={'schema':'scar.owned-call-capture-archive','schema_version':1,'files':rows,
        'wall_seconds':time.perf_counter()-before,'raw_bytes':sum(row['raw_bytes'] for row in rows),
        'retained_compressed_bytes':sum(row['compressed_bytes'] for row in rows),
        'status':'VERIFIED_COMPRESSED','capture_coverage_status':result['capture_coverage_status'],
        'whole_program_complete':False,'transformation_authorized':False}
    receipt.write_text(json.dumps(report,indent=2)+'\n')
    print(json.dumps({key:value for key,value in report.items() if key!='files'}),flush=True)


if __name__=='__main__':
    main()
