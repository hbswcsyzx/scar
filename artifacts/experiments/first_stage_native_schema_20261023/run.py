"""Recover real native schema ports and audit the original ordered slots once."""
from collections import Counter
import gc
import gzip
from hashlib import sha256
import json
from pathlib import Path
import subprocess
import time

from scar.ir.v2 import IRBundle
from scar.trace.native_import import NativeImportResult
from scar.trace.native_schema import PROVIDER_REVISION, recover_schema_contracts

ROOT = Path(__file__).resolve().parent
WORKTREE = ROOT.parents[2]
INPUT = ROOT.parent / "first_stage_joined_dispatch_20261023/result/native"
STARTED = time.perf_counter()
LOG = ROOT / "stages.jsonl"


def stage(name, **fields):
    row = {"stage": name, "elapsed_s": round(time.perf_counter() - STARTED, 3), **fields}
    line = json.dumps(row, sort_keys=True)
    print(line, flush=True)
    with LOG.open("a", encoding="utf-8") as stream:
        stream.write(line + "\n")


def stored(path):
    digest, size = sha256(), 0
    with path.open("rb") as stream:
        while chunk := stream.read(2**20):
            digest.update(chunk); size += len(chunk)
    return {"path": str(path), "stored_sha256": digest.hexdigest(), "stored_bytes": size}


def read(path):
    receipt = stored(path)
    stage("read_begin", artifact=receipt)
    with gzip.open(path, "rb") as stream:
        payload = stream.read()
    receipt.update(raw_sha256=sha256(payload).hexdigest(), raw_bytes=len(payload))
    document = json.loads(payload)
    del payload
    stage("read_end", artifact=receipt)
    return document, receipt


def write(path, document):
    encoder, digest, size = json.JSONEncoder(sort_keys=True, separators=(",", ":"), allow_nan=False), sha256(), 0
    parts, length = [], 0
    with gzip.open(path, "wb", compresslevel=1) as stream:
        for part in encoder.iterencode(document):
            parts.append(part); length += len(part)
            if length >= 65536:
                payload = "".join(parts).encode("utf-8")
                digest.update(payload); size += len(payload); stream.write(payload)
                parts, length = [], 0
        if parts:
            payload = "".join(parts).encode("utf-8")
            digest.update(payload); size += len(payload); stream.write(payload)
    return {**stored(path), "raw_sha256": digest.hexdigest(), "raw_bytes": size}


def slot_digest(bundle):
    digest, count = sha256(), 0
    for instance in bundle.evidence.instances.values():
        if instance.metadata.get("provider") != "ETO":
            continue
        for ordinal, slot in enumerate(instance.metadata.get("tensor_slots", ())):
            row = [instance.id.wire, ordinal, slot["role"], slot["ordered_path"],
                   slot["provider_reference"], slot["descriptor_id"], slot["raw_reference"]]
            digest.update(json.dumps(row, separators=(",", ":")).encode()); digest.update(b"\n")
            count += 1
    return digest.hexdigest(), count


def value_ids(bundle):
    graph = bundle.values
    return {name: frozenset(getattr(graph, name)) for name in (
        "logical_values", "versions", "provenance", "allocations", "regions", "materializations", "objects")}


LOG.write_text("")
implementation = {"git_head": subprocess.check_output(["git", "rev-parse", "HEAD"], cwd=WORKTREE, text=True).strip(),
    "source_sha256": sha256((WORKTREE / "scar/trace/native_schema.py").read_bytes()).hexdigest(),
    "script_sha256": sha256(Path(__file__).read_bytes()).hexdigest()}
stage("start", implementation=implementation)
document, bundle_source = read(INPUT / "evidence-bundle.json.gz")
stage("bundle_decode_begin")
bundle = IRBundle.from_dict(document)
del document
gc.collect()
stage("bundle_decode_end", instances=len(bundle.evidence.instances), definitions=len(bundle.semantic.definitions))
report, report_source = read(INPUT / "import-report.json.gz")
native = NativeImportResult(bundle, report, [], [])
graph = bundle.semantic
before = {"slots": frozenset(graph.slots), "effects": frozenset(graph.effects), "edges": frozenset(graph.edges),
          "definitions": frozenset(graph.definitions), "instances": frozenset(bundle.evidence.instances),
          "value_ids": value_ids(bundle), "slot_observations": slot_digest(bundle)}
stage("recover_begin", actual_tensor_slots=before["slot_observations"][1])
recovered = recover_schema_contracts(native, provider_revision=PROVIDER_REVISION)
stage("recover_end", unique_schemas=recovered["unique_schemas_parsed"],
      definitions=recovered["definitions_with_ports"], counts=recovered["actual_tensor_slot_counts"])
assert before["definitions"] == frozenset(graph.definitions)
assert before["instances"] == frozenset(bundle.evidence.instances)
assert before["value_ids"] == value_ids(bundle)
assert before["slot_observations"] == slot_digest(bundle)
assert before["slots"] <= graph.slots.keys() and before["effects"] <= graph.effects.keys() and before["edges"] <= graph.edges.keys()
new_slots, new_effects, new_edges = set(graph.slots) - before["slots"], set(graph.effects) - before["effects"], set(graph.edges) - before["edges"]
assert len(new_slots) == recovered["formal_slots"] and len(new_effects) == recovered["effect_summaries"]
slot_index = {slot.slot_id.wire: slot for slot in graph.slots.values()}
instances = {instance.id.wire: instance for instance in bundle.evidence.instances.values()}
bindings = {}
counts = Counter()
for row in recovered["bindings"]:
    instance = instances[row["instance"]["wire"]]
    assert row["definition"] == instance.definition.as_dict()
    key = (instance.id.wire, row["actual_tensor_slot_index"])
    assert key not in bindings
    bindings[key] = row
    actual = instance.metadata["tensor_slots"][row["actual_tensor_slot_index"]]
    assert row["ordered_path"] == actual["ordered_path"] and row["role"] == actual["role"]
    assert row["provider_reference"] == actual["provider_reference"] and row["raw_reference"] == actual["raw_reference"]
    assert row["provider_reference"] in bundle.evidence.provider_references
    annotation = actual["native_schema_binding"]
    assert annotation["formal_slot"] == row["formal_slot"] and annotation["status"] == row["status"]
    counts[row["status"]] += 1
    if row["status"] == "QUALIFIED":
        formal = slot_index[row["formal_slot"]["wire"]]
        assert formal.owner == instance.definition
        definition = graph.definitions[instance.definition]
        interface = definition.input_slots if row["role"] == "inputs" else definition.output_slots
        assert interface[row["ordered_path"][0]] == formal.slot_id
        assert formal.metadata["native_schema"]["ordinal"] == row["ordered_path"][0]
        assert formal.metadata["native_schema"]["direction"] == ("input" if row["role"] == "inputs" else "output")
        assert sha256(definition.metadata["op_schema"].encode()).hexdigest() == row["schema_sha256"]
    else:
        assert row["formal_slot"] is None and row["gap"]
unqualified = {row["instance"]["wire"]: row for row in recovered["unqualified_without_schema"]}
for instance in bundle.evidence.instances.values():
    if instance.metadata.get("provider") != "ETO":
        continue
    for ordinal, actual in enumerate(instance.metadata.get("tensor_slots", ())):
        if (instance.id.wire, ordinal) in bindings:
            continue
        declared = unqualified[instance.id.wire]
        assert declared["actual_tensor_slots"] == len(instance.metadata["tensor_slots"])
        assert actual["native_schema_binding"]["status"] == "UNQUALIFIED"
        assert actual["native_schema_binding"]["formal_slot"] is None
        counts["UNQUALIFIED"] += 1
assert dict(counts) == recovered["actual_tensor_slot_counts"]
assert sum(counts.values()) == before["slot_observations"][1]
updated = []
for definition in graph.definitions.values():
    if "native_schema_contract" not in definition.metadata:
        continue
    updated.append(definition)
    effect = graph.effects[definition.effect_summary]
    assert not effect.is_complete and effect.writes.completeness.value == "PARTIAL" and effect.aliases.completeness.value == "PARTIAL"
    for collection in (effect.reads, effect.writes, effect.aliases, effect.allocates, effect.frees, effect.escapes):
        for target in collection.members:
            if target.kind.value == "value_slot":
                assert target.reference in slot_index
    for identity in definition.input_slots + definition.output_slots:
        assert graph.slots[identity].owner == definition.id
assert len(updated) == recovered["definitions_with_ports"]
stage("endpoint_audit_pass", qualified=counts["QUALIFIED"], unqualified=counts["UNQUALIFIED"],
      actual_slots_unchanged_sha256=before["slot_observations"][0])
delta = {"schema": "scar.native-schema-graph-delta", "schema_version": 1,
    "kind": "derived_semantic_graph_delta_not_a_new_program_or_value_graph",
    "base_bundle": bundle_source, "base_import_report": report_source,
    "implementation": implementation, "provider_revision": PROVIDER_REVISION,
    "replay_api": "recover_schema_contracts(NativeImportResult(IRBundle.from_dict(base_bundle), base_report, [], []))",
    "slots": [graph.slots[key].as_dict() for key in sorted(new_slots, key=lambda item: item.wire)],
    "effects": [graph.effects[key].as_dict() for key in sorted(new_effects, key=lambda item: item.wire)],
    "edges": [graph.edges[key].as_dict() for key in sorted(new_edges)],
    "updated_definitions": [definition.as_dict() for definition in sorted(updated, key=lambda item: item.id.wire)],
    "actual_slot_bindings": "report.json.gz bindings and unqualified_without_schema refer to the unchanged original ETO instance/slot identities",
    "whole_model_established": False, "transformation_authorized": False}
stage("write_report_begin")
report_output = write(ROOT / "report.json.gz", recovered)
stage("write_report_end", artifact=report_output)
delta_output = write(ROOT / "schema-graph-delta.json.gz", delta)
stage("write_delta_end", artifact=delta_output)
summary = {"schema": "scar.native-schema-real-capture-acceptance", "valid": True,
    "implementation": implementation, "inputs": {"bundle": bundle_source, "report": report_source},
    "unique_schemas_parsed": recovered["unique_schemas_parsed"], "parse_failures": recovered["parse_failures"],
    "definitions_with_ports": len(updated), "new_slots": len(new_slots), "new_effects": len(new_effects), "new_edges": len(new_edges),
    "actual_tensor_slot_counts": dict(counts), "binding_gaps": recovered["binding_gaps"],
    "contract_gaps": recovered["contract_gaps"], "actual_slot_observations_unchanged": True,
    "value_graph_ids_unchanged": True, "instance_ids_unchanged": True,
    "all_actual_slot_bindings_audited": True, "all_new_endpoints_audited": True,
    "outputs": {"report": report_output, "semantic_delta": delta_output},
    "elapsed_s": round(time.perf_counter() - STARTED, 3),
    "whole_model_established": False, "transformation_authorized": False}
(ROOT / "summary.json").write_text(json.dumps(summary, indent=2, sort_keys=True) + "\n")
stage("complete", summary="summary.json")
