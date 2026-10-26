"""Incremental SP5 admission using existing publications and qualified endpoints.

Only source-entry publication navigation is combined. Original SP5/CP2 graphs,
IDs, namespaces and witnesses remain the existing facts. Parent body legality
is retained by its exact immutable publication receipt, not re-proved here.
"""
from pathlib import Path
from hashlib import sha256
from copy import deepcopy
import json

from scar.ir.record_codec import decode,encode,loads
from scar.ir.program.providers import ProviderArtifact
from scar.ir.program.source_references import SourceArtifactLocator,SourceDefinitionReference


def _need(ok,detail):
    if not ok:raise ValueError('incremental source publication: '+detail)


def _canonical(value):
    return json.dumps(value,sort_keys=True,ensure_ascii=False,separators=(',',':'),allow_nan=False).encode()


def _read(artifact,maximum):
    _need(type(artifact) is ProviderArtifact,'exact input artifact required')
    artifact.__post_init__();p=Path(artifact.uri)
    _need(p.is_absolute() and p.resolve(strict=True)==p and not p.is_symlink() and p.is_file(), 'original input URI unavailable/aliased')
    before=p.stat();stamp=lambda s:(s.st_dev,s.st_ino,s.st_size,s.st_mtime_ns,s.st_ctime_ns)
    _need(0<before.st_size==artifact.size_bytes<=maximum,'input metadata byte bound differs')
    with p.open('rb') as stream:raw=stream.read(maximum+1)
    _need(stamp(p.stat())==stamp(before) and len(raw)==artifact.size_bytes and sha256(raw).hexdigest()==artifact.sha256,'input metadata SHA/stability differs')
    doc=loads(raw.decode('utf8'));_need(type(doc) is dict,'input metadata must be an object')
    return doc


def _publication(artifact,maximum):
    from scar.analysis.source_program_publication import _ENTRY_AUTHORITY
    d=_read(artifact,maximum)
    _need(artifact.schema=='scar.source-entry-publication' and d.get('schema')==artifact.schema and type(d.get('schema_version')) is int
          and d['schema_version']==3 and all(d.get(k) is v for k,v in _ENTRY_AUTHORITY.items()), 'explicit publication3 authority/schema required')
    _need(sha256(_canonical(d['plan'])).hexdigest()==d['plan_sha256'],'publication plan SHA differs')
    _need(len(d['bodies'])==len(d['plan']['expectations']),'body/expectation denominator differs')
    keys=set();definitions=set()
    for row,expected in zip(d['bodies'],d['plan']['expectations']):
        _need(all(row.get(k)==v for k,v in expected.items()),'original body/plan fields differ')
        ref=decode(SourceDefinitionReference,row['definition']);identity=_canonical(encode(ref))
        _need(row['entry_key'] not in keys and identity not in definitions,'publication repeats qualified entry/definition')
        keys.add(row['entry_key']);definitions.add(identity)
    return d


def collect_source_entry_deltas(parent_publication,delta_inputs,*,max_metadata_bytes=32_000_000):
    """Select original seven-field SP5 receipts; success labels grant no proof."""
    _need(type(delta_inputs) is tuple and delta_inputs,'nonempty exact delta inputs required')
    parent=_publication(parent_publication,max_metadata_bytes)
    old={row['entry_key']:row['source_program'] for row in parent['bodies']};selected={};origins={}
    fields={'uri','external','representation','physical_sha256','physical_bytes','decoded_sha256','decoded_bytes'}
    for artifact in delta_inputs:
        document=_read(artifact,max_metadata_bytes)
        _need(type(document.get('entries')) is list,'delta requires original entries')
        seen=set()
        for row in document['entries']:
            key=row['entry_key'];_need(type(key) is str and key and key not in seen,'delta repeats/omits entry key');seen.add(key)
            if row.get('status') is not None and row['status']!='SUCCEEDED':continue
            program=row['program']
            _need(type(program) is dict and set(program)==fields and program['external'] is True and program['representation']=='scar.source-program/5','exact original SP5 seven-field receipt required')
            if key in old:
                _need(program==old[key],'existing entry revision needs explicit REVISE policy')
                continue
            _need(key not in selected or selected[key]['source_program']==program,'conflicting delta program for one entry')
            selected[key]={'entry_key':key,'source_program':deepcopy(program)}
            origins.setdefault(key,[]).append(encode(artifact))
    return tuple(selected[k] for k in sorted(selected)),origins


def publish_source_entry_deltas(parent_publication,delta_inputs,target,catalog,out,*,max_programs=128,
                                 max_operations_per_body=10000,max_record_bytes=128_000_000,max_metadata_bytes=32_000_000):
    """Normally admit only new bodies; retain old CP2/SP5 refs in one schema3 root.

    No old live lowering owner is restored. The union has the same plain
    project/catalog parent and is consumable by the existing full reader; a
    selected reader below independently checks only the requested body.
    """
    from scar.analysis.source_program_publication import plan_source_entry_publication,publish_source_entries
    root=Path(out).resolve();_need(not root.exists(),'output must be fresh');root.mkdir(parents=True)
    parent=_publication(parent_publication,max_metadata_bytes)
    requests,origins=collect_source_entry_deltas(parent_publication,delta_inputs,max_metadata_bytes=max_metadata_bytes)
    _need(0<len(requests)<=max_programs,'new body denominator exceeds bound or is empty')
    by_key={r['entry_key']:r for r in catalog.metadata()['candidates']}
    requests=tuple(sorted(requests,key=lambda r:(by_key[r['entry_key']]['file_key'],r['entry_key'])))
    (root/'selection.json').write_bytes(_canonical({'parent':encode(parent_publication),'delta_inputs':encode(delta_inputs),
        'requests':requests,'origins':origins,'new_bodies':len(requests),'retained_parent_bodies':len(parent['bodies'])})+b'\n')
    # One genuine private ordinary scope brackets planning and admission. It
    # owns PreparedSource caches; no callback or serialized accepted token.
    with catalog._ordinary_read_session(target,controls=(requests,)) as session:
        private_requests=tuple(json.loads(session.control_bytes)[0])
        plan=plan_source_entry_publication(session.target,session.catalog,private_requests,max_programs=max_programs,publication_version=3)
        common={k:v for k,v in parent['plan'].items() if k not in ('expectations',)}
        _need({k:v for k,v in plan.document.items() if k!='expectations'}==common,'parent source/catalog/compiler/namespace/CAS inputs differ')
        published=publish_source_entries(session.target,session.catalog,private_requests,root/'delta',plan=plan,
            max_programs=max_programs,max_operations_per_body=max_operations_per_body,max_record_bytes=max_record_bytes)
    delta_artifact=ProviderArtifact(published['manifest'],published['sha256'],Path(published['manifest']).stat().st_size,'scar.source-entry-publication')
    delta=_publication(delta_artifact,max_metadata_bytes)
    old_keys={r['entry_key'] for r in parent['bodies']}
    _need(not old_keys & {r['entry_key'] for r in delta['bodies']},'increment repeats an original entry')
    combined=deepcopy(delta);combined['bodies']=deepcopy(parent['bodies'])+delta['bodies']
    combined['plan']['expectations']=deepcopy(parent['plan']['expectations'])+delta['plan']['expectations']
    _need(len({_canonical(row['definition']) for row in combined['bodies']})==len(combined['bodies']),'increment repeats a qualified definition')
    combined['plan_sha256']=sha256(_canonical(combined['plan'])).hexdigest()
    raw=_canonical(combined);_need(len(raw)<=max_metadata_bytes,'combined publication metadata exceeds bound')
    path=root/'manifest.json'
    with path.open('xb') as stream:stream.write(raw)
    result={'publication':encode(ProviderArtifact(str(path),sha256(raw).hexdigest(),len(raw),'scar.source-entry-publication')),
        'parent_publication':encode(parent_publication),'delta_publication':encode(delta_artifact),
        'retained_parent_bodies':len(parent['bodies']),'normally_admitted_new_bodies':len(delta['bodies']),
        'total_bodies':len(combined['bodies']),'parent_bodies_replayed':False,'new_bodies_relowered':False,
        'full_independent_reader_completed':False,'whole_program_complete':False,
        'qualification':'normal new-body admission plus exact immutable parent publication references; selected-body qualification remains queryable'}
    (root/'increment.json').write_bytes(_canonical(result)+b'\n')
    # Recheck all small immutable declarations, not prior body payloads.
    _publication(parent_publication,max_metadata_bytes)
    for artifact in delta_inputs:_read(artifact,max_metadata_bytes)
    return result


def read_source_entry_publication_body(publication,entry_key,target,catalog,*,max_operations=10000,max_record_bytes=128_000_000,max_metadata_bytes=32_000_000):
    """Ordinary selected SP5/source/code/CP2 qualification, no full-parent replay."""
    from scar.analysis.source_program_publication import (_entry_program,_entry2_abi,_entry2_checkpoint,_entry_admissions,
        _entry_body_cache,_canonical as canonical,plan_source_entry_publication)
    from scar.analysis.inventory_partitions import _read_receipt
    from scar.ir.program.codec import dumps
    document=_publication(publication,max_metadata_bytes)
    found=[row for row in document['bodies'] if row['entry_key']==entry_key]
    _need(len(found)==1,'selected entry is absent or ambiguous');row=found[0]
    request={'entry_key':entry_key,'source_program':row['source_program']}
    with catalog._ordinary_read_session(target,controls=(request,)) as session:
        request=json.loads(session.control_bytes)[0]
        plan=plan_source_entry_publication(session.target,session.catalog,(request,),max_programs=1,publication_version=3)
        expected=plan.document['expectations'][0]
        _need(all(row.get(k)==v for k,v in expected.items()),'selected current parent/body CAS differs')
        entry,program,body,signature=_entry_program(session.catalog,request,max_operations,max_record_bytes,publication_version=3)
        _entry2_abi(expected,program)
        checkpoint,actual=_read_receipt(row['checkpoint']['uri'],limit=max_record_bytes)
        _need(all(actual[k]==row['checkpoint'][k] for k in actual) and checkpoint==_entry2_checkpoint(entry,program,expected)
            and row['signature']==encode(signature) and row['root']==encode(body.graph.root)
            and row['admissions']==_entry_admissions(session.catalog,entry,body)
            and row['program_graph_sha256']==sha256(canonical(json.loads(dumps(program.graph)))).hexdigest(), 'selected original CP2/source/code/ports differ')
        result={'record':deepcopy(row),'body':body,'program':_entry_body_cache(program,True),'entry':entry}
    result['entry']=session.entry(result['entry'])
    _publication(publication,max_metadata_bytes)
    return result
