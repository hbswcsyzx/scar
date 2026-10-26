"""Metadata + exact archived text ranking. No graph, CodeType or worker."""
from collections import Counter
from dataclasses import asdict
from pathlib import Path
import ast, hashlib, json
from common import HERE, ROOT, OLD, OBSERVER, canonical, need, receipt, save, normal_inputs, worker_budget


def shape(node, formals):
    gaps = []
    if node.handlers and node.finalbody: gaps.append('COMBINED_HANDLER_FINALLY')
    if len(node.handlers) > 1 or any(h.name for h in node.handlers): gaps.append('MULTIPLE_OR_AS_HANDLERS')
    for child in ast.walk(node):
        if child is not node and isinstance(child, (ast.Try, ast.TryStar, ast.Return, ast.Break,
                ast.Continue, ast.Yield, ast.YieldFrom, ast.Await)):
            gaps.append('TRANSFER_OR_NESTED:' + type(child).__name__)
    for h in node.handlers:
        if h.type is not None and not (isinstance(h.type, ast.Name) and h.type.id in formals):
            gaps.append('HANDLER_EXPRESSION_SOURCE_PROTOCOL')
    return sorted(set(gaps))


def main():
    need(not (HERE/'freeze.json').exists() and not (HERE/'result').exists(), 'fresh preparation required')
    oldfreeze=json.loads((OLD/'freeze.json').read_bytes()); config=json.loads((OLD/'inputs.json').read_bytes())
    ledger_path=OLD/'result/entry-ledger.json'; ledger=json.loads(ledger_path.read_bytes())
    need(ledger['current_entry_statuses']=={'SUCCEEDED':63,'UNSUPPORTED':49,'FAILED':17,'PENDING_NOT_STARTED':80}, 'original terminal snapshot differs')
    inputs={r['path']:r for r in oldfreeze['inputs']}; inputs[str(ledger_path)]=receipt(ledger_path)
    inputs[str(OLD/'run.py')]=receipt(OLD/'run.py'); inputs[str(OLD/'freeze.json')]=receipt(OLD/'freeze.json')
    attempts=[]; unsupported=[]
    for row in ledger['entries']:
        if row['status']!='UNSUPPORTED': continue
        terminal=Path(row['public_terminal']); saved=terminal.parent/'returned-metadata.json'
        for path in (terminal,saved): inputs[str(path)]=receipt(path)
        record=json.loads(saved.read_bytes()); gaps=[g for g in record['metadata']['gaps']
            if g['detail']=='structured control/effect protocol still required for Try']
        unsupported.append({'entry_key':row['entry_key'],'historical_calls':row['historical_calls'],
            'original_terminal':receipt(terminal),'returned_metadata':receipt(saved),
            'prior_gaps':record['metadata']['gaps']})
        if gaps: attempts.append((row,record,gaps[0]))
    need(attempts, 'no original Try frontier to select')
    paths=sorted(set((ROOT/'scar').rglob('*.py'))|{ROOT/'sitecustomize.py'}|set(HERE.glob('*.py')))
    for path in paths: ast.parse(path.read_bytes(), filename=str(path))
    freeze={'schema':'scar.function-try-real-entry-freeze/1','head_label':'991c090a','code_root':str(ROOT),
        'sources':[receipt(p)for p in paths],'runtime':oldfreeze['runtime'],'inputs':list(inputs.values()),
        'archive_members':oldfreeze['archive_members'],'graph_declarations':[],
        'source_count':len(list((ROOT/'scar').rglob('*.py'))),'runtime_scope':oldfreeze['runtime_scope']}
    config['budgets']={'max_input_stored_plus_decoded_bytes':4_000_000_000,
        'max_output_stored_bytes':512_000_000,'max_record_bytes':128_000_000,
        'max_graph_decoded_per_batch':300_000_000,'AS_bytes':4*1024**3,'outer_seconds':1200}
    observer=OBSERVER.Driver(config,freeze);observer.output=HERE/'prepared-metadata';observer.output.mkdir()
    observer.install_readers()
    from scar.analysis.source_attachments import SourceAttachments
    from scar.analysis.code_witness import CodeWitnessStore
    from scar.ir.record_codec import decode
    from scar.ir.semantics_v2 import SourceSnapshot
    def forbidden(*args,**kw):raise AssertionError('prepare forbids graph/CodeType/compile/lower/worker')
    SourceAttachments._view=forbidden;CodeWitnessStore.resolve=forbidden
    owner,archives,catalog,metadata=normal_inputs(config,observer)
    candidates={r['entry_key']:r for r in metadata['candidates']}
    oldplan=json.loads(Path(config['read_plan']['path']).read_bytes())
    files={f['file_key']:f for b in oldplan['batches']for f in b['file_groups']}
    trees={}; ranked=[]
    for old,record,gap in attempts:
        candidate=candidates[old['entry_key']];snapshot=candidate['basis']['source_snapshot']
        need(candidate['status']=='CANDIDATE_SOURCE_GRAPH_UNVERIFIED','old Try candidate not currently metadata-ready')
        if candidate['file_key']not in trees:
            store=archives.store_for(candidate['archive_variants'][0]['store'])
            text=store.text(decode(SourceSnapshot,snapshot));trees[candidate['file_key']]=ast.parse(text,filename=snapshot['path'])
        tree=trees[candidate['file_key']];source=candidate['basis']['source']
        def span(n):return (n.lineno,n.end_lineno,n.col_offset,n.end_col_offset)
        def source_span(s):return(s['start_line'],s['end_line'],s['start_column'],s['end_column'])
        definitions=[n for n in ast.walk(tree)if isinstance(n,(ast.FunctionDef,ast.AsyncFunctionDef))and span(n)==source_span(source)]
        tries=[n for n in ast.walk(tree)if isinstance(n,ast.Try)and span(n)==source_span(gap['source'])]
        need(len(definitions)==len(tries)==1,'original function/Try source does not resolve uniquely in archived AST')
        definition,node=definitions[0],tries[0];a=definition.args
        formals={x.arg for x in (*a.posonlyargs,*a.args,*a.kwonlyargs)}|{x.arg for x in (a.vararg,a.kwarg)if x}
        gaps=shape(node,formals);later=[]
        for child in ast.walk(definition):
            if getattr(child,'lineno',0)<=node.end_lineno:continue
            if isinstance(child,ast.Call)and(any(isinstance(v,ast.Starred)for v in child.args)or any(k.arg is None for k in child.keywords)):
                later.append({'type':'EXTENDED_CALL_LIFETIME','line':child.lineno})
            elif isinstance(child,(ast.Set,ast.ListComp,ast.DictComp,ast.SetComp,ast.GeneratorExp,
                                   ast.FunctionDef,ast.With,ast.AsyncWith,ast.Import,ast.ImportFrom,ast.AugAssign)):
                later.append({'type':type(child).__name__,'line':child.lineno})
        ranked.append({'entry_key':old['entry_key'],'historical_calls':old['historical_calls'],
            'file_key':candidate['file_key'],'original_candidate':candidate,
            'original_terminal':receipt(Path(old['public_terminal'])),'prior_try_gap':gap,
            'try_shape': 'FINALLY'if node.finalbody else 'EXCEPT','try_shape_frontiers':gaps,
            'later_AST_frontier_candidates_not_runtime_proof':later})
    ranked.sort(key=lambda r:(bool(r['try_shape_frontiers']),len(r['try_shape_frontiers']),
        len(r['later_AST_frontier_candidates_not_runtime_proof']),-r['historical_calls'],r['entry_key']))
    selected=ranked[:4]; selected_files={r['file_key']:files[r['file_key']]for r in selected}
    need(sum(f['source_graph']['declaration']['canonical_bytes']for f in selected_files.values())<=300_000_000,'selected graph declaration exceeds proposed window')
    need(sum(f['source_text']['normalized_bytes']for f in selected_files.values())<=1_000_000,'selected source declaration exceeds proposed window')
    from scar.analysis.source_frontend_worklist import plan_source_entries
    from scar.ir.program.source_language import SourceLanguageCapability as C
    capabilities=tuple(C(v)for v in oldplan['old_producer_and_capabilities']['capabilities'])+(C.FUNCTION_TRY_314_V1,)
    keys=tuple(r['entry_key']for r in selected)
    plan=plan_source_entries(catalog,budget=worker_budget(),capabilities=capabilities,
        eligible_entry_keys=keys,dispatch_order='FILE_GROUPED_V1')
    ordered=[r['entry_key']for r in plan.dispatch];need(set(ordered)==set(keys),'normal planner narrowed selected Try keys')
    selected=sorted(selected,key=lambda r:ordered.index(r['entry_key']))
    readplan={'schema':'scar.function-try-archived-entry-read-plan/1','classification_scope':'metadata/archived AST heuristic only; ordinary worker decides all actual support',
        'ranking':'supported original Try shape first, then fewer shape frontiers, fewer later known AST frontier candidates, calls-desc/key; no package/function filter',
        'full_groups':817,'full_calls':100438,'source_candidates':243,
        'original_source209_ledger':receipt(ledger_path),'all49_original_unsupported_retained':unsupported,
        'all_original_try_entries':ranked,'try_entry_count':len(ranked),'selected':selected,
        'selected_keys':ordered,'selected_files':list(selected_files.values()),
        'declarations':{'entries':len(selected),'files':len(selected_files),
            'historical_calls':sum(r['historical_calls']for r in selected),
            'source_bytes':sum(f['source_text']['normalized_bytes']for f in selected_files.values()),
            'graph_stored_bytes':sum(f['source_graph']['declaration']['compressed_bytes']for f in selected_files.values()),
            'graph_decoded_bytes':sum(f['source_graph']['declaration']['canonical_bytes']for f in selected_files.values()),
            'SP5_repeated_context_decoded_proxy_all_success':sum(files[r['file_key']]['source_graph']['declaration']['canonical_bytes']for r in selected)},
        'original_worker_gate':'FAILED_MISSING_ORIGINAL_FILE_RETAINED','publication_currentRun_binding_target':'NOT_RUN'}
    save(HERE/'READ_PLAN.json',readplan)
    config.update(schema='scar.function-try-real-entry-inputs/1',code_root=str(ROOT),code_head_label='991c090a',
        capabilities=[x.value for x in capabilities],selected_keys=ordered,read_plan=receipt(HERE/'READ_PLAN.json'),
        selection_source='original source209 Try UNSUPPORTED only; separate producer/capability attempt',public_worker_budget=asdict(worker_budget()))
    save(HERE/'inputs.json',config)
    for path in (HERE/'READ_PLAN.json',HERE/'inputs.json'):inputs[str(path)]=receipt(path)
    freeze['inputs']=list(inputs.values());freeze['budgets']=config['budgets']
    freeze['graph_declarations']=[{**f['source_graph']['declaration'],
        'declaration_relative_path':f['source_graph']['declaration']['path'],'path':f['source_graph']['path']}for f in selected_files.values()]
    need(owner.measurements().get('graph_artifacts_read',0)==0 and all(s.counts['module_loads']==s.counts['compile_attempts']==0 for s in archives._stores.values()),'preparation acquired graph/CodeType')
    check={'status':'PREPARED_NOT_RUN','normal_plan_dispatch':ordered,'metadata_IO_separate':observer.io(),
        'archive_counts_source_text_only':[s.counts for s in archives._stores.values()],
        'declared_window':readplan['declarations'],'all_Try_candidates':len(ranked),'graph_CodeType_compile_lower_worker':False}
    save(HERE/'PREPARE_CHECK.json',check);inputs[str(HERE/'PREPARE_CHECK.json')]=receipt(HERE/'PREPARE_CHECK.json');freeze['inputs']=list(inputs.values())
    for row in freeze['sources']:need(receipt(row['path'])==row,'consumer source changed during prepare')
    save(HERE/'freeze.json',freeze)
    print(json.dumps({'status':'PREPARED_NOT_RUN','freeze':receipt(HERE/'freeze.json'),'run':receipt(HERE/'run.py'),
        'window':readplan['declarations'],'try_count':len(ranked),'metadata_IO':observer.io(),
        'selected_shapes':[{'entry_key':r['entry_key'],'source':r['prior_try_gap']['source']['path'],
            'line':r['prior_try_gap']['source']['start_line'],'shape':r['try_shape'],'frontiers':r['try_shape_frontiers'],
            'later':r['later_AST_frontier_candidates_not_runtime_proof']}for r in selected]},sort_keys=True),flush=True)

if __name__=='__main__':main()
