"""Only this owned child gets SIGINT, inside a real monitoring callback."""
import json,os,signal,sys
from pathlib import Path

ROOT=Path(sys.argv[1]).resolve()
for name in tuple(os.environ):
    if name.startswith('SCAR_'):del os.environ[name]
os.environ.update(SCAR_PYTHON_CAPTURE_PROFILE='SCAR_PROGRAM_PORTS_V2',
    SCAR_CAPTURE_TRANSPORT='jsonl',SCAR_OPERAND_CAPTURE='process-ports',
    SCAR_PYTHON_CALL_TARGETS='PYTHON_CALL_TARGETS_V2')
from scar.trace.call_edges import install
from scar.trace.call_operands import install as install_operands,CallOperandObserver

def lightweight(value):
    return value

sent=False
original=CallOperandObserver._shape
def interrupt_in_shape(self,value,*args,**kwargs):
    global sent
    if value is lightweight and not sent:
        sent=True
        os.kill(os.getpid(),signal.SIGINT)
    return original(self,value,*args,**kwargs)
CallOperandObserver._shape=interrupt_in_shape
trace=ROOT/'trace';trace.mkdir(parents=True)
recorder=install(trace,Path(__file__).parent)
observer=install_operands(recorder,capture='process-ports',python_targets=True)
result={'sigint_sent':False,'loop_completed':False,'keyboard_interrupt_reached_program':False,
        'only_owned_process_signalled':True,'Torch_or_LeWM_imported':False}
def run_loop():
    # Enter after observer registration: the already-active module frame has
    # no retroactive monitoring mask and cannot exercise an actual CALL hook.
    for index in range(100):lightweight(index)
try:
    run_loop()
    result['loop_completed']=True
except KeyboardInterrupt:
    result['keyboard_interrupt_reached_program']=True
    raise
finally:
    recorder._collector_finish()
    result['sigint_sent']=sent
    result['operand_errors']=list(observer._errors)
    (ROOT/'RESULT.json').write_text(json.dumps(result,indent=2)+'\n')
