"""Current writer checks both originals against already immutable outputs."""
from pathlib import Path
import hashlib,json,resource,time
from scar.ir.record_codec import decode,encode
from scar.ir.program.source_references import SourceArtifactLocator
from scar.store.source_fragments import SourceFragmentWriter
ROOT=Path(__file__).resolve().parent
old=json.loads((ROOT.parent/'attempt03/result.json').read_text())
store=ROOT.parent/'attempt03/store'
def stamp(p):
 s=p.stat();return [s.st_dev,s.st_ino,s.st_size,s.st_mtime_ns,s.st_ctime_ns]
before={str(p):stamp(p) for p in store.rglob('*.gz')}
started=time.monotonic();writer=SourceFragmentWriter(store)
actual=[writer.write(decode(SourceArtifactLocator,x),namespace_root='/home/zyf/AAA/le-wm') for x in old['originals']]
assert [encode(x) for x in actual]==old['fragments']
measurement=writer.finish()
assert measurement['stored_output_bytes']==measurement['decoded_output_bytes']==0
assert before=={str(p):stamp(p) for p in store.rglob('*.gz')}
sources=[]
for name in ('scar/store/source_fragments.py','scar/analysis/program_lowering.py'):
 p=Path(name);b=p.read_bytes();sources.append({'path':str(p.resolve()),'bytes':len(b),'sha256':hashlib.sha256(b).hexdigest()})
result={'status':'PASSED_CURRENT_WRITER_IDEMPOTENT_RECEIPT_CHECK','inputs':old['originals'],
 'same_fragments':True,'old_output_stats_unchanged':True,'measurement':measurement,
 'elapsed_seconds':time.monotonic()-started,'peak_self_rss_KiB':resource.getrusage(resource.RUSAGE_SELF).ru_maxrss,
 'scope':'two original SP5 archive checks, no typed source/body replay or graph production; all existing outputs byte/stat stable','sources':sources}
(ROOT/'result.json').write_text(json.dumps(result,indent=2)+'\n');print(json.dumps(result,indent=2))
