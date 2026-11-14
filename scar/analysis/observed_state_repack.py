"""Repack completed observed state units without running their solver again."""
import argparse
from concurrent.futures import ProcessPoolExecutor,as_completed
from hashlib import sha256
import gzip
import json
import multiprocessing
from pathlib import Path
import resource
import time

import os
from scar.analysis.binding_track_storage import TrackPacker,unpack_wire,pins,ENCODING
from scar.analysis.normal_output import write_table
from scar.analysis.source_declared_catalog import _receipt,_check
from scar.analysis.source_stage import _durable_bytes,_durable_mkdir
from scar.analysis.source_template_links import _json
from scar.analysis.source_observed_state import SCHEMA,compatible_pins


def _stream_table(folder,receipt):
    """Authenticate the same JSONL receipt while holding one record at a time."""
    path=Path(folder)/receipt['path'];digest=sha256();size=0
    with path.open('rb') as stream:
        for block in iter(lambda:stream.read(1024*1024),b''):digest.update(block);size+=len(block)
    if size!=receipt['bytes'] or digest.hexdigest()!=receipt['sha256']:
        raise ValueError('legacy compressed table receipt differs')
    digest=sha256();size=count=0
    with gzip.open(path,'rb') as stream:
        for raw in stream:
            digest.update(raw);size+=len(raw);count+=1;yield json.loads(raw)
    if (size,count,digest.hexdigest())!=(receipt['decoded_bytes'],receipt['records'],receipt['decoded_sha256']):
        raise ValueError('legacy decoded table receipt differs')


def _repack_unit(source,out):
    started=time.monotonic();source=Path(source);out=Path(out);original=_receipt(source/'result.json')
    header=json.loads((source/'result.json').read_bytes())
    if (header['schema'],header['schema_version'])!=('scar.source-state-view',1):
        raise ValueError('stream repack requires a completed schema-1 state unit')
    codec=pins();_durable_mkdir(out);packer=TrackPacker();count=0
    def records():
        nonlocal count
        for wire in _stream_table(source,header['tables']['tracks']):
            packed=packer.pack_wire(wire)
            if unpack_wire(packed,packer.controls)!=wire:raise ValueError('stream codec changed a legacy field')
            count+=1;yield packed
    tables=dict(tracks=write_table(out/'tracks.jsonl.gz',records()),
        controls=write_table(out/'controls.jsonl.gz',packer.controls))
    for name,receipt in header['tables'].items():
        if name=='tracks':continue
        if receipt['path']!=name+'.jsonl.gz':raise ValueError('state table path differs')
        path=source/receipt['path'];digest=sha256();size=0
        with path.open('rb') as stream:
            for block in iter(lambda:stream.read(1024*1024),b''):digest.update(block);size+=len(block)
        if (size,digest.hexdigest())!=(receipt['bytes'],receipt['sha256']):raise ValueError('state table changed')
        os.link(path,out/receipt['path']);tables[name]=receipt
    _check(original)
    if count!=header['counts']['tracks'] or pins()!=codec:raise ValueError('codec or track domain changed')
    result=dict(header,schema_version=2,track_encoding=ENCODING,storage_pins=codec,tables=tables,
        repacked_from=original,all_legacy_track_fields_roundtripped=True,
        repacking_seconds=time.monotonic()-started,legacy_table_read='STREAMED_RECEIPT_CHECKED_JSONL')
    _durable_bytes(out/'result.json',_json(result),replace=False);return result


def _unit(task):
    row,out,memory_mib=task
    soft,hard=resource.getrlimit(resource.RLIMIT_AS);limit=memory_mib*1024*1024
    if hard!=resource.RLIM_INFINITY:limit=min(limit,hard)
    resource.setrlimit(resource.RLIMIT_AS,(limit,hard))
    _check(row['state']);header=_repack_unit(Path(row['state']['path']).parent,out)
    return dict(row,state=_receipt(Path(out)/'result.json'),analysis_seconds=row['seconds'],
        seconds=header['repacking_seconds'],analysis_worker_peak_rss_kib=row['worker_peak_rss_kib'],
        worker_peak_rss_kib=resource.getrusage(resource.RUSAGE_SELF).ru_maxrss,
        storage_controls=header['tables']['controls']['records'])


def repack_observed(source,out,*,jobs=8,memory_mib=8192):
    started=time.monotonic();source=Path(source).resolve();out=Path(out).absolute()
    if out.exists() or out.resolve()!=out or not 1<=jobs<=32 or memory_mib<256:
        raise ValueError('fresh output, 1..32 workers and >=256 MiB required')
    parent=_receipt(source/'result.json');r=json.loads((source/'result.json').read_bytes())
    if (r['schema'],r['schema_version'])!=(SCHEMA,1) or not compatible_pins(r['plan']['pins']):
        raise ValueError('observed state analysis contract differs')
    if json.loads((source/'plan.json').read_bytes())!=r['plan']:raise ValueError('source state plan differs')
    codec=pins();_durable_mkdir(out);rows=[]
    tasks=[(row,str(out/'units'/row['unit']),memory_mib) for row in r['units']]
    with ProcessPoolExecutor(max_workers=min(jobs,len(tasks) or 1),mp_context=multiprocessing.get_context('spawn')) as pool:
        pending={pool.submit(_unit,task):task[0]['unit'] for task in tasks}
        for future in as_completed(pending):
            row=future.result();rows.append(row)
            print(json.dumps(dict(done=len(rows),total=len(tasks),unit=row['unit'],
                seconds=round(row['seconds'],3),controls=row['storage_controls'])),flush=True)
    rows.sort(key=lambda row:row['unit']);_check(parent)
    if pins()!=codec:raise ValueError('state storage codec changed while repacking')
    if {x['unit'] for x in rows}!={x['unit'] for x in r['units']}:raise ValueError('state repack omitted original units')
    report=dict(r,units=rows,analysis_seconds=r['seconds'],seconds=time.monotonic()-started,
        storage_pins=codec,repacked_from=parent,all_legacy_track_fields_roundtripped=True,
        source_fixed_points_repeated=False)
    _durable_bytes(out/'plan.json',_json(r['plan']),replace=False)
    _durable_bytes(out/'result.json',_json(report),replace=False)
    return report


def main():
    p=argparse.ArgumentParser(description=__doc__)
    p.add_argument('--source',required=True);p.add_argument('--out',required=True)
    p.add_argument('--jobs',type=int,default=8);p.add_argument('--memory-mib',type=int,default=8192);a=p.parse_args()
    r=repack_observed(a.source,a.out,jobs=a.jobs,memory_mib=a.memory_mib)
    print(json.dumps(dict(units=len(r['units']),seconds=r['seconds'],fixed_points_repeated=False)),flush=True)


if __name__=='__main__':main()
