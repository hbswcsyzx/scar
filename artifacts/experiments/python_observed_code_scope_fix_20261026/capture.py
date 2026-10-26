"""One CPU example: direct code, opaque partial wrapper, same code, sentinel."""
from pathlib import Path
import functools,json,sys

ROOT=Path(__file__).resolve().parent
sys.path[:0]=[str(ROOT/'example/project'),str(ROOT/'example/dependency')]
import entry,external
from scar.trace.call_edges import install
from scar.trace.call_operands import install as install_operands
output=ROOT/sys.argv[1]
entry.gateway=functools.partial(external.opaque_wrapper,external.selected)
recorder=install(output,ROOT/'example/project')
observer=install_operands(recorder,capture='windows',max_events=10000,max_bytes=4_000_000,
    python_targets=sys.argv[2]=='v2')
token=object()
assert entry.run(token) is token
print(json.dumps({'status':'CPU_EXAMPLE_RETURNED','output':str(output),'v2':sys.argv[2]=='v2'}))
