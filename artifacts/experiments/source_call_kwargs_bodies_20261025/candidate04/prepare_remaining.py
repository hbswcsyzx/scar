"""Reuse frozen metadata only; no eval context/92-op graph or source scan."""
import ast
import hashlib
import json
from pathlib import Path
import sys

BASE=Path(__file__).resolve().parent
ROOT=BASE.parents[3]
PARENT=BASE.parent/'candidate03'

def raw(v):return (json.dumps(v,ensure_ascii=False,sort_keys=True,indent=2)+'\n').encode()
def sha(b):return hashlib.sha256(b).hexdigest()
def stat_equal(row):
    p=Path(row['path']);s=p.stat()
    if p.is_symlink() or (s.st_size,s.st_mtime_ns,s.st_ctime_ns,s.st_ino,s.st_dev)!=(row['size'],row['mtime_ns'],row['ctime_ns'],row['inode'],row['device']):raise ValueError('parent frozen input stat changed')
def meta(path):
    b=path.read_bytes();s=path.stat()
    if path.is_symlink() or len(b)>4_000_000:raise ValueError('small parent metadata bound')
    return json.loads(b),{'path':str(path),'stored_bytes':len(b),'stored_sha256':sha(b),'decoded_bytes':len(b),'decoded_sha256':sha(b),'size':s.st_size,'mtime_ns':s.st_mtime_ns,'ctime_ns':s.st_ctime_ns,'inode':s.st_ino,'device':s.st_dev}
def source_ref(v):return (v['path'],v['fingerprint'],v['start_line'],v['end_line'],v['start_column'],v['end_column'])

def main():
    parent,pr=meta(PARENT/'freeze.json');selection,sr=meta(PARENT/'selection.json')
    failure,fr=meta(PARENT/'attempt03/failure.json');launch,lr=meta(PARENT/'attempt03/launch-result.json')
    if launch['exit_code']!=1 or failure['message']!='retained actual stored+decoded input budget exceeded, including repeated reads':raise ValueError('parent terminal evidence differs')
    source_rows=parent['production_sources']
    for r in source_rows:
        b=Path(r['path']).read_bytes()
        if len(b)!=r['bytes'] or sha(b)!=r['sha256']:raise ValueError('frozen12 source changed')
    rows=[];prior={};metadata_inputs=[pr,sr,fr,lr]
    for ordinal in (1,2):
        result,ref=meta(PARENT/f'attempt03/body-{ordinal:02d}-result.json');metadata_inputs.append(ref)
        matches=[r for r in selection['selected'] if r['definition']['id']==result['definition'] and r['definition']['source']==result['source']]
        if len(matches)!=1:raise ValueError('parent result has no exact qualified subject')
        subject=matches[0]
        kwargs=[g for g in result['gaps'] if g['detail'].startswith('CALL_EX_LOCAL_UNWIND_CONTRACT_UNVERIFIED:') and source_ref(g['source'])==source_ref(subject['frontier']['source'])]
        if not kwargs:raise ValueError('result did not return evidence of advancing original kwargs frontier')
        if result['status']=='REUSED_REVALIDATED_WITH_OPEN':
            if not result['checks']['public_structure']['roundtrip_equal'] or not result['checks']['independent_source_and_compiler']['source_shape_verified']:
                raise ValueError('prior first graph independent qualification missing')
        elif result['status']=='UNSUPPORTED':
            if result['artifact'] is not None or not result['gaps'] or result['gaps'][-1]['kind']!='UNSUPPORTED_SYNTAX':raise ValueError('prior later frontier missing')
        else:raise ValueError('unexpected handled kwargs result')
        prior[str(subject['original_sequence'])]={'subject':subject,'evidence':{'path':ref['path'],'sha256':ref['stored_sha256'],'bytes':ref['stored_bytes']},'result':result,'body_state':'OPEN','inherited_only':True}
    remaining=[r for r in selection['selected'] if str(r['original_sequence']) not in prior]
    if len(selection['selected'])!=4 or len(remaining)!=2:raise ValueError('original four/remaining two denominator differs')
    file_indexes={r['file_index'] for r in remaining}
    if len(file_indexes)!=1:raise ValueError('remaining work is not one exact retained source file')
    # Keep the original21 receipts/stat pins. They do not authorize opening
    # unneeded payloads or constitute new read/semantic qualification.
    original=selection['reused_artifacts']
    dropped={v[k]['path'] for v in original.values() for k in ('artifact','producer_freeze','body_inputs')}
    inputs=[r for r in parent['inputs'] if r['path'] not in dropped]
    if len(inputs)!=21:raise ValueError('original21 metadata pin set differs')
    for row in inputs:stat_equal(row)
    by_path={r['path']:r for r in inputs}
    by_path.update({r['path']:r for r in metadata_inputs})
    new={**selection,'status':'PREPARED_REMAINING_ONLY_NO_BODY_LOWERING','scope_subjects':selection['selected'],
         'parent_scope':{'freeze':{'path':pr['path'],'sha256':pr['stored_sha256'],'bytes':pr['stored_bytes']},'selection':{'path':sr['path'],'sha256':sr['stored_sha256'],'bytes':sr['stored_bytes']},'run':selection['run'],'subject_count':4,'prior_window_terminal':{'path':lr['path'],'sha256':lr['stored_sha256'],'bytes':lr['stored_bytes']}},
         'prior_outcomes':prior,'selected':remaining,'files':{str(fi):selection['files'][str(fi)] for fi in file_indexes},'reused_artifacts':{},
         'new_body_lowering_sequences':[r['original_sequence'] for r in remaining],
         'remaining_selection_rule':'original four exact AST/SG predicate subjects minus exact prior returned kwargs-handling subjects; no function-name rule',
         'previous_window_not_lowered':{'current_subject':selection['selected'][failure['current_body']-1],'reason':failure['message'],'new_operations_emitted':failure['emitted_cost_for_unreturned_current_body']}}
    with (BASE/'selection.json').open('xb') as f:f.write(raw(new))
    candidates=[]
    for path in sorted((ROOT/'scar').rglob('*.py')):
        b=path.read_bytes();candidates.append({'path':str(path),'bytes':len(b),'sha256':sha(b)})
    fixed=[]
    for path in (BASE/'prepare_remaining.py',BASE/'run_gate.py',BASE/'gate_guards.py',BASE/'selection.json',Path(sys.executable).resolve(),Path('/usr/bin/time')):
        b=path.read_bytes();fixed.append({'path':str(path),'bytes':len(b),'sha256':sha(b)})
    freeze={**parent,'candidate':'candidate04_remaining','status':'FROZEN_NOT_EXECUTED','production_sources':source_rows,'candidate_scar_sources':candidates,'small_frozen_files':fixed,'inputs':sorted(by_path.values(),key=lambda r:r['path']),'attempt':str(BASE/'attempt04'),'parent_scope':new['parent_scope'],'active_subjects':len(remaining),'full_parent_subjects':4,'actual_source_files':1,'reuse_policy':'no old graph read; inherit two exact prior result records; only remaining two bodies may lower','remaining_selection_rule':new['remaining_selection_rule']}
    with (BASE/'freeze.json').open('xb') as f:f.write(raw(freeze))
    print(json.dumps({'status':'FROZEN_NOT_RUN','freeze_sha256':sha((BASE/'freeze.json').read_bytes()),'remaining_sequences':new['new_body_lowering_sequences'],'full_subjects':4,'active_files':len(file_indexes),'input_pins':len(by_path),'no_source_payloads_opened':True},sort_keys=True))

if __name__=='__main__':main()
