"""Join canonical native input ports to retained provider metadata paths.

This is a receipt-bound view over two existing sources.  It does not create
operations, values, or content versions: matches connect an original native
input port to the retained metadata leaf at the same ETO locator and boxed
input path.
"""
from __future__ import annotations

from dataclasses import dataclass, fields
from hashlib import sha256
from io import BytesIO
import gzip
import json
import os
from pathlib import Path
import re
import sqlite3
import stat
import tempfile
import time
from typing import Any
import zlib

from scar.ir.execution.fragment_relations import EvidenceInstanceRef
from scar.ir.execution.ids import DenotationID, OperationOccurrenceID, ValueOccurrenceID
from scar.ir.execution.content import NativeInputRef
from scar.ir.execution.coordinates import UseOccurrence
from scar.ir.program.providers import ProviderArtifact, ProviderFactReference
from scar.ir.record_codec import decode, encode, loads


NAVIGATION_SCHEMA = "scar.native-input-port-navigation"
METADATA_SCHEMA = "scar.native-input-association-index"
PROFILE = "NATIVE_DECLARATION_INPUT_METADATA_JOIN_V1"
_NODE_LOCATOR = re.compile(r"^#/nodes/(0|[1-9][0-9]*)$")


def _valid_metadata_disposition(canonical_status: str, association: str) -> bool:
    """Match the two independent dispositions emitted by native_input_index.finalize."""
    return ((canonical_status == "CANONICAL_BOUNDARY_AVAILABLE"
             and association == "ASSOCIATED")
            or (canonical_status == "CANONICAL_NATIVE_BOUNDARY_UNAVAILABLE"
                and association in ("ASSOCIATED", "CANONICAL_NATIVE_BOUNDARY_UNAVAILABLE")))


def _need(condition: bool, message: str) -> None:
    if not condition:
        raise ValueError(message)


def _canonical(value: Any) -> bytes:
    return json.dumps(value, sort_keys=True, separators=(",", ":"),
                      ensure_ascii=False, allow_nan=False).encode("utf-8")


def _stamp(value: os.stat_result) -> tuple[int, int, int, int, int]:
    return (value.st_dev, value.st_ino, value.st_size, value.st_mtime_ns,
            value.st_ctime_ns)


def _read_regular(path: Path, maximum: int) -> bytes:
    flags = os.O_RDONLY | os.O_CLOEXEC | os.O_NONBLOCK | os.O_NOFOLLOW
    fd = os.open(path, flags)
    try:
        before = os.fstat(fd)
        _need(stat.S_ISREG(before.st_mode) and 0 <= before.st_size <= maximum,
              "input must be a bounded regular nonsymlink file")
        with os.fdopen(fd, "rb") as stream:
            fd = -1
            raw = stream.read(maximum + 1)
            after = os.fstat(stream.fileno())
        _need(len(raw) == before.st_size and _stamp(before) == _stamp(after),
              "input changed during read")
        return raw
    finally:
        if fd >= 0:
            os.close(fd)


def _read_artifact(artifact: ProviderArtifact, *, schema: str,
                   maximum: int) -> tuple[bytes, dict[str, Any]]:
    _need(type(artifact) is ProviderArtifact and artifact.schema == schema,
          "typed source artifact required: " + schema)
    artifact.__post_init__()
    path = Path(artifact.uri)
    _need(path.is_absolute() and path.resolve() == path and not path.is_symlink(),
          "artifact URI must be absolute, canonical, and nonsymlink")
    raw = _read_regular(path, min(maximum, artifact.size_bytes))
    _need(len(raw) == artifact.size_bytes and sha256(raw).hexdigest() == artifact.sha256,
          "artifact bytes differ from receipt")
    doc = loads(raw.decode("utf-8"))
    _need(type(doc) is dict and doc.get("schema") == schema,
          "artifact schema differs from receipt")
    return raw, doc


@dataclass(frozen=True, slots=True)
class NativeDeclarationInputBudget:
    max_navigation_manifest_bytes: int = 16_000_000
    max_metadata_manifest_bytes: int = 16_000_000
    max_chunk_stored_bytes: int = 8_100_000
    max_chunk_decoded_bytes: int = 8_000_000
    max_stored_bytes: int = 80_000_000
    max_decoded_bytes: int = 1_500_000_000
    max_rows: int = 400_000
    max_leaves: int = 500_000
    max_record_bytes: int = 4_000_000
    max_scratch_bytes: int = 1_000_000_000
    max_seconds: int = 900

    def __post_init__(self) -> None:
        if any(type(getattr(self, name)) is not int or getattr(self, name) <= 0
               for name in self.__dataclass_fields__):
            raise ValueError("native declaration input budgets must be positive exact integers")


@dataclass(frozen=True, slots=True)
class NativeDeclarationInputMetadataPort:
    """One existing canonical input port and its exact retained metadata leaf."""

    native_instance: EvidenceInstanceRef
    invocation: OperationOccurrenceID
    input: NativeInputRef
    value: ValueOccurrenceID
    use_occurrence: UseOccurrence
    denotation: DenotationID
    boxed_port_row: ProviderFactReference
    original_input: ProviderFactReference
    native_path: tuple[int, ...]
    status: str
    metadata_index_row: int | None
    prior_canonical_status: str | None
    metadata_leaf: ProviderFactReference | None
    provider_epoch_status: str | None
    provider_epoch: ProviderFactReference | None
    # Absent in earlier serialized DTOs; a new match records it separately
    # from the containing native row's canonical status.
    prior_metadata_association: str | None = None

    def __post_init__(self) -> None:
        for name, cls in (("native_instance", EvidenceInstanceRef),
                          ("invocation", OperationOccurrenceID),
                          ("input", NativeInputRef),
                          ("value", ValueOccurrenceID),
                          ("use_occurrence", UseOccurrence),
                          ("denotation", DenotationID),
                          ("boxed_port_row", ProviderFactReference),
                          ("original_input", ProviderFactReference)):
            if type(getattr(self, name)) is not cls:
                raise TypeError("native input metadata join requires typed " + name)
        if type(self.native_path) is not tuple or any(type(v) is not int or v < 0
                                                       for v in self.native_path):
            raise TypeError("native boxed path must be an integer tuple")
        if self.status not in ("MATCHED_EXACT_INPUT_PATH", "NO_RETAINED_METADATA_ROW",
                               "NO_METADATA_LEAF_AT_NATIVE_PATH"):
            raise ValueError("unsupported native input metadata join status")
        if (self.use_occurrence.operation != self.invocation
                or self.use_occurrence.value != self.value):
            raise ValueError("native input ValueOccurrence/UseOccurrence relation differs")
        matched = self.status == "MATCHED_EXACT_INPUT_PATH"
        if matched != (self.metadata_index_row is not None and self.metadata_leaf is not None
                       and self.prior_canonical_status is not None):
            raise ValueError("matched metadata fields disagree with join status")
        if not matched and self.prior_metadata_association is not None:
            raise ValueError("unmatched metadata join has a leaf association")
        if (matched and self.prior_metadata_association is not None
                and not _valid_metadata_disposition(self.prior_canonical_status,
                                                    self.prior_metadata_association)):
            raise ValueError("native row and metadata leaf dispositions are inconsistent")


def decode_native_declaration_input_metadata_port(value: dict[str, Any]
                                                   ) -> NativeDeclarationInputMetadataPort:
    """Decode the current DTO plus the previous wire shape (association=None)."""
    names = {item.name for item in fields(NativeDeclarationInputMetadataPort)}
    _need(type(value) is dict, "native declaration input DTO must be a wire object")
    if set(value) == names - {"prior_metadata_association"}:
        value = {**value, "prior_metadata_association": None}
    _need(set(value) == names, "native declaration input DTO fields differ")
    return decode(NativeDeclarationInputMetadataPort, value)


@dataclass(frozen=True, slots=True)
class NativeDeclarationInputFragment:
    fragment: ProviderArtifact
    view: object
    input_ports: tuple[NativeDeclarationInputMetadataPort, ...]
    navigation: ProviderArtifact
    metadata_index: ProviderArtifact
    measurements: dict[str, int | float]


class NativeDeclarationInputSession:
    """One verified metadata-row pass, then ordered fragment joins.

    The SQLite file is disposable lookup state only.  Stored facts remain the
    old association-index rows and leaves; the join key is the full ETO
    ProviderArtifact receipt, original ``#/nodes/N`` locator, and boxed path.
    """

    def __init__(self, navigation: ProviderArtifact, *, budget=None):
        self.budget = budget or NativeDeclarationInputBudget()
        if type(self.budget) is not NativeDeclarationInputBudget:
            raise TypeError("typed native declaration input budget required")
        self.budget.__post_init__()
        self.navigation_artifact = navigation
        self.navigation_raw, self.navigation_doc = _read_artifact(
            navigation, schema=NAVIGATION_SCHEMA,
            maximum=self.budget.max_navigation_manifest_bytes)
        doc = self.navigation_doc
        _need(type(doc.get("schema_version")) is int and doc["schema_version"] == 1
              and doc.get("profile") == "SCAR_NATIVE_INPUT_CANONICAL_PARENT_NAVIGATION_V1"
              and doc.get("status") == "PUBLISHED_WITH_OPEN"
              and doc.get("whole_model_established") is False
              and doc.get("logical_content_established") is False
              and doc.get("alias_established") is False
              and doc.get("resource_ready_established") is False,
              "unsupported retained native-input navigation receipt")
        self.metadata_artifact = decode(ProviderArtifact, doc["metadata"])
        self.metadata_raw, self.metadata_doc = _read_artifact(
            self.metadata_artifact, schema=METADATA_SCHEMA,
            maximum=self.budget.max_metadata_manifest_bytes)
        self._validate_manifests()
        self.started = time.monotonic()
        self._stored = len(self.navigation_raw) + len(self.metadata_raw)
        self._decoded = self._stored
        self._rows = 0
        self._leaves = 0
        self._source_artifact_key: str | None = None
        self._prepared = False
        self._closed = False
        self._temp = tempfile.TemporaryDirectory(prefix="scar-native-declaration-inputs-")
        self._db = sqlite3.connect(str(Path(self._temp.name) / "metadata-lookup.sqlite"))
        self._db.execute("PRAGMA journal_mode=OFF")
        self._db.execute("PRAGMA synchronous=OFF")
        self._db.execute("PRAGMA temp_store=FILE")
        self._db.execute("PRAGMA page_size=4096")
        self._db.execute("PRAGMA max_page_count=" +
                         str(self.budget.max_scratch_bytes // 4096))
        self._db.execute("""CREATE TABLE native_rows (
            locator TEXT NOT NULL,
            row_index INTEGER NOT NULL, node_id INTEGER, canonical_status TEXT,
            PRIMARY KEY (locator)) WITHOUT ROWID""")
        self._db.execute("""CREATE TABLE metadata_leaves (
            locator TEXT NOT NULL, path_key TEXT NOT NULL,
            row_index INTEGER NOT NULL, leaf_refs BLOB NOT NULL,
            canonical_status TEXT NOT NULL,
            PRIMARY KEY (locator, path_key)) WITHOUT ROWID""")

    def _validate_manifests(self) -> None:
        nav = self.navigation_doc
        metadata = self.metadata_doc
        _need(type(metadata.get("schema_version")) is int and metadata["schema_version"] == 1
              and metadata.get("profile") == "SCAR_NATIVE_INPUT_METADATA_ASSOCIATION_INDEX_V1"
              and metadata.get("status") == "PUBLISHED_WITH_OPEN"
              and metadata.get("whole_model_established") is False
              and metadata.get("logical_content_established") is False
              and metadata.get("alias_established") is False
              and metadata.get("resource_ready_established") is False,
              "unsupported native-input metadata association index")
        _need(nav.get("metadata") == encode(self.metadata_artifact)
              and nav.get("run") == metadata.get("run")
              and nav.get("process") == metadata.get("process")
              and nav.get("counts") == metadata.get("counts"),
              "navigation/metadata parent identity differs")
        nav_rows = nav.get("navigation", {})
        counts = metadata.get("counts", {})
        _need(type(nav_rows) is dict
              and nav_rows.get("scoped_associations") == counts.get("associated_metadata_paths")
              and type(metadata.get("tables")) is dict
              and type(metadata["tables"].get("rows")) is dict,
              "navigation row table/counts differ")
        rows = metadata["tables"]["rows"]
        _need(type(rows.get("records")) is int and rows["records"] == counts.get("retained_rows")
              and type(rows.get("chunks")) is list,
              "metadata retained-row denominator differs")
        self.row_table = rows

    def _check(self) -> None:
        _need(not self._closed, "native declaration input session is closed")
        _need(time.monotonic() - self.started <= self.budget.max_seconds,
              "native declaration input session wall budget exceeded")
        _need(self._stored <= self.budget.max_stored_bytes
              and self._decoded <= self.budget.max_decoded_bytes,
              "native declaration input byte budget exceeded")

    def __enter__(self):
        try:
            self.prepare_metadata_rows()
            return self
        except BaseException:
            self.close()
            raise

    def __exit__(self, *exc):
        self.close()

    def close(self) -> None:
        if self._closed:
            return
        self._closed = True
        try:
            self._db.close()
        finally:
            self._temp.cleanup()

    def prepare_metadata_rows(self) -> dict[str, int | float]:
        """Verify and index all retained metadata rows once for multi-shard use."""
        self._check()
        if self._prepared:
            return self.measurements
        root = Path(self.metadata_artifact.uri).parent.resolve()
        chunks = self.row_table["chunks"]
        expected_first = 0
        for chunk in chunks:
            self._check()
            required = {"path", "raw_bytes", "raw_sha256", "rows", "first_ordinal",
                        "first_row", "last_row", "size_bytes", "sha256"}
            _need(type(chunk) is dict and required <= set(chunk),
                  "metadata row chunk header incomplete")
            _need(type(chunk["first_ordinal"]) is int
                  and chunk["first_ordinal"] == expected_first
                  and type(chunk["rows"]) is int and chunk["rows"] > 0
                  and chunk["rows"] <= 1000
                  and type(chunk["raw_bytes"]) is int
                  and 0 < chunk["raw_bytes"] <= self.budget.max_chunk_decoded_bytes
                  and type(chunk["size_bytes"]) is int
                  and 0 < chunk["size_bytes"] <= self.budget.max_chunk_stored_bytes,
                  "metadata row chunk range or size differs")
            relative = Path(chunk["path"])
            _need(not relative.is_absolute() and ".." not in relative.parts,
                  "metadata row chunk path escapes its manifest")
            path = root / relative
            _need(path.resolve().is_relative_to(root),
                  "metadata row chunk resolves outside its manifest")
            stored = _read_regular(path, self.budget.max_chunk_stored_bytes)
            _need(len(stored) == chunk["size_bytes"]
                  and sha256(stored).hexdigest() == chunk["sha256"],
                  "metadata row chunk stored receipt differs")
            with gzip.GzipFile(fileobj=BytesIO(stored), mode="rb") as stream:
                decoded = stream.read(chunk["raw_bytes"] + 1)
            _need(len(decoded) == chunk["raw_bytes"]
                  and sha256(decoded).hexdigest() == chunk["raw_sha256"],
                  "metadata row chunk decoded receipt differs")
            self._stored += len(stored)
            self._decoded += len(decoded)
            _need(self._stored <= self.budget.max_stored_bytes
                  and self._decoded <= self.budget.max_decoded_bytes,
                  "metadata row scan exceeds byte budget")
            lines = decoded.splitlines()
            _need(len(lines) == chunk["rows"], "metadata row chunk count differs")
            for line in lines:
                _need(len(line) <= self.budget.max_record_bytes,
                      "metadata row exceeds record bound")
                row = loads(line.decode("utf-8"))
                _need(type(row) is dict and type(row.get("index")) is int
                      and row["index"] > 0,
                      "metadata row record shape differs")
                original = row.get("original_node")
                if original is not None:
                    _need(type(original) is dict and type(original.get("artifact")) is dict
                          and type(original.get("locator")) is str,
                          "metadata original ETO reference malformed")
                    match = _NODE_LOCATOR.fullmatch(original["locator"])
                    _need(match is not None, "metadata original ETO locator is not a node")
                    artifact_key = _canonical(original["artifact"]).decode("utf-8")
                    _need(original["artifact"].get("schema") == "pytorch.execution-trace.v1",
                          "metadata original source is not a pinned ETO artifact")
                    _need(self._source_artifact_key in (None, artifact_key),
                          "metadata row index mixes original ETO artifacts")
                    self._source_artifact_key = artifact_key
                    node_id = row.get("node_id")
                    _need(node_id is None or (type(node_id) is int and node_id >= 0),
                          "metadata node id must be exact or null")
                    status = row.get("canonical_status", "UNSPECIFIED")
                    _need(type(status) is str, "metadata canonical status malformed")
                    self._db.execute("INSERT INTO native_rows VALUES(?,?,?,?)",
                        (original["locator"], row["index"], node_id, status))
                    leaves = row.get("metadata", [])
                    _need(type(leaves) is list, "metadata leaves must be an ordered list")
                    seen_paths = set()
                    for leaf in leaves:
                        _need(type(leaf) is dict and type(leaf.get("path")) is list
                              and all(type(v) is int and v >= 0 for v in leaf["path"])
                              and type(leaf.get("metadata")) is dict
                              and type(leaf.get("source")) is dict,
                              "metadata leaf shape differs")
                        path_key = _canonical(leaf["path"]).decode("utf-8")
                        _need(path_key not in seen_paths, "duplicate metadata leaf path in row")
                        seen_paths.add(path_key)
                        _need(self._leaves < self.budget.max_leaves,
                              "metadata leaf count exceeds budget")
                        _need(type(leaf.get("provider_epoch")) is dict
                              and type(leaf.get("source")) is dict,
                              "metadata leaf lacks its retained source/epoch references")
                        refs = {"source": leaf["source"],
                                "provider_epoch": leaf["provider_epoch"],
                                "association": leaf.get("association", status)}
                        packed_refs = zlib.compress(_canonical(refs), 1)
                        self._db.execute("INSERT INTO metadata_leaves VALUES(?,?,?,?,?)",
                            (original["locator"], path_key, row["index"], packed_refs, status))
                        self._leaves += 1
                self._rows += 1
                _need(self._rows <= self.budget.max_rows,
                      "metadata row count exceeds budget")
            expected_first += chunk["rows"]
            _need(expected_first <= self.budget.max_rows,
                  "metadata row denominator exceeds budget")
            self._db.commit()
            page_count = self._db.execute("PRAGMA page_count").fetchone()[0]
            _need(page_count * 4096 <= self.budget.max_scratch_bytes,
                  "temporary metadata lookup exceeds scratch budget")
        _need(self._rows == self.row_table["records"]
              and expected_first == self.row_table["records"],
              "metadata row scan did not cover its full declared denominator")
        expected_leaves = self.metadata_doc.get("counts", {}).get("metadata_paths")
        _need(self._leaves == expected_leaves,
              "metadata leaf count differs from the original index denominator")
        self._prepared = True
        self.measurements = {
            "metadata_rows": self._rows,
            "metadata_leaves": self._leaves,
            "stored_bytes": self._stored,
            "decoded_bytes": self._decoded,
            "elapsed_seconds": time.monotonic() - self.started,
            "temporary_index_bytes": self._db.execute("PRAGMA page_count").fetchone()[0] * 4096,
        }
        return self.measurements

    @staticmethod
    def _source_ref(occurrence):
        point = occurrence.completion.point
        source = point.source
        _need(type(source) is ProviderFactReference
              and source.artifact.schema == "pytorch.execution-trace.v1",
              "native declaration lacks its original ETO source point")
        return source

    @classmethod
    def _source_sha256(cls, occurrence):
        return cls._source_ref(occurrence).artifact.sha256

    @classmethod
    def _source_uri(cls, occurrence):
        return cls._source_ref(occurrence).artifact.uri

    @classmethod
    def _source_ordinal(cls, occurrence):
        source = cls._source_ref(occurrence)
        match = re.fullmatch(r"#/nodes/(0|[1-9][0-9]*)", source.locator)
        _need(match is not None, "native declaration source is not an exact ETO node")
        return int(match.group(1))

    @classmethod
    def _input_path(cls, source: ProviderFactReference) -> tuple[str, tuple[int, ...]]:
        match = re.fullmatch(r"(#/nodes/(0|[1-9][0-9]*))/inputs/values/((?:0|[1-9][0-9]*)(?:/(?:0|[1-9][0-9]*))*)",
                             source.locator)
        _need(match is not None, "native input source is not an exact ordered ETO value path")
        return match.group(1), tuple(int(part) for part in match.group(3).split("/"))

    def join_fragment(self, view) -> tuple[NativeDeclarationInputMetadataPort, ...]:
        """Join a normally read declaration view to original input metadata leaves."""
        self._check()
        if not self._prepared:
            self.prepare_metadata_rows()
        _need(type(view.occurrences) is tuple and type(view.execution.denotations) is tuple,
              "normal native declaration view required")
        _need(getattr(view.validation, "valid", False) is True,
              "native declaration view did not pass its normal reader")
        _need(len(view.execution.runs) == 1
              and encode(view.execution.runs[0].id) == self.navigation_doc["run"]
              and any(encode(process.id) == self.navigation_doc["process"]
                      for process in view.execution.processes),
              "native declaration fragment Run/process differs from metadata index")
        denotations: dict[NativeInputRef, Any] = {}
        for item in view.execution.denotations:
            _need(type(item.basis) is NativeInputRef and item.basis not in denotations,
                  "native declaration input denotation is absent or ambiguous")
            denotations[item.basis] = item
        uses: dict[tuple[OperationOccurrenceID, ValueOccurrenceID], UseOccurrence] = {}
        for use in view.execution.uses:
            if type(use.value) is not ValueOccurrenceID:
                continue
            key = (use.operation, use.value)
            _need(key not in uses, "native declaration ValueOccurrence has ambiguous UseOccurrence")
            uses[key] = use
        joined = []
        for occurrence in view.occurrences:
            source = self._source_ref(occurrence)
            ordinal = self._source_ordinal(occurrence)
            source_locator = source.locator
            _need(source_locator == f"#/nodes/{ordinal}",
                  "native declaration source locator differs from its exact ordinal")
            port_row = occurrence.ports
            _need(port_row.artifact.schema == "scar.native-boxed-port-shard"
                  and port_row.pointer.startswith("#/value/rows/"),
                  "native declaration lacks its verified original boxed-port row locator")
            row_number = port_row.pointer.rsplit("/", 1)[-1]
            _need(row_number.isdecimal(), "native boxed-port row locator malformed")
            for position, native_input in enumerate(occurrence.inputs):
                denotation = denotations.get(native_input)
                _need(denotation is not None and native_input.position == position
                      and denotation.source.artifact == source.artifact,
                      "canonical input, ValueOccurrence, and original ETO artifact do not align")
                use = uses.get((occurrence.invocation, denotation.value))
                _need(use is not None,
                      "canonical input ValueOccurrence has no original operation UseOccurrence")
                node_locator, native_path = self._input_path(denotation.source)
                _need(node_locator == source_locator,
                      "canonical input source belongs to a different ETO node")
                # The normal fragment reader has checked this row pointer against
                # the original port shard and execution construction. Position
                # selects the input among its ordered input ports.
                port_reference = ProviderFactReference(port_row.artifact, port_row.pointer)
                common = dict(native_instance=occurrence.native,
                    invocation=occurrence.invocation, input=native_input,
                    value=denotation.value, use_occurrence=use,
                    denotation=denotation.id,
                    boxed_port_row=port_reference, original_input=denotation.source,
                    native_path=native_path)
                source_artifact_key = _canonical(encode(source.artifact)).decode("utf-8")
                _need(source_artifact_key == self._source_artifact_key,
                      "declaration ETO artifact differs from retained metadata source")
                locator = source.locator
                node = self._db.execute(
                    "SELECT row_index,canonical_status FROM native_rows "
                    "WHERE locator=?", (locator,)).fetchall()
                _need(len(node) <= 1, "original ETO node has ambiguous retained metadata rows")
                if not node:
                    joined.append(NativeDeclarationInputMetadataPort(**common,
                        status="NO_RETAINED_METADATA_ROW", metadata_index_row=None,
                        prior_canonical_status=None, metadata_leaf=None,
                        provider_epoch_status=None, provider_epoch=None))
                    continue
                path_key = _canonical(list(native_path)).decode("utf-8")
                found = self._db.execute(
                    "SELECT row_index,leaf_refs,canonical_status FROM metadata_leaves "
                    "WHERE locator=? AND path_key=?", (locator, path_key)).fetchall()
                _need(len(found) <= 1, "original native input metadata path is ambiguous")
                if not found:
                    joined.append(NativeDeclarationInputMetadataPort(**common,
                        status="NO_METADATA_LEAF_AT_NATIVE_PATH", metadata_index_row=node[0][0],
                        prior_canonical_status=node[0][1], metadata_leaf=None,
                        provider_epoch_status=None, provider_epoch=None))
                    continue
                metadata_row, refs_raw, prior_status = found[0]
                refs = loads(zlib.decompress(bytes(refs_raw)).decode("utf-8"))
                _need(type(refs) is dict and type(refs.get("association")) is str,
                      "retained metadata leaf association is malformed")
                leaf_association = refs["association"]
                _need(_valid_metadata_disposition(prior_status, leaf_association),
                      "retained canonical status/leaf association pair violates native_input_index.finalize")
                metadata_source = decode(ProviderFactReference, refs["source"])
                epoch = refs.get("provider_epoch")
                _need(type(epoch) is dict and type(epoch.get("status")) is str,
                      "provider epoch reference record malformed")
                epoch_source = (decode(ProviderFactReference, epoch["source"])
                                if epoch.get("status") == "OBSERVED_PROVIDER_EPOCH_REFERENCE"
                                else None)
                joined.append(NativeDeclarationInputMetadataPort(**common,
                    status="MATCHED_EXACT_INPUT_PATH", metadata_index_row=metadata_row,
                    prior_canonical_status=prior_status, metadata_leaf=metadata_source,
                    provider_epoch_status=epoch["status"],
                    provider_epoch=epoch_source,
                    prior_metadata_association=leaf_association))
        return tuple(joined)

    # Kept as a small source-compatible alias for development callers.
    join_view = join_fragment

    def read_fragment(self, fragment: ProviderArtifact, *, declaration_budget=None
                      ) -> NativeDeclarationInputFragment:
        """Use the canonical normal reader, then add only metadata-path refs."""
        from scar.analysis.native_declaration_interfaces import read_native_declaration_fragment

        self._check()
        view = read_native_declaration_fragment(fragment, budget=declaration_budget)
        ports = self.join_fragment(view)
        return NativeDeclarationInputFragment(fragment, view, ports,
            self.navigation_artifact, self.metadata_artifact, dict(self.measurements))


def read_native_declaration_inputs(fragment: ProviderArtifact,
        navigation: ProviderArtifact, *, budget=None, declaration_budget=None
        ) -> NativeDeclarationInputFragment:
    """One-fragment convenience; use a session to process many fragments once."""
    with NativeDeclarationInputSession(navigation, budget=budget) as session:
        return session.read_fragment(fragment, declaration_budget=declaration_budget)
