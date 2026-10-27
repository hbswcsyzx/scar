"""Generate design specifications from the proposed stub, not a SCAR producer.

Only reads this stub, named docs and SCAR source files. No imports of SCAR,
raw/artifact enumeration, target execution, semantic tests or database access.
"""
import ast
import hashlib
import json
from pathlib import Path

HERE = Path(__file__).resolve().parent
ROOT = HERE.parents[2]

def write(name, value):
    (HERE / name).write_text(json.dumps(value, ensure_ascii=False, indent=2, sort_keys=True) + "\n")

def sha(path):
    raw = path.read_bytes()
    return {"path": str(path.relative_to(ROOT)), "bytes": len(raw),
            "sha256": hashlib.sha256(raw).hexdigest()}

REVIEW_RULES = [
    ("R01_STRICT_CODEC", "exact fields, fixed union tags, reject duplicate JSON keys and unknown versions", "INVALID"),
    ("R02_REAL_LOCATOR", "resolve a real original JSON/JSONL/text/chunk position; reject invented arrays and absent-field pointers", "INVALID"),
    ("R03_PHYSICAL_DECODED", "verify original stored and decoded receipt under explicit encoding; do not guess gzip filenames", "INVALID"),
    ("R04_QUALIFIED_SUBJECT", "source/root/context or namespace+kind+original local_id plus original record; bare ID is insufficient", "INVALID"),
    ("R05_RUN_PROCESS_SCOPE", "actual relations must retain original Run/process/visit/slot scope and provider membership", "INVALID"),
    ("R06_STABLE_IDS", "derive scope/obligation IDs from immutable original anchors and stable rule keys, never status/time/order", "INVALID"),
    ("R07_ALL_REQUIRED_DOMAINS", "missing source/call/dispatch/native/OS domain creates an explicit collection obligation anchored in capture membership", "OPEN"),
    ("R08_ENUMERATION_COVERAGE", "declared, partial and enumerated inventories remain distinct from actual observation coverage", "OPEN"),
    ("R09_MEMBER_CONSERVATION", "every enumerated original member must map to all applicable obligation IDs; retain independent domain membership", "OPEN"),
    ("R10_UNENUMERATED_DEBT", "unknown count, missing members, unfinished chunks and budgets remain collection-level OPEN with exact cursor", "OPEN"),
    ("R11_FOUR_AXES", "exactly structural attribution, dependency connection, internal expansion and runtime evidence; no omitted/empty requirement-set success", "INVALID"),
    ("R12_ORIGINAL_PORTS", "requirement expansion scans every original input/result/state/completion/resource slot, preserving duplicate Uses", "OPEN"),
    ("R13_NO_DEPENDENCY_GUESS", "names, same type, same local ID, adjacent time and retained ancestors cannot establish actual data/state/native call edges", "OPEN"),
    ("R14_EXPANSION_FIXED", "SOURCE_BODY and other preselected required_expansion cannot be lowered after UNSUPPORTED or opaque effects", "OPEN"),
    ("R15_INTERFACE_CLOSURE", "interface acceptance requires ordered inputs/results, state posts, alias/escape, control/failure, resources and ready/lifetime", "OPEN"),
    ("R16_EVIDENCE_MODES", "preserve STATIC_SOURCE/ACTUAL_OBSERVATION/VERSIONED_CONTRACT/CONDITIONAL; do not promote static to observed", "OPEN"),
    ("R17_SCOPE_FIELDS", "original argv/cwd/code-env/config/input/run/process/window/provider layers must have correct sources; analysis machine values cannot repair old capture", "OPEN"),
    ("R18_OBSERVABILITY", "selection/version/loss/window/process/thread/parser prerequisites must support claimed coverage; CLOSED/zero drops alone is insufficient", "OPEN"),
    ("R19_NOT_APPLICABLE", "NOT_APPLICABLE requires exact exclusion evidence and a fixed policy rule; no observation is not exclusion", "OPEN"),
    ("R20_REVISION_DELTA", "retain additions/removals/modifications with reasons, especially mandatory, relation sets, expansion, snapshot and scope changes", "INVALID"),
    ("R21_REUSE_EXACT_GATE", "reuse accepted semantic evidence only for exact immutable artifacts, producer/dependency hashes, schema/capability, scope and requirement-set", "OPEN"),
    ("R22_QUERY_COST", "ordinary query reuses accepted evidence and local immutable snapshot caches; no full raw rescan or new owned live session per query", "OPEN"),
    ("R23_REPLAY_DISCLOSURE", "query reports REUSED_ACCEPTED, exact original gate/range, unreplayed sources and remaining conditions; caller PASS booleans are not receipts", "OPEN"),
    ("R24_INCREMENTAL_RECHECK", "new facts/ranges/policy obligations or mismatching dependencies invalidate only affected reuse and trigger necessary producer-gate checks", "OPEN"),
    ("R25_NO_GRAPH_AUTHORITY", "ledger contains requirements and reviews only; canonical facts remain in original Program/Execution/Value/Evidence graphs", "INVALID"),
    ("R26_NO_EMPTY_MANIFEST_PASS", "a published ledger or all-false summary without per-member obligations and collection debt is not automatic coverage", "OPEN"),
    ("R27_ZERO_UNKNOWN_NOT_COMPLETE", "unknown=0 with missing domain/member/count/cursor/obligation or unreviewed condition remains OPEN", "OPEN"),
    ("R28_ALL_DISPATCH_GROUPS", "full dispatch pipeline retains every original group/phase/failure/unknown operator; never select schema-known or small-prefix subset", "OPEN"),
]

PRODUCERS = [
    {"domain": "SOURCE_DEFINITIONS", "reader": "scar/analysis/inventory_partitions.py:InventoryPartitions.file",
     "origin": "actual source shard #/file/definitions/j; snapshot/context; original source definition reference when present",
     "collection": "inventory manifest #/files; fixed recursive profile over all source shards",
     "generation_now": "all retained definitions and original body status/absence; no typed body required",
     "must_retain": ["UNSUPPORTED", "NOT_ATTEMPTED", "source-only", "unexecuted definitions"],
     "reported_baseline_not_remeasured": {"source_files": 151, "body_definitions": 2217, "active_bodies": 843}},
    {"domain": "SOURCE_CONSTRUCTS", "reader": "scar/analysis/inventory_partitions.py:InventoryPartitions.file",
     "origin": "#/file/coverage/j, #/file/calls/j, #/file/implicit_invocations/j",
     "collection": "inventory manifest #/files; fixed recursive source-construct profile",
     "generation_now": "source phase/construct membership; no new operations for non-executing text"},
    {"domain": "OBSERVED_PYTHON_CALLS", "reader": "scar/analysis/source_invocations.py:published invocations and orphan-exits files",
     "origin": "exact invocation JSONL line/hash and original InvocationKey/entry/exit anchors",
     "collection": "source-invocations report #/invocations and #/orphan_exits declarations",
     "generation_now": "all original invocation rows; retain prior842 targets as prior-snapshot evidence only",
     "must_retain": ["body-linked", "source-only", "unresolved", "orphan exits"],
     "reported_baseline_not_remeasured": {"calls": 100438, "linked_report_source_snapshot": 842, "current_source_snapshot": 843}},
    {"domain": "DISPATCH_ATTEMPTS", "reader": "scar/trace/dispatch_import.py:import_dispatch_bridge",
     "origin": "dispatch-bridge schema1 #/observations/j with actual sequence/phase/source_line and upstream metadata",
     "collection": "bridge #/observations plus original #/dispatches and capture dispatch metadata",
     "generation_now": "only sequence members actually locatable in retained observations; any unproved group difference remains collection OPEN debt",
     "missing_upstream_fields": ["complete per-sequence group inventory", "all END references", "operator source per original BEGIN", "end-only/markerless group rows"],
     "required_upstream_change": "publish complete bounded DispatchInventoryEntry records in the new native-capture-batch artifact with explicit schema and original phase/operator/outcome/count receipts; only modifying the old strict dispatch report requires its schema2/capability",
     "reported_baseline_not_remeasured": {"dispatches": 39796},
     "forbidden": ["assume sequence1..N", "marker_count/2 denominator", "16-prefix completion", "drop no-schema/failed groups"]},
    {"domain": "NATIVE_ACTIVITIES", "reader": "scar/store/bundle_partitions.py:BundlePartitions.iter_records",
     "origin": "evidence.instances original chunk record; actual manifest #/graphs/evidence/tables/instances/chunks/n",
     "collection": "bundle manifest #/graphs/evidence/tables/instances",
     "generation_now": "manifest declares collection and cursor; full typed per-member obligations require streaming original derived chunks, no raw replay"},
    {"domain": "OS_INTERFACES", "reader": "scar/trace/os_resources.py:OSInterfacePartitions.iter_records",
     "origin": "observations/line_classifications/submissions/outcomes original record envelopes",
     "collection": "OS fragment manifest #/tables/<allowed-table>",
     "generation_now": "all existing derived interface rows with explicit parser/selection/canonical-effect gaps; no syscall-return-to-ready promotion"},
    {"domain": "OS_RESOURCES", "reader": "scar/trace/os_resources.py:OSInterfacePartitions.iter_records",
     "origin": "resources/handles/target_lifetime_events/processes/threads original record envelopes",
     "collection": "OS fragment manifest #/tables/<allowed-table> and independent OS/provider inventory",
     "generation_now": "exact retained resources and handles; domain completeness stays OPEN for missing inherited/stdio/shared/short-lived resources",
     "forbidden": ["existing FD bindings are the OS universe", "new owned-launch selection qualifies old filtered capture"]},
    {"domain": "PHYSICAL_OBJECTS_AND_RESOURCES", "reader": "scar/store/bundle_partitions.py:BundlePartitions.iter_records",
     "origin": "values.objects/allocations/regions original records and provider resource catalogs",
     "collection": "bundle manifest #/graphs/values/tables/<allowed-table>",
     "generation_now": "exact original identities and geometry membership; content/materialization/ready absent remain independent OPEN requirements"},
]

def main():
    stub = HERE / "proposed_api.pyi"
    tree = ast.parse(stub.read_text(), filename=str(stub))
    records, enums, aliases, signatures = [], {}, {}, []
    tagged = {"JsonRecordRef", "JsonlRecordRef", "PartitionRecordRef", "TextRangeRef",
              "SourceDefinitionSubject", "QualifiedEntitySubject", "ArtifactRecordSubject", "CollectionSubject",
              "CoverageObligation", "DenominatorInventory", "DenominatorMember", "CoverageAssessment", "ScopeRevisionDelta"}
    for node in tree.body:
        if isinstance(node, ast.ClassDef):
            if any(isinstance(base, ast.Name) and base.id == "Enum" for base in node.bases):
                enums[node.name] = [ast.literal_eval(n.value) for n in node.body
                                    if isinstance(n, ast.Assign) and isinstance(n.value, ast.Constant)]
            elif any(isinstance(d, ast.Call) and isinstance(d.func, ast.Name) and d.func.id == "dataclass"
                     for d in node.decorator_list):
                records.append({"name": node.name, "wire_tag": node.name if node.name in tagged else None,
                    "fields": [{"name": n.target.id, "type": ast.unparse(n.annotation), "required": True}
                               for n in node.body if isinstance(n, ast.AnnAssign)]})
        elif isinstance(node, ast.AnnAssign) and isinstance(node.annotation, ast.Name) and node.annotation.id == "TypeAlias":
            aliases[node.target.id] = ast.unparse(node.value)
        elif isinstance(node, ast.FunctionDef):
            signatures.append(ast.unparse(node).split("\n")[0])
    obligation = next(r for r in records if r["name"] == "CoverageObligation")
    assert {"id", "source", "subject", "required_relations", "required_expansion", "mandatory"} <= {f["name"] for f in obligation["fields"]}
    assert set(enums["Axis"]) == {"STRUCTURAL_ATTRIBUTION", "DEPENDENCY_CONNECTION", "INTERNAL_EXPANSION", "RUNTIME_EVIDENCE"}
    assert "Any" not in stub.read_text()
    write("record-schema.json", {"schema": "scar.proposed.modeling-scope-record-codec", "schema_version": 1,
        "deployment_status": "DESIGN_ONLY_NOT_IMPLEMENTED", "planned_public_schema": "scar.modeling-scope-ledger",
        "planned_public_schema_version": 1,
        "format": "exact Python type/field/union-tag specification for a future strict record_codec; not a deployed codec or an asserted JSON-Schema validator",
        "discriminator": "$ledger_record", "unknown_fields": "REJECT", "duplicate_json_keys": "REJECT",
        "records": records, "enums": enums, "aliases": aliases, "public_api": signatures,
        "existing_types": ["ProviderArtifact", "SourceDefinitionReference", "SourceReference", "RunID", "canonical Program IDs"],
        "borrowed_shapes_not_new_graph_identities": ["OriginalNamespaceArtifact", "OriginalBodyIdentity", "OriginalGraphNamespace", "QualifiedProgramReference"],
        "id_rules": {"ScopeID": "hash(profile, original qualified Run, original command artifact identity and locator)",
            "ScopeRevision": "hash(canonical AnalysisScope excluding revision itself)",
            "ObligationID": "hash(ScopeID, original qualified subject key, stable rule_key), excluding status/mandatory/expansion",
            "DenominatorID": "hash(ScopeID, independent domain, original collection identity and fixed extraction profile)"},
        "invariants": ["all fields required; optional values use explicit null", "nonempty source/rule/requirement keys",
            "nonnegative byte/count/ordinal fields; decoded and text/JSONL lines are one-based where specified",
            "exact identifier wire kind/value/wire must match original ID class",
            "four axes occur exactly once; expected requirement-key set comes from fixed policy and original port inventory",
            "OPEN/CONTRADICTED results have concrete gaps; NOT_APPLICABLE requires exclusion proof",
            "ENUMERATED is not observation completeness; unvisited cursor or missing domain blocks whole completion",
            "SATISFIED claims only count after producer gate or precise accepted-evidence reuse",
            "no execution facts, arbitrary metadata, caller PASS booleans or independent writable database authority"]})
    write("producer-map.json", {"schema": "scar.proposed.modeling-scope-producer-map", "schema_version": 1,
        "status": "PLAN_ONLY_NO_ARCHIVE_OR_RAW_READ", "domains": PRODUCERS,
        "initial_implementation_priority": ["all original SOURCE_DEFINITIONS", "all original SOURCE_CONSTRUCTS",
            "current OBSERVED_PYTHON_CALLS denominator", "current DISPATCH_ATTEMPTS denominator with exact retained members and collection debt"],
        "other_domains": "always preserve collection obligations and exact missing/unvisited gaps; do not fabricate per-member rows from summary counts",
        "mainline": "automatic whole39796 dispatch integration; scalar is one relation family, not a new repeated prefix gate"})
    write("evidence-rules.json", {"schema": "scar.proposed.modeling-scope-evidence-rules", "schema_version": 1,
        "status": "REVIEW_BEFORE_IMPLEMENTATION",
        "rules": [{"id": k, "check": c, "failure_effect": s} for k, c, s in REVIEW_RULES],
        "verification_cost_tiers": {
            "producer_gate": "full semantic audit for exact immutable inputs/producer/scope once; whole dispatch producer joins raw once",
            "ledger_publication": "membership/count/locator/axis/receipt checks; reuse exact accepted semantic gates and recheck only changed requirements",
            "ordinary_query": "local row/endpoint/receipt lookup plus immutable cache; no global raw replay or new live-owned session; disclose reuse and remaining conditions",
            "independent_audit": "explicit bounded replay mode, separately costed and scoped"},
        "aggregate_statuses": ["INVALID", "OPEN", "SATISFIED_WITHIN_SCOPE"],
        "zero_unknown_counterexample": "0 unknown plus any missing domain/member/obligation/identity/cursor/unreviewed condition must remain OPEN"})
    write("schema-changes.json", {"schema": "scar.proposed.modeling-scope-schema-changes", "schema_version": 1,
        "changes": [
            {"component": "new ledger records/strict codec/producer/query", "required": True, "scope": "non-execution acceptance records only"},
            {"component": "complete dispatch group inventory publication", "required": True,
             "scope": "new native-capture-batch artifact may publish full original group/phase/operator/outcome/frontier records with explicit schema; ledger references it directly; old bridge need not change"},
            {"component": "old dispatch import report schema2/capability", "required": False,
             "scope": "needed only if extending the old strict report itself; preserve schema1 semantics otherwise"},
            {"component": "future owned launch/run scope receipt revision", "required": True,
             "scope": "capture original cwd and code/env/input identities when available; original run.json only contains command/returncode/wall_s; old capture gaps remain OPEN"},
            {"component": "ledger bounded transport", "required": True,
             "scope": "separate ledger format or shared chunk helper; do not silently add ledger tables to the closed IRBundle partition schema"},
            {"component": "ProgramGraph/ExecutionModel/v2 canonical identity schemas", "required": False,
             "scope": "retain graph fact authority; specific missing actual facts are produced through their original public schemas"},
            {"component": "SQLite as canonical facts", "required": False,
             "scope": "forbidden; any ledger lookup database remains delete-and-rebuild derived index"}],
        "current_stage": "design only; root to select initial implementation scope after reviewing API, evidence reuse and schema boundaries"})
    sources = [
        "docs/FIRST_STAGE_MODEL_CONTRACT.md", "docs/DECLARATIVE_MODEL_AUDIT.md",
        "docs/DECLARATIVE_GRAPH_STORAGE.md", "docs/FIRST_STAGE_EXECUTION_PLAN.md", "docs/FIRST_STAGE_DELIVERY.md",
        "scar/ir/record_codec.py", "scar/ir/program/providers.py", "scar/ir/program/source_references.py",
        "scar/analysis/inventory_partitions.py", "scar/analysis/source_invocations.py", "scar/analysis/dispatch_sources.py",
        "scar/trace/capture_coordinates.py", "scar/trace/os_resources.py", "scar/trace/dispatch_import.py",
        "scar/trace/native_protocol.py", "scar/trace/os_capture_launch.py", "scar/trace/execution_evidence.py",
        "scar/store/bundle_partitions.py", "scar/cli.py"]
    write("source-receipts.json", {"schema": "scar.proposed.modeling-scope-plan-sources", "schema_version": 1,
        "sources": [sha(ROOT / p) for p in sources], "target_executions": 0, "raw_reads": 0,
        "old_archive_reads": 0, "tests_run": 0, "actual_ledger_generated": False,
        "verification": "source inspection, proposed-stub AST parsing and specification consistency only"})
    outputs = [HERE / "proposed_api.pyi", HERE / "build_specs.py", HERE / "README.md",
               ROOT / "docs/MODELING_SCOPE_LEDGER_PLAN.md", *sorted(HERE.glob("*.json"))]
    outputs = [p for p in outputs if p.name != "plan-receipt.json"]
    write("plan-receipt.json", {"schema": "scar.proposed.modeling-scope-plan-receipt", "schema_version": 1,
        "status": "DESIGN_FROZEN_NO_PRODUCTION_IMPLEMENTATION", "files": [sha(p) for p in outputs],
        "scope": "only new plan doc and plan analysis directory written; no target/raw/archive/test/git operations",
        "actual_ledger_generated": False})
    print(json.dumps({"proposed_records": len(records), "enums": len(enums), "api_functions": len(signatures),
                      "evidence_rules": len(REVIEW_RULES), "domains": len(PRODUCERS)}, sort_keys=True))

if __name__ == "__main__":
    main()
