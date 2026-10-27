"""ONE bounded automatic source frontend gate; no target or publication."""
from __future__ import annotations

from hashlib import sha256
import json
import os
from pathlib import Path
import resource
import shutil
import subprocess
import sys
import time
import traceback

HERE = Path(__file__).resolve().parent
ROOT = HERE.parents[2]
EX = HERE.parent
COMPOSITION = EX / 'first_stage_source_publication_current_20261023/result/composition/index.json.gz'
PUBLICATION = EX / 'first_stage_source_publication_current_20261023/result/publication/manifest.json'
SOURCE = EX / 'first_stage_source_publication_current_attempt02_20261023/result/connections/source'
LAYERS = EX / 'first_stage_source_context_20261022/result/source-layers'
ATTACHMENT = EX / 'first_stage_dependency_continuation_20261023/result/continuation.json'
STORE = EX / 'first_stage_partitioned_operand_routes_20261023/result/code-witnesses'
started = time.perf_counter()
log = (HERE / 'progress.jsonl').open('x', buffering=1)


def receipt(path):
    path = Path(path).resolve()
    raw = path.read_bytes()
    return {'path': str(path), 'sha256': sha256(raw).hexdigest(), 'bytes': len(raw)}


def write(event):
    log.write(json.dumps({'elapsed_s': time.perf_counter()-started,
        'pid': os.getpid(), 'max_rss_kib': resource.getrusage(resource.RUSAGE_SELF).ru_maxrss, **event})+'\n')


def verify_frozen_imports(final=False):
    frozen = json.loads((HERE/'producer.json').read_text())
    by_path = {row['path']: row for row in frozen['candidate_sources']}
    modules = []
    for name, module in sorted(sys.modules.items()):
        path = getattr(module, '__file__', None)
        if name.startswith('scar.') and path and Path(path).resolve().is_relative_to(ROOT):
            row = receipt(path)
            if by_path.get(row['path']) != row:
                raise ValueError('participating source drift: '+row['path'])
            modules.append(row)
    if final:
        folder=HERE/'participating-source-evidence';folder.mkdir(exist_ok=False)
        for row in modules:
            path=folder/(row['sha256']+'.py-source')
            if not path.exists():shutil.copyfile(row['path'],path)
        (HERE/'participating-producer.json').write_text(json.dumps({'modules':modules,
            'all_imported_sources_unchanged':True},indent=2)+'\n')


try:
    for row in json.loads((HERE/'inputs.json').read_text())['inputs']:
        if receipt(row['path']) != row: raise ValueError('input changed: '+row['path'])
    cache_before = [receipt(path) for path in sorted(STORE.iterdir()) if path.is_file()]
    (HERE/'cache-before.json').write_text(json.dumps(cache_before,indent=2)+'\n')
    write({'stage':'imports','status':'BEGIN'})
    from scar.analysis.code_witness import CodeWitnessStore,CodeWitnessBudget
    from scar.analysis.program_composition import CompositionIndex
    from scar.analysis.source_attachments import SourceAttachmentBudget
    from scar.analysis.source_frontend_worklist import SourceFrontendBudget,plan_source_frontend,run_source_frontend
    verify_frozen_imports()
    budget=SourceFrontendBudget(max_dispatch_bodies=12,max_source_files=4,max_operations_per_body=4000,
        max_total_operations=24000,max_elapsed_seconds=180,max_output_bytes=128_000_000,max_record_bytes=128_000_000)
    (HERE/'budget.json').write_text(json.dumps(budget.__dict__,indent=2)+'\n')
    comp=CompositionIndex(COMPOSITION,source_attachments=((str(ATTACHMENT),receipt(ATTACHMENT)['sha256']),),
        attachment_budget=SourceAttachmentBudget(max_record_bytes=128_000_000,max_artifact_bytes=2_200_000_000))
    store=CodeWitnessStore(STORE,budget=CodeWitnessBudget(max_compile_keys=20),create=False,compile_missing=False,progress=write)
    write({'stage':'plan','status':'BEGIN'})
    tick=time.perf_counter()
    plan=plan_source_frontend(comp,SOURCE,store,budget=budget,out_dir=HERE/'plan',progress=write)
    plan_seconds=time.perf_counter()-tick
    summary=plan.document['summary']
    if summary['bodies']!=2217 or summary['current_groups']!=817 or summary['current_calls']!=100438:
        raise ValueError('complete static/current denominator changed')
    if summary['body_statuses']['LOWERED_WITH_GAPS']!=842:raise ValueError('published body denominator changed')
    (HERE/'plan-summary.json').write_text(json.dumps(summary,indent=2)+'\n')
    write({'stage':'plan','status':'END','summary':summary,'seconds':plan_seconds})
    write({'stage':'worker','status':'BEGIN'})
    tick=time.perf_counter()
    result=run_source_frontend(plan,store,HERE/'worker',budget=budget,progress=write)
    worker_seconds=time.perf_counter()-tick
    write({'stage':'worker','status':'END','counts':result['counts'],'seconds':worker_seconds})
    if store.counts['compile_attempts']!=0:raise ValueError('unexpected code compilation')
    cache_after=[receipt(path) for path in sorted(STORE.iterdir()) if path.is_file()]
    (HERE/'cache-after.json').write_text(json.dumps(cache_after,indent=2)+'\n')
    if cache_after!=cache_before:raise ValueError('owned readonly witness archive bytes changed')
    verify_frozen_imports(final=True)
    final={'status':'AUTOMATIC_WINDOW_FINISHED_WITH_OPEN','plan_seconds':plan_seconds,'worker_seconds':worker_seconds,
        'elapsed_s':time.perf_counter()-started,'max_rss_kib':resource.getrusage(resource.RUSAGE_SELF).ru_maxrss,
        'plan_summary':summary,'worker':result,'code_witness_counts':store.counts,
        'code_witness_all_payloads_unchanged':True,'source_prepared':False,'code_compiled':False,
        'target_executed':False,'new_publication_performed':False,'current_run_integrated':False,'first_stage_complete':False}
    (HERE/'summary.json').write_text(json.dumps(final,indent=2)+'\n')
    write({'stage':'FINISHED','status':final['status']})
    print(json.dumps({'status':final['status'],'counts':result['counts'],'program_paths':result['program_paths'],
        'elapsed_s':final['elapsed_s'],'max_rss_kib':final['max_rss_kib']}))
except BaseException as error:
    (HERE/'failure.json').write_text(json.dumps({'status':'FAILED_RETAINED_NO_RETRY','type':type(error).__name__,
        'detail':str(error),'traceback':traceback.format_exc(),'elapsed_s':time.perf_counter()-started},indent=2)+'\n')
    write({'stage':'FAILED','type':type(error).__name__,'detail':str(error)})
    raise
finally:
    log.close()
