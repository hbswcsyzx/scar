"""One normal twelve-ADD publication -> composer; no redundant third graph read."""
import ast
from hashlib import sha256
import json
from pathlib import Path
import pickle
import resource
import signal
import sys
import time
import traceback

HERE = Path(__file__).resolve().parent
ROOT = HERE.parents[2]
sys.path.insert(0, str(ROOT))
WINDOW = HERE.parent / 'source_frontend_remainder_attempt02_20261025'
PARENT = HERE.parent / 'source_call_kwargs_publication_20261025/result/composition/index.json.gz'
STORE = HERE.parent / 'first_stage_partitioned_operand_routes_20261023/result/code-witnesses'

def canonical(value):
    return json.dumps(value, sort_keys=True, ensure_ascii=False, separators=(',', ':'), allow_nan=False).encode()

def need(value, message):
    if not value:
        raise ValueError(message)

def receipt(path):
    path = Path(path).resolve(); digest = sha256(); size = 0
    with path.open('rb') as stream:
        for block in iter(lambda: stream.read(65536), b''):
            digest.update(block); size += len(block)
    return {'path': str(path), 'sha256': digest.hexdigest(), 'bytes': size}

def save(name, value):
    with (HERE / name).open('xb') as stream:
        stream.write(canonical(value) + b'\n')

class Deadline(BaseException):
    pass

def main():
    started = time.perf_counter()
    freeze = json.loads((HERE/'freeze.json').read_text())  # Created only after owner fixes/root approval.
    need(receipt(__file__) == freeze['entry'], 'publication entry changed')
    log = (HERE/'progress.jsonl').open('x', buffering=1)
    def progress(row):
        log.write(json.dumps({'elapsed_s':time.perf_counter()-started,
            'max_rss_kib':resource.getrusage(resource.RUSAGE_SELF).ru_maxrss, **row})+'\n')
    def timer(*_):
        if time.perf_counter()-started >= 1800: raise Deadline('publication outer1800s exhausted')
        progress({'stage':'HEARTBEAT'})
    signal.signal(signal.SIGALRM,timer); signal.setitimer(signal.ITIMER_REAL,10,10)
    try:
        for category in ('sources','runtime','inputs'):
            for row in freeze[category]: need(receipt(row['path'])==row, 'frozen '+category+' changed: '+row['path'])
        from scar.analysis.code_witness import CodeWitnessBudget, CodeWitnessStore
        from scar.analysis.inventory_partitions import InventoryPartitions
        from scar.analysis.program_composition import CompositionIndex, compose_source_publication
        from scar.analysis.source_program_publication import plan_source_body_publication, publish_source_body_revisions
        from scar.ir.record_codec import decode
        from scar.ir.semantics_v2 import SourceSnapshot

        programs = json.loads((WINDOW/'successful-programs.json').read_text())['graphs']
        need(len(programs)==12 and sum(row['retained_call_weight'] for row in programs)==179,
             'original successful artifact inventory differs')
        paths=tuple(row['program']['uri'] for row in programs)
        store = CodeWitnessStore(STORE,budget=CodeWitnessBudget(max_compile_keys=20),create=False,compile_missing=False)
        before_store=[receipt(path) for path in sorted(STORE.iterdir()) if path.is_file()]
        texts={}
        for row in programs:
            original=json.loads((WINDOW/'worker'/f"attempt-{row['sequence']:05d}"/'result.json').read_text())
            need(original['status']=='SUCCEEDED' and original['program']==row['program'], 'original success receipt differs')
            snapshot=decode(SourceSnapshot,original['work_input']['snapshot'])
            text=store.text(snapshot)
            need(snapshot.path not in texts or texts[snapshot.path]==text, 'source-text namespace conflict')
            texts[snapshot.path]=text
        progress({'stage':'PARENT_846','status':'BEGIN'})
        parent=CompositionIndex(PARENT)
        need(parent.inventory.manifest['counts']['graph_bodies']==846, 'strict publication parent is not846')
        origin=parent.original_code_source_origin()
        plan=plan_source_body_publication(parent,paths,max_programs=12,max_record_bytes=128_000_000)
        need(len(plan.document['expectations'])==12 and all(row['operation']=='ADD_GRAPH' for row in plan.document['expectations']),
             'normal exact-parent ADD plan differs')
        need(len({row['file_index'] for row in plan.document['expectations']})==7, 'source-file inventory differs')
        save('plan.json',{'sha256':plan.sha256,'document':plan.document})
        progress({'stage':'PUBLICATION','status':'BEGIN'})
        publication=publish_source_body_revisions(parent,plan,HERE/'result/publication',code_witnesses=store,
            max_programs=12,max_changed_sources=7,max_operations_per_body=4000,max_record_bytes=128_000_000,progress=progress)
        save('publication-result.json',publication)

        # Observe the actual existing ordinary-reader returns inside composer.
        # This invokes the unchanged method once, without adding a validator,
        # cache, prepared token or independent authority.
        original_reader=InventoryPartitions.typed_body
        manifest_path=Path(publication['manifest']).resolve(); observed=[]
        def record_reader(inventory,fi,bi,**kwargs):
            body=original_reader(inventory,fi,bi,**kwargs)
            if inventory.path.resolve()==manifest_path:
                need(kwargs.get('source_texts')==texts, 'composer omitted exact archived source_texts')
                observed.append({'file_index':fi,'body_index':bi,'namespace':body.namespace,
                    'definition':body.body.definition.wire,'graph_operations':len(body.body.graph.operations),
                    'public_graph_validated':body.public_graph_validated,
                    'public_language_structure_validated':body.public_language_structure_validated})
                progress({'stage':'COMPOSER_ORDINARY_READER','status':'PASS','file_index':fi,'body_index':bi})
            return body
        InventoryPartitions.typed_body=record_reader
        try:
            composed=compose_source_publication(parent,publication['manifest'],HERE/'result/composition',
                max_record_bytes=128_000_000,max_output_bytes=256_000_000,source_texts=texts,progress=progress)
        finally:
            InventoryPartitions.typed_body=original_reader
        save('compose-result.json',composed);save('composer-reader-returns.json',observed)
        expected=[(row['file_index'],row['body_index']) for row in plan.document['expectations']]
        need([(row['file_index'],row['body_index']) for row in observed]==expected,
             'composer ordinary-reader coverage differs')
        progress({'stage':'NEW_ROOT_METADATA','status':'BEGIN'})
        current=CompositionIndex(HERE/'result/composition/index.json.gz')
        inventory=current.inventory
        need(inventory.manifest['counts']['graph_bodies']==858 and len(current.document['files'])==151
             and sum(len(row['bodies']) for row in current.document['files'])==2217, 'new root denominator differs')
        need(current.original_code_source_origin()==origin, 'strict original compiler/source origin changed')
        refs=[]
        for expected, seen in zip(plan.document['expectations'],observed):
            fi,bi=expected['file_index'],expected['body_index']
            file=inventory.file(fi);checkpoint=inventory.checkpoint(file['bodies'][bi]['checkpoint'])
            attachment=current.document['files'][fi]['bodies'][bi]
            need(checkpoint['source_program']==expected['replacement'] and attachment['namespace']==seen['namespace'],
                 'original artifact URI/namespace changed')
            need(checkpoint['construction_operations'] is None and not checkpoint['construction_cost_known'],
                 'CP2 construction cost was guessed from graph size')
            refs.append({'file_index':fi,'body_index':bi,'source_program':checkpoint['source_program'],
                'namespace':seen['namespace'],'checkpoint':file['bodies'][bi]['checkpoint']})
        need(not store.counts['compile_attempts'] and before_store==[receipt(path) for path in sorted(STORE.iterdir()) if path.is_file()],
             'readonly witness archive changed or compiled')
        frozen={row['path']:row for row in freeze['sources']+freeze['runtime']}
        actual_imports=[]
        for module in tuple(sys.modules.values()):
            filename=getattr(module,'__file__',None)
            if filename and Path(filename).is_file():
                path=Path(filename).resolve()
                if path.is_relative_to(ROOT/'scar') or not path.is_relative_to(ROOT):
                    row=receipt(path);need(frozen.get(str(path))==row,'participating source/runtime not frozen: '+str(path))
                    if row not in actual_imports: actual_imports.append(row)
        save('actual-imports.json',actual_imports)
        save('result.json',{'status':'PUBLISHED_WITH_OPEN','manifest_counts':inventory.manifest['counts'],
            'header_summary':inventory.component('header')['summary'],'original_compiler_origin_preserved':True,
            'parent':parent.index_receipt,'composition':receipt(HERE/'result/composition/index.json.gz'),
            'manifest':receipt(publication['manifest']),'active_graph_references':refs,
            'composer_ordinary_reader_returns':len(observed),'redundant_third_graph_decode_performed':False,
            'code_witness_counts':dict(store.counts),'potential_call_weight':179,'current_runtime_increment_measured':False,
            'complete_runtime_snapshot_bodies':843,'source_lowered':False,'raw_read':False,'target_executed':False,
            'source_prepared':False,'combined_io_accounting':'OPEN','whole_first_stage_established':False,
            'elapsed_s':time.perf_counter()-started,'max_rss_kib':resource.getrusage(resource.RUSAGE_SELF).ru_maxrss})
        progress({'stage':'FINISHED','status':'PUBLISHED_WITH_OPEN'})
    except BaseException as error:
        save('failure.json',{'type':type(error).__name__,'detail':str(error),'traceback':traceback.format_exc(),
            'elapsed_s':time.perf_counter()-started,'artifacts_retained':True,'rerun_or_relower_performed':False})
        raise
    finally:
        signal.setitimer(signal.ITIMER_REAL,0);log.close()

if __name__=='__main__':
    main()
