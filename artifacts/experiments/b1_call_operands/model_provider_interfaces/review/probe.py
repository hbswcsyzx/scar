"""One bounded P0 review probe; manual graphs, no provider/target execution."""
from dataclasses import replace
import hashlib
import json
from pathlib import Path
import platform
import subprocess

from scar.ir.program import OperationID, ValueID
from scar.ir.program.codec import dumps, loads
from scar.ir.program.providers import (
    ProviderBinding, ProviderElement, ProviderElementKind, ProviderPathIndex,
    ProviderPathKey, ProviderRegion, ProviderRegionRelation,
)
from scar.ir.program.queries import ProgramIndex
from scar.ir.program.validation import validate
from tests.fixtures.program_provider_graphs import (
    _envelope, definition_provider_graph, execution_observation_graph,
)
from tests.unit.test_program_completions_adversarial import _invoke_graph, _forward_slot
from scar.ir.program import ExitKind

ROOT = Path.cwd()
OUT = Path(__file__).parent
FILES = (
    "scar/ir/program/providers.py", "scar/ir/program/provider_validation.py",
    "scar/ir/program/model.py", "scar/ir/program/codec.py",
    "scar/ir/program/queries.py", "scar/cli.py", "docs/M1_PROVIDER_INTERFACES.md",
)
def hashes():
    return {name: hashlib.sha256((ROOT / name).read_bytes()).hexdigest() for name in FILES}

def attach(base, value, external_key, path):
    envelope = _envelope("completion-provider")
    association = ProviderRegion(envelope.id, "main", base.root,
                                 ProviderRegionRelation.DEFINES_REPRESENTATION)
    operations = tuple(ProviderBinding(envelope.id, base.root,
        ProviderElement(ProviderElementKind.OPERATION, key), OperationID(name))
        for key, name in (("invoke", "main.invoke"), ("return", "main.normal.done"),
                          ("raise", "main.raise.done")))
    kind = ProviderElementKind.STATE_VALUE if value.endswith("world") else ProviderElementKind.REFERENCE_VALUE
    result = ProviderBinding(envelope.id, base.root,
        ProviderElement(kind, external_key, path), ValueID(value))
    return replace(base, provider_envelopes=(envelope,), provider_regions=(association,),
                   provider_bindings=(*operations, result))

def observe(graph):
    issues = validate(graph)
    row = {"issues": [dict(code=i.code, path=i.path, message=i.message) for i in issues]}
    try:
        encoded = dumps(graph)
        row.update(codec_accepted=True, roundtrip_equal=loads(encoded) == graph,
                   schema_version=json.loads(encoded)["schema_version"])
    except (ValueError, TypeError) as exc:
        row.update(codec_accepted=False, error=str(exc))
    return row

report = {"python": platform.python_version(), "head": subprocess.check_output(
    ["git", "rev-parse", "HEAD"], text=True).strip(), "source_before": hashes(),
    "scope": "manual declaration/validator probe; no source/provider/runtime proof", "cases": {}}
cases = report["cases"]
base = _invoke_graph()
cases["valid_produced_normal"] = observe(attach(base, "main.normal.value", "invoke",
    (ProviderPathKey("normal"), ProviderPathIndex(0))))
cases["wrong_producer_normal"] = observe(attach(base, "main.normal.value", "return",
    (ProviderPathKey("normal"), ProviderPathIndex(0))))
cases["missing_projection_normal"] = observe(attach(base, "main.normal.value", "invoke", ()))
cases["wrong_producer_raise"] = observe(attach(base, "main.raise.value", "return",
    (ProviderPathKey("raise"), ProviderPathIndex(0))))
cases["wrong_producer_poststate"] = observe(attach(base, "main.normal.world", "return",
    (ProviderPathKey("world"),)))
cases["ordinary_entry_has_no_invented_producer"] = observe(attach(base, "main.input", "parameter", ()))
forwarded = _forward_slot(base, ExitKind.NORMAL, 0)
cases["forwarded_block_argument_is_not_produced"] = observe(attach(
    forwarded, "main.normal.value", "forwarded", ()))
observed = execution_observation_graph()
owner = observed.provider_regions[0]
many = replace(observed, provider_regions=(owner,
    replace(owner, region=observed.root), replace(owner, external_region="another.window")))
cases["observation_scope_many_to_many"] = observe(many)
declared = definition_provider_graph(complete_claims=True)
index = ProgramIndex(declared)
cases["complete_declaration_query"] = {
    "issues": [i.code for i in validate(declared)],
    "declared_completeness": [c.completeness.value for c in declared.provider_envelopes[0].coverage],
    "conditions": len(declared.provider_envelopes[0].conditions),
    "left_target": index.provider_sources(next(row.target for row in declared.provider_bindings
        if str(row.target) == "program_use:twice.left"))[0].target.wire,
    "query_result_class": type(index.provider_region_sources(declared.provider_regions[0].region)[0]).__name__,
}
for version in range(2, 7):
    payload = (ROOT / f"tests/fixtures/program_graph_v{version}_frozen.json").read_text().rstrip("\n")
    graph = loads(payload)
    mutated = json.loads(payload)
    mutated["provider_envelopes"] = []
    try:
        loads(json.dumps(mutated))
        rejected = False
    except ValueError:
        rejected = True
    cases[f"historical_v{version}"] = {"wire_equal": dumps(graph) == payload,
        "empty_future_table_rejected": rejected}
report["source_after"] = hashes()
report["source_unchanged"] = report["source_before"] == report["source_after"]
(OUT / "probe.result.json").write_text(json.dumps(report, indent=2) + "\n")
print(json.dumps(report, indent=2))
