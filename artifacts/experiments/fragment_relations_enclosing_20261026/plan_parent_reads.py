from pathlib import Path
import json,sqlite3,time
ROOT=Path(__file__).resolve().parents[3];OUT=Path(__file__).resolve().parent
BASE=ROOT/'artifacts/experiments/fragment_relations_implementation_20261026/candidate02/attempt01/result'
m=json.loads((BASE/'manifest.json').read_text());p=Path(m['catalog']['original_eeg_manifest']['uri']);em=json.loads(p.read_text());chunks=em['graphs']['evidence']['tables']['instances']['chunks']
def rchar():return int(dict(line.split(':') for line in Path('/proc/self/io').read_text().splitlines())['rchar'])
start=time.monotonic();before=rchar();db=sqlite3.connect('file:'+str(BASE/'locator.sqlite')+'?mode=ro&immutable=1',uri=True);db.execute('PRAGMA query_only=ON')
native={r[0] for r in db.execute('SELECT DISTINCT instance FROM native')}
pairs=db.execute("SELECT e.target,e.source FROM edges e JOIN nodes t ON t.id=e.target WHERE e.relation='provider_scope_association' AND t.category IN ('kernel','gpu_memcpy','gpu_memset')").fetchall()
hosts={host for target,host in pairs if host not in native};needed={};visited=set()
for host in hosts:
 current=host;path=set()
 while True:
  if current in visited:break
  assert current not in path;path.add(current)
  row=db.execute('SELECT ordinal,parent FROM nodes WHERE id=?',(current,)).fetchone();assert row
  ordinal,parent=row;number=next(i for i,d in enumerate(chunks) if d['first_ordinal']<=ordinal<=d['last_ordinal']);needed[number]=chunks[number]
  if current in native:break
  assert parent;current=parent
 visited.update(path)
actual=rchar()-before
result={'qualification':'PLANNING_FROM_ORIGINAL_READONLY_DERIVED_INDEX; ALL_GATE_PROOFS_REPLAY_ORIGINALS','missing_distinct_hosts':len(hosts),'needed_original_parent_records':len(visited),'original_parent_chunks':[dict(number=n,**d) for n,d in sorted(needed.items())],'parent_stored_bytes':sum(d['physical_bytes'] for d in needed.values()),'parent_decoded_bytes':sum(d['decoded_bytes'] for d in needed.values()),'sqlite_selected_query_rchar_bytes':actual,'elapsed_s':time.monotonic()-start,'source_artifact':m['catalog']['original_eeg_manifest']}
(OUT/'PARENT_READ_PLAN.json').write_text(json.dumps(result,indent=2)+'\n');print(json.dumps({k:v for k,v in result.items() if k!='original_parent_chunks'},indent=2))
