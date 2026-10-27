"""Owned, version-specific CodeType evidence; compilation never executes code.

The archive is a compiler witness, not an executable program or another IR.
Only its creator may populate it. Readers validate its receipts and complete
structural descriptors before handing real CodeType objects to existing dis
consumers. A missing witness never changes a verified source correspondence.
"""
from __future__ import annotations

from dataclasses import asdict, dataclass
import hashlib
import importlib.util
import io
import json
import marshal
import os
from pathlib import Path
import stat
import sys
import tokenize
from types import CodeType

from scar.analysis.call_compilation import compile_cache_key
from scar.ir.program.call_edges import CapturedCode
from scar.ir.program.compilation import CallCompilationProfile
from scar.ir.record_codec import encode, loads as strict_loads
from scar.trace.code_snapshot import describe_code


def _need(condition, detail):
    if not condition:
        raise ValueError("code witness: " + detail)


def _bytes(value):
    return json.dumps(value, sort_keys=True, ensure_ascii=False,
                      separators=(",", ":"), allow_nan=False).encode("utf-8")


def _sha(value):
    return hashlib.sha256(value).hexdigest()


def _runtime():
    return {"implementation": sys.implementation.name, "python": sys.version,
            "version": list(sys.version_info), "cache_tag": sys.implementation.cache_tag,
            "magic": importlib.util.MAGIC_NUMBER.hex(), "marshal_version": marshal.version}


@dataclass(frozen=True)
class CodeWitnessBudget:
    max_compile_keys: int = 20
    max_source_files: int = 32
    max_source_bytes: int = 16_000_000
    max_module_bytes: int = 16_000_000
    max_archive_bytes: int = 256_000_000
    max_manifest_bytes: int = 8_000_000
    max_nested_codes: int = 8192
    max_depth: int = 128

    def __post_init__(self):
        _need(all(type(value) is int and value > 0 for value in asdict(self).values()),
              "all independent budgets must be positive exact integers")


class CodeWitnessUnavailable(ValueError):
    """A local evidence frontier; not a source mismatch."""


class CodeWitnessStore:
    """Read an owned archive, or explicitly create/populate a fresh archive.

    ``create=True, compile_missing=True`` must be an explicit caller decision.
    Construction itself does not read target source, compile, or load CodeType.
    A read-only store never falls back to compilation. All materialized module
    payloads remain immutable; the small writer manifest is atomically replaced.
    """
    def __init__(self, directory, *, budget=CodeWitnessBudget(), create=False,
                 compile_missing=False, producer=None, progress=None):
        _need(type(budget) is CodeWitnessBudget, "budget must be CodeWitnessBudget")
        budget.__post_init__()
        _need(type(create) is bool and type(compile_missing) is bool,
              "create/compile_missing must be exact bool")
        _need(not compile_missing or create, "only a new owned writer may compile")
        _need(progress is None or callable(progress), "progress must be callable or None")
        path = Path(directory).absolute()
        _need(not path.is_symlink() and path == path.resolve(), "archive root must be a canonical non-symlink path")
        self.root, self.budget = path, budget
        self.progress = progress
        self.writable, self.compile_missing = create, compile_missing
        self.modules, self.module_indexes, self.texts = {}, {}, {}
        self.counts = {"compile_attempts": 0, "module_loads": 0,
                       "complete_descriptor_matches": 0, "source_bytes_read": 0}
        if create:
            _need(not path.exists(), "new witness archive already exists")
            _need(type(producer) is dict and bool(producer), "writer requires an explicit producer")
            path.mkdir(parents=True, mode=0o700)
            self.document = {"schema": "scar.code-witness-store", "schema_version": 1,
                "runtime": _runtime(), "producer": producer, "budget": asdict(budget),
                "sources": {}, "modules": {}, "target_executed": False,
                "source_prepared": False, "transformation_authorized": False}
            self._publish()
        else:
            self._owned(path, directory=True)
            raw = self._read("manifest.json", budget.max_manifest_bytes)
            self.document = strict_loads(raw.decode("utf-8"))
            _need(type(self.document) is dict and self.document.get("schema") == "scar.code-witness-store"
                  and self.document.get("schema_version") == 1, "unsupported archive schema")
            _need(self.document.get("runtime") == _runtime(), "Python build/magic/marshal differs")
            _need(all(self.document.get(name) is False for name in
                      ("target_executed", "source_prepared", "transformation_authorized")),
                  "archive overstates execution authority")
            _need(type(self.document.get("sources")) is dict
                  and type(self.document.get("modules")) is dict, "archive maps are missing")
            _need(len(self.document["modules"]) <= budget.max_compile_keys
                  and len(self.document["sources"]) <= budget.max_source_files,
                  "archive exceeds independent key/source count ceilings")
            declared = [row["artifact"] for row in self.document["modules"].values()]
            declared += [row["artifact"] for row in self.document["sources"].values()]
            _need(all(type(row.get("bytes")) is int and row["bytes"] >= 0 for row in declared)
                  and sum(row["bytes"] for row in declared) <= budget.max_archive_bytes,
                  "archive exceeds independent total-byte ceiling")
            _need(sum(row["artifact"]["bytes"] for row in self.document["sources"].values())
                  <= budget.max_source_bytes, "archive exceeds independent source-byte ceiling")

    def _notify(self, stage, **fields):
        if self.progress is not None:
            self.progress({"stage": stage, "code_witness_activity": dict(self.counts), **fields})

    @staticmethod
    def _owned(path, *, directory=False):
        status = path.lstat()
        _need(not stat.S_ISLNK(status.st_mode)
              and (stat.S_ISDIR(status.st_mode) if directory else stat.S_ISREG(status.st_mode))
              and status.st_uid == os.geteuid() and not status.st_mode & 0o022,
              "witness files/directories must be owned, regular, and not group/world writable")

    def _read(self, relative, limit):
        _need(type(relative) is str and Path(relative).name == relative,
              "artifact locator must be one local archive filename")
        self._owned(self.root, directory=True)
        path = self.root / relative
        self._owned(path)
        _need(path.stat().st_size <= limit, "artifact exceeds independent byte ceiling")
        with path.open("rb") as stream:
            raw = stream.read(limit + 1)
        _need(len(raw) <= limit, "artifact grew beyond its byte ceiling")
        return raw

    def _artifact(self, declaration, limit):
        raw = self._read(declaration["path"], limit)
        _need(len(raw) == declaration["bytes"] and _sha(raw) == declaration["sha256"],
              "artifact SHA/size differs from immutable receipt")
        return raw

    def _write(self, name, raw):
        total = sum(row["artifact"]["bytes"] for row in self.document["sources"].values())
        total += sum(row["artifact"]["bytes"] for row in self.document["modules"].values())
        _need(total + len(raw) <= self.budget.max_archive_bytes, "archive total-byte budget exceeded")
        path = self.root / name
        descriptor = os.open(path, os.O_WRONLY | os.O_CREAT | os.O_EXCL, 0o600)
        with os.fdopen(descriptor, "wb") as stream:
            stream.write(raw)
        return {"path": name, "sha256": _sha(raw), "bytes": len(raw)}

    def _publish(self):
        raw = _bytes(self.document)
        _need(len(raw) <= self.budget.max_manifest_bytes, "manifest byte budget exceeded")
        temporary = self.root / ".manifest.tmp"
        descriptor = os.open(temporary, os.O_WRONLY | os.O_CREAT | os.O_EXCL, 0o600)
        with os.fdopen(descriptor, "wb") as stream:
            stream.write(raw)
        temporary.replace(self.root / "manifest.json")

    def text(self, snapshot):
        """Return archived exact text, or fingerprint current text once for a writer."""
        key = _sha(_bytes(encode(snapshot)))
        if key in self.texts:
            return self.texts[key]
        row = self.document["sources"].get(key)
        if row is not None:
            _need(row["snapshot"] == encode(snapshot), "source snapshot/key differs")
            text = self._artifact(row["artifact"], self.budget.max_source_bytes).decode("utf-8")
        else:
            if not self.writable:
                raise CodeWitnessUnavailable("SOURCE_TEXT_WITNESS_UNAVAILABLE")
            _need(len(self.document["sources"]) < self.budget.max_source_files,
                  "source-file budget exceeded")
            path = Path(snapshot.path)
            _need(path.is_absolute() and path == path.resolve() and path.is_file(),
                  "source must retain its canonical exact path")
            remaining = self.budget.max_source_bytes - self.counts["source_bytes_read"]
            _need(path.stat().st_size <= remaining, "source-byte budget exceeded")
            with path.open("rb") as stream:
                raw = stream.read(remaining + 1)
            _need(len(raw) <= remaining, "source-byte budget exceeded")
            self.counts["source_bytes_read"] += len(raw)
            encoding, _ = tokenize.detect_encoding(io.BytesIO(raw).readline)
            # Match tokenize.open's universal-newline normalization exactly.
            with io.TextIOWrapper(io.BytesIO(raw), encoding=encoding) as stream:
                text = stream.read()
            _need(snapshot.fingerprint == "sha256:" + _sha(text.encode("utf-8")),
                  "current source fingerprint drifted")
            normalized = text.encode("utf-8")
            _need(sum(row["artifact"]["bytes"] for row in self.document["sources"].values())
                  + len(normalized) <= self.budget.max_source_bytes, "archived source-byte budget exceeded")
            declaration = self._write(key + ".source.utf8", normalized)
            self.document["sources"][key] = {"snapshot": encode(snapshot), "artifact": declaration,
                                            "original_encoding": encoding, "original_raw_sha256": _sha(raw)}
            self._publish()
        _need(snapshot.fingerprint == "sha256:" + _sha(text.encode("utf-8")),
              "archived source fingerprint differs")
        self.texts[key] = text
        return text

    def admit_archived_source(self, snapshot, *, source_owner):
        """Admit text from a normal original source owner into this new writer.

        No bare text, serialized owner or applicability boolean is accepted.
        Compilation and independent nested-descriptor replay remain resolve's
        ordinary responsibilities. Existing archives and live text() are unchanged.
        """
        from scar.analysis.source_attachments import SourceAttachments
        from scar.ir.semantics_v2 import SourceSnapshot
        _need(self.writable and self.compile_missing and type(snapshot) is SourceSnapshot
              and type(source_owner) is SourceAttachments,
              "archived source admission requires a new writer and normal source owner")
        original = source_owner.archived_source(snapshot)
        text = original["text"]
        _need(original["snapshot"] == snapshot and type(text) is str
              and snapshot.fingerprint == "sha256:" + _sha(text.encode("utf-8"))
              and original["owner"] == source_owner.receipts(),
              "original source owner/text fingerprint differs")
        provenance = {"kind": "ORIGINAL_ARCHIVED_SOURCE",
            "snapshot": encode(snapshot), "artifact": encode(original["locator"]),
            "declaration": encode(original["declaration"]), "owner": original["owner"],
            "source_root": original["source_root"], "namespace_root": original["namespace_root"],
            "raw_bytes": original["raw_bytes"]}
        key = _sha(_bytes(encode(snapshot)))
        existing = self.document["sources"].get(key)
        if existing is not None:
            _need(existing.get("archived_source_origin") == provenance
                  and existing["original_encoding"] == original["encoding"]
                  and existing["original_raw_sha256"] == original["raw_sha256"]
                  and self.text(snapshot) == text,
                  "existing writer source conflicts with its original archive provenance")
            return {"snapshot": encode(snapshot), "artifact": dict(existing["artifact"]),
                    "archived_source_origin": provenance}
        normalized = text.encode("utf-8")
        _need(len(self.document["sources"]) < self.budget.max_source_files
              and sum(row["artifact"]["bytes"] for row in self.document["sources"].values())
                  + len(normalized) <= self.budget.max_source_bytes,
              "archived source-file/byte budget exceeded")
        declaration = self._write(key + ".source.utf8", normalized)
        self.document["sources"][key] = {"snapshot": encode(snapshot), "artifact": declaration,
            "original_encoding": original["encoding"], "original_raw_sha256": original["raw_sha256"],
            "archived_source_origin": provenance}
        self.texts[key] = text
        self._publish()
        return {"snapshot": encode(snapshot), "artifact": dict(declaration),
                "archived_source_origin": provenance}

    def admit_captured_source(self, snapshot, *, captured, source_owner):
        """Admit capture-observed bytes without claiming a compiler match.

        The normal owner establishes exact original rows/CodeID membership.
        Only resolve's actual compilation plus complete descriptor comparison
        can subsequently create a CodeWitness. No live text fallback is used.
        """
        from scar.analysis.captured_source_owner import CapturedSourceOwner
        from scar.ir.semantics_v2 import SourceSnapshot
        _need(self.writable and self.compile_missing and type(snapshot) is SourceSnapshot
              and type(captured) is CapturedCode and type(source_owner) is CapturedSourceOwner,
              "captured source admission requires a new writer and normal captured-source owner")
        _need(source_owner.snapshot(captured) == snapshot,
              "captured CodeID does not select this exact archived source snapshot")
        original = source_owner.archived_source(snapshot)
        text = original.text
        _need(original.snapshot == snapshot and type(text) is str
              and snapshot.fingerprint == "sha256:" + _sha(text.encode("utf8"))
              and original.compiler_match == 'NOT_CHECKED' and original.loader_bytes_observed is False,
              "captured source text/observation qualification differs")
        _need(original.observed_python == sys.version,
              "captured interpreter build differs from this compiler witness runtime")
        provenance = {"kind": "CAPTURED_SOURCE_OBSERVATION",
            "snapshot": encode(snapshot), "source": encode(original.source),
            "declaration": encode(original.declaration), "code_sources": encode(original.code_sources),
            "owner": source_owner.receipts(), "raw_bytes": original.raw_bytes,
            "unchanged_at_close": original.unchanged_at_close,
            "observation_frontier": original.observation_frontier,
            "compiler_match": 'NOT_CHECKED', "loader_bytes_observed": False}
        key = _sha(_bytes(encode(snapshot)))
        existing = self.document['sources'].get(key)
        if existing is not None:
            _need(existing.get('captured_source_origin') == provenance
                  and existing['original_encoding'] == original.original_encoding
                  and existing['original_raw_sha256'] == original.raw_sha256 and self.text(snapshot) == text,
                  "existing writer source conflicts with its original captured provenance")
            declaration = existing['artifact']
        else:
            normalized = text.encode('utf8')
            _need(len(self.document['sources']) < self.budget.max_source_files
                  and sum(row['artifact']['bytes'] for row in self.document['sources'].values())
                      + len(normalized) <= self.budget.max_source_bytes,
                  "captured source-file/byte budget exceeded")
            declaration = self._write(key + '.source.utf8', normalized)
            self.document['sources'][key] = {'snapshot': encode(snapshot), 'artifact': declaration,
                'original_encoding': original.original_encoding, 'original_raw_sha256': original.raw_sha256,
                'captured_source_origin': provenance}
            self.texts[key] = text
            self._publish()
        source_owner.require_unchanged()
        return {'snapshot': encode(snapshot), 'artifact': dict(declaration),
                'captured_source_origin': provenance,
                'code_membership': source_owner.code_membership(captured)}

    def _walk(self, module):
        pending, count = [(module, ())], 0
        while pending:
            code, path = pending.pop()
            count += 1
            _need(count <= self.budget.max_nested_codes and len(path) <= self.budget.max_depth,
                  "nested-code count/depth budget exceeded")
            yield code, path
            pending.extend((item, path + (index,)) for index, item in reversed(tuple(enumerate(code.co_consts)))
                           if type(item) is CodeType)

    def _load(self, key, row):
        if key not in self.modules:
            _need(row["runtime"] == _runtime(), "module Python build/magic differs")
            raw = self._artifact(row["artifact"], self.budget.max_module_bytes)
            stream = io.BytesIO(raw)
            module = marshal.load(stream)
            _need(stream.tell() == len(raw) and type(module) is CodeType,
                  "marshal artifact is not exactly one CodeType")
            _need(describe_code(module) == row["module_descriptor"],
                  "loaded module complete descriptor differs")
            self.modules[key] = tuple(self._walk(module))
            self.counts["module_loads"] += 1
            self._notify("CODE_WITNESS_LOADED", module_key=key)
        return self.modules[key]

    def _index(self, key, row):
        if key not in self.module_indexes:
            indexed = {}
            for code, path in self._load(key, row):
                try:
                    descriptor = describe_code(code)
                except ValueError:
                    continue  # Same bounded descriptor boundary as the source resolver.
                indexed.setdefault(descriptor["key"], []).append((code, path, descriptor))
            self.module_indexes[key] = indexed
        return self.module_indexes[key]

    def resolve(self, captured, snapshot, optimize_levels, *, allow_compile=False):
        """Resolve only the recorded exact descriptor; never execute the code."""
        _need(type(captured) is CapturedCode and captured.filename == snapshot.path,
              "descriptor/source filename differs")
        _need(type(allow_compile) is bool, "allow_compile must be an exact bool")
        levels = tuple(sorted(set(optimize_levels)))
        _need(bool(levels) and all(type(level) is int and level in (0, 1, 2) for level in levels),
              "witness has no valid recorded matching optimize levels")
        for optimize in levels:
            identity = compile_cache_key(Path(snapshot.path), snapshot.fingerprint,
                CallCompilationProfile.RECORDED_FUTURE_FLAGS, captured.flags, optimize,
                compile_filename=captured.filename)
            encoded_key = encode(identity)
            key = _sha(_bytes(encoded_key))
            row = self.document["modules"].get(key)
            if row is None and self.compile_missing and allow_compile:
                if self.counts["compile_attempts"] >= self.budget.max_compile_keys:
                    raise CodeWitnessUnavailable("CODE_WITNESS_COMPILE_BUDGET")
                text = self.text(snapshot)
                self.counts["compile_attempts"] += 1
                self._notify("CODE_WITNESS_COMPILE_BEGIN", compile_key=encoded_key)
                module = compile(text, captured.filename, "exec", flags=identity.future_flags,
                                 dont_inherit=True, optimize=optimize)
                codes = tuple(self._walk(module))
                _need(any(describe_code(code) == encode(captured) for code, _ in codes),
                      "recorded optimize variant does not reproduce the complete descriptor")
                raw = marshal.dumps(module)
                _need(len(raw) <= self.budget.max_module_bytes, "module marshal-byte budget exceeded")
                row = {"compile_key": encoded_key, "snapshot": encode(snapshot), "runtime": _runtime(),
                       "source_key": _sha(_bytes(encode(snapshot))),
                       "module_descriptor": describe_code(module),
                       "artifact": self._write(key + ".marshal", raw)}
                self.document["modules"][key] = row
                self.modules[key] = codes
                self._publish()
                self._notify("CODE_WITNESS_COMPILE_END", compile_key=encoded_key,
                             artifact=row["artifact"], nested_codes=len(codes))
            if row is None:
                continue
            _need(row["compile_key"] == encoded_key and row["snapshot"] == encode(snapshot),
                  "module compile key/source snapshot differs")
            # The matching complete fingerprint is checked again after load.
            matches = [(code, path) for code, path, descriptor in self._index(key, row).get(captured.key, ())
                       if descriptor == encode(captured)]
            if matches:
                code, path = matches[0]
                self.counts["complete_descriptor_matches"] += 1
                return code, {"module_key": key, "module_artifact": row["artifact"],
                              "constant_path": list(path), "descriptor": encode(captured)}
        raise CodeWitnessUnavailable("CODE_WITNESS_UNAVAILABLE")

    def receipt(self):
        raw = self._read("manifest.json", self.budget.max_manifest_bytes)
        return {"path": str(self.root / "manifest.json"), "sha256": _sha(raw), "bytes": len(raw),
                "runtime": _runtime(), "module_count": len(self.document["modules"]),
                "source_count": len(self.document["sources"]),
                "code_executed": False, "source_prepared": False}


__all__ = ["CodeWitnessStore", "CodeWitnessBudget", "CodeWitnessUnavailable"]
