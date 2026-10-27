"""Read exact archived source for twelve returned frontiers; no lowering."""
import ast
from collections import Counter
import gzip
from hashlib import sha256
import json
from pathlib import Path

HERE=Path(__file__).resolve().parent
ROOT=HERE.parents[2]
STORE=HERE.parent/'first_stage_partitioned_operand_routes_20261023/result/code-witnesses'
manifest=json.loads((STORE/'manifest.json').read_text())
sources={json.dumps(row['snapshot'],sort_keys=True):row for row in manifest['sources'].values()}
bodies=json.loads(gzip.decompress((HERE/'plan/bodies.json.gz').read_bytes()))['rows']
by_key={row['body_key']:row for row in bodies}
trees={}
records=[]
counts=Counter();weights=Counter()
for line in (HERE/'worker/attempts.jsonl').read_text().splitlines():
    attempt=json.loads(line); folder=HERE/'worker'/f"attempt-{attempt['sequence']:05d}"
    returned=json.loads((folder/'returned-metadata.json').read_text());gap=returned['metadata']['gaps'][-1]
    body=by_key[attempt['body_key']]
    snapshot=body['snapshot'];key=json.dumps(snapshot,sort_keys=True)
    if key not in trees:
        source=sources[key];path=STORE/source['artifact']['path'];raw=path.read_bytes()
        assert len(raw)==source['artifact']['bytes'] and sha256(raw).hexdigest()==source['artifact']['sha256']
        text=raw.decode('utf-8');assert 'sha256:'+sha256(text.encode()).hexdigest()==snapshot['fingerprint']
        trees[key]=(ast.parse(text,filename=snapshot['path']),text,{**source['artifact'],'path':str(path.resolve())})
    tree,text,receipt=trees[key]
    span=gap['source']
    candidates=[node for node in ast.walk(tree) if hasattr(node,'end_lineno')
        and (node.lineno,node.end_lineno,node.col_offset,node.end_col_offset)
        ==(span['start_line'],span['end_line'],span['start_column'],span['end_column'])]
    shapes=[]
    for node in candidates:
        item={'ast_kind':type(node).__name__}
        if isinstance(node,ast.Call):
            item.update(positional_kinds=[type(arg).__name__ for arg in node.args],
                starred_positions=[i for i,arg in enumerate(node.args) if isinstance(arg,ast.Starred)],
                keyword_kinds=['DOUBLE_STARRED' if kw.arg is None else 'NAMED' for kw in node.keywords])
        if isinstance(node,ast.Slice):
            item.update(lower_omitted=node.lower is None,upper_omitted=node.upper is None,step_omitted=node.step is None)
        shapes.append(item)
    assert candidates
    kinds=tuple(sorted({type(node).__name__ for node in candidates}))
    label='|'.join(kinds);counts[label]+=1;weights[label]+=body['current_calls']
    records.append({'sequence':attempt['sequence'],'body_key':attempt['body_key'],
        'definition_kind':body['definition']['kind'],'current_groups':len(body['current_groups']),
        'current_calls':body['current_calls'],'body_locator':body['body_locator'],
        'definition_source':body['definition']['source'],'last_frontier':gap,'exact_ast_shapes':shapes,
        'archived_source_receipt':receipt,'source_excerpt':ast.get_source_segment(text,candidates[0])})
result={'scope':'exact source diagnosis of original returned frontiers; no attempt selection/target/lowering',
    'source_files_parsed':len(trees),'attempts':len(records),'ast_kind_counts':dict(counts),
    'current_call_weights':dict(weights),'rows':records,'source_prepared':False,'code_compiled_or_loaded':False,
    'production_files_modified':False,'first_stage_complete':False}
(HERE/'exact-ast-frontiers.json').write_text(json.dumps(result,indent=2)+'\n')
print(json.dumps({'counts':dict(counts),'weighted_current_calls':dict(weights),'files':len(trees)},indent=2))
