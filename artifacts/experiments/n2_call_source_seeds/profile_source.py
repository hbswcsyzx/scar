"""Profile one offline source match, selected by observed source byte size."""
import argparse,cProfile,gzip,json,pstats,time
from pathlib import Path
from scar.analysis.call_edges import _Sources
from scar.ir.program.call_edges import CallEdgeBudget,CapturedCode
from scar.ir.record_codec import decode
p=argparse.ArgumentParser()
p.add_argument('report',type=Path);p.add_argument('--out',type=Path,required=True)
a=p.parse_args();a.out.mkdir(parents=True,exist_ok=False)
with gzip.open(a.report,'rt') as f:d=json.load(f)
links=[link for link in d['model']['code_links'] if link['status']=='VERIFIED' and link['snapshot']]
selected=max(links,key=lambda link:Path(link['snapshot']['path']).stat().st_size)
raw=next(capture['code'] for capture in d['model']['codes'] if capture['code']['key']==selected['code'])
code=decode(CapturedCode,raw)
resolver=_Sources(Path(d['model']['project_root']),decode(CallEdgeBudget,d['model']['budget']),inventory=None)
profile=cProfile.Profile();start=time.perf_counter();link=profile.runcall(resolver.code,code);elapsed=time.perf_counter()-start
profile.dump_stats(a.out/'source.pstats')
with (a.out/'source.txt').open('w') as out:pstats.Stats(profile,stream=out).sort_stats('cumulative').print_stats(35)
summary={'scope':'Instrumented single source-code match; not target execution, clean benchmark or semantic proof',
         'selection':'largest current source bytes among generated VERIFIED code links',
         'file':code.filename,'source_bytes':Path(code.filename).stat().st_size,'code':code.key,
         'status':link.status.value,'wall_s':elapsed,'target_executed':False,'transformation_authorized':False}
(a.out/'summary.json').write_text(json.dumps(summary,indent=2)+'\n');print(json.dumps(summary))
