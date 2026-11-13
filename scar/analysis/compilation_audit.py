"""Read bounded original audit streams and match code-equivalent recipes.

Audit attempts are never paired by adjacency. A compatible replay is not an
observation of requested compiler options, source lineage or exec namespaces.
No candidate code is executed by this module.
"""
import argparse
import base64
from collections import Counter, defaultdict
from dataclasses import dataclass
from hashlib import sha256
from io import BytesIO
import json
from pathlib import Path
import sys
import time
import tokenize

from scar.analysis.call_compilation import supported_future_flag_mask
from scar.analysis.source_consumer_parents import _stamp
from scar.analysis.source_stage import _durable_bytes, _durable_mkdir
from scar.analysis.source_template_links import _json
from scar.ir.program.call_edges import CapturedCode
from scar.ir.record_codec import decode, loads, encode
from scar.trace.code_snapshot import describe_code
from scar.trace.files import open_binary, resolve


SCHEMA='scar.observed-compilation-matches'


@dataclass(frozen=True,slots=True)
class AuditSource:
    process_id: int
    kind: str
    sha256: str
    raw: bytes
    record: dict

    def text(self):
        if self.kind=='TEXT':return self.raw.decode('utf-8','surrogatepass')
        encoding,_=tokenize.detect_encoding(BytesIO(self.raw).readline)
        return self.raw.decode(encoding).replace('\r\n','\n').replace('\r','\n')


class CompilationAuditInputs:
    def __init__(self,trace,*,max_bytes=32_000_000,max_rows=20_000):
        self.path=Path(trace).absolute();self.sources={};self.events=[];self.metadata=[]
        self.receipts=[];self._guards={};self._total=0;self._rows=0
        self.max_bytes,self.max_rows=max_bytes,max_rows
        if self.path.resolve()!=self.path or self.path.is_symlink():raise ValueError('original canonical audit directory required')
        metas=tuple(sorted(self.path.glob('compilation-meta.*.json')))
        if tuple(self.path.glob('compilation-disabled.*.json')):
            raise ValueError('one or more compilation audit hooks were disabled')
        if not metas:raise ValueError('compilation audit capability was not recorded')
        self._inventory=metas;processes=set()
        for meta in metas:
            raw=self._file(meta,maximum=1_000_000);report=loads(raw)
            if ((report['schema'],report['schema_version'])!=('scar.compilation-audit-collection',1)
                    or report['python']!=sys.version or report['stopped'] or report['errors'] or report['io_failed']
                    or report['hook_installed'] is not True
                    or report['original_compile_options_observed'] is not False
                    or report['execution_namespace_observed'] is not False
                    or report['source_code_pairing_performed'] is not False):
                raise ValueError('incomplete audit capture or incompatible observation contract')
            pid=report['process_id']
            if type(pid) is not int or pid<1 or pid in processes or meta.name!=f'compilation-meta.{pid}.json':
                raise ValueError('audit issuer differs from its original process file')
            processes.add(pid);self.metadata.append(report)
            source_rows=self._stream(report['files']['sources'],pid,'sources')
            for row in source_rows:
                if row['source_kind'] not in ('TEXT','BYTES'):raise ValueError('unsupported audit source kind')
                payload=base64.b64decode(row['payload_base64'],validate=True)
                if (len(payload)!=row['size_bytes'] or sha256(payload).hexdigest()!=row['sha256']
                        or row['encoding']!=('utf-8-surrogatepass' if row['source_kind']=='TEXT' else None)):
                    raise ValueError('audit source byte identity differs')
                key=pid,row['source_kind'],row['sha256']
                if key in self.sources:raise ValueError('audit source deduplication key repeated')
                self.sources[key]=AuditSource(pid,row['source_kind'],row['sha256'],payload,row)
            events=self._stream(report['files']['events'],pid,'events');counts=Counter()
            for row in events:
                kind=row['kind'];counts[kind]+=1
                if kind=='COMPILE':
                    if (pid,row['source_kind'],row['source_sha256']) not in self.sources:
                        raise ValueError('compile observation references unrecorded source')
                elif kind=='CODE_EXECUTION':decode(CapturedCode,row['code'])
                elif kind!='GAP':raise ValueError('unsupported compilation audit event')
                self.events.append(row)
            expected=report['counts']
            if (any(counts[k]!=expected[k] for k in ('COMPILE','CODE_EXECUTION','GAP'))
                    or len(events)!=expected['events'] or len(source_rows)!=expected['sources']
                    or sum(s.record['size_bytes'] for s in self.sources.values() if s.process_id==pid)!=expected['unique_source_bytes']):
                raise ValueError('audit capture event/source counters differ')
        self.check()

    def _file(self,path,*,maximum=None):
        logical=Path(path);physical=resolve(logical)
        if (not logical.is_absolute() or logical.resolve()!=logical or logical.is_symlink()
                or physical.is_symlink() or not physical.is_file()):raise ValueError('audit input is not original canonical material')
        stamp=_stamp(physical);maximum=self.max_bytes-self._total if maximum is None else min(maximum,self.max_bytes-self._total)
        if stamp[2]>maximum:raise ValueError('audit input byte ceiling')
        with open_binary(logical) as stream:raw=stream.read(maximum+1)
        if len(raw)>maximum or _stamp(physical)!=stamp:raise ValueError('audit input grew or exceeded read ceiling')
        self._total+=len(raw);self._guards[logical]=physical,stamp
        self.receipts.append(dict(path=str(logical),bytes=len(raw),sha256=sha256(raw).hexdigest()))
        return raw

    def _stream(self,receipt,pid,family):
        path=self.path/f'compilation-{family}.{pid}.jsonl'
        if receipt['path']!=str(path):raise ValueError('audit stream left original process namespace')
        raw=self._file(path)
        if (len(raw),sha256(raw).hexdigest())!=(receipt['bytes'],receipt['sha256']):raise ValueError('audit stream receipt differs')
        rows=[]
        for index,line in enumerate(raw.splitlines(keepends=True),1):
            self._rows+=1
            if self._rows>self.max_rows or len(line)>2_000_000 or not line.endswith(b'\n'):
                raise ValueError('audit record/row ceiling or incomplete row')
            row=loads(line)
            if ((row['schema'],row['schema_version'])!=(f'scar.compilation-audit-{family}',1)
                    or row['index']!=index or row['process_id']!=pid):raise ValueError('audit stream record identity differs')
            rows.append(row)
        if len(rows)!=receipt['rows']:raise ValueError('audit EOF row count differs')
        return rows

    def check(self):
        if tuple(sorted(self.path.glob('compilation-meta.*.json')))!=self._inventory:
            raise ValueError('audit process inventory changed')
        if any(resolve(p)!=physical or p.is_symlink() or physical.is_symlink() or _stamp(physical)!=stamp
                for p,(physical,stamp) in self._guards.items()):raise ValueError('admitted audit material changed')

    def guard_stamps(self):
        self.check()
        return {physical:stamp for physical,stamp in self._guards.values()}


def match_compilation(trace,out,*,max_attempts=20_000,max_seconds=120):
    """Enumerate finite replay candidates; exact root CodeID selects matches."""
    started=time.monotonic();inputs=CompilationAuditInputs(trace);out=Path(out).absolute()
    if out.resolve()!=out or out.exists():raise ValueError('fresh canonical compilation match output required')
    _durable_mkdir(out)
    compile_events=defaultdict(list);roots=defaultdict(list)
    for event in inputs.events:
        pid=event['process_id']
        if event['kind']=='COMPILE':compile_events[pid,event['source_kind'],event['source_sha256']].append(event['index'])
        elif event['kind']=='CODE_EXECUTION':roots[pid,event['code']['key']].append(event)
    matches=[];unmatched=[];attempts=0;cache={};errors=Counter();future=supported_future_flag_mask()
    for (pid,key),events in sorted(roots.items()):
        observed=decode(CapturedCode,events[0]['code']);recipes=[]
        if any(event['code']!=events[0]['code'] for event in events):raise ValueError('one code fingerprint has conflicting descriptors')
        flags=observed.flags&future
        if observed.flags&~future:
            unmatched.append(dict(process_id=pid,code=encode(observed),reason='NON_MODULE_EXECUTION_CODE_REPLAY_NOT_IMPLEMENTED'));continue
        for source_key,source in sorted(inputs.sources.items()):
            if source.process_id!=pid:continue
            payload=source.raw if source.kind=='BYTES' else source.text()
            for mode in ('exec','eval','single'):
                for optimize in (0,1,2):
                    signature=source_key,observed.filename,mode,flags,optimize
                    if signature not in cache:
                        if attempts>=max_attempts or time.monotonic()-started>max_seconds:
                            raise TimeoutError('compilation replay candidate budget exhausted')
                        attempts+=1
                        try:
                            code=compile(payload,observed.filename,mode,flags=flags,dont_inherit=True,optimize=optimize)
                            cache[signature]=describe_code(code)
                        except (SyntaxError,ValueError,TypeError,OverflowError,RecursionError) as error:
                            errors[type(error).__name__]+=1;cache[signature]=None
                    if cache[signature]!=encode(observed):continue
                    recipes.append(dict(source_kind=source.kind,source_sha256=source.sha256,
                        source_process_id=pid,source_record=source.record['index'],
                        compile_attempt_events=compile_events[source_key],filename=observed.filename,
                        mode=mode,flags=flags,dont_inherit=True,optimize=optimize))
        row=dict(process_id=pid,code=encode(observed),execution_events=[e['index'] for e in events],recipes=recipes)
        if recipes:matches.append(row)
        else:unmatched.append(dict(**row,reason='NO_CAPTURED_SOURCE_WITH_COMPATIBLE_REPLAY_IN_DECLARED_SEARCH_DOMAIN'))
    inputs.check()
    report=dict(schema=SCHEMA,schema_version=1,trace=str(inputs.path),python=sys.version,
        capture_inputs=inputs.receipts,matches=matches,unmatched=unmatched,
        counts=dict(sources=len(inputs.sources),execution_code_templates=len(roots),matched=len(matches),
            compatible_recipes=sum(len(m['recipes']) for m in matches),compile_attempts=attempts,
            failed_candidate_compiles=dict(errors)),
        search_domain=dict(modes=['exec','eval','single'],optimize=[0,1,2],
            flags='OBSERVED_ROOT_FUTURE_FLAGS_ONLY',dont_inherit=True),
        original_compile_options_proven=False,source_code_temporal_pairing_proven=False,
        execution_namespace_proven=False,target_executed=False,first_stage_complete=False,
        seconds=time.monotonic()-started)
    _durable_bytes(out/'result.json',_json(report),replace=False)
    return report


def main():
    parser=argparse.ArgumentParser(description=__doc__)
    parser.add_argument('--trace',required=True);parser.add_argument('--out',required=True)
    args=parser.parse_args();r=match_compilation(args.trace,args.out)
    print(json.dumps(dict(counts=r['counts'],seconds=r['seconds'])),flush=True)


if __name__=='__main__':main()
