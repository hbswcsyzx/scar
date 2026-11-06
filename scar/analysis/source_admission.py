"""Join normal/context module demands to receipt-bound material candidates.

Recorded inventory indices keep their original scopes. New demand-derived
searches form a separate overlay over explicit roots, never fabricated import
relations or modifications of the original manifests. No target is imported.
"""
import argparse
from collections import Counter,defaultdict
from hashlib import sha256
import json
from pathlib import Path
import stat
import time

from scar.analysis.normal_query import NormalCallGraph
from scar.analysis import static_dependencies,source_discovery
from scar.analysis.source_stage import _durable_bytes,_durable_mkdir
from scar.analysis.source_template_links import _json,_stream
from scar.ir.program.discovery import CandidateRole
from scar.ir.program.static_dependencies import (
    DependencyMaterialKind as K,DependencySearchStatus as S,DependencyVersionStatus as V,
)
from scar.ir.record_codec import encode


def _reference(path, snapshots):
    path=Path(path).absolute();raw=path.read_bytes()
    if path in snapshots and snapshots[path]!=raw:
        raise ValueError('source admission input changed: '+str(path))
    snapshots[path]=raw
    return dict(path=str(path),bytes=len(raw),sha256=sha256(raw).hexdigest())


def _providers(store):
    """Select the actual primitive owner of each importable source unit."""
    selected=getattr(store,'importable_units',store.rows)
    providers={}
    for identity in store.rows:
        if identity not in selected:continue
        parent=store.source_parent_for(identity) if hasattr(store,'source_parent_for') else store
        while parent.parents:parent=parent.parents[parent.unit_parent[identity]]
        key=str(parent.path)
        if key in providers and providers[key][0].raw!=parent.raw:
            raise ValueError('source provider path has conflicting snapshots')
        providers.setdefault(key,(parent,[]))[1].append(identity)
    return tuple(providers.values())


def _inventories(store,snapshots):
    inventories=[];unavailable=[]
    for parent,units in _providers(store):
        facts=_reference(parent.path/'result.json',snapshots)
        if facts['sha256']!=sha256(parent.raw).hexdigest():
            raise ValueError('source provider report differs')
        manifest=_reference(parent.model/'manifest.json',snapshots)
        if manifest['sha256']!=parent.report['model_manifest_sha256']:
            raise ValueError('source provider model differs')
        model=json.loads(snapshots[Path(manifest['path'])]);artifacts=model.get('artifacts',{})
        basis=dict(facts=facts,model=str(parent.model),manifest=manifest,source_units=tuple(units))
        if 'imports' not in artifacts or 'dependencies' not in artifacts:
            unavailable.append(dict(**basis,status='NO_PUBLISHED_DEPENDENCY_INVENTORY'))
            continue
        inventory=static_dependencies.read_static_dependencies(parent.model)
        receipt=_reference(parent.model/artifacts['dependencies']['path'],snapshots)
        if (receipt['bytes']!=artifacts['dependencies']['bytes']
                or receipt['sha256']!=artifacts['dependencies']['sha256']):
            raise ValueError('dependency inventory stored receipt differs')
        original_imports=_reference(inventory.import_index.artifact.uri,snapshots)
        if (original_imports['bytes']!=inventory.import_index.artifact.size_bytes
                or original_imports['sha256']!=inventory.import_index.artifact.sha256):
            raise ValueError('dependency inventory import parent differs')
        inventories.append((inventory,dict(**basis,receipt=receipt,descriptor=artifacts['dependencies'],
            import_index=encode(inventory.import_index),search_roots=inventory.search_roots,
            native_suffixes=inventory.native_suffixes)))
    return inventories,unavailable


def _search(module,roots,suffixes,materials,file_cache,spent,stamps):
    """Probe only module-derived paths; hash Python source, never native code."""
    indices=[];frontiers=[]
    if not module or not all(part.isidentifier() for part in module.split('.')):
        return dict(module=module,status='INVALID_MODULE_NAME',materials=(),frontiers=())
    candidates={}
    for root in roots:
        root=Path(root)
        try:
            if static_dependencies._symlink(root) is not None or not stat.S_ISDIR(root.lstat().st_mode):
                frontiers.append(dict(kind='SEARCH_ROOT_UNAVAILABLE_OR_SYMLINK',path=str(root)));continue
            gaps=[]
            found=source_discovery._resolve_module(module,root,root,CandidateRole.REQUESTED_MODULE,None,gaps)
            frontiers.extend(encode(gap) for gap in gaps)
            for candidate in found:
                kind=K.NAMESPACE_DIRECTORY if candidate.namespace else K.SOURCE
                candidates[candidate.name,candidate.path,str(root),kind.value]=dict(module=candidate.name,
                    path=candidate.path,source_root=str(root),kind=kind.value,
                    parent_initializers=candidate.parent_initializers,role=candidate.role.value)
            stem=root.joinpath(*module.split('.'))
            alternatives=[(Path(str(stem)+'.pyi'),K.STUB),(stem/'__init__.pyi',K.STUB)]
            stub=root.joinpath(module.split('.')[0]+'-stubs',*module.split('.')[1:])
            alternatives.extend(((Path(str(stub)+'.pyi'),K.STUB),(stub/'__init__.pyi',K.STUB)))
            for suffix in suffixes:
                alternatives.extend(((Path(str(stem)+suffix),K.NATIVE),(stem/('__init__'+suffix),K.NATIVE)))
            for path,kind in alternatives:
                if static_dependencies._symlink(path) is None and path.is_file():
                    candidates[module,str(path),str(root),kind.value]=dict(module=module,path=str(path),
                        source_root=str(root),kind=kind.value,parent_initializers=(),role='REQUESTED_MODULE')
        except OSError as error:
            frontiers.append(dict(kind='SEARCH_ROOT_OR_CANDIDATE_UNAVAILABLE',path=str(root),detail=str(error)))
    for _,candidate in sorted(candidates.items()):
        path=Path(candidate['path']);kind=candidate['kind']
        # A native package initializer is a package candidate, not evidence
        # for an otherwise initializer-free namespace directory.
        if kind==K.NAMESPACE_DIRECTORY.value and any(c['kind']==K.NATIVE.value
                and Path(c['path']).parent==path and Path(c['path']).name.startswith('__init__.')
                for c in candidates.values()):continue
        row=dict(candidate,scope='DEMAND_DERIVED_EXPLICIT_ROOT_SEARCH',artifact=None,
            version_status='DIRECTORY_ONLY' if kind==K.NAMESPACE_DIRECTORY.value else 'CONTENT_NOT_READ',
            conditions=('EXPLICIT_SEARCH_ROOT_CANDIDATE_SELECTED','TARGET_IMPORT_PATH_AND_HOOKS_NOT_RESOLVED',
                        'FILE_VERSION_RECHECK_REQUIRED_BEFORE_SOURCE_INGESTION'))
        try:
            if static_dependencies._symlink(path) is not None:
                raise OSError('candidate path traverses a symbolic link')
            info=path.lstat();row['stat_stamp']=static_dependencies._stamp(info)
            if kind==K.SOURCE.value:
                if path not in file_cache:
                    available=min(8*1024*1024,64*1024*1024-spent[1])
                    if spent[0]>=4096:raise ValueError('source file read budget reached')
                    digest,count=static_dependencies._read_receipt(path,info,available,spent)
                    file_cache[path]=dict(uri=str(path),sha256=digest,size_bytes=count,
                        schema='scar.dependency-material-bytes')
                    stamps[path]=static_dependencies._stamp(info)
                row.update(artifact=file_cache[path],version_status='CONTENT_HASHED')
        except (OSError,ValueError) as error:
            row.update(version_status='READ_FAILED',version_detail=str(error))
        indices.append(len(materials));materials.append(row)
    return dict(module=module,status='SEARCHED_EXPLICIT_ROOTS',materials=tuple(indices),frontiers=tuple(frontiers),
        scope='DEMAND_DERIVED_EXPLICIT_ROOT_SEARCH',native_search_profiled=bool(suffixes))


def build_admission_plan(targets,out,*,search_roots=()):
    started=time.monotonic();out=Path(out).absolute();snapshots={}
    if out.exists():raise ValueError('fresh source admission output required')
    target_ref=_reference(Path(targets)/'result.json',snapshots)
    schema=json.loads(snapshots[Path(target_ref['path'])])['schema']
    if schema=='scar.context-source-targets':
        from scar.analysis.source_context_query import ContextTargetGraph
        view=ContextTargetGraph(targets)
    else:view=NormalCallGraph(targets)
    if json.loads(snapshots[Path(target_ref['path'])])!=view.report:
        raise ValueError('target graph changed during admission')
    store=view.fact_store;inventories,unavailable=_inventories(store,snapshots)
    queries=defaultdict(list)
    for inventory_index,(inventory,_) in enumerate(inventories):
        for query_index,query in enumerate(inventory.module_queries):
            queries[query.module].append((inventory_index,query_index,query))
    roots=tuple(dict.fromkeys(str(Path(p).absolute()) for p in search_roots))
    root_origin='EXPLICIT_CLI_SEARCH_ROOTS' if roots else 'RECORDED_DEPENDENCY_INVENTORY_ROOTS'
    if not roots:roots=tuple(dict.fromkeys(p for inventory,_ in inventories for p in inventory.search_roots))
    suffixes=tuple(dict.fromkeys(s for inventory,_ in inventories for s in inventory.native_suffixes))
    groups=defaultdict(list);demand_rows=[]
    for index,demand in enumerate(view.module_demands()):
        groups[demand.module].append(index);demand_rows.append(dict(ordinal=index,demand=demand))
    admitted=defaultdict(list);modules=defaultdict(list)
    for identity,row in store.rows.items():
        if identity not in getattr(store,'importable_units',store.rows):continue
        admitted[row['path']].append(identity);modules[row['module']].append(identity)
    def existing(path,digest=None):
        return tuple(i for i in admitted.get(path,()) if digest is None
            or store.model_units[i].get('raw_sha256')==digest)
    rows=[];searches=[];searched_materials=[];file_cache={};spent=[0,0];stamps={}
    for module,indices in sorted(groups.items()):
        found=queries.get(module,());inventory_queries=[];source_refs=[];stub_refs=[];native_refs=[];namespace_refs=[]
        present=set(modules.get(module,()));ready=[];version_pending=[];snapshots_pending=[]
        legacy={'SOURCE':[],'STUB':[],'NATIVE':[]}
        for inv,qi,query in found:
            inventory=inventories[inv][0]
            inventory_queries.append(dict(inventory=inv,module_query=qi,materials=query.materials,status=query.status.value))
            for index in query.materials:
                material=inventory.materials[index]
                digest=None if material.artifact is None else material.artifact.sha256
                if material.version_status is V.SUPPLIED_SNAPSHOT:
                    units=(material.supplied_unit,) if (material.supplied_unit in store.rows
                        and material.supplied_unit in getattr(store,'importable_units',store.rows)
                        and store.rows[material.supplied_unit]['path']==material.path) else ()
                else:units=existing(material.path,digest)
                present.update(units)
                ref=dict(scope='RECORDED_DEPENDENCY_INVENTORY',inventory=inv,material=index)
                if material.kind is K.SOURCE:
                    source_refs.append(ref)
                    if material.version_status is V.CONTENT_HASHED and material.artifact is not None:
                        if not units:ready.append(ref)
                    elif material.version_status is V.SUPPLIED_SNAPSHOT:
                        if not units:snapshots_pending.append(ref)
                    else:version_pending.append(ref)
                elif material.kind is K.STUB:stub_refs.append(ref)
                elif material.kind is K.NATIVE:native_refs.append(ref)
                else:namespace_refs.append(ref)
                if inv==0 and material.kind.value in legacy:legacy[material.kind.value].append(index)
        searched_query=None
        if not found and roots:
            searched_query=len(searches)
            result=_search(module,roots,suffixes,searched_materials,file_cache,spent,stamps);searches.append(result)
            for index in result['materials']:
                material=searched_materials[index]
                if material['module']!=module:continue  # Parent namespace candidates retain their own names.
                digest=None if material['artifact'] is None else material['artifact']['sha256']
                units=existing(material['path'],digest);present.update(units)
                ref=dict(scope='DEMAND_DERIVED_EXPLICIT_ROOT_SEARCH',material=index)
                if material['kind']==K.SOURCE.value:
                    source_refs.append(ref)
                    if material['version_status']=='CONTENT_HASHED' and material['artifact'] is not None:
                        if not units:ready.append(ref)
                    else:version_pending.append(ref)
                elif material['kind']==K.STUB.value:stub_refs.append(ref)
                elif material['kind']==K.NATIVE.value:native_refs.append(ref)
                else:namespace_refs.append(ref)
        if ready:status='SOURCE_READY_NOT_ADMITTED'
        elif present:status='SOURCE_NAMESPACE_MAPPING_OPEN'
        elif version_pending:status='SOURCE_VERSION_PENDING'
        elif snapshots_pending:status='SOURCE_SNAPSHOT_FRONTEND_PENDING'
        elif native_refs:status='NATIVE_INTERFACE_CANDIDATE'
        elif stub_refs:status='DECLARATION_WITHOUT_RUNTIME_SOURCE'
        elif namespace_refs:status='PACKAGE_NAMESPACE_CANDIDATE'
        elif found and any(q.status is S.MODULE_BUDGET for _,_,q in found):status='MODULE_QUERY_PENDING'
        elif found:status='NO_MATERIAL_IN_RECORDED_SEARCH'
        elif searched_query is None:status='UNINDEXED_MODULE_REQUEST'
        else:status='UNINDEXED_MODULE_NO_MATERIAL_IN_EXPLICIT_ROOTS'
        rows.append(dict(module=module,demand_indices=tuple(indices),
            module_query=next((qi for inv,qi,_ in found if inv==0),None),status=status,
            source_materials=tuple(legacy['SOURCE']),stub_materials=tuple(legacy['STUB']),native_materials=tuple(legacy['NATIVE']),
            legacy_material_index_scope='INVENTORY_0_ONLY',inventory_queries=tuple(inventory_queries),searched_query=searched_query,
            source_candidates=tuple(source_refs),stub_candidates=tuple(stub_refs),native_candidates=tuple(native_refs),
            namespace_candidates=tuple(namespace_refs),source_ready_candidates=tuple(ready),
            source_version_pending_candidates=tuple(version_pending),
            source_snapshot_frontend_candidates=tuple(snapshots_pending),existing_source_units=tuple(sorted(present)),
            conditions=('MATERIAL_AND_VERSION_ALTERNATIVE_NOT_IMPORT_SELECTION','SOURCE_INGESTION_RECHECKS_COMPLETE_BYTES')))
    _durable_mkdir(out);table=_stream(out/'module-admission.jsonl.gz',rows)
    tables=dict(demands=_stream(out/'demands.jsonl.gz',demand_rows),
        searched_queries=_stream(out/'searched-queries.jsonl.gz',searches),
        searched_materials=_stream(out/'searched-materials.jsonl.gz',searched_materials),
        admitted_modules=_stream(out/'admitted-modules.jsonl.gz',(dict(module=name,source_units=tuple(units),
            scope='SOURCE_CATALOG_CANDIDATES_NOT_NEW_DEMANDS') for name,units in sorted(modules.items()))))
    for path,raw in snapshots.items():
        if path.read_bytes()!=raw:raise ValueError('source admission input changed before publication: '+str(path))
    for path,stamp in stamps.items():
        if static_dependencies._symlink(path) is not None or static_dependencies._stamp(path.lstat())!=stamp:
            raise ValueError('searched source candidate changed before publication')
    if hasattr(store,'validate_parents'):store.validate_parents()
    if view.interface_store is not None:view.interface_store.validate_parents()
    first=None if not inventories else inventories[0][1]
    report=dict(schema='scar.source-admission-plan',schema_version=1,status='DEMANDS_LINKED_TO_MATERIALS',
        targets=str(view.path),targets_result_sha256=target_ref['sha256'],target_schema=schema,
        demand_table=view.report.get('entry_module_demands'),demand_ordinal_base=0,
        inventory=None if first is None else first['receipt']['path'],
        inventory_sha256=None if first is None else first['receipt']['sha256'],
        model_manifest_sha256=None if first is None else first['manifest']['sha256'],
        inventory_scope='DISTINCT_PRIMITIVE_SOURCE_PROVIDERS',inventories=[r for _,r in inventories],
        providers_without_inventory=unavailable,module_admission=table,tables=tables,
        search_roots=roots,search_root_origin=root_origin,native_suffixes=suffixes,
        search_scope='ONLY_ACTUAL_UNINDEXED_MODULE_DEMANDS;FIXED_MODULE_PATHS;NO_DIRECTORY_WALK',
        search_read_files=len(file_cache),search_read_attempts=spent[0],search_read_bytes=spent[1],
        search_read_budget=dict(max_files=4096,max_bytes=64*1024*1024,max_file_bytes=8*1024*1024,
            cache_hit_charge='NO_FILE_ATTEMPT_OR_BYTES'),
        statuses=dict(Counter(r['status'] for r in rows)),module_demands=sum(map(len,groups.values())),
        unique_module_requests=len(groups),unindexed_module_requests=sum(not r['inventory_queries'] for r in rows),
        source_candidates=sum(len(r['source_candidates']) for r in rows),searched_module_queries=len(searches),
        import_choice_established=False,model_changed=False,target_executed=False,first_stage_complete=False,
        input_receipts=[dict(path=str(p),bytes=len(raw),sha256=sha256(raw).hexdigest()) for p,raw in snapshots.items()],
        pins={name:sha256(Path(module.__file__).read_bytes()).hexdigest() for name,module in
            (('dependency_reader',static_dependencies),('source_locator',source_discovery))},
        implementation_sha256=sha256(Path(__file__).read_bytes()).hexdigest(),seconds=time.monotonic()-started)
    _durable_bytes(out/'result.json',_json(report),replace=False);return report


def main():
    parser=argparse.ArgumentParser(description=__doc__)
    parser.add_argument('--targets',required=True);parser.add_argument('--out',required=True)
    parser.add_argument('--search-root',action='append',default=[],help='explicit import-root candidate; repeatable')
    args=parser.parse_args();r=build_admission_plan(args.targets,args.out,search_roots=args.search_root)
    print(json.dumps({k:r[k] for k in ('status','statuses','unique_module_requests','source_candidates','seconds')},indent=2))


if __name__=='__main__':main()
