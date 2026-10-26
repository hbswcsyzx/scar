from pathlib import Path
from types import CodeType
import ast,dis,json
from scar.analysis.compiler_witness_archives import CompilerWitnessArchives,CompilerArchiveBudget
from scar.analysis.code_witness import CodeWitnessBudget
from scar.ir.record_codec import decode
from scar.ir.program.call_edges import CapturedCode
from scar.ir.semantics_v2 import SourceSnapshot
ROOT=Path(__file__).resolve().parents[3];HERE=Path(__file__).resolve().parent
original=json.loads((ROOT/'artifacts/analysis/complete_source_entry_selection_20261026/complete-latest-ledger.json').read_bytes())
latest=json.loads((ROOT/'artifacts/experiments/call_expansion_related_entries_20261026/continuation01/terminal.json').read_bytes())
rows=[]
for row in [*original['entries'],*latest['entries']]:
 if row['status']!='UNSUPPORTED':continue
 p=Path(row['public_terminal']);m=json.loads(p.with_name('returned-metadata.json').read_bytes());gap=m['metadata']['gaps'][-1]
 if gap['detail']=='structured control/effect protocol still required for FunctionDef':rows.append((json.loads(p.read_bytes()),gap,p))
assert len(rows)==len({row['entry_key']for row,g,p in rows})
config=json.loads(Path('/home/zyf/AAA/scar-worktrees/source209-model/artifacts/experiments/source209_resume01_20261026/inputs.json').read_bytes())
archives=CompilerWitnessArchives(tuple((x['directory'],x['manifest']['sha256'])for x in config['archives']),store_budget=CodeWitnessBudget(max_compile_keys=94,max_source_files=94,max_source_bytes=8_000_000,max_module_bytes=16_000_000,max_archive_bytes=256_000_000,max_manifest_bytes=8_000_000),budget=CompilerArchiveBudget(max_archives=4,max_total_modules=256,max_total_sources=256,max_declared_payload_bytes=256_000_000))
records=[]
for row,gap,p in rows:
 e=row['code_witness'];store=archives.store_for(e['witness']['store']);snap=decode(SourceSnapshot,e['source_link']['snapshot']);code,_=store.resolve(decode(CapturedCode,e['captured']),snap,tuple(e['source_link']['optimize_levels']),allow_compile=False);text=store.text(snap);tree=ast.parse(text)
 s=gap['source'];nodes=[n for n in ast.walk(tree)if isinstance(n,ast.FunctionDef)and(n.lineno,n.end_lineno,n.col_offset,n.end_col_offset)==(s['start_line'],s['end_line'],s['start_column'],s['end_column'])];assert len(nodes)==1;n=nodes[0]
 cs=[(i,c)for i,c in enumerate(code.co_consts)if type(c)is CodeType and c.co_name==n.name and c.co_firstlineno==(n.decorator_list[0].lineno if n.decorator_list else n.lineno)]
 annotations=any(a.annotation is not None for a in (*n.args.posonlyargs,*n.args.args,*n.args.kwonlyargs))or n.returns is not None or any(a and a.annotation for a in(n.args.vararg,n.args.kwarg))
 instructions=list(dis.get_instructions(code));details=[]
 for k,load in enumerate(instructions):
  if load.opname=='LOAD_CONST'and type(load.argval)is CodeType and load.argval.co_name==n.name:
   details.append([{'opname':x.opname,'arg':x.arg,'argrepr':x.argrepr,'offset':x.offset,'span':list(x.positions)}for x in instructions[max(0,k-8):k+15]])
 item={'entry_key':row['entry_key'],'public_terminal':str(p),'source':s,'name':n.name,'decorators':len(n.decorator_list),'annotations':bool(annotations),'type_params':len(n.type_params),'defaults':[ast.dump(x,include_attributes=False)for x in n.args.defaults],'kwdefaults':[ast.dump(x,include_attributes=False)if x else None for x in n.args.kw_defaults],'child_code_candidates':[{'constant_index':i,'freevars':c.co_freevars,'flags':c.co_flags,'qualname':c.co_qualname}for i,c in cs],'instructions':details,'source_segment':ast.get_source_segment(text,n)};records.append(item)
 print(row['entry_key'][:8],Path(s['path']).name,s['start_line'],'decor',item['decorators'],'annot',item['annotations'],'defaults',len(item['defaults']),len([x for x in item['kwdefaults']if x]),'free',[x['freevars']for x in item['child_code_candidates']],flush=True)
(HERE/'real-nested-definitions.json').write_text(json.dumps({'entries':records,'CodeWitness_counts':[s.counts for s in archives._stores.values()],'graph_decode':0,'compile':0,'target':0},sort_keys=True,separators=(',',':'))+'\n')
