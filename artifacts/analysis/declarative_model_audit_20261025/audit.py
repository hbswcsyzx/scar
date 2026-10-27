"""Read source declarations only; never import SCAR, execute targets or read raw archives."""
import ast
import hashlib
import json
from collections import defaultdict
from pathlib import Path

ROOT = Path(__file__).resolve().parents[3]
OUT = Path(__file__).resolve().parent
DOCS = ["FIRST_STAGE_MODEL_CONTRACT.md", "MODEL.md", "IR_DESIGN_V2.md",
        "CORE_GRAPH_MODEL.md", "COMPOSITE_MODEL_CONNECTION.md", "GRAPH_STORAGE.md"]
NAMES = {
    "ProgramGraph", "Operation", "Use", "StateAccess", "StateLocation", "ReferenceValue",
    "DataValue", "StateVersionValue", "Region", "ResourceDefinition", "ResourceRequirement",
    "EnvironmentInterface", "FunctionEntryLayout", "StateAddressRefinement", "StoredValueWrite",
    "StoredValueRead", "ExecutionModel", "ExecutionRun", "ProcessInstance", "HostThreadInstance",
    "RegionActivation", "OperationOccurrence", "ValueOccurrence", "UseOccurrence", "CallActivation",
    "ValueDenotation", "ContentRead", "SourceEndpointBridge", "EvidenceInventoryBinding",
    "WriteAssociation", "OutcomeProduction", "EstablishedProduction", "ResourceInstance",
    "ResourceRealization", "RequirementBinding", "HandleBinding", "ResourceAccessBinding",
    "WorkSubmission", "ResourceOutcome", "WorkQuiescence", "WorkRetention", "EventRecord",
    "QueueWait", "ObjectInstance", "LogicalValue", "ValueVersion", "ProvenanceRecord",
    "StorageAllocation", "StorageRegion", "Materialization", "ObjectBinding", "AnalysisScope",
    "CoverageObligation", "ObservationRequirement", "ObservationRoot", "ContractDefinition",
}

# Audit categories, never new execution entities. A reference names the original
# dataclass declaration; its fields are resolved from the source-only catalog.
ENTITIES = [
    ("code_identity", "AUTO_PARTIAL", ["program/source.py:OperationSource", "program/source.py:ValueSource", "program/source.py:UseSource", "v2/common.py:SourceReference", "v2/semantic.py:OperationDefinition"],
     ["scar/ir/ids.py:CodeID.from_code", "scar/analysis/program_lowering.py:prepare_source"],
     "Loaded code, source snapshot and core definitions require exact correspondence; source code_id is not universally the loaded marshal SHA."),
    ("operation_definition", "AUTO_PARTIAL", ["program/model.py:Operation", "program/model.py:Use"],
     ["scar/analysis/program_lowering.py:_Builder", "scar/analysis/structured_lowering.py:StructuredBuilder", "scar/analysis/source_heap_lowering.py:store_heap_target"],
     "Supported source profiles generate canonical operations; opaque effects and unsupported constructs remain gaps."),
    ("value_definition", "AUTO_PARTIAL", ["program/model.py:DataValue", "program/model.py:ReferenceValue", "program/model.py:StateVersionValue", "program/model.py:LocalBindingValue", "program/model.py:ProtocolValue", "program/model.py:OperationResult", "program/model.py:BlockArgument"],
     ["scar/analysis/program_lowering.py:_Builder", "scar/ir/program/validation.py:validate"],
     "Operation.results and value.origin are mutually checked endpoints of one canonical definition; UseIDs remain distinct."),
    ("state_location_and_address", "AUTO_PARTIAL", ["program/model.py:StateLocation", "program/model.py:StateAccess", "program/state_addresses.py:StateAddressRefinement", "program/state_addresses.py:AddressEffect"],
     ["scar/analysis/environment_lowering.py:StructuredEnvironmentBuilder._addresses", "scar/analysis/source_heap_lowering.py:store_heap_target"],
     "Actual owner/selector/alias/state-domain identity is not implied by coarse world IDs or PARTIAL refinements."),
    ("region_and_control", "AUTO_PARTIAL", ["program/model.py:Region", "program/model.py:Block", "program/model.py:Terminator", "program/model.py:Successor", "program/model.py:CompletionSuccessor"],
     ["scar/analysis/structured_lowering.py:StructuredBuilder.make_graph", "scar/analysis/program_composition.py:CompositionIndex"],
     "Containment is distinct from call references, path execution and ordered data transfer."),
    ("resource_definition_requirement", "SUPPLIED", ["program/resources.py:ResourceDefinition", "program/resources.py:ResourceRequirement", "program/resources.py:ResourceUse", "program/resources.py:ResourceLocation"],
     ["scar/ir/program/resource_validation.py:resource_errors", "scar/store/graph_index.py:_index_body"],
     "Legacy v2 ResourceRequirement(ResourceID, selector) is not this canonical ResourceRequirementID or a dynamic resource instance."),
    ("run_process_thread", "AUTO_PARTIAL", ["execution/coordinates.py:ExecutionRun", "execution/coordinates.py:ProcessInstance", "execution/coordinates.py:HostThreadInstance"],
     ["scar/trace/capture_coordinates.py", "scar/trace/os_resources.py:import_os_resources"],
     "IDs distinguish incarnations; generic parent/start/end are not fields of these three records."),
    ("activation_invocation", "AUTO_PARTIAL", ["execution/coordinates.py:RegionActivation", "execution/coordinates.py:ExecutionSegment", "execution/coordinates.py:BlockVisit", "execution/calls.py:CallActivation"],
     ["scar/trace/native_protocol.py:_build_execution", "scar/analysis/source_invocations.py"],
     "Python InvocationKey association is not automatically a CallActivation; cross-body actual/formal/return remains open."),
    ("operation_value_use_occurrence", "AUTO_PARTIAL", ["execution/coordinates.py:OperationOccurrence", "execution/coordinates.py:ValueOccurrence", "execution/coordinates.py:UseOccurrence", "execution/coordinates.py:ControlTransfer", "execution/model.py:OccurrenceEvidenceBinding"],
     ["scar/trace/native_protocol.py:_build_execution", "scar/ir/execution/validation.py:_coordinates"],
     "Bounded native automatic producer exists; full source operation occurrences and all actual uses do not follow from frame entry alone."),
    ("object_identity", "AUTO_PARTIAL", ["v2/values.py:ObjectInstance", "v2/values.py:ObjectBinding", "execution/content.py:ObjectIdentity", "execution/content.py:ObjectRef"],
     ["scar/trace/reference_import.py", "scar/trace/dispatch_import.py", "scar/trace/native_protocol.py:_build_execution"],
     "An object can have no known content version; first/last observation is not allocation/free."),
    ("function_environment", "AUTO_PARTIAL", ["program/environments.py:EnvironmentInterface", "program/environments.py:EnvironmentMember", "program/environments.py:FunctionEntryLayout"],
     ["scar/analysis/environment_lowering.py:StructuredEnvironmentBuilder", "scar/analysis/callable_environment_import.py"],
     "Original reference ports are populated conditionally; defaults snapshots are not entry bindings or immutable cell contents."),
    ("logical_content_version_provenance", "AUTO_PARTIAL", ["v2/values.py:LogicalValue", "v2/values.py:ValueVersion", "v2/values.py:ProvenanceRecord"],
     ["scar/ir/provenance.py:ProvenanceRegistry", "scar/trace/normalize_v2.py:_Normalizer.snapshot"],
     "Opt-in registry and provisional legacy snapshots exist; native actual content lineage is not automatically reconstructed."),
    ("allocation_view_geometry", "AUTO_PARTIAL", ["v2/values.py:StorageAllocation", "v2/values.py:StorageRegion", "execution/resources.py:AllocationPlacement"],
     ["scar/trace/native_memory.py:append_memory_events", "scar/trace/tensor_physical_import.py:import_tensor_physical", "scar/trace/native_protocol.py:_project"],
     "Reuse original epoch/region identity; pointer or overlap is not content identity; CUDA allocation claim remains provider-qualified."),
    ("materialization", "SUPPLIED", ["v2/values.py:Materialization", "execution/work.py:MaterializationRef"],
     ["scar/ir/provenance.py:ProvenanceRegistry", "scar/trace/normalize_v2.py:_Normalizer.snapshot"],
     "Native whole-capture materialization/validity/readiness producer remains open; old ready_event string is insufficient for typed order proof."),
    ("content_denotation_read", "AUTO_PARTIAL", ["execution/content.py:ValueDenotation", "execution/content.py:DataIdentity", "execution/content.py:VersionRef", "execution/content.py:ContentRead"],
     ["scar/trace/native_protocol.py:_build_execution", "scar/ir/execution/content_validation.py:content_errors"],
     "Native window writes ObjectIdentity denotations only; DataValue must denote DataIdentity, ReferenceValue must denote ObjectIdentity."),
    ("stored_payload_and_production", "SUPPLIED", ["program/stored_values.py:StoredValueWrite", "program/stored_values.py:StoredValueRead", "execution/production.py:SourceEndpointBridge", "execution/production.py:WriteAssociation", "execution/production.py:OutcomeProduction", "execution/validity.py:EstablishedProduction"],
     ["scar/ir/program/stored_values.py:stored_value_errors", "scar/ir/execution/production_validation.py"],
     "Attachments reference canonical sites/Use/results; no second heap or independent producer graph. No full native automatic production chain."),
    ("resource_instance_handle_access", "AUTO_PARTIAL", ["execution/resources.py:ResourceInstance", "execution/resources.py:ResourceRealization", "execution/resources.py:RequirementBinding", "execution/resources.py:HandleBinding", "execution/resources.py:ResourceAccessBinding", "execution/resources.py:ProviderResourceAccess"],
     ["scar/trace/os_resources.py:import_os_resources", "scar/trace/os_fd_table_contexts.py"],
     "OS fragment has actual resources/handle observations and explicit unresolved continuity; canonical requirement/executor linkage is not complete."),
    ("resource_work_outcome_lifetime", "AUTO_PARTIAL", ["execution/work.py:WorkSubmission", "execution/work.py:ResourceOutcome", "execution/work.py:WorkQuiescence", "execution/work.py:WorkRetention"],
     ["scar/trace/os_resources.py:OSResourceFragment.iter_work_records", "scar/ir/execution/work_validation.py"],
     "OS typed work has UNKNOWN executor/dependency/effect/retention closure; syscall return is not device ready/quiescence."),
    ("queue_event_wait_order", "SUPPLIED", ["execution/work.py:QueuePrefix", "execution/order.py:QueueOrderProfile", "execution/order.py:EventRecord", "execution/order.py:QueueWait"],
     ["scar/ir/execution/order_validation.py", "scar/ir/execution/validity_order.py"],
     "No generic whole-native enqueue/ready/wait producer; timestamp adjacency and provider correlation cannot supply these edges."),
    ("evidence_contract_measurement", "AUTO_PARTIAL", ["program/providers.py:ProviderArtifact", "program/providers.py:ProviderFactReference", "program/providers.py:ProviderEnvelope", "v2/common.py:EvidenceClaim", "v2/common.py:ProofClaim", "v2/contracts.py:ContractDefinition", "v2/contracts.py:EffectSummary", "v2/contracts.py:MeasurementRecord", "execution/observations.py:ObservationRequirement", "execution/observations.py:ObservationRoot"],
     ["scar/trace/native_import.py", "scar/ir/v2/codec.py", "scar/ir/execution/composition_query.py"],
     "Fact provenance, proof status, observed roots and completeness remain separate; final required roots are not all automatically bound."),
    ("analysis_scope_coverage_obligation", "DESIGN_ONLY", ["program/inventory.py:CoverageEntry", "program/inventory.py:BodyInventory"],
     ["scar/analysis/program_inventory.py", "docs/FIRST_STAGE_MODEL_CONTRACT.md:2.1"],
     "Existing source/provider/OS frontiers are not a complete AnalysisScope ledger with obligation ID, subject, required relations, required_expansion and mandatory."),
]

RELATIONS = [
    ("canonical_producer", "value.origin <-> Operation.results", "IMPLEMENTED_VALIDATED", "scar/ir/program/validation.py:117", "No independently writable database producer table."),
    ("ordered_use", "Operation.uses[j] -> Use(value,role)", "IMPLEMENTED_VALIDATED", "scar/store/graph_index.py:ordered_uses", "Duplicate values retain distinct UseID/ordinal."),
    ("state_transition", "StateAccess.before/after + StateVersionValue.location", "AUTO_PARTIAL", "scar/ir/program/validation.py:437", "Cross-body coarse-world domain/instance correspondence is OPEN."),
    ("actual_formal_return_exception", "canonical call ports + CallActivation + UseOccurrence/ControlTransfer", "INTEGRATION_OPEN", "scar/analysis/source_invocations.py:880", "Source/operand conditional route reports do not by themselves instantiate complete calls."),
    ("object_environment_state", "EnvironmentMember.reference/locations + exact actual reference", "AUTO_PARTIAL", "scar/analysis/callable_environment_import.py:300", "Identity is not mutable contents/default argument binding."),
    ("source_occurrence", "OperationSource / qualified namespace / OccurrenceEvidenceBinding", "AUTO_PARTIAL", "scar/trace/native_protocol.py:_build_execution", "Retained ancestry is not direct Python-to-native callsite."),
    ("content_version_materialization", "ContentRead + VersionRef/MatRef + WriteAssociation/OutcomeProduction", "INTEGRATION_OPEN", "scar/ir/execution/content_validation.py:411", "Tensor reference cannot permanently denote content version; provider tokens are not content endpoints."),
    ("operation_resource_work", "ResourceAccessBinding/ProviderResourceAccess + WorkSubmission", "AUTO_PARTIAL", "scar/trace/os_resources.py:196", "Unknown executor/effects stay unknown; old SG selectors do not establish instance realization."),
    ("ready_order_lifetime", "ResourceOutcome/Quiescence + EventRecord/QueueWait + WorkRetention", "INTEGRATION_OPEN", "scar/ir/execution/work.py:152", "Host return, language completion and resource completion are distinct."),
    ("source_evidence_coverage", "ProviderEnvelope/FactReference + source/provider/OS denominators", "INTEGRATION_OPEN", "docs/FIRST_STAGE_MODEL_CONTRACT.md:2.1", "Whole mandatory ledger remains missing; OPEN cannot be removed by changing denominator."),
]


def write(name, value, compact=False):
    text = json.dumps(value, ensure_ascii=False, sort_keys=True,
                      separators=(",", ":") if compact else None,
                      indent=None if compact else 2) + "\n"
    (OUT / name).write_text(text)


def main():
    records, calls, declarations, snapshots = [], defaultdict(list), defaultdict(list), []
    for path in sorted((ROOT / "scar").rglob("*.py")):
        relative = str(path.relative_to(ROOT))
        text = path.read_text()
        tree = ast.parse(text, filename=relative)
        in_ir = any(relative.startswith(prefix) for prefix in
                    ("scar/ir/program/", "scar/ir/execution/", "scar/ir/v2/"))
        for node in ast.walk(tree):
            if isinstance(node, ast.ClassDef):
                if node.name in NAMES:
                    declarations[node.name].append({"path": relative, "line": node.lineno})
                is_record = any((isinstance(d, ast.Name) and d.id == "dataclass") or
                                (isinstance(d, ast.Call) and isinstance(d.func, ast.Name)
                                 and d.func.id == "dataclass") for d in node.decorator_list)
                if in_ir and is_record:
                    records.append({"class": node.name, "path": relative, "line": node.lineno,
                        "fields": [[n.target.id, ast.unparse(n.annotation), n.lineno]
                                   for n in node.body if isinstance(n, ast.AnnAssign)
                                   and isinstance(n.target, ast.Name)],
                        "meaning": (ast.get_docstring(node) or "").split("\n")[0]})
            elif isinstance(node, ast.Call):
                name = (node.func.id if isinstance(node.func, ast.Name) else
                        node.func.attr if isinstance(node.func, ast.Attribute) else "")
                if name in NAMES:
                    calls[name].append({"path": relative, "line": node.lineno})
        if in_ir or relative.startswith(("scar/store/", "scar/analysis/", "scar/trace/")) or relative == "scar/cli.py":
            snapshots.append({"path": relative, "sha256": hashlib.sha256(text.encode()).hexdigest(),
                              "bytes": len(text.encode())})
    documents = []
    for name in DOCS:
        path = ROOT / "docs" / name
        raw = path.read_bytes()
        documents.append({"path": "docs/" + name, "sha256": hashlib.sha256(raw).hexdigest(),
                          "bytes": len(raw), "lines": len(raw.splitlines())})
    write("typed_records.json", {"schema": "scar.audit.source-record-catalog", "schema_version": 1,
        "scope": "all dataclass declarations in program/execution/v2; includes query results and codec compatibility records, not just graph entities",
        "record_count": len(records), "records": records}, compact=True)
    write("constructor_sites.json", {"schema": "scar.audit.constructor-sites", "schema_version": 1,
        "scope": "AST Name/Attribute calls in scar/**/*.py; excludes tests and artifacts",
        "limitation": "Syntactic constructor candidates; codecs/imports/aliases/replace may construct indirectly. Absence is not proof that no producer is possible.",
        "declarations": dict(declarations), "calls": dict(calls),
        "queried_names_without_direct_calls": sorted(NAMES - set(calls))})
    write("source_receipts.json", {"schema": "scar.audit.source-receipts", "schema_version": 1,
        "documents": documents, "code": snapshots,
        "target_executions": 0, "raw_archive_reads": 0, "tests_run": 0,
        "verification": "stdlib AST parsing and source SHA256; no imports, generated IR or archive semantics are certified"})
    by_key = {row["path"].removeprefix("scar/ir/") + ":" + row["class"]: row for row in records}
    entity_rows = []
    for name, status, refs, paths, boundary in ENTITIES:
        resolved = [{"path": by_key[ref]["path"], "class": by_key[ref]["class"],
                     "line": by_key[ref]["line"], "field_names": [f[0] for f in by_key[ref]["fields"]]}
                    for ref in refs]
        entity_rows.append({"category": name, "status": status, "original_records": resolved,
                            "production_or_validation_paths": paths, "boundary": boundary})
    write("audit.json", {"schema": "scar.audit.declarative-model", "schema_version": 1,
        "date": "2026-10-25", "authority": "docs/FIRST_STAGE_MODEL_CONTRACT.md",
        "document": "docs/DECLARATIVE_MODEL_AUDIT.md", "whole_first_stage_status": "OPEN",
        "audit_is_new_program_ir": False, "database_authority": "REBUILDABLE_INDEX_ONLY",
        "new_dsl_required": False, "entities": entity_rows,
        "relations": [{"category": n, "original_endpoints": e, "status": s,
                       "verification_path": p, "boundary": b} for n, e, s, p, b in RELATIONS],
        "formats": [
            {"schema": "scar.program-graph", "max_version": 28, "codec": "scar/ir/program/codec.py", "selection": "populated capabilities, preserving old profiles"},
            {"schema": "scar.execution-model", "max_version": 9, "codec": "scar/ir/execution/codec.py", "selection": "populated capabilities; exact single ProgramSnapshot"},
            {"schema": "scar.ir.v2.semantic", "versions": [2], "codec": "scar/ir/v2/codec.py:semantic_from_dict"},
            {"schema": "scar.ir.v2.values", "versions": [1, 2], "codec": "scar/ir/v2/codec.py:values_from_dict"},
            {"schema": "scar.ir.v2.evidence", "versions": [3, 4, 5, 6], "codec": "scar/ir/v2/codec.py:evidence_from_dict"},
            {"schema": "scar.ir.v2.correspondence", "versions": [1], "codec": "scar/ir/v2/codec.py:correspondence_from_dict"},
            {"schema": "scar.ir.v2.bundle", "versions": [1, 2], "codec": "scar/ir/v2/codec.py:bundle_from_dict"},
            {"schema": "scar.source-program", "versions": [1, 2, 3, 4, 5], "codec": "scar/analysis/program_lowering.py:SourceProgram"},
            {"schema": "scar.partitioned-program-inventory", "versions": [1, 2], "codec": "scar/analysis/inventory_partitions.py:InventoryPartitions"},
            {"schema": "scar.partitioned-ir-bundle", "versions": [1], "codec": "scar/store/bundle_partitions.py:BundlePartitions", "semantic_reader_revalidation": False},
            {"schema": "scar.readonly-program-graph-index", "versions": [1], "codec": "scar/store/graph_index.py:GraphIndex", "authoritative_records": False},
            {"schema": "scar.partitioned-os-resource-fragment", "versions": [1], "codec": "scar/trace/os_resources.py:OSInterfacePartitions"}],
        "next_task": {
            "implementation": "Extend the existing bounded native_protocol window with exact builtin boxed scalar content at existing DataValue occurrences.",
            "source": "scar/ir/execution/native_port_protocol.py:flat_native retains original path/type/value; native_protocol._build_execution currently skips non-Tensor denotations",
            "reuse": ["DataValue", "ValueOccurrence", "ValueGraph", "ProvenanceRecord", "ValueDenotation", "DataIdentity", "VersionRef"],
            "acceptance": ["exact original slot and run/body/artifact binding", "no new canonical IDs or producer/use/state graph", "independent scalar type/content replay", "per-occurrence lineage; no equality-based merging", "public codec/validator roundtrip", "wrong run/body/ordinal/type/output rejected", "Tensor reference/content/alias/ready unknowns retained", "bounded old archive reads; target executions zero", "original mandatory whole-stage OPEN obligations retained"]},
        "verification": {"target_executions": 0, "raw_archive_reads": 0, "tests_run": 0,
                         "scope": "source and field/codec/producer inspection only"}})
    print(json.dumps({"record_count": len(records), "constructor_names": len(calls),
        "code_files_hashed": len(snapshots), "documents_hashed": len(documents)}, sort_keys=True))


if __name__ == "__main__":
    main()
