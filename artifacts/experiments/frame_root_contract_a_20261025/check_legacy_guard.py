"""Only the newly required historical source-wrapper capability boundary."""
from dataclasses import replace
import json
from pathlib import Path
from check_contract import mapping_graph
from scar.analysis.program_lowering import SourceProgram


def run_checks():
    checks = []
    def rejected(label, call):
        try:
            call()
        except ValueError as error:
            if 'historical source1-7' not in str(error):
                raise
            checks.append(label)
        else:
            raise AssertionError(label)
    for label, version, core in (
        ('v7 refuses core29 before accepting a new root authority', 7, {'schema_version':29}),
        ('v6 refuses explicit frame_roots even empty', 6, {'schema_version':2,'frame_roots':[]}),
        ('v5 refuses FRAME with unknown core version', 5,
         {'schema_version':'unknown','control_scopes':[{'kind':'FRAME'}]}),
    ):
        rejected(label, lambda version=version,core=core: SourceProgram.from_dict(
            {'schema_version':version,'graph':core}, verification='STRUCTURE', source_texts={}))
    graph=mapping_graph()
    rejected('historical writer refuses nonempty frame_roots',
             lambda: SourceProgram(graph,None,None,None,None).to_dict())
    rejected('historical writer refuses FRAME without a root record',
             lambda: SourceProgram(replace(graph,frame_roots=()),None,None,None,None).to_dict())
    return {'status':'LEGACY_WRAPPER_BOUNDARY_PASS','checks':checks,
            'scope':'SYNTHETIC_TYPE_GUARD_ONLY','source_or_runtime_proof':False}

if __name__=='__main__':
    import sys
    result=run_checks();out=Path(sys.argv[1]);out.parent.mkdir(parents=True,exist_ok=True)
    if out.exists(): raise FileExistsError(out)
    out.write_text(json.dumps(result,indent=2)+'\n')
    print(json.dumps({'status':result['status'],'checks':len(result['checks']),'output':str(out)}))
