"""Connect owned boundary markers, original CALLs, OS work and source ports.

Only per-thread syscall order and explicit marker offsets are used. Markers
are collector work. Other work is either enclosed by a balanced observed
native call or remains unassigned; enclosure is not exclusive program origin.
"""
from collections import Counter,defaultdict
from hashlib import sha256
import argparse
import json
from pathlib import Path
import time

from scar.trace.capture_coordinates import bind_capture_coordinates
from scar.trace.resource_scopes import read_resource_scopes,RECORD,SCHEMA as MARKERS
from scar.trace.os_resources import _scan,_number,_interface_family
from scar.analysis.call_operand_reader import read_call_operands
from scar.analysis.source_body_activations import _SourceAnchors
from scar.analysis.source_body_interfaces import BodyInterfaceResolver
from scar.analysis.source_observed_codes import ObservedSourceCodeProvider
from scar.analysis.source_observed_calls import ObservedSourceCallsiteIndex
from scar.analysis.program_view import ProgramView,_digest
from scar.analysis.source_template_links import _json
from scar.analysis.source_stage import _durable_bytes,_durable_mkdir
from scar.analysis.source_consumer_parents import _stamp
from scar.analysis.source_symbol_variants import _table
from scar.analysis.normal_output import write_table
from scar.ir.program import resource_scopes as R
from scar.ir.program import source_productions as P
from scar.ir.program.ids import ProviderID
from scar.ir.program.providers import ProviderArtifact,ProviderFactReference
from scar.ir.record_codec import encode,decode


SCHEMA='scar.source-resource-scopes'


def _receipt(path):
    path=Path(path);raw=path.read_bytes()
    return dict(path=str(path),sha256=sha256(raw).hexdigest(),bytes=len(raw))


def _pins():
    from scar.trace import resource_scopes,os_resources,capture_coordinates
    from scar.analysis import source_body_activations,source_observed_codes,source_observed_calls
    return {**source_observed_codes.request_code_pins(),**{name:sha256(Path(module.__file__).read_bytes()).hexdigest() for name,module in (
        ('producer',__import__(__name__,fromlist=['__file__'])),('types',R),
        ('markers',resource_scopes),('os_reader',os_resources),('coordinates',capture_coordinates),
        ('source_anchors',source_body_activations),('call_index',source_observed_calls))}}


def _physical_members(coordinates,artifacts):
    """Use exact retained logical/physical aliases, never hash-only PID guesses."""
    result={}
    for index,artifact in enumerate(artifacts):
        rows=[row for row in coordinates.report['membership']
            if row['local_path']==artifact.uri and
            (row['artifact']['sha256'],row['artifact']['size_bytes'],row['artifact']['schema'])==
            (artifact.sha256,artifact.size_bytes,artifact.schema)]
        if len(rows)==1:result[index]=decode(ProviderArtifact,rows[0]['artifact'])
    return result


def derive_resource_scopes(coordinates,capture,trace):
    membership=coordinates.report.get('resource_scope_membership')
    if membership is None:raise ValueError('capture has no bound resource scope marker channel')
    declaration=membership['manifest'];metadata=Path(declaration['uri'])
    markers=read_resource_scopes(metadata,expected_sha256=declaration['sha256'])
    if markers.metadata['process_id']!=coordinates.target_process.pid:
        raise ValueError('resource marker process differs from its bound capture')
    attempts={(row.invocation,row.index):row for row in trace.attempts}
    files,artifacts,lines,calls=_scan(Path(capture)/'os',128_000_000,2_000_000,interface_work=True)
    members=_physical_members(coordinates,artifacts)
    events={event.sequence:event for event in markers.events};os_markers=defaultdict(list)
    candidates=[];unassigned=[];frontiers=[]
    def fact(call,entry=False):
        artifact=members.get(call['file'],artifacts[call['file']])
        return ProviderFactReference(artifact,'#/lines/'+str(call['first_line'] if entry else call['line']))
    for call in calls:
        if not call.get('interface_record'):continue
        artifact=members.get(call['file']);process=(coordinates.process_for(artifact,call['tid']) if artifact else None)
        if process is None or process.id!=coordinates.target_process.id:
            unassigned.append((fact(call),'OUTSIDE_VERIFIED_TARGET_PROCESS'));continue
        a=call['args'];is_marker=False
        if call['name']=='pwrite64' and len(a)==4 and _number(a[0])==markers.metadata['marker_fd']:
            offset=_number(a[3]);sequence=(offset//RECORD.size+1 if offset is not None and offset>=0 and offset%RECORD.size==0 else None)
            event=events.get(sequence)
            if (event is not None and event.native_tid==call['tid']
                    and _number(a[2])==RECORD.size and call['result']==RECORD.size):
                os_markers[sequence].append(call);is_marker=True
        if not is_marker:candidates.append(call)
    if set(os_markers)!=set(events) or any(len(v)!=1 for v in os_markers.values()):
        raise ValueError('marker offsets have no unique exact native-TID pwrite receipts')
    by_tid=defaultdict(list)
    for event in markers.events:by_tid[event.native_tid].append(event)
    scopes=[];ranges=defaultdict(list);scope_calls={}
    for tid,rows in by_tid.items():
        stack=[];previous=0
        for event in rows:
            call=os_markers[event.sequence][0]
            if call['first_line']<=previous:raise ValueError('marker file and per-thread syscall orders disagree')
            previous=call['line']
            if event.kind is R.ScopeEventKind.BEGIN:stack.append(event);continue
            if not stack or stack[-1].scope!=event.scope:
                raise ValueError('resource marker completions are not properly nested')
            begin=stack.pop();attempt=attempts.get((begin.caller,begin.attempt_index))
            if attempt is None:raise ValueError('resource scope has no original CALL attempt')
            opening=os_markers[begin.sequence][0]
            identity=ProviderID(_digest((SCHEMA,coordinates.run.id,begin,event)))
            row=R.ObservedResourceScope(identity,begin,event,attempt.anchor,fact(opening),fact(call,True))
            scopes.append(row);scope_calls[identity]=attempt
            ranges[tid].append((opening['line'],call['first_line'],identity))
        frontiers.extend(dict(reason='UNCLOSED_NATIVE_SCOPE',begin=encode(event.source)) for event in stack)
    # Find the innermost balanced enclosing region. Calls spanning a marker
    # boundary remain unassigned; incomplete ranges never acquire later work.
    for tid in ranges:ranges[tid].sort()
    work=[]
    for call in candidates:
        enclosing=[row for row in ranges.get(call['tid'],())
            if row[0]<call['first_line'] and call['line']<row[1]]
        if not enclosing:
            unassigned.append((fact(call),'NO_BALANCED_ENCLOSING_SCOPE'));continue
        selected=max(enclosing,key=lambda row:row[0])
        work.append(R.ScopedResourceWork(selected[2],fact(call),call['name'],
            _interface_family(call['name']),call['result']))
    return dict(scopes=tuple(sorted(scopes,key=lambda row:row.id.value)),work=tuple(work),
        markers=tuple((events[i].source,fact(os_markers[i][0])) for i in sorted(events)),
        unassigned=tuple(unassigned),frontiers=tuple(frontiers)),scope_calls,markers


def _source_bindings(index,rows,attempts):
    resolver=BodyInterfaceResolver(index.view)
    for unit,contexts in index._contexts.items():
        resolver.plans.update(((unit,key),context) for key,context in contexts.items())
    anchors=_SourceAnchors(index,resolver);bindings=[]
    for scope in rows['scopes']:
        for anchor in anchors.select(scope.begin.caller.process_id,attempts[scope.id].site):
            bindings.append(R.SourceResourceScopeBinding(scope.id,anchor))
    return tuple(bindings)


def build_resource_scopes(capture,out,*,catalog=None,project_root=None,graph_check_out=None,index=None):
    started=time.monotonic();capture=Path(capture).resolve();out=Path(out).absolute()
    if out.exists() or out.resolve()!=out:raise ValueError('fresh canonical resource scope output required')
    pins=_pins();coordinate_path=capture/'capture-coordinates.json'
    coordinates=bind_capture_coordinates(capture,max_bytes=512_000_000,max_lines=2_000_000,profile_uri=str(coordinate_path))
    if coordinate_path.read_bytes()!=coordinates.payload:raise ValueError('stored capture coordinates differ')
    trace_path=capture/'trace'
    if index is not None:
        if (Path(index.codes.trace.directory).resolve()!=trace_path or
                catalog is not None and Path(catalog).resolve()!=index.view.catalog.path):
            raise ValueError('resource builder index belongs to another original source/capture')
        view=index.view;catalog=view.catalog.path;trace=index.codes.trace
    elif catalog is not None:
        view=ProgramView(catalog);codes=ObservedSourceCodeProvider(view,trace_path,project_root)
        index=ObservedSourceCallsiteIndex(codes);trace=codes.trace
    else:
        index=None;trace=read_call_operands(trace_path,project_root)
    rows,attempts,markers=derive_resource_scopes(coordinates,capture,trace)
    bindings=();source_frontiers=[]
    if index is not None:
        bindings=_source_bindings(index,rows,attempts)
        bound={row.scope for row in bindings}
        source_frontiers=[dict(scope=encode(scope.id),reason='SOURCE_OPERATION_NOT_CORRESPONDED')
            for scope in rows['scopes'] if scope.id not in bound]
        index.check()
    _durable_mkdir(out);tables={}
    tables['scopes']=write_table(out/'scopes.jsonl.gz',rows['scopes'])
    tables['work']=write_table(out/'work.jsonl.gz',rows['work'])
    tables['markers']=write_table(out/'markers.jsonl.gz',rows['markers'])
    tables['unassigned']=write_table(out/'unassigned.jsonl.gz',rows['unassigned'])
    tables['frontiers']=write_table(out/'frontiers.jsonl.gz',(*rows['frontiers'],*source_frontiers))
    shards={}
    for unit in sorted({row.anchor.operation.unit for row in bindings}):
        folder=out/'units'/unit;_durable_mkdir(folder)
        table=write_table(folder/'bindings.jsonl.gz',(row for row in bindings if row.anchor.operation.unit==unit))
        shards[unit]=dict(path='units/'+unit,bindings=table)
    summary=dict(scopes=len(rows['scopes']),enclosed_work=len(rows['work']),
        excluded_marker_writes=len(rows['markers']),unassigned_work=len(rows['unassigned']),
        source_bindings=len(bindings),source_bound_scopes=len({r.scope for r in bindings}),
        source_frontiers=len(source_frontiers),unclosed_scopes=len(rows['frontiers']),
        syscalls=dict(Counter(row.syscall for row in rows['work'])))
    report=dict(schema=SCHEMA,schema_version=1,capture=str(capture),catalog=None if catalog is None else str(Path(catalog).resolve()),
        project_root=project_root,coordinates=encode(coordinates.artifact),pins=pins,tables=tables,shards=shards,summary=summary,
        scope_ownership_condition=markers.metadata['ownership_condition'],
        non_marker_work_may_include_nested_callbacks_and_collector_overhead=True,
        direct_program_origin_proven=False,effects_closed=False,readiness_established=False,
        clock_matching_used=False,source_bodies_copied=False,first_stage_complete=False,seconds=time.monotonic()-started)
    if pins!=_pins():raise ValueError('resource scope implementation changed during build')
    _durable_bytes(out/'result.json',_json(report),replace=False)
    if graph_check_out is not None:
        from scar.analysis.source_resource_scope_view import verify_resource_scope_graph
        verify_resource_scope_graph(out,graph_check_out,index=index)
    return report


class ResourceScopeStore:
    """Read stored typed scopes against original OS, CALL and source inputs."""
    def __init__(self,path,*,index=None):
        self.path=Path(path).resolve();self.raw=(self.path/'result.json').read_bytes();r=json.loads(self.raw);self.report=r
        if (r['schema'],r['schema_version'],r['pins'])!=(SCHEMA,1,_pins()):
            raise ValueError('resource scope schema or implementation differs')
        if (any(r[name]is not False for name in ('direct_program_origin_proven','effects_closed',
                'readiness_established','clock_matching_used','source_bodies_copied','first_stage_complete'))
                or r['non_marker_work_may_include_nested_callbacks_and_collector_overhead']is not True):
            raise ValueError('resource scope publication claims unproved effects or ownership')
        self.coordinates=bind_capture_coordinates(r['capture'],max_bytes=512_000_000,max_lines=2_000_000,
            profile_uri=r['coordinates']['uri'])
        if encode(self.coordinates.artifact)!=r['coordinates']:raise ValueError('resource scope capture changed')
        if index is None and r['catalog'] is not None:
            view=ProgramView(r['catalog']);codes=ObservedSourceCodeProvider(view,Path(r['capture'])/'trace',r['project_root'])
            index=ObservedSourceCallsiteIndex(codes)
        self.index=index
        trace=(index.codes.trace if index is not None else read_call_operands(Path(r['capture'])/'trace',r['project_root']))
        if (Path(trace.directory).resolve()!=Path(r['capture'])/'trace'
                or index is not None and str(index.view.catalog.path)!=r['catalog']):
            raise ValueError('resource scope index uses another source catalog or capture')
        expected,attempts,_=derive_resource_scopes(self.coordinates,r['capture'],trace)
        expected_bindings=() if index is None else _source_bindings(index,expected,attempts)
        kinds=dict(scopes=R.ObservedResourceScope,work=R.ScopedResourceWork,
            markers=tuple[ProviderFactReference,ProviderFactReference],
            unassigned=tuple[ProviderFactReference,str],frontiers=None)
        self.rows={};self.guards={}
        for name,kind in kinds.items():
            receipt=r['tables'][name];p=self.path/receipt['path'];before=_stamp(p)
            values=tuple(decode(kind,row,record_tags=P.PRODUCTION_RECORD_TAGS) if kind else row for row in _table(self.path,receipt))
            if _stamp(p)!=before:raise ValueError('resource scope table changed while reading')
            self.guards[p]=before;self.rows[name]=values
            if name!='frontiers' and values!=expected[name]:raise ValueError('stored resource scopes differ from original marker/CALL/OS evidence')
        bound={row.scope for row in expected_bindings}
        expected_frontiers=(*expected['frontiers'],*(dict(scope=encode(scope.id),reason='SOURCE_OPERATION_NOT_CORRESPONDED')
            for scope in expected['scopes'] if index is not None and scope.id not in bound))
        if self.rows['frontiers']!=tuple(expected_frontiers):raise ValueError('resource scope frontier denominator differs')
        loaded=[]
        for unit,s in r['shards'].items():
            if s['path']!='units/'+unit:raise ValueError('resource scope unit shard differs')
            folder=self.path/s['path'];p=folder/s['bindings']['path'];before=_stamp(p)
            rows=tuple(decode(R.SourceResourceScopeBinding,row,record_tags=P.PRODUCTION_RECORD_TAGS) for row in _table(folder,s['bindings']))
            if any(row.anchor.operation.unit!=unit for row in rows) or _stamp(p)!=before:
                raise ValueError('resource scope binding unit changed')
            loaded.extend(rows);self.guards[p]=before
        order=lambda row:_digest(row)
        if tuple(sorted(loaded,key=order))!=tuple(sorted(expected_bindings,key=order)):
            raise ValueError('stored resource source ports differ from original source/CALL correspondence')
        self.bindings=tuple(loaded);self.guards[self.path/'result.json']=_stamp(self.path/'result.json')
        self.check()

    def check(self):
        if any(_stamp(path)!=stamp for path,stamp in self.guards.items()) or self.raw!=(self.path/'result.json').read_bytes():
            raise ValueError('admitted resource scope publication changed')
        if self.index is not None:self.index.codes._check_trace()


def main():
    p=argparse.ArgumentParser(description=__doc__);p.add_argument('--capture',required=True)
    p.add_argument('--catalog');p.add_argument('--project-root',required=True);p.add_argument('--out',required=True)
    p.add_argument('--graph-check-out')
    a=p.parse_args();r=build_resource_scopes(a.capture,a.out,catalog=a.catalog,project_root=a.project_root,
        graph_check_out=a.graph_check_out)
    print(json.dumps(r['summary'],indent=2))


if __name__=='__main__':main()
