"""Compress owned terminal capture files; verify exact bytes before unlinking."""
import gzip
import hashlib
import json
from pathlib import Path
import time


HERE = Path(__file__).resolve().parent


def main():
    result = json.loads((HERE / 'capture-result.json').read_text())
    assert result['returncode'] == 0 and result['scar_source_unchanged']
    assert result['target_git_unchanged'] and result['target_tracked_python_unchanged']
    trace = HERE / 'trace'
    rows = []
    started = time.perf_counter()
    for path in sorted(trace.glob('call-*.jsonl')):
        original = path.stat()
        target = path.with_name(path.name + '.gz')
        assert not target.exists() and not path.is_symlink()
        digest = hashlib.sha256()
        count = 0
        with path.open('rb') as source, target.open('xb') as raw:
            with gzip.GzipFile(fileobj=raw, mode='wb', filename='', mtime=0, compresslevel=1) as output:
                while chunk := source.read(1_000_000):
                    digest.update(chunk)
                    count += len(chunk)
                    output.write(chunk)
        checked = hashlib.sha256()
        decoded = 0
        with gzip.open(target, 'rb') as source:
            while chunk := source.read(1_000_000):
                checked.update(chunk)
                decoded += len(chunk)
        assert count == decoded == original.st_size and checked.digest() == digest.digest()
        current = path.stat()
        assert (current.st_ino,current.st_size,current.st_mtime_ns) == (original.st_ino,original.st_size,original.st_mtime_ns)
        with target.open('rb') as source:
            compressed_sha = hashlib.file_digest(source, 'sha256').hexdigest()
        row = {'logical_path':str(path),'retained_path':str(target),'raw_bytes':count,
               'raw_sha256':digest.hexdigest(),'compressed_bytes':target.stat().st_size,
               'compressed_sha256':compressed_sha,'allocated_bytes_before':original.st_blocks*512,
               'verified_decompression':True}
        path.unlink()
        row['plain_removed'] = True
        rows.append(row)
    meta_path, = trace.glob('call-operand-meta.*.json')
    meta = json.loads(meta_path.read_text())
    report = {'schema':'scar.b1-owned-capture-archive','schema_version':1,'files':rows,
              'wall_seconds':time.perf_counter()-started,
              'raw_bytes':sum(row['raw_bytes'] for row in rows),
              'retained_compressed_bytes':sum(row['compressed_bytes'] for row in rows),
              'status':'VERIFIED_COMPRESSED','capture_coverage_status':'FAILED_BUDGET',
              'operand_metadata':{key:meta[key] for key in ('rule','events','instructions','call_attempts',
                  'handshakes','gaps','loads','references','bytes','dropped_events','errors','io_failed')},
              'route_analysis_performed':False,
              'inferred_route_boundary':'Current route builder rejects all attempts of a process with dropped_events.',
              'whole_program_complete':False,'transformation_authorized':False}
    (HERE/'archive-result.json').write_text(json.dumps(report,indent=2)+'\n')
    print(json.dumps({key:value for key,value in report.items() if key not in ('files','operand_metadata')}))


if __name__ == '__main__':
    main()
