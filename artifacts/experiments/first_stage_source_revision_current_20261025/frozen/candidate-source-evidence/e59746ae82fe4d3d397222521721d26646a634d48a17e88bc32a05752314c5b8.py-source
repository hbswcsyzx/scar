"""SQLite lookup index of existing, independently validated ProgramGraph bodies.

The checksum-bound archive owns the records. SQLite stores their qualified
identities, exact locators and explicit relation projections, never a second
editable IR. PUBLISHED describes index storage, not whole-program completeness.
"""
from __future__ import annotations

from collections import Counter, OrderedDict
from dataclasses import dataclass, fields
from hashlib import sha256
import json
import os
from pathlib import Path
import sqlite3
from urllib.parse import quote

from scar.analysis.inventory_partitions import InventoryPartitions
from scar.ir.record_codec import encode


SCHEMA = "scar.readonly-program-graph-index"
VERSION = 1
_APPLICATION_ID = 0x53434152


@dataclass(frozen=True)
class IndexBudgets:
    max_bodies: int = 100000
    max_entities: int = 5000000
    max_relations: int = 25000000
    max_facts: int = 5000000
    max_database_bytes: int = 4000000000
    max_shard_bytes: int = 128000000
    max_record_bytes: int = 65536
    batch_rows: int = 2000
    query_limit: int = 1000

    def __post_init__(self):
        if any(type(getattr(self, field.name)) is not int or getattr(self, field.name) < 1
               for field in fields(self)):
            raise ValueError("graph index budgets must be positive exact integers")
        if self.max_database_bytes < 1048576:
            raise ValueError("graph index database budget must allow at least one MiB")


class IndexBuildError(RuntimeError):
    """An incomplete index remains BUILDING and is unavailable to GraphIndex."""
    def __init__(self, message, report):
        super().__init__(message)
        self.report = report


def _json(value):
    return json.dumps(value, sort_keys=True, ensure_ascii=True,
                      separators=(",", ":"), allow_nan=False)


def _budgets(value):
    if value is None:
        return IndexBudgets()
    if type(value) is dict:
        return IndexBudgets(**value)
    if type(value) is not IndexBudgets:
        raise TypeError("budgets must be IndexBudgets or its exact keyword dictionary")
    value.__post_init__()
    return value


def _file_receipt(path):
    digest, size = sha256(), 0
    with path.open("rb") as stream:
        for piece in iter(lambda: stream.read(1048576), b""):
            digest.update(piece)
            size += len(piece)
    return {"path": str(path), "physical_sha256": digest.hexdigest(), "physical_bytes": size}


_DDL = """
CREATE TABLE snapshot (
 singleton INTEGER PRIMARY KEY CHECK(singleton=1),
 schema_name TEXT NOT NULL, schema_version INTEGER NOT NULL,
 status TEXT NOT NULL CHECK(status IN ('BUILDING','PUBLISHED')),
 manifest_uri TEXT NOT NULL, manifest_receipt TEXT NOT NULL,
 report TEXT NOT NULL
);
CREATE TABLE artifacts (
 id INTEGER PRIMARY KEY, receipt TEXT NOT NULL UNIQUE
);
CREATE TABLE namespaces (
 id INTEGER PRIMARY KEY, identity TEXT NOT NULL UNIQUE,
 artifact_id INTEGER NOT NULL REFERENCES artifacts(id),
 file_index INTEGER NOT NULL, body_index INTEGER NOT NULL,
 graph_pointer TEXT NOT NULL, graph_schema_version INTEGER NOT NULL
);
CREATE TABLE bodies (
 file_index INTEGER NOT NULL, body_index INTEGER NOT NULL,
 source_artifact INTEGER NOT NULL REFERENCES artifacts(id),
 pointer TEXT NOT NULL, status TEXT NOT NULL,
 namespace_id INTEGER REFERENCES namespaces(id),
 graph_present INTEGER NOT NULL, public_graph_validated INTEGER NOT NULL,
 PRIMARY KEY(file_index,body_index)
);
CREATE TABLE entities (
 id INTEGER PRIMARY KEY, namespace_id INTEGER NOT NULL REFERENCES namespaces(id),
 kind TEXT NOT NULL, local_id TEXT NOT NULL, record_type TEXT NOT NULL,
 pointer TEXT NOT NULL, wire_order INTEGER NOT NULL,
 UNIQUE(namespace_id,kind,local_id)
);
CREATE TABLE relations (
 id INTEGER PRIMARY KEY, namespace_id INTEGER NOT NULL REFERENCES namespaces(id),
 kind TEXT NOT NULL, source INTEGER NOT NULL REFERENCES entities(id),
 target INTEGER NOT NULL REFERENCES entities(id),
 ordinal_path TEXT NOT NULL, pointer TEXT NOT NULL, qualifiers TEXT NOT NULL
);
CREATE INDEX relation_source ON relations(source,id);
CREATE INDEX relation_target ON relations(target,id);
CREATE INDEX relation_source_kind ON relations(source,kind,id);
CREATE INDEX relation_target_kind ON relations(target,kind,id);
CREATE TABLE facts (
 id INTEGER PRIMARY KEY, namespace_id INTEGER NOT NULL REFERENCES namespaces(id),
 owner INTEGER REFERENCES entities(id), kind TEXT NOT NULL,
 pointer TEXT NOT NULL, details TEXT NOT NULL
);
CREATE INDEX fact_owner ON facts(owner,kind,id);
CREATE INDEX fact_namespace ON facts(namespace_id,kind,id);
CREATE TABLE coverage (
 field TEXT PRIMARY KEY, records INTEGER NOT NULL, bodies_nonempty INTEGER NOT NULL,
 reference_endpoints INTEGER NOT NULL,
 indexing_status TEXT NOT NULL, note TEXT NOT NULL
);
"""


_SUPPORTED_FIELDS = {
    "root": "root locator and original Region identity",
    "regions": "parent, ordered blocks, entry, arguments and operation containment; exit port locators",
    "operations": "ordered Uses/results, direct StateAccess, terminators and declared callee",
    "values": "original origin/owner, state location and explicitly possible reference targets",
    "locations": "original StateLocation identity; no storage inference",
    "ordering": "original before/after order only",
    "resources": "static definition kind/role and original creation/external origin",
    "resource_requirements": "typed owner and declared relation constraints; capacity records remain locators",
    "resource_uses": "original requirement/optional definition/handle; no runtime binding",
    "resource_locations": "original static resource ownership of StateLocation",
    "state_address_refinements": "original site/owner and explicitly typed selector Use paths; no alias inference",
}

# Reference-only coverage for selected NOT_INDEXED records. These are explicit
# field paths from their typed definitions, NOT a dataclass-ID walk. No path
# below authorizes a semantic edge, call, alias, result replacement or purity.
_REFERENCE_PATHS = {
    "binding_definitions": ("value", "payload", "previous"),
    "binding_reads": ("operation", "binding", "normal_result"),
    "environments": ("region", "code_definition", "members/*/reference", "members/*/locations/*"),
    "function_entries": ("environment", "parameters/*/slot", "parameters/*/value"),
    "control_scopes": ("region", "parent", "blocks/*"),
    "control_ports": ("scope", "block"),
    "exception_packets": ("value", "exception", "traceback"),
    "pending_completions": ("value", "port", "payload"),
    "provider_regions": ("provider", "region"),
    "provider_bindings": ("provider", "region", "target"),
    "native_boundaries": ("provider", "region", "inputs/*/port/region", "inputs/*/port/value",
                          "core_inputs/*/port/region", "core_inputs/*/port/value",
                          "outputs/*/port/region", "core_outputs/*/port/region"),
    "boundary_relations": ("left", "right", "ports/*/left/region", "ports/*/right/region"),
    "handled_context_domains": ("region", "location"),
    "cleanup_interfaces": ("scope", "protected", "entry", "pending_argument"),
    "cleanup_enters": ("operation", "cleanup", "pending", "saved_context"),
    "cleanup_resumes": ("operation", "cleanup", "pending", "context", "continuation/operation"),
    "cleanup_replacements": ("operation", "cleanup", "saved_pending", "replacement", "context", "continuation/operation"),
    "handled_context_reads": ("operation", "exception_result"),
    "resumable_bodies": ("region", "context_location"),
    "frame_context_initials": ("operation", "frame"),
    "frame_context_attaches": ("operation", "frame", "caller"),
    "frame_context_detaches": ("operation", "caller", "frame"),
    "raw_driver_requests": ("value", "operands/*"),
    "resumable_creates": ("operation", "body", "function_object", "captures/*/formal", "captures/*/source"),
    "async_request_creates": ("operation", "body", "latent"),
    "request_association_reads": ("operation", "request"),
    "driver_interfaces": ("region", "body", "receiver", "scheduler_request", "lifecycle/*"),
    "final_body_gates": ("operation", "drive"),
    "body_drives": ("operation", "instance", "scheduler_request", "session",
                    "state_inputs/*/location", "state_inputs/*/source", "resume_inputs/*/source"),
    "driver_lifecycles": ("region",),
    "body_outcome_commits": ("operation", "outcome/drive", "outcome/source", "instance"),
    "created_close_tests": ("operation", "instance", "scheduler_request", "effective_request", "session", "result"),
    "no_body_finishes": ("operation", "precondition/operation", "instance"),
    "session_updates": ("operation", "request", "body"),
    "terminal_frame_releases": ("operation", "owner"),
    "protocol_operations": ("scope", "operation"),
    "protocol_call_inputs": ("site/scope", "site/operation"),
    "protocol_result_consumers": ("site/scope", "site/operation"),
    "exception_matches": ("operation", "input_use", "branch", "state_sites/*/operation"),
    "call_effect_expansions": ("operation", "callee"),
    "stored_value_writes": ("site/operation", "payload", "completion/operation"),
    "stored_value_reads": ("site/operation",),
}


def _declared_path(record, path, pointer):
    """Project one whitelisted typed field; optional values add no endpoint."""
    if record is None:
        return
    if not path:
        yield pointer, record
    elif path[0] == "*":
        if type(record) is not tuple:
            raise ValueError("reference whitelist expected an original typed tuple")
        for ordinal, item in enumerate(record):
            yield from _declared_path(item, path[1:], pointer + f"/{ordinal}")
    else:
        yield from _declared_path(getattr(record, path[0]), path[1:], pointer + "/" + path[0])


class _Writer:
    _INSERTS = {
        "entities": "INSERT INTO entities VALUES(?,?,?,?,?,?,?)",
        "relations": "INSERT INTO relations VALUES(?,?,?,?,?,?,?,?)",
        "facts": "INSERT INTO facts VALUES(?,?,?,?,?,?)",
    }

    def __init__(self, path, reader, budgets, manifest_path):
        self.path, self.reader, self.budgets = path, reader, budgets
        fd = os.open(path, os.O_WRONLY | os.O_CREAT | os.O_EXCL, 0o600)
        os.close(fd)
        self.db = sqlite3.connect(str(path))
        self.db.execute("PRAGMA foreign_keys=ON")
        self.db.execute("PRAGMA journal_mode=DELETE")
        self.db.execute("PRAGMA synchronous=FULL")
        self.db.execute("PRAGMA page_size=4096")
        self.db.execute(f"PRAGMA max_page_count={budgets.max_database_bytes // 4096}")
        self.db.execute(f"PRAGMA application_id={_APPLICATION_ID}")
        self.db.execute(f"PRAGMA user_version={VERSION}")
        self.db.executescript(_DDL)
        self.counts = Counter()
        self.relation_counts, self.coverage = Counter(), {}
        self.coverage_references = Counter()
        self.pending, self.artifacts = [], {}
        self.report = {"schema": SCHEMA, "schema_version": VERSION,
            "status": "BUILDING", "manifest_uri": str(manifest_path),
            "manifest_receipt": reader.manifest_receipt,
            "budgets": {field.name: getattr(budgets, field.name) for field in fields(budgets)},
            "publication_meaning": "index construction completed; not ProgramModel completeness",
            "whole_program_graph_established": False, "all_relationships_indexed": False,
            "source_replay_performed": False, "target_executed": False,
            "transformation_authorized": False}
        self.db.execute("INSERT INTO snapshot VALUES(1,?,?,?,?,?,?)",
            (SCHEMA, VERSION, "BUILDING", self.report["manifest_uri"],
             _json(reader.manifest_receipt), _json(self.report)))
        self.db.commit()

    def text(self, value):
        result = _json(value)
        if len(result.encode("utf-8")) > self.budgets.max_record_bytes:
            raise ValueError("index scalar/locator record byte budget exceeded")
        return result

    def add(self, table, row):
        self.pending.append((table, row))
        if len(self.pending) >= self.budgets.batch_rows:
            self.flush()

    def flush(self):
        if not self.pending:
            return
        # Explicit IDs preserve original order independently of insertion
        # grouping. Insert all entities before FK-referencing projections.
        grouped = {name: [] for name in self._INSERTS}
        for table, row in self.pending:
            grouped[table].append(row)
        for table, rows in grouped.items():
            if rows:
                self.db.executemany(self._INSERTS[table], rows)
        self.db.commit()
        self.pending.clear()

    def artifact(self, ref):
        receipt = self.text(ref)
        if receipt not in self.artifacts:
            row = self.db.execute("INSERT INTO artifacts(receipt) VALUES(?)", (receipt,))
            self.artifacts[receipt] = row.lastrowid
        return self.artifacts[receipt]

    def start_body(self, file_index, body_index, typed, raw_file):
        self.counts["bodies"] += 1
        if self.counts["bodies"] > self.budgets.max_bodies:
            raise ValueError("body count budget exceeded")
        row = raw_file["bodies"][body_index]
        if row["checkpoint"] is not None:
            self.counts["checkpoint_returns"] += 1
        source_artifact = self.artifact(self.reader.manifest["files"][file_index])
        namespace_id = None
        if typed.body.graph is not None:
            ref = row["checkpoint"]
            if ref is None or typed.public_graph_validated is not True or typed.namespace is None:
                raise ValueError("indexed graph lacks its original public codec validation/namespace")
            if (ref.get("graph_pointer") != "#/graph"
                    or ref.get("body_identity", {}).get("definition") != encode(typed.body.definition)
                    or ref["body_identity"].get("entry") != typed.body.metadata.entry
                    or ref["body_identity"].get("source") != (
                        encode(typed.structured.source) if typed.structured is not None else None)):
                raise ValueError("body namespace/pointer does not match its original canonical return")
            checkpoint = self.reader.checkpoint(ref)
            version = checkpoint["graph"]["schema_version"]
            artifact = self.artifact(ref)
            result = self.db.execute("INSERT INTO namespaces(identity,artifact_id,file_index,body_index,graph_pointer,graph_schema_version) VALUES(?,?,?,?,?,?)",
                (self.text(typed.namespace), artifact, file_index, body_index,
                 ref["graph_pointer"], version))
            namespace_id = result.lastrowid
            self.counts["graph_bodies"] += 1
        else:
            self.counts["bodies_without_graph"] += 1
        self.db.execute("INSERT INTO bodies VALUES(?,?,?,?,?,?,?,?)",
            (file_index, body_index, source_artifact, f"#/file/bodies/{body_index}",
             typed.body.status.value, namespace_id, int(typed.body.graph is not None),
             int(typed.public_graph_validated)))
        self.counts[f"body_status:{typed.body.status.value}"] += 1
        return namespace_id

    def entity(self, ns, kind, identity, record_type, pointer, local):
        encoded = self.text(encode(identity))
        key = (kind, encoded)
        if key in local:
            raise ValueError("duplicate original entity in the same qualified namespace")
        self.counts["entities"] += 1
        if self.counts["entities"] > self.budgets.max_entities:
            raise ValueError("entity count budget exceeded")
        entity_id = self.counts["entities"]
        local[key] = entity_id
        self.add("entities", (entity_id, ns, kind, encoded, record_type, pointer, entity_id))
        self.counts[f"entity:{kind}"] += 1
        return entity_id

    def endpoint(self, local, kind, identity):
        try:
            return local[(kind, self.text(encode(identity)))]
        except KeyError as error:
            raise ValueError(f"relation endpoint is not an original {kind} in this body") from error

    def relation(self, ns, kind, source, target, pointer, ordinal=(), **qualifiers):
        self.counts["relations"] += 1
        if self.counts["relations"] > self.budgets.max_relations:
            raise ValueError("relation count budget exceeded")
        self.add("relations", (self.counts["relations"], ns, kind, source, target,
            self.text(list(ordinal)), pointer, self.text(qualifiers)))
        self.relation_counts[kind] += 1

    def fact(self, ns, owner, kind, pointer, **details):
        self.counts["facts"] += 1
        if self.counts["facts"] > self.budgets.max_facts:
            raise ValueError("locator fact count budget exceeded")
        self.add("facts", (self.counts["facts"], ns, owner, kind, pointer, self.text(details)))

    def record_coverage(self, ns, graph, local):
        from scar.ir.program.ids import (BlockID, LocationID, OperationID, RegionID,
            ResourceDefinitionID, ResourceRequirementID, UseID, ValueID)
        from scar.ir.v2.ids import Identifier
        indexed_kinds = {BlockID: "Block", LocationID: "StateLocation", OperationID: "Operation",
            RegionID: "Region", ResourceDefinitionID: "ResourceDefinition",
            ResourceRequirementID: "ResourceRequirement", UseID: "Use", ValueID: "Value"}
        for field in fields(type(graph)):
            value = getattr(graph, field.name)
            count = len(value) if type(value) is tuple else 1
            summary = self.coverage.setdefault(field.name, [0, 0])
            summary[0] += count
            summary[1] += int(count > 0)
            if field.name not in _SUPPORTED_FIELDS:
                # This enumerates declared top-level record collections for
                # coverage only. It does NOT scan IDs or invent semantic edges.
                for ordinal, record in enumerate(value):
                    self.fact(ns, None, "NOT_INDEXED_RECORD",
                        f"#/graph/{field.name}/{ordinal}", field=field.name,
                        record_type=type(record).__name__,
                        endpoint_mapping="PARTIAL_EXPLICIT_FIELD_WHITELIST; semantic relations NOT_INDEXED",
                        reference_fields=list(_REFERENCE_PATHS.get(field.name, ())))
                    for recipe in _REFERENCE_PATHS.get(field.name, ()):
                        for pointer, endpoint in _declared_path(record, recipe.split("/"),
                                f"#/graph/{field.name}/{ordinal}"):
                            if not isinstance(endpoint, Identifier):
                                raise ValueError("explicit reference field is not a typed identifier")
                            kind = indexed_kinds.get(type(endpoint))
                            located = kind is not None and (kind, self.text(encode(endpoint))) in local
                            self.fact(ns, None, "NOT_INDEXED_REFERENCE", pointer,
                                field=field.name, record_ordinal=ordinal,
                                endpoint_type=type(endpoint).__name__, local_id=encode(endpoint),
                                indexed_kind=kind if located else None,
                                qualification="CANONICAL_ENDPOINT_LOCATED" if located else "DECLARED_REFERENCE_ONLY",
                                semantic_relationship="NOT_INDEXED")
                            self.counts["unindexed_endpoint_references"] += 1
                            self.coverage_references[field.name] += 1

    def finish(self):
        self.flush()
        manifest_counts = self.reader.manifest["counts"]
        denominators = {"source_files": self.counts["source_files"],
            "checkpoint_returns": self.counts["checkpoint_returns"],
            "graph_bodies": self.counts["graph_bodies"],
            "not_attempted_bodies": self.counts["body_status:NOT_ATTEMPTED"]}
        if any(type(manifest_counts.get(name)) is not int or manifest_counts[name] != value
               for name, value in denominators.items()):
            raise ValueError("indexed source/body denominators do not match the original manifest")
        for field, (records, bodies) in self.coverage.items():
            indexed = field in _SUPPORTED_FIELDS
            self.db.execute("INSERT INTO coverage VALUES(?,?,?,?,?,?)", (field, records, bodies,
                self.coverage_references[field],
                "EXPLICIT_PROJECTION" if indexed else "NOT_INDEXED",
                _SUPPORTED_FIELDS.get(field, "original record locators and partial explicit reference endpoints retained; semantic relationships not indexed")))
        if self.db.execute("PRAGMA foreign_key_check").fetchone() is not None:
            raise ValueError("index relation/locator endpoint foreign-key validation failed")
        self.report.update(status="PUBLISHED", counts=dict(self.counts),
            relation_counts=dict(self.relation_counts),
            coverage={name: {"records": value[0], "bodies_nonempty": value[1],
                "declared_reference_endpoints": self.coverage_references[name],
                "indexing_status": "EXPLICIT_PROJECTION" if name in _SUPPORTED_FIELDS else "NOT_INDEXED"}
                for name, value in self.coverage.items()},
            unindexed_scopes=["global inventory components and source-call candidates",
                "cross-body composition and dynamic call correspondence",
                "alias/materialization/lifetime/ready inference",
                "extension record relations listed NOT_INDEXED in coverage"],
            public_graph_validation="InventoryPartitions.typed_body -> public ProgramGraph codec",
            source_overlay_validation=False)
        self.db.execute("UPDATE snapshot SET status='PUBLISHED',report=? WHERE singleton=1 AND status='BUILDING'",
                        (self.text(self.report),))
        self.db.commit()
        self.db.close()
        return {**self.report, "database": _file_receipt(self.path)}

    def failed(self, error):
        self.pending.clear()
        self.db.rollback()
        self.report.update(status="BUILDING", counts=dict(self.counts),
            counts_scope="attempted before failure; may include the rolled-back final batch",
            error={"type": type(error).__name__, "message": str(error)[:1024]})
        try:
            self.db.execute("UPDATE snapshot SET report=? WHERE singleton=1 AND status='BUILDING'",
                            (self.text(self.report),))
            self.db.commit()
        except (sqlite3.Error, ValueError):
            self.db.rollback()
        finally:
            self.db.close()
        return {**self.report, "database_path": str(self.path)}


def _index_body(writer, ns, graph):
    from scar.ir.program.model import BlockArgument, OperationResult, StateVersionValue, ReferenceValue
    from scar.ir.program.resources import CreatedResource, ExternalResource
    from scar.ir.program.ids import OperationID
    local, blocks = {}, {}
    for i, region in enumerate(graph.regions):
        writer.entity(ns, "Region", region.id, type(region).__name__, f"#/graph/regions/{i}", local)
        for j, block in enumerate(region.blocks):
            writer.entity(ns, "Block", block.id, type(block).__name__,
                          f"#/graph/regions/{i}/blocks/{j}", local)
            blocks[block.id] = block
    for i, operation in enumerate(graph.operations):
        writer.entity(ns, "Operation", operation.id, type(operation).__name__,
                      f"#/graph/operations/{i}", local)
        for j, use in enumerate(operation.uses):
            writer.entity(ns, "Use", use.id, type(use).__name__,
                          f"#/graph/operations/{i}/uses/{j}", local)
    for field, kind in (("values", "Value"), ("locations", "StateLocation"),
                        ("resources", "ResourceDefinition"),
                        ("resource_requirements", "ResourceRequirement")):
        for i, record in enumerate(getattr(graph, field)):
            writer.entity(ns, kind, record.id, type(record).__name__, f"#/graph/{field}/{i}", local)
    writer.flush()
    get = lambda kind, identity: writer.endpoint(local, kind, identity)
    root = get("Region", graph.root)
    writer.fact(ns, root, "GRAPH_ROOT", "#/graph/root")
    for i, region in enumerate(graph.regions):
        pointer, owner = f"#/graph/regions/{i}", get("Region", region.id)
        if region.parent is not None:
            writer.relation(ns, "REGION_CHILD", get("Region", region.parent), owner, pointer + "/parent", (i,))
        writer.relation(ns, "REGION_ENTRY", owner, get("Block", region.entry), pointer + "/entry")
        for j, block in enumerate(region.blocks):
            block_pointer, block_id = pointer + f"/blocks/{j}", get("Block", block.id)
            writer.relation(ns, "REGION_BLOCK", owner, block_id, block_pointer, (j,))
            for k, value in enumerate(block.arguments):
                writer.relation(ns, "BLOCK_ARGUMENT", block_id, get("Value", value),
                                block_pointer + f"/arguments/{k}", (k,))
            for k, operation in enumerate(block.operations):
                writer.relation(ns, "BLOCK_OPERATION", block_id, get("Operation", operation),
                                block_pointer + f"/operations/{k}", (k,))
        for j, port in enumerate(region.exits):
            writer.fact(ns, owner, "REGION_EXIT_PORT", pointer + f"/exits/{j}",
                        name=port.name, completion_kind=port.kind.value, arity=len(port.types))
    for i, value in enumerate(graph.values):
        pointer, target = f"#/graph/values/{i}", get("Value", value.id)
        writer.relation(ns, "REGION_VALUE", get("Region", value.region), target, pointer + "/region", (i,))
        origin = value.origin
        writer.fact(ns, target, "VALUE_ORIGIN", pointer + "/origin", origin_kind=type(origin).__name__)
        if type(origin) is OperationResult:
            writer.relation(ns, "VALUE_OPERATION_ORIGIN", get("Operation", origin.operation), target,
                            pointer + "/origin/operation", (origin.index,), result_index=origin.index)
        elif type(origin) is BlockArgument:
            writer.relation(ns, "VALUE_BLOCK_ORIGIN", get("Block", origin.block), target,
                            pointer + "/origin/block", (origin.index,), argument_index=origin.index)
        if type(value) is StateVersionValue:
            writer.relation(ns, "STATE_VERSION_LOCATION", target, get("StateLocation", value.location),
                            pointer + "/location")
        if type(value) is ReferenceValue:
            writer.fact(ns, target, "REFERENCE_TARGET_QUALIFICATION", pointer + "/targets",
                        declared_targets_unknown=value.targets is None,
                        meaning="possible static targets; not actual alias or runtime identity")
            for j, location in enumerate(value.targets or ()):
                writer.relation(ns, "DECLARED_POSSIBLE_LOCATION", target, get("StateLocation", location),
                                pointer + f"/targets/{j}", (j,), applicability="DECLARED_POSSIBLE")
    for i, operation in enumerate(graph.operations):
        pointer, owner = f"#/graph/operations/{i}", get("Operation", operation.id)
        for j, use in enumerate(operation.uses):
            use_id = get("Use", use.id)
            writer.relation(ns, "OPERATION_USE", owner, use_id, pointer + f"/uses/{j}", (j,), role=use.role.value)
            writer.relation(ns, "VALUE_USE", get("Value", use.value), use_id,
                            pointer + f"/uses/{j}/value", (i, j), role=use.role.value)
        for j, value in enumerate(operation.results):
            writer.relation(ns, "OPERATION_RESULT", owner, get("Value", value),
                            pointer + f"/results/{j}", (j,))
        for j, access in enumerate(operation.accesses):
            p = pointer + f"/accesses/{j}"
            attrs = {"access_index": j, "mode": access.mode.value,
                     "full_overwrite": access.full_overwrite}
            writer.relation(ns, "STATE_ACCESS", owner, get("StateLocation", access.location), p + "/location", (j,), **attrs)
            writer.relation(ns, "ACCESS_BEFORE_USE", owner, get("Use", access.before), p + "/before", (j,), **attrs)
            if access.after is not None:
                writer.relation(ns, "ACCESS_AFTER_VALUE", owner, get("Value", access.after), p + "/after", (j,), **attrs)
            if access.reference is not None:
                writer.relation(ns, "ACCESS_REFERENCE_USE", owner, get("Use", access.reference), p + "/reference", (j,), **attrs)
            writer.fact(ns, owner, "STATE_ACCESS", p, **attrs,
                footprint={"kind": access.footprint.kind.value,
                           "start": access.footprint.start, "stop": access.footprint.stop})
        if operation.callee is not None:
            writer.relation(ns, "DECLARED_CALLEE", owner, get("Region", operation.callee), pointer + "/callee",
                            applicability="static declaration; not observed call")
        for name in ("call_arguments", "invoke_arguments"):
            for j, use in enumerate(getattr(operation, name)):
                writer.relation(ns, name.upper(), owner, get("Use", use), pointer + f"/{name}/{j}", (j,))
        if operation.terminator is not None:
            _terminator(writer, ns, owner, operation.terminator, pointer + "/terminator",
                        get, blocks)
    for i, order in enumerate(graph.ordering):
        writer.relation(ns, "EXPLICIT_ORDER", get("Operation", order.before), get("Operation", order.after),
                        f"#/graph/ordering/{i}", (i,))
    for i, resource in enumerate(graph.resources):
        pointer, target = f"#/graph/resources/{i}", get("ResourceDefinition", resource.id)
        writer.fact(ns, target, "RESOURCE_DEFINITION", pointer, resource_kind=resource.kind.value,
                    resource_role=resource.role.value, origin_kind=type(resource.origin).__name__)
        if type(resource.origin) is CreatedResource:
            writer.relation(ns, "RESOURCE_CREATED_BY", get("Operation", resource.origin.operation), target, pointer + "/origin/operation")
        elif type(resource.origin) is ExternalResource:
            writer.relation(ns, "RESOURCE_EXTERNAL_PORT", get("Region", resource.origin.region), target,
                            pointer + "/origin", port=resource.origin.port)
    for i, requirement in enumerate(graph.resource_requirements):
        pointer, target = f"#/graph/resource_requirements/{i}", get("ResourceRequirement", requirement.id)
        owner_kind = "Operation" if type(requirement.owner) is OperationID else "Region"
        writer.relation(ns, "RESOURCE_REQUIREMENT_OWNER", get(owner_kind, requirement.owner), target,
                        pointer + "/owner", resource_kind=requirement.kind.value, resource_role=requirement.role.value)
        for j, relation in enumerate(requirement.relations):
            writer.relation(ns, "RESOURCE_REQUIREMENT_CONSTRAINT", target,
                get("ResourceRequirement", relation.other), pointer + f"/relations/{j}", (j,),
                constraint=relation.relation.value, applicability="DECLARED_CONSTRAINT")
        for j, capacity in enumerate(requirement.capacities):
            writer.fact(ns, target, "RESOURCE_CAPACITY_LOCATOR", pointer + f"/capacities/{j}",
                        metric=capacity.metric, unit=capacity.unit)
    for i, use in enumerate(graph.resource_uses):
        pointer, owner = f"#/graph/resource_uses/{i}", get("Operation", use.operation)
        attrs = {"resource_use_index": i, "applicability": "static requirement, not runtime binding"}
        writer.relation(ns, "RESOURCE_USE_REQUIREMENT", owner, get("ResourceRequirement", use.requirement),
                        pointer + "/requirement", (i,), **attrs)
        if use.definition is not None:
            writer.relation(ns, "RESOURCE_USE_DECLARED_DEFINITION", owner, get("ResourceDefinition", use.definition),
                            pointer + "/definition", (i,), **attrs)
        if use.handle is not None:
            writer.relation(ns, "RESOURCE_USE_HANDLE", owner, get("Use", use.handle), pointer + "/handle", (i,), **attrs)
    for i, location in enumerate(graph.resource_locations):
        writer.relation(ns, "RESOURCE_LOCATION_OWNER", get("StateLocation", location.location),
            get("ResourceDefinition", location.resource), f"#/graph/resource_locations/{i}", (i,))
    _state_addresses(writer, ns, graph.state_address_refinements, get)
    writer.record_coverage(ns, graph, local)
    writer.flush()


def _terminator(writer, ns, owner, term, pointer, get, blocks):
    from scar.ir.program.ids import UseID
    from scar.ir.program.model import CompletionResult
    from scar.ir.program.drivers import BodyDriveResult
    from scar.ir.program.control import PendingPayload
    from scar.ir.program.resumption import SavedInput, ResumeInput
    kind = term.kind.value
    writer.fact(ns, owner, "TERMINATOR", pointer, terminator_kind=kind,
                successor_count=len(term.successors))
    if term.condition is not None:
        writer.relation(ns, "CONTROL_CONDITION_USE", owner, get("Use", term.condition), pointer + "/condition")
    if term.exit is not None:
        writer.fact(ns, owner, "REGION_EXIT", pointer + "/exit", exit_name=term.exit, terminator_kind=kind)
    # Dedicated terminators expose values as computed properties. Their wire
    # locators must use real fields rather than a fabricated /values member.
    if kind in ("RETURN", "RAISE"):
        for j, use in enumerate(term.values):
            writer.relation(ns, "EXIT_VALUE_USE", owner, get("Use", use), pointer + f"/values/{j}", (j,), terminator_kind=kind)
    if kind in ("PENDING_DISPATCH", "CLEANUP_ROUTE"):
        writer.relation(ns, "PENDING_CONTROL_USE", owner, get("Use", term.pending), pointer + "/pending")
    if kind == "SUSPEND":
        writer.relation(ns, "SUSPEND_EXPORTED_USE", owner, get("Use", term.exported), pointer + "/exported")
        for j, saved in enumerate(term.saved):
            writer.relation(ns, "SUSPEND_SAVED_USE", owner, get("Use", saved.use), pointer + f"/saved/{j}/use", (j,), saved_role=saved.role.value)
        for j, use in enumerate(term.handoff):
            writer.relation(ns, "SUSPEND_STATE_HANDOFF_USE", owner, get("Use", use), pointer + f"/handoff/{j}", (j,))
    for edge_index, edge in enumerate(term.successors):
        p = pointer + f"/successors/{edge_index}"
        attributes = {"terminator_kind": kind, "successor_index": edge_index,
                      "applicability": "canonical static successor, not observed transition"}
        if kind == "BRANCH":
            attributes["branch_value"] = edge_index == 0
        if kind == "INVOKE":
            attributes["completion_kind"] = edge.kind.value
        if kind in ("PENDING_DISPATCH", "CLEANUP_ROUTE"):
            attributes["control_port"] = encode(edge.port)
        if kind == "SUSPEND":
            attributes["temporal_relation"] = "later resumption ingress, not immediate branch"
        if kind == "BODY_DRIVE":
            attributes["body_outcome_source"] = encode(edge.source)
            writer.relation(ns, "BODY_DRIVE_OUTCOME_SOURCE", owner, get("Operation", edge.source),
                            p + "/source", (edge_index,))
        writer.relation(ns, "TERMINATOR_SUCCESSOR", owner, get("Block", edge.block),
                        p + "/block", (edge_index,), **attributes)
        for argument_index, argument in enumerate(edge.arguments):
            destination = get("Value", blocks[edge.block].arguments[argument_index])
            a = p + f"/arguments/{argument_index}"
            attrs = {**attributes, "argument_index": argument_index}
            if type(argument) is UseID:
                writer.relation(ns, "SUCCESSOR_ARGUMENT_USE", get("Use", argument), destination,
                                a, (edge_index, argument_index), **attrs)
            elif type(argument) is CompletionResult:
                writer.relation(ns, "COMPLETION_RESULT_PROJECTION", owner, destination, a,
                    (edge_index, argument_index), **attrs, completion_result_index=argument.index)
            elif type(argument) is PendingPayload:
                writer.relation(ns, "PENDING_PAYLOAD_PROJECTION", owner, destination, a,
                                (edge_index, argument_index), **attrs)
            elif type(argument) is BodyDriveResult:
                writer.relation(ns, "BODY_DRIVE_RESULT_PROJECTION", get("Operation", edge.source), destination,
                    a, (edge_index, argument_index), **attrs, body_result_index=argument.index)
            elif type(argument) is SavedInput:
                writer.relation(ns, "SAVED_INPUT_PROJECTION", get("Use", term.saved[argument.saved_slot].use),
                    destination, a, (edge_index, argument_index), **attrs, saved_slot=argument.saved_slot)
            elif type(argument) is ResumeInput:
                slot = edge.inputs[argument.resume_slot]
                writer.relation(ns, "RESUME_INPUT_PROJECTION", owner, destination, a,
                    (edge_index, argument_index), **attrs, resume_slot=argument.resume_slot,
                    resume_kind=slot.kind.value)
            else:
                raise ValueError("canonical successor argument has no explicit projection mapping")


def _state_addresses(writer, ns, refinements, get):
    from scar.ir.program.state_addresses import (
        ExistingAccess, InvokeStateOperand, ReferenceOwner, ResourceOwner,
        UnknownOwner, NamespaceKey, DynamicField, Element, Slice, StorageRange,
        UnknownSelection, ObjectField,
    )
    for i, refinement in enumerate(refinements):
        p = f"#/graph/state_address_refinements/{i}"
        owner = get("Operation", refinement.site.operation)
        site = refinement.site
        details = {"site_kind": type(site).__name__, "coverage": refinement.coverage.value}
        if type(site) is ExistingAccess:
            details["access_index"] = site.index
        elif type(site) is InvokeStateOperand:
            writer.relation(ns, "ADDRESS_INVOKE_STATE_USE", owner, get("Use", site.state_use), p + "/site/state_use", (i,))
        writer.fact(ns, owner, "STATE_ADDRESS_REFINEMENT", p, **details)
        for j, effect in enumerate(refinement.effects):
            e = p + f"/effects/{j}"
            attrs = {"refinement_index": i, "effect_index": j,
                     "mode": effect.mode.value, "stage": effect.stage,
                     "coverage": refinement.coverage.value}
            writer.fact(ns, owner, "ADDRESS_EFFECT", e, **attrs, owner_kind=type(effect.owner).__name__)
            if type(effect.owner) is ReferenceOwner:
                writer.relation(ns, "ADDRESS_REFERENCE_OWNER_USE", owner, get("Use", effect.owner.use),
                                e + "/owner/use", (i, j), **attrs)
            elif type(effect.owner) is ResourceOwner:
                writer.relation(ns, "ADDRESS_RESOURCE_OWNER_REQUIREMENT", owner,
                    get("ResourceRequirement", effect.owner.requirement), e + "/owner/requirement", (i, j), **attrs)
            elif type(effect.owner) is UnknownOwner:
                for k, use in enumerate(effect.owner.operands):
                    writer.relation(ns, "ADDRESS_UNKNOWN_OWNER_OPERAND", owner, get("Use", use),
                                    e + f"/owner/operands/{k}", (i, j, k), **attrs)
            for k, selector in enumerate(effect.path):
                s = e + f"/path/{k}"
                detail = {**attrs, "selector_index": k, "selector_kind": type(selector).__name__}
                if type(selector) is ObjectField:
                    detail["field_name"] = selector.name
                writer.fact(ns, owner, "ADDRESS_SELECTOR", s, **detail)
                slots = []
                if type(selector) is NamespaceKey:
                    slots = [("key", selector.key)]
                elif type(selector) is DynamicField:
                    slots = [("name", selector.name)]
                elif type(selector) is Element:
                    slots = [("index", selector.index)]
                elif type(selector) is Slice:
                    slots = [(name, getattr(selector, name)) for name in ("start", "stop", "step")
                             if getattr(selector, name) is not None]
                elif type(selector) is StorageRange:
                    slots = [("start", selector.start), ("count", selector.count)]
                elif type(selector) is UnknownSelection:
                    slots = [(f"operands/{n}", use) for n, use in enumerate(selector.operands)]
                for number, (field, use) in enumerate(slots):
                    writer.relation(ns, "ADDRESS_SELECTOR_USE", owner, get("Use", use), s + "/" + field,
                                    (i, j, k, number), **detail, selector_field=field)


def index_inventory(manifest, fresh_sqlite_path, budgets=None, *, progress=None):
    """Build a disposable index of all available original body graphs.

    Uses public InventoryPartitions/ProgramGraph codec validation per body.
    No source lowering, target execution, graph mutation or optimization occurs.
    Raises IndexBuildError after a failed build; the partial DB stays BUILDING.
    Optional progress receives FILE_BEGIN/BODY_COMPLETE scalar counters; it
    does not receive graphs or application data. Callback failure aborts build.
    """
    limits = _budgets(budgets)
    if progress is not None and not callable(progress):
        raise TypeError("progress must be a callable or None")
    manifest_path = Path(manifest).resolve()
    if manifest_path.is_dir():
        manifest_path = manifest_path / "manifest.json"
    reader = InventoryPartitions(manifest_path, max_shard_bytes=limits.max_shard_bytes,
                                 cache_entries=2)
    path = Path(fresh_sqlite_path).absolute()
    if path.exists() or path.is_symlink() or not path.parent.is_dir():
        raise ValueError("index needs a fresh path in an existing output directory")
    writer = _Writer(path, reader, limits, manifest_path)
    try:
        for file_index, raw_file in enumerate(reader.iter_files()):
            writer.counts["source_files"] += 1
            if progress is not None:
                progress({"phase": "FILE_BEGIN", "file_index": file_index,
                    "body_count": len(raw_file["bodies"]),
                    "source": raw_file["snapshot"]["path"],
                    "bodies_completed": writer.counts["bodies"]})
            for body_index in range(len(raw_file["bodies"])):
                if writer.counts["bodies"] >= limits.max_bodies:
                    raise ValueError("body count budget exceeded before decoding another body")
                typed = reader.typed_body(file_index, body_index)
                ns = writer.start_body(file_index, body_index, typed, raw_file)
                if typed.body.graph is not None:
                    _index_body(writer, ns, typed.body.graph)
                if progress is not None:
                    progress({"phase": "BODY_COMPLETE", "file_index": file_index,
                        "body_index": body_index, "status": typed.body.status.value,
                        **{key: writer.counts[key] for key in ("source_files", "bodies",
                            "graph_bodies", "entities", "relations", "facts")}})
                # Per-body references, not a whole-inventory object, are live.
                del typed
        writer.flush()
        return writer.finish()
    except Exception as error:
        report = writer.failed(error)
        raise IndexBuildError("graph index was not published: " + str(error), report) from error


class GraphIndex:
    """Read-only local queries; every answer retains original namespace/receipt.

    Queries require InventoryPartitions.qualified_reference-shaped keys. Local
    IDs alone are never accepted. Edges retain static/possible/temporal meaning.
    """
    def __init__(self, snapshot):
        path = Path(snapshot).resolve(strict=True)
        if not path.is_file():
            raise ValueError("graph index snapshot is not a regular file")
        self.path = path
        self.db = sqlite3.connect("file:" + quote(str(path), safe="/") + "?mode=ro", uri=True)
        self.db.row_factory = sqlite3.Row
        try:
            self.db.execute("PRAGMA query_only=ON")
            self.db.execute("BEGIN")
            if (self.db.execute("PRAGMA application_id").fetchone()[0] != _APPLICATION_ID
                    or self.db.execute("PRAGMA user_version").fetchone()[0] != VERSION):
                raise ValueError("unsupported graph index database/schema")
            row = self.db.execute("SELECT * FROM snapshot WHERE singleton=1").fetchone()
            if (row is None or row["schema_name"] != SCHEMA or row["schema_version"] != VERSION
                    or row["status"] != "PUBLISHED"):
                raise ValueError("graph index snapshot is not PUBLISHED")
            self.snapshot = json.loads(row["report"])
            if self.snapshot.get("status") != "PUBLISHED":
                raise ValueError("graph index publication metadata is inconsistent")
            self.query_limit = self.snapshot["budgets"]["query_limit"]
            self._namespace_cache = OrderedDict()
        except Exception:
            self.db.close()
            raise

    def __enter__(self):
        return self

    def __exit__(self, *args):
        self.close()

    def close(self):
        self.db.close()

    def _key(self, reference):
        if type(reference) is not dict or set(reference) != {"namespace", "kind", "local_id"}:
            raise ValueError("query needs an exact artifact/representation/body/kind/local_id reference")
        if type(reference["namespace"]) is not dict or type(reference["kind"]) is not str:
            raise ValueError("query namespace/kind is not explicit")
        row = self.db.execute("SELECT e.* FROM entities e JOIN namespaces n ON n.id=e.namespace_id WHERE n.identity=? AND e.kind=? AND e.local_id=?",
            (_json(reference["namespace"]), reference["kind"], _json(encode(reference["local_id"]))))
        # encode accepts the original wire dictionary unchanged or a typed ID.
        return row.fetchone()

    def _entity(self, row):
        key = row["namespace_id"]
        if key not in self._namespace_cache:
            ns = self.db.execute("SELECT n.*,a.receipt FROM namespaces n JOIN artifacts a ON a.id=n.artifact_id WHERE n.id=?",
                                 (key,)).fetchone()
            self._namespace_cache[key] = (ns["identity"], ns["receipt"])
            while len(self._namespace_cache) > 64:
                self._namespace_cache.popitem(last=False)
        self._namespace_cache.move_to_end(key)
        namespace, receipt = self._namespace_cache[key]
        return {"qualified_reference": {"namespace": json.loads(namespace),
                "kind": row["kind"], "local_id": json.loads(row["local_id"])},
            "record_type": row["record_type"], "pointer": row["pointer"],
            "artifact_receipt": json.loads(receipt),
            "wire_order": row["wire_order"], "wire_order_is_runtime_order": False}

    def entity(self, reference):
        row = self._key(reference)
        return None if row is None else self._entity(row)

    def _limit(self, value):
        result = self.query_limit if value is None else value
        if type(result) is not int or not 1 <= result <= self.query_limit:
            raise ValueError("query limit exceeds this snapshot's bounded query policy")
        return result

    def _relations(self, reference, *, incoming, relation=None, limit=None, after=0):
        bound = self._limit(limit)
        if type(after) is not int or after < 0:
            raise ValueError("relation cursor must be a nonnegative exact integer")
        if relation is not None and (type(relation) is not str or not relation):
            raise ValueError("relation filter must be a nonempty exact string")
        entity = self._key(reference)
        if entity is None:
            return {"items": [], "next_cursor": None, "entity_found": False}
        column = "target" if incoming else "source"
        predicate, arguments = f"r.{column}=? AND r.id>?", [entity["id"], after]
        if relation is not None:
            predicate += " AND r.kind=?"
            arguments.append(relation)
        rows = self.db.execute(f"SELECT r.*,a.receipt FROM relations r JOIN namespaces n ON n.id=r.namespace_id JOIN artifacts a ON a.id=n.artifact_id WHERE {predicate} ORDER BY r.id LIMIT ?",
                               (*arguments, bound + 1)).fetchall()
        items = []
        for row in rows[:bound]:
            source = self.db.execute("SELECT * FROM entities WHERE id=?", (row["source"],)).fetchone()
            target = self.db.execute("SELECT * FROM entities WHERE id=?", (row["target"],)).fetchone()
            items.append({"cursor": row["id"], "relation": row["kind"],
                "source": self._entity(source), "target": self._entity(target),
                "ordinal_path": json.loads(row["ordinal_path"]),
                "pointer": row["pointer"], "artifact_receipt": json.loads(row["receipt"]),
                "qualifiers": json.loads(row["qualifiers"])})
        return {"items": items, "next_cursor": rows[bound - 1]["id"] if len(rows) > bound else None,
                "entity_found": True, "all_relationships_indexed": False}

    def incoming(self, reference, *, relation=None, limit=None, after=0):
        return self._relations(reference, incoming=True, relation=relation, limit=limit, after=after)

    def outgoing(self, reference, *, relation=None, limit=None, after=0):
        return self._relations(reference, incoming=False, relation=relation, limit=limit, after=after)

    def region_children(self, reference, *, relation="REGION_BLOCK", limit=None, after=0):
        if reference.get("kind") != "Region" or relation not in ("REGION_BLOCK", "REGION_CHILD", "REGION_VALUE"):
            raise ValueError("region_children requires a Region and an explicit containment relation")
        return self.outgoing(reference, relation=relation, limit=limit, after=after)

    def producer(self, reference):
        if reference.get("kind") != "Value":
            raise ValueError("producer requires a qualified canonical Value")
        entity = self._key(reference)
        if entity is None:
            return None
        origins = self.db.execute("SELECT * FROM facts WHERE owner=? AND kind='VALUE_ORIGIN'", (entity["id"],)).fetchall()
        if len(origins) != 1:
            raise ValueError("canonical Value origin index is not unique")
        fact = origins[0]
        kind = json.loads(fact["details"])["origin_kind"]
        relation = ("VALUE_OPERATION_ORIGIN" if kind == "OperationResult" else
                    "VALUE_BLOCK_ORIGIN" if kind == "BlockArgument" else None)
        return {"value": self._entity(entity), "origin_kind": kind,
            "origin_pointer": fact["pointer"],
            "producer": None if relation is None else self.incoming(reference, relation=relation, limit=1),
            "literal_contents_loaded": False,
            "completion_projections_do_not_replace_block_argument_origin": True}

    def ordered_uses(self, reference, *, limit=None, after=0):
        kind = reference.get("kind")
        if kind not in ("Operation", "Value"):
            raise ValueError("ordered_uses requires an Operation or Value")
        result = self.outgoing(reference, relation="OPERATION_USE" if kind == "Operation" else "VALUE_USE",
                               limit=limit, after=after)
        for row in result["items"]:
            use = row["target"]["qualified_reference"]
            value_page = self.incoming(use, relation="VALUE_USE", limit=1)
            owner_page = self.incoming(use, relation="OPERATION_USE", limit=1)
            value_rows, owner_rows = value_page["items"], owner_page["items"]
            if (len(value_rows) != 1 or len(owner_rows) != 1
                    or value_page["next_cursor"] is not None or owner_page["next_cursor"] is not None):
                raise ValueError("indexed canonical Use lost its unique value or operation owner")
            row["use_value"] = value_rows[0]["source"]
            row["use_operation"] = owner_rows[0]["source"]
        result.update(order="original operation/use wire order; not runtime execution order",
                      duplicate_values_preserved=True)
        return result

    def facts(self, reference, *, kind=None, limit=None, after=0):
        """Bounded locator views, including StateAccess/address-selector paths."""
        bound = self._limit(limit)
        if type(after) is not int or after < 0:
            raise ValueError("fact cursor must be a nonnegative exact integer")
        if kind is not None and (type(kind) is not str or not kind):
            raise ValueError("fact filter must be a nonempty exact string")
        entity = self._key(reference)
        if entity is None:
            return {"items": [], "next_cursor": None, "entity_found": False}
        where, arguments = "owner=? AND id>?", [entity["id"], after]
        if kind is not None:
            where += " AND kind=?"
            arguments.append(kind)
        rows = self.db.execute(f"SELECT * FROM facts WHERE {where} ORDER BY id LIMIT ?",
                               (*arguments, bound + 1)).fetchall()
        source = self._entity(entity)
        return {"items": [{"cursor": row["id"], "kind": row["kind"],
                "pointer": row["pointer"], "details": json.loads(row["details"]),
                "owner": source, "artifact_receipt": source["artifact_receipt"]}
                for row in rows[:bound]],
            "next_cursor": rows[bound - 1]["id"] if len(rows) > bound else None,
            "entity_found": True}

    def unindexed_records(self, namespace, *, references=False, limit=None, after=0):
        """Exact extension-record locators; no inferred endpoint/semantic edges."""
        bound = self._limit(limit)
        if (type(namespace) is not dict or type(after) is not int or after < 0
                or type(references) is not bool):
            raise ValueError("an explicit namespace and bounded fact cursor are required")
        ns = self.db.execute("SELECT n.id,a.receipt FROM namespaces n JOIN artifacts a ON a.id=n.artifact_id WHERE n.identity=?",
                             (_json(namespace),)).fetchone()
        if ns is None:
            return {"items": [], "next_cursor": None, "namespace_found": False}
        kind = "NOT_INDEXED_REFERENCE" if references else "NOT_INDEXED_RECORD"
        rows = self.db.execute("SELECT * FROM facts WHERE namespace_id=? AND kind=? AND id>? ORDER BY id LIMIT ?",
                              (ns["id"], kind, after, bound + 1)).fetchall()
        receipt = json.loads(ns["receipt"])
        return {"items": [{"cursor": row["id"], "pointer": row["pointer"],
                "namespace": namespace, "artifact_receipt": receipt,
                **json.loads(row["details"])} for row in rows[:bound]],
            "next_cursor": rows[bound - 1]["id"] if len(rows) > bound else None,
            "namespace_found": True}

    def coverage(self):
        return {row["field"]: {"records": row["records"], "bodies_nonempty": row["bodies_nonempty"],
            "declared_reference_endpoints": row["reference_endpoints"],
            "indexing_status": row["indexing_status"], "note": row["note"]}
            for row in self.db.execute("SELECT * FROM coverage ORDER BY field")}


__all__ = ["GraphIndex", "IndexBudgets", "IndexBuildError", "index_inventory", "SCHEMA", "VERSION"]
