"""Read one existing fragment after closing its original decoded-byte receipt."""
from pathlib import Path
from dataclasses import replace
import gzip,hashlib,json,resource,time
from scar.ir.record_codec import decode,encode
from scar.ir.program.providers import ProviderArtifact
from scar.ir.program.source_references import SourceArtifactLocator
from scar.store.source_fragments import SourceContextSession,_canonical

ROOT=Path(__file__).resolve().parent
old=json.loads((ROOT.parent/'attempt03/result.json').read_text())
artifact=decode(SourceArtifactLocator,old['fragments'][1])
source=old['originals'][0]
path='/home/zyf/AAA/le-wm/stable-worldmodel/stable_worldmodel/world/world.py'
text=Path(path).read_text();started=time.monotonic()
with SourceContextSession(source_texts={path:text}) as session:
    view=session.read(artifact,namespace_root='/home/zyf/AAA/le-wm')
    assert len(view.body.graph.operations)==217
    doc=json.loads(gzip.decompress(Path(artifact.artifact.uri).read_bytes()))
    doc['original']['decoded_sha256']='0'*64
    decoded=_canonical(doc);raw=gzip.compress(decoded,mtime=0)
    bad=ROOT/'wrong-original-receipt.json.gz';bad.write_bytes(raw)
    negative=SourceArtifactLocator(ProviderArtifact(str(bad),hashlib.sha256(raw).hexdigest(),len(raw),'scar.source-body-fragment/1'),
        hashlib.sha256(decoded).hexdigest(),len(decoded),'gzip-canonical-json')
    try:session.read(negative,namespace_root='/home/zyf/AAA/le-wm')
    except ValueError as error:
        assert 'original decoded receipt differs' in str(error);rejection=str(error)
    else:raise AssertionError('changed original receipt accepted')
    measurement=session.finish()
receipts=[]
for name in ('scar/store/source_fragments.py','scar/analysis/program_lowering.py'):
    p=Path(name);b=p.read_bytes();receipts.append({'path':str(p.resolve()),'bytes':len(b),'sha256':hashlib.sha256(b).hexdigest()})
result={'status':'PASSED_ORIGINAL_RECEIPT_AND_NORMAL_READER','artifact':encode(artifact),'operations':217,
    'negative_original_receipt':rejection,'session':measurement,'original_SP5_payloads_read':0,
    'source_lower':0,'target_exec':0,'peak_self_rss_KiB':resource.getrusage(resource.RUSAGE_SELF).ru_maxrss,
    'elapsed_seconds':time.monotonic()-started,'sources':receipts,
    'scope':'original canonical UTF8 or exact same bytes plus LF checked by decoded size/SHA; prior source/runtime limits remain'}
(ROOT/'result.json').write_text(json.dumps(result,indent=2)+'\n');print(json.dumps(result,indent=2))
