"""Generic unchanged-source profile comparison from a prior inventory.

No program-specific function list, target import, graph patch or optimization.
The baseline's exact bytes are already archived/verified by the previous gate;
this run reuses its input settings and independently replays the new report.
"""
import argparse
from collections import Counter
import gzip
import hashlib
import json
from pathlib import Path
import resource
import subprocess
import time

from scar.analysis.program_inventory import ProgramInventory, inventory_program
from scar.cli import _call_json, _write_call_document
from scar.ir.program.expansion import ContextStoreBudget
from scar.ir.program.frames import FrameEnter, FrameExit
from scar.ir.program.model import LiteralOrigin, ReferenceValue, TerminatorKind
from scar.ir.program.runtime_sources import RuntimeTraceBudget


def sha(path):
    with Path(path).open('rb') as stream:
        return hashlib.file_digest(stream, 'sha256').hexdigest()


def save(path, value):
    _write_call_document(Path(path), value, max_bytes=256000000)


def git(root, *args):
    return subprocess.check_output(['git', '-C', str(root), *args], text=True).strip()


def source_hashes(root):
    return {str(p.relative_to(root)): sha(p) for folder in ('scar', 'tests', 'scripts')
            for p in sorted((root/folder).rglob('*.py'))} | {
                str(p.relative_to(root)):sha(p) for p in sorted((root/'gates').glob('*.json'))
            } | {name:sha(root/name) for name in ('pyproject.toml','sitecustomize.py')}


def frame_coverage(inventory):
    bodies = {body.definition: body for file in inventory.files for body in file.bodies if body.graph}
    ports = {body.definition: body for body in inventory.interfaces.bodies}
    transitions = Counter()
    payloads = Counter()
    rows = []
    for frame in inventory.frames:
        body = bodies[frame.definition]
        operations = {operation.id:operation for operation in body.graph.operations}
        values = {value.id:value for value in body.graph.values}
        formal_values = {formal.value for formal in ports[frame.definition].parameters}
        enters = [transition for transition in frame.transitions if isinstance(transition, FrameEnter)]
        assert len(enters) == 1 and len(enters[0].formals) == len(formal_values)
        counts = Counter(transition.kind.value for transition in frame.transitions)
        transitions.update(counts)
        local_payloads = Counter()
        for transition in frame.transitions:
            if not isinstance(transition, FrameExit):
                continue
            operation = operations[transition.completion]
            if operation.terminator.kind is not TerminatorKind.RETURN:
                continue
            uses = {use.id:use for use in operation.uses}
            value = values[uses[operation.terminator.values[0]].value]
            category = ('DIRECT_FORMAL_REFERENCE' if value.id in formal_values else
                        'LITERAL_REFERENCE' if isinstance(value.origin, LiteralOrigin) else
                        type(value.origin).__name__)
            assert isinstance(value, ReferenceValue)
            local_payloads[category] += 1
        payloads.update(local_payloads)
        rows.append({'definition':frame.definition.wire, 'region':frame.region.wire,
                     'source':{'path':frame.source.path,'line':frame.source.start_line},
                     'formal_holds':len(enters[0].formals), 'transitions':dict(counts),
                     'normal_payload_origin_kinds':dict(local_payloads),
                     'conditions_established':False,'transformation_authorized':False})
    return {'bodies':len(rows), 'transitions':dict(transitions),
            'normal_payload_origin_kinds':dict(payloads),'rows':rows}


def main():
    parser=argparse.ArgumentParser()
    parser.add_argument('--baseline',type=Path,required=True)
    parser.add_argument('--out',type=Path,required=True)
    args=parser.parse_args()
    out=args.out.resolve();out.mkdir(parents=True,exist_ok=False)
    baseline_path=args.baseline.resolve()
    old=_call_json(baseline_path)
    assert old['schema']=='scar.program-inventory' and old['schema_version']==4
    root=Path.cwd().resolve(); project=Path(old['discovery']['project_root'])
    hashes=source_hashes(root)
    snapshots={file['snapshot']['path']:sha(file['snapshot']['path']) for file in old['files']}
    before_git={'head':git(project,'rev-parse','HEAD'),'status':git(project,'status','--porcelain')}
    runtime=old['runtime_scope']
    runtime_budget=RuntimeTraceBudget(**runtime['trace']['budget'])
    context_budget=ContextStoreBudget(**old['expansion']['budget'])
    options=dict(old['budget'])
    options.update(project_root=str(project),source_roots=(old['discovery']['source_roots']
        if old['discovery']['root_mode']=='DECLARED' else ()),
        runtime_trace=runtime['trace']['manifest']['logical_path'], runtime_budget=runtime_budget,
        max_compile_attempts=runtime['max_compile_attempts'],context_budget=context_budget)
    settings={key:value for key,value in options.items() if key not in ('runtime_budget','context_budget')}
    settings.update(runtime_budget=old['runtime_scope']['trace']['budget'],context_budget=old['expansion']['budget'])
    metadata={'schema':'scar.frame-source-experiment','schema_version':1,'status':'RUNNING',
              'revision':git(root,'rev-parse','HEAD'),'baseline_path':str(baseline_path),
              'baseline_sha256':sha(baseline_path),'entry':old['discovery']['entry'],
              'options':settings,'target_git_before':before_git,'source_sha256_before':hashes,
              'target_executed':False,'transformation_authorized':False}
    save(out/'run.json',metadata)
    started=time.monotonic()
    generated=inventory_program(old['discovery']['entry'],**options)
    generated_s=time.monotonic()-started
    doc=generated.to_dict()
    assert doc['schema_version']==5
    save(out/'inventory.json.gz',doc)
    save(out/'progress.json',{'phase':'GENERATED','generated_s':generated_s,'summary':generated.summary()})
    ceilings=dict(old['budget'])
    started=time.monotonic()
    replayed=ProgramInventory.from_dict(doc,**ceilings,runtime_verification_budget=runtime_budget,
        max_compile_attempts=runtime['max_compile_attempts'],context_verification_budget=context_budget)
    replay_s=time.monotonic()-started
    assert replayed.to_dict()==doc
    assert replayed.runtime_scope.trace.manifest==generated.runtime_scope.trace.manifest
    assert doc['runtime_scope']['trace']['manifest']==runtime['trace']['manifest']
    after_git={'head':git(project,'rev-parse','HEAD'),'status':git(project,'status','--porcelain')}
    assert after_git==before_git
    assert source_hashes(root)==hashes
    assert all(sha(path)==digest for path,digest in snapshots.items())
    assert {file['snapshot']['path']:file['snapshot']['fingerprint'] for file in old['files']} == {
            file['snapshot']['path']:file['snapshot']['fingerprint'] for file in doc['files']}
    coverage=frame_coverage(replayed)
    old_bodies={body['definition']['wire'] for file in old['files'] for body in file['bodies'] if body['graph']}
    new_bodies={body.definition.wire for file in replayed.files for body in file.bodies if body.graph}
    metadata.update(status='REPLAYED',generated_s=generated_s,replay_s=replay_s,
        peak_rss_kib=resource.getrusage(resource.RUSAGE_SELF).ru_maxrss,target_git_after=after_git,
        source_unchanged=True,source_snapshots_unchanged=True,trace_unchanged=True,
        baseline_summary=old['summary'],summary=replayed.summary(),frame_coverage=coverage,
        body_difference={'retained':len(old_bodies&new_bodies),'gained':sorted(new_bodies-old_bodies),
                         'lost':sorted(old_bodies-new_bodies)},
        inventory_gzip_sha256=sha(out/'inventory.json.gz'),
        baseline_verification='prior public replay; same compressed SHA, not rerun here',
        scope='offline automatic source/frame construction and independent replay, not workload A/B')
    save(out/'run.json',metadata)
    print(json.dumps({key:metadata[key] for key in ('status','revision','generated_s','replay_s',
                                                   'peak_rss_kib','source_unchanged','body_difference')}),flush=True)


if __name__=='__main__':
    main()
