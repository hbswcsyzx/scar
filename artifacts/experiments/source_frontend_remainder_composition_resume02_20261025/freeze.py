"""Freeze the composer-only consumer; SHA receipts, no graph decode."""
import argparse
from hashlib import sha256
import json
from pathlib import Path
import pickle
import sys

HERE=Path(__file__).resolve().parent
ROOT=HERE.parents[2]
sys.path.insert(0,str(ROOT))
WINDOW=HERE.parent/'source_frontend_remainder_attempt02_20261025'
ORIGINAL=HERE.parent/'source_frontend_remainder_publication_20261025'
PREVIOUS=HERE.parent/'source_frontend_remainder_composition_resume01_20261025'

def receipt(path):
    path=Path(path).resolve();digest=sha256();size=0
    with path.open('rb') as stream:
        for block in iter(lambda:stream.read(65536),b''):digest.update(block);size+=len(block)
    return {'path':str(path),'sha256':digest.hexdigest(),'bytes':size}

def main():
    parser=argparse.ArgumentParser();parser.add_argument('--head-label',required=True);args=parser.parse_args()
    import scar.analysis.code_witness
    import scar.analysis.program_composition
    import scar.analysis.source_program_publication
    graphs=json.loads((WINDOW/'successful-programs.json').read_text())['graphs']
    assert len(graphs)==12
    paths={WINDOW/name for name in ('successful-programs.json','terminal-receipt.json','result.json','freeze.json')}
    paths.update(HERE/name for name in ('run.py','README.md','freeze.py'))
    paths.update(ORIGINAL/name for name in ('run.py','freeze.json','failure.json','plan.json','publication-result.json'))
    paths.update(PREVIOUS/name for name in ('run.py','freeze.json','failure.json','producer-separation.json'))
    paths.update(path for path in (ORIGINAL/'result/publication').rglob('*') if path.is_file())
    paths.add(HERE.parent/'source_call_kwargs_publication_20261025/result/composition/index.json.gz')
    paths.add(HERE.parent/'source_call_kwargs_publication_20261025/result/publication/manifest.json')
    for row in graphs:
        paths.add(Path(row['program']['uri']))
        paths.add(WINDOW/'worker'/f"attempt-{row['sequence']:05d}"/'result.json')
    store=HERE.parent/'first_stage_partitioned_operand_routes_20261023/result/code-witnesses'
    paths.update(path for path in store.iterdir() if path.is_file())
    runtime={Path(row['path']) for row in json.loads((WINDOW/'freeze.json').read_text())['runtime']}
    for module in tuple(sys.modules.values()):
        filename=getattr(module,'__file__',None)
        if filename and Path(filename).is_file() and not Path(filename).resolve().is_relative_to(ROOT):
            runtime.add(Path(filename).resolve())
    document={'schema':'scar.existing-source-publication-consumer-freeze','schema_version':1,
        'head_label_supplied_by_root':args.head_label,'entry':receipt(HERE/'run.py'),
        'sources':[receipt(path) for path in sorted((ROOT/'scar').rglob('*.py'))],
        'runtime':[receipt(path) for path in sorted(runtime)],
        'inputs':[receipt(path) for path in sorted(paths)],
        'source_runtime_payload_copies':0,'graph_decodes':0,'plan_lower_publish_executed':False,
        'original_failed_gate_retained':True,'new_consumer_only':True}
    with (HERE/'freeze.json').open('x') as stream:
        json.dump(document,stream,sort_keys=True,ensure_ascii=False,separators=(',',':'));stream.write('\n')
    print(json.dumps({'freeze':receipt(HERE/'freeze.json'),'source_files':len(document['sources']),
        'runtime_files':len(document['runtime']),'input_files':len(document['inputs'])}))

if __name__=='__main__':main()
