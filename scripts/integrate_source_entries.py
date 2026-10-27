"""Admit retained frontend results through the ordinary source/code readers.

No target execution, lowering, owner restoration or program graph copying.
Ledger paths select inputs; their success flags never replace admission checks.
"""
from __future__ import annotations

import argparse
from collections import Counter
import hashlib
import json
from pathlib import Path
import resource
import time
import traceback


def read(path):
    path = Path(path).resolve()
    if path.stat().st_size > 32_000_000:
        raise ValueError("selection metadata exceeds 32 MB")
    raw = path.read_bytes()
    return json.loads(raw), {"path": str(path), "bytes": len(raw), "sha256": hashlib.sha256(raw).hexdigest()}


def main():
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--composition", required=True)
    parser.add_argument("--owner-config", required=True, help="original continuation and readonly archive declarations")
    parser.add_argument("--ledger", action="append", required=True, help="frontend ledgers in explicit oldest-to-newest order")
    parser.add_argument("--out", required=True)
    args = parser.parse_args()
    out = Path(args.out).resolve()
    out.mkdir(parents=True, exist_ok=False)
    started, phase = time.monotonic(), "selection"
    report = {"whole_program_complete": False, "target_executions": 0, "source_lowering_calls": 0}

    def save(name, value):
        with (out / name).open("x", encoding="utf-8") as stream:
            json.dump(value, stream, ensure_ascii=False, sort_keys=True, indent=2, allow_nan=False)
            stream.write("\n")

    def progress(row):
        print(json.dumps({"phase": phase, **row}, ensure_ascii=False), flush=True)

    try:
        config, config_ref = read(args.owner_config)
        selected, layers, revisions = {}, [], []
        for ledger in args.ledger:
            document, receipt = read(ledger)
            entries = document.get("retained_previous112_entries", []) + document["entries"]
            if len({row["entry_key"] for row in entries}) != len(entries):
                raise ValueError("duplicate entries within one selection ledger")
            layers.append({"receipt": receipt, "statuses": dict(Counter(row["status"] for row in entries))})
            for row in entries:
                if row["status"] != "SUCCEEDED":
                    continue
                key = row["entry_key"]
                request = {"entry_key": key, "source_program": row["program"]}
                if key in selected and selected[key] != request:
                    revisions.append({"entry_key": key, "previous": selected[key], "replacement": request})
                selected[key] = request
        if not selected:
            raise ValueError("no retained programs selected")
        requests = tuple(sorted(selected.values(), key=lambda row: (row["source_program"]["uri"], row["entry_key"])))
        save("selection.json", {"owner_config": config_ref, "layers": layers, "revisions": revisions,
                                "requests": requests, "count": len(requests)})
        phase = "normal-owners"
        progress({"selected_programs": len(requests)})
        from scar.analysis.code_witness import CodeWitnessBudget
        from scar.analysis.compiler_witness_archives import CompilerArchiveBudget, CompilerWitnessArchives
        from scar.analysis.source_attachments import SourceAttachmentBudget, SourceAttachments
        from scar.analysis.source_entry_catalog import SourceEntryCatalog
        from scar.analysis.program_composition import CompositionIndex
        from scar.analysis.source_program_publication import plan_source_entry_publication, publish_source_entries
        from scar.ir.record_codec import encode
        attachment_budget = SourceAttachmentBudget(max_report_bytes=8_000_000, max_artifact_bytes=3_000_000_000,
                                                   max_record_bytes=128_000_000, cached_files=2)
        owner = SourceAttachments(config["continuation"]["path"],
                                  expected_report_sha256=config["continuation"]["sha256"],
                                  project_root=config["project_root"], budget=attachment_budget)
        archives = CompilerWitnessArchives(tuple((row["directory"], row["manifest"]["sha256"]) for row in config["archives"]),
            store_budget=CodeWitnessBudget(max_compile_keys=256, max_source_files=256, max_source_bytes=8_000_000,
                max_module_bytes=16_000_000, max_archive_bytes=256_000_000, max_manifest_bytes=8_000_000),
            budget=CompilerArchiveBudget(max_archives=4, max_total_modules=256, max_total_sources=256,
                                        max_declared_payload_bytes=256_000_000))
        parent = CompositionIndex(args.composition, max_input_bytes=128_000_000, max_record_bytes=128_000_000)
        catalog = SourceEntryCatalog(archives=archives, admissions=(owner,), projects=(parent,),
                                     max_groups=8192, max_candidates=8192, max_selected_decode_bytes=3_000_000_000)
        phase = "ordinary-publication"
        plan = plan_source_entry_publication(parent, catalog, requests, max_programs=len(requests), publication_version=3)
        save("plan.json", plan.document)
        published = publish_source_entries(parent, catalog, requests, out / "publication", plan=plan,
            max_programs=len(requests), max_operations_per_body=10000, max_record_bytes=128_000_000, progress=progress)
        save("publication-receipt.json", published)
        phase = "ordinary-composition-reader"
        progress({"published_bodies": published["body_count"]})
        composition = CompositionIndex.from_source_entry_publication(published["manifest"],
            expected_sha256=published["sha256"], archives=archives, max_input_bytes=128_000_000,
            max_record_bytes=128_000_000, max_programs=len(requests), max_operations_per_body=10000,
            max_catalog_groups=8192, max_catalog_entries=8192, max_selected_decode_bytes=3_000_000_000,
            attachment_budget=attachment_budget)
        queries = []
        for row in composition._require_entry_publication()["checked"]:
            reference = composition.body_reference(row["entry"].reference)
            typed = composition.typed_qualified_body(reference)
            assert typed.body.graph.root == reference.identity
            assert reference.source_program.artifact.uri == row["record"]["source_program"]["uri"]
            queries.append({"reference": encode(reference), "namespace": typed.namespace,
                            "operations": len(typed.body.graph.operations),
                            "source_shape_verified": typed.source_shape_verified,
                            "source_code_verified": typed.source_code_witness_verified})
        assert len(queries) == len(requests)
        save("queries.json", {"queries": queries, "source_inputs": composition.source_inputs()})
        report.update(status="PUBLISHED_AND_QUERIED", bodies=len(queries), publication=published,
                      contexts_in_body_cache=sum(hasattr(row["program"], "semantic") for row in
                                                composition._require_entry_publication()["checked"]),
                      readonly_activity=[dict(store.counts) for store in archives._stores.values()])
    except BaseException as error:
        report.update(status="FAILED_RETAINED", phase=phase, error_type=type(error).__name__,
                      detail=str(error), traceback=traceback.format_exc())
    report.update(elapsed_s=time.monotonic() - started, max_rss_kib=resource.getrusage(resource.RUSAGE_SELF).ru_maxrss)
    save("result.json", report)
    print(json.dumps(report, ensure_ascii=False), flush=True)
    return 0 if report["status"] == "PUBLISHED_AND_QUERIED" else 1


if __name__ == "__main__":
    raise SystemExit(main())
