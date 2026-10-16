"""Auto-loaded by Python child processes launched by SCAR."""
import os

if os.environ.get("SCAR_TRACE_DIR"):
    try:
        if os.environ.get('SCAR_TRACE_CALL_EDGES') == '1':
            from scar.trace.call_edges import install
            _scar_recorder = install(os.environ['SCAR_TRACE_DIR'],os.environ['SCAR_CALL_PROJECT_ROOT'])
            if _scar_recorder is not None and os.environ.get('SCAR_CALL_OPERANDS') == '1':
                from scar.trace.call_operands import install as _scar_install_operands
                _scar_install_operands(_scar_recorder)
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
