"""Owned, bounded source-definition and same-Run invocation obligation scan.

This module does not lower source, read raw captures, execute the target or
establish graph relations. Original JSON/JSONL record locators are subjects;
missing bodies, source associations and every other contract domain survive.
"""
from __future__ import annotations

from collections import Counter
from dataclasses import dataclass, fields
import gzip
import hashlib
import json
from pathlib import Path
import time

from scar.analysis.inventory_partitions import InventoryPartitions
from scar.ir.execution.common import EvidencePoint
from scar.ir.execution.coordinates import ExecutionRun, ProcessInstance
from scar.ir.program.call_edges import InvocationKey, CallRecordAnchor
from scar.ir.program.inventory import DefinitionInventory, SourceContextDigest
from scar.ir.program.providers import ProviderArtifact
from scar.ir.semantics_v2 import SourceSnapshot
from scar.ir.v2.ids import OperationDefinitionID
from scar.ir.record_codec import decode, encode, loads as strict_loads
from scar.ir.modeling_scope import (
    AnalysisScope, Axis, AxisResult, CollectionLocator, CollectionProfile, Coverage,
    CoverageAssessment, CoverageGap, CoverageObligation, CoverageSubject,
    DenominatorInventory, DenominatorMember, Domain, Encoding, Enumeration,
    EnumerationCursor, Expansion, LedgerEntry, ObligationSource, Observability,
    RecordLocator, RelationKind, RelationRequirement, RequirementResult,
    RequirementStatus, RetainedArtifact, ScopeField, ScopeFieldKind, SubjectKind,
    digest, obligation_id, require, locator_key, subject_key,
)

POLICY = "SOURCE_CALL_MEMBERSHIP_V1"
_SOURCE_RELATIONS = (RelationKind.SOURCE_BINDING, RelationKind.ORDERED_INPUTS,
    RelationKind.ORDERED_RESULTS, RelationKind.STATE_PRE_POST, RelationKind.CONTROL_COMPLETION,
    RelationKind.ENVIRONMENT_IDENTITY, RelationKind.OWNER_SELECTOR, RelationKind.ALIAS_ESCAPE,
    RelationKind.RESOURCE_BINDING, RelationKind.LIFETIME)
_CALL_RELATIONS = tuple(RelationKind)


@dataclass(frozen=True)
class InputArtifact:
    """Explicit immutable small root input; no decoder/provider callbacks."""
    path: str
    physical_sha256: str
    physical_bytes: int
    encoding: Encoding = Encoding.JSON

    def __post_init__(self):
        require(type(self.path) is str and Path(self.path).is_absolute(), "input path must be absolute")
        require(type(self.physical_sha256) is str and len(self.physical_sha256) == 64
                and all(c in "0123456789abcdef" for c in self.physical_sha256), "input SHA required")
        require(type(self.physical_bytes) is int and self.physical_bytes > 0, "input byte count required")
        require(type(self.encoding) is Encoding and self.encoding in (Encoding.JSON, Encoding.GZIP_JSON, Encoding.TEXT),
                "root catalog requires explicit JSON/gzip JSON/text encoding")


@dataclass(frozen=True)
class InputCatalog:
    coordinates: InputArtifact
    source_inventory: InputArtifact
    source_invocations: InputArtifact
    contract: InputArtifact
    native_bundle: InputArtifact | None = None
    os_fragment: InputArtifact | None = None
    native_capture_batch: InputArtifact | None = None

    def __post_init__(self):
        require(all(type(getattr(self, name)) is InputArtifact for name in
                    ("coordinates", "source_inventory", "source_invocations", "contract")), "fixed input catalog required")
        require(all(getattr(self, name) is None or type(getattr(self, name)) is InputArtifact for name in
                    ("native_bundle", "os_fragment", "native_capture_batch")), "invalid optional fixed catalog")
        require(self.native_capture_batch is None,
                "native-capture-batch inventory adapter awaits its explicitly published schema; no schema guess")


@dataclass(frozen=True)
class InputBudgets:
    max_root_bytes: int = 32_000_000
    max_shard_bytes: int = 32_000_000
    max_calls_stored_bytes: int = 128_000_000
    max_calls_decoded_bytes: int = 1_000_000_000
    max_line_bytes: int = 1_000_000
    max_total_read_bytes: int = 2_000_000_000
    max_members: int = 200_000
    max_source_files: int = 1000
    max_seconds: int = 600

    def __post_init__(self):
        require(all(type(getattr(self, f.name)) is int and getattr(self, f.name) > 0 for f in fields(self)),
                "input budgets must be positive exact integers")


def _pointer(document, pointer):
    require(type(pointer) is str and (pointer == "#" or pointer.startswith("#/")), "invalid input pointer")
    result = document
    for token in pointer[2:].split("/") if pointer != "#" else ():
        token = token.replace("~1", "/").replace("~0", "~")
        if type(result) is list:
            require(token.isdecimal() and (token == "0" or not token.startswith("0")), "invalid original array ordinal")
            result = result[int(token)]
        else:
            require(type(result) is dict and token in result, "original locator does not exist")
            result = result[token]
    return result


def _artifact(path, raw, schema, encoding=Encoding.TEXT, decoded=None):
    decoded = raw if decoded is None else decoded
    return RetainedArtifact(ProviderArtifact(str(path), hashlib.sha256(raw).hexdigest(), len(raw), schema),
        hashlib.sha256(decoded).hexdigest(), len(decoded), encoding)


def _producer_paths():
    here = Path(__file__).resolve()
    return (here, here.parents[1] / "ir/modeling_scope.py",
            here.parents[1] / "ir/modeling_scope_codec.py", here.parents[1] / "store/scope_partitions.py")


def _freeze_producers():
    return tuple(_artifact(p, p.read_bytes(),
        "scar.modeling-scope-byte-membership-checker.v1" if i == 0 else "scar.modeling-scope-producer-source.v1")
        for i, p in enumerate(_producer_paths()))


class InputResolver:
    """Fixed catalog and owned scan; no arbitrary callback or verified=True API.

    Streaming members are handed once to the publisher. Skipping/changing rows
    or publishing before end-of-stream receipt verification is rejected.
    """
    def __init__(self, catalog, *, budgets=None):
        require(type(catalog) is InputCatalog, "expected fixed typed InputCatalog")
        catalog.__post_init__()
        self.catalog = catalog
        self.limits = InputBudgets() if budgets is None else budgets
        require(type(self.limits) is InputBudgets, "expected InputBudgets")
        self.limits.__post_init__()
        self.start = time.monotonic()
        self.bytes_read, self.members_seen = 0, 0
        self._pending, self._owned_scope, self._begun, self._finished = None, None, False, False
        self._source_verified, self._calls_verified = False, False
        self._counts = Counter()
        self._frozen_producers = _freeze_producers()
        self._code = self._frozen_producers[0]
        self.coordinates, self.coordinate_artifact = self._root(catalog.coordinates, "scar.capture-coordinates", (1,))
        self.run = decode(ExecutionRun, self.coordinates["run"])
        processes = tuple(decode(ProcessInstance, p) for p in self.coordinates["processes"])
        require(all(p.run == self.run.id for p in processes), "coordinate process belongs to another Run")
        self.processes = {p.id: p for p in processes}
        self.inventory_document, self.inventory_artifact = self._root(catalog.source_inventory,
            "scar.partitioned-program-inventory", (1, 2))
        self.report, self.report_artifact = self._root(catalog.source_invocations, "scar.source-invocations", (2, 3))
        # This is the current CompositionIndex inventory receipt, not its
        # original compiler/static-source witness origin. Same Run is not a
        # license to combine a prior body snapshot with the supplied manifest.
        self._check_inventory_binding()
        require(decode(ExecutionRun, self.report["run"]) == self.run, "source-invocations report belongs to another Run")
        bound = decode(ProviderArtifact, self.report["coordinate_binding"])
        require((bound.sha256, bound.size_bytes, bound.schema) ==
                (self.coordinate_artifact.decoded_sha256, self.coordinate_artifact.decoded_bytes, "scar.capture-coordinates"),
                "source-invocations coordinate binding mismatch")
        require(type(self.report["invocations"]) is dict and type(self.report["summary"]) is dict,
                "missing invocation denominator")
        self.call_count = self._count(self.report["invocations"]["rows"])
        require(self.call_count == self._count(self.report["summary"]["invocations"]), "invocation denominator declaration mismatch")
        self.contract_artifact = self._read(catalog.contract, schema="text/markdown")[1]
        require(self.contract_artifact.encoding is Encoding.TEXT, "contract must be exact original Markdown text")
        # Public source partition reader validates original source shard receipts;
        # it never opens graph checkpoints during file/header enumeration.
        self.inventory = InventoryPartitions(catalog.source_inventory.path,
            max_shard_bytes=self.limits.max_shard_bytes, cache_entries=1)
        require(self.inventory.manifest_receipt == {
            "physical_sha256": self.inventory_artifact.original.sha256,
            "physical_bytes": self.inventory_artifact.original.size_bytes,
            "decoded_sha256": self.inventory_artifact.decoded_sha256,
            "decoded_bytes": self.inventory_artifact.decoded_bytes}, "source manifest changed between fixed readers")
        require(len(self.inventory.manifest["files"]) <= self.limits.max_source_files, "source file budget exceeded")
        for name in ("header", "publication") if self.inventory.version == 2 else ("header",):
            ref = self.inventory.manifest["components"][name]
            self._charge(ref["physical_bytes"] * 2 + ref["decoded_bytes"])
        self.header = self.inventory.component("header")
        self.source_count = self._count(self.header["summary"]["definitions"])
        require(self.inventory.manifest["counts"]["source_files"] == len(self.inventory.manifest["files"]),
                "source file denominator mismatch")
        self._optional = {}
        if catalog.native_bundle is not None:
            self._optional["native"] = self._root(catalog.native_bundle, "scar.partitioned-ir-bundle", (1,))
        if catalog.os_fragment is not None:
            doc, artifact = self._root(catalog.os_fragment, "scar.partitioned-os-resource-fragment", (1,))
            require(decode(ExecutionRun, doc["run"]) == self.run, "OS fragment belongs to another Run")
            self._optional["os"] = doc, artifact

    @staticmethod
    def _count(value):
        require(type(value) is int and value >= 0, "declared count must be nonnegative exact int")
        return value

    def _check_inventory_binding(self):
        """Check the exact _InventorySource._read public receipt contract.

        raw_sha256/raw_bytes denote physical (possibly gzip) bytes. The old
        public receipt carries decoded_bytes, but no decoded_sha256 field.
        Our root/public partition readers separately check decoded identity.
        """
        binding = self.report.get("inventory")
        require(type(binding) is dict and set(binding) ==
                {"path", "raw_sha256", "raw_bytes", "decoded_bytes"},
                "unsupported/missing current source-invocations inventory receipt")
        path = self.catalog.source_inventory.path
        require(path == str(Path(path).resolve()),
                "source inventory requires its canonical original URI; retention relocation is unsupported")
        require(type(binding["path"]) is str and type(binding["raw_sha256"]) is str
                and type(binding["raw_bytes"]) is int and type(binding["decoded_bytes"]) is int,
                "current inventory receipt requires exact public field types")
        expected = {"path": path, "raw_sha256": self.inventory_artifact.original.sha256,
            "raw_bytes": self.inventory_artifact.original.size_bytes,
            "decoded_bytes": self.inventory_artifact.decoded_bytes}
        require(binding == expected,
                "source-invocations current inventory receipt differs from supplied manifest; same Run cannot repair snapshot mismatch")

    def _charge(self, size):
        self.bytes_read += size
        require(self.bytes_read <= self.limits.max_total_read_bytes, "scope input total byte budget exceeded")
        require(time.monotonic() - self.start <= self.limits.max_seconds, "scope input wall budget exceeded")

    def _read(self, item, *, schema):
        item.__post_init__()
        path = Path(item.path)
        require(path.is_file() and not path.is_symlink() and path.stat().st_size == item.physical_bytes
                and item.physical_bytes <= self.limits.max_root_bytes, "root input size/path budget mismatch")
        raw = path.read_bytes(); self._charge(len(raw))
        require(hashlib.sha256(raw).hexdigest() == item.physical_sha256, "root input receipt mismatch")
        if item.encoding is Encoding.GZIP_JSON:
            import io
            with gzip.GzipFile(fileobj=io.BytesIO(raw)) as stream:
                payload = stream.read(self.limits.max_root_bytes + 1)
            self._charge(len(payload))
            require(len(payload) <= self.limits.max_root_bytes, "root decoded budget exceeded")
        else:
            payload = raw
        return payload, _artifact(path, raw, schema, item.encoding, payload)

    def _root(self, item, schema, versions):
        raw, artifact = self._read(item, schema=schema)
        document = strict_loads(raw.decode("utf-8"))
        require(type(document) is dict and document.get("schema") == schema
                and type(document.get("schema_version")) is int and document["schema_version"] in versions,
                "unsupported fixed catalog schema/version: " + schema)
        return document, artifact

    @staticmethod
    def _ref(artifact, pointer="#"):
        return RecordLocator(artifact, pointer)

    def _collection(self, domain):
        if domain is Domain.SOURCE_DEFINITIONS:
            return CollectionLocator(self._ref(self.inventory_artifact, "#/files"), CollectionProfile.SOURCE_DEFINITIONS_V1_V2), self.source_count
        if domain is Domain.SOURCE_CONSTRUCTS:
            count = self.header["summary"].get("coverage_atoms")
            return CollectionLocator(self._ref(self.inventory_artifact, "#/files"), CollectionProfile.SOURCE_CONSTRUCTS_V1_V2), None if count is None else self._count(count)
        if domain is Domain.OBSERVED_PYTHON_CALLS:
            return CollectionLocator(self._ref(self.report_artifact, "#/invocations"), CollectionProfile.SOURCE_INVOCATIONS_V1_V3), self.call_count
        if domain is Domain.DISPATCH_ATTEMPTS:
            declaration = self.coordinates.get("dispatch_collector_declaration")
            if type(declaration) is dict and type(declaration.get("dispatch_attempts")) is int:
                return CollectionLocator(self._ref(self.coordinate_artifact, "#/dispatch_collector_declaration"), CollectionProfile.DECLARED_COLLECTION), self._count(declaration["dispatch_attempts"])
        if domain in (Domain.NATIVE_ACTIVITIES, Domain.PHYSICAL_OBJECTS_AND_RESOURCES) and "native" in self._optional:
            doc, artifact = self._optional["native"]
            if domain is Domain.NATIVE_ACTIVITIES:
                pointer = "#/graphs/evidence/tables/instances"
                count = self._count(_pointer(doc, pointer)["records"])
            else:
                pointer = "#/graphs/values/tables"
                tables = _pointer(doc, pointer)
                count = sum(self._count(tables[k]["records"]) for k in ("objects", "allocations", "regions"))
            return CollectionLocator(self._ref(artifact, pointer), CollectionProfile.DECLARED_COLLECTION), count
        if domain in (Domain.OS_RESOURCES, Domain.OS_INTERFACES) and "os" in self._optional:
            doc, artifact = self._optional["os"]
            if domain is Domain.OS_INTERFACES:
                pointer = "#/tables/observations"; count = self._count(_pointer(doc, pointer)["records"])
            else:
                pointer = "#/tables"
                tables = _pointer(doc, pointer)
                count = sum(self._count(tables[k]["records"]) for k in ("resources", "handles", "target_lifetime_events", "processes", "threads"))
            return CollectionLocator(self._ref(artifact, pointer), CollectionProfile.DECLARED_COLLECTION), count
        require(type(self.coordinates.get("membership")) is list, "capture membership collection absent")
        return CollectionLocator(self._ref(self.coordinate_artifact, "#/membership"), CollectionProfile.CAPTURE_MEMBERSHIP_V1), None

    def _gap(self, code, key, source, reason, missing=None):
        return CoverageGap(code, key, source, reason, missing)

    def plan_scope(self):
        require(self._owned_scope is None, "resolver scope is already frozen")
        source = self._ref(self.coordinate_artifact)
        policy = self._ref(self._code)
        policy_sources = tuple(self._ref(a) for a in self._frozen_producers)
        seed = self.coordinates.get("seed")
        require(type(seed) is dict and type(seed.get("command_sha256")) is str, "original command seed is absent")
        require(len(seed["command_sha256"]) == 64 and all(c in "0123456789abcdef" for c in seed["command_sha256"]),
                "invalid original command seed SHA")
        identity = "scope:" + digest(("ANALYSIS_SCOPE_V1", self.run.id, seed["command_sha256"]))
        scope_fields = tuple(ScopeField(kind, (source,), (self._gap("SCOPE_FIELD_NOT_REVIEWED", kind.value, source,
            "Original scope field needs its specific retained evidence; analysis-machine values are not substituted"),)) for kind in ScopeFieldKind)
        observations = tuple(Observability(domain, self._observation_sources(domain), Coverage.UNKNOWN, (self._gap(
            "OBSERVABILITY_NOT_CLOSED", domain.value, self._collection(domain)[0].record,
            "Exact input roots/declarations are bound, but provider observation completeness is not reviewed"),)) for domain in Domain)
        payload = (identity, self._ref(self.contract_artifact), policy, source, self.run.id, scope_fields,
                   observations, tuple(Domain), policy_sources)
        scope = AnalysisScope(identity, "scope_revision:" + digest(payload), None, self._ref(self.contract_artifact),
            policy, source, self.run.id, scope_fields, observations, tuple(Domain), policy_sources)
        self._owned_scope = scope
        return scope

    def _observation_sources(self, domain):
        """Typed exact catalog roots plus declarations; no positive coverage claim."""
        if domain in (Domain.SOURCE_DEFINITIONS, Domain.SOURCE_CONSTRUCTS):
            root = self.inventory_artifact
        elif domain is Domain.OBSERVED_PYTHON_CALLS:
            root = self.report_artifact
        elif domain in (Domain.NATIVE_ACTIVITIES, Domain.PHYSICAL_OBJECTS_AND_RESOURCES) and "native" in self._optional:
            root = self._optional["native"][1]
        elif domain in (Domain.OS_INTERFACES, Domain.OS_RESOURCES) and "os" in self._optional:
            root = self._optional["os"][1]
        else:
            root = self.coordinate_artifact
        return tuple(dict.fromkeys((self._ref(root), self._collection(domain)[0].record)))

    def _denominator_id(self, scope, domain, collection):
        return "denominator:" + digest((scope.id, domain, locator_key(collection.record), collection.profile))

    def _entry(self, scope, domain, subject, *, membership=True, retained_gaps=()):
        rule = POLICY + ":" + domain.value
        relations = (_SOURCE_RELATIONS if domain is Domain.SOURCE_DEFINITIONS else _CALL_RELATIONS)
        if subject.kind is SubjectKind.COLLECTION:
            relations = (RelationKind.SOURCE_BINDING, RelationKind.RESOURCE_BINDING, RelationKind.READY_ORDER, RelationKind.LIFETIME)
        expansion = Expansion.SOURCE_BODY if domain in (Domain.SOURCE_DEFINITIONS, Domain.SOURCE_CONSTRUCTS, Domain.OBSERVED_PYTHON_CALLS) else Expansion.PROTOCOL_INTERFACE
        obligation = CoverageObligation(obligation_id(subject, rule), scope.revision, rule,
            ObligationSource(scope.policy, subject.record), subject,
            tuple(RelationRequirement(r.value, r, scope.policy) for r in relations), expansion, True)
        collection, _ = self._collection(domain)
        member = DenominatorMember(self._denominator_id(scope, domain, collection), subject, obligation.id, subject.record) if membership else None
        axes = []
        for axis in Axis:
            keys = (["ORIGINAL_RECORD_MEMBERSHIP"] if axis is Axis.STRUCTURAL_ATTRIBUTION else
                [r.value for r in relations] if axis is Axis.DEPENDENCY_CONNECTION else
                [expansion.value] if axis is Axis.INTERNAL_EXPANSION else ["ORIGINAL_SEMANTIC_EVIDENCE"])
            results = []
            for key in keys:
                if axis is Axis.STRUCTURAL_ATTRIBUTION and membership:
                    results.append(RequirementResult(key, RequirementStatus.SATISFIED, (subject.record,), (), ()))
                else:
                    reason = ("Collection membership is unenumerated or provider is absent" if not membership else
                              "Original record membership does not prove this semantic relation/expansion; no accepted-scope reuse implemented")
                    results.append(RequirementResult(key, RequirementStatus.OPEN, (subject.record,), (),
                        (self._gap("REQUIRED_EVIDENCE_OPEN", key, subject.record, reason),)))
            axes.append(AxisResult(axis, tuple(results)))
        return LedgerEntry(obligation, member, CoverageAssessment(obligation.id, scope.revision, tuple(axes),
            self._code.original, subject.record, retained_gaps))

    def _offer(self, row):
        require(self._pending is None, "owned row was skipped instead of published")
        self._pending = row
        return row

    def _denominator(self, scope, domain, count, membership_hash, *, complete):
        collection, declared = self._collection(domain)
        gaps = [self._gap("OBSERVATION_COMPLETENESS_UNKNOWN", domain.value, collection.record,
            "Retained archive enumeration does not prove no collection loss or missing runtime/resource activity")]
        if not complete:
            gaps.append(self._gap("DOMAIN_UNENUMERATED" if declared is not None else "MISSING_PROVIDER_OR_COLLECTION",
                domain.value, collection.record, "This contract domain is retained as an explicit independent collection debt",
                declared if declared is not None else None))
        if domain in (Domain.NATIVE_ACTIVITIES, Domain.PHYSICAL_OBJECTS_AND_RESOURCES) and "native" in self._optional:
            gaps.append(self._gap("CATALOG_RUN_BINDING_UNREVIEWED", domain.value, collection.record,
                "Exact native manifest counts are retained declarations; same-Run provider membership is not yet reviewed"))
        orphan_count = self._count(self.report.get("orphan_exits", {}).get("rows", 0))
        if domain is Domain.OBSERVED_PYTHON_CALLS and orphan_count:
            gaps.append(self._gap("ORPHAN_EXITS_UNENUMERATED", "ORPHAN_EXITS", self._ref(self.report_artifact, "#/orphan_exits"),
                "Original orphan exits remain outside entered-call membership", orphan_count))
        return DenominatorInventory(self._denominator_id(scope, domain, collection), scope.revision, domain, collection,
            collection.record, declared, count, membership_hash if complete else None,
            Enumeration.ENUMERATED if complete else Enumeration.DECLARED, Coverage.UNKNOWN,
            None if complete else EnumerationCursor(collection, 0, 0, "Domain not visited by initial source/call producer"), tuple(gaps))

    def rows(self, scope):
        require(scope == self._owned_scope and self._begun and not self._finished, "scope scan is not owned/active")
        hashes = {d: hashlib.sha256() for d in (Domain.SOURCE_DEFINITIONS, Domain.OBSERVED_PYTHON_CALLS)}
        for fi, ref in enumerate(self.inventory.manifest["files"]):
            self._charge(ref["physical_bytes"] * 2 + ref["decoded_bytes"])
            file = self.inventory.file(fi)
            snapshot = decode(SourceSnapshot, file["snapshot"])
            context = decode(SourceContextDigest, file["context"])
            require(Path(snapshot.path).is_absolute() and Path(snapshot.path).is_relative_to(context.namespace_root),
                    "source definition namespace mismatch")
            path = Path(ref["uri"]) if ref["external"] else self.inventory.root / ref["uri"]
            encoding = Encoding.GZIP_JSON if path.suffix == ".gz" else Encoding.JSON
            artifact = RetainedArtifact(ProviderArtifact(str(path.absolute()), ref["physical_sha256"], ref["physical_bytes"], "scar.partitioned-file-inventory"),
                ref["decoded_sha256"], ref["decoded_bytes"], encoding)
            definitions = [decode(DefinitionInventory, d) for d in file["definitions"]]
            require(len({d.id for d in definitions}) == len(definitions), "duplicate source definition in original shard")
            body_headers = {}
            for bi, body in enumerate(file["bodies"]):
                definition_id = decode(OperationDefinitionID, body["definition"])
                require(definition_id not in body_headers, "duplicate body header for original definition")
                body_headers[definition_id] = bi, body
            for di, definition in enumerate(definitions):
                require(definition.source.path == snapshot.path and definition.source.fingerprint == snapshot.fingerprint,
                        "definition source differs from exact original snapshot")
                subject = CoverageSubject(scope.id, SubjectKind.SOURCE_DEFINITION,
                    RecordLocator(artifact, "#/file/definitions/" + str(di)))
                self._member_seen(Domain.SOURCE_DEFINITIONS)
                hashes[Domain.SOURCE_DEFINITIONS].update((digest(subject_key(subject)) + "\n").encode())
                if definition.id not in body_headers:
                    retained = (self._gap("CANONICAL_BODY_UNAVAILABLE", Expansion.SOURCE_BODY.value, subject.record,
                        "Original source definition has no body header; no body is invented"),)
                else:
                    bi, body = body_headers[definition.id]
                    require(body["status"] in ("LOWERED_WITH_GAPS", "UNSUPPORTED", "NOT_ATTEMPTED"), "unknown body inventory status")
                    retained = (self._gap("ORIGINAL_BODY_" + body["status"], Expansion.SOURCE_BODY.value,
                        RecordLocator(artifact, "#/file/bodies/" + str(bi)),
                        str(body.get("reason") or ("Original body status " + body["status"]))[:512]),)
                yield self._offer(self._entry(scope, Domain.SOURCE_DEFINITIONS, subject, retained_gaps=retained))
        require(self._counts[Domain.SOURCE_DEFINITIONS.value] == self.source_count, "source definition denominator mismatch")
        self._source_verified = True
        for subject, retained in self._calls(scope):
            self._member_seen(Domain.OBSERVED_PYTHON_CALLS)
            hashes[Domain.OBSERVED_PYTHON_CALLS].update((digest(subject_key(subject)) + "\n").encode())
            yield self._offer(self._entry(scope, Domain.OBSERVED_PYTHON_CALLS, subject, retained_gaps=retained))
        require(self._counts[Domain.OBSERVED_PYTHON_CALLS.value] == self.call_count, "invocation row denominator mismatch")
        for domain in Domain:
            complete = domain in hashes
            if not complete:
                collection, _ = self._collection(domain)
                yield self._offer(self._entry(scope, domain,
                    CoverageSubject(scope.id, SubjectKind.COLLECTION, collection.record), membership=False))
            yield self._offer(self._denominator(scope, domain, self._counts[domain.value],
                hashes[domain].hexdigest() if complete else None, complete=complete))
        require(self._pending is None, "last owned row was not published")
        self._finished = True

    def _member_seen(self, domain):
        self.members_seen += 1
        self._counts[domain.value] += 1
        require(self.members_seen <= self.limits.max_members, "source/call member budget exceeded")

    def _calls(self, scope):
        declaration = self.report["invocations"]
        require(set(declaration) == {"path", "rows", "raw_sha256", "raw_bytes"}, "invocation file declaration fields differ")
        relative = Path(declaration["path"])
        require(not relative.is_absolute() and len(relative.parts) == 1 and relative.name == "invocations.jsonl.gz",
                "source-invocation artifact path is not its exact published relative file")
        path = Path(self.catalog.source_invocations.path).parent / relative
        require(path.is_file() and not path.is_symlink() and path.stat().st_size <= self.limits.max_calls_stored_bytes,
                "invocation artifact path/stored byte budget invalid")
        require(self._count(declaration["raw_bytes"]) <= self.limits.max_calls_decoded_bytes, "invocation decoded byte budget exceeded")
        before = path.stat()
        physical, size = hashlib.sha256(), 0
        with path.open("rb") as stream:
            for block in iter(lambda: stream.read(1_048_576), b""):
                physical.update(block); size += len(block); self._charge(len(block))
        artifact = RetainedArtifact(ProviderArtifact(str(path.absolute()), physical.hexdigest(), size,
            "scar.source-invocation-rows.v" + str(self.report["schema_version"])), declaration["raw_sha256"],
            declaration["raw_bytes"], Encoding.GZIP_JSONL)
        total, count, raw_hash, seen = 0, 0, hashlib.sha256(), set()
        with gzip.open(path, "rb") as stream:
            while True:
                raw = stream.readline(self.limits.max_line_bytes + 1)
                if not raw:
                    break
                require(len(raw) <= self.limits.max_line_bytes and raw.endswith(b"\n"), "invocation line bound/terminator invalid")
                total += len(raw); count += 1; self._charge(len(raw)); raw_hash.update(raw)
                require(total <= declaration["raw_bytes"] and count <= self.call_count, "invocation stream exceeds declaration")
                row = strict_loads(raw.decode("utf-8"))
                require(type(row) is dict and row.get("kind") == "INVOCATION", "original row is not an invocation")
                invocation = decode(InvocationKey, row["invocation"])
                require(invocation not in seen, "duplicate actual invocation in original source report")
                seen.add(invocation)
                decode(CallRecordAnchor, row["anchor"])
                require(type(row.get("status")) is str and type(row.get("frontiers")) is list,
                        "invocation source/frontier inventory absent")
                require(all(type(g) is str and bool(g) for g in row["frontiers"]), "invalid original invocation frontier")
                if row.get("point") is not None:
                    point = decode(EvidencePoint, row["point"])
                    require(point.run == self.run.id, "invocation point belongs to another Run")
                    if point.process is not None:
                        require(point.process in self.processes and self.processes[point.process].pid == invocation.process_id,
                                "actual invocation process contradicts coordinates")
                locator = RecordLocator(artifact, "#", count, hashlib.sha256(raw).hexdigest())
                retained = tuple(self._gap("ORIGINAL_CALL_FRONTIER", "ORIGINAL_SEMANTIC_EVIDENCE", locator, reason)
                                 for reason in row["frontiers"])
                if row.get("region_activation") is None:
                    retained += (self._gap("CANONICAL_ACTIVATION_UNAVAILABLE", "ORIGINAL_SEMANTIC_EVIDENCE", locator,
                        "Original invocation status " + row["status"] + " has no canonical activation"),)
                yield CoverageSubject(scope.id, SubjectKind.INVOCATION, locator), retained
        require((count, total, raw_hash.hexdigest()) ==
                (self.call_count, declaration["raw_bytes"], declaration["raw_sha256"]), "invocation full decoded receipt mismatch")
        after = path.stat()
        require((before.st_dev, before.st_ino, before.st_size, before.st_mtime_ns, before.st_ctime_ns) ==
                (after.st_dev, after.st_ino, after.st_size, after.st_mtime_ns, after.st_ctime_ns),
                "invocation artifact changed during owned scan")
        self._calls_verified = True

    def begin_publication(self, scope):
        require(scope == self._owned_scope and not self._begun, "resolver may publish its exact frozen scope only once")
        self._begun = True

    def accept_publication_row(self, scope, row):
        require(scope == self._owned_scope and self._begun and self._pending is not None and row == self._pending,
                "publication row was not handed off by the fixed owned scan")
        self._pending = None

    def finish_publication(self, scope):
        require(scope == self._owned_scope and self._finished and self._pending is None
                and self._source_verified and self._calls_verified, "owned scan did not finish full source/call receipts")
        self.producer_receipts()  # All four initial source versions must still hold.

    def producer_receipts(self):
        result = []
        for frozen in self._frozen_producers:
            original = frozen.original
            current = Path(original.uri).read_bytes()
            require(len(current) == original.size_bytes and hashlib.sha256(current).hexdigest() == original.sha256,
                    "producer source changed during owned scan: " + original.uri)
            result.append({"path": original.uri, "sha256": original.sha256, "bytes": original.size_bytes})
        return result

    def review_receipt(self):
        return {"policy": POLICY, "accounted_stored_plus_decoded_bytes": self.bytes_read, "members_seen": self.members_seen,
            "source_members": self._counts[Domain.SOURCE_DEFINITIONS.value],
            "invocation_members": self._counts[Domain.OBSERVED_PYTHON_CALLS.value],
            "source_receipt_review": "FULL_ENUMERATED" if self._source_verified else "UNFINISHED",
            "invocation_receipt_review": "FULL_ENUMERATED" if self._calls_verified else "UNFINISHED",
            "semantic_scope_reuse": "UNSUPPORTED_INITIAL_POLICY", "raw_replay": "NONE",
            "target_executions": 0, "wall_seconds": time.monotonic() - self.start}


def produce_scope_ledger(catalog, fresh_output, *, input_budgets=None, storage_budgets=None):
    from scar.store.scope_partitions import publish_scope_ledger
    resolver = InputResolver(catalog, budgets=input_budgets)
    scope = resolver.plan_scope()
    return publish_scope_ledger(scope, resolver.rows(scope), fresh_output, resolver=resolver, budgets=storage_budgets)


__all__ = ["InputArtifact", "InputCatalog", "InputBudgets", "InputResolver", "produce_scope_ledger", "POLICY"]
