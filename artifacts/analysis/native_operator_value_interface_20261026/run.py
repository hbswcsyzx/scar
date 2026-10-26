#!/usr/bin/env python3
"""Build and read one real view -> add_ -> view native interface path."""
from __future__ import annotations

from hashlib import sha256
import gzip
import json
from pathlib import Path
import sys
import time


ROOT = Path(__file__).resolve().parents[3]
sys.path.insert(0, str(ROOT))

from scar.ir.execution.content import EvidenceEdgeRef
from scar.ir.program.providers import ProviderArtifact, ProviderFactReference
from scar.ir.record_codec import decode
from scar.ir.v2.evidence import OperationInstance, ProviderReference
from scar.ir.v2.ids import OperationDefinitionID, ValueSlotID
from scar.ir.v2.contracts import EffectSummary
from scar.ir.v2.semantic import OperationDefinition, ValueSlot
from scar.store.bundle_partitions import BundlePartitions
from scar.trace.native_port_sidecar import query_native_ports, read_native_port_index
from scar.trace.native_reference_flow import (
    query_native_reference_flow_upstream, read_native_reference_flow_index,
)
from scar.trace.native_operator_value_interface import (
    NativePhysicalCandidateRef, build_native_operator_value_fragment,
    query_native_operator_value_port, read_native_operator_value_fragment,
    write_native_operator_value_fragment,
)


MAIN = Path("/home/zyf/AAA/scar-worktrees/structured-program-model")
IMPORT = MAIN / "artifacts/experiments/native_inputs_full_20261026/native-import/native"
BUNDLE = IMPORT / "bundle-partitions"
PORT_PUBLICATION = ROOT / "artifacts/analysis/native_port_sidecar_full_20261026/publication"
FLOW_PUBLICATION = ROOT / "artifacts/analysis/native_reference_flow_20261026/publication"
OUTPUT = ROOT / "artifacts/analysis/native_operator_value_interface_20261026/publication-v3"
REPORT = ROOT / "artifacts/analysis/native_operator_value_interface_20261026/report.json"
ORDINALS = (21684, 21686, 21694)


def sha_file(path: Path) -> str:
    digest = sha256()
    with path.open("rb") as stream:
        for block in iter(lambda: stream.read(1 << 20), b""):
            digest.update(block)
    return digest.hexdigest()


def wire_value(value: str, prefix: str) -> str:
    expected = prefix + ":"
    if not value.startswith(expected):
        raise ValueError(f"expected {prefix} wire ID, got {value}")
    return value[len(expected):]


def main() -> int:
    started = time.perf_counter()
    partitions = BundlePartitions(BUNDLE)
    bundle_manifest_path = BUNDLE / "manifest.json"
    bundle_artifact = ProviderArtifact(
        str(bundle_manifest_path.resolve()), partitions.manifest_receipt["physical_sha256"],
        partitions.manifest_receipt["physical_bytes"], partitions.manifest["schema"])

    port_index = read_native_port_index(PORT_PUBLICATION,
        expected_sha256="54f9dfbcc8a4e3cfc720c2dfb0c377d61707cde3f70c1360f1f68fd54cbf17b2")
    port_index_path = (PORT_PUBLICATION / "index.json").resolve()
    port_index_sha = sha_file(port_index_path)
    port_index_artifact = ProviderArtifact(str(port_index_path), port_index_sha,
        port_index_path.stat().st_size, "scar.native-boxed-port-index")
    eto_artifact = ProviderArtifact(port_index.source_uri, port_index.source_sha256,
        port_index.source_raw_bytes, "pytorch.execution-trace.v1")

    flow_index, flow_sha = read_native_reference_flow_index(
        FLOW_PUBLICATION,
        expected_sha256="63030af42af9adfb883d9b2a04e2289800b08caa95bed0f443f4e118a8f1e6ca")
    flow_index_path = (FLOW_PUBLICATION / "index.json").resolve()
    flow_index_artifact = ProviderArtifact(str(flow_index_path), flow_sha,
        flow_index_path.stat().st_size, "scar.native-reference-flow-index")

    original_envelopes = partitions.selected_records("evidence", "instances", ORDINALS)
    instances = {item["ordinal"]: decode(OperationInstance, item["record"])
                 for item in original_envelopes}
    port_rows = [query_native_ports(instances[ordinal], PORT_PUBLICATION, BUNDLE,
                    expected_index_sha256=port_index_sha) for ordinal in ORDINALS]
    target_definitions = {row.definition for row in port_rows}

    definitions: dict[OperationDefinitionID, OperationDefinition] = {}
    for envelope in partitions.iter_records("semantic", "definitions"):
        raw_id = envelope["record"].get("id", {}).get("wire")
        if raw_id in {item.wire for item in target_definitions}:
            record = decode(OperationDefinition, envelope["record"])
            definitions[record.id] = record
    if set(definitions) != target_definitions:
        raise ValueError("selected native operations do not resolve to all original semantic definitions")
    target_slots = {slot for definition in definitions.values()
                    for slot in definition.input_slots + definition.output_slots + definition.state_slots}
    slots: dict[ValueSlotID, ValueSlot] = {}
    for envelope in partitions.iter_records("semantic", "slots"):
        raw_id = envelope["record"].get("slot_id", {}).get("wire")
        if raw_id in {item.wire for item in target_slots}:
            record = decode(ValueSlot, envelope["record"])
            slots[record.slot_id] = record
    if set(slots) != target_slots:
        raise ValueError("selected schema formal slots are not fully present in the original semantic graph")
    target_effects = {definition.effect_summary for definition in definitions.values()
                      if definition.effect_summary is not None}
    effects: dict = {}
    for envelope in partitions.iter_records("semantic", "effects"):
        raw_id = envelope["record"].get("id", {}).get("wire")
        if raw_id in {item.wire for item in target_effects}:
            record = decode(EffectSummary, envelope["record"])
            effects[record.id] = record
    if set(effects) != target_effects:
        raise ValueError("selected native definitions do not resolve to original EffectSummary records")

    provider_ids = {port.provider_reference for row in port_rows for port in row.ports
                    if port.kind == "TENSOR" and port.provider_reference}
    providers: dict[str, ProviderReference] = {}
    for envelope in partitions.iter_records("evidence", "provider_references"):
        raw_id = envelope["record"].get("reference_id")
        if raw_id in provider_ids:
            record = decode(ProviderReference, envelope["record"])
            providers[record.reference_id] = record
    if set(providers) != provider_ids:
        raise ValueError("selected Tensor ports do not resolve to all original ProviderReferences")

    physical_path = IMPORT / "tensor-physical.json.gz"
    physical_sha = sha_file(physical_path)
    with gzip.open(physical_path, "rt", encoding="utf-8") as stream:
        physical_document = json.load(stream)
    physical_artifact = ProviderArtifact(str(physical_path.resolve()), physical_sha,
        physical_path.stat().st_size, physical_document["schema"])
    wanted_physical_refs = {token for token in provider_ids}
    physical_candidates = []
    for ordinal, association in enumerate(physical_document["associations"]):
        if association.get("provider_reference") not in wanted_physical_refs:
            continue
        physical_candidates.append(NativePhysicalCandidateRef(
            ProviderFactReference(physical_artifact, f"#/associations/{ordinal}"),
            association["provider_reference"], association["storage_region"],
            association["allocation"], association["marker_instance"],
            association["physical_reference"], association.get("object")))

    fragment, graph = build_native_operator_value_fragment(
        port_rows, instances={row.instance: instances[ordinal]
                              for ordinal, row in zip(ORDINALS, port_rows, strict=True)},
        definitions=definitions, effects=effects, slots=slots, provider_references=providers,
        port_index=port_index, port_index_artifact=port_index_artifact,
        bundle_manifest=bundle_artifact, eto_source=eto_artifact,
        flow_index=flow_index, flow_index_artifact=flow_index_artifact,
        flow_publication=FLOW_PUBLICATION,
        physical_candidates=tuple(physical_candidates))

    interface_path = OUTPUT / "operator-values.json"
    OUTPUT.mkdir(parents=True, exist_ok=True)
    write_started = time.perf_counter()
    fragment_sha = write_native_operator_value_fragment(interface_path, fragment, graph)
    write_seconds = time.perf_counter() - write_started

    # One real three-operator route: view result -> add_ reported argument,
    # then add_ result -> later view argument. These remain candidate references.
    first_flows = query_native_reference_flow_upstream(
        FLOW_PUBLICATION, PORT_PUBLICATION, BUNDLE, instances[21686], (1,),
        expected_flow_index_sha256=flow_sha,
        expected_native_port_index_sha256=port_index_sha)
    second_flows = query_native_reference_flow_upstream(
        FLOW_PUBLICATION, PORT_PUBLICATION, BUNDLE, instances[21694], (0,),
        expected_flow_index_sha256=flow_sha,
        expected_native_port_index_sha256=port_index_sha)
    first = next((flow for flow in first_flows if flow.output.source_ordinal == 21684), None)
    second = next((flow for flow in second_flows if flow.output.source_ordinal == 21686
                   and flow.output.path == (0,)), None)
    if first is None or second is None:
        raise ValueError("retained provider-reference candidates do not reproduce the selected three-op route")

    query_start = time.perf_counter()
    add_input_interface, add_input, decoded_graph = query_native_operator_value_port(
        interface_path, instances[21686], "input", (0,), PORT_PUBLICATION, BUNDLE,
        expected_fragment_sha256=fragment_sha,
        expected_native_port_index_sha256=port_index_sha)
    _, add_argument, _ = query_native_operator_value_port(
        interface_path, instances[21686], "input", (1,), PORT_PUBLICATION, BUNDLE,
        expected_fragment_sha256=fragment_sha,
        expected_native_port_index_sha256=port_index_sha)
    add_output_interface, add_output, _ = query_native_operator_value_port(
        interface_path, instances[21686], "output", (0,), PORT_PUBLICATION, BUNDLE,
        expected_fragment_sha256=fragment_sha,
        expected_native_port_index_sha256=port_index_sha)
    view_interface, view_output, _ = query_native_operator_value_port(
        interface_path, instances[21684], "output", (0,), PORT_PUBLICATION, BUNDLE,
        expected_fragment_sha256=fragment_sha,
        expected_native_port_index_sha256=port_index_sha)
    consumer_interface, consumer, _ = query_native_operator_value_port(
        interface_path, instances[21694], "input", (0,), PORT_PUBLICATION, BUNDLE,
        expected_fragment_sha256=fragment_sha,
        expected_native_port_index_sha256=port_index_sha)
    decoded_fragment, decoded_graph = read_native_operator_value_fragment(
        interface_path, expected_sha256=fragment_sha)
    query_seconds = time.perf_counter() - query_start

    if (any(item.logical_value is None for item in
            (add_input, add_argument, add_output, view_output, consumer))
            or decoded_graph.validate()["valid"] is not True):
        raise ValueError("operator interface query did not resolve to typed ValueGraph symbols")
    if not any(item.relation == "DECLARED_MAY_WRITE" and item.left_port_id == add_input.port_id
               for item in add_input_interface.state_boundaries):
        raise ValueError("aten::add_ input formal did not resolve to its schema-declared may-write boundary")
    if not any(item.relation == "SCHEMA_MAY_ALIAS" and item.left_port_id == add_input.port_id
               and item.right_port_id == add_output.port_id
               for item in add_input_interface.state_boundaries):
        raise ValueError("aten::add_ input/output formal ports did not resolve to schema may-alias")
    if (first.output_edge.edge != view_output.original_edge.edge
            or first.input_edge.edge != add_argument.original_edge.edge
            or second.output_edge.edge != add_output.original_edge.edge
            or second.input_edge.edge != consumer.original_edge.edge):
        raise ValueError("reference-flow edges differ from the original operator port references")

    publication_bytes = interface_path.stat().st_size
    per_operator = []
    for interface in decoded_fragment.interfaces:
        input_versions = tuple(item.value_version for item in interface.inputs
                               if item.kind == "TENSOR")
        output_versions = tuple(item.value_version for item in interface.outputs
                                if item.kind == "TENSOR")
        output_provenance = (decoded_graph.versions[output_versions[0]].provenance_id
                             if output_versions else None)
        parent_count = (len(decoded_graph.provenance[output_provenance].inputs)
                        if output_provenance is not None else 0)
        per_operator.append({
            "source_ordinal": interface.source_ordinal,
            "instance": interface.instance.wire,
            "label": interface.label,
            "tensor_input_ports": len(input_versions),
            "tensor_output_ports": len(output_versions),
            "output_provenance_input_versions": parent_count,
            "matches_same_instance_tensor_input_count": parent_count == len(input_versions),
            "cross_instance_reference_flows_as_parents": False,
        })
    report = {
        "schema": "scar.native-operator-value-interface-report",
        "schema_version": 1,
        "terminal_status": "SUCCEEDED",
        "source": {
            "bundle_manifest": bundle_artifact.uri,
            "bundle_manifest_sha256": bundle_artifact.sha256,
            "native_port_index": port_index_artifact.uri,
            "native_port_index_sha256": port_index_artifact.sha256,
            "reference_flow_index": flow_index_artifact.uri,
            "reference_flow_index_sha256": flow_index_artifact.sha256,
            "eto_source_uri": eto_artifact.uri,
            "eto_source_sha256": eto_artifact.sha256,
        },
        "scope": {
            "source_ordinals": list(ORDINALS),
            "operation_labels": [item.label for item in fragment.interfaces],
            "original_port_rows": len(port_rows),
            "ordered_ports": sum(len(row.ports) for row in port_rows),
            "tensor_ports": len(graph.logical_values),
            "tensor_input_ports": sum(item["tensor_input_ports"] for item in per_operator),
            "tensor_output_ports": sum(item["tensor_output_ports"] for item in per_operator),
            "per_operator_tensor_io_and_provenance_parents": per_operator,
            "typed_value_graph_delta": graph.validate()["counts"],
            "schema_state_boundaries": sum(len(item.state_boundaries) for item in fragment.interfaces),
            "physical_reference_candidates": len(fragment.physical_candidates),
        },
        "publication": {
            "path": str(interface_path.resolve()),
            "sha256": fragment_sha,
            "bytes": publication_bytes,
            "write_seconds": round(write_seconds, 3),
            "readback_query_seconds": round(query_seconds, 3),
        },
        "route": {
            "first": {
                "relation": first.relation,
                "status": first.status.value,
                "output_instance": first.output.instance.wire,
                "output_ordinal": first.output.source_ordinal,
                "output_path": list(first.output.path),
                "output_edge": first.output_edge.edge,
                "output_symbol": view_output.value_version.wire,
                "consumer_instance": first.input.instance.wire,
                "consumer_ordinal": first.input.source_ordinal,
                "consumer_path": list(first.input.path),
                "input_edge": first.input_edge.edge,
                "input_symbol": add_argument.value_version.wire,
                "provider_reference": first.provider_reference,
                "descriptor_id": first.descriptor_id,
                "ordering_basis": first.ordering_basis,
                "content_identity": first.content_identity,
                "logical_version": first.logical_version,
            },
            "inplace_interface": {
                "instance": add_input_interface.instance.wire,
                "label": add_input_interface.label,
                "input_port_id": add_input.port_id,
                "input_formal": add_input.formal_slot.wire,
                "input_symbol": add_input.value_version.wire,
                "other_tensor_argument_symbol": add_argument.value_version.wire,
                "output_port_id": add_output.port_id,
                "output_formal": add_output.formal_slot.wire,
                "output_symbol": add_output.value_version.wire,
                "state_boundaries": [{"relation": item.relation,
                    "effect_summary": item.effect_summary.wire if item.effect_summary else None,
                    "left_formal_slot": item.left_formal_slot.wire,
                    "left_port": item.left_port_id,
                    "right_formal_slot": item.right_formal_slot.wire if item.right_formal_slot else None,
                    "right_port": item.right_port_id}
                    for item in add_input_interface.state_boundaries],
                "actual_write": "UNKNOWN",
                "same_symbol_or_content": "NOT_ASSERTED",
            },
            "second": {
                "relation": second.relation,
                "status": second.status.value,
                "output_instance": second.output.instance.wire,
                "output_ordinal": second.output.source_ordinal,
                "output_path": list(second.output.path),
                "output_edge": second.output_edge.edge,
                "output_symbol": add_output.value_version.wire,
                "consumer_instance": second.input.instance.wire,
                "consumer_ordinal": second.input.source_ordinal,
                "consumer_path": list(second.input.path),
                "input_edge": second.input_edge.edge,
                "provider_reference": second.provider_reference,
                "descriptor_id": second.descriptor_id,
                "ordering_basis": second.ordering_basis,
                "content_identity": second.content_identity,
                "logical_version": second.logical_version,
                "consumer_symbol": consumer.value_version.wire,
            },
        },
        "semantics": {
            "unknown_provenance_inputs": "reported Tensor argument interface only; not complete/minimal parents or actual read proof",
            "cross_instance_candidates": "same original provider reference+descriptor; not ValueGraph parents or happens-before",
            "symbol_identity": "different endpoint IDs do not imply different tensor contents",
            "schema_state": "provider-declared may-write and possible-alias, mapped to original actual formal ports; not actual write/alias proof",
            "physical_candidates": "original marker/storage refs keyed by provider token only; not bound to an operator symbol",
            "physical_candidates_for_add_input0": sum(1 for item in fragment.physical_candidates
                if item.provider_reference == add_input.provider_reference),
            "normal_completion_ready_storage_contents": "UNKNOWN",
            "tensor_values_saved": False,
        },
        "elapsed_seconds": round(time.perf_counter() - started, 3),
    }
    REPORT.parent.mkdir(parents=True, exist_ok=True)
    REPORT.write_text(json.dumps(report, indent=2, sort_keys=True) + "\n", encoding="utf-8")
    print(json.dumps({"terminal_status": report["terminal_status"],
                      "report": str(REPORT.resolve()),
                      "publication_sha256": fragment_sha,
                      "publication_bytes": publication_bytes,
                      "elapsed_seconds": report["elapsed_seconds"],
                      "value_graph_delta": graph.validate()["counts"],
                      "interfaces": len(fragment.interfaces),
                      "state_boundaries": report["scope"]["schema_state_boundaries"]},
                     sort_keys=True))
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
