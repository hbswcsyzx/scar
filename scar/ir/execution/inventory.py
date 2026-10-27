"""Offline, source-rooted format inventory; never complete runtime write proof."""
from __future__ import annotations

from dataclasses import dataclass
import hashlib
import io
import json
import math
from pathlib import Path

from scar.ir.program.providers import ProviderArtifact, ProviderRunScope
from scar.ir.v2.codec import bundle_from_dict
from scar.ir.v2.common import SourceVersion
from scar.ir.v2.schemas import IRBundle, canonical_json
from .resources import _exact, _record
from .snapshot import ExternalSnapshots, external_artifact


MANIFEST_SCHEMA = "scar.capture-source-manifest"
INDEX_SCHEMA = "scar.normalization-index"
COVERAGE_SCHEMA = "scar.trace.v2.coverage"


def _text(value, name):
    _exact(value, str, name)
    if not value:
        raise ValueError(name + " must be nonempty")


def _positive(value, name):
    _exact(value, int, name)
    if value <= 0:
        raise ValueError(name + " must be positive")


@dataclass(frozen=True, slots=True)
class InventoryGap:
    code: str
    path: str
    message: str

    def __post_init__(self):
        for name in ("code", "path", "message"):
            _text(getattr(self, name), "inventory gap " + name)


@dataclass(frozen=True, slots=True)
class RawInventoryRecord:
    line: int
    sha256: str
    payload: dict | None

    def __post_init__(self):
        _positive(self.line, "raw line")
        if type(self.sha256) is not str or len(self.sha256) != 64 or any(c not in "0123456789abcdef" for c in self.sha256):
            raise ValueError("raw line SHA256 must be canonical lowercase hexadecimal")
        if self.payload is not None and type(self.payload) is not dict:
            raise TypeError("raw inventory payload must be detached dict or None")


@dataclass(frozen=True, slots=True)
class ResolvedSource:
    key: str
    raw_artifact: ProviderArtifact
    raw_records: tuple[RawInventoryRecord, ...]
    bundle: IRBundle | None
    evidence_artifact: ProviderArtifact | None
    values_artifact: ProviderArtifact | None
    semantic_artifact: ProviderArtifact | None
    projection_replayed: bool

    def __post_init__(self):
        _text(self.key, "source key")
        _record(self.raw_artifact, ProviderArtifact, "raw artifact")
        _exact(self.raw_records, tuple, "raw inventory records")
        for row in self.raw_records:
            _record(row, RawInventoryRecord, "raw inventory record")
        if self.bundle is not None:
            _exact(self.bundle, IRBundle, "source bundle")
        for name in ("evidence_artifact", "values_artifact", "semantic_artifact"):
            if getattr(self, name) is not None:
                _record(getattr(self, name), ProviderArtifact, name)
        _exact(self.projection_replayed, bool, "projection replay flag")


@dataclass(frozen=True, slots=True)
class InventoryResolution:
    sources: tuple[ResolvedSource, ...]
    gaps: tuple[InventoryGap, ...]
    format_replayed: bool

    def __post_init__(self):
        for name, kind in (("sources", ResolvedSource), ("gaps", InventoryGap)):
            _exact(getattr(self, name), tuple, name)
            for row in getattr(self, name):
                _record(row, kind, name + " row")
        _exact(self.format_replayed, bool, "format replay flag")

    @property
    def source_runtime_verified(self):
        return False

    @property
    def transformation_authorized(self):
        return False


def artifact_json(artifact):
    _record(artifact, ProviderArtifact, "inventory artifact")
    return {name: getattr(artifact, name) for name in ("uri", "sha256", "size_bytes", "schema")}


def _keys(value, expected, path):
    if type(value) is not dict or any(type(key) is not str for key in value) or set(value) != set(expected):
        raise ValueError(path + ": missing, unknown, or invalid fields")


def _artifact(value, path):
    _keys(value, ("uri", "sha256", "size_bytes", "schema"), path)
    return ProviderArtifact(**value)


def _array(value, path):
    if type(value) is not list:
        raise ValueError(path + ": expected JSON array")
    return value


def _pairs(pairs):
    result = {}
    for key, value in pairs:
        if key in result:
            raise ValueError("duplicate JSON key: " + key)
        result[key] = value
    return result


def _no_constant(value):
    raise ValueError("non-finite JSON number: " + value)


def _float(value):
    result = float(value)
    if not math.isfinite(result):
        raise ValueError("non-finite JSON float")
    return result


def _json(payload):
    return json.loads(payload.decode("utf-8", errors="strict"), object_pairs_hook=_pairs,
                      parse_constant=_no_constant, parse_float=_float)


def normalizer_implementation():
    """Fingerprint only fixed installed SCAR code, never a recipe-provided path."""
    from scar.trace import normalize_v2
    return SourceVersion("scar/trace/normalize_v2.py",
                         "sha256:" + hashlib.sha256(Path(normalize_v2.__file__).read_bytes()).hexdigest())


class InventoryResolver:
    def __init__(self, snapshots, *, max_bytes=67_108_864, max_lines=1_000_000,
                 max_line_bytes=4_194_304, max_artifacts=256):
        _exact(snapshots, ExternalSnapshots, "inventory snapshots")
        self.snapshots = snapshots
        for name, value in (("max_bytes", max_bytes), ("max_lines", max_lines),
                            ("max_line_bytes", max_line_bytes), ("max_artifacts", max_artifacts)):
            _positive(value, name)
            setattr(self, name, value)

    def _gap(self, code, path, message):
        self._gaps.append(InventoryGap(code, path, message))

    def _payload(self, artifact, path):
        key = artifact.sha256, artifact.schema, artifact.size_bytes
        if key in self._seen:
            return self._seen[key]
        if len(self._seen) >= self.max_artifacts or artifact.size_bytes > self.max_bytes - self._bytes:
            self._gap("inventory_budget", path, "source artifact/byte budget exhausted; source remains pending")
            return None
        payload = self.snapshots.payload(artifact)
        self._seen[key] = payload
        if payload is None:
            self._gap("inventory_artifact_missing", path, "exact source bytes were not supplied; URI is not opened")
        else:
            self._bytes += len(payload)
        return payload

    def _document(self, artifact, path, schema=None):
        if schema is not None and artifact.schema != schema:
            raise ValueError(path + ": artifact schema disagrees with required source profile")
        payload = self._payload(artifact, path)
        if payload is None:
            return None
        try:
            document = _json(payload)
        except (UnicodeError, ValueError, RecursionError, OverflowError) as error:
            raise ValueError(path + ": invalid strict JSON: " + str(error)) from error
        if type(document) is not dict:
            raise ValueError(path + ": expected JSON object")
        return document

    def _scope(self, value, path):
        if type(value) is not dict:
            raise ValueError(path + ": expected typed scope")
        if value.get("kind") == "missing":
            _keys(value, ("kind", "reason"), path)
            _text(value["reason"], path)
            self._gap("inventory_scope_missing", path, value["reason"])
            return None
        _keys(value, ("kind", "value"), path)
        if value["kind"] != "provider":
            raise ValueError(path + ": unknown scope variant")
        _keys(value["value"], ("run", "process_id", "window", "clock", "thread_id"), path)
        scope = ProviderRunScope(**value["value"])
        self._gap("inventory_scope_unverified", path, "provider scope is not canonical runtime incarnation/capture proof")
        return scope

    def _metadata(self, artifact, path, *, collector):
        document = self._document(artifact, path)
        if document is None:
            return
        for name in ("dropped_events", "dropped_codes", "open_invocations", "gaps"):
            if name in document:
                value = document[name]
                if type(value) is not int or value < 0:
                    raise ValueError(path + ": invalid collector counter " + name)
                if value:
                    self._gap("inventory_collection_gap", path + "." + name, "collector reports nonzero " + name)
        for name in ("io_failed", "previous_profile"):
            if name in document:
                if type(document[name]) is not bool:
                    raise ValueError(path + ": invalid collector flag " + name)
                if document[name]:
                    self._gap("inventory_collection_gap", path + "." + name, "collector reports " + name)
        if "errors" in document:
            errors = _array(document["errors"], path + ".errors")
            if any(type(error) is not str for error in errors):
                raise ValueError(path + ": invalid collector errors")
            if errors:
                self._gap("inventory_collection_gap", path, "collector reports errors")
        if collector and "ended_ns" not in document:
            self._gap("inventory_window_unsealed", path, "collector metadata does not establish a finished capture window")
        for name in ("started_ns", "ended_ns", "event_count", "entity_count"):
            if name in document and (type(document[name]) is not int or document[name] < 0):
                raise ValueError(path + ": invalid collector field " + name)
        if ("started_ns" in document and "ended_ns" in document
                and document["ended_ns"] < document["started_ns"]):
            raise ValueError(path + ": collector end precedes start")
        if collector and any(name not in document for name in ("dropped_events", "io_failed", "errors")):
            self._gap("inventory_loss_coverage_missing", path, "metadata does not declare collector loss/error coverage")

    def _records(self, payload, path):
        records, stream = [], io.BytesIO(payload)
        while raw := stream.readline(self.max_line_bytes + 1):
            if self._lines >= self.max_lines or len(raw) > self.max_line_bytes:
                self._gap("inventory_budget", path, "physical-line budget exhausted; this source projection is pending")
                return tuple(records), False
            self._lines += 1
            try:
                row = _json(raw)
                if type(row) is not dict:
                    row = None
            except (UnicodeError, ValueError, RecursionError, OverflowError):
                row = None
            records.append(RawInventoryRecord(len(records) + 1, hashlib.sha256(raw).hexdigest(), row))
        return tuple(records), True

    def resolve(self, manifest, index):
        _record(manifest, ProviderArtifact, "capture manifest")
        _record(index, ProviderArtifact, "normalization index")
        try:
            return self._resolve(manifest, index)
        except (TypeError, AttributeError, KeyError, RecursionError, OverflowError) as error:
            raise ValueError("invalid inventory structure: " + str(error)) from error

    def _resolve(self, manifest, index):
        _record(manifest, ProviderArtifact, "capture manifest")
        _record(index, ProviderArtifact, "normalization index")
        self._seen, self._gaps, self._bytes, self._lines = {}, [], 0, 0
        document = self._document(manifest, "manifest", MANIFEST_SCHEMA)
        if document is None:
            return InventoryResolution((), tuple(self._gaps), False)
        _keys(document, ("schema", "schema_version", "run_metadata", "streams"), "manifest")
        if document["schema"] != MANIFEST_SCHEMA or type(document["schema_version"]) is not int or document["schema_version"] != 1:
            raise ValueError("unsupported capture manifest schema/version")
        streams = []
        for number, stream in enumerate(_array(document["streams"], "streams")):
            path = f"manifest.streams[{number}]"
            _keys(stream, ("key", "raw", "profile", "scope", "metadata"), path)
            _text(stream["key"], path + ".key")
            _text(stream["profile"], path + ".profile")
            raw = _artifact(stream["raw"], path + ".raw")
            scope = self._scope(stream["scope"], path + ".scope")
            metadata = tuple(_artifact(item, path + ".metadata") for item in _array(stream["metadata"], path + ".metadata"))
            streams.append((stream["key"], raw, stream["profile"], scope, metadata))
        if len({row[0] for row in streams}) != len(streams):
            raise ValueError("capture manifest stream keys must be unique")
        if not streams:
            self._gap("inventory_sources_empty", "manifest", "empty source declaration is not an empty physical writer universe")
        placeholders = tuple(ResolvedSource(key, raw, (), None, None, None, None, False)
                             for key, raw, *_ in streams)
        indexed = self._document(index, "index", INDEX_SCHEMA)
        if indexed is None:
            return InventoryResolution(placeholders, tuple(self._gaps), False)
        _keys(indexed, ("schema", "schema_version", "manifest", "entries"), "index")
        if indexed["schema"] != INDEX_SCHEMA or type(indexed["schema_version"]) is not int or indexed["schema_version"] != 1:
            raise ValueError("unsupported normalization index schema/version")
        expected = _artifact(indexed["manifest"], "index.manifest")
        if (expected.sha256, expected.schema, expected.size_bytes) != (manifest.sha256, manifest.schema, manifest.size_bytes):
            raise ValueError("normalization index binds another capture manifest")
        entries = {}
        for entry in _array(indexed["entries"], "index.entries"):
            _keys(entry, ("stream", "projection"), "index.entry")
            _text(entry["stream"], "index stream")
            if entry["stream"] in entries:
                raise ValueError("duplicate normalization entry")
            entries[entry["stream"]] = entry["projection"]
        if set(entries) != {row[0] for row in streams}:
            raise ValueError("normalization index must account for every manifest stream exactly")
        for item in _array(document["run_metadata"], "run_metadata"):
            self._metadata(_artifact(item, "run_metadata"), "run_metadata", collector=False)
        resolved = []
        implementation = None
        for key, raw_artifact, profile, scope, metadata in streams:
            path = "sources[" + key + "]"
            if not metadata:
                self._gap("inventory_metadata_missing", path, "collector boundary/loss metadata was not provided")
            for item in metadata:
                self._metadata(item, path + ".metadata", collector=True)
            projection = entries[key]
            if type(projection) is not dict:
                raise ValueError(path + ": invalid projection")
            if projection.get("kind") == "unresolved":
                _keys(projection, ("kind", "reason"), path)
                _text(projection["reason"], path)
                self._gap("inventory_projection_unresolved", path, projection["reason"])
                resolved.append(ResolvedSource(key, raw_artifact, (), None, None, None, None, False))
                continue
            _keys(projection, ("kind", "recipe", "bundle", "coverage"), path)
            if projection["kind"] != "normalized":
                raise ValueError(path + ": unknown projection variant")
            recipe = projection["recipe"]
            _keys(recipe, ("profile", "version", "implementation", "source_label", "namespace"), path + ".recipe")
            for name in ("profile", "source_label", "namespace"):
                _text(recipe[name], path + ".recipe." + name)
            if type(recipe["version"]) is not int or recipe["version"] <= 0:
                raise ValueError("recipe version must be a positive exact integer")
            _keys(recipe["implementation"], ("path", "fingerprint"), path + ".implementation")
            for name in ("path", "fingerprint"):
                _text(recipe["implementation"][name], "recipe implementation " + name)
            declared = SourceVersion(**recipe["implementation"])
            bundle_artifact = _artifact(projection["bundle"], path + ".bundle")
            coverage_artifact = _artifact(projection["coverage"], path + ".coverage")
            if bundle_artifact.schema != IRBundle.SCHEMA or coverage_artifact.schema != COVERAGE_SCHEMA:
                raise ValueError(path + ": normalized artifact schema contradicts its required profile")
            if implementation is None:
                implementation = normalizer_implementation()
            if (profile != "SCAR_TRACE_SESSION_V1" or recipe["profile"] != "SCAR_NORMALIZE_V2"
                    or recipe["version"] != 1 or declared != implementation):
                self._gap("inventory_recipe_unsupported", path, "capture/normalizer recipe implementation is not supported; no supplied code is executed")
                resolved.append(ResolvedSource(key, raw_artifact, (), None, None, None, None, False))
                continue
            if raw_artifact.schema != 'scar.trace.raw-jsonl':
                raise ValueError(path + ': raw artifact schema contradicts the supported capture profile')
            raw = self._payload(raw_artifact, path + ".raw")
            if raw is None:
                resolved.append(ResolvedSource(key, raw_artifact, (), None, None, None, None, False))
                continue
            records, complete = self._records(raw, path)
            if not complete:
                resolved.append(ResolvedSource(key, raw_artifact, records, None, None, None, None, False))
                continue
            if scope is not None:
                for record in records:
                    meta = None if record.payload is None else record.payload.get("metadata")
                    pid = meta.get("process_id") if type(meta) is dict else None
                    if type(pid) is int and pid != scope.process_id:
                        raise ValueError(path + ": raw process ID conflicts with declared provider scope")
                    if type(pid) is not int:
                        self._gap('inventory_process_scope_unresolved', f'{path}.raw[{record.line}]',
                                  'raw process ID is absent or not an exact integer; it is not coerced to provider scope')
            bundle_document = self._document(bundle_artifact, path + ".bundle", IRBundle.SCHEMA)
            coverage = self._document(coverage_artifact, path + ".coverage", COVERAGE_SCHEMA)
            if bundle_document is None or coverage is None:
                resolved.append(ResolvedSource(key, raw_artifact, records, None, None, None, None, False))
                continue
            bundle = bundle_from_dict(bundle_document)
            from scar.trace.normalize_v2 import normalize_bytes
            replay = normalize_bytes(raw, source=recipe["source_label"], namespace=recipe["namespace"],
                                     max_lines=self.max_lines, max_line_bytes=self.max_line_bytes)
            if (canonical_json(replay.bundle) != canonical_json(bundle_document)
                    or canonical_json(replay.coverage) != canonical_json(coverage)):
                raise ValueError(path + ": normalization projection does not match exact raw replay")
            if any(record.payload is None for record in records):
                self._gap("inventory_invalid_raw", path, "source retains invalid/nonobject physical JSONL rows")
            if any(coverage["status_counts"][status] for status in ("ambiguous", "opaque", "unmatched", "invalid")):
                self._gap("inventory_projection_gaps", path, "normalizer retains ambiguous/opaque/unmatched/invalid source rows")
            resolved.append(ResolvedSource(key, raw_artifact, records, bundle,
                external_artifact(bundle.evidence, "inventory:" + key + ":evidence"),
                external_artifact(bundle.values, "inventory:" + key + ":values"),
                external_artifact(bundle.semantic, "inventory:" + key + ":semantic"), True))
        self._gap("inventory_capture_unverified", "manifest",
                  "input source set/format accounting does not prove all runtime writes, aliases, processes or windows captured")
        self._gap("inventory_alias_coverage_unverified", "manifest",
                  "format projection has no complete foreign/shared-storage alias-write inventory")
        return InventoryResolution(tuple(resolved), tuple(self._gaps), bool(resolved) and all(row.projection_replayed for row in resolved))


def build_inventory(sources, *, scopes=None, metadata=None):
    """Seal explicitly supplied source bytes, not a complete physical execution.

    The small offline builder returns (manifest, index, payload catalog). It
    neither launches a program nor derives source membership from work rows.
    Recipe source_label/namespace are ``inventory:`` plus the original key.
    """
    _exact(sources, dict, "source bytes")
    scopes = {} if scopes is None else scopes
    metadata = {} if metadata is None else metadata
    for mapping in (scopes, metadata):
        _exact(mapping, dict, "source metadata/scopes")
        if not set(mapping) <= set(sources):
            raise ValueError("metadata/scope references another source key")
    payloads, streams, entries = {}, [], []

    def pack(payload, schema, uri):
        artifact = ProviderArtifact(uri, hashlib.sha256(payload).hexdigest(), len(payload), schema)
        payloads[artifact.sha256] = payload
        return artifact

    def document(value, schema, uri):
        return pack(canonical_json(value).encode("utf-8"), schema, uri)

    from scar.trace.normalize_v2 import normalize_bytes
    implementation = normalizer_implementation()
    for key, raw in sources.items():
        _text(key, "source key")
        _exact(raw, bytes, "source bytes")
        label = "inventory:" + key
        raw_artifact = pack(raw, "scar.trace.raw-jsonl", label + ":raw")
        scope = scopes.get(key)
        if scope is None:
            scope_json = {"kind": "missing", "reason": "input bytes do not authenticate a runtime scope"}
        else:
            _record(scope, ProviderRunScope, "source provider scope")
            scope_json = {"kind": "provider", "value": {
                name: getattr(scope, name) for name in ("run", "process_id", "window", "clock", "thread_id")}}
        meta_refs = []
        if key in metadata:
            _exact(metadata[key], dict, "collector metadata")
            meta_refs.append(artifact_json(document(metadata[key], "scar.collector-metadata", label + ":metadata")))
        streams.append({"key": key, "raw": artifact_json(raw_artifact), "profile": "SCAR_TRACE_SESSION_V1",
                        "scope": scope_json, "metadata": meta_refs})
        normalized = normalize_bytes(raw, source=label, namespace=label)
        bundle = document(normalized.bundle.to_dict(), IRBundle.SCHEMA, label + ":bundle")
        coverage = document(normalized.coverage, COVERAGE_SCHEMA, label + ":coverage")
        entries.append({"stream": key, "projection": {"kind": "normalized", "recipe": {
            "profile": "SCAR_NORMALIZE_V2", "version": 1,
            "implementation": {"path": implementation.path, "fingerprint": implementation.fingerprint},
            "source_label": label, "namespace": label},
            "bundle": artifact_json(bundle), "coverage": artifact_json(coverage)}})
    manifest = document({"schema": MANIFEST_SCHEMA, "schema_version": 1,
                         "run_metadata": [], "streams": streams}, MANIFEST_SCHEMA, "inventory:manifest")
    index = document({"schema": INDEX_SCHEMA, "schema_version": 1,
                      "manifest": artifact_json(manifest), "entries": entries}, INDEX_SCHEMA, "inventory:index")
    return manifest, index, payloads


__all__ = ["InventoryGap", "RawInventoryRecord", "ResolvedSource", "InventoryResolution",
           "InventoryResolver", "artifact_json", "normalizer_implementation", "build_inventory",
           "MANIFEST_SCHEMA", "INDEX_SCHEMA"]
