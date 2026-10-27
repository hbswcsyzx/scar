"""Normal read-only owner of capture-observed Python source bytes.

This owner does not prepare source graphs or certify loader-time bytes. A
CodeID/filename observation selects source bytes; ordinary CodeWitness resolve
must separately reproduce the full captured descriptor before matching it.
"""
from __future__ import annotations

import base64
from dataclasses import asdict, dataclass
from hashlib import sha256
from pathlib import Path, PurePosixPath
import re

from scar.analysis.call_trace_reader import CallTraceScan, scan_call_trace
from scar.ir.program.call_edges import CallEdgeBudget, CapturedCode
from scar.ir.program.providers import ProviderArtifact, ProviderFactReference
from scar.ir.record_codec import encode, loads as strict_loads
from scar.ir.semantics_v2 import SourceSnapshot
from scar.trace.captured_sources import (PROGRAM_PORTS_PROFILE, SOURCE_SCHEMA, SOURCE_SCOPE,
    validate_source_metadata, validate_source_row)
from scar.trace.files import open_binary, resolve


def _need(value, detail):
    if not value:
        raise ValueError('captured source owner: '+detail)


def _stamp(path):
    value=path.stat()
    return value.st_dev,value.st_ino,value.st_size,value.st_mtime_ns,value.st_ctime_ns


@dataclass(frozen=True, slots=True)
class CapturedSourceBudget:
    max_metadata_bytes: int = 8_000_000
    max_rows_bytes: int = 96_000_000
    max_row_bytes: int = 4_000_000
    max_files: int = 1024
    max_source_bytes: int = 64_000_000
    max_codes: int = 8192
    max_code_bytes: int = 32_000_000

    def __post_init__(self):
        _need(all(type(v) is int and v>0 for v in asdict(self).values()),'budgets must be positive exact integers')


class CapturedSourceUnavailable(LookupError):
    """Retained source frontier; never authorizes fallback to a live filename."""


@dataclass(frozen=True, slots=True)
class CapturedSourceText:
    snapshot: SourceSnapshot
    text: str
    source: ProviderFactReference
    declaration: ProviderFactReference
    code_sources: ProviderFactReference
    original_encoding: str
    raw_sha256: str
    raw_bytes: int
    observed_python: str
    unchanged_at_close: bool
    observation_frontier: str | None
    compiler_match: str = 'NOT_CHECKED'
    loader_bytes_observed: bool = False


class _DiscardFrames:
    def entry(self,value): pass
    def exit(self,value): pass


class CapturedSourceOwner:
    """Read pinned metadata/rows and their original closed code membership.

    An optional normal CallTraceScan can be reused from this fresh caller
    session. Its code/meta bytes and exact code anchors are still rechecked;
    it is never a serialized proof token. Without one the ordinary scanner
    supplies the original scan. No method opens/stats the source filenames.
    """
    def __init__(self, trace_directory, *, project_root, metadata: ProviderArtifact,
                 budget=CapturedSourceBudget(), frame_scan=None, frame_budget=CallEdgeBudget()):
        _need(type(metadata) is ProviderArtifact and metadata.schema==SOURCE_SCHEMA+'/1',
              'explicit captured-source metadata artifact required')
        _need(type(budget) is CapturedSourceBudget,'typed captured-source budget required')
        budget.__post_init__()
        _need(type(frame_budget) is CallEdgeBudget,'typed normal frame budget required')
        self._budget=budget;self._inputs=[];self._stamps={};self._closed=False
        self.counts={'stored_bytes_read':0,'decoded_bytes_read':0,'source_rows':0,'source_bytes':0,
                     'frame_scan_stored_bytes':0,'frame_scan_decoded_bytes':0}
        directory=Path(trace_directory).absolute()
        _need(directory==directory.resolve() and directory.is_dir() and not directory.is_symlink(),
              'original trace directory must be canonical')
        raw=self._read(metadata,budget.max_metadata_bytes)
        document=strict_loads(raw.decode('utf8'))
        pid=document.get('process_id')
        _need(type(pid) is int and pid>0 and metadata.uri==str(directory/f'captured-source-meta.{pid}.json'),
              'source metadata process/namespace differs')
        _need(frame_scan is None or type(frame_scan) is CallTraceScan,'normal frame scan required, not JSON')
        if frame_scan is None:
            frame_scan=scan_call_trace(directory,str(project_root),frame_budget,sink=_DiscardFrames())
            self.counts['frame_scan_decoded_bytes']=sum(r.raw_bytes for r in frame_scan.files)
            self.counts['frame_scan_stored_bytes']=sum(resolve(r.path).stat().st_size for r in frame_scan.files)
        _need(frame_scan.directory==str(directory),'normal frame scan namespace differs')
        files={(r.process_id,r.family):r for r in frame_scan.files}
        call_meta=files.get((pid,'meta'));codes=files.get((pid,'codes'))
        _need(call_meta is not None and codes is not None,'original process/code declarations absent')
        self._frame_files=tuple(frame_scan.files)
        call_artifact=ProviderArtifact(call_meta.path,call_meta.raw_sha256,call_meta.raw_bytes,'scar.call-edge-trace')
        caller=strict_loads(self._read(call_artifact,budget.max_metadata_bytes).decode('utf8'))
        _need(caller in frame_scan.metadata and caller.get('process_id')==pid
              and caller.get('project_root')==str(project_root) and caller.get('capture_profile')==PROGRAM_PORTS_PROFILE
              and caller.get('scope_policy')==SOURCE_SCOPE and caller.get('instruction_monitoring') is False
              and caller.get('captured_sources')==encode(metadata),
              'closed original call/source membership differs or unsupported profile')
        version=re.match(r'([0-9]+\.[0-9]+)\.[0-9]+(?:\s|$)',caller.get('python',''))
        _need(version is not None,'captured interpreter version is absent')
        code_artifact=ProviderArtifact(codes.path,codes.raw_sha256,codes.raw_bytes,'scar.call-codes/1')
        code_raw=self._read(code_artifact,budget.max_code_bytes)
        captures={r.code.key:r for r in frame_scan.captures if r.process_id==pid}
        _need(len(captures)<=budget.max_codes,'code membership count budget exceeded')
        actual={}
        for number,line in enumerate(code_raw.splitlines(keepends=True),1):
            from scar.ir.record_codec import decode
            _need(line.endswith(b'\n') and bool(line.strip()),'incomplete original code row')
            captured=decode(CapturedCode,strict_loads(line.decode('utf8')))
            capture=captures.get(captured.key)
            _need(capture is not None and capture.code==captured and capture.anchor.path==codes.path,
                  'original captured descriptor differs from normal code scan')
            if capture.anchor.line_number==number:
                _need(capture.anchor.line_sha256==sha256(line).hexdigest(),'original CodeID line digest differs')
            _need(captured.key not in actual,'duplicate original CodeID source membership')
            actual[captured.key]=captured
        _need(len(actual)==codes.lines and actual=={key:r.code for key,r in captures.items()},
              'original code membership/row count differs')
        by_path=validate_source_metadata(document,pid,{key:code.filename for key,code in actual.items()})
        _need(len(by_path)<=budget.max_files,'source inventory count budget exceeded')
        declared=document['file']
        _need(declared['uri']==str(directory/f'captured-sources.{pid}.jsonl'),
              'source rows do not retain their original process namespace')
        rows_artifact=ProviderArtifact(declared['uri'],declared['sha256'],declared['size_bytes'],SOURCE_SCHEMA+'/1')
        rows=self._read(rows_artifact,budget.max_rows_bytes)
        texts={}
        for index,line in enumerate(rows.splitlines(keepends=True),1):
            _need(line.endswith(b'\n') and len(line)<=budget.max_row_bytes,'source row line budget/framing differs')
            row=strict_loads(line.decode('ascii'));validate_source_row(row,document,index,by_path)
            _need(row.get('status')=='ARCHIVED_SOURCE_BYTES' and row.get('observation')=='FIRST_DESCRIPTOR_OBSERVATION'
                  and row.get('frontier') is None,'source row is not a first observed byte snapshot')
            filename=row['path'];item=by_path[filename]
            _need(PurePosixPath(filename).is_absolute() and filename not in texts
                  and type(item.get('unchanged_at_close')) is bool,'source snapshot filename/close observation differs')
            raw=base64.b64decode(row['raw_base64'],validate=True)
            text=raw.decode(row['encoding']).replace('\r\n','\n').replace('\r','\n')
            size=len(text.encode('utf8'));self.counts['source_bytes']+=size
            _need(self.counts['source_bytes']<=budget.max_source_bytes,'normalized source byte budget exceeded')
            # Generated source layers use normalized UTF8 text and major.minor
            # version. Original raw encoding/hash are separately retained.
            snapshot=SourceSnapshot(filename,'sha256:'+row['normalized_sha256'],
                                    encoding='utf-8',python_version=version.group(1))
            position=next(i for i,v in enumerate(document['files'])if v['path']==filename)
            texts[filename]=CapturedSourceText(snapshot,text,
                ProviderFactReference(rows_artifact,f'#/lines/{index}'),
                ProviderFactReference(metadata,f'#/files/{position}'),
                ProviderFactReference(metadata,'#/code_sources'),row['encoding'],row['raw_sha256'],len(raw),
                caller['python'],item['unchanged_at_close'],item.get('frontier'))
            self.counts['source_rows']+=1
        _need(self.counts['source_rows']==declared['rows'],'source row denominator differs')
        self._texts=texts;self._codes=actual;self._captures=captures;self._metadata=metadata
        self._code_artifact=code_artifact;self._call_artifact=call_artifact
        self._membership={r['code']:i for i,r in enumerate(document['code_sources'])}
        self._frontiers=tuple((r['path'],r['frontier'])for r in document['files']if r['status']=='UNAVAILABLE')
        self.require_unchanged()

    def _read(self,artifact,limit):
        _need(type(artifact) is ProviderArtifact and 0<=artifact.size_bytes<=limit,'artifact decoded byte budget exceeded')
        logical=Path(artifact.uri);physical=resolve(logical)
        _need(logical.is_absolute() and physical.is_file() and not physical.is_symlink()
              and physical==physical.resolve(),'retained artifact path is absent or noncanonical')
        before=_stamp(physical)
        with open_binary(logical) as stream: raw=stream.read(artifact.size_bytes+1)
        _need(before==_stamp(physical) and len(raw)==artifact.size_bytes
              and sha256(raw).hexdigest()==artifact.sha256,'original source/code artifact bytes changed or SHA differs')
        self._stamps[str(physical)]=before;self._inputs.append(artifact)
        self.counts['stored_bytes_read']+=before[2];self.counts['decoded_bytes_read']+=len(raw)
        return raw

    def require_unchanged(self):
        _need(not self._closed,'captured source owner is closed')
        _need(all(_stamp(Path(p))==stamp for p,stamp in self._stamps.items()),'original captured source inputs changed')

    def captured_codes(self):
        self.require_unchanged()
        return tuple(self._codes.values())

    def snapshot(self,captured):
        self.require_unchanged()
        _need(type(captured) is CapturedCode and self._codes.get(captured.key)==captured,
              'CodeID/descriptor is not an original member of this capture')
        original=self._texts.get(captured.filename)
        if original is None:
            reason=dict(self._frontiers).get(captured.filename,'CAPTURED_SOURCE_UNAVAILABLE')
            raise CapturedSourceUnavailable(captured.filename+': '+str(reason))
        return original.snapshot

    def archived_source(self,snapshot):
        self.require_unchanged()
        _need(type(snapshot) is SourceSnapshot,'typed exact source snapshot required')
        original=self._texts.get(snapshot.path)
        _need(original is not None and original.snapshot==snapshot,'original source filename/fingerprint/version differs')
        return original

    def code_membership(self,captured):
        self.snapshot(captured)
        capture=self._captures[captured.key]
        return {'code_source':encode(ProviderFactReference(self._metadata,f'#/code_sources/{self._membership[captured.key]}')),
                'captured_code':encode(ProviderFactReference(self._code_artifact,f'#/lines/{capture.anchor.line_number}')),
                'captured_code_anchor':encode(capture.anchor)}

    def receipts(self):
        self.require_unchanged()
        return {'inputs':encode(tuple(self._inputs)),'frame_files':encode(self._frame_files),
                'compiler_match':'NOT_CHECKED','loader_bytes_observed':False}

    def frontiers(self):
        self.require_unchanged()
        return self._frontiers

    def close(self):
        self.require_unchanged();self._closed=True;self._texts.clear()

    def __enter__(self):
        self.require_unchanged();return self

    def __exit__(self,*ignored):
        self.close()
