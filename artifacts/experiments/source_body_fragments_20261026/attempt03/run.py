"""Two retained real SP5s -> one context + two bodies; source-only read checks."""
from pathlib import Path
from dataclasses import replace
import gzip,hashlib,json,resource,time,traceback
from scar.ir.program.providers import ProviderArtifact
from scar.ir.program.source_references import SourceArtifactLocator
from scar.ir.record_codec import encode,decode
from scar.store.source_fragments import (SourceFragmentWriter,SourceContextSession,
    SourceFragmentBudget,SourceContextReference)
from scar.analysis.program_lowering import SourceProgram,LoweredSourceBody

ROOT=Path(__file__).resolve().parent
ORIGINAL=Path('/home/zyf/AAA/scar-worktrees/source-call-model/artifacts/experiments/source_call_kwargs_bodies_20261025/candidate04/attempt04')
NAMESPACE='/home/zyf/AAA/le-wm'
started=time.monotonic();result={'status':'BUILDING','target_exec':0,'source_lower':0}
(ROOT/'result.json').write_text(json.dumps(result)+'\n')
try:
    originals=[];source=None
    for name in ('body-01-result.json','body-02-result.json'):
        old=json.loads((ORIGINAL/name).read_text());a=old['artifact']
        originals.append(SourceArtifactLocator(ProviderArtifact(a['path'],a['sha256'],a['bytes'],'scar.source-program/5'),
            a['decoded_sha256'],a['decoded_bytes'],'gzip-canonical-json'))
        if source is None:source=old['source']
        else:assert source['path']==old['source']['path'] and source['fingerprint']==old['source']['fingerprint']
    text=Path(source['path']).read_text()
    assert 'sha256:'+hashlib.sha256(text.encode()).hexdigest()==source['fingerprint']
    texts={source['path']:text}
    writer=SourceFragmentWriter(ROOT/'store')
    fragments=[writer.write(original,namespace_root=NAMESPACE) for original in originals]
    writer_measurement=writer.finish()
    assert len(list((ROOT/'store/contexts').glob('*.gz')))==1
    assert len(list((ROOT/'store/bodies').glob('*.gz')))==2
    (ROOT/'FRAGMENTS.json').write_text(json.dumps([encode(x) for x in fragments],indent=2)+'\n')
    with SourceContextSession(source_texts=texts) as session:
        views=[session.read(item,namespace_root=NAMESPACE) for item in fragments]
        assert [len(view.body.graph.operations) for view in views]==[85,217]
        assert all(type(view.body) is LoweredSourceBody and not hasattr(view.body,'semantic') for view in views)
        assert views[0].context==views[1].context
        assert session.counts['context_reads']==session.counts['context_validations']==1
        shared=session.finish()
    def rejects(label,action,substring):
        try:action()
        except ValueError as exc:
            assert substring in str(exc),(label,str(exc));return {'check':label,'error':str(exc)}
        raise AssertionError(label+' accepted')
    negative=[rejects('closed-session',lambda:session.read(fragments[0],namespace_root=NAMESPACE),'closed')]
    with SourceContextSession(source_texts=texts) as independent:
        view=independent.read(fragments[1],namespace_root=NAMESPACE)
        assert len(view.body.graph.operations)==217
        cold=independent.finish()
    # Wrong context receipt is rejected by an ordinary new live session.
    raw=gzip.decompress(Path(fragments[0].artifact.uri).read_bytes());body_doc=json.loads(raw)
    context=decode(SourceContextReference,body_doc['context'])
    bad=replace(context,payload=replace(context.payload,artifact=replace(context.payload.artifact,sha256='0'*64)))
    with SourceContextSession(source_texts=texts) as bad_session:
        negative.append(rejects('wrong-context-SHA',lambda:SourceProgram.read_structure_fragment(body_doc['program'],context_session=bad_session,context=bad),'SHA'))
    with SourceContextSession(source_texts=texts) as bad_namespace:
        negative.append(rejects('wrong-namespace',lambda:bad_namespace.read(fragments[0],namespace_root='/different/namespace'),'namespace'))
    # Private mutability is never trusted as a cached validity boolean.
    with SourceContextSession(source_texts=texts) as mutation:
        mutation.read(fragments[0],namespace_root=NAMESPACE)
        owned=mutation._context(context)
        module=next(iter(owned.semantic.modules.values()));module.name+='-tampered'
        negative.append(rejects('private-context-mutation',lambda:mutation.read(fragments[0],namespace_root=NAMESPACE),'changed after validation'))
    # One old ordinary SP5 read keeps the unchanged compatibility path visible.
    original_raw=gzip.decompress(Path(originals[0].artifact.uri).read_bytes())
    legacy=SourceProgram.read_structure(json.loads(original_raw),source_texts=texts,max_operations=4000)
    assert len(legacy.graph.operations)==85
    assert legacy.metadata==views[0].body.metadata and legacy.graph==views[0].body.graph
    assert legacy.to_dict()==json.loads(original_raw)
    source_receipts=[]
    for name in ('scar/store/source_fragments.py','scar/analysis/program_lowering.py'):
        p=Path(name);b=p.read_bytes();source_receipts.append({'path':str(p.resolve()),'bytes':len(b),'sha256':hashlib.sha256(b).hexdigest()})
    result={'status':'PASSED_SOURCE_TRANSPORT_AND_STRUCTURE_ONLY','source_lower':0,'target_exec':0,
        'originals':[encode(x) for x in originals],'fragments':[encode(x) for x in fragments],
        'writer':writer_measurement,'shared_session':shared,'independent_body_session':cold,
        'legacy_SP5_ordinary_read':{'operations':85,'wire_tree_equal':True},'negative_checks':negative,
        'original_stored_bytes':sum(x.artifact.size_bytes for x in originals),
        'original_decoded_bytes':sum(x.decoded_bytes for x in originals),
        'output_contexts':1,'output_bodies':2,'source_text_bytes':len(text.encode()),
        'output_stored_bytes':sum(p.stat().st_size for p in (ROOT/'store').rglob('*.gz')),
        'output_decoded_bytes':sum(len(gzip.decompress(p.read_bytes())) for p in (ROOT/'store').rglob('*.gz')),
        'peak_self_rss_KiB':resource.getrusage(resource.RUSAGE_SELF).ru_maxrss,
        'elapsed_seconds':time.monotonic()-started,'source_receipts':source_receipts,
        'runtime_code_or_contents_effects_proved':False,'full_source_body_replay':False,
        'qualification':'ordinary context AST/semantics/CFG + ordinary per-body core/structured/language transport; no new CodeWitness/runtime proof'}
    (ROOT/'result.json').write_text(json.dumps(result,indent=2)+'\n')
    print(json.dumps({k:result[k] for k in ('status','output_contexts','output_bodies','original_stored_bytes','original_decoded_bytes','output_stored_bytes','output_decoded_bytes','peak_self_rss_KiB','elapsed_seconds')},indent=2))
except BaseException as exc:
    result.update(status='FAILED',error=str(exc),elapsed_seconds=time.monotonic()-started)
    (ROOT/'result.json').write_text(json.dumps(result,indent=2)+'\n')
    (ROOT/'failure.txt').write_text(traceback.format_exc());raise
