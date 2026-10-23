"""Bounded, source-replayed sidecars for the inventory's existing source layers.

The archive stores the canonical SemanticGraph, SourceSemanticsGraph, and
SourceControlFlowGraph documents. ``source`` binds those documents to the
inventory's per-file snapshot and digest. ``metadata`` describes the rebuild
and its limits; it is not a substitute source graph or a proof of body/runtime
coverage. Reading an archive verifies its stored structure and digest links,
but deliberately does not read source files or replay the whole inventory.
"""
from __future__ import annotations

from dataclasses import dataclass
import errno
import gzip
import hashlib
from io import BytesIO
import json
import os
from pathlib import Path
import re
import shutil
import sys
import tokenize
from typing import Any

from scar.analysis.program_lowering import prepare_source
from scar.ir.control_flow_v2 import SourceControlFlowGraph
from scar.ir.program.inventory import SourceContextDigest
from scar.ir.program.providers import ProviderArtifact, ProviderFactReference
from scar.ir.program.source_references import SourceArtifactLocator
from scar.ir.record_codec import decode, encode, loads as strict_loads
from scar.ir.semantics_v2 import SourceSemanticsGraph, SourceSnapshot
from scar.ir.v2.codec import semantic_from_dict
from scar.ir.v2.semantic import SemanticGraph


_INDEX_NAME = "index.json"
_ARCHIVE_DIR = "archives"
_SCHEMA = "scar.source-layers"
_VERSION = 1
_SHA256 = re.compile(r"^[0-9a-f]{64}$")
_FINGERPRINT = re.compile(r"^sha256:[0-9a-f]{64}$")
_SCOPE = "one source-layer replay per inventory file; no call/body inventory replay"
_METADATA = {
    "source_replay": "REBUILT_AND_MATCHED_INVENTORY_CONTEXT_DIGESTS",
    "whole_program_graph_established": False,
    "fine_state_effects_established": False,
    "transformation_authorized": False,
}


@dataclass(frozen=True, slots=True)
class SourceLayerView:
    snapshot: SourceSnapshot
    context: SourceContextDigest
    semantic: SemanticGraph
    semantics: SourceSemanticsGraph
    control: SourceControlFlowGraph
    metadata: dict[str, Any]
    artifact_locator: SourceArtifactLocator | None = None


def _check_budgets(**budgets: int) -> None:
    for name, value in budgets.items():
        if type(value) is not int or value < 1:
            raise ValueError(f"{name} must be a positive exact integer")


def _canonical(document: Any) -> bytes:
    try:
        return json.dumps(document, sort_keys=True, ensure_ascii=False,
                          separators=(",", ":"), allow_nan=False).encode("utf-8", errors="strict")
    except (TypeError, ValueError, UnicodeEncodeError) as error:
        raise ValueError("source-layer document is not canonical JSON") from error


def _digest(document: Any) -> str:
    return hashlib.sha256(_canonical(document)).hexdigest()


def _read_bounded(path: Path, *, limit: int) -> tuple[bytes, str]:
    """Return decoded bytes and raw-source SHA, bounding both streams."""
    raw_size = 0
    raw_hash = hashlib.sha256()
    raw_chunks: list[bytes] = []
    with path.open("rb") as raw:
        while True:
            block = raw.read(min(1024 * 1024, limit + 1 - raw_size))
            if not block:
                break
            raw_size += len(block)
            if raw_size > limit:
                raise ValueError("input raw-byte budget exceeded")
            raw_hash.update(block)
            raw_chunks.append(block)
    raw_payload = b"".join(raw_chunks)
    chunks: list[bytes] = []
    decoded_size = 0
    source_stream = (gzip.GzipFile(fileobj=BytesIO(raw_payload), mode="rb")
                     if path.suffix == ".gz" else BytesIO(raw_payload))
    with source_stream as stream:
        while True:
            block = stream.read(min(1024 * 1024, limit + 1 - decoded_size))
            if not block:
                break
            decoded_size += len(block)
            if decoded_size > limit:
                raise ValueError("input decoded-byte budget exceeded")
            chunks.append(block)
    return b"".join(chunks), raw_hash.hexdigest()


def _read_file_limited(path: Path, limit: int, detail: str) -> bytes:
    chunks: list[bytes] = []
    size = 0
    with path.open("rb") as stream:
        while True:
            block = stream.read(min(1024 * 1024, limit + 1 - size))
            if not block:
                break
            size += len(block)
            if size > limit:
                raise ValueError(detail)
            chunks.append(block)
    return b"".join(chunks)


def _canonical_absolute_path(value: Any, label: str) -> str:
    if type(value) is not str or not value or "\x00" in value:
        raise ValueError(f"{label} must be a canonical absolute path")
    path = Path(value)
    if not path.is_absolute() or os.path.normpath(value) != value:
        raise ValueError(f"{label} must be a canonical absolute path")
    # Inventory source paths and roots were already resolved at preparation
    # time. Resolve lexically only here; in particular, the sidecar reader
    # must not inspect the caller's source file or follow its symlinks.
    if str(path) != value:
        raise ValueError(f"{label} must be a canonical absolute path")
    return value


def _preflight_resolved_path(value: str, label: str) -> None:
    """Reject symlink/noncanonical aliases before preparing any source."""
    try:
        resolved = Path(value).resolve(strict=False)
    except (OSError, RuntimeError) as error:
        raise ValueError(f"{label} cannot be resolved canonically") from error
    if str(resolved) != value:
        raise ValueError(f"{label} must be a canonical absolute path")


def _validate_snapshot(snapshot: SourceSnapshot) -> None:
    _canonical_absolute_path(snapshot.path, "snapshot path")
    if type(snapshot.fingerprint) is not str or not _FINGERPRINT.fullmatch(snapshot.fingerprint):
        raise ValueError("snapshot fingerprint is malformed")


def _validate_context(context: SourceContextDigest) -> None:
    _canonical_absolute_path(context.namespace_root, "namespace root")
    for name in ("semantic_sha256", "semantics_sha256", "control_sha256"):
        value = getattr(context, name)
        if type(value) is not str or not _SHA256.fullmatch(value):
            raise ValueError(f"context {name} is malformed")


def _preflight_inventory(document: Any, *, max_files: int) -> tuple[int, list[dict[str, Any]]]:
    if type(document) is not dict:
        raise ValueError("inventory header must be an object")
    version = document.get("schema_version")
    if (document.get("schema") != "scar.program-inventory" or type(version) is not int
            or version not in (1, 2, 3, 4, 5, 6, 7, 8)):
        raise ValueError("unsupported inventory schema/version")
    raw_files = document.get("files")
    if type(raw_files) is not list:
        raise ValueError("inventory files must be an array")
    if len(raw_files) > max_files:
        raise ValueError("inventory file count exceeds source-layer budget")

    result: list[dict[str, Any]] = []
    seen: set[str] = set()
    for index, item in enumerate(raw_files):
        if type(item) is not dict or "snapshot" not in item or "context" not in item:
            raise ValueError(f"inventory file {index} lacks snapshot/context")
        snapshot = decode(SourceSnapshot, item["snapshot"])
        _validate_snapshot(snapshot)
        _preflight_resolved_path(snapshot.path, "snapshot path")
        if snapshot.path in seen:
            raise ValueError("inventory contains duplicate source paths")
        seen.add(snapshot.path)

        raw_context = item["context"]
        if raw_context is None:
            # Historical entries without a source-context digest stay in the
            # denominator but cannot be independently bound to a source layer.
            result.append({"snapshot": snapshot, "context": None,
                           "preflight_gap": {"code": "MISSING_CONTEXT",
                                             "detail": "inventory file has no SourceContextDigest"}})
            continue
        context = decode(SourceContextDigest, raw_context)
        _validate_context(context)
        _preflight_resolved_path(context.namespace_root, "namespace root")
        result.append({"snapshot": snapshot, "context": context, "preflight_gap": None})
    return version, result


def _new_row(item: dict[str, Any]) -> dict[str, Any]:
    return {
        "source_path": item["snapshot"].path,
        "snapshot": encode(item["snapshot"]),
        "context": encode(item["context"]) if item["context"] is not None else None,
        "status": "GAP",
        "archive": None,
        "canonical_sha256": None,
        "canonical_bytes": 0,
        "compressed_bytes": 0,
        "gap": item["preflight_gap"],
    }


def _manifest(input_raw_sha256: str, input_decoded_bytes: int, input_schema_version: int,
              rows: list[dict[str, Any]]) -> dict[str, Any]:
    stored = sum(row["status"] == "STORED" for row in rows)
    gaps = len(rows) - stored
    return {
        "schema": _SCHEMA,
        "schema_version": _VERSION,
        "scope": _SCOPE,
        "input": {
            "schema": "scar.program-inventory",
            "schema_version": input_schema_version,
            "raw_sha256": input_raw_sha256,
            "decoded_bytes": input_decoded_bytes,
        },
        "files_total": len(rows),
        "files_stored": stored,
        "files_gapped": gaps,
        "complete": gaps == 0,
        **_METADATA,
        "files": rows,
    }


def _index_reservation(input_raw_sha256: str, input_decoded_bytes: int,
                       input_schema_version: int, items: list[dict[str, Any]]) -> int:
    """Conservatively reserve index space before charging record payloads."""
    rows = []
    for item in items:
        row = _new_row(item)
        row.update(
            status="GAP",
            archive=f"{_ARCHIVE_DIR}/{'f' * 64}.json.gz",
            canonical_sha256="f" * 64,
            canonical_bytes=9_223_372_036_854_775_807,
            compressed_bytes=9_223_372_036_854_775_807,
            gap={"code": "x" * 64, "detail": "x" * 512},
        )
        rows.append(row)
    return len(_canonical(_manifest(input_raw_sha256, input_decoded_bytes,
                                    input_schema_version, rows)))


def _write_gzip_exclusive(path: Path, payload: bytes) -> int:
    created = False
    try:
        with path.open("xb") as raw:
            created = True
            with gzip.GzipFile(filename="", mode="wb", fileobj=raw, mtime=0) as stream:
                stream.write(payload)
        return path.stat().st_size
    except BaseException:
        if created:
            path.unlink(missing_ok=True)
        raise


def _preflight_reuse_archive(
    reuse_dir: Path,
    *,
    input_sha256: str,
    input_decoded_bytes: int,
    input_schema_version: int,
    items: list[dict[str, Any]],
    max_index_bytes: int,
) -> tuple[Path, dict[str, dict[str, Any]]]:
    """Read a prior sidecar index and bind every present row to this input."""
    if reuse_dir.is_symlink() or not reuse_dir.is_dir():
        raise ValueError("reuse source-layer archive must be a real directory")
    index_path = reuse_dir / _INDEX_NAME
    if index_path.is_symlink() or not index_path.is_file():
        raise ValueError("reuse source-layer index is missing or unsafe")
    if index_path.stat().st_size > max_index_bytes:
        raise ValueError("reuse source-layer index byte budget exceeded")
    try:
        index_bytes = _read_file_limited(
            index_path, max_index_bytes, "reuse source-layer index byte budget exceeded")
        document = strict_loads(index_bytes.decode("utf-8", errors="strict"))
    except (OSError, UnicodeError, ValueError, RecursionError) as error:
        raise ValueError("reuse source-layer index is not strict UTF-8 JSON") from error
    if _canonical(document) != index_bytes:
        raise ValueError("reuse source-layer index is not canonical JSON")
    rows = _validate_manifest(document)

    input_meta = document["input"]
    if (input_meta["raw_sha256"] != input_sha256
            or input_meta["decoded_bytes"] != input_decoded_bytes
            or input_meta["schema_version"] != input_schema_version):
        raise ValueError("reuse archive belongs to a different inventory input")

    expected = {item["snapshot"].path: item for item in items}
    if len(rows) > len(expected):
        raise ValueError("reuse archive contains paths outside the current inventory")
    by_path: dict[str, dict[str, Any]] = {}
    for row in rows:
        path = row["source_path"]
        item = expected.get(path)
        if item is None:
            raise ValueError("reuse archive contains a path outside the current inventory")
        snapshot = decode(SourceSnapshot, row["snapshot"])
        context = decode(SourceContextDigest, row["context"]) if row["context"] is not None else None
        if snapshot != item["snapshot"] or context != item["context"]:
            raise ValueError("reuse archive snapshot/context differs from the inventory")
        by_path[path] = row
    return reuse_dir, by_path


def _current_source_matches(snapshot: SourceSnapshot, context: SourceContextDigest) -> bool:
    """Check a cached record against current decoded source and runtime version."""
    if snapshot.python_version != f"{sys.version_info.major}.{sys.version_info.minor}":
        return False
    try:
        source_path = Path(snapshot.path)
        root_path = Path(context.namespace_root)
        if str(source_path.resolve(strict=True)) != snapshot.path:
            return False
        if str(root_path.resolve(strict=True)) != context.namespace_root or not root_path.is_dir():
            return False
        with tokenize.open(str(source_path)) as stream:
            text = stream.read()
    except (OSError, UnicodeError, LookupError, RuntimeError, SyntaxError, ValueError):
        return False
    fingerprint = "sha256:" + hashlib.sha256(text.encode("utf-8")).hexdigest()
    return fingerprint == snapshot.fingerprint


def _link_or_copy_exclusive(source: Path, destination: Path) -> int:
    """Publish an immutable cached archive without replacing an output file."""
    linked = False
    try:
        os.link(source, destination)
        linked = True
        return destination.stat().st_size
    except OSError as error:
        if linked:
            destination.unlink(missing_ok=True)
        if error.errno != errno.EXDEV:
            raise

    created = False
    try:
        with source.open("rb") as source_file, destination.open("xb") as destination_file:
            created = True
            shutil.copyfileobj(source_file, destination_file, length=1024 * 1024)
        return destination.stat().st_size
    except BaseException:
        if created:
            destination.unlink(missing_ok=True)
        raise


def reconstruct_source_layers(
    inventory_path: str | Path,
    out_dir: str | Path,
    *,
    reuse_archive: str | Path | None = None,
    max_input_bytes: int = 256_000_000,
    max_files: int = 256,
    max_record_bytes: int = 64_000_000,
    max_total_bytes: int = 512_000_000,
) -> dict[str, Any]:
    """Rebuild each inventory file's three canonical source layers once.

    The inventory itself is only header-checked and its per-file
    ``snapshot/context`` records are strictly decoded. The call/body inventory
    is not replayed. Global input/path/digest defects fail before output is
    created; source drift and per-file/output-budget failures remain explicit
    rows so the original file denominator is preserved. A prior sidecar may
    supply records only when its inventory identity and per-file records match,
    its archive decodes strictly, and the current source fingerprint, resolved
    path/root, and Python major/minor still match. Such records retain the
    original source-replay evidence; they are not freshly prepared in this
    call. Missing or gapped cache rows are rebuilt normally.
    """
    _check_budgets(max_input_bytes=max_input_bytes, max_files=max_files,
                   max_record_bytes=max_record_bytes, max_total_bytes=max_total_bytes)
    source_inventory = Path(inventory_path)
    if not source_inventory.is_file():
        raise ValueError("inventory input must be a regular file")
    decoded, input_sha256 = _read_bounded(source_inventory, limit=max_input_bytes)
    try:
        document = strict_loads(decoded.decode("utf-8", errors="strict"))
    except (UnicodeError, ValueError, RecursionError) as error:
        raise ValueError("inventory input is not strict UTF-8 JSON") from error
    version, items = _preflight_inventory(document, max_files=max_files)

    reuse_root: Path | None = None
    reuse_rows: dict[str, dict[str, Any]] = {}
    if reuse_archive is not None:
        reuse_root, reuse_rows = _preflight_reuse_archive(
            Path(reuse_archive), input_sha256=input_sha256,
            input_decoded_bytes=len(decoded), input_schema_version=version,
            items=items, max_index_bytes=min(16_000_000, max_input_bytes))

    destination = Path(out_dir)
    if not destination.is_absolute():
        destination = Path.cwd() / destination
    destination = Path(os.path.normpath(str(destination)))
    if destination.exists() or destination.is_symlink():
        raise ValueError("source-layer output directory must be fresh and absent")
    parent = destination.parent

    reservation = _index_reservation(input_sha256, len(decoded), version, items)
    if reservation > max_total_bytes:
        raise ValueError("manifest alone exceeds total-byte budget")
    parent.mkdir(parents=True, exist_ok=True)
    charged = 0
    rows = [_new_row(item) for item in items]
    created = False
    try:
        # Exclusive mkdir reserves the path against concurrent exporters; no
        # existing directory, including an empty one, can be replaced.
        destination.mkdir(exist_ok=False)
        created = True
        archive_dir = destination / _ARCHIVE_DIR
        archive_dir.mkdir(exist_ok=False)

        total_exhausted = False
        for item, row in zip(items, rows):
            if item["preflight_gap"] is not None:
                continue
            if total_exhausted:
                row["gap"] = {"code": "TOTAL_BYTE_BUDGET",
                              "detail": "source replay not attempted after total-byte budget was exhausted"}
                continue
            snapshot: SourceSnapshot = item["snapshot"]
            context: SourceContextDigest = item["context"]
            cached_row = reuse_rows.get(snapshot.path)
            if cached_row is not None and cached_row["status"] == "STORED":
                cached_canonical_bytes = cached_row["canonical_bytes"]
                if cached_canonical_bytes > max_record_bytes:
                    row["gap"] = {"code": "RECORD_BYTE_BUDGET",
                                  "detail": "cached canonical source-layer record exceeds max_record_bytes"}
                    continue
                if reservation + charged + cached_canonical_bytes > max_total_bytes:
                    row["gap"] = {"code": "TOTAL_BYTE_BUDGET",
                                  "detail": "cached source-layer records exceed max_total_bytes"}
                    total_exhausted = True
                    continue
                try:
                    assert reuse_root is not None
                    cached_view = load_source_layers(
                        reuse_root, snapshot.path,
                        max_index_bytes=min(16_000_000, max_input_bytes),
                        max_record_bytes=max_record_bytes)
                    if cached_view.snapshot != snapshot or cached_view.context != context:
                        raise ValueError("cached source-layer record differs from inventory context")
                except (OSError, ValueError, TypeError, KeyError, SyntaxError,
                        RecursionError, UnicodeError) as error:
                    row["gap"] = {"code": "CACHE_VALIDATION_FAILED",
                                  "detail": _safe_detail(error)}
                    continue

                if _current_source_matches(snapshot, context):
                    archive_rel = cached_row["archive"]
                    cached_archive = reuse_root / archive_rel
                    archive_path = destination / archive_rel
                    try:
                        compressed_bytes = _link_or_copy_exclusive(cached_archive, archive_path)
                        if compressed_bytes != cached_row["compressed_bytes"]:
                            archive_path.unlink(missing_ok=True)
                            raise ValueError("cached source-layer compressed size changed")
                        row.update(
                            status="STORED", archive=archive_rel,
                            canonical_sha256=cached_row["canonical_sha256"],
                            canonical_bytes=cached_canonical_bytes,
                            compressed_bytes=compressed_bytes, gap=None)
                        charged += cached_canonical_bytes
                        continue
                    except (OSError, ValueError) as error:
                        row["gap"] = {"code": "CACHE_REUSE_FAILED",
                                      "detail": _safe_detail(error)}
                        continue

            try:
                prepared = prepare_source(snapshot.path, project_root=context.namespace_root)
                rebuilt_snapshot = prepared.semantics.sources.get(snapshot.path)
                if (str(prepared.path) != snapshot.path or str(prepared.root) != context.namespace_root
                        or rebuilt_snapshot != snapshot):
                    raise ValueError("current source snapshot/namespace differs from inventory")
                semantic_doc = prepared.semantic.to_dict()
                semantics_doc = prepared.semantics.to_dict()
                control_doc = prepared.control.to_dict()
                actual_digests = (_digest(semantic_doc), _digest(semantics_doc), _digest(control_doc))
                expected_digests = (context.semantic_sha256, context.semantics_sha256, context.control_sha256)
                if actual_digests != expected_digests:
                    raise ValueError("rebuilt source-layer digest differs from inventory context")

                envelope = {
                    "schema": "scar.source-layers.record",
                    "schema_version": 1,
                    "source": {"snapshot": encode(snapshot), "context": encode(context)},
                    "payload": {"semantic": semantic_doc, "semantics": semantics_doc,
                                "control": control_doc},
                    "metadata": dict(_METADATA),
                }
                canonical = _canonical(envelope)
                if len(canonical) > max_record_bytes:
                    row["gap"] = {"code": "RECORD_BYTE_BUDGET",
                                  "detail": "canonical source-layer record exceeds max_record_bytes"}
                    continue
                if reservation + charged + len(canonical) > max_total_bytes:
                    row["gap"] = {"code": "TOTAL_BYTE_BUDGET",
                                  "detail": "canonical source-layer records exceed max_total_bytes"}
                    total_exhausted = True
                    continue
                canonical_sha256 = hashlib.sha256(canonical).hexdigest()
                archive_rel = f"{_ARCHIVE_DIR}/{canonical_sha256}.json.gz"
                archive_path = destination / archive_rel
                compressed_bytes = _write_gzip_exclusive(archive_path, canonical)
                row.update(status="STORED", archive=archive_rel,
                           canonical_sha256=canonical_sha256,
                           canonical_bytes=len(canonical), compressed_bytes=compressed_bytes,
                           gap=None)
                charged += len(canonical)
            except (OSError, ValueError, TypeError, KeyError, SyntaxError,
                    RecursionError, UnicodeError) as error:
                row["gap"] = {"code": "SOURCE_REPLAY_FAILED",
                              "detail": _safe_detail(error)}

        manifest = _manifest(input_sha256, len(decoded), version, rows)
        index_payload = _canonical(manifest)
        if len(index_payload) + charged > max_total_bytes:
            raise ValueError("final source-layer manifest exceeds total-byte budget")
        index_path = destination / _INDEX_NAME
        with index_path.open("xb") as index_file:
            index_file.write(index_payload)
        return manifest
    except BaseException:
        if created:
            shutil.rmtree(destination, ignore_errors=True)
        raise


def _safe_detail(error: BaseException) -> str:
    detail = " ".join(str(error).split())
    if not detail:
        detail = type(error).__name__
    return detail[:512]


def _validate_manifest(document: Any) -> list[dict[str, Any]]:
    expected = {
        "schema", "schema_version", "scope", "input", "files_total", "files_stored",
        "files_gapped", "complete", "whole_program_graph_established",
        "fine_state_effects_established", "transformation_authorized", "files", "source_replay",
    }
    if type(document) is not dict or set(document) != expected:
        raise ValueError("source-layer index fields mismatch")
    if (document["schema"] != _SCHEMA or type(document["schema_version"]) is not int
            or document["schema_version"] != _VERSION or document["scope"] != _SCOPE):
        raise ValueError("unsupported source-layer index schema/version")
    if (document["source_replay"] != _METADATA["source_replay"]
            or document["whole_program_graph_established"] is not False
            or document["fine_state_effects_established"] is not False
            or document["transformation_authorized"] is not False):
        raise ValueError("source-layer index overstates model authority")
    input_meta = document["input"]
    if (type(input_meta) is not dict
            or set(input_meta) != {"schema", "schema_version", "raw_sha256", "decoded_bytes"}
            or input_meta["schema"] != "scar.program-inventory"
            or type(input_meta["schema_version"]) is not int
            or input_meta["schema_version"] not in (1, 2, 3, 4, 5, 6, 7, 8)
            or type(input_meta["raw_sha256"]) is not str
            or not _SHA256.fullmatch(input_meta["raw_sha256"])
            or type(input_meta["decoded_bytes"]) is not int or input_meta["decoded_bytes"] < 0):
        raise ValueError("source-layer input metadata is malformed")
    files = document["files"]
    if type(files) is not list:
        raise ValueError("source-layer files must be an array")
    if any(type(document[name]) is not int or document[name] < 0
           for name in ("files_total", "files_stored", "files_gapped")):
        raise ValueError("source-layer file counts are malformed")
    if document["files_total"] != len(files):
        raise ValueError("source-layer file denominator mismatch")
    seen: set[str] = set()
    stored = 0
    for row in files:
        if type(row) is not dict or set(row) != {
            "source_path", "snapshot", "context", "status", "archive", "canonical_sha256",
            "canonical_bytes", "compressed_bytes", "gap",
        }:
            raise ValueError("source-layer file row fields mismatch")
        snapshot = decode(SourceSnapshot, row["snapshot"])
        _validate_snapshot(snapshot)
        path = _canonical_absolute_path(row["source_path"], "source-layer path")
        if path != snapshot.path or path in seen:
            raise ValueError("source-layer path is duplicated or differs from snapshot")
        seen.add(path)
        if row["context"] is None:
            if row["status"] != "GAP":
                raise ValueError("source-layer without context cannot contain an archive")
        else:
            context = decode(SourceContextDigest, row["context"])
            _validate_context(context)
        if row["status"] == "STORED":
            if row["context"] is None or row["gap"] is not None:
                raise ValueError("stored source-layer row has missing context or gap")
            if (type(row["archive"]) is not str
                    or not re.fullmatch(rf"{_ARCHIVE_DIR}/[0-9a-f]{{64}}\.json\.gz", row["archive"])):
                raise ValueError("source-layer archive path is malformed")
            archive_hash = row["archive"].split("/")[-1][:-len(".json.gz")]
            if row["canonical_sha256"] != archive_hash:
                raise ValueError("source-layer archive name/hash mismatch")
            if (type(row["canonical_bytes"]) is not int or row["canonical_bytes"] < 1
                    or type(row["compressed_bytes"]) is not int or row["compressed_bytes"] < 1):
                raise ValueError("source-layer archive sizes are malformed")
            stored += 1
        elif row["status"] == "GAP":
            if (row["archive"] is not None or row["canonical_sha256"] is not None
                    or type(row["canonical_bytes"]) is not int or row["canonical_bytes"] != 0
                    or type(row["compressed_bytes"]) is not int or row["compressed_bytes"] != 0
                    or type(row["gap"]) is not dict
                    or set(row["gap"]) != {"code", "detail"}
                    or type(row["gap"]["code"]) is not str or not row["gap"]["code"]
                    or type(row["gap"]["detail"]) is not str or not row["gap"]["detail"]):
                raise ValueError("source-layer gap row is malformed")
        else:
            raise ValueError("unknown source-layer row status")
    if (document["files_stored"] != stored or document["files_gapped"] != len(files) - stored
            or type(document["complete"]) is not bool or document["complete"] != (stored == len(files))):
        raise ValueError("source-layer completeness/counts are inconsistent")
    return files


def load_source_layers(
    out_dir: str | Path,
    source_path: str | Path,
    *,
    max_index_bytes: int = 16_000_000,
    max_record_bytes: int = 64_000_000,
) -> SourceLayerView:
    """Load one stored file's graph triple without reading target source.

    This checks archive integrity, graph structure, and snapshot/context links.
    It does not re-read ``source_path`` or attest current AST/source replay.
    """
    _check_budgets(max_index_bytes=max_index_bytes, max_record_bytes=max_record_bytes)
    root = Path(out_dir)
    if root.is_symlink() or not root.is_dir():
        raise ValueError("source-layer output must be a real directory")
    index_path = root / _INDEX_NAME
    if index_path.is_symlink() or not index_path.is_file():
        raise ValueError("source-layer index is missing or not a regular file")
    if index_path.stat().st_size > max_index_bytes:
        raise ValueError("source-layer index byte budget exceeded")
    try:
        index_bytes = _read_file_limited(index_path, max_index_bytes,
                                         "source-layer index byte budget exceeded")
        document = strict_loads(index_bytes.decode("utf-8", errors="strict"))
    except (OSError, UnicodeError, ValueError, RecursionError) as error:
        raise ValueError("source-layer index is not strict UTF-8 JSON") from error
    if _canonical(document) != index_bytes:
        raise ValueError("source-layer index is not canonical JSON")
    rows = _validate_manifest(document)
    requested_path = _canonical_absolute_path(str(source_path), "source path")
    matches = [row for row in rows if row["source_path"] == requested_path]
    if len(matches) != 1:
        raise ValueError("source path is not uniquely indexed")
    row = matches[0]
    if row["status"] != "STORED":
        gap = row["gap"]["code"] if row["gap"] else "unknown"
        raise ValueError(f"source-layer record is unavailable: {gap}")

    archive_dir = root / _ARCHIVE_DIR
    if archive_dir.is_symlink() or not archive_dir.is_dir():
        raise ValueError("source-layer archive directory is missing or unsafe")
    archive_path = root / row["archive"]
    if archive_path.is_symlink() or not archive_path.is_file():
        raise ValueError("source-layer archive is missing or unsafe")
    # Gzip headers/trailers and large incompressible records add only bounded
    # overhead. This also prevents a forged index from making the reader scan
    # an arbitrarily large compressed file before checking decompressed bytes.
    compressed_limit = max_record_bytes * 2 + 1_000_000
    if archive_path.stat().st_size > compressed_limit:
        raise ValueError("source-layer compressed record exceeds reader budget")
    try:
        compressed_payload = _read_file_limited(
            archive_path, compressed_limit, "source-layer compressed record exceeds reader budget")
    except OSError as error:
        raise ValueError("source-layer archive could not be read") from error
    if len(compressed_payload) != row["compressed_bytes"]:
        raise ValueError("source-layer archive compressed size mismatch")
    chunks: list[bytes] = []
    decoded_size = 0
    try:
        with gzip.GzipFile(fileobj=BytesIO(compressed_payload), mode="rb") as stream:
            while True:
                block = stream.read(min(1024 * 1024, max_record_bytes + 1 - decoded_size))
                if not block:
                    break
                decoded_size += len(block)
                if decoded_size > max_record_bytes:
                    raise ValueError("source-layer record byte budget exceeded")
                chunks.append(block)
    except (OSError, EOFError, gzip.BadGzipFile) as error:
        raise ValueError("source-layer archive gzip is invalid") from error
    canonical = b"".join(chunks)
    if (decoded_size != row["canonical_bytes"]
            or hashlib.sha256(canonical).hexdigest() != row["canonical_sha256"]
            or archive_path.stat().st_size != row["compressed_bytes"]):
        raise ValueError("source-layer archive size/hash mismatch")
    try:
        envelope = strict_loads(canonical.decode("utf-8", errors="strict"))
    except (UnicodeError, ValueError, RecursionError) as error:
        raise ValueError("source-layer record is not strict UTF-8 JSON") from error
    if _canonical(envelope) != canonical:
        raise ValueError("source-layer record is not canonical JSON")
    if (type(envelope) is not dict
            or set(envelope) != {"schema", "schema_version", "source", "payload", "metadata"}
            or envelope["schema"] != "scar.source-layers.record"
            or type(envelope["schema_version"]) is not int or envelope["schema_version"] != 1):
        raise ValueError("source-layer record envelope mismatch")
    source = envelope["source"]
    if type(source) is not dict or set(source) != {"snapshot", "context"}:
        raise ValueError("source-layer source fields mismatch")
    snapshot = decode(SourceSnapshot, source["snapshot"])
    context = decode(SourceContextDigest, source["context"])
    _validate_snapshot(snapshot)
    _validate_context(context)
    if snapshot != decode(SourceSnapshot, row["snapshot"]) or context != decode(SourceContextDigest, row["context"]):
        raise ValueError("source-layer record source differs from index")
    if (envelope["metadata"] != _METADATA
            or type(envelope["metadata"]) is not dict):
        raise ValueError("source-layer record metadata overstates authority")
    payload = envelope["payload"]
    if type(payload) is not dict or set(payload) != {"semantic", "semantics", "control"}:
        raise ValueError("source-layer payload fields mismatch")
    metadata = dict(envelope["metadata"])
    metadata.update({
        "archive_sha256": row["canonical_sha256"],
        "archive_bytes": row["canonical_bytes"],
        "input_inventory_raw_sha256": document["input"]["raw_sha256"],
        "input_inventory_schema_version": document["input"]["schema_version"],
        "source_replay_on_load": False,
    })
    declaration = ProviderFactReference(ProviderArtifact(str(index_path.resolve()),
        hashlib.sha256(index_bytes).hexdigest(), len(index_bytes), _SCHEMA),
        "#/files/" + str(rows.index(row)))
    locator = SourceArtifactLocator(ProviderArtifact(str(archive_path.resolve()),
        hashlib.sha256(compressed_payload).hexdigest(), len(compressed_payload), "scar.source-layers.record"),
        row["canonical_sha256"], decoded_size, "gzip-canonical-json", declaration=declaration)
    return _decoded_source_layer_view(snapshot, context, payload, metadata, locator)


def _decoded_source_layer_view(snapshot, context, payload, metadata, locator=None):
    """Shared graph validation, without changing either producer's envelope."""
    _validate_snapshot(snapshot); _validate_context(context)
    if type(payload) is not dict or set(payload) != {"semantic", "semantics", "control"}:
        raise ValueError("source-layer payload fields mismatch")
    semantic = semantic_from_dict(payload["semantic"])
    semantics = SourceSemanticsGraph.from_dict(payload["semantics"], semantic)
    control = SourceControlFlowGraph.from_dict(payload["control"])
    control.assert_valid(semantic, semantics)
    if semantics.sources.get(snapshot.path) != snapshot:
        raise ValueError("source-layer semantics snapshot differs from source record")
    if control.sources.get(snapshot.path) is None or control.sources[snapshot.path].fingerprint != snapshot.fingerprint:
        raise ValueError("source-layer control source version differs from source record")
    actual_digests = (_digest(semantic.to_dict()), _digest(semantics.to_dict()), _digest(control.to_dict()))
    if actual_digests != (context.semantic_sha256, context.semantics_sha256, context.control_sha256):
        raise ValueError("source-layer graph digest differs from index context")
    return SourceLayerView(snapshot, context, semantic, semantics, control, metadata, locator)


def load_source_graph_artifact(path, *, schema, canonical_sha256, canonical_bytes,
                               compressed_bytes, source_root, snapshot, context,
                               snapshot_locator, declaration, max_record_bytes=128_000_000):
    """Read an original dependency graph artifact without source preparation.

    The caller binds the original manifest declaration and admitted path. This
    reader preserves both existing dependency envelopes and their true origin;
    it does not manufacture an inventory/source-replay receipt.
    """
    _check_budgets(max_record_bytes=max_record_bytes, canonical_bytes=canonical_bytes,
                   compressed_bytes=compressed_bytes)
    if schema not in ("scar.dependency-source-graphs", "scar.dependency-continuation-source-graphs"):
        raise ValueError("unsupported dependency source graph schema")
    if not _SHA256.fullmatch(canonical_sha256) or canonical_bytes > max_record_bytes:
        raise ValueError("source graph hash/record budget mismatch")
    if type(snapshot) is not SourceSnapshot or type(context) is not SourceContextDigest:
        raise TypeError("source graph requires the bound original snapshot/context")
    if type(declaration) is not ProviderFactReference:
        raise TypeError("source graph requires its original artifact declaration")
    path = Path(path)
    if path.is_symlink() or not path.is_file() or str(path.resolve()) != str(path):
        raise ValueError("source graph artifact must be an ordinary canonical path")
    before = path.stat()
    if before.st_size != compressed_bytes:
        raise ValueError("source graph compressed-byte receipt mismatch")
    payload, physical_sha = _read_bounded(path, limit=max_record_bytes)
    after = path.stat()
    if ((before.st_dev, before.st_ino, before.st_size, before.st_mtime_ns)
            != (after.st_dev, after.st_ino, after.st_size, after.st_mtime_ns)
            or len(payload) != canonical_bytes or hashlib.sha256(payload).hexdigest() != canonical_sha256):
        raise ValueError("source graph artifact changed or differs from its original receipt")
    document = strict_loads(payload.decode("utf-8", errors="strict"))
    if (_canonical(document) != payload or document.get("schema") != schema
            or type(document.get("schema_version")) is not int or document["schema_version"] != 1):
        raise ValueError("source graph canonical schema/version mismatch")
    flags = ("target_executed_by_resolver", "transitive_dependency_closure_established",
             "canonical_bodies_established", "actual_formal_routing_established",
             "function_environment_established", "effects_established", "state_versions_established",
             "observer_origin_established", "provider_version_at_capture_established",
             "whole_program_graph_established", "first_stage_complete", "transformation_authorized")
    if (any(document.get(name) is not False for name in flags)
            or document.get("independent_source_replay_established") is not False):
        raise ValueError("source graph artifact overstates its authority")
    if (document["source_root"] != source_root or decode(SourceSnapshot, document["snapshot"]) != snapshot
            or decode(SourceContextDigest, document["context"]) != context
            or document["namespace_root"] != context.namespace_root):
        raise ValueError("source graph root/snapshot/context differs from its declaration")
    if schema == "scar.dependency-source-graphs":
        if (snapshot_locator.get("origin") != "PARENT"
                or document["source_snapshot_artifact"] != snapshot_locator["artifact"]):
            raise ValueError("original graph snapshot artifact differs from its parent declaration")
    elif document["source_snapshot_locator"] != snapshot_locator:
        raise ValueError("continuation graph snapshot locator differs from its original declaration")
    metadata = {"archive_sha256": canonical_sha256, "archive_bytes": canonical_bytes,
                "source_replay_on_load": False, "source_layer_producer": document["source_layer_producer"],
                "independent_source_replay_established": False, "whole_program_graph_established": False,
                "fine_state_effects_established": False, "transformation_authorized": False}
    locator = SourceArtifactLocator(ProviderArtifact(str(path), physical_sha, compressed_bytes, schema),
        canonical_sha256, canonical_bytes, "gzip-canonical-json", declaration=declaration)
    view = _decoded_source_layer_view(snapshot, context,
        {name: document[name] for name in ("semantic", "semantics", "control")}, metadata, locator)
    return view, locator


__all__ = ["SourceLayerView", "reconstruct_source_layers", "load_source_layers", "load_source_graph_artifact"]
