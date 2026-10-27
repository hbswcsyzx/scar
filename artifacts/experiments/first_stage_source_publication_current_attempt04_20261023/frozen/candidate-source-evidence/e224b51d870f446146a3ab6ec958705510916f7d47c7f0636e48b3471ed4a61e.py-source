"""Admit archived source-language bodies into an immutable partition snapshot.

CP2 records contain fixed locators into existing SourceProgram5 artifacts. They
do not copy graphs, replay lowering, or turn historical calls into this Run.
"""
from __future__ import annotations

import ast
from collections import Counter
from copy import deepcopy
from hashlib import sha256
import json
from pathlib import Path
import tempfile
import time
import tokenize

from scar.analysis.inventory_partitions import InventoryPartitions, _read_receipt, _write_shard
from scar.analysis.program_composition import CompositionIndex
from scar.analysis.program_lowering import SourceProgram, _symbol_tables
from scar.analysis.source_language import SourceCodeEvidence, SourceLanguageOptions
from scar.analysis.structured_lowering import require_valid_structured_body
from scar.ir.program.call_edges import CapturedCode, CodeCapture, CodeSourceLink
from scar.ir.program.call_demand import CallSourceScope
from scar.ir.program.inventory import BodyInventory, BodyStatus, DefinitionInventory
from scar.ir.program.functions import FunctionSignature
from scar.ir.record_codec import decode, encode


def _need(condition, message):
    if not condition:
        raise ValueError("source publication: " + message)


def _canonical(document):
    return json.dumps(document, sort_keys=True, ensure_ascii=False,
                      separators=(",", ":"), allow_nan=False).encode()


def _input_ref(path, receipt, representation):
    return {"uri": str(Path(path).resolve()), "external": True,
            "representation": representation, **receipt}


def _module_receipts():
    names = ("source_program_publication.py", "inventory_partitions.py", "program_composition.py",
             "source_language.py", "call_demand.py")
    return [{"path": str(Path(__file__).with_name(name)),
             "sha256": sha256(Path(__file__).with_name(name).read_bytes()).hexdigest()}
            for name in names]


def publish_source_programs(base_composition, source_program_paths, out_dir, *, code_witnesses,
                            max_programs=128, max_changed_sources=64, max_operations_per_body=10000,
                            max_record_bytes=128_000_000, progress=None):
    """Publish checked existing bodies; never prepare, compile or execute source.

    Defaults are general tool ceilings. A gate can independently narrow them.
    The published construction cost is UNKNOWN: graph size is a different fact.
    """
    from scar.analysis.code_witness import CodeWitnessStore
    from scar.analysis.call_demand import derive_call_source_admission
    from scar.analysis.function_interfaces import validate_body_interface
    _need(type(base_composition) is CompositionIndex and base_composition.partitioned,
          "an original regular partitioned CompositionIndex is required")
    _need(type(code_witnesses) is CodeWitnessStore and not code_witnesses.writable
          and not code_witnesses.compile_missing, "CodeWitnessStore must be explicit, owned and read-only")
    _need(type(source_program_paths) is tuple and 0 < len(source_program_paths) <= max_programs,
          "source program input count exceeds the independent publication budget")
    _need(all(type(value) is int and value > 0 for value in
              (max_programs, max_changed_sources, max_operations_per_body, max_record_bytes)), "invalid publication ceiling")
    _need(progress is None or callable(progress), "invalid progress callback")
    out_dir = Path(out_dir).resolve()
    _need(not out_dir.exists(), "output already exists")
    out_dir.parent.mkdir(parents=True, exist_ok=True)
    started = time.perf_counter()
    original_modules = _module_receipts()
    base = base_composition.inventory
    _need(type(base) is InventoryPartitions, "publication requires the canonical partition reader")
    origin = base_composition.original_code_source_origin()
    interfaces = base_composition.inventory_component("interfaces")
    source_model = base_composition.inventory_component("call_sources")["model"]
    scope_raw = base_composition.inventory_component("call_source_scope")
    scope = decode(CallSourceScope, scope_raw)
    source_links = {row.code: row for row in (decode(CodeSourceLink, row) for row in source_model["code_links"])}
    captures = {}
    for raw in source_model["codes"]:
        row = decode(CodeCapture, raw)
        _need(row.code.key not in captures or captures[row.code.key] == row.code, "conflicting original code descriptors")
        captures[row.code.key] = row.code
    changed, inputs, texts = {}, [], {}
    for path in source_program_paths:
        document, receipt = _read_receipt(path, limit=max_record_bytes)
        program = SourceProgram.read_structure(document, max_operations=max_operations_per_body)
        _need(program.language is not None and program.graph is not None and program.interface is not None,
              "only a recovered SourceProgram5 language body can be admitted")
        _need(len(program.graph.operations) <= max_operations_per_body, "body graph exceeds independent operation ceiling")
        files = [row for row in base_composition.document["files"]
                 if row["snapshot"] == encode(program.metadata.source)
                 and (row.get("context") or {}).get("namespace_root") == program.language.namespace_root]
        _need(len(files) == 1, "source snapshot/namespace has no unique original file")
        file_index = files[0]["file_index"]
        bodies = [(i, row) for i, row in enumerate(files[0]["bodies"])
                  if row["definition"] == program.interface.definition.wire]
        _need(len(bodies) == 1 and bodies[0][1]["root"] is None, "body is ambiguous or already has a canonical graph")
        body_index = bodies[0][0]
        key = file_index, body_index
        _need(key not in changed, "duplicate source-qualified body admission")
        _need(len({item[0] for item in changed} | {file_index}) <= max_changed_sources, "changed source-file ceiling exceeded")
        raw_file = base_composition.inventory_file(file_index)
        view = base_composition.source(file_index)
        _need(encode(view.snapshot) == raw_file["snapshot"] and encode(view.context) == raw_file["context"],
              "original file/source archive snapshot or context differs")
        digests = [sha256(_canonical(document[name])).hexdigest() for name in ("semantic", "semantics", "control")]
        _need(digests == [raw_file["context"][name] for name in
                          ("semantic_sha256", "semantics_sha256", "control_sha256")],
              "SourceProgram5 source graphs differ from the exact original context")
        declarations = decode(tuple[DefinitionInventory, ...], raw_file["definitions"])
        definitions = [row for row in declarations if row.id == program.interface.definition
                       and row.source == program.structured.source]
        _need(len(definitions) == 1, "body needs one exact original definition/source")
        _need(type(program.language.code_evidence) is dict and "captured" in program.language.code_evidence,
              "body has no independently replayable complete code witness")
        captured = decode(CapturedCode, program.language.code_evidence["captured"])
        _need(captures.get(captured.key) == captured, "body code descriptor differs from the original source producer")
        evidence = SourceCodeEvidence(code_witnesses, base_composition, captured)
        options = SourceLanguageOptions(program.language.capabilities, evidence)
        source_key = program.metadata.source.path, program.metadata.source.fingerprint
        if source_key not in texts:
            with tokenize.open(source_key[0]) as stream:
                text = stream.read()
            _need("sha256:" + sha256(text.encode()).hexdigest() == source_key[1], "current exact source drifted")
            texts[source_key] = (ast.parse(text, filename=source_key[0]), _symbol_tables(text, source_key[0]))
        require_valid_structured_body(program.structured, program.graph, program.interface, program.metadata,
            semantic=program.semantic, control=program.control, language=program.language,
            source_tree=texts[source_key][0], language_options=options)
        reason = "; ".join(dict.fromkeys(row.detail for row in program.metadata.gaps))
        body = BodyInventory(program.interface.definition, BodyStatus.LOWERED_WITH_GAPS,
                             program.graph, program.metadata, reason, None)
        signatures = [decode(FunctionSignature, row) for row in interfaces["signatures"]
            if row["definition"] == encode(body.definition) and row["source"] == encode(definitions[0].source)]
        _need(len(signatures) == 1, "new interface has no unique original signature")
        validate_body_interface(body, program.interface, signatures[0])
        ref = _input_ref(path, receipt, "scar.source-program/5")
        changed[key] = {"program": program, "body": body, "input": ref,
            "original": deepcopy(raw_file["bodies"][body_index]), "file": raw_file,
            "definitions": declarations, "captured": captured,
            "previous_body": base_composition.inventory_body_locators(file_index, body_index)}
        inputs.append(ref)
        if progress is not None:
            progress({"stage": "admit_source_program", "file_index": file_index,
                      "body_index": body_index, "definition": body.definition.wire})
    # The common rule receives canonical, publicly checked BodyInventory, not
    # a caller-supplied success flag or bare root. Every other origin is kept.
    admissions = []
    admission_changes = []
    for index, admission in enumerate(scope.admissions):
        link = source_links.get(admission.origin.code)
        matching = [item for item in changed.values() if link is not None
                    and item["body"].definition == link.definition and item["body"].metadata.source == link.snapshot]
        _need(len(matching) <= 1, "one static origin matches multiple published bodies")
        if not matching:
            admissions.append(admission)
            continue
        item, = matching
        _need(captures.get(admission.origin.code) == item["captured"],
              "source body compiler descriptor is inapplicable to this original origin")
        updated = derive_call_source_admission(admission.origin, link,
            source_snapshot=item["body"].metadata.source, indexed_definitions=item["definitions"], body=item["body"])
        admissions.append(updated)
        if updated != admission:
            admission_changes.append({"index": index, "before": encode(admission), "after": encode(updated)})
    temporary = Path(tempfile.mkdtemp(prefix=".scar-publication-", dir=out_dir.parent))
    try:
        files = [base.external_reference(ref) for ref in base.manifest["files"]]
        components = {name: base.external_reference(ref) for name, ref in base.manifest["components"].items()}
        new_refs, replacements = [], []
        for serial, ((fi, bi), item) in enumerate(sorted(changed.items())):
            program = item["program"]
            identity = {"definition": encode(program.interface.definition), "source": encode(program.structured.source),
                        "entry": program.metadata.entry}
            cp = {"schema": "scar.body-construction-checkpoint", "schema_version": 2,
                "origin": "SOURCE_PROGRAM5_ADMISSION", "source_program": item["input"],
                "body_identity": identity, "context": item["file"]["context"],
                "profile": program.profile.value, "language": "#/language",
                "fields": {name: "#/" + name for name in ("graph", "metadata", "interface", "frame", "structured", "language")},
                "construction_operations": None, "construction_cost_known": False,
                "previous_body": item["previous_body"],
                "verification": {"public_structure_validated": True, "independent_source_and_code_witness_verified": True,
                    "source_replay_performed": False, "runtime_code_instance_established": False,
                    "effects_established": False}, "whole_program_established": False}
            ref = _write_shard(temporary, f"bodies/{serial:05d}.json.gz", cp, limit=max_record_bytes)
            # Body references remain valid when a later snapshot inherits this
            # source shard without rewriting it under another archive root.
            ref = {**ref, "uri": str(out_dir / ref["uri"]), "external": True}
            ref["body_identity"] = identity
            new_refs.append(ref)
            item["checkpoint"] = ref
            replacements.append({"file_index": fi, "body_index": bi, "snapshot": encode(program.metadata.source),
                "definition": encode(program.interface.definition), "source": encode(program.structured.source),
                "previous_body": item["previous_body"], "checkpoint": ref, "source_program": item["input"]})
        for fi in sorted({key[0] for key in changed}):
            file = deepcopy(next(item["file"] for key, item in changed.items() if key[0] == fi))
            for (owner, bi), item in changed.items():
                if owner == fi:
                    file["bodies"][bi] = {"definition": encode(item["body"].definition), "status": "LOWERED_WITH_GAPS",
                        "reason": item["body"].reason, "construction_operations": None,
                        "checkpoint": item["checkpoint"], "metadata_without_checkpoint": None}
            files[fi] = _write_shard(temporary, f"sources/{fi:05d}.json.gz",
                {"schema": "scar.partitioned-file-inventory", "schema_version": 2, "file_index": fi, "file": file},
                limit=max_record_bytes)

        def component(name, value):
            components[name] = _write_shard(temporary, f"components/{name}.json.gz",
                {"schema": "scar.inventory-component", "schema_version": 1, "name": name, "value": value},
                limit=max_record_bytes)

        updated_interfaces = deepcopy(interfaces)
        updated_interfaces["bodies"] = [base.external_reference(ref) for ref in interfaces["bodies"]]
        updated_interfaces["bodies"].extend(new_refs)
        component("interfaces", updated_interfaces)
        component("structured", [base.external_reference(ref) for ref in
                                  base_composition.inventory_component("structured")] + new_refs)
        component("call_source_scope", encode(CallSourceScope(tuple(admissions))))
        old_header = base_composition.inventory_component("header")
        summary = deepcopy(old_header["summary"])
        known = summary.get("known_construction_operations", summary["construction_operations"])
        unknown = summary.get("unknown_construction_cost_bodies", 0)
        for item in changed.values():
            old, program = item["original"], item["program"]
            summary["body_statuses"][old["status"]] -= 1
            summary["body_statuses"]["LOWERED_WITH_GAPS"] += 1
            summary["core_operations"] += len(program.graph.operations)
            summary["core_values"] += len(program.graph.values)
            if old["construction_operations"] is not None:
                known -= old["construction_operations"]
                unknown += 1
            summary["interfaces"]["bound_bodies"] += 1
            summary["structured"]["bodies"] += 1
            summary["structured"]["protocols"] += len(program.structured.protocols)
            summary["structured"]["loops"] += len(program.structured.loops)
        summary["construction_operations"] = None
        summary["known_construction_operations"] = known
        summary["unknown_construction_cost_bodies"] = unknown
        summary["call_source_scope"] = dict(sorted(Counter(row.status.value for row in admissions).items()))
        component("header", {"schema": "scar.partitioned-inventory-header", "schema_version": 2,
            "profile": "STRUCTURED_ENV_V1", "capabilities": ["SOURCE_PROGRAM5_ADMISSION_V1"],
            "base_header": base.external_reference(base.manifest["components"]["header"]),
            "base_analysis_budget": old_header.get("budget", old_header.get("base_analysis_budget")),
            "publication_budget": {"max_programs": max_programs, "max_changed_sources": max_changed_sources,
                                   "max_operations_per_body": max_operations_per_body, "max_record_bytes": max_record_bytes},
            "summary": summary, "target_executed": False, "transformation_authorized": False})
        publication = {"schema": "scar.source-program-publication", "schema_version": 1,
            "base_inventory": deepcopy(base_composition.document["inventory"]),
            "base_composition": deepcopy(base_composition.index_receipt),
            "base_composition_canonical_sha256": base_composition._original_document_sha256,
            "code_source_origin": origin, "changed_bodies": replacements,
            "changed_files": sorted({key[0] for key in changed}), "source_programs": inputs,
            "admission_changes": admission_changes,
            "measurements": {"elapsed_s": time.perf_counter() - started, "source_files_parsed": len(texts),
                "source_prepare_attempts": 0, "compile_attempts": 0,
                "published_graph_operations": sum(len(item["program"].graph.operations) for item in changed.values()),
                "original_construction_cost_known": False},
            "producer": {"modules": original_modules, "code_witness_store": code_witnesses.receipt()},
            "whole_program_established": False, "current_run_integrated": False, "transformation_authorized": False}
        component("publication", publication)
        component("producer", {"kind": "SOURCE_PROGRAM5_ADMISSION", "modules": original_modules,
            "base_producer": base.external_reference(base.manifest["components"]["producer"])})
        component("inputs", {"base_inventory": deepcopy(base_composition.document["inventory"]),
            "base_inputs": base.external_reference(base.manifest["components"]["inputs"]), "source_programs": inputs})
        counts = deepcopy(base.manifest["counts"])
        counts["graph_bodies"] += len(changed)
        counts["checkpoint_returns"] += sum(item["original"]["checkpoint"] is None for item in changed.values())
        counts["not_attempted_bodies"] -= sum(item["original"]["status"] == "NOT_ATTEMPTED" for item in changed.values())
        manifest = {"schema": "scar.partitioned-program-inventory", "schema_version": 2,
            "capabilities": ["SOURCE_PROGRAM5_ADMISSION_V1"],
            "storage": "immutable original artifacts and source-program admission references",
            "identity": "actual artifact/representation/record pointer/body/kind/local_id",
            "parent_inventory": _input_ref(base.path, base.manifest_receipt,
                "scar.partitioned-program-inventory/" + str(base.version)),
            "files": files, "components": components, "counts": counts,
            "public_source_replay_performed": False, "fresh_body_lowering_performed": False,
            "whole_program_graph_established": False, "transformation_authorized": False}
        (temporary / "manifest.json").write_text(json.dumps(manifest, sort_keys=True, ensure_ascii=False, indent=2) + "\n")
        _need(_module_receipts() == original_modules, "participating publisher source changed during admission")
        temporary.rename(out_dir)
        return {"schema": "scar.source-program-publication-result", "schema_version": 1,
            "manifest": str(out_dir / "manifest.json"), "changed_bodies": replacements,
            "changed_files": publication["changed_files"], "admission_changes": len(admission_changes),
            "counts": counts, "current_run_integrated": False, "whole_program_established": False}
    except BaseException as error:
        failure = {"status": "BUILDING_FAILED_RETAINED", "error_type": type(error).__name__,
            "detail": str(error), "building_directory": str(temporary),
            "intended_output": str(out_dir), "source_programs": inputs,
            "whole_program_established": False}
        (temporary / "failure.json").write_text(json.dumps(failure, indent=2) + "\n")
        error.add_note("source publication BUILDING artifacts retained at " + str(temporary))
        raise


__all__ = ["publish_source_programs"]
