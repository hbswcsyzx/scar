"""One diagnostic of SCAR's own main-thread stack; no application values."""
import sys as _scar_probe_sys
import json as _scar_probe_json
import time as _scar_probe_time
from pathlib import Path as _scar_probe_Path
_scar_probe_records=[]
for _scar_probe_thread,_scar_probe_frame in _scar_probe_sys._current_frames().items():
    _scar_probe_stack=[]
    while _scar_probe_frame is not None:
        _scar_probe_stack.append({'file':_scar_probe_frame.f_code.co_filename,
                                  'function':_scar_probe_frame.f_code.co_name,
                                  'line':_scar_probe_frame.f_lineno})
        _scar_probe_frame=_scar_probe_frame.f_back
    _scar_probe_records.append({'thread_id':_scar_probe_thread,'stack':_scar_probe_stack})
_scar_probe_Path('/home/zyf/AAA/scar/artifacts/experiments/n2_call_source_seeds/stack.json').write_text(
    _scar_probe_json.dumps({'scope':'One live stack diagnostic of SCAR seed analysis; no values captured',
                            'time':_scar_probe_time.time(),'threads':_scar_probe_records},indent=2)+'\n')
