"""Auto-loaded by Python child processes launched by SCAR."""
import os

if os.environ.get("SCAR_TRACE_DIR"):
    try:
        if os.environ.get('SCAR_TRACE_CALL_EDGES') == '1':
            from scar.trace.call_edges import install
            _scar_lean_plan = None
            if os.environ.get('SCAR_CAPTURE_PLAN') is not None:
                from scar.trace.lean_capture import read_plan as _scar_read_plan
                _scar_lean_plan = _scar_read_plan(os.environ['SCAR_CAPTURE_PLAN'],
                    expected_sha256=os.environ['SCAR_CAPTURE_PLAN_SHA256'])
            _scar_recorder = install(os.environ['SCAR_TRACE_DIR'],os.environ['SCAR_CALL_PROJECT_ROOT'],
                                     lean_plan=_scar_lean_plan)
            if _scar_recorder is not None and getattr(_scar_recorder, 'collector_witness', None) is not None:
                import sys as _scar_sys
                _scar_recorder.collector_witness.register_loader(_scar_sys._getframe())
            if _scar_recorder is not None and os.environ.get('SCAR_CALL_OPERANDS') == '1':
                from scar.trace.call_operands import install as _scar_install_operands
                _scar_install_operands(_scar_recorder,
                    python_targets=os.environ.get('SCAR_PYTHON_CALL_TARGETS') == 'PYTHON_CALL_TARGETS_V2')
            if _scar_recorder is not None and os.environ.get('SCAR_EXECUTION_EVIDENCE') == '1':
                import atexit as _scar_atexit
                from scar.trace.execution_evidence import install as _scar_install_evidence
                _scar_evidence = _scar_install_evidence(os.environ['SCAR_TRACE_DIR'], recorder=_scar_recorder)
                # Close provider artifacts before the earlier call-recorder
                # callback. It remains the sole Python profile-hook owner.
                _scar_atexit.register(_scar_evidence.close)
        else:
            from scar.trace.inject import install
            install()
    except Exception as _scar_error:
        # A profiler must never make the target program fail to start.
        if os.environ.get("SCAR_TRACE_DEBUG"):
            print(f"SCAR injector disabled: {_scar_error}", flush=True)
elif os.environ.get("SCAR_OPTIMIZE"):
    try:
        from scar.trace.optimizer import install
        install()
    except Exception as _scar_error:
        # The backend is opt-in; a failed optimizer must leave the original
        # target execution available for comparison.
        if os.environ.get("SCAR_TRACE_DEBUG"):
            print(f"SCAR optimizer disabled: {_scar_error}", flush=True)
