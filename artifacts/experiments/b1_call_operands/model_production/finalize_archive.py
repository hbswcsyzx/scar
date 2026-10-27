"""Seal already completed evidence; do not launch tests or providers."""
from collections import Counter
import hashlib
import json
from pathlib import Path
import subprocess

HERE = Path(__file__).resolve().parent
ROOT = HERE.parents[3]
PREVIOUS = HERE.parent / 'model_content'


def read(path):
    return json.loads(path.read_text())


def dump(path, document):
    path.write_text(json.dumps(document, indent=2, ensure_ascii=False) + '\n')


def main():
    full = read(HERE / 'full/report.json')
    component = read(HERE / 'component/final/report.json')
    assert full['status'] == component['status'] == 'PASS'
    before, after = (read(HERE / f'full/source.{phase}.json') for phase in ('before', 'after'))
    assert before == after and not before['worktree_status']
    old_source = read(PREVIOUS / 'full/source.before.json')
    old_cases, new_cases = (read(base / 'full/cases.json') for base in (PREVIOUS, HERE))
    identity = lambda case: (case['class'],case['name'])
    old_set, new_set = ({identity(row) for row in rows} for rows in (old_cases,new_cases))
    added = [row for row in new_cases if identity(row) not in old_set]
    preservation = {
        'preserved_previous_cases':len(old_set & new_set),
        'missing_cases':sorted(old_set-new_set), 'new_cases':added,
        'new_cases_by_class':dict(sorted(Counter(row['class'] for row in added).items())),
        'previous_source_files':len(old_source['files']),
        'new_source_files':sorted(set(before['files'])-set(old_source['files'])),
        'removed_source_files':sorted(set(old_source['files'])-set(before['files'])),
        'changed_previous_source_files':[p for p,h in old_source['files'].items() if before['files'].get(p)!=h],
        'unchanged_previous_source_files':sum(before['files'].get(p)==h for p,h in old_source['files'].items()),
        'previous_fixtures':len(old_source['fixture_sha256']),
        'current_fixtures':len(before['fixture_sha256']),
        'changed_previous_fixtures':[p for p,h in old_source['fixture_sha256'].items() if before['fixture_sha256'].get(p)!=h],
        'current_fixtures_unchanged':before['fixture_sha256']==after['fixture_sha256'],
    }
    dump(HERE / 'preservation.json',preservation)
    protected={}
    for label,path in [('lewm','/home/zyf/AAA/le-wm'),('scar_main','/home/zyf/AAA/scar')]:
        def git(*args):
            return subprocess.check_output(['git',*args],cwd=path,text=True).strip()
        protected[label]={'path':path,'head':git('rev-parse','HEAD'),'status':git('status','--porcelain=v1')}
    dump(HERE / 'protected.after.json',protected)
    documents=['README.md','docs/STATUS.md','docs/ROADMAP.md','docs/FIRST_STAGE_COMPLETION_MATRIX.md',
               'docs/WHOLE_PROGRAM_MODEL_PLAN.md','docs/M1_PRODUCTION_PLAN.md',
               'docs/M1_PRODUCTION_API.md','docs/M1_PRODUCTION_ACCEPTANCE.md']
    dump(HERE / 'closure.json',{
        'scope':'P declared source/write/production interfaces; native complete writer capture and V/R3/full M0-M2 remain open',
        'implementation_revision':before['revision'],'source_sha256':before['source_sha256'],
        'source_files':len(before['files']),'component_cases':477,'full_cases':len(new_cases),
        'component_seconds':component['duration_seconds'],'full_seconds':full['duration_seconds'],
        'source_runtime_verified':False,'readiness_verified':False,'transformation_authorized':False,
        'documents':{p:hashlib.sha256((ROOT/p).read_bytes()).hexdigest() for p in documents},
    })
    files={str(path.relative_to(HERE)):{'bytes':path.stat().st_size,
        'sha256':hashlib.sha256(path.read_bytes()).hexdigest()}
        for path in sorted(HERE.rglob('*')) if path.is_file() and path!=HERE/'manifest.json'}
    dump(HERE/'manifest.json',{'schema':'scar.production-interface-archive','schema_version':1,'files':files})
    print(json.dumps({'archived_files':len(files),'preservation':{k:v for k,v in preservation.items() if k!='new_cases'}},ensure_ascii=False))


if __name__=='__main__':
    main()
