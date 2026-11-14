"""Lossless shared-control and definition-set codec for stored binding tracks.

No solving or application observation occurs here. All states, incoming and
outgoing sets, reads, transitions, limits and frontiers survive the roundtrip.
Only immutable compiler-record storage is interned; runtime identities are
never inferred from these pools.
"""
from hashlib import sha256
import json
import os
from pathlib import Path
import time

from scar.analysis.normal_output import write_table
from scar.analysis.source_symbol_variants import _table
from scar.analysis.source_stage import _durable_bytes,_durable_mkdir
from scar.analysis.source_template_links import _json
from scar.ir.program import binding_track_storage as B,source_productions as P,source_state as S
from scar.ir.record_codec import decode,encode


ENCODING='SHARED_CONTROL_DEFINITION_SETS_V1'
_FIELDS=frozenset(S.StoredBindingTrack.__dataclass_fields__)


def pins():
    return dict(codec=sha256(Path(__file__).read_bytes()).hexdigest(),
        types=sha256(Path(B.__file__).read_bytes()).hexdigest())


def _mask(values,count):
    bits=0;previous=-1
    for value in values:
        if type(value)is not int or not previous<value<count:
            raise ValueError('definition set must contain ordered unique track-local ordinals')
        bits|=1<<value;previous=value
    return format(bits,'x')


def _values(mask,count):
    if (type(mask)is not str or not mask or any(c not in '0123456789abcdef' for c in mask)
            or len(mask)>1 and mask[0]=='0'):
        raise ValueError('noncanonical definition bitset')
    bits=int(mask,16)
    if bits.bit_length()>count:raise ValueError('definition bitset exceeds its track domain')
    result=[]
    while bits:
        bit=bits&-bits;result.append(bit.bit_length()-1);bits^=bit
    return result


class TrackPacker:
    def __init__(self):self.controls=[];self._controls={}

    def _control(self,control):
        # A wire key is stable for both typed publication and legacy repacking.
        typed=type(control)is B.SharedBindingControl
        key=_json((encode(control.source_function),control.max_states,control.max_stack)) if typed else _json(
            (control['source_function'],control['max_states'],control['max_stack']))
        if key in self._controls:
            ordinal=self._controls[key]
            prior=self.controls[ordinal]
            if type(prior)is not type(control) or control!=prior:
                raise ValueError('one function/control budget has different matched topology')
            return ordinal
        ordinal=len(self.controls);self._controls[key]=ordinal;self.controls.append(control);return ordinal

    def pack(self,track):
        if type(track)is not S.StoredBindingTrack:raise TypeError('expected a stored binding track')
        control=B.SharedBindingControl(track.source_function,track.max_states,track.max_stack,
            tuple((s.port,s.stack) for s in track.states),track.transitions,track.traversal_complete)
        ordinal=self._control(control);sets=[];by_mask={};by_identity={}
        def intern(values):
            # The input track owns all these immutable tuples for this call.
            # Identity avoids repeatedly hashing long identical IR tuples.
            identity=id(values)
            if identity in by_identity:return by_identity[identity]
            mask=_mask(values,len(track.definitions));i=by_mask.get(mask)
            if i is None:i=len(sets);by_mask[mask]=i;sets.append(mask)
            by_identity[identity]=i;return i
        states=tuple((intern(s.incoming),intern(s.outgoing)) for s in track.states)
        reads=tuple((r.state,r.access,r.anchors,intern(r.definitions)) for r in track.reads)
        return B.PackedBindingTrack(ordinal,track.namespace,track.max_updates,track.definitions,
            tuple(sets),states,reads,track.frontiers,track.dataflow_complete)

    def pack_wire(self,track):
        if set(track)!=_FIELDS:raise ValueError('legacy binding-track field domain differs')
        control={k:track[k] for k in ('source_function','max_states','max_stack','transitions','traversal_complete')}
        control['states']=[[s['port'],s['stack']] for s in track['states']]
        ordinal=self._control(control);sets=[];by_values={}
        def intern(values):
            key=tuple(values);i=by_values.get(key)
            if i is None:i=len(sets);by_values[key]=i;sets.append(_mask(key,len(track['definitions'])))
            return i
        return dict(control=ordinal,namespace=track['namespace'],max_updates=track['max_updates'],
            definitions=track['definitions'],definition_sets=sets,
            states=[[intern(s['incoming']),intern(s['outgoing'])] for s in track['states']],
            reads=[[r['state'],r['access'],r['anchors'],intern(r['definitions'])] for r in track['reads']],
            frontiers=track['frontiers'],dataflow_complete=track['dataflow_complete'])


def unpack_wire(track,controls):
    if set(track)!=set(B.PackedBindingTrack.__dataclass_fields__):raise ValueError('packed track field domain differs')
    i=track['control']
    if type(i)is not int or not 0<=i<len(controls):raise ValueError('track control reference is outside its unit')
    control=controls[i];n=len(control['states']);definitions=track['definitions']
    sets=[_values(mask,len(definitions)) for mask in track['definition_sets']]
    if len(set(track['definition_sets']))!=len(sets) or len(track['states'])!=n:
        raise ValueError('track set pool or control-state denominator differs')
    used=set()
    def get(i):
        if type(i)is not int or not 0<=i<len(sets):raise ValueError('definition-set reference is outside its track')
        used.add(i);return sets[i]
    states=[]
    for coordinate,indices in zip(control['states'],track['states'],strict=True):
        if len(coordinate)!=2 or len(indices)!=2:raise ValueError('control/set coordinate arity differs')
        port,stack=coordinate
        states.append(dict(port=port,stack=stack,incoming=get(indices[0]),outgoing=get(indices[1])))
    reads=[]
    for state,access,anchors,definition_set in track['reads']:
        if type(state)is not int or not 0<=state<n or type(access)is not int or access<0:
            raise ValueError('read state/access reference is invalid')
        reads.append(dict(state=state,access=access,anchors=anchors,definitions=get(definition_set)))
    if used!=set(range(len(sets))):raise ValueError('packed track has unused definition sets')
    return dict(source_function=control['source_function'],namespace=track['namespace'],
        max_states=control['max_states'],max_stack=control['max_stack'],max_updates=track['max_updates'],
        definitions=definitions,states=states,transitions=control['transitions'],reads=reads,
        frontiers=track['frontiers'],traversal_complete=control['traversal_complete'],
        dataflow_complete=track['dataflow_complete'])


def read_tracks(folder,header):
    folder=Path(folder)
    if header['schema_version']==1:
        yield from _table(folder,header['tables']['tracks']);return
    if (header['schema_version'],header.get('track_encoding'),header.get('storage_pins'))!=(2,ENCODING,pins()):
        raise ValueError('unsupported binding-track storage contract')
    controls=list(_table(folder,header['tables']['controls']))
    for wire in _table(folder,header['tables']['tracks']):yield unpack_wire(wire,controls)


def repack(source,out):
    """Reencode a completed unit, checking every legacy record roundtrip."""
    started=time.monotonic();source=Path(source).resolve();out=Path(out).absolute()
    if out.exists() or out.resolve()!=out:raise ValueError('fresh canonical repack output required')
    raw=(source/'result.json').read_bytes();header=json.loads(raw)
    if (header['schema'],header['schema_version'])!=('scar.source-state-view',1):
        raise ValueError('repacking requires an original schema-1 state unit')
    original_pins=pins();_durable_mkdir(out);packer=TrackPacker();count=0
    def rows():
        nonlocal count
        for wire in _table(source,header['tables']['tracks']):
            packed=packer.pack_wire(wire)
            if unpack_wire(packed,packer.controls)!=wire:raise ValueError('binding-track codec changed a legacy field')
            count+=1;yield packed
    tables=dict(tracks=write_table(out/'tracks.jsonl.gz',rows()),
        controls=write_table(out/'controls.jsonl.gz',packer.controls))
    for name,receipt in header['tables'].items():
        if name=='tracks':continue
        if receipt['path']!=name+'.jsonl.gz':raise ValueError('legacy state table path differs')
        p=source/receipt['path'];data=p.read_bytes()
        if len(data)!=receipt['bytes'] or sha256(data).hexdigest()!=receipt['sha256']:
            raise ValueError('legacy state table receipt changed')
        os.link(p,out/receipt['path']);tables[name]=receipt
    if count!=header['counts']['tracks'] or raw!=(source/'result.json').read_bytes() or pins()!=original_pins:
        raise ValueError('state input, codec or track denominator changed while repacking')
    report=dict(header,schema_version=2,track_encoding=ENCODING,storage_pins=original_pins,tables=tables,
        repacked_from=dict(path=str(source/'result.json'),bytes=len(raw),sha256=sha256(raw).hexdigest()),
        all_legacy_track_fields_roundtripped=True,repacking_seconds=time.monotonic()-started)
    _durable_bytes(out/'result.json',_json(report),replace=False)
    return report


def publish_state_view(state,out):
    """Publish the same state projection with losslessly factored tracks."""
    from scar.analysis.program_state_view import _rows,_counts,_pins
    from scar.analysis.source_value_flow import _artifact
    started=time.monotonic();out=Path(out).absolute();analysis_pins=_pins();storage_pins=pins()
    if out.exists() or out.resolve()!=out:raise ValueError('fresh canonical state output required')
    state.check();_durable_mkdir(out);rows=_rows(state);packer=TrackPacker();timings={}
    tables=dict(tracks=write_table(out/'tracks.jsonl.gz',
        (packer.pack(track) for track in rows['tracks'][1]),timings=timings))
    tables['controls']=write_table(out/'controls.jsonl.gz',packer.controls,timings=timings)
    tables.update({name:write_table(out/(name+'.jsonl.gz'),records,timings=timings)
        for name,(_,records) in rows.items() if name!='tracks'})
    report=dict(schema='scar.source-state-view',schema_version=2,
        catalog=str(state.view.catalog.path),parent=encode(_artifact(state.view.catalog.path/'result.json',state.view.catalog.report['schema'])),
        unit=state.material.unit,namespace=encode(state.namespace),source_material=encode(state.material.result_artifact),
        binding_materials=encode(state.materials),pins=analysis_pins,storage_pins=storage_pins,
        track_encoding=ENCODING,tables=tables,counts=_counts(state),table_seconds=timings,
        original_body_bytes_copied=0,loops_unrolled=False,target_executed=False,
        tensor_content_versions_proven=False,effect_membership_closed=False,first_stage_complete=False,
        seconds=time.monotonic()-started)
    state.check()
    if analysis_pins!=_pins() or storage_pins!=pins():raise ValueError('state rules or storage codec changed')
    _durable_bytes(out/'result.json',_json(report),replace=False);return report


def read_state_view(path):
    """Optional independent solver replay; default graph reads do not call it."""
    from itertools import zip_longest
    from scar.analysis.program_view import ProgramView
    from scar.analysis.program_state_view import _rows,_counts,_pins
    from scar.analysis.source_value_flow import _artifact
    from scar.ir.program import normal_targets as T,normal_links as F
    path=Path(path).resolve();raw=(path/'result.json').read_bytes();header=json.loads(raw)
    if header['schema_version']==1:
        from scar.analysis.program_state_view import read_state_view as legacy_read
        return legacy_read(path)
    if (header['schema'],header['schema_version'],header['track_encoding'],header['storage_pins'],header['pins'])!=(
            'scar.source-state-view',2,ENCODING,pins(),_pins()):raise ValueError('state/storage replay contract differs')
    if header['original_body_bytes_copied']!=0 or any(header[k]is not False for k in (
            'loops_unrolled','target_executed','tensor_content_versions_proven','effect_membership_closed','first_stage_complete')):
        raise ValueError('state storage cannot grant runtime authority')
    view=ProgramView(header['catalog']);state=view.state(header['unit'])
    if (encode(_artifact(view.catalog.path/'result.json',view.catalog.report['schema']))!=header['parent']
            or encode(state.namespace)!=header['namespace']
            or encode(state.material.result_artifact)!=header['source_material']
            or encode(state.materials)!=header['binding_materials']):raise ValueError('state replay original inputs differ')
    controls=list(_table(path,header['tables']['controls']))
    for wire in _table(path,header['tables']['tracks']):
        i=wire['control']
        if type(i)is not int or not 0<=i<len(controls):raise ValueError('packed control reference is invalid')
        control=controls[i]
        state.track(decode(T.GlobalPort,control['source_function']),decode(F.Namespace,wire['namespace']),
            max_states=control['max_states'],max_stack=control['max_stack'],max_updates=wire['max_updates'])
    rows=_rows(state);packer=TrackPacker();missing=object()
    if set(header['tables'])!=set(rows)|{'controls'}:raise ValueError('packed state table domain differs')
    expected=(encode(packer.pack(track)) for track in rows['tracks'][1])
    if any(a!=b for a,b in zip_longest(_table(path,header['tables']['tracks']),expected,fillvalue=missing)):
        raise ValueError('packed state tracks differ from current source fixed points')
    if controls!=[encode(c) for c in packer.controls]:raise ValueError('shared control differs from original topology')
    for name,(cls,expected) in rows.items():
        if name=='tracks':continue
        actual=(decode(cls,wire,record_tags=P.PRODUCTION_RECORD_TAGS) for wire in _table(path,header['tables'][name]))
        if any(a!=b for a,b in zip_longest(actual,expected,fillvalue=missing)):
            raise ValueError('packed state '+name+' differs from original projection')
    if _counts(state)!=header['counts'] or raw!=(path/'result.json').read_bytes():
        raise ValueError('state replay count or input changed')
    state.check();return header,view,state


def state_view_main(argv):
    """Keep the established state-view CLI; dispatch readback by wire schema."""
    import argparse
    p=argparse.ArgumentParser(add_help=False);p.add_argument('--read');a,rest=p.parse_known_args(argv)
    if a.read and json.loads((Path(a.read)/'result.json').read_bytes()).get('schema_version')==2:
        if rest:raise ValueError('state-view --read stands alone')
        started=time.monotonic();header,_,_=read_state_view(a.read)
        print(json.dumps(dict(status='STATE_VIEW_REDERIVED',schema_version=2,counts=header['counts'],
            seconds=time.monotonic()-started)),flush=True);return 0
    from scar.analysis.program_state_view import main as legacy_main
    import sys
    previous=sys.argv
    try:
        sys.argv=[previous[0],*argv];return legacy_main()
    finally:sys.argv=previous


def main():
    import argparse
    p=argparse.ArgumentParser(description=__doc__);p.add_argument('--source',required=True);p.add_argument('--out',required=True)
    a=p.parse_args();r=repack(a.source,a.out)
    print(json.dumps(dict(tracks=r['tables']['tracks']['records'],controls=r['tables']['controls']['records'],
        bytes=r['tables']['tracks']['bytes']+r['tables']['controls']['bytes'],seconds=r['repacking_seconds'])),flush=True)


if __name__=='__main__':main()
