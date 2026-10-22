"""Independent standard-library raw line/birth correspondence; not a full model proof."""
from collections import Counter
import gzip,hashlib,json,re
from pathlib import Path

root=Path(__file__).resolve().parent
with gzip.open(root/'result-attempt2/os-resources.json.gz','rt') as stream:
    document=json.load(stream)
artifacts=document['artifacts'];lines_by_artifact={};raw_births=set();raw_lines=0
for i,artifact in enumerate(artifacts):
    path=Path(artifact['uri'])
    if path.parent.name!='os':raise ValueError('unexpected artifact scope')
    digest=hashlib.sha256();size=0;count=0
    with gzip.open(path,'rb') if path.suffix=='.gz' else path.open('rb') as stream:
        for count,raw in enumerate(stream,1):
            digest.update(raw);size+=len(raw)
            if re.match(rb'^\d+\.\d+ (?:open|openat|openat2|creat)\(.*\)\s+=\s+[0-9]+(?:\s|$)',raw):
                raw_births.add((i,count))
    assert digest.hexdigest()==artifact['sha256'] and size==artifact['size_bytes']
    lines_by_artifact[i]=count;raw_lines+=count
cursor=Counter()
for artifact,line,kind,name,reason in document['line_classifications']:
    cursor[artifact]+=1
    assert line==cursor[artifact] and line<=lines_by_artifact[artifact]
assert dict(cursor)==lines_by_artifact and raw_lines==705569
resources=document['resources'];handles=document['handles'];events=document['target_lifetime_events']
# IDs are exact execution record IDs with a scalar value field.
def wire(row):return row['value'] if 'value' in row else row['wire']
ids={wire(row['id']) for row in resources}
assert len(ids)==len(resources)==len(raw_births)==12587
assert len({wire(row['id']) for row in handles})==len(handles)
assert all(wire(row['target']['instance']) in ids for row in handles)
assert len(events)==len(resources)
raw_locations={}
for i,a in enumerate(artifacts):raw_locations[a['sha256']]=i
observed_births={(raw_locations[row['source']['artifact']['sha256']],int(row['source']['locator'].split('/')[-1])) for row in resources}
assert observed_births==raw_births
observations=document['observations']
unknown_mutating=sum(row['result'] is None and row['syscall'] in {'clone','clone3','fork','vfork','dup2','dup3','execve','execveat','unshare','close_range','io_uring_setup','io_uring_enter'} for row in observations)
resumed=sum(row['source']['line']!=row['entry_source']['line'] for row in observations)
unsupported=Counter(row[4] for row in document['line_classifications'] if row[4] not in (None,'outside_fd_profile'))
assert not unknown_mutating and not resumed and not unsupported, 'new continuity guards affect this capture; re-import required'
summary={'valid':True,'raw_artifacts':len(artifacts),'raw_lines':raw_lines,'resource_births':len(resources),'handle_generations':len(handles),'connected_io':document['summary']['connected_io'],'raw_successful_open_receipts':len(raw_births),'all_line_locators_exact':True,'all_artifact_hashes_checked':True,'unknown_mutating_returns':unknown_mutating,'resumed_calls':resumed,'unparsed_frontiers':dict(unsupported),'new_continuity_guards_change_this_capture':False,'complete_resource_model':False,'canonical_source_connections_established':False,'transformation_authorized':False}
(root/'audit-result.json').write_text(json.dumps(summary,indent=2)+'\n')
print(json.dumps(summary))
