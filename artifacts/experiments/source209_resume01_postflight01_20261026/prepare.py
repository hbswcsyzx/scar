"""Pin existing small outcomes; never decode/checksum a program payload here."""
from pathlib import Path
import ast, hashlib, json
HERE=Path(__file__).resolve().parent
ROOT=HERE.parent
OLD=ROOT/'source209_model_20261026'
RESUME=ROOT/'source209_resume01_20261026'
MAIN=Path('/home/zyf/AAA/scar-worktrees/structured-program-model')

def ref(path,**extra):
    raw=path.read_bytes()
    return {'path':str(path.resolve()),'bytes':len(raw),'sha256':hashlib.sha256(raw).hexdigest(),**extra}

def main():
    if(HERE/'freeze.json').exists():raise ValueError('fresh postflight freeze required')
    a=json.loads((OLD/'result/entry-ledger.json').read_bytes());b=json.loads((RESUME/'result/entry-ledger.json').read_bytes())
    allrows={r['public_terminal']:r for r in a['entries']+b['entries']if 'public_terminal'in r}
    if len(allrows)!=226:raise ValueError('original226 public terminal history differs')
    fixed=json.loads((RESUME/'freeze.json').read_bytes()); missing=[]
    for r in fixed['inputs']:
        p=Path(r['path'])
        if not p.is_file():missing.append(r);continue
        if ref(p)!=r:raise ValueError('original input SHA/size differs: '+str(p))
    if missing:raise ValueError('restore original fixed pins first: '+json.dumps(missing))
    for p in HERE.glob('*.py'):ast.parse(p.read_bytes(),filename=str(p))
    config={'schema':'scar.source209-postflight-freeze/1','postflight_sources':[ref(p)for p in sorted(HERE.glob('*.py'))],
        'original_freeze':ref(OLD/'freeze.json'),'resume_freeze':ref(RESUME/'freeze.json'),
        'original_ledger':ref(OLD/'result/entry-ledger.json'),'resume_ledger':ref(RESUME/'result/entry-ledger.json'),
        'original_terminal':ref(OLD/'result/terminal.json'),'resume_terminal':ref(RESUME/'result/terminal.json'),
        'public_terminals':[ref(Path(path),entry_key=row['entry_key'])for path,row in sorted(allrows.items())],
        'early_terminal_receipts':json.loads((RESUME/'inputs.json').read_bytes())['old_terminal_receipts'],
        'original_missing_continuation_detail':"[Errno 2] No such file or directory: '"+str(MAIN/'artifacts/experiments/first_stage_dependency_continuation_20261023/result/continuation.json')+"'",
        'restoration_receipt':ref(MAIN/'artifacts/experiments/source209_workspace_recovery_20261026/FINAL_CONTROL_RESTORE.json'),
        'budgets':{'stored_bytes':512_000_000,'JSON_bytes':32_000_000,'record_bytes':8_000_000,'output_bytes':8_000_000,'AS_bytes':1024**3,'wall_seconds':180},
        'worker_program_hash_read_or_decode_during_preparation':False,'original_gate_exit1_preserved':True}
    raw=json.dumps(config,sort_keys=True,ensure_ascii=False,separators=(',',':')).encode()+b'\n'
    with(HERE/'freeze.json').open('xb')as stream:stream.write(raw)
    print(json.dumps({'status':'PREPARED_NOT_RUN','freeze':ref(HERE/'freeze.json'),'run':ref(HERE/'run.py'),'history_records':len(allrows),'original_inputs_checked':len(fixed['inputs']),'original_input_bytes':sum(r['bytes']for r in fixed['inputs'])}),flush=True)
if __name__=='__main__':main()
