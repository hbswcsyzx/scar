"""Actual _source_tables checkpoint closure: no graph/SP5 payload decoding."""
from pathlib import Path
import hashlib,json
from collections import Counter
from config import HERE,REMAINDER
from report_archive import receipt
from scar.analysis.inventory_partitions import InventoryPartitions


def body_check():
    partitions=InventoryPartitions(REMAINDER/'result/publication/manifest.json')
    pins={};checked={};rows=[];missing={};metadata=[];status=Counter();kinds=Counter()
    def path_for(ref):
        # Exact same external/internal choice and namespace constraints as _read.
        if ref['external']:
            p=Path(ref['uri'])
            if not p.is_absolute():raise ValueError('body preflight: external evidence URI must be absolute')
        else:
            r=Path(ref['uri'])
            if r.is_absolute() or '..' in r.parts:raise ValueError('body preflight: internal ref escapes inventory root')
            p=partitions.root/r
        return p
    def physical(ref):
        p=path_for(ref);row={'path':str(p),'bytes':ref['physical_bytes'],'sha256':ref['physical_sha256']}
        if str(p) in pins and pins[str(p)]!=row:raise ValueError('body preflight: conflicting original receipt '+str(p))
        pins[str(p)]=row
        if str(p) in checked:return p
        if not p.is_file():missing[str(p)]=row;return p
        if p.is_symlink() or p.resolve()!=p:raise ValueError('body preflight: original ref not canonical regular file '+str(p))
        if receipt(p)!=row:raise ValueError('body preflight: original stored receipt differs '+str(p))
        checked[str(p)]=row
        return p
    for fi in range(len(partitions.manifest['files'])):
        file=partitions.file(fi) # normal metadata SHA/decoded receipt + schema checks
        metadata.append(partitions.external_reference(partitions.manifest['files'][fi]))
        for bi,body in enumerate(file['bodies']):
            status[body['status']]+=1
            record={'file_index':fi,'body_index':bi,'definition':body['definition'],
                'status':body['status'],'checkpoint':body['checkpoint'],'source_program':None}
            ref=body['checkpoint']
            if ref is None:
                kinds['NO_CHECKPOINT']+=1;rows.append(record);continue
            physical(ref)
            representation=ref['representation'];kinds[representation]+=1
            if representation=='scar.body-construction-checkpoint/2':
                if not path_for(ref).is_file():
                    record['unopened_CP2_wrapper']=True;rows.append(record);continue
                # Only CP2's small normal wrapper. Never decode CP1 graphs or SP5.
                if ref['decoded_bytes']>1_000_000:raise ValueError('body preflight: CP2 wrapper metadata exceeds1MB')
                wrapper=partitions.checkpoint(ref)
                if wrapper['schema_version']!=2:raise ValueError('body preflight: checkpoint version differs from ref')
                program=wrapper['source_program'];record['source_program']=program
                if program['representation']!='scar.source-program/5':raise ValueError('body preflight: unsupported external program contract')
                physical(program)
            elif representation!='scar.body-construction-checkpoint/1':
                raise ValueError('body preflight: unsupported checkpoint representation '+representation)
            rows.append(record)
    if len(rows)!=2217 or status['LOWERED_WITH_GAPS']!=858:
        raise ValueError('body preflight: complete original body/active graph denominator differs')
    return {'schema':'scar.source-tables-checkpoint-preflight/1',
        'status':'PASS_ALL_SOURCE_TABLE_PHYSICAL_REFS_ONLY' if not missing else 'MISSING_SOURCE_TABLE_PHYSICAL_REFS',
        'normal_reader':'InventoryPartitions.file/checkpoint(CP2 only); _read-equivalent path resolution',
        'all_body_records':len(rows),'active_graphs':858,'body_statuses':dict(status),'checkpoint_kinds':dict(kinds),
        'body_rows':rows,'metadata_file_refs':metadata,'physical_inputs':sorted(pins.values(),key=lambda r:r['path']),
        'physical_stored_bytes':sum(r['bytes'] for r in pins.values()),'physically_checked':len(checked),
        'missing':sorted(missing.values(),key=lambda r:r['path']),
        'graph_or_SP5_payload_decoded':False,'raw_read':False,'CodeWitness_constructed':False,
        'source_port_consumer_started':False,'qualification':'physical dependency closure only; no source-port semantic PASS'}


if __name__=='__main__':
    result=body_check()
    with (HERE/'BODY_PREFLIGHT.json').open('x') as stream:json.dump(result,stream,indent=2);stream.write('\n')
    if not (HERE/'MISSING_PINS.json').exists():
        with (HERE/'MISSING_PINS.json').open('x') as stream:json.dump({'inputs':result['missing'],'total_bytes':sum(r['bytes'] for r in result['missing']),'basis':'all actual _source_tables body-record checkpoint refs, including CP2 external SP5'},stream,indent=2);stream.write('\n')
    print(json.dumps({'status':result['status'],'all_body_records':result['all_body_records'],'active_graphs':result['active_graphs'],'checkpoint_kinds':result['checkpoint_kinds'],'physical_refs':len(result['physical_inputs']),'missing':len(result['missing']),'missing_bytes':sum(r['bytes'] for r in result['missing'])}))
