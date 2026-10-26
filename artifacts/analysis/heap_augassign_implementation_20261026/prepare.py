"""Select one retained heap AugAssign by original archived AST and weight."""
import ast,json,hashlib
from pathlib import Path
HERE=Path(__file__).resolve().parent
FRONTIERS=Path('/home/zyf/AAA/scar-worktrees/source-comprehension-model/artifacts/analysis/source_comprehension_implementation_20261026/FRONTIERS.json')
def receipt(path):
 data=path.read_bytes();return {'path':str(path),'bytes':len(data),'sha256':hashlib.sha256(data).hexdigest()}
def save(name,data):(HERE/name).write_text(json.dumps(data,sort_keys=True,indent=2)+'\n')
rows=json.loads(FRONTIERS.read_bytes())['unsupported']; candidates=[];evaluated=[];sources={}
for row in rows:
 if 'AugAssign' not in row['frontier']['detail']:continue
 terminal=Path(row['public_terminal']);record=json.loads(terminal.read_bytes())
 snapshot=record['entry_reference']['snapshot'];manifest=Path(record['code_witness']['witness']['store']['path'])
 doc=json.loads(manifest.read_bytes());declared=[r for r in doc['sources'].values() if r['snapshot']==snapshot]
 assert len(declared)==1
 source=declared[0]['artifact'];path=manifest.parent/source['path'];data=path.read_bytes()
 assert len(data)==source['bytes'] and hashlib.sha256(data).hexdigest()==source['sha256']
 text=data.decode(snapshot['encoding']);assert 'sha256:'+hashlib.sha256(text.encode('utf8')).hexdigest()==snapshot['fingerprint']
 ref=row['frontier']['source'];span=(ref['start_line'],ref['end_line'],ref['start_column'],ref['end_column'])
 matching=[n for n in ast.walk(ast.parse(text)) if isinstance(n,ast.AugAssign) and (n.lineno,n.end_lineno,n.col_offset,n.end_col_offset)==span]
 assert len(matching)==1
 node=matching[0];details={**row,'target_kind':type(node.target).__name__,'expression':ast.unparse(node),'terminal_receipt':receipt(terminal),'archived_source':receipt(path),'archive_manifest':receipt(manifest)}
 evaluated.append(details)
 if isinstance(node.target,(ast.Attribute,ast.Subscript)):candidates.append(details)
assert len(evaluated)==4 and sum(r['historical_calls'] for r in evaluated)==53
candidates.sort(key=lambda r:(-r['historical_calls'],r['entry_key']))
assert candidates
save('READ_PLAN.json',{'base':'c6e31a9a','selection':'original AugAssign frontier + archived AST Attribute/Subscript; historical_calls DESC, entry_key ASC','frontiers':receipt(FRONTIERS),'all_four':evaluated,'selected':candidates[:1],'budget':{'body':1,'source_files':1,'operations':4000,'elapsed_seconds':600,'record_bytes':128000000,'output_bytes':256000000},'target':0,'compile':0,'lower':0})
print(json.dumps({'selected':[{k:r[k]for k in ('entry_key','target_kind','historical_calls','expression')}for r in candidates[:1]],'four_count':len(evaluated)}))
