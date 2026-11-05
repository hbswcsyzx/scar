"""Join entry module demands to immutable source/native material candidates.

This locates the next frontend inputs. A candidate file does not establish
the target importer's choice, and this command never changes the source model.
"""
import argparse
from collections import Counter,defaultdict
from hashlib import sha256
import json
from pathlib import Path
import time

from scar.analysis.normal_query import NormalCallGraph
from scar.analysis.static_dependencies import read_static_dependencies
from scar.analysis.source_stage import _durable_bytes,_durable_mkdir
from scar.analysis.source_template_links import _json,_stream
from scar.ir.program.static_dependencies import DependencyMaterialKind as K,DependencySearchStatus as S


def build_admission_plan(targets,out):
    started=time.monotonic();view=NormalCallGraph(targets);out=Path(out).absolute()
    if out.exists():raise ValueError('fresh source admission output required')
    model=view.fact_store.model
    inventory=read_static_dependencies(model)
    queries={q.module:(i,q) for i,q in enumerate(inventory.module_queries)}
    groups=defaultdict(list)
    for index,demand in enumerate(view.module_demands()):groups[demand.module].append(index)
    admitted=defaultdict(list)
    for row in view.inputs['units']:admitted[row['path']].append(row['unit'])
    rows=[]
    for module,indices in sorted(groups.items()):
        found=queries.get(module);query_index=None if found is None else found[0]
        query=None if found is None else found[1];sources=[];stubs=[];native=[];existing=set()
        for index in (() if query is None else query.materials):
            material=inventory.materials[index]
            existing.update(admitted.get(material.path,()))
            if material.kind is K.SOURCE:sources.append(index)
            elif material.kind is K.STUB:stubs.append(index)
            elif material.kind is K.NATIVE:native.append(index)
        if query is None:status='UNINDEXED_MODULE_REQUEST'
        elif query.status is S.MODULE_BUDGET:status='MODULE_QUERY_PENDING'
        elif existing:status='SOURCE_NAMESPACE_MAPPING_OPEN'
        elif sources:status='SOURCE_READY_NOT_ADMITTED'
        elif native:status='NATIVE_INTERFACE_CANDIDATE'
        elif stubs:status='DECLARATION_WITHOUT_RUNTIME_SOURCE'
        elif query.materials:status='PACKAGE_NAMESPACE_CANDIDATE'
        else:status='NO_MATERIAL_IN_RECORDED_SEARCH'
        rows.append(dict(module=module,demand_indices=tuple(indices),module_query=query_index,status=status,
            source_materials=tuple(sources),stub_materials=tuple(stubs),native_materials=tuple(native),
            existing_source_units=tuple(sorted(existing))))
    manifest_raw=(model/'manifest.json').read_bytes();manifest=json.loads(manifest_raw)
    descriptor=manifest['artifacts']['dependencies'];inventory_path=model/descriptor['path']
    _durable_mkdir(out);table=_stream(out/'module-admission.jsonl.gz',rows)
    report=dict(schema='scar.source-admission-plan',schema_version=1,status='DEMANDS_LINKED_TO_MATERIALS',
        targets=str(view.path),targets_result_sha256=sha256((view.path/'result.json').read_bytes()).hexdigest(),
        demand_table=view.report['entry_module_demands'],demand_ordinal_base=0,
        inventory=str(inventory_path),inventory_sha256=sha256(inventory_path.read_bytes()).hexdigest(),
        model_manifest_sha256=sha256(manifest_raw).hexdigest(),inventory_scope='PRIMARY_SOURCE_PARENT',module_admission=table,
        statuses=dict(Counter(r['status'] for r in rows)),module_demands=sum(map(len,groups.values())),
        unique_module_requests=len(groups),source_candidates=len({i for r in rows for i in r['source_materials']}),
        import_choice_established=False,model_changed=False,target_executed=False,first_stage_complete=False,
        implementation_sha256=sha256(Path(__file__).read_bytes()).hexdigest(),seconds=time.monotonic()-started)
    _durable_bytes(out/'result.json',_json(report),replace=False);return report


def main():
    parser=argparse.ArgumentParser(description=__doc__)
    parser.add_argument('--targets',required=True);parser.add_argument('--out',required=True)
    args=parser.parse_args();r=build_admission_plan(args.targets,args.out)
    print(json.dumps({k:r[k] for k in ('status','statuses','unique_module_requests','source_candidates','seconds')},indent=2))


if __name__=='__main__':main()
