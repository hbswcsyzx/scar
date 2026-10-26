"""196-row schedule/hash projection only; no catalog owner/body proof."""
from pathlib import Path
from hashlib import sha256
import json,time,ast
ROOT=Path(__file__).resolve().parent
publication=Path('/home/zyf/AAA/scar-worktrees/source-entry-project/artifacts/experiments/source_entry_incremental35_continuation02_20261026/result/manifest.json')
ledger=Path('/home/zyf/AAA/scar-worktrees/source-try-model/artifacts/analysis/complete_source_entry_selection_20261026/complete-latest-ledger.json')
start=time.monotonic();canonical=lambda d:json.dumps(d,sort_keys=True,ensure_ascii=False,separators=(',',':'),allow_nan=False).encode()
raw=publication.read_bytes();assert sha256(raw).hexdigest()=='a124d78bb5e50e4ff96d1af2858357651cb9eda13918c328fd753a3a4bd4650b'
d=json.loads(raw);l=json.loads(ledger.read_bytes());assert sha256(canonical(d['plan'])).hexdigest()==d['plan_sha256']
lookup={r['entry_key']:r['file_key'] for r in l['entries']};assert len(lookup)==len(l['entries'])
rows=d['bodies'];expected=d['plan']['expectations'];assert len(rows)==len(expected)==196
common={k:v for k,v in d['plan'].items() if k!='expectations'}
groups={}
for i,(r,e) in enumerate(zip(rows,expected)):
 assert all(r.get(k)==v for k,v in e.items())
 groups.setdefault(lookup[r['entry_key']],[]).append((i,(r,e)))
checked=[None]*len(rows);plans=[]
for key in sorted(groups):
 group=groups[key]
 # A metadata-only projection, NOT the normal planner or qualification.
 projection={**common,'expectations':[e for _,(_,e) in group]}
 plans.append({'file_key':key,'indices':[i for i,_ in group],'projection_sha256':sha256(canonical(projection)).hexdigest()})
 for index,(r,e) in group:checked[index]=r
assert checked==rows and sorted(i for g in plans for i in g['indices'])==list(range(196))
# The whole ordinary body-check loop stays textually exact.
rel='scar/analysis/source_program_publication.py'
before=(ROOT/'before'/rel).read_text();after=(ROOT/'after'/rel).read_text()
start_token='    for index, (row, expected) in row_order:';end_token='    return document, receipt, tuple(checked)'
a=before[before.index(start_token,before.index('    checked = [None] * len(rows)',before.index('def _read_source_entries2'))):];a=a[:a.index(end_token)]
b=after[after.index(start_token,after.index('    checked = [None] * len(rows)',after.index('def _read_source_entries2'))):];b=b[:b.index(end_token)]
assert a==b
# Group formation no longer calls resolve; normal source/CAS planner does.
assert 'file_key = catalog.resolve' not in after
for p in (ROOT/'after').rglob('*.py'):compile(p.read_text(),str(p),'exec')
result={'status':'PASS_METADATA_SCHEDULE_AND_UNCHANGED_BODY_KERNEL','bodies':len(rows),'file_groups':len(groups),
 'complete_plan_sha256':d['plan_sha256'],'row_order_preserved':True,'no_overlap_or_missing_rows':True,
 'body_check_kernel_textually_unchanged':True,'normal_planner_calls':0,'body_reads':0,'source_graph_reads':0,
 'metadata_bytes_read':len(raw)+ledger.stat().st_size,'elapsed_seconds':time.monotonic()-start,
 'qualification':'metadata/syntax/static API review only; grouped normal semantic reader NOT run','groups':plans}
(ROOT/'METADATA_CHECK.json').write_text(json.dumps(result,indent=2)+'\n')
print({k:v for k,v in result.items() if k!='groups'})
