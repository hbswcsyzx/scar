#!/usr/bin/env python3
"""Rebuild one validated source body and join retained stream calls to its ports.

This artifact runner reads existing capture/source inputs only. It does not
execute the target or write a source inventory/publication.
"""
from __future__ import annotations

import argparse
import gzip
import hashlib
import json
from pathlib import Path
import sys
import time


def _json(path):
    path = Path(path)
    raw = path.read_bytes()
    if path.suffix == ".gz":
        raw = gzip.decompress(raw)
    return json.loads(raw), raw


def _sha(path):
    digest = hashlib.sha256()
    with Path(path).open("rb") as stream:
        while chunk := stream.read(1 << 20):
            digest.update(chunk)
    return digest.hexdigest()


def _parse_args(argv, capability_values):
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--capture", required=True, type=Path,
                        help="existing capture directory containing trace/")
    parser.add_argument("--source", type=Path,
                        help="optional exact source path; otherwise derived from CodeWitness")
    parser.add_argument("--inventory", required=True, type=Path,
                        help="typed monolithic scar.program-inventory JSON/JSON.GZ")
    parser.add_argument("--composition", required=True, type=Path,
                        help="existing CompositionIndex index.json.gz")
    parser.add_argument("--code-store", required=True, type=Path,
                        help="existing read-only CodeWitnessStore directory")
    parser.add_argument("--stream-metadata", type=Path,
                        help="stream-interface-meta JSON; defaults to the single trace metadata file")
    parser.add_argument("--capability", action="append", choices=capability_values, default=[],
                        help="additional SourceLanguageCapability value; repeat as needed")
    parser.add_argument("--max-operations", type=int, default=10000)
    parser.add_argument("--inventory-max-files", type=int, default=128)
    parser.add_argument("--inventory-max-bytes", type=int, default=8_000_000)
    parser.add_argument("--output", required=True, type=Path,
                        help="new JSON result path; existing files are refused")
    return parser.parse_args(argv)


def main(argv=None):
    # The source capabilities are now part of the normal package. Derive the
    # repository root so this runner works from any current working directory.
    repo_root = Path(__file__).resolve().parents[3]
    sys.path.insert(0, str(repo_root))

    from scar.analysis.call_operand_reader import read_call_operands
    from scar.analysis.code_witness import CodeWitnessStore
    from scar.analysis.program_composition import CompositionIndex
    from scar.analysis.program_inventory import ProgramInventory
    from scar.analysis.program_lowering import lower_source
    from scar.analysis.source_language import SourceCodeEvidence, SourceLanguageOptions
    from scar.analysis.source_stream_interfaces import read_source_stream_interfaces
    from scar.ir.program.call_edges import CapturedSite
    from scar.ir.program.functions import BodyLoweringProfile
    from scar.ir.program.source_language import SourceLanguageCapability
    from scar.ir.record_codec import decode
    from scar.trace.stream_interfaces import read_stream_interfaces

    args = _parse_args(argv, [row.value for row in SourceLanguageCapability])
    started = time.perf_counter()
    capture = args.capture.resolve()
    trace_dir = (capture / "trace").resolve()
    inventory_path = args.inventory.resolve()
    composition_path = args.composition.resolve()
    code_store_path = args.code_store.resolve()
    inventory_document, inventory_raw = _json(inventory_path)
    source_model = ProgramInventory.from_dict(inventory_document,
        max_files=args.inventory_max_files, max_bytes=args.inventory_max_bytes)
    project_root = Path(source_model.discovery.project_root).resolve()
    trace = read_call_operands(trace_dir, project_root)

    metadata_path = args.stream_metadata.resolve() if args.stream_metadata else None
    if metadata_path is None:
        candidates = sorted(trace_dir.glob("stream-interface-meta.*.json"))
        if len(candidates) != 1:
            raise ValueError("specify --stream-metadata unless trace has exactly one stream metadata file")
        metadata_path = candidates[0]
    metadata_sha = _sha(metadata_path)
    observed = read_stream_interfaces(metadata_path, expected_sha256=metadata_sha)
    code_keys = {decode(CapturedSite, row["site"]).code for row in observed["calls"]}
    if len(code_keys) != 1:
        raise ValueError("this runner needs one caller code descriptor per source-body join")
    code_key = next(iter(code_keys))
    descriptors = [row.code for row in trace.frame_scan.captures if row.code.key == code_key]
    if not descriptors or any(row != descriptors[0] for row in descriptors):
        raise ValueError("current trace has no consistent complete caller descriptor for stream rows")

    composition = CompositionIndex(composition_path)
    code_store = CodeWitnessStore(code_store_path)
    evidence = SourceCodeEvidence(code_store, composition, descriptors[0])
    definitions = [(file, definition) for file in source_model.files
                   for definition in file.definitions
                   if definition.id == evidence.source_link.definition]
    if len(definitions) != 1:
        raise ValueError("CodeWitness definition does not resolve to one original inventory definition")
    original_file, definition = definitions[0]
    evidence.require_definition(original_file.snapshot, definition.id, definition.source)
    source_path = Path(evidence.source_link.snapshot.path).resolve()
    if args.source is not None and args.source.resolve() != source_path:
        raise ValueError("--source differs from the exact CodeWitness source path")
    requested_capabilities = tuple(SourceLanguageCapability(value) for value in args.capability)
    capabilities = tuple(dict.fromkeys((*SourceLanguageOptions().capabilities, *requested_capabilities)))
    options = SourceLanguageOptions(capabilities, evidence)
    source_program = lower_source(source_path, definition.name, max_operations=args.max_operations,
        profile=BodyLoweringProfile.STRUCTURED_ENV, language_options=options, project_root=project_root)

    view = read_source_stream_interfaces(trace=trace, source_model=source_model,
        metadata=metadata_path, expected_sha256=metadata_sha,
        source_program=source_program, language_options=options)
    calls = []
    for call in view.calls:
        ports = call.ports
        calls.append({
            "attempt": call.attempt.index,
            "method": call.resource.contract.method,
            "observed_completion": call.observed_completion,
            "source_span": ([call.source.start_line, call.source.end_line,
                             call.source.start_column, call.source.end_column]
                            if call.source is not None else None),
            "source_call_id": call.call_site.call.wire if call.call_site.call else None,
            "source_body_origin": ports.body_origin.value if ports else None,
            "source_body_operation_id": ports.operation.wire if ports else None,
            "callee_use_id": ports.callee_use.wire if ports else None,
            "actual_use_ids": [item.wire for item in ports.actual_uses] if ports else None,
            "world_use_id": ports.world_use.wire if ports else None,
            "source_completion_edges": [item.kind.value for item in ports.completions] if ports else None,
            "issues": list(call.issues),
        })
    status_counts = {status.value: sum(call.status is status for call in view.calls)
                     for status in type(view.calls[0].status)} if view.calls else {}
    status = ("PASS" if view.calls and all(call.ports is not None for call in view.calls)
              else "COMPLETED_WITH_BOUNDARIES")
    result = {
        "schema": "scar.source-stream-interface-terminal", "schema_version": 1,
        "status": status, "actual": True,
        "elapsed_seconds": time.perf_counter() - started,
        "inputs": {
            "capture_trace": str(trace_dir), "stream_metadata": str(metadata_path),
            "stream_metadata_sha256": metadata_sha,
            "source": str(source_path), "source_sha256": source_program.metadata.source.fingerprint.removeprefix("sha256:"),
            "inventory": {"path": str(inventory_path), "sha256": hashlib.sha256(inventory_raw).hexdigest()},
            "composition": str(composition_path), "code_store": str(code_store_path),
        },
        "source_program": {
            "profile": source_program.profile.value,
            "capabilities": [item.value for item in capabilities],
            "operations": len(source_program.graph.operations) if source_program.graph else 0,
            "gaps": len(source_program.metadata.gaps),
            "original_definition_id": definition.id.wire,
            "source_replay_validation": "PASS",
            "runtime_code_instance_established": False,
        },
        "original_inventory_body": {
            "status": next(body.status.value for body in original_file.bodies
                            if body.definition == definition.id),
            "graph_replaced": False,
        },
        "summary": {
            "calls": len(view.calls),
            "observed_completions": {kind: sum(call.observed_completion == kind for call in view.calls)
                                      for kind in ("C_RETURN", "C_RAISE", "UNOBSERVED")},
            "statuses": status_counts,
            "source_replay_local_ports": sum(call.ports is not None
                and call.ports.body_origin.value == "SOURCE_REPLAY_LOCAL_BODY" for call in view.calls),
        },
        "nonclaims": {
            "runtime_actual_formal_binding": False,
            "receiver_bound_to_source_value_or_resource": False,
            "stream_effects_complete": False,
            "observed_outcome_selects_source_completion": False,
            "bytes_or_readiness_proved": False,
            "runtime_code_object_identity_established": False,
        },
        "calls_detail": calls,
    }
    output = args.output.resolve()
    output.parent.mkdir(parents=True, exist_ok=True)
    with output.open("x", encoding="utf-8") as stream:
        json.dump(result, stream, sort_keys=True, indent=2)
        stream.write("\n")
    print(json.dumps({"status": status, "output": str(output), "summary": result["summary"],
                      "elapsed_seconds": result["elapsed_seconds"]}, sort_keys=True))
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
