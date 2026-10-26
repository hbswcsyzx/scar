"""One retained EOF/SHA diagnostic pass; not a full typed operand reader."""
from pathlib import Path
from collections import Counter,deque
import gzip,hashlib,json,time
control=Path(__file__).resolve().parent
command=json.loads((control/'COMMAND.json').read_text())
archive=json.loads((Path(command['capture_root'])/'archive-index.json').read_text())
result={'qualification':'archived raw EOF/SHA and GAP/tail projection only; no full typed stream/model qualification','files':[]}
for prefix in ('call-operands.','python-call-targets.'):
    refs=[row for row in archive['files'] if Path(row['logical_path']).name.startswith(prefix)]
    assert len(refs)==1
    ref=refs[0];path=Path(ref['actual_path']);stored_sha=hashlib.sha256()
    with path.open('rb') as stream:
        while block:=stream.read(1024*1024):stored_sha.update(block)
    assert stored_sha.hexdigest()==ref['gzip_sha256']
    digest=hashlib.sha256();decoded=rows=0;gaps=[];tail=deque(maxlen=8)
    started=time.monotonic()
    with gzip.open(path,'rb') as stream:
        for line in stream:
            digest.update(line);decoded+=len(line);rows+=1;tail.append(line)
            if b'"GAP"' in line:
                row=json.loads(line)
                if row.get('kind')=='GAP':gaps.append(row)
    assert (decoded,digest.hexdigest())==(ref['raw_bytes'],ref['raw_sha256'])
    reasons=Counter(row.get('reason',row.get('value',{}).get('reason')) for row in gaps)
    result['files'].append({'original_archive_declaration':ref,'raw_rows':rows,'decoded_bytes_read':decoded,
        'stored_unique_bytes':path.stat().st_size,'stored_bytes_read':2*path.stat().st_size,'stored_sha256_verified':stored_sha.hexdigest(),
        'raw_sha256_verified':digest.hexdigest(),'elapsed_seconds':time.monotonic()-started,
        'gap_reason_counts':dict(reasons),'gaps':gaps,'last_eight_records':[json.loads(line) for line in tail]})
(control/'STOP_DIAGNOSTIC.json').write_text(json.dumps(result,indent=2)+'\n')
print(json.dumps({'files':[{'logical':r['original_archive_declaration']['logical_path'],'raw_rows':r['raw_rows'],
    'decoded':r['decoded_bytes_read'],'stored':r['stored_bytes_read'],'gap_reason_counts':r['gap_reason_counts'],
    'first_gap':r['gaps'][0] if r['gaps'] else None} for r in result['files']]},indent=2))
