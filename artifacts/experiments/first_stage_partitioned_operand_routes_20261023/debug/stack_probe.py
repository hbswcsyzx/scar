"""One bounded stack observation of our offline analysis process, never LeWM."""
def _scar_probe_20261023():
    import json
    import os
    import sys
    import time
    from pathlib import Path
    try:
        frames = []
        for thread, top in sys._current_frames().items():
            depth = 0
            current = top
            while current is not None and depth < 64:
                code = current.f_code
                row = {'thread': thread, 'file': code.co_filename,
                       'function': code.co_name, 'line': current.f_lineno}
                if code.co_filename.endswith('/scar/analysis/call_operand_routes.py'):
                    sizes = {}
                    for name in ('issues', 'attempts', 'arguments', 'returns', 'handshakes', 'by_attempt'):
                        value = current.f_locals.get(name)
                        if type(value) in (list, tuple, dict, set, frozenset):
                            sizes[name] = len(value)
                    row['container_sizes'] = sizes
                frames.append(row)
                current = current.f_back
                depth += 1
        out = Path('/home/zyf/AAA/scar-worktrees/structured-program-model/artifacts/experiments/first_stage_partitioned_operand_routes_20261023/debug/stack-observation.json')
        doc = {'schema': 'scar.offline-analysis-stack-observation', 'schema_version': 1,
               'pid': os.getpid(), 'time_ns': time.time_ns(), 'frames': frames,
               'model_state_modified': False, 'target_executed': False}
        raw = json.dumps(doc, indent=2).encode() + b'\n'
        if len(raw) <= 100000:
            with out.open('xb') as stream:
                stream.write(raw)
    except BaseException:
        # A debug observation must not abort or replace the analysis outcome.
        pass


_scar_probe_20261023()
del _scar_probe_20261023
