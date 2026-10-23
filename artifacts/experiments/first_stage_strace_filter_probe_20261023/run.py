"""Two isolated diagnostic launches, never a replay of the old episode."""
import hashlib
import json
from pathlib import Path
import platform
import subprocess
import sys


HERE=Path(__file__).resolve().parent
assert platform.machine()=='x86_64'
binary=Path('/usr/bin/strace')
version=subprocess.run([str(binary),'-V'],capture_output=True,text=True,check=True)
report={'schema':'scar.local-strace-filter-probe','schema_version':1,
 'binary_sha256':hashlib.sha256(binary.read_bytes()).hexdigest(),'version':version.stdout+version.stderr,
 'architecture':platform.machine(),'child_sha256':hashlib.sha256((HERE/'child.py').read_bytes()).hexdigest(),
 'old_episode_evidence':False,'modes':[]}
for name,selection in [('original_four_classes','%file,%process,%memory,%desc'),('explicit_names','unshare,close_range')]:
    out=HERE/name;out.mkdir(exist_ok=False)
    argv=[str(binary),'--seccomp-bpf','-ff','-qq','-ttt','-T','-s','256','-e','trace='+selection,
          '-o',str(out/'syscalls'),sys.executable,str(HERE/'child.py')]
    with (out/'stdout.json').open('xb') as stdout,(out/'stderr.txt').open('xb') as stderr:
        result=subprocess.run(argv,stdout=stdout,stderr=stderr,check=False)
    child=json.loads((out/'stdout.json').read_text())
    observed={key:[] for key in ('unshare','close_range')}
    receipts=[]
    for path in sorted(out.glob('syscalls.*')):
        raw=path.read_bytes();receipts.append({'path':str(path),'sha256':hashlib.sha256(raw).hexdigest(),'bytes':len(raw)})
        for number,line in enumerate(raw.decode().splitlines(),1):
            for key in observed:
                if ' '+key+'(' in line:observed[key].append({'line':number,'rendering':line,'artifact':str(path)})
    report['modes'].append({'mode':name,'argv':argv,'actual_exit':result.returncode,'child':child,
        'observed':observed,'raw_receipts':receipts})
first,second=report['modes']
assert all(row['actual_exit']==0 for row in report['modes'])
assert all(not first['observed'][key] and len(second['observed'][key])==1 for key in ('unshare','close_range'))
report['status']='CONFIRMED_FOUR_CLASS_FILTER_OMITS_BOTH_INVOKED_SYSCALLS'
with (HERE/'summary.json').open('x') as stream:json.dump(report,stream,indent=2,sort_keys=True);stream.write('\n')
print(json.dumps({'status':report['status'],'actual_exits':[m['actual_exit'] for m in report['modes']]}))
