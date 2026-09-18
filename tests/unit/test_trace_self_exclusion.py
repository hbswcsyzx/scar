from types import SimpleNamespace

from scar.trace import session as session_module


def test_tracer_excludes_its_own_installed_location(tmp_path, monkeypatch):
    package = tmp_path / "wheel-target" / "scar"
    monkeypatch.setattr(session_module, "__file__", str(package / "trace" / "session.py"))
    session = session_module.TraceSession(tmp_path / "trace")
    try:
        internal = compile("pass", str(package / "backends" / "reuse.py"), "exec")
        session.python_call(SimpleNamespace(f_code=internal, f_lineno=1))
        assert session.event_count == 0
        external = compile("pass", str(tmp_path / "application.py"), "exec")
        session.python_call(SimpleNamespace(f_code=external, f_lineno=1))
        assert session.event_count == 1
    finally:
        session.close()
