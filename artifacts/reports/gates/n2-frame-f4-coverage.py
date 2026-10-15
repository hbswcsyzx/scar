"""Explain coverage-status changes using raw AST and new typed frame records."""
import ast
from collections import Counter
import gzip
import json
from pathlib import Path
import tokenize

root=Path.cwd()
folder=root/'artifacts/experiments/n2_frame_source_f4/real'
with gzip.open(root/'artifacts/reports/gates/n2-functions-lewm-inventory.json.gz','rt') as stream:
    old=json.load(stream)
with gzip.open(folder/'inventory.json.gz','rt') as stream:
    new=json.load(stream)
assert len(old['files'])==len(new['files'])
discards={json.dumps(transition['source'],sort_keys=True) for model in new['frames']
          for transition in model['transitions'] if set(transition)=={'operation','source','reference'}}
trees={};rows=[]
for old_file,new_file in zip(old['files'],new['files']):
    assert old_file['snapshot']==new_file['snapshot']
    assert len(old_file['coverage'])==len(new_file['coverage'])
    for before,after in zip(old_file['coverage'],new_file['coverage']):
        assert before['source']==after['source']
        if before==after:
            continue
        ref=before['source'];path=ref['path']
        span=(ref['start_line'],ref['end_line'],ref['start_column'],ref['end_column'])
        if path not in trees:
            with tokenize.open(path) as stream:
                trees[path]=ast.parse(stream.read(),filename=path)
        if before['status']=='CONNECTED' and after['status']=='INVENTORY_ONLY':
            nodes=[node.body[0].value for node in ast.walk(trees[path])
                   if isinstance(node,(ast.FunctionDef,ast.AsyncFunctionDef)) and node.body
                   and isinstance(node.body[0],ast.Expr) and isinstance(node.body[0].value,ast.Constant)
                   and type(node.body[0].value.value) is str]
            assert any((node.lineno,node.end_lineno,node.col_offset,node.end_col_offset)==span for node in nodes)
            reason='DECLARATION_DOCSTRING_NOT_CALL_TIME_VALUE'
        elif before['status']=='INVENTORY_ONLY' and after['status']=='CONNECTED':
            assert before['ast_kind']=='Expr' and json.dumps(ref,sort_keys=True) in discards
            reason='EXPRESSION_DISCARD_LIFETIME'
        else:
            raise AssertionError((before,after))
        rows.append({'source':ref,'ast_kind':before['ast_kind'],'old_status':before['status'],
                     'new_status':after['status'],'reason':reason})
report={'schema':'scar.frame-coverage-difference','schema_version':1,'changes':rows,
        'reason_counts':dict(Counter(row['reason'] for row in rows)),
        'old_connected':old['summary']['coverage_statuses']['CONNECTED'],
        'new_connected':new['summary']['coverage_statuses']['CONNECTED'],
        'new_discard_sources_verified':True,'source_snapshots_and_atom_order_identical':True,
        'transformation_authorized':False}
assert report['reason_counts']=={'EXPRESSION_DISCARD_LIFETIME':5,'DECLARATION_DOCSTRING_NOT_CALL_TIME_VALUE':18}
(folder/'coverage-audit.json').write_text(json.dumps(report,indent=2,ensure_ascii=False)+'\n')
print(json.dumps({key:report[key] for key in ('reason_counts','old_connected','new_connected')}))
