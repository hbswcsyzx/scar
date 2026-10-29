"""Call/return provenance is inferred from source; the application never runs."""
import gzip
import json
import subprocess
import sys
from pathlib import Path
from tempfile import TemporaryDirectory


SOURCE = """def a():
    return 11
def b():
    return 22
def identity(value):
    return value
def get_a():
    return a
def get_b():
    return b
def apply(function):
    return function()
def relay(function):
    return identity(function)
def shadow(function):
    function = b
    return function
def cycle(function):
    return cycle(function)
fa = identity(a)
fb = identity(b)
fa()
fb()
ra = apply(get_a)
rb = apply(get_b)
ra()
rb()
xa = relay(a)
xb = relay(b)
xa()
xb()
changed = shadow(a)
changed()
unseeded = cycle(a)
unseeded()
raise RuntimeError("this application must never execute")
"""


def test_static_call_contexts_preserve_values_and_stop_unseeded_cycles():
    from scar.ir.program.static_calls import loads

    with TemporaryDirectory(prefix="scar-static-values-") as temporary:
        root = Path(temporary)
        source = root / "source"
        source.mkdir()
        application = source / "application.py"
        application.write_text(SOURCE)
        model = root / "model"
        for options in ((), ("--expand",), ("--link-calls",)):
            result = subprocess.run(
                [sys.executable, "-B", "-m", "scar.cli", "static", str(source),
                 "--out", str(model), "--jobs", "1", *options],
                capture_output=True, text=True,
            )
            assert result.returncode == 0, result.stderr + result.stdout

        manifest = json.loads((model / "manifest.json").read_text())
        publication = manifest["static_calls"]
        assert publication["schema_version"] == 5
        assert publication["scope"]["value_worklist_quiescent_for_processed_scope"]
        assert not publication["scope"]["whole_program_model_complete"]
        names = {definition["wire"]: body["name"]
                 for unit in manifest["units"] for body in unit["bodies"]
                 for definition in body.get("definitions", ())}
        calls = []
        for shard in publication["shards"]:
            payload = gzip.decompress(
                (model / "indexes" / "calls" / shard["artifact"]["path"]).read_bytes()
            ).decode()
            calls.extend(loads(payload).calls)
        lines = SOURCE.splitlines()
        expected = {"fa()": "a", "fb()": "b", "ra()": "a", "rb()": "b",
                    "xa()": "a", "xb()": "b", "changed()": "b"}
        for expression, name in expected.items():
            selected = [call for call in calls if call.source.start_line == lines.index(expression) + 1]
            assert len(selected) == 1
            assert {names[target.definition.definition.wire] for target in selected[0].targets} == {"<module>." + name}
        recursive_result = [call for call in calls
                            if call.source.start_line == lines.index("unseeded()") + 1]
        assert len(recursive_result) == 1 and not recursive_result[0].targets
        assert any(flow.requirements for call in calls for flow in call.return_value_flows)
        from scar.analysis.static_query import query_static_program
        entry = next(body["entry_key"] for unit in manifest["units"] for body in unit["bodies"]
                     if body["name"] == "<module>.relay")
        query = query_static_program(model, file=str(application), name=entry, limit=100,
                                     include_dependencies=True)
        shards = query["dependencies"]["static_calls"]["shards"]
        assert shards and all(shard["v5_value_flows_checked"] for shard in shards)
        verified = [call for shard in shards for call in shard["calls"]["items"]]
        assert verified and any(flow["requirements"] for call in verified
                               for flow in call["argument_value_flows"]["items"])
        assert application.read_text() == SOURCE
