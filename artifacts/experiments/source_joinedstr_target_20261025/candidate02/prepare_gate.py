"""Freeze one exact prior JoinedStr debt; no context/graph stream or lowerer."""
import ast
import difflib
import hashlib
import json
from pathlib import Path
import runpy
import sys

BASE=Path(__file__).resolve().parent
ROOT=BASE.parents[3]
OLD=ROOT/'artifacts/experiments/source_call_kwargs_bodies_20261025'
MAIN=Path('/home/zyf/AAA/scar-worktrees/structured-program-model')

def raw(v):return (json.dumps(v,ensure_ascii=False,sort_keys=True,indent=2)+'\n').encode()
def sha(b):return hashlib.sha256(b).hexdigest()
def meta(path):
    path=Path(path);s=path.stat()
    if path.is_symlink() or s.st_size>1_000_000:raise ValueError('small metadata bound')
    b=path.read_bytes()
    return json.loads(b),{'path':str(path),'stored_bytes':len(b),'stored_sha256':sha(b),'decoded_bytes':len(b),
        'decoded_sha256':sha(b),'size':s.st_size,'mtime_ns':s.st_mtime_ns,'ctime_ns':s.st_ctime_ns,'inode':s.st_ino,'device':s.st_dev}
def source(path):
    path=Path(path);b=path.read_bytes()
    return {'path':str(path),'bytes':len(b),'sha256':sha(b)}
def receipt(row):return {'path':row['path'],'sha256':row['stored_sha256'],'bytes':row['stored_bytes']}

def main():
    parent,pr=meta(OLD/'candidate04/freeze.json');previous,ps=meta(OLD/'candidate04/selection.json')
    earlier,es=meta(OLD/'candidate03/selection.json');launch,lr=meta(OLD/'candidate04/attempt04/launch-result.json')
    failure,fr=meta(OLD/'candidate04/attempt04/failure.json');postflight,pf=meta(OLD/'candidate04/postflight01/receipt.json')
    if launch['exit_code']!=1 or postflight['postflight']['exit_code']!=0 or postflight['original_window']['exit_code']!=1:
        raise ValueError('original/postflight terminal identities differ')
    debt,dr=meta(OLD/'candidate03/attempt03/body-02-result.json')
    returned,rr=meta(OLD/'candidate03/attempt03/body-02-returned.json')
    subjects=previous['scope_subjects']
    active=[r for r in subjects if r['definition']['id']==debt['definition'] and r['definition']['source']==debt['source']]
    if len(subjects)!=4 or len(active)!=1 or debt['artifact'] is not None or returned['graph_present']:
        raise ValueError('exact previous unreturned body qualification differs')
    frontier=debt['gaps'][-1]
    if frontier['kind']!='UNSUPPORTED_SYNTAX' or not frontier['detail'].endswith('checked rule for JoinedStr'):
        raise ValueError('prior final unsupported debt is not JoinedStr')
    item={**active[0],'retry_frontier':frontier}
    fi=str(item['file_index']);file=earlier['files'][fi]
    text_path=Path(file['utf8_path']);text=text_path.read_bytes()
    if sha(text)!=item['snapshot']['fingerprint'].removeprefix('sha256:'):raise ValueError('archived UTF8 differs')
    tree=ast.parse(text.decode('utf8'),filename=item['snapshot']['path'])
    ref=frontier['source'];span=(ref['start_line'],ref['end_line'],ref['start_column'],ref['end_column'])
    nodes=[n for n in ast.walk(tree) if isinstance(n,ast.JoinedStr)
           and (n.lineno,n.end_lineno,n.col_offset,n.end_col_offset)==span]
    if len(nodes)!=1:raise ValueError('prior exact source debt has no unique JoinedStr AST')
    prior={};extra=[pr,ps,es,lr,fr,pf,dr,rr]
    for subject in subjects:
        if subject['definition']['id']==debt['definition']:continue
        if str(subject['original_sequence']) in previous['prior_outcomes']:
            old=previous['prior_outcomes'][str(subject['original_sequence'])]
            result,mr=meta(old['evidence']['path'])
        else:
            matches=[r for r in failure['completed_results'] if r['definition']==subject['definition']['id']]
            if len(matches)!=1:raise ValueError('remaining original subject has no exact returned result')
            matches2=[]
            for ordinal in (1,2):
                path=OLD/f'candidate04/attempt04/body-{ordinal:02d}-result.json'
                value,m=meta(path)
                if value==matches[0]:matches2.append((value,m))
            if len(matches2)!=1:raise ValueError('exact body result storage differs')
            result,mr=matches2[0]
        if result['artifact'] is None or not result['checks']['public_structure']['roundtrip_equal']:
            raise ValueError('prior finite graph lacks exact independent structure qualification')
        prior[str(subject['original_sequence'])]={'subject':subject,'evidence':receipt(mr),'result':result,
            'body_state':'OPEN','inherited_only':True}
        extra.append(mr)
    selection={**previous,'status':'PREPARED_ONE_JOINEDSTR_FRONTIER_NO_BODY_LOWERING',
        'selected':[item],'scope_subjects':subjects,'files':{fi:file},'prior_outcomes':prior,'reused_artifacts':{},
        'parent_scope':{'freeze':receipt(pr),'selection':receipt(ps),'prior_window_terminal':receipt(lr),
            'postflight':receipt(pf),'run':previous['run'],'subject_count':4},
        'prior_checks':[receipt(pf)],'previous_attempts':{'joinedstr_construction350':receipt(dr),'returned_without_graph':receipt(rr)},
        'new_body_lowering_sequences':[item['original_sequence']],
        'remaining_selection_rule':'original four qualified subjects; exactly the saved no-graph final JoinedStr debt matched by definition/source and original AST; inherit three finite results without opening graphs'}
    (BASE/'selection.json').write_bytes(raw(selection))
    changed=('scar/analysis/source_heap_lowering.py','scar/analysis/source_string_lowering.py',
             'scar/analysis/source_string_validation.py','scar/analysis/source_language_validation.py')
    changes=[];diff=[]
    for relative in changed:
        current=source(ROOT/relative);current['relative_path']=relative
        target=MAIN/relative
        old=source(target) if target.exists() else None
        current['main_baseline']=old;changes.append(current)
        diff.extend(difflib.unified_diff(target.read_text().splitlines(True) if target.exists() else [],
            (ROOT/relative).read_text().splitlines(True),fromfile='main/'+relative,tofile='candidate/'+relative))
    (BASE/'changed-sources.json').write_bytes(raw(changes));(BASE/'changes.diff').write_text(''.join(diff))
    production=[]
    for row in parent['production_sources']:
        current=source(row['path']);current['relative_path']=row['relative_path'];current['previous_source']=row
        if row['relative_path'] not in changed and (current['bytes']!=row['bytes'] or current['sha256']!=row['sha256']):
            raise ValueError('one of the other ten frozen production sources changed')
        production.append(current)
    for relative in changed:
        if relative not in {r['relative_path'] for r in production}:
            row=source(ROOT/relative);row['relative_path']=relative;production.append(row)
    candidates=[source(path) for path in sorted((ROOT/'scar').rglob('*.py'))]
    runtime=runpy.run_path(str(BASE/'run_gate.py'),run_name='preflight_imports')['preload_readers']()
    runtime_paths=sorted({path for name,path in runtime.items() if name!='__main__' and Path(path).is_file()})
    runtime_rows=[source(path) for path in runtime_paths]
    fixed=[source(path) for path in (BASE/'prepare_gate.py',BASE/'run_gate.py',BASE/'gate_guards.py',BASE/'selection.json',
        BASE/'changed-sources.json',BASE/'changes.diff',Path(sys.executable).resolve(),Path('/usr/bin/time'))]
    fixed=list({r['path']:r for r in fixed+runtime_rows}.values())
    inputs={r['path']:r for r in parent['inputs']};inputs.update({r['path']:r for r in extra})
    for row in inputs.values():
        p=Path(row['path']);s=p.stat()
        if p.is_symlink() or (s.st_size,s.st_mtime_ns,s.st_ctime_ns,s.st_ino,s.st_dev)!=(row['size'],row['mtime_ns'],row['ctime_ns'],row['inode'],row['device']):
            raise ValueError('exact retained input stat changed')
    freeze={**parent,'candidate':'joinedstr_candidate02','status':'FROZEN_NOT_EXECUTED','production_sources':production,
        'changed_sources':changes,'candidate_scar_sources':candidates,'small_frozen_files':fixed,'runtime_modules':runtime_rows,
        'inputs':sorted(inputs.values(),key=lambda r:r['path']),'attempt':str(BASE/'attempt01'),'active_subjects':1,
        'full_parent_subjects':4,'actual_source_files':1,'parent_scope':selection['parent_scope'],
        'internal_check_inputs':[{'path':str(BASE/'freeze.json'),'role':'ROOT_APPROVED_FREEZE_SHA256','max_bytes':1000000}],
        'reuse_policy':'inherit three finite per-body results; do not open/read/decode/re-lower their graphs; one exact JoinedStr-debt body may lower once'}
    (BASE/'freeze.json').write_bytes(raw(freeze))
    value={'status':'FROZEN_NOT_RUN','freeze_sha256':sha((BASE/'freeze.json').read_bytes()),'active_subjects':1,'full_subjects':4,
        'selected_sequence':item['original_sequence'],'source_files':1,'source_sha_files':len(candidates),'input_stat_pins':len(inputs),
        'runtime_preloaded_files':len(runtime_rows),'tool_guard_bytes':sum(r['bytes'] for r in fixed+candidates),
        'target_context_or_graph_stream_reads':0,'body_lowerings':0,'compiler_payloads_loaded':0,'changed_sources':changes}
    (BASE/'PREPARATION_RECEIPT.json').write_bytes(raw(value));print(json.dumps(value,ensure_ascii=False,sort_keys=True))

if __name__=='__main__':main()
