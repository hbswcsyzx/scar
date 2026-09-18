import inspect

from scar.ir import CodeID, from_source


def _compiled_function(constant):
    namespace = {}
    exec(compile(f"def f():\n    return {constant}\n", "<dynamic-source>", "exec"), namespace)
    return namespace["f"].__code__


def test_loaded_code_version_changes_without_a_source_file():
    first = CodeID.from_code(_compiled_function(1))
    second = CodeID.from_code(_compiled_function(2))
    assert first.source == second.source and first.line == second.line
    assert first.version != second.version
    assert first == CodeID.from_code(_compiled_function(1))


def test_code_key_parser_handles_colons_in_version_fingerprint():
    original = CodeID.from_code(_compiled_function(3))
    assert CodeID.parse_key(original.key()) == original


def test_one_frame_keeps_its_function_identity_across_instructions():
    frame = inspect.currentframe()
    try:
        first = CodeID.from_frame(frame)
        second = CodeID.from_frame(frame)
        assert first == second
    finally:
        del frame


def test_static_nodes_are_namespaced_by_source_version(tmp_path):
    source = tmp_path / "program.py"
    source.write_text("x = 1\n")
    before = from_source(source)
    source.write_text("x = 2\n")
    after = from_source(source)
    assert set(before.nodes).isdisjoint(after.nodes)
    assert all(node.attrs.get("source_version", "").startswith("source-sha256:")
               for node in after.nodes.values() if node.line is not None)
