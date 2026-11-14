"""Refine selector scope from observed paths to already modeled code regions.

This is a capture policy, never execution, namespace or argument-binding
proof. Full retained root/child code identities admit every added selector.
"""
from collections import defaultdict
from pathlib import Path
import argparse
import json
from hashlib import sha256

from scar.ir.record_codec import encode
from scar.trace.code_snapshot import describe_code
from scar.trace.lean_capture import LeanCapturePlan, read_plan, _raw


def _caller_contexts(trace,selected,planned):
    """Follow original frame/path links to a retained planned activation.

    A thin ancestor can itself be an unplanned caller. Its own original entry
    supplies the next outer segment. No adjacency is promoted to a Python
    argument binding; these paths only limit the next collection's scope.
    """
    entries={frame.invocation:frame for frame in trace.entries}
    contexts=defaultdict(set);observations=[]
    for frame in trace.entries:
        if (frame.invocation.process_id,frame.code) not in selected:continue
        if not any(site.code not in planned for site in frame.path):continue
        path=list(frame.path);ancestor=frame.ancestor_invocation;visited=set()
        while True:
            if not frame.path_complete or not path or len(path)>128:
                raise ValueError('caller refinement needs a complete bounded original path')
            stop=next((i for i,site in enumerate(path) if site.code in planned),None)
            if stop is not None:
                path=path[:stop+1];break
            entry=entries.get(ancestor)
            if (entry is None or ancestor in visited or not entry.path_complete
                    or path[-1].code!=entry.code):
                raise ValueError('caller refinement has no original path to a planned activation')
            visited.add(ancestor);path.extend(entry.path);ancestor=entry.ancestor_invocation
        for i,site in enumerate(path[:-1]):
            if site.code not in planned:contexts[site.code].add(tuple(path[i+1:]))
        observations.append(dict(entry=encode(frame.anchor),code=frame.code,
            missing_callers=tuple(site.code for site in path if site.code not in planned),
            path_complete=True,activation_path=encode(tuple(path))))
    return contexts,observations


def refine_caller_paths(plan, provider, *, seed_records=None, max_new_codes=128, source_catalog=None):
    if type(plan) is not LeanCapturePlan or type(max_new_codes) is not int or max_new_codes<1:
        raise TypeError('typed original plan and exact positive refinement budget required')
    provider.check();plan.verify_sources()
    if plan.namespace_root!=provider.project_root:
        raise ValueError('capture selector and observed code namespaces differ')
    records=tuple(row for name in ('records','scope_records','request_records')
        for row in getattr(provider,name,{}).values())
    known={row.id:row for row in records}
    seeds=records if seed_records is None else tuple(seed_records)
    record_types={type(item) for item in records}
    if any(type(row) not in record_types
            or known.get(row.id) is not row for row in seeds):
        raise ValueError('refinement seeds must be original admitted code records')
    selected={(c.process_id,c.code.key) for row in seeds for c in row.captures}
    planned={body.code.key for body in plan.bodies}
    contexts,observations=_caller_contexts(provider.trace,selected,planned)
    required=set(contexts)
    if len(required)>max_new_codes or len(plan.bodies)+len(required)>plan.max_codes:
        raise ValueError('caller refinement exceeds its explicit selector budget')
    captures={c.code.key:c for c in provider.trace.frame_scan.captures}
    # This directory is only a candidate locator index. It does not admit a
    # graph/catalog or replace the code-view reader's semantic validation.
    # Only the needed snapshots are read, then full compiler identities below
    # independently establish their suitability as selectors.
    index=provider.view.catalog.report;index_receipt=None
    from scar.analysis.source_declared_catalog import _check,_receipt
    if source_catalog is not None:
        path=Path(source_catalog).absolute()
        if path.is_dir():path/='result.json'
        if path.resolve()!=path or path.is_symlink() or not 0<path.stat().st_size<=2_000_000:
            raise ValueError('bounded canonical source locator index required')
        index_receipt=_receipt(path);index=json.loads(path.read_bytes());_check(index_receipt)
        if (index.get('schema'),index.get('schema_version'))!=('scar.observed-source-catalog',3):
            raise ValueError('source locator index has an unsupported format')
    witnesses=defaultdict(list)
    for entry in index.get('compiled',()):
        for item in entry.get('matched_captures',()):
            key=item['capture']['code']['key']
            if key in required:witnesses[key].append((entry,item))
    roots={};additions=[];evidence=[];fingerprints={};snapshots=[]
    for key in sorted(required):
        capture=captures[key];filename=capture.code.filename
        if not Path(filename).is_absolute():
            raise ValueError('caller needs an archive-qualified selector source: '+key)
        if not witnesses[key]:
            raise ValueError('caller has no retained compatible source replay: '+key)
        entry,item=witnesses[key][0];receipt=entry['material']
        _check(receipt)
        if receipt['path'] not in roots:
            report=json.loads(Path(receipt['path']).read_bytes())
            relative=Path(report['snapshot']['path'])
            if relative.is_absolute() or '..' in relative.parts:
                raise ValueError('caller snapshot must belong to its original material')
            snapshot=Path(receipt['path']).parent/relative
            if snapshot.resolve()!=snapshot or snapshot.is_symlink() or snapshot.stat().st_size>1_000_000:
                raise ValueError('caller snapshot is not bounded canonical source')
            raw=snapshot.read_bytes()
            if (len(raw),sha256(raw).hexdigest())!=(report['snapshot']['bytes'],report['snapshot']['sha256']):
                raise ValueError('caller snapshot differs from its retained source receipt')
            snapshots.append(_receipt(snapshot))
            # The current file is only a selector version guard. It must be
            # the same retained bytes; no historical-source claim is inferred.
            if Path(filename).read_bytes()!=raw:
                raise ValueError('caller source version differs from its retained replay')
            from scar.analysis.source_observed_codes import replay_catalog_code
            roots[receipt['path']]=replay_catalog_code(raw,
                dict(recipe=entry['recipe'],root_code=entry['root_code']))[0]
            text=raw.decode('utf-8').replace('\r\n','\n').replace('\r','\n')
            fingerprints[filename]='sha256:'+sha256(text.encode('utf-8')).hexdigest()
        code=roots[receipt['path']]
        for ordinal in item['constant_path']:code=code.co_consts[ordinal]
        if describe_code(code)!=encode(capture.code):
            raise ValueError('caller replay lost its full observed code identity')
        additions.append(code)
        evidence.append(dict(code=key,capture=encode(capture.anchor),material=receipt,
            constant_path=item['constant_path']))
    extra=() if not additions else LeanCapturePlan.from_codes(plan.namespace_root,
        tuple(additions),max_codes=max_new_codes).bodies
    if any(body.source.fingerprint!=fingerprints[body.code.filename] for body in extra):
        raise ValueError('caller source changed while creating its selector')
    activation_paths=tuple((key,tuple(sorted(contexts[key],key=lambda path:
        tuple((site.code,site.offset) for site in path)))) for key in sorted(contexts))
    result=LeanCapturePlan(plan.namespace_root,(*plan.bodies,*extra),plan.max_codes,
        (*plan.activation_paths,*activation_paths))
    provider.check();result.verify_sources()
    for receipt in snapshots:_check(receipt)
    if index_receipt is not None:_check(index_receipt)
    return result,dict(schema='scar.observed-caller-plan-refinement',
        original_selectors=len(plan.bodies),added_selectors=len(extra),
        result_selectors=len(result.bodies),seed_records=len(seeds),observations=observations,
        replay_witnesses=evidence,truncated_source_paths=0,
        context_restricted_selectors=len(activation_paths),
        activation_paths=encode(activation_paths),
        candidate_locator_index=index_receipt,candidate_catalog_semantics_admitted=False,
        original_selectors_preserved=True,source_body_graphs_rebuilt=False,
        target_executed=False,argument_binding_proven=False,first_stage_complete=False)


def main(argv=None):
    parser=argparse.ArgumentParser(description=__doc__)
    for name in ('plan','plan-sha256','codes','out'):parser.add_argument('--'+name,required=True)
    parser.add_argument('--seed-kind',choices=('all','requests'),default='all')
    parser.add_argument('--max-codes',type=int,default=8192)
    parser.add_argument('--max-new-codes',type=int,default=128)
    parser.add_argument('--source-catalog',help='existing composite directory used only to locate candidate snapshots')
    args=parser.parse_args(argv);out=Path(args.out).absolute()
    if out.resolve()!=out or out.exists():raise ValueError('fresh canonical refinement output required')
    plan=read_plan(args.plan,expected_sha256=args.plan_sha256,max_codes=args.max_codes)
    from scar.analysis.source_observed_codes import read_observed_request_codes
    provider=read_observed_request_codes(args.codes)
    seeds=None if args.seed_kind=='all' else tuple(provider.request_records.values())
    refined,report=refine_caller_paths(plan,provider,seed_records=seeds,
        max_new_codes=args.max_new_codes,source_catalog=args.source_catalog)
    from hashlib import sha256
    from scar.analysis.source_stage import _durable_mkdir,_durable_bytes
    raw=_raw(refined.to_dict());_durable_mkdir(out)
    _durable_bytes(out/'capture-plan.json',raw,replace=False)
    report.update(input_plan_sha256=args.plan_sha256,new_plan_sha256=sha256(raw).hexdigest())
    _durable_bytes(out/'result.json',_raw(report),replace=False)
    print(json.dumps({k:report[k] for k in ('original_selectors','added_selectors',
        'result_selectors','new_plan_sha256','first_stage_complete')}),flush=True)


if __name__=='__main__':main()
