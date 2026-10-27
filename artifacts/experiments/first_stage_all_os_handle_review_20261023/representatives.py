"""Only small non-main raw representatives selected by existing catalog facts."""
from collections import defaultdict
import gzip
import hashlib
import json
from pathlib import Path

from scar.trace.os_resources import _TIME, _CALL, _arguments, _number


HERE=Path(__file__).resolve().parent
EXP=HERE.parent
summary=json.loads((HERE/'summary.json').read_text())
archive=json.loads((EXP/'first_stage_lewm_physical_20261023/archive-index.json').read_text())
by_logical={row['logical_path']:row for row in archive['files']}
groups={row['native_tid']:row for row in summary['handles_by_actor']}
wanted=[];legacy_sources=set();total=0
with gzip.open(HERE/'handles.jsonl.gz','rb') as stream:
    for raw in stream:
        row=json.loads(raw)
        if row['container_status']!='TYPED_CONTAINER_CONNECTED':
            total+=1;legacy_sources.add((row['source']['artifact_index'],row['source']['physical_line']))
            if not wanted or not row['target_origin_same_source']:
                wanted.append(row)
needs=defaultdict(list)
for row in wanted:
    needs[groups[row['native_actor']]['logical_source']].append(row)
records=[]
for logical, rows in needs.items():
    entry=by_logical[logical]
    assert entry['raw_bytes']<=500000, 'representative budget forbids main raw'
    stored=Path(entry['actual_path']).read_bytes()
    assert len(stored)==entry['compressed_bytes'] and hashlib.sha256(stored).hexdigest()==entry['gzip_sha256']
    decoded=gzip.decompress(stored)
    assert len(decoded)==entry['raw_bytes'] and hashlib.sha256(decoded).hexdigest()==entry['raw_sha256']
    lines=decoded.splitlines()
    for row in rows:
        text=lines[row['source']['physical_line']-1].decode();body=_TIME.match(text)[1]
        call=_CALL.match(body);name,args,result,tail=call.groups()
        fd=_number(result);assert fd is not None and fd>=0
        records.append({'original_handle_id':row['id'],'original_handle_ordinal':row['handle_ordinal'],
            'source_artifact':entry,'physical_line':row['source']['physical_line'],
            'syscall':name,'arguments':_arguments(args),'actual_fd_from_return':fd,'rendering':text,
            'target_origin_same_source':row['target_origin_same_source'],'stored_and_raw_sha_verified':True})
assert len(records)==2 and len(legacy_sources)==total==12649
report={'schema':'scar.os-handle-source-small-representatives','schema_version':1,
    'legacy_handles':total,'unique_legacy_source_lines':len(legacy_sources),'records':records,
    'raw_bytes_read':sum(by_logical[key]['raw_bytes'] for key in needs),'main_raw_read':False,'production_changed':False}
with (HERE/'representatives.json').open('x') as stream:json.dump(report,stream,indent=2,sort_keys=True);stream.write('\n')
print(json.dumps({'raw_bytes_read':report['raw_bytes_read'],'records':len(records),'unique_legacy_sources':len(legacy_sources)}))
