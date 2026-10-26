"""One actual closed-row locator; off-line CPU comparison, not a model gate."""
from pathlib import Path
import cProfile,hashlib,importlib.util,json,pstats,sys,time
from scar.ir.execution.fragment_relations import FragmentLocator
from scar.ir.record_codec import decode,encode
from scar.store.fragment_relations import Meter,RelationBudgets
BASE=Path(__file__).resolve().parent
ROOT=BASE.parents[3]
sample=json.loads((BASE/'CACHE_SAMPLE.json').read_bytes());locator=decode(FragmentLocator,sample['locator'])
def module(name,path):
 s=importlib.util.spec_from_file_location(name,path);m=importlib.util.module_from_spec(s);sys.modules[name]=m;s.loader.exec_module(m);return m
before=module('fragment_cache_before',BASE.parent/'candidate01/production_snapshot/scar/analysis/fragment_relations.py')
after=module('fragment_cache_after',BASE/'fragment_relations.candidate.py')
def measure(m,name):
 original=m.strict_loads;calls={'n':0}
 def counted(value):calls['n']+=1;return original(value)
 m.strict_loads=counted;cache={};meter=Meter(RelationBudgets(max_input_bytes=32_000_000,max_seconds=30));results=[]
 profile=cProfile.Profile();start=time.perf_counter();profile.enable()
 for _ in range(20):results.append(m._read_locator(locator,meter,cache))
 profile.disable();elapsed=time.perf_counter()-start;profile.dump_stats(str(BASE/(name+'.pstats')))
 assert all(v==results[0] for v in results)
 return results,{'strict_loads_calls':calls['n'],'elapsed_s':elapsed,'io':meter.receipt(),'profile_total_calls':pstats.Stats(profile).total_calls}
a,old=measure(before,'before');b,new=measure(after,'after')
assert a==b and old['strict_loads_calls']==20 and new['strict_loads_calls']==1
report={'scope':'ONE_REAL_RETAINED_CODE_SOURCE_JSON_LOCATOR_ONLY; NOT_SOURCE_RUNTIME_OR_MODEL_COMPLETENESS','sample':sample,'iterations':20,'return_values_identical':True,'before':old,'after':new,'live_gate_unchanged':True,'original_exit1_preserved':True,'target_or_graph_execution':False,'producer_or_index_runs':0,'candidate_sha256':hashlib.sha256((BASE/'fragment_relations.candidate.py').read_bytes()).hexdigest()}
(BASE/'CACHE_COMPARISON.json').write_text(json.dumps(report,indent=2)+'\n');print(json.dumps({'identical':True,'before':old,'after':new,'candidate_sha256':report['candidate_sha256']}))
