from pathlib import Path
import sys
HERE=Path(__file__).resolve().parent
sys.path[:0]=[str(HERE/'project'),str(HERE/'dependency')]
import sample
from scar.trace.call_edges import install
from scar.trace.call_operands import install as install_operands
recorder=install(HERE/'capture',HERE/'project')
observer=install_operands(recorder,capture='windows',max_events=4096,max_bytes=2_000_000,max_references=8192)
result=sample.run()
assert result==34,result
print('GENERIC_METHOD_FUNCTION_EXTERNAL_NATIVE_CAPTURE_RETURNED',result)
