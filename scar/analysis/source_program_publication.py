"""Admit archived source-language bodies into an immutable partition snapshot.

CP2 records contain fixed locators into existing SourceProgram5 artifacts. They
do not copy graphs, replay lowering, or turn historical calls into this Run.
"""
from __future__ import annotations

import ast
from collections import Counter
from copy import deepcopy
from dataclasses import dataclass
from hashlib import sha256
import json
from pathlib import Path
import tempfile
import time

from scar.analysis.inventory_partitions import InventoryPartitions, _read_receipt, _write_shard
from scar.analysis.program_composition import CompositionIndex
from scar.analysis.program_lowering import SourceProgram, _symbol_tables
from scar.analysis.source_language import SourceCodeEvidence, SourceLanguageOptions
from scar.analysis.structured_lowering import require_valid_structured_body
from scar.ir.program.call_edges import CapturedCode, CodeCapture, CodeSourceLink
from scar.ir.program.call_demand import CallSourceScope
from scar.ir.program.inventory import BodyInventory, BodyStatus, DefinitionInventory
from scar.ir.program.functions import BodyEntryInterface, BodyLoweringProfile, FunctionSignature
from scar.ir.program.codec import dumps as dump_graph
from scar.ir.program.frames import FrameModel
from scar.ir.program.model import ProgramGraph
from scar.ir.program.source import LoweringMetadata
from scar.ir.program.source_language import SourceLanguageOverlay
from scar.ir.program.structured import StructuredBodyModel
from scar.ir.record_codec import decode, encode
from scar.ir.semantics_v2 import SourceSnapshot


_ENTRY_AUTHORITY = {
    "target_executed": False, "source_relowered": False,
    "construction_cost_known": False, "runtime_code_instance_established": False,
    "actual_formal_routing_established": False, "function_environment_established": False,
    "state_versions_established": False, "effects_established": False,
    "whole_program_established": False, "first_stage_complete": False,
    "transformation_authorized": False,
}


@dataclass(frozen=True, slots=True)
class _EntryBodyCache:
    """Already checked body fields used by CompositionIndex, without file layers.

    This private in-memory projection is never serialized as SourceProgram or
    treated as validation input. Original source contexts remain in their exact
    archived artifacts. Projection occurs only after ordinary admission checks.
    """
    graph: ProgramGraph
    metadata: LoweringMetadata
    profile: BodyLoweringProfile
    interface: BodyEntryInterface
    frame: FrameModel | None
    structured: StructuredBodyModel
    language: SourceLanguageOverlay


def _entry_body_cache(program, compact):
    if not compact:
        return program
    _need(type(program) is SourceProgram and program.graph is not None,
          "compact entry cache requires an admitted SourceProgram body")
    return _EntryBodyCache(*(getattr(program, name) for name in _EntryBodyCache.__dataclass_fields__))


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


_ADMISSION_CAPS = ["SOURCE_PROGRAM5_ADMISSION_V1"]
_REVISION_CAPS = ["SOURCE_PROGRAM5_ADMISSION_V1", "SOURCE_BODY_REVISION_V1"]


def _program_counts(program):
    return {"graph_bodies": 1, "core_operations": len(program.graph.operations),
        "core_values": len(program.graph.values), "regions": len(program.graph.regions),
        "locations": len(program.graph.locations),
        "ordered_uses": sum(len(row.uses) for row in program.graph.operations),
        "bound_bodies": 1, "structured_bodies": 1,
        "protocols": len(program.structured.protocols), "loops": len(program.structured.loops)}


def _replace_active_refs(base, references, changed, count_name):
    result = [base.external_reference(ref) for ref in references]
    for item in changed.values():
        target = item["accounting"]["checkpoint"]
        identity = item["checkpoint"]["body_identity"]
        positions = [i for i, ref in enumerate(result) if ref == target]
        same_body = [i for i, ref in enumerate(result) if ref["body_identity"] == identity]
        required = item["accounting"]["counts"][count_name]
        _need(required in (0, 1) and len(positions) == len(same_body) == required,
              "active component has missing, duplicate or different previous checkpoint for one qualified body")
        if positions:
            result[positions[0]] = item["checkpoint"]
        else:
            result.append(item["checkpoint"])
    return result


def _summary_after(parent, transitions, admissions):
    summary = deepcopy(parent)
    known = summary.get("known_construction_operations", summary["construction_operations"])
    unknown = summary.get("unknown_construction_cost_bodies", 0)
    for old, before, after in transitions:
        summary["body_statuses"][old["status"]] -= 1
        summary["body_statuses"]["LOWERED_WITH_GAPS"] += 1
        for name in ("core_operations", "core_values"):
            summary[name] += after[name] - before[name]
        if old["construction_operations"] is not None:
            known -= old["construction_operations"]; unknown += 1
        summary["interfaces"]["bound_bodies"] += after["bound_bodies"] - before["bound_bodies"]
        for source, target in (("structured_bodies", "bodies"), ("protocols", "protocols"), ("loops", "loops")):
            summary["structured"][target] += after[source] - before[source]
    _need(known >= 0 and unknown >= 0 and all(value >= 0 for value in summary["body_statuses"].values())
          and all(summary[key] >= 0 for key in ("core_operations", "core_values"))
          and summary["interfaces"]["bound_bodies"] >= 0
          and all(summary["structured"][key] >= 0 for key in ("bodies", "protocols", "loops")),
          "body revision accounting underflow")
    summary.update(construction_operations=None, known_construction_operations=known,
                   unknown_construction_cost_bodies=unknown)
    summary["call_source_scope"] = dict(sorted(Counter(row.status.value for row in admissions).items()))
    return summary


@dataclass(frozen=True)
class SourceBodyPublicationPlan:
    document: dict
    sha256: str

    def require_unchanged(self):
        _need(type(self.document) is dict and sha256(_canonical(self.document)).hexdigest() == self.sha256,
              "body publication expectations changed")


def plan_source_body_publication(base_composition, source_program_paths, *, max_programs=128,
                                 max_record_bytes=128_000_000):
    """Derive exact parent/CAS navigation records; this does not admit a graph."""
    _need(type(max_programs) is int and max_programs > 0 and type(max_record_bytes) is int and max_record_bytes > 0,
          "positive independent revision plan ceilings required")
    _need(type(base_composition) is CompositionIndex and base_composition.partitioned
          and type(source_program_paths) is tuple and 0 < len(source_program_paths) <= max_programs,
          "bounded original composition and immutable program paths required")
    base = base_composition.inventory
    expectations, seen = [], set()
    for path in source_program_paths:
        document, receipt = _read_receipt(path, limit=max_record_bytes)
        _need(document.get("schema") == "scar.source-program" and document.get("schema_version") == 5
              and document.get("graph") is not None and document.get("interface") is not None
              and document.get("language") is not None, "revision navigation requires a real SourceProgram5")
        files = [row for row in base_composition.document["files"]
                 if row["snapshot"] == document["metadata"]["source"]
                 and (row.get("context") or {}).get("namespace_root") == document["language"]["namespace_root"]]
        _need(len(files) == 1, "replacement source has no unique original snapshot/context")
        file = files[0]; fi = file["file_index"]
        bodies = [(i, row) for i, row in enumerate(file["bodies"])
                  if row["definition"] == document["interface"]["definition"]["wire"]]
        _need(len(bodies) == 1, "replacement definition has no unique original body")
        bi, body = bodies[0]; key = fi, bi
        _need(key not in seen, "duplicate qualified body revision")
        seen.add(key)
        raw_file = base_composition.inventory_file(fi)
        raw_body = raw_file["bodies"][bi]
        definitions = [row for row in raw_file["definitions"]
                       if row["id"] == document["interface"]["definition"]
                       and row["source"] == document["structured"]["source"]]
        _need(len(definitions) == 1, "replacement definition/source differs from its original index")
        expectations.append({"operation": "REVISE_GRAPH" if body["root"] is not None else "ADD_GRAPH",
            "file_index": fi, "body_index": bi, "snapshot": deepcopy(raw_file["snapshot"]),
            "context": deepcopy(raw_file["context"]), "definition": deepcopy(raw_body["definition"]),
            "source": deepcopy(document["structured"]["source"]),
            "expected_checkpoint": base.external_reference(raw_body["checkpoint"]) if raw_body["checkpoint"] else None,
            "expected_namespace": deepcopy(body.get("namespace")),
            "expected_graph_canonical_sha256": body["program_canonical_sha256"],
            "expected_root": body["root"],
            "replacement": _input_ref(path, receipt, "scar.source-program/5")})
    document = {"schema": "scar.source-body-publication-plan", "schema_version": 1,
        "base_inventory": deepcopy(base_composition.document["inventory"]),
        "base_manifest_receipt": deepcopy(base.manifest_receipt),
        "base_composition": deepcopy(base_composition.index_receipt),
        "base_composition_canonical_sha256": base_composition.source_inputs()["composition_canonical_sha256"],
        "code_source_origin": base_composition.original_code_source_origin(),
        "expectations": expectations, "source_admission_authorized": False}
    return SourceBodyPublicationPlan(document, sha256(_canonical(document)).hexdigest())


def publish_source_body_revisions(base_composition, plan, out_dir, *, code_witnesses,
                                  max_programs=128, max_changed_sources=64,
                                  max_operations_per_body=10000, max_record_bytes=128_000_000, progress=None):
    """Explicit snapshot revision, with independent current-parent/CAS checks."""
    _need(type(plan) is SourceBodyPublicationPlan, "a regular explicit revision expectation plan is required")
    plan.require_unchanged()
    paths = tuple(row["replacement"]["uri"] for row in plan.document["expectations"])
    fresh = plan_source_body_publication(base_composition, paths, max_programs=max_programs,
                                         max_record_bytes=max_record_bytes)
    _need(fresh.document == plan.document and fresh.sha256 == plan.sha256,
          "stale parent/checkpoint/namespace/digest body publication expectation")
    return _publish_source_programs(base_composition, paths, out_dir, code_witnesses=code_witnesses,
        max_programs=max_programs, max_changed_sources=max_changed_sources,
        max_operations_per_body=max_operations_per_body, max_record_bytes=max_record_bytes,
        progress=progress, revision_plan=plan)


def validate_body_revision_publication(base_composition, inventory, *, max_programs=128):
    """Validate lineage/counts/active references, not historical source legality.

    New bodies still require the ordinary public typed/source/code validators.
    This bounded check reads only the changed old/new bodies for accounting.
    """
    _need(type(base_composition) is CompositionIndex and type(inventory) is InventoryPartitions
          and inventory.manifest.get("capabilities") == _REVISION_CAPS,
          "explicit revision snapshot and actual parent composition required")
    publication = inventory.component("publication")
    _need(publication.get("schema_version") == 2, "revision requires publication2")
    _need(publication["base_inventory"] == base_composition.document["inventory"]
          and publication["base_composition"] == base_composition.index_receipt
          and publication["base_composition_canonical_sha256"] == base_composition.source_inputs()["composition_canonical_sha256"]
          and publication["code_source_origin"] == inventory.code_source_origin()
              == base_composition.original_code_source_origin(), "revision actual parent or original compiler basis differs")
    document = publication["expectations"]
    _need(type(max_programs) is int and 0 < len(document["expectations"]) <= max_programs,
          "revision expectation count exceeds independent validation ceiling")
    plan = SourceBodyPublicationPlan(document, publication["expectations_sha256"])
    plan.require_unchanged()
    fresh = plan_source_body_publication(base_composition,
        tuple(row["replacement"]["uri"] for row in document["expectations"]),
        max_programs=max_programs, max_record_bytes=inventory.max_shard_bytes)
    _need(fresh.document == document and fresh.sha256 == plan.sha256,
          "revision snapshot has stale parent/checkpoint/namespace/digest expectations")
    expected = {(row["file_index"], row["body_index"]): row for row in document["expectations"]}
    _need(len(publication["changed_bodies"]) == len(expected), "revision changed-body denominator differs")
    base, changed, transitions = base_composition.inventory, {}, []
    changed_files = {fi for fi, _ in expected}
    _need(publication["changed_files"] == sorted(changed_files)
          and len(inventory.manifest["files"]) == len(base.manifest["files"]),
          "revision changed-file or source-file denominator differs")
    for fi, ref in enumerate(base.manifest["files"]):
        if fi not in changed_files:
            _need(base.external_reference(ref) == inventory.external_reference(inventory.manifest["files"][fi]),
                  "revision changed an undeclared original source shard")
            continue
        old_file, new_file = base.file(fi), inventory.file(fi)
        _need({key: value for key, value in old_file.items() if key != "bodies"}
              == {key: value for key, value in new_file.items() if key != "bodies"}
              and len(old_file["bodies"]) == len(new_file["bodies"]),
              "revision changed source/snapshot/context/static-definition denominators")
        for bi, body in enumerate(old_file["bodies"]):
            if (fi, bi) not in expected:
                _need(body == new_file["bodies"][bi], "revision changed an undeclared original body")
    for change in publication["changed_bodies"]:
        key = change["file_index"], change["body_index"]
        _need(key in expected and key not in changed and change["expectation"] == expected[key]
              and change["operation"] == expected[key]["operation"], "revision target/CAS record differs")
        fi, bi = key; target = expected[key]
        old = base.historical_body_accounting(fi, bi, expected_parent=document["base_manifest_receipt"],
            expected_checkpoint=target["expected_checkpoint"], expected_namespace=target["expected_namespace"],
            expected_graph_sha256=target["expected_graph_canonical_sha256"])
        _need(change["old_accounting"] == old, "revision historical raw/core accounting differs")
        current_ref = inventory.external_reference(inventory.file(fi)["bodies"][bi]["checkpoint"])
        _need(current_ref == change["checkpoint"], "revision active checkpoint differs from its transition")
        cp = inventory.checkpoint(current_ref)
        previous = {"inventory_locator": base_composition.inventory_file_locator(fi, f"/bodies/{bi}"),
                    **old["field_locators"], "namespace": old["namespace"]}
        _need(cp["schema_version"] == 2 and cp["previous_body"] == change["previous_body"] == previous
              and cp["source_program"] == target["replacement"] == change["source_program"],
              "new CP admission lost its actual source-program or exact previous-body reference")
        raw = inventory.body_record(fi, bi)
        graph_sha = sha256(_canonical(raw["graph"])).hexdigest()
        locators = inventory.body_field_locators(fi, bi)
        after = inventory.historical_body_accounting(fi, bi, expected_parent=inventory.manifest_receipt,
            expected_checkpoint=current_ref, expected_namespace=locators["graph_locator"]["namespace"],
            expected_graph_sha256=graph_sha)
        counts = after["counts"]
        _need(counts["graph_bodies"] == counts["bound_bodies"] == counts["structured_bodies"] == 1
              and counts == change["new_counts"]
              and {key: counts[key] - old["counts"][key] for key in counts} == change["counts_delta"],
              "revision new counts/delta differ from actual receipt-bound core fields")
        changed[key] = {"accounting": old, "checkpoint": current_ref}
        transitions.append(({"status": old["status"], "construction_operations": old["construction_operations"]},
                            old["counts"], counts))
    # Checkpoint shards/changed_bodies are stored by (file, body), while ADD
    # references are appended in the exact original publication-plan order.
    # Preserve that order when independently rebuilding active components.
    changed = {key: changed[key] for key in expected}
    interfaces = deepcopy(base_composition.inventory_component("interfaces"))
    interfaces["bodies"] = _replace_active_refs(base, interfaces["bodies"], changed, "bound_bodies")
    _need(inventory.component("interfaces") == interfaces, "revision active interface replacement differs")
    _need(inventory.component("structured") == _replace_active_refs(base,
          base_composition.inventory_component("structured"), changed, "structured_bodies"),
          "revision active structured replacement differs")
    scope = decode(CallSourceScope, inventory.component("call_source_scope"))
    old_scope = decode(CallSourceScope, base_composition.inventory_component("call_source_scope"))
    expected_admissions = list(old_scope.admissions)
    seen = set()
    for row in publication["admission_changes"]:
        index = row["index"]
        _need(type(index) is int and 0 <= index < len(expected_admissions) and index not in seen
              and encode(expected_admissions[index]) == row["before"], "revision admission previous record differs")
        seen.add(index)
        updated = decode(type(expected_admissions[index]), row["after"])
        _need(updated.origin == expected_admissions[index].origin, "revision changed an original admission origin")
        expected_admissions[index] = updated
    _need(scope.admissions == tuple(expected_admissions), "revision changed undeclared admission records")
    parent_summary = base_composition.inventory_component("header")["summary"]
    header = inventory.component("header")
    _need(header.get("schema") == "scar.partitioned-inventory-header" and header.get("schema_version") == 2
          and header.get("profile") == "STRUCTURED_ENV_V1" and header.get("capabilities") == _REVISION_CAPS,
          "revision header/version/entry ABI/capability differs")
    _need(header["summary"] == _summary_after(parent_summary, transitions, scope.admissions),
          "revision header summary violates before-minus-old-plus-new accounting")
    counts = deepcopy(base.manifest["counts"])
    counts["graph_bodies"] += sum(after["graph_bodies"] - before["graph_bodies"] for _, before, after in transitions)
    counts["checkpoint_returns"] += sum(row["expected_checkpoint"] is None for row in expected.values())
    counts["not_attempted_bodies"] -= sum(old["status"] == "NOT_ATTEMPTED" for old, _, _ in transitions)
    _need(inventory.manifest["counts"] == counts, "revision manifest count denominator differs")
    return {"valid": True, "scope": "LINEAGE_ACTIVE_REFERENCES_AND_ACCOUNTING_ONLY",
            "changed_bodies": len(changed), "old_source_legality_established": False,
            "new_source_code_proof_repeated": False, "target_executed": False}


def _entry_canonical(document, receipt):
    payload = _canonical(document)
    return any(len(value) == receipt["decoded_bytes"] and sha256(value).hexdigest() == receipt["decoded_sha256"]
               for value in (payload, payload + b"\n"))


def _entry_program(catalog, request, max_operations, max_record_bytes, *, publication_version=1):
    """Ordinary independent reader over one original, externally qualified body."""
    from scar.analysis.source_entry_catalog import SourceEntryCatalog
    from scar.analysis.source_attachments import SourceAttachments
    from scar.analysis.function_interfaces import extract_entry_signature, validate_body_interface
    _need(type(catalog) is SourceEntryCatalog and type(request) is dict
          and set(request) == {"entry_key", "source_program"}, "exact entry/program request required")
    entry = catalog.resolve(request["entry_key"])
    owner = catalog.require_entry(entry)
    _need(publication_version in (1, 2, 3) and (type(owner) is SourceAttachments
          or publication_version in (2, 3) and type(owner) is CompositionIndex and owner in catalog.projects),
          "publication requires its exact admitted owner under this schema")
    expected = request["source_program"]
    _need(type(expected) is dict and set(expected) == {"uri", "external", "representation",
          "physical_sha256", "physical_bytes", "decoded_sha256", "decoded_bytes"}
          and expected["external"] is True and expected["representation"] == "scar.source-program/5",
          "exact original SourceProgram5 receipt required")
    path = Path(expected["uri"])
    _need(path.is_absolute() and path.resolve(strict=True) == path, "original source program URI changed")
    document, receipt = _read_receipt(path, limit=max_record_bytes)
    _need(all(receipt[key] == expected[key] for key in receipt)
          and _entry_canonical(document, receipt),
          "original program stored/decoded/canonical receipt differs")
    _need(document.get("schema_version") == 5, "external function publication requires SourceProgram5")
    context = catalog.prepare(entry)  # archived source/AST only, no lower/seal/prepare_source
    program = SourceProgram.read_structure(document, max_operations=max_operations,
        source_texts={entry.reference.snapshot.path: context.text})
    reference = entry.reference
    _need(program.graph is not None and program.interface is not None and program.language is not None
          and program.structured is not None and program.metadata.source == reference.snapshot
          and program.interface.definition == reference.definition
          and program.structured.definition == reference.definition and program.structured.source == reference.source
          and program.language.namespace_root == reference.context.namespace_root,
          "source program changes the original definition/snapshot/namespace")
    _need([sha256(_canonical(document[key])).hexdigest() for key in ("semantic", "semantics", "control")]
          == [getattr(reference.context, key) for key in ("semantic_sha256", "semantics_sha256", "control_sha256")],
          "program source graphs differ from the original qualified context")
    evidence = SourceCodeEvidence.from_entry(catalog, entry)
    _need(program.language.code_evidence == evidence.to_dict(), "program compiler/source origin differs from the exact entry")
    require_valid_structured_body(program.structured, program.graph, program.interface, program.metadata,
        semantic=program.semantic, control=program.control, language=program.language,
        source_tree=context.tree, language_options=SourceLanguageOptions(program.language.capabilities, evidence))
    body = BodyInventory(reference.definition, BodyStatus.LOWERED_WITH_GAPS, program.graph, program.metadata,
                         "; ".join(dict.fromkeys(gap.detail for gap in program.metadata.gaps)), None)
    signature = extract_entry_signature(context, reference)
    validate_body_interface(body, program.interface, signature)
    return entry, program, body, signature


def _entry_admissions(catalog, entry, body):
    from scar.analysis.call_demand import derive_entry_source_admission
    from scar.ir.program.call_demand import EnteredCallCode
    return [encode(derive_entry_source_admission(EnteredCallCode(row["process_id"], row["code"]),
        entry.source_link, catalog=catalog, entry=entry, body=body))
        for row in catalog.metadata()["groups"] if row.get("entry_key") == entry.key]


def _entry_parent(base, catalog):
    from scar.analysis.source_entry_catalog import SourceEntryCatalog
    _need(type(base) is CompositionIndex and type(catalog) is SourceEntryCatalog
          and len(catalog.projects) == 1 and catalog.projects[0] is base
          and not base.has_source_entry_publication and not base.has_source_attachments,
          "entry publication requires its exact unchanged project parent and original catalog")
    _need(all(owner.receipts()["format"] == "scar.source-admissions-input.v1" for owner in catalog.admissions),
          "entry publication requires explicit direct-admissions inputs")
    catalog.require_unchanged()
    return {"parent_composition": deepcopy(base.index_receipt), "parent_inputs": base.source_inputs(),
            "catalog_inputs": catalog.inputs(), "catalog_sha256": sha256(_canonical(catalog.metadata())).hexdigest(),
            "entered_code_groups": catalog.metadata()["entered_code_groups"],
            "entered_invocations": catalog.metadata()["entered_invocations"],
            "candidate_entries": len(catalog.metadata()["candidates"])}


def _entry_module_receipts():
    names = ("source_program_publication.py", "program_composition.py", "function_interfaces.py", "call_demand.py",
             "source_entry_catalog.py", "source_attachments.py", "source_language.py", "compiler_witness_archives.py",
             "code_witness.py", "program_lowering.py", "structured_lowering.py", "inventory_partitions.py")
    return [{"path": str(Path(__file__).with_name(name)),
             "sha256": sha256(Path(__file__).with_name(name).read_bytes()).hexdigest()} for name in names]


def publish_source_entries(base_composition, catalog, source_programs, out_dir, *, max_programs=1,
                           max_operations_per_body=4000, max_record_bytes=64_000_000, progress=None, plan=None):
    """Ordinary per-body admission, with a private source-input read scope."""
    from scar.analysis.source_entry_catalog import SourceEntryCatalog
    _need(type(catalog) is SourceEntryCatalog and type(base_composition) is CompositionIndex
          and (progress is None or callable(progress))
          and (plan is None or type(plan) is SourceEntryPublicationPlan), "exact entry publisher inputs/progress required")
    if catalog._ordinary_read_active():
        return _publish_source_entries(base_composition, catalog, source_programs, out_dir,
            max_programs=max_programs, max_operations_per_body=max_operations_per_body,
            max_record_bytes=max_record_bytes, progress=progress, plan=plan)
    controls = (source_programs, plan.document if plan is not None else None)
    with catalog._ordinary_read_session(base_composition, controls=controls) as session:
        callback = None if progress is None else lambda row: session.progress(progress, row)
        fixed = json.loads(session.control_bytes)
        private_plan = SourceEntryPublicationPlan(fixed[1], plan.sha256) if plan is not None else None
        return _publish_source_entries(session.target, session.catalog, tuple(fixed[0]), out_dir,
            max_programs=max_programs, max_operations_per_body=max_operations_per_body,
            max_record_bytes=max_record_bytes, progress=callback, plan=private_plan)


def _publish_source_entries(base_composition, catalog, source_programs, out_dir, *, max_programs=1,
                            max_operations_per_body=4000, max_record_bytes=64_000_000, progress=None, plan=None):
    """Independently admit saved external SP5s; publish only qualified navigation.

    No lower owner, fi/bi, copied graph or known construction cost is created.
    """
    if plan is not None:
        return _publish_source_entries2(base_composition, catalog, source_programs, out_dir, plan=plan,
            max_programs=max_programs, max_operations_per_body=max_operations_per_body,
            max_record_bytes=max_record_bytes, progress=progress)
    _need(all(type(value) is int and value > 0 for value in
              (max_programs, max_operations_per_body, max_record_bytes))
          and type(source_programs) is tuple and 0 < len(source_programs) <= max_programs,
          "positive bounded original entry publication requests required")
    _need(progress is None or callable(progress), "invalid entry publication progress callback")
    parent = _entry_parent(base_composition, catalog)
    out = Path(out_dir).resolve()
    _need(not out.exists(), "entry publication output already exists")
    out.mkdir(parents=True, exist_ok=False)
    rows, seen = [], set()
    for serial, request in enumerate(source_programs):
        entry, program, body, signature = _entry_program(catalog, request, max_operations_per_body, max_record_bytes)
        key = _canonical(encode(entry.reference))
        _need(key not in seen, "duplicate original qualified body ADD")
        seen.add(key)
        identity = {"definition": encode(entry.reference.definition), "source": encode(entry.reference.source),
                    "entry": program.metadata.entry}
        checkpoint = {"schema": "scar.body-construction-checkpoint", "schema_version": 2,
            "origin": "SOURCE_PROGRAM5_ADMISSION", "source_program": deepcopy(request["source_program"]),
            "body_identity": identity, "context": encode(entry.reference.context),
            "profile": program.profile.value, "language": "#/language",
            "fields": {name: "#/" + name for name in ("graph", "metadata", "interface", "frame", "structured", "language")},
            "construction_operations": None, "construction_cost_known": False, "previous_body": None,
            "definition_reference": encode(entry.reference), "whole_program_established": False}
        cp_ref = _write_shard(out, f"bodies/{serial:05d}.json.gz", checkpoint, limit=max_record_bytes)
        cp_ref = {**cp_ref, "uri": str(out / cp_ref["uri"]), "external": True}
        rows.append({"operation": "ADD_GRAPH", "entry_key": entry.key, "definition": encode(entry.reference),
            "source_program": deepcopy(request["source_program"]), "checkpoint": cp_ref,
            "signature": encode(signature), "admissions": _entry_admissions(catalog, entry, body),
            "program_graph_sha256": sha256(_canonical(json.loads(dump_graph(program.graph)))).hexdigest(),
            "root": encode(program.graph.root), "construction_operations": None})
        if progress is not None:
            progress({"stage": "admit_qualified_entry", "entry_key": entry.key, "status": "VERIFIED"})
    _need(_entry_parent(base_composition, catalog) == parent, "entry parent inputs changed during admission")
    document = {"schema": "scar.source-entry-publication", "schema_version": 1, **parent,
        "bodies": rows, "producer": _entry_module_receipts(), **_ENTRY_AUTHORITY}
    payload = _canonical(document)
    _need(len(payload) <= max_record_bytes, "entry manifest byte ceiling exceeded")
    with (out / "manifest.json").open("xb") as stream:
        stream.write(payload)
    return {"manifest": str(out / "manifest.json"), "sha256": sha256(payload).hexdigest(),
            "body_count": len(rows), "construction_operations": None, **_ENTRY_AUTHORITY}


def read_source_entry_publication(path, *, expected_sha256, catalog, max_programs=1,
                                  max_operations_per_body=4000, max_record_bytes=64_000_000,
                                  target_composition=None, _compact_body_cache=False):
    """Normal source/code read; private caches do not survive as proof flags."""
    from scar.analysis.source_entry_catalog import SourceEntryCatalog
    _need(type(catalog) is SourceEntryCatalog, "exact ordinary source-entry catalog required")
    if catalog._ordinary_read_active():
        return _read_source_entry_publication(path, expected_sha256=expected_sha256, catalog=catalog,
            max_programs=max_programs, max_operations_per_body=max_operations_per_body,
            max_record_bytes=max_record_bytes, target_composition=target_composition,
            _compact_body_cache=_compact_body_cache)
    target = target_composition or catalog.projects[0]
    with catalog._ordinary_read_session(target) as session:
        document, receipt, checked = _read_source_entry_publication(path,
            expected_sha256=expected_sha256, catalog=session.catalog, max_programs=max_programs,
            max_operations_per_body=max_operations_per_body, max_record_bytes=max_record_bytes,
            target_composition=session.target if target_composition is not None else None,
            _compact_body_cache=_compact_body_cache)
    return document, receipt, tuple({**row, 'entry':session.entry(row['entry'])} for row in checked)


def _read_source_entry_publication(path, *, expected_sha256, catalog, max_programs=1,
                                   max_operations_per_body=4000, max_record_bytes=64_000_000,
                                   target_composition=None, _compact_body_cache=False):
    """Ordinary source/code reader; returned records are a cache, not new graphs."""
    from scar.ir.program.source_references import SourceDefinitionReference
    _need(all(type(value) is int and value > 0 for value in
              (max_programs, max_operations_per_body, max_record_bytes)), "invalid entry-reader ceilings")
    _need(type(_compact_body_cache) is bool, "compact cache selection requires exact bool")
    _need(type(catalog.projects) is tuple and len(catalog.projects) == 1,
          "publication reader needs one exact original project")
    document, receipt = _read_receipt(path, limit=max_record_bytes)
    if document.get("schema_version") in (2, 3):
        return _read_source_entries2(document, receipt, expected_sha256=expected_sha256, catalog=catalog,
            target=target_composition, max_programs=max_programs, max_operations=max_operations_per_body,
            max_record_bytes=max_record_bytes, compact_body_cache=_compact_body_cache)
    _need(receipt["physical_sha256"] == expected_sha256
          and _entry_canonical(document, receipt)
          and document.get("schema") == "scar.source-entry-publication" and document.get("schema_version") == 1
          and all(document.get(key) is value for key, value in _ENTRY_AUTHORITY.items()),
          "entry publication schema/canonical receipt/authority differs")
    parent = _entry_parent(catalog.projects[0], catalog)
    _need(all(document.get(key) == value for key, value in parent.items()), "entry publication parent/catalog/CAS differs")
    rows, seen = document.get("bodies"), set()
    _need(type(rows) is list and 0 < len(rows) <= max_programs, "entry publication body ceiling exceeded")
    checked = []
    for row in rows:
        _need(row["operation"] == "ADD_GRAPH" and row["construction_operations"] is None,
              "external publication must be a cost-unknown independent ADD")
        entry, program, body, signature = _entry_program(catalog,
            {"entry_key": row["entry_key"], "source_program": row["source_program"]},
            max_operations_per_body, max_record_bytes)
        reference = decode(SourceDefinitionReference, row["definition"])
        key = _canonical(encode(reference))
        _need(reference == entry.reference and key not in seen, "duplicate or substituted qualified entry")
        seen.add(key)
        _need(row["signature"] == encode(signature) and row["root"] == encode(body.graph.root)
              and row["admissions"] == _entry_admissions(catalog, entry, body)
              and row["program_graph_sha256"] == sha256(_canonical(json.loads(dump_graph(program.graph)))).hexdigest(),
              "entry signature/admission/root/graph digest differs")
        checkpoint, actual = _read_receipt(row["checkpoint"]["uri"], limit=max_record_bytes)
        _need(all(actual[name] == row["checkpoint"][name] for name in actual)
              and _entry_canonical(checkpoint, actual), "entry CP2 receipt differs")
        expected = {"schema": "scar.body-construction-checkpoint", "schema_version": 2,
            "origin": "SOURCE_PROGRAM5_ADMISSION", "source_program": row["source_program"],
            "body_identity": {"definition": encode(reference.definition), "source": encode(reference.source),
                              "entry": program.metadata.entry}, "context": encode(reference.context),
            "profile": program.profile.value, "language": "#/language",
            "fields": {name: "#/" + name for name in ("graph", "metadata", "interface", "frame", "structured", "language")},
            "construction_operations": None, "construction_cost_known": False, "previous_body": None,
            "definition_reference": encode(reference), "whole_program_established": False}
        _need(checkpoint == expected, "entry CP2 fixed fields/origin/context/body identity differ")
        checked.append({"record": deepcopy(row), "body": body,
                        "program": _entry_body_cache(program, _compact_body_cache), "entry": entry})
    return document, receipt, tuple(checked)


@dataclass(frozen=True)
class SourceEntryPublicationPlan:
    document: dict
    sha256: str

    def require_unchanged(self):
        _need(sha256(_canonical(self.document)).hexdigest() == self.sha256,
              "qualified entry publication plan changed")


def _entry_attachment3(declaration):
    """Exact existing owner inputs, not a decoder that constructs authority."""
    from scar.ir.program.source_references import SourceArtifactLocator
    _need(type(declaration) is dict and set(declaration) == {
        "report", "parent", "format", "source_root_count", "source_file_count"}
        and all(type(declaration[key]) is int and declaration[key] >= 0
                for key in ("source_root_count", "source_file_count")),
          "schema3 requires complete original attachment receipts")
    report = decode(SourceArtifactLocator, declaration["report"])
    _need(report.pointer == "#" and report.declaration is None
          and report.representation == "canonical-json", "schema3 report must name the whole original manifest")
    if declaration["format"] == "scar.source-admissions-input.v1":
        _need(declaration["parent"] is None and report.artifact.schema == "scar.dependency-source-admissions",
              "schema3 direct input has a parent or different report schema")
        return report, None
    _need(declaration["format"] == "scar.source-attachments-input.v1"
          and report.artifact.schema == "scar.dependency-source-continuation"
          and declaration["parent"] is not None,
          "schema3 continuation input requires its exact report and parent")
    parent = decode(SourceArtifactLocator, declaration["parent"])
    _need(parent.pointer == "#" and parent.declaration is None
          and parent.representation == "canonical-json"
          and parent.artifact.schema == "scar.dependency-source-admissions",
          "schema3 continuation parent must name the whole original admissions manifest")
    return report, parent


def _entry_attachment_inputs3(catalog):
    """Keep continuation parents immutable as well as the original reports."""
    from scar.analysis.source_attachments import SourceAttachments, _plain
    declarations = []
    for owner in catalog.admissions:
        _need(type(owner) is SourceAttachments, "schema3 requires an ordinary original attachment owner")
        owner.require_unchanged()
        declaration = owner.receipts()
        _, parent = _entry_attachment3(declaration)
        if parent is not None:
            _, actual = _plain(parent.artifact.uri, parent.artifact.sha256,
                               "scar.dependency-source-admissions", owner.budget.max_report_bytes)
            _need(actual == parent, "schema3 continuation parent locator/bytes changed")
        declarations.append(declaration)
    return declarations


def _entry_parent2(target, catalog, *, publication_version=2):
    from scar.analysis.source_entry_catalog import SourceEntryCatalog
    _need(type(target) is CompositionIndex and type(catalog) is SourceEntryCatalog and len(catalog.projects) == 1,
          "qualified publication requires one original project/catalog")
    original = catalog.projects[0]
    _need(not original.has_source_entry_publication and not original.has_source_attachments
          and (not target.has_source_attachments or target.has_source_entry_publication),
          "planning project must remain its original view; target uses explicit entry overlays")
    _need(original.original_code_source_origin() == target.original_code_source_origin()
          and _canonical(original.inventory_component("call_sources")) == _canonical(target.inventory_component("call_sources"))
          and original.inventory_component("discovery")["project_root"] == target.inventory_component("discovery")["project_root"],
          "planning and publication targets differ in original compiler/capture/project basis")
    _need(type(publication_version) is int and publication_version in (2, 3),
          "qualified publication requires explicit schema2 or schema3")
    if publication_version == 3:
        _entry_attachment_inputs3(catalog)
    else:
        _need(all(owner.receipts()["format"] == "scar.source-admissions-input.v1" for owner in catalog.admissions),
              "qualified publication requires exact direct-admissions inputs")
    if target.has_source_entry_publication:
        _need(target.source_inputs()["attachments"] == [owner.receipts() for owner in catalog.admissions],
              "target overlay and catalog admitted namespaces differ")
    catalog.require_unchanged()
    metadata = catalog.metadata()
    return {"parent_composition": deepcopy(target.index_receipt), "parent_inputs": target.source_inputs(),
        "parent_entry_publication": target.entry_publication_reference(),
        "catalog_project_composition": deepcopy(original.index_receipt), "catalog_inputs": catalog.inputs(),
        "catalog_sha256": sha256(_canonical(metadata)).hexdigest(),
        "original_code_source_origin": target.original_code_source_origin(),
        "entered_code_groups": metadata["entered_code_groups"], "entered_invocations": metadata["entered_invocations"],
        "candidate_entries": len(metadata["candidates"])}


def plan_source_entry_publication(target, catalog, source_programs, *, max_programs=1, publication_version=2):
    """Exact original CAS plan; no canonical body or lowering owner is made."""
    from scar.analysis.source_entry_catalog import SourceEntryCatalog
    _need(type(catalog) is SourceEntryCatalog and type(target) is CompositionIndex,
          "exact ordinary entry planner owners required")
    if catalog._ordinary_read_active():
        return _plan_source_entry_publication(target, catalog, source_programs,
            max_programs=max_programs, publication_version=publication_version)
    with catalog._ordinary_read_session(target, controls=(source_programs,)) as session:
        return _plan_source_entry_publication(session.target, session.catalog, tuple(json.loads(session.control_bytes)[0]),
            max_programs=max_programs, publication_version=publication_version)


def _plan_source_entry_publication(target, catalog, source_programs, *, max_programs=1, publication_version=2):
    """Exact source-qualified ADD/REVISE expectations; never admit a graph."""
    _need(type(max_programs) is int and max_programs > 0 and type(source_programs) is tuple
          and 0 < len(source_programs) <= max_programs, "bounded complete program requests required")
    parent, expected, seen = _entry_parent2(target, catalog, publication_version=publication_version), [], set()
    for request in source_programs:
        _need(type(request) is dict and set(request) == {"entry_key", "source_program"}, "exact entry request required")
        entry = catalog.resolve(request["entry_key"])
        catalog.require_entry(entry).resolve_definition(entry.reference)
        identity = _canonical(encode(entry.reference))
        _need(identity not in seen, "duplicate qualified program definition")
        seen.add(identity)
        state = target.body_publication_state(entry.reference)
        _need((entry.origin["kind"] == "PROJECT_INVENTORY") == (state["project_slot"] is not None),
              "project entry has no unique real target file/body slot, or external entry acquired one")
        expected.append({"entry_key": entry.key, "definition": encode(entry.reference),
            "entry_navigation_origin": entry.origin, "owner_kind": entry.origin["kind"],
            "operation": "REVISE_GRAPH" if state["body"] is not None else "ADD_GRAPH",
            "expected_parent_body": state, "source_program": deepcopy(request["source_program"])})
    document = {"schema": "scar.source-entry-publication-plan", "schema_version": publication_version,
                **parent, "expectations": expected, "source_admission_authorized": False}
    return SourceEntryPublicationPlan(document, sha256(_canonical(document)).hexdigest())


def _entry2_checkpoint(entry, program, expected):
    return {"schema": "scar.body-construction-checkpoint", "schema_version": 2,
        "origin": "SOURCE_PROGRAM5_ADMISSION", "source_program": deepcopy(expected["source_program"]),
        "body_identity": {"definition": encode(entry.reference.definition), "source": encode(entry.reference.source),
                          "entry": program.metadata.entry}, "context": encode(entry.reference.context),
        "profile": program.profile.value, "language": "#/language",
        "fields": {name: "#/" + name for name in ("graph", "metadata", "interface", "frame", "structured", "language")},
        "construction_operations": None, "construction_cost_known": False,
        "previous_body": deepcopy(expected["expected_parent_body"]), "definition_reference": encode(entry.reference),
        "entry_navigation_origin": entry.origin, "compiler_evidence_pointer": "#/language/code_evidence",
        "publication_operation": expected["operation"], "whole_program_established": False}


def _entry2_abi(expected, program):
    old = expected["expected_parent_body"]["body"]
    if old is not None:
        _need(not old["frame_present"] and old["entry_profile"] in (None, program.profile.value),
              "qualified revision has an incompatible entry ABI or unadapted frame")


def _publish_source_entries2(target, catalog, requests, out_dir, *, plan, max_programs,
                              max_operations_per_body, max_record_bytes, progress):
    _need(type(plan) is SourceEntryPublicationPlan, "qualified publication requires its explicit CAS plan")
    plan.require_unchanged()
    version = plan.document.get("schema_version")
    _need(type(version) is int and version in (2, 3), "unsupported qualified publication plan schema")
    fresh = plan_source_entry_publication(target, catalog, requests, max_programs=max_programs,
                                          publication_version=version)
    _need(fresh.document == plan.document and fresh.sha256 == plan.sha256, "stale target/body/root/artifact CAS plan")
    _need(type(max_operations_per_body) is int and max_operations_per_body > 0
          and type(max_record_bytes) is int and max_record_bytes > 0 and (progress is None or callable(progress)),
          "invalid qualified publication ceilings/progress")
    out = Path(out_dir).resolve()
    _need(not out.exists(), "qualified publication output already exists")
    out.mkdir(parents=True, exist_ok=False)
    rows = []
    for serial, (request, expected) in enumerate(zip(requests, plan.document["expectations"])):
        entry, program, body, signature = _entry_program(catalog, request, max_operations_per_body,
                                                        max_record_bytes, publication_version=version)
        _need(encode(entry.reference) == expected["definition"] and entry.origin == expected["entry_navigation_origin"],
              "qualified definition/navigation changed")
        _entry2_abi(expected, program)
        checkpoint = _entry2_checkpoint(entry, program, expected)
        ref = _write_shard(out, f"bodies/{serial:05d}.json.gz", checkpoint, limit=max_record_bytes)
        ref = {**ref, "uri": str(out / ref["uri"]), "external": True}
        rows.append({**deepcopy(expected), "checkpoint": ref, "signature": encode(signature),
            "admissions": _entry_admissions(catalog, entry, body), "root": encode(body.graph.root),
            "program_graph_sha256": sha256(_canonical(json.loads(dump_graph(program.graph)))).hexdigest(),
            "construction_operations": None})
        if progress is not None:
            progress({"stage": "admit_qualified_entry", "entry_key": entry.key, "owner_kind": expected["owner_kind"],
                      "operation": expected["operation"], "status": "VERIFIED"})
    _need(plan_source_entry_publication(target, catalog, requests, max_programs=max_programs,
                                      publication_version=version).document == plan.document,
          "publication parent/body inputs changed during independent admission")
    document = {"schema": "scar.source-entry-publication", "schema_version": version,
        **_entry_parent2(target, catalog, publication_version=version),
        "plan": deepcopy(plan.document), "plan_sha256": plan.sha256,
        "bodies": rows, "producer": _entry_module_receipts(), **_ENTRY_AUTHORITY}
    payload = _canonical(document)
    _need(len(payload) <= max_record_bytes, "qualified publication manifest byte ceiling exceeded")
    with (out / "manifest.json").open("xb") as stream:
        stream.write(payload)
    return {"manifest": str(out / "manifest.json"), "sha256": sha256(payload).hexdigest(),
            "body_count": len(rows), "schema_version": version, "construction_operations": None, **_ENTRY_AUTHORITY}


def _read_source_entries2(document, receipt, *, expected_sha256, catalog, target, max_programs,
                           max_operations, max_record_bytes, compact_body_cache=False):
    version = document.get("schema_version")
    _need(type(target) is CompositionIndex and receipt["physical_sha256"] == expected_sha256
          and _entry_canonical(document, receipt) and document.get("schema") == "scar.source-entry-publication"
          and type(version) is int and version in (2, 3)
          and all(document.get(key) is value for key, value in _ENTRY_AUTHORITY.items()),
          "schema2 publication root/canonical receipt/authority differs")
    rows = document["bodies"]
    requests = tuple({"entry_key": row["entry_key"], "source_program": row["source_program"]} for row in rows)
    plan = plan_source_entry_publication(target, catalog, requests, max_programs=max_programs,
                                        publication_version=version)
    _need(plan.document == document["plan"] and plan.sha256 == document["plan_sha256"]
          and all(document.get(key) == value for key, value in
                  _entry_parent2(target, catalog, publication_version=version).items()),
          "schema2 parent/plan/source/CAS differs")
    checked = []
    for row, expected in zip(rows, plan.document["expectations"]):
        _need(all(row.get(key) == value for key, value in expected.items()) and row["construction_operations"] is None,
              "schema2 qualified expectation differs")
        entry, program, body, signature = _entry_program(catalog,
            {"entry_key": row["entry_key"], "source_program": row["source_program"]},
            max_operations, max_record_bytes, publication_version=version)
        _entry2_abi(expected, program)
        checkpoint, actual = _read_receipt(row["checkpoint"]["uri"], limit=max_record_bytes)
        _need(all(actual[name] == row["checkpoint"][name] for name in actual)
              and _entry_canonical(checkpoint, actual) and checkpoint == _entry2_checkpoint(entry, program, expected)
              and row["signature"] == encode(signature) and row["root"] == encode(body.graph.root)
              and row["admissions"] == _entry_admissions(catalog, entry, body)
              and row["program_graph_sha256"] == sha256(_canonical(json.loads(dump_graph(program.graph)))).hexdigest(),
              "schema2 original checkpoint/program/signature/admission differs")
        checked.append({"record": deepcopy(row), "body": body,
                        "program": _entry_body_cache(program, compact_body_cache), "entry": entry})
    return document, receipt, tuple(checked)


def publish_source_programs(base_composition, source_program_paths, out_dir, *, code_witnesses,
                            max_programs=128, max_changed_sources=64, max_operations_per_body=10000,
                            max_record_bytes=128_000_000, progress=None):
    """Historical add-only entry; an existing canonical graph still rejects."""
    return _publish_source_programs(base_composition, source_program_paths, out_dir,
        code_witnesses=code_witnesses, max_programs=max_programs, max_changed_sources=max_changed_sources,
        max_operations_per_body=max_operations_per_body, max_record_bytes=max_record_bytes, progress=progress)


def _publish_source_programs(base_composition, source_program_paths, out_dir, *, code_witnesses,
                            max_programs=128, max_changed_sources=64, max_operations_per_body=10000,
                            max_record_bytes=128_000_000, progress=None, revision_plan=None):
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
    revision_mode = revision_plan is not None
    expected = ({(row["file_index"], row["body_index"]): row for row in revision_plan.document["expectations"]}
                if revision_mode else {})
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
        # The original witness archive is the source authority.  Structure
        # verification must use those exact bytes even when the live checkout
        # has moved since this SourceProgram was produced.
        snapshot = decode(SourceSnapshot, document["metadata"]["source"])
        source_key = snapshot.path, snapshot.fingerprint
        if source_key not in texts:
            text = code_witnesses.text(snapshot)
            texts[source_key] = (text, ast.parse(text, filename=snapshot.path),
                                 _symbol_tables(text, snapshot.path))
        program = SourceProgram.read_structure(document, max_operations=max_operations_per_body,
            source_texts={snapshot.path: texts[source_key][0]})
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
        _need(len(bodies) == 1, "body is ambiguous or already has a canonical graph")
        body_index = bodies[0][0]
        key = file_index, body_index
        _need(bodies[0][1]["root"] is None or revision_mode and key in expected
              and expected[key]["operation"] == "REVISE_GRAPH", "body is ambiguous or already has a canonical graph")
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
        require_valid_structured_body(program.structured, program.graph, program.interface, program.metadata,
            semantic=program.semantic, control=program.control, language=program.language,
            source_tree=texts[source_key][1], language_options=options)
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
        if revision_mode:
            expectation = expected[key]
            accounting = base.historical_body_accounting(file_index, body_index,
                expected_parent=revision_plan.document["base_manifest_receipt"],
                expected_checkpoint=expectation["expected_checkpoint"],
                expected_namespace=expectation["expected_namespace"],
                expected_graph_sha256=expectation["expected_graph_canonical_sha256"])
            _need(not accounting["frame_present"] and (accounting["entry_profile"] is None
                  or accounting["entry_profile"] == program.profile.value),
                  "body revision requires the same supported entry ABI and no unadapted frame")
            old_counts = accounting["counts"]
            attachment_counts = bodies[0][1]["counts"]
            _need(all(attachment_counts.get(target, 0) == old_counts[source] for source, target in (
                ("core_operations", "operations"), ("core_values", "values"), ("regions", "regions"),
                ("locations", "locations"), ("ordered_uses", "ordered_uses"))),
                "parent projection differs from historical raw/core accounting")
            changed[key].update(expectation=expectation, accounting=accounting)
            changed[key]["previous_body"] = {"inventory_locator": changed[key]["previous_body"]["inventory_locator"],
                **deepcopy(accounting["field_locators"]), "namespace": accounting["namespace"]}
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
            if revision_mode:
                before, after = item["accounting"]["counts"], _program_counts(program)
                replacements[-1].update(operation=item["expectation"]["operation"],
                    expectation=deepcopy(item["expectation"]), old_accounting=item["accounting"],
                    new_counts=after, counts_delta={key: after[key] - before[key] for key in after})
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
        if revision_mode:
            updated_interfaces["bodies"] = _replace_active_refs(base, interfaces["bodies"], changed, "bound_bodies")
        else:
            updated_interfaces["bodies"] = [base.external_reference(ref) for ref in interfaces["bodies"]]
            updated_interfaces["bodies"].extend(new_refs)
        component("interfaces", updated_interfaces)
        old_structured = base_composition.inventory_component("structured")
        component("structured", _replace_active_refs(base, old_structured, changed, "structured_bodies") if revision_mode
                  else [base.external_reference(ref) for ref in old_structured] + new_refs)
        if revision_mode:
            frame_refs = [base.external_reference(ref) for ref in base_composition.inventory_component("frames")]
            _need(all(item["accounting"]["checkpoint"] not in frame_refs for item in changed.values()),
                  "body revision cannot retain an unadapted old active frame")
        component("call_source_scope", encode(CallSourceScope(tuple(admissions))))
        old_header = base_composition.inventory_component("header")
        summary = _summary_after(old_header["summary"],
            [(item["original"], item["accounting"]["counts"] if revision_mode else Counter(),
              _program_counts(item["program"])) for item in changed.values()], admissions)
        component("header", {"schema": "scar.partitioned-inventory-header", "schema_version": 2,
            "profile": "STRUCTURED_ENV_V1", "capabilities": _REVISION_CAPS if revision_mode else _ADMISSION_CAPS,
            "base_header": base.external_reference(base.manifest["components"]["header"]),
            "base_analysis_budget": old_header.get("budget", old_header.get("base_analysis_budget")),
            "publication_budget": {"max_programs": max_programs, "max_changed_sources": max_changed_sources,
                                   "max_operations_per_body": max_operations_per_body, "max_record_bytes": max_record_bytes},
            "summary": summary, "target_executed": False, "transformation_authorized": False})
        publication = {"schema": "scar.source-program-publication", "schema_version": 2 if revision_mode else 1,
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
        if revision_mode:
            publication["expectations"] = deepcopy(revision_plan.document)
            publication["expectations_sha256"] = revision_plan.sha256
        component("publication", publication)
        component("producer", {"kind": "SOURCE_PROGRAM5_ADMISSION", "modules": original_modules,
            "base_producer": base.external_reference(base.manifest["components"]["producer"])})
        component("inputs", {"base_inventory": deepcopy(base_composition.document["inventory"]),
            "base_inputs": base.external_reference(base.manifest["components"]["inputs"]), "source_programs": inputs})
        counts = deepcopy(base.manifest["counts"])
        counts["graph_bodies"] += sum(1 - item["accounting"]["counts"]["graph_bodies"] for item in changed.values()) if revision_mode else len(changed)
        counts["checkpoint_returns"] += sum(item["original"]["checkpoint"] is None for item in changed.values())
        counts["not_attempted_bodies"] -= sum(item["original"]["status"] == "NOT_ATTEMPTED" for item in changed.values())
        manifest = {"schema": "scar.partitioned-program-inventory", "schema_version": 2,
            "capabilities": _REVISION_CAPS if revision_mode else _ADMISSION_CAPS,
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


__all__ = ["publish_source_programs", "SourceBodyPublicationPlan", "plan_source_body_publication",
           "publish_source_body_revisions", "validate_body_revision_publication"]
