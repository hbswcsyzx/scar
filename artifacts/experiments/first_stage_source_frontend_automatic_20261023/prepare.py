"""Freeze exact metadata/source-context/code-witness inputs; no SCAR import."""
import ast
import datetime
import gzip
from hashlib import sha256
import json
from pathlib import Path
import subprocess

HERE=Path(__file__).resolve().parent
ROOT=HERE.parents[2]
EX=HERE.parent
PUB=EX/'first_stage_source_publication_current_20261023/result/publication/manifest.json'
COMP=EX/'first_stage_source_publication_current_20261023/result/composition/index.json.gz'
SOURCE=EX/'first_stage_source_publication_current_attempt02_20261023/result/connections/source'
LAYERS=EX/'first_stage_source_context_20261022/result/source-layers'
STORE=EX/'first_stage_partitioned_operand_routes_20261023/result/code-witnesses'
ATT=EX/'first_stage_dependency_continuation_20261023/result/continuation.json'


def load(path):
    raw=path.read_bytes()
    return json.loads(gzip.decompress(raw) if path.suffix=='.gz' else raw)


def receipt(path):
    raw=path.read_bytes()
    return {'path':str(path.resolve()),'sha256':sha256(raw).hexdigest(),'bytes':len(raw)}


paths={PUB,COMP,SOURCE/'report.json',SOURCE/'bindings.json',ATT,LAYERS/'index.json'}
manifest=load(PUB)
for ref in [*manifest['files'],*manifest['components'].values(),manifest['parent_inventory']]:
    paths.add(Path(ref['uri']) if ref['external'] else PUB.parent/ref['uri'])
publication=load(PUB.parent/manifest['components']['publication']['uri'])['value']
paths.add(Path(publication['base_composition']['path']))
for row in load(LAYERS/'index.json')['files']:
    if row['status']=='STORED':paths.add(LAYERS/row['archive'])
paths.update(path for path in STORE.iterdir() if path.is_file())
attachment=load(ATT)
parent=EX/'first_stage_dependency_sources_20261023/result/admissions.json'
paths.add(parent)
input_doc={'schema':'scar.source-frontend-gate-inputs','schema_version':1,
    'inputs':[receipt(path) for path in sorted(paths)],'scope':'metadata, existing source contexts and owned code witnesses; no raw frame/native/105 dependency graph reread',
    'target_executed':False,'code_compiled':False,'first_stage_complete':False}
(HERE/'inputs.json').write_text(json.dumps(input_doc,indent=2)+'\n')
names=subprocess.check_output(['rg','--files','scar'],cwd=ROOT,text=True).splitlines()
sources=[ROOT/name for name in names if name.endswith('.py')]
for path in sources:ast.parse(path.read_bytes(),filename=str(path))
producer={'head':subprocess.check_output(['git','rev-parse','HEAD'],cwd=ROOT,text=True).strip(),
    'created_at_utc':datetime.datetime.now(datetime.timezone.utc).isoformat(),
    'candidate_sources':[receipt(path) for path in sorted(sources)],
    'scripts':[receipt(path) for path in sorted(HERE.glob('*.py'))]+[receipt(HERE/'run.sh')],
    'input_manifest':receipt(HERE/'inputs.json'),'all_candidate_ast_pass':True}
(HERE/'producer.json').write_text(json.dumps(producer,indent=2)+'\n')
report=load(SOURCE/'report.json')
(HERE/'preflight-interface.json').write_text(json.dumps({'prior_module_sha256':'f34938b5f758d8f11517a16ee0a276d638e9efe4daeca56903e6d5ceba4345ec',
    'actual_module':receipt(ROOT/'scar/analysis/source_frontend_worklist.py'),
    'source_report':receipt(SOURCE/'report.json'),'public_summary_counter':'invocations',
    'public_invocations':report['summary']['invocations'],'legacy_entered_invocations_field_present':'entered_invocations' in report['summary'],
    'correction_before_actual_plan':True,'guard_relaxed':False},indent=2)+'\n')
print(json.dumps({'inputs':len(paths),'stored_input_bytes':sum(row['bytes'] for row in input_doc['inputs']),
    'producer_sha256':receipt(HERE/'producer.json')['sha256'],'module_sha256':receipt(ROOT/'scar/analysis/source_frontend_worklist.py')['sha256']}))
