"""Join current external source representations to the same local catalog.

Discovery authenticates code scopes, not historical module versions. Lowering
is offline and parallel; publication references the primitive F4/interface
shards and never turns current file candidates into import/runtime grants.
"""
import argparse
from dataclasses import replace
from hashlib import sha256
import json
from pathlib import Path
import time

from scar.analysis.source_declared_catalog import read_source_catalog, DeclaredSourceCatalog, _receipt, _check
from scar.analysis.observed_source_catalog import ObservedSourceCatalog, SCHEMA, _FALSE
from scar.analysis.observed_compiled_material import ObservedCompiledLocalMaterial
from scar.analysis.observed_external_sources import ExternalSourceMatches, match_external_sources
from scar.analysis.source_stage import _durable_bytes, _durable_mkdir
from scar.analysis.source_template_links import _json
from scar.ir.program.call_edges import CallEdgeBudget


def discover(catalog, trace, project_root, out, *, frame_max_events=100_000):
    from scar.analysis.program_view import ProgramView
    from scar.analysis.source_observed_codes import ObservedSourceCodeProvider
    view=ProgramView(catalog)
    codes=ObservedSourceCodeProvider(view, trace, project_root,
        frame_budget=replace(CallEdgeBudget(),max_events=frame_max_events))
    records=(*codes.records.values(),*codes.scope_records.values())
    body_known={(c.process_id,c.code.key) for row in records for c in row.captures}
    # A full source/code representation can already be retained even when a
    # particular language body interface is not projected. Do not lower that
    # source again to repair a different layer's frontier. The admitted
    # catalog binds these original captures to checked source/root recipes.
    represented_codes={item['capture']['code']['key']
        for entry in view.catalog.report.get('compiled',())
        for item in entry.get('matched_captures',())}
    represented_codes.update(key
        for entry in view.catalog.report.get('compiled',())
        if entry.get('origin')=='AUDIT_CODE_ROOT_MATCH'
        for key in entry['observed_child_codes'])
    # CodeID is a complete structural code identity, independent of PID.
    # Reusing its source representation is not reusing an old invocation,
    # function object, namespace or argument binding from that process.
    represented={(c.process_id,c.code.key) for c in codes.trace.frame_scan.captures
        if c.code.key in represented_codes}
    known=body_known|represented
    report=match_external_sources(codes.trace.frame_scan.captures,known,out)
    codes.check()
    # Keep the supplying trace/catalog footprint beside the matcher, whose
    # API also accepts independent typed captures without a target process.
    receipts=[dict(path=str(logical),bytes=size,sha256=digest)
        for logical,(_,_,size,digest) in codes._trace_guard.items()]
    _durable_bytes(Path(out)/'supplying-code-view.json',_json(dict(
        schema='scar.external-source-capture-supplier',schema_version=1,
        catalog=_receipt(view.catalog.path/'result.json'),trace=codes.trace.directory,
        project_root=codes.trace.project_root,capture_inputs=receipts,
        code_summary=codes.summary(),source_body_interface_keys=len(body_known),
        retained_source_representation_keys=len(represented),
        represented_without_projected_body_keys=[list(k) for k in sorted(represented-body_known)],
        source_representation_is_not_body_interface_proof=True,target_executed=False)),replace=False)
    return report


def extend(catalog, materials, out):
    from scar.analysis import observed_source_catalog as producer
    started=time.monotonic();catalog=read_source_catalog(catalog)
    if not isinstance(catalog,DeclaredSourceCatalog):
        raise TypeError('external local material joins require a declared source catalog')
    out=Path(out).absolute();materials=Path(materials).absolute()
    if materials.is_dir():materials/='result.json'
    if out.resolve()!=out or out.exists():raise ValueError('fresh canonical extended source catalog required')
    receipt=_receipt(materials);batch=json.loads(materials.read_bytes())
    if ((batch['schema'],batch['schema_version'],batch['status'])
            != ('scar.external-source-materials',1,'EXTERNAL_SOURCE_MATERIALS_BUILT')
            or batch['coverage']['complete'] is not True or batch['target_executed'] is not False):
        raise ValueError('external material batch did not publish complete matched scope coverage')
    from scar.analysis.external_source_materials import _pins
    if batch['pins']!=_pins():raise ValueError('external material batch producer differs')
    _check(batch['source_reader']);reader=ExternalSourceMatches(Path(batch['source_reader']['path']).parent)
    expected={(c['capture']['process_id'],c['capture']['code']['key'])
        for m in reader.matches for c in m['matched_captures']}
    covered={(c['capture']['process_id'],c['capture']['code']['key'])
        for entry in batch['entries'] for c in entry['matched_captures']}
    if (covered!=expected or batch['coverage']['covered_keys']!=[list(v) for v in sorted(covered)]
            or batch['coverage']['expected_keys']!=[list(v) for v in sorted(expected)]):
        raise ValueError('external batch omitted an original matched code reference')
    observed=isinstance(catalog,ObservedSourceCatalog)
    base=catalog.base if observed else catalog
    added=[dict(entry,source_reader=batch['source_reader']) for entry in batch['entries']]
    supplied=[*catalog.report['compiled'],*added] if observed else added
    entries=[];retained={};representations={};deduplicated=[]
    fields=('origin','recipe','root_code','source_id','external_group')
    for entry in supplied:
        # Evidence locators can give independent snapshots different unit
        # IDs. The complete retained source/root/recipe identifies whether
        # they actually supply the same static representation.
        representation=(_json([entry.get(k) for k in fields])
            if entry['origin']=='CURRENT_SOURCE_CODE_MATCH' else None)
        prior=retained.get(entry['unit']) or representations.get(representation)
        if prior is not None:
            # Resuming an older bounded discovery can supply an already
            # retained primitive again. Reuse only the same source/recipe and
            # a subset of the exact original capture/constant-path evidence.
            if (entry['origin']!='CURRENT_SOURCE_CODE_MATCH'
                    or any(prior.get(k)!=entry.get(k) for k in fields)
                    or not {_json(item) for item in entry['matched_captures']}
                        <= {_json(item) for item in prior['matched_captures']}):
                raise ValueError('extended source namespace collides with different material evidence')
            _check(entry['material']);_check(entry['interfaces'])
            deduplicated.append(dict(supplied=entry['unit'],retained=prior['unit']))
            continue
        entries.append(entry);retained[entry['unit']]=entry
        if representation is not None:representations[representation]=entry
    rows=dict(base.fact_store.rows)
    for entry in entries:
        _check(entry['material']);_check(entry['interfaces'])
        material=ObservedCompiledLocalMaterial(Path(entry['material']['path']).parent)
        if material.unit in rows:raise ValueError('extended source namespace collides with another material')
        rows[material.unit]=dict(material.fact_store.row,
            facts=str(material.path/material.fact_store.row['facts']),module=None)
    reader.check();catalog.validate_parents();_check(receipt)
    _durable_mkdir(out)
    _durable_bytes(out/'facts.json',_json(dict(schema='scar.observed-source-facts',schema_version=1,units=rows)),replace=False)
    report=dict(schema=SCHEMA,schema_version=3,base=_receipt(base.path/'result.json'),
        matches=catalog.report['matches'] if observed else None,external_matches=batch['source_reader'],
        external_materials=receipt,input_catalog=_receipt(catalog.path/'result.json'),
        facts=_receipt(out/'facts.json'),compiled=entries,
        unselected_roots=catalog.report['unselected_roots'] if observed else [],
        selection='RETAINED_LOCAL_DECLARATIONS_PLUS_EXACT_CAPTURED_CODE_SOURCE_REPRESENTATIONS',
        retained_primitive_duplicates=deduplicated,
        imports='ORIGINAL_FILE_UNITS_ONLY',source_units=list(rows),
        auxiliary_interfaces='ALL_COMPILED_LOCAL_FAMILIES_PROJECTED',
        implementation_sha256=sha256(Path(producer.__file__).read_bytes()).hexdigest(),
        **{name:False for name in _FALSE},seconds=time.monotonic()-started)
    _durable_bytes(out/'result.json',_json(report),replace=False)
    ObservedSourceCatalog(out)
    return report


def main():
    parser=argparse.ArgumentParser(description=__doc__);sub=parser.add_subparsers(dest='action',required=True)
    find=sub.add_parser('discover')
    for name in ('catalog','trace','project-root','out'):find.add_argument('--'+name,required=True)
    find.add_argument('--frame-max-events',type=int,default=100_000)
    join=sub.add_parser('extend')
    for name in ('catalog','materials','out'):join.add_argument('--'+name,required=True)
    args=parser.parse_args()
    if args.action=='discover':
        r=discover(args.catalog,args.trace,args.project_root,args.out,frame_max_events=args.frame_max_events)
        print(json.dumps(dict(counts=r['counts'],seconds=r['seconds'])),flush=True)
    else:
        r=extend(args.catalog,args.materials,args.out)
        print(json.dumps(dict(source_units=len(r['source_units']),seconds=r['seconds'],first_stage_complete=False)),flush=True)


if __name__=='__main__':main()
