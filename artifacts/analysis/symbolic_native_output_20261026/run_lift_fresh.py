#!/usr/bin/env python
"""Create and query one symbolic payload projection for an existing lift_fresh output."""
from __future__ import annotations

import argparse
from copy import deepcopy
from dataclasses import replace
from hashlib import sha256
import json
from pathlib import Path
import sys
from time import perf_counter


REPO = Path(__file__).resolve().parents[3]
sys.path.insert(0, str(REPO))

from scar.ir.execution.codec import loads as execution_loads
from scar.ir.execution.ids import ValueOccurrenceID
from scar.ir.program.codec import SCHEMA as PROGRAM_SCHEMA, loads as program_loads
from scar.ir.program.providers import ProviderArtifact
from scar.ir.record_codec import decode, loads as strict_loads
from scar.ir.v2.codec import values_from_dict
from scar.ir.v2.common import EvidenceClaim
from scar.ir.v2.evidence import (
    EvidenceEdge, EvidenceEndpoint, EvidenceNodeKind, EvidenceRelation,
    OperationInstance, ProviderReference,
)
from scar.ir.v2.ids import OperationInstanceID
from scar.store.bundle_partitions import BundlePartitions
from scar.trace.native_port_sidecar import (
    query_native_ports, read_native_port_index,
)
from scar.ir.execution.symbolic_native_output import (
    _validate_projection_delta,
    build_symbolic_native_output, merge_symbolic_native_output,
    query_symbolic_native_output, write_symbolic_native_output,
)


MAIN = REPO.parent / "structured-program-model"
ATTEMPT = MAIN / "artifacts/experiments/native_inputs_full_20261026/attempt05/native-input-connections"
BUNDLE = MAIN / "artifacts/experiments/native_inputs_full_20261026/native-import/native/bundle-partitions"
PORT_PUBLICATION = REPO / "artifacts/analysis/native_port_sidecar_full_20261026/publication"
OUTPUT_OCCURRENCE = ValueOccurrenceID(
    "native-port:capture:ca66b69a8cfc3c1b88e0c22e8ec00d58d735fd016d16edf85e8cf0ac51eb5fc3:4:outputs:0")
INSTANCE_ID = "native:636fde61a45803f11712767bc1cbf0b0ea3de13b14e0b27edc2d6071daea1612:eto:25"
PROVIDER_REFERENCE_ID = "native:636fde61a45803f11712767bc1cbf0b0ea3de13b14e0b27edc2d6071daea1612:tensor-token:19"
DESCRIPTOR_ID = "d38d15147c00358219c47ec3f7319db1bbd99b1ef205d55879f3096122dbcbd6"


def artifact(path: Path, schema: str) -> tuple[ProviderArtifact, bytes]:
    payload = path.read_bytes()
    return ProviderArtifact(str(path.resolve()), sha256(payload).hexdigest(), len(payload), schema), payload


def find_provider(partitions: BundlePartitions, reference_id: str) -> ProviderReference:
    for envelope in partitions.iter_records("evidence", "provider_references"):
        record = envelope["record"]
        if record.get("reference_id") == reference_id:
            return decode(ProviderReference, record)
    raise KeyError(f"original ProviderReference is missing: {reference_id}")


def find_exact_edge(partitions: BundlePartitions, instance_id: str,
                    provider_reference_id: str, locator: str) -> EvidenceEdge:
    for envelope in partitions.iter_records("evidence", "edges"):
        record = envelope["record"]
        if type(record) is not dict:
            continue
        source, target = record.get("source"), record.get("target")
        evidence = record.get("evidence")
        refs = evidence.get("references", ()) if type(evidence) is dict else ()
        source_ref = source.get("reference") if type(source) is dict else None
        if (type(source_ref) is not dict or type(target) is not dict
                or source_ref.get("wire") != OperationInstanceID(instance_id).wire
                or source.get("kind") != "operation_instance"
                or target.get("kind") != "provider_reference"
                or target.get("reference") != provider_reference_id
                or record.get("relation") != "output_reference"
                or locator not in refs):
            continue
        edge = EvidenceEdge(
            record["edge_id"], EvidenceRelation(record["relation"]),
            EvidenceEndpoint(EvidenceNodeKind.OPERATION_INSTANCE,
                             decode(OperationInstanceID, source["reference"])),
            EvidenceEndpoint(EvidenceNodeKind.PROVIDER_REFERENCE,
                             target["reference"]),
            decode(EvidenceClaim, evidence))
        if edge.as_dict() != record:
            raise ValueError("original EvidenceEdge differs from its typed decoded record")
        return edge
    raise KeyError("exact original OUTPUT_REFERENCE edge was not found")


def expect_rejection(label: str, action) -> str:
    try:
        action()
    except (TypeError, ValueError):
        return label
    raise ValueError(f"validator accepted a forbidden projection mutation: {label}")


def expect_no_overwrite(path: Path, projection, delta) -> str:
    if not path.is_file():
        raise ValueError("expected prior successful publication is missing")
    try:
        write_symbolic_native_output(path, projection, delta)
    except FileExistsError:
        return "writer_refuses_overwrite"
    raise ValueError("writer replaced a prior symbolic output publication")


def main() -> int:
    parser = argparse.ArgumentParser()
    parser.add_argument("--output", type=Path, required=True,
                        help="fresh destination for the tiny projection publication")
    args = parser.parse_args()
    started = perf_counter()

    program_path = ATTEMPT / "program.json"
    execution_path = ATTEMPT / "shards/000000/execution.json"
    evidence_path = ATTEMPT / "shards/000000/source-evidence.json"
    values_path = ATTEMPT / "shards/000000/source-values.json"
    index_path = PORT_PUBLICATION / "index.json"
    previous_publication = Path(__file__).resolve().parent / "publication/lift_fresh_output.json"
    protected_paths = (program_path, execution_path, evidence_path, values_path, index_path,
                       previous_publication)
    before = {str(path): sha256(path.read_bytes()).hexdigest() for path in protected_paths}

    program = program_loads(program_path.read_text(encoding="utf-8"))
    execution = execution_loads(execution_path.read_text(encoding="utf-8"))
    values = values_from_dict(strict_loads(values_path.read_bytes()))
    program_artifact, _ = artifact(program_path, PROGRAM_SCHEMA)
    if program_artifact != execution.snapshot.artifact:
        raise ValueError("loaded ProgramGraph bytes differ from the existing ProgramSnapshot artifact")
    partitions = BundlePartitions(BUNDLE)
    index_artifact, _ = artifact(index_path, "scar.native-boxed-port-index")
    index = read_native_port_index(index_path, expected_sha256=index_artifact.sha256)
    evidence_artifact, _ = artifact(evidence_path, "scar.ir.v2.evidence")
    execution_artifact, _ = artifact(execution_path, "scar.execution-model")

    denotation = next(item for item in execution.denotations
                      if item.value == OUTPUT_OCCURRENCE)
    base_value_artifact = denotation.identity.object.artifact
    if Path(base_value_artifact.uri).resolve() != values_path.resolve():
        raise ValueError("output denotation no longer points at the retained source ValueGraph")
    value_artifact, _ = artifact(values_path, "scar.ir.v2.values")
    if value_artifact != base_value_artifact:
        raise ValueError("retained source ValueGraph bytes differ from original denotation artifact")

    ordinal = 18
    instance_records = partitions.selected_records("evidence", "instances", (ordinal,))
    if len(instance_records) != 1:
        raise ValueError("original ETO instance ordinal 18 is absent")
    native_instance = decode(OperationInstance, instance_records[0]["record"])
    if native_instance.id.value != INSTANCE_ID:
        raise ValueError("original ETO ordinal 18 no longer identifies the lift_fresh instance")
    ports = query_native_ports(native_instance, PORT_PUBLICATION, BUNDLE,
                               expected_index_sha256=index_artifact.sha256)
    output_ports = [port for port in ports.ports
                    if port.direction == "output" and port.path == (0,)
                    and port.provider_reference == PROVIDER_REFERENCE_ID
                    and port.descriptor_id == DESCRIPTOR_ID]
    if len(output_ports) != 1:
        raise ValueError("ETO node 18 does not have exactly one expected Tensor output port")
    port = output_ports[0]
    provider = find_provider(partitions, PROVIDER_REFERENCE_ID)
    edge_pointer = (f"sha256:{index.source_sha256}#/nodes/{ordinal}{port.source_locator}")
    edge = find_exact_edge(partitions, INSTANCE_ID, PROVIDER_REFERENCE_ID, edge_pointer)

    projection, delta = build_symbolic_native_output(
        program, execution, execution_artifact, OUTPUT_OCCURRENCE,
        index, index_artifact, ports, native_instance, port, provider, edge,
        evidence_artifact, base_value_artifact, values)

    def add_object_to_delta():
        forged = deepcopy(delta)
        forged.add_object(next(iter(values.objects.values())))
        _validate_projection_delta(projection, forged)

    def forge_logical_status():
        forged = deepcopy(delta)
        forged.logical_values[projection.symbolic_value].metadata["evidence_status"] = "Observed"
        _validate_projection_delta(projection, forged)

    def forge_provenance_status():
        forged = deepcopy(delta)
        forged.provenance[projection.symbolic_provenance].evidence = "Observed"
        _validate_projection_delta(projection, forged)

    def forge_parent_version():
        forged = deepcopy(delta)
        forged.versions[projection.symbolic_version].parent_versions = (projection.symbolic_version,)
        _validate_projection_delta(projection, forged)

    def forge_symbol_id():
        forged_projection = replace(
            projection, projection_id="native-output-symbol:" + "0" * 64)
        _validate_projection_delta(forged_projection, delta)

    validator_rejections = [
        expect_rejection("extra_object_record", add_object_to_delta),
        expect_rejection("logical_evidence_status_observed", forge_logical_status),
        expect_rejection("provenance_evidence_observed", forge_provenance_status),
        expect_rejection("nonempty_parent_versions", forge_parent_version),
        expect_rejection("recomputed_symbol_id", forge_symbol_id),
    ]
    validator_rejections.append(expect_no_overwrite(previous_publication, projection, delta))
    publication_sha = write_symbolic_native_output(args.output, projection, delta)

    loaded_projection, loaded_delta = query_symbolic_native_output(
        args.output, OUTPUT_OCCURRENCE, expected_sha256=publication_sha)
    merged = merge_symbolic_native_output(values, loaded_delta)
    if (loaded_projection != projection
            or loaded_projection.symbolic_value not in merged.logical_values
            or loaded_projection.symbolic_version not in merged.versions
            or loaded_projection.symbolic_provenance not in merged.provenance
            or loaded_projection.symbolic_materialization not in merged.materializations):
        raise ValueError("normal codec query/ValueGraph merge did not return the projected symbol")
    after = {str(path): sha256(path.read_bytes()).hexdigest() for path in protected_paths}
    if before != after:
        raise ValueError("one or more original source artifacts changed during projection")

    report = {
        "schema": "scar.analysis.symbolic-native-output-run",
        "schema_version": 1,
        "status": "completed",
        "elapsed_seconds": round(perf_counter() - started, 3),
        "sample": "aten::lift_fresh(Tensor(a) self) -> Tensor(a)",
        "output_occurrence": str(loaded_projection.output_occurrence),
        "program_value": loaded_projection.program_value.wire,
        "program_value_kind": type(next(v for v in program.values
                                         if v.id == loaded_projection.program_value)).__name__,
        "original_denotation": loaded_projection.original_denotation.wire,
        "original_denotation_identity": type(denotation.identity).__name__,
        "native_output": {
            "boundary": loaded_projection.native_output.boundary.wire,
            "operation_occurrence": loaded_projection.native_output.operation.wire,
            "position": loaded_projection.native_output.position,
        },
        "native_port": {
            "operation_instance": loaded_projection.native_port.instance.wire,
            "source_ordinal": loaded_projection.native_port.source_ordinal,
            "direction": "output",
            "path": list(loaded_projection.native_port.path),
            "source_locator": loaded_projection.native_port.source_fact.locator,
            "formal_slot": loaded_projection.native_port.formal_slot.wire,
            "provider_reference": loaded_projection.native_port.provider_reference,
            "descriptor_id": loaded_projection.native_port.descriptor_id,
        },
        "original_edge": {
            "id": loaded_projection.original_edge.edge,
            "artifact_sha256": loaded_projection.original_edge.artifact.sha256,
            "relation": "output_reference",
        },
        "projection": {
            "id": loaded_projection.projection_id,
            "status": loaded_projection.status.value,
            "logical_value": loaded_projection.symbolic_value.wire,
            "version": loaded_projection.symbolic_version.wire,
            "provenance": loaded_projection.symbolic_provenance.wire,
            "materialization": loaded_projection.symbolic_materialization.wire,
            "representation": loaded_delta.materializations[
                loaded_projection.symbolic_materialization].representation,
            "device": loaded_delta.materializations[
                loaded_projection.symbolic_materialization].device,
            "region": None,
            "identity_semantics": loaded_projection.identity_semantics,
            "unknowns": list(loaded_projection.unknowns),
        },
        "value_graph_delta_counts": loaded_delta.validate()["counts"],
        "merged_value_graph_counts": merged.validate()["counts"],
        "validator_rejections": validator_rejections,
        "publication": {
            "path": str(args.output.resolve()),
            "sha256": publication_sha,
            "bytes": args.output.stat().st_size,
        },
        "original_artifacts_unchanged": before,
    }
    print(json.dumps(report, sort_keys=True, indent=2))
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
