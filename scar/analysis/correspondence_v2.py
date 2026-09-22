"""Reproduce loaded Python code identities without executing source programs.

Source text hashes and loaded CodeType hashes identify different things. Exact
marshal digest reproduction binds one compiled code object to a source snapshot;
it does not prove module globals, closure values, effects or value equivalence.
Location matches stay candidates. Runtime stubs and invocation IDs are retained.
"""
from __future__ import annotations

import ast
from collections import Counter, defaultdict
from dataclasses import dataclass, field
from enum import Enum
import hashlib
import marshal
from pathlib import Path
import platform
import re
import sys
import tokenize
from types import CodeType
from typing import Any, Mapping

from scar.ir.ids import CodeID
from scar.ir.v2 import (
    CorrespondenceGraph, CorrespondenceID, CorrespondenceKind,
    CorrespondenceRecord, EvidenceClaim, EvidenceKind, IRBundle,
    OperationDefinition, OperationDefinitionID, OperationInstanceID,
    OperationKind, SemanticGraph,
)


class JoinStatus(str, Enum):
    VERIFIED = "VERIFIED"
    AMBIGUOUS = "AMBIGUOUS"
    MISMATCH = "MISMATCH"
    MISSING = "MISSING"
    OUT_OF_SCOPE = "OUT_OF_SCOPE"


class JoinReason(str, Enum):
    EXACT_CODE_REPRODUCED = "exact_code_reproduced"
    NON_PYTHON_CODE = "non_python_code"
    SOURCE_OUT_OF_SCOPE = "source_out_of_scope"
    SOURCE_UNAVAILABLE = "source_unavailable"
    SOURCE_FINGERPRINT_MISMATCH = "source_fingerprint_mismatch"
    CODE_DIGEST_MISSING = "code_digest_missing"
    CODE_DIGEST_MISMATCH = "code_digest_mismatch"
    COMPILE_CONTEXT_UNSUPPORTED = "compile_context_unsupported"
    COMPILATION_FAILED = "compilation_failed"
    CALLABLE_SCOPE_UNRESOLVED = "callable_scope_unresolved"
    AMBIGUOUS_SOURCE_DEFINITION = "ambiguous_source_definition"


@dataclass(frozen=True)
class CompileContext:
    """A concrete tried context; equality can verify a guessed context's output."""

    optimize: int = 0
    flags: int = 0
    implementation: str = field(default_factory=lambda: sys.implementation.name)
    python_version: str = field(default_factory=platform.python_version)

    def __post_init__(self):
        if type(self.optimize) is not int or self.optimize not in (0, 1, 2):
            raise ValueError("optimize must be explicitly 0, 1 or 2")
        if type(self.flags) is not int or self.flags < 0:
            raise ValueError("compile flags must be a non-negative integer")
        if not self.implementation or not self.python_version:
            raise ValueError("compile context requires implementation/version")

    def as_dict(self):
        return {"optimize": self.optimize, "flags": self.flags,
                "implementation": self.implementation, "python_version": self.python_version,
                "mode": "exec", "dont_inherit": True}


@dataclass(frozen=True)
class CodeSourceWitness:
    source_path: str
    source_fingerprint: str
    loaded_code_id: str
    compiled_code_digest: str
    compile_filename: str
    compile_context: CompileContext
    qualname: str
    first_line: int
    marshal_reference_policy: str = "retain_compiled_code_tree"

    def as_dict(self):
        return {"source_path": self.source_path,
                "source_fingerprint": self.source_fingerprint,
                "source_fingerprint_algorithm": "sha256(decoded_text_utf8)",
                "loaded_code_id": self.loaded_code_id,
                "compiled_code_digest": self.compiled_code_digest,
                "code_digest_algorithm": "sha256(marshal.dumps(CodeType))",
                "marshal_reference_policy": self.marshal_reference_policy,
                "compile_filename": self.compile_filename,
                "compile_context": self.compile_context.as_dict(),
                "qualname": self.qualname, "first_line": self.first_line,
                "method": "offline_compile_match", "extent": "code_object_only",
                "original_compile_context_attested": False,
                "target_executed": False}


@dataclass(frozen=True)
class SourceJoinRequest:
    reason: JoinReason
    missing_fact: str
    source_path: str | None
    first_line: int | None
    runtime_definition: OperationDefinitionID
    instances: tuple[OperationInstanceID, ...]
    candidate_definitions: tuple[OperationDefinitionID, ...]
    raw_references: tuple[str, ...]
    fields: tuple[str, ...]
    collector: str = "code_source_witness"

    def as_dict(self):
        return {"action": "CONTRACT", "reason": self.reason.value,
                "missing_fact": self.missing_fact,
                "location": {"path": self.source_path, "start_line": self.first_line},
                "runtime_definition": self.runtime_definition.as_dict(),
                "instances": [item.as_dict() for item in self.instances],
                "candidate_definitions": [item.as_dict() for item in self.candidate_definitions],
                "raw_references": list(self.raw_references), "fields": list(self.fields),
                "collector": self.collector,
                "collector_availability": "loader-bound source capture requires implementation",
                "required_contract": "supply immutable loader-bound source, raw filename and compile context; unique callable span if ambiguous",
                "scope": "matching loaded callable and its source acquisition/compile boundary",
                "completion": "immutable source snapshot and compiled code identity uniquely locate the loaded callable",
                "rerun": {"command_ref": "run manifest argv; required if absent",
                          "required_phase": "source acquisition/compilation and matching invocation",
                          "executable": False},
                "fallback": "keep runtime/source boundary unresolved"}


@dataclass
class CorrespondenceResult:
    graph: CorrespondenceGraph
    report: dict[str, Any]


def _path(value: str) -> str:
    return value if value.startswith("<") else str(Path(value).resolve())


def _digest(code):
    return "pycode-sha256:" + hashlib.sha256(marshal.dumps(code)).hexdigest()


def _codes(code):
    yield code
    for constant in code.co_consts:
        if isinstance(constant, CodeType):
            yield from _codes(constant)


def _qualname(graph: SemanticGraph, definition: OperationDefinition) -> str | None:
    if definition.metadata.get("phase") == "module_initialization":
        return "<module>"
    if definition.kind in (OperationKind.FUNCTION, OperationKind.METHOD):
        name = definition.metadata.get("callable_name", definition.label)
    elif definition.label.startswith("class "):
        name = definition.label.removeprefix("class ")
    else:
        return None
    parent = graph.definitions.get(definition.parent_id)
    if parent is None or parent.metadata.get("phase") == "module_initialization":
        return name
    parent_name = _qualname(graph, parent)
    if parent_name is None:
        return None
    separator = ".<locals>." if parent.kind in (OperationKind.FUNCTION, OperationKind.METHOD) else "."
    return parent_name + separator + name


class _Source:
    def __init__(self, path, text, fingerprints):
        self.path, self.text = path, text
        self.fingerprint = "sha256:" + hashlib.sha256(text.encode()).hexdigest()
        self.expected = fingerprints
        self.ast_error = None
        self.first_lines = defaultdict(set)
        try:
            tree = ast.parse(text, filename=path)
        except (SyntaxError, ValueError) as error:
            self.ast_error = f"{type(error).__name__}: {error}"
        else:
            for node in ast.walk(tree):
                if isinstance(node, (ast.FunctionDef, ast.AsyncFunctionDef, ast.ClassDef, ast.Lambda)):
                    first = min([node.lineno] + [item.lineno for item in getattr(node, "decorator_list", ())])
                    self.first_lines[node.lineno].add(first)
        self.compiled = {}

    def compile(self, filename, context):
        key = (filename, context)
        if key in self.compiled:
            return self.compiled[key]
        attempted = {"filename": filename, "context": context.as_dict()}
        if context.implementation != sys.implementation.name or context.python_version != platform.python_version():
            attempted.update(status="unsupported", reason="local interpreter differs from requested context")
            result = ([], attempted)
        else:
            try:
                code = compile(self.text, filename, "exec", flags=context.flags,
                               dont_inherit=True, optimize=context.optimize)
                if not isinstance(code, CodeType):
                    raise ValueError("compile flags did not produce executable CodeType")
                # marshal's reference flags depend on live references, including
                # nested code constants. Preserve one explicit tree-retention
                # policy for reproducibility; never canonicalize old hashes to
                # manufacture equality. Other loaded layouts can remain unmatched.
                code_tree = list(_codes(code))
                records = [(_digest(item), item.co_qualname, item.co_firstlineno)
                           for item in code_tree]
            except (SyntaxError, ValueError, TypeError, OverflowError) as error:
                attempted.update(status="failed", reason=f"{type(error).__name__}: {error}")
                result = ([], attempted)
            else:
                attempted.update(status="compiled", code_objects=len(records),
                                 marshal_reference_policy="retain_compiled_code_tree")
                result = (records, attempted)
        self.compiled[key] = result
        return result


def build_correspondence(
    source_graph: SemanticGraph,
    runtime_bundle: IRBundle,
    *,
    source_texts: Mapping[str, str] | None = None,
    compile_contexts: tuple[CompileContext, ...] | None = None,
    filename_candidates: Mapping[str, tuple[str, ...]] | None = None,
) -> CorrespondenceResult:
    """Build auditable links without mutating either input graph.

    Default trials are local Python, flags=0, optimize=0/1/2 and the parsed
    CodeID filename. These are reproducible hypotheses, not captured facts.
    Exact byte-hash reproduction can verify their output despite absent old
    compile metadata. Mismatches never trigger relaxed/normalized code hashes.
    """
    source_graph.assert_valid()
    runtime_bundle.assert_valid()
    contexts = tuple(dict.fromkeys(compile_contexts if compile_contexts is not None else (
        CompileContext(optimize=0), CompileContext(optimize=1), CompileContext(optimize=2))))
    if not contexts or any(not isinstance(item, CompileContext) for item in contexts):
        raise ValueError("at least one typed CompileContext is required")
    texts = {_path(str(path)): text for path, text in (source_texts or {}).items()}
    if any(isinstance(names, str) for names in (filename_candidates or {}).values()):
        raise ValueError("filename candidates must be sequences, not individual strings")
    filenames = {_path(str(path)): tuple(names) for path, names in (filename_candidates or {}).items()}
    if any(not names or any(not isinstance(name, str) or not name for name in names) for names in filenames.values()):
        raise ValueError("filename candidates must be nonempty strings")
    files = defaultdict(set)
    for atom in source_graph.source_atoms.values():
        files[_path(atom.reference.path)].add(atom.reference.fingerprint)
    for module in source_graph.modules.values():
        if module.path and module.fingerprint:
            files[_path(module.path)].add(module.fingerprint)
    definitions = defaultdict(list)
    for definition in source_graph.definitions.values():
        if definition.source_file and (qualname := _qualname(source_graph, definition)) is not None:
            definitions[(_path(definition.source_file), qualname)].append(definition)
    source_cache: dict[str, _Source | str] = {}
    groups = defaultdict(list)
    for instance in runtime_bundle.evidence.instances.values():
        groups[instance.definition].append(instance)
    graph = CorrespondenceGraph()
    rows, requests = [], []

    for runtime_id in sorted(groups, key=lambda item: item.wire):
        runtime = runtime_bundle.semantic.definitions[runtime_id]
        instances = sorted(groups[runtime_id], key=lambda item: item.id.wire)
        raw_refs = tuple(sorted({str(item.metadata["raw_reference"]) for item in instances if item.metadata.get("raw_reference")}))
        parsed = CodeID.parse_key(runtime.code_id) if runtime.code_id else None
        row = {"runtime_definition": runtime_id.as_dict(),
               "instances": [item.id.as_dict() for item in instances],
               "loaded_code_id": runtime.code_id, "status": None, "reason": None,
               "candidates": [], "witnesses": [], "tried_contexts": [],
               "raw_references": list(raw_refs)}
        rows.append(row)
        source_path = _path(parsed.source) if parsed is not None else None
        row["source_path"] = source_path
        candidates = sorted(definitions.get((source_path, parsed.qualname), ()), key=lambda item: item.id.wire) if parsed else []

        def finish(status, reason, missing_fact=None):
            row.update(status=status.value, reason=reason.value)
            if missing_fact is not None:
                request = SourceJoinRequest(
                    reason, missing_fact, source_path, parsed.line if parsed else None,
                    runtime_id, tuple(item.id for item in instances),
                    tuple(item.id for item in candidates), raw_refs,
                    ("raw co_filename", "co_qualname/co_firstlineno", "loaded CodeID digest",
                     "immutable source text and fingerprint", "Python implementation/version",
                     "compile flags/optimize", "callable source span"))
                requests.append(request.as_dict())

        if parsed is None:
            finish(JoinStatus.OUT_OF_SCOPE, JoinReason.NON_PYTHON_CODE)
            continue
        if source_path not in files:
            finish(JoinStatus.OUT_OF_SCOPE, JoinReason.SOURCE_OUT_OF_SCOPE)
            continue
        if source_path not in source_cache:
            try:
                if source_path in texts:
                    text = texts[source_path]
                    if not isinstance(text, str):
                        raise ValueError("source_texts values must be strings")
                else:
                    with tokenize.open(source_path) as stream:
                        text = stream.read()
                source_cache[source_path] = _Source(source_path, text, files[source_path])
            except (OSError, UnicodeError, ValueError) as error:
                source_cache[source_path] = f"{type(error).__name__}: {error}"
        source = source_cache[source_path]
        if isinstance(source, str):
            row["source_error"] = source
            row["candidates"] = [item.id.as_dict() for item in candidates]
            finish(JoinStatus.MISSING, JoinReason.SOURCE_UNAVAILABLE, "source snapshot for the selected graph is unavailable")
            continue
        row["source_path"] = source_path
        row["source_fingerprint"] = source.fingerprint
        row["expected_source_fingerprints"] = sorted(source.expected)
        candidates = [item for item in candidates if item.metadata.get("phase") == "module_initialization"
                      or parsed.line in source.first_lines.get(item.source_start, {item.source_start})]
        row["candidates"] = [item.id.as_dict() for item in candidates]
        if source.expected != {source.fingerprint}:
            finish(JoinStatus.MISMATCH, JoinReason.SOURCE_FINGERPRINT_MISMATCH,
                   "source snapshot does not identify the selected Semantic Graph version")
            continue
        if re.fullmatch(r"pycode-sha256:[0-9a-f]{64}", parsed.version) is None:
            finish(JoinStatus.MISSING, JoinReason.CODE_DIGEST_MISSING, "loaded CodeType digest was not captured")
            continue
        if not candidates:
            finish(JoinStatus.MISSING, JoinReason.CALLABLE_SCOPE_UNRESOLVED,
                   "source graph has no uniquely scoped callable candidate at the loaded code location")
            continue
        witnessed = []
        names = tuple(dict.fromkeys(filenames.get(source_path, (parsed.source,))))
        for filename in names:
            for context in contexts:
                compiled, attempted = source.compile(filename, context)
                row["tried_contexts"].append(attempted)
                if any(digest == parsed.version and qualname == parsed.qualname and line == parsed.line
                       for digest, qualname, line in compiled):
                    witnessed.append(CodeSourceWitness(source_path, source.fingerprint, runtime.code_id,
                                                        parsed.version, filename, context, parsed.qualname, parsed.line))
        row["witnesses"] = [item.as_dict() for item in witnessed]
        if not witnessed:
            statuses = {item["status"] for item in row["tried_contexts"]}
            reason = (JoinReason.COMPILE_CONTEXT_UNSUPPORTED if statuses == {"unsupported"} else
                      JoinReason.COMPILATION_FAILED if "compiled" not in statuses else JoinReason.CODE_DIGEST_MISMATCH)
            finish(JoinStatus.MISMATCH, reason,
                   "no exact loaded-code reproduction; capture the loader-bound source, raw filename and compile context")
            continue
        ambiguous = len(candidates) != 1
        finish(JoinStatus.AMBIGUOUS if ambiguous else JoinStatus.VERIFIED,
               JoinReason.AMBIGUOUS_SOURCE_DEFINITION if ambiguous else JoinReason.EXACT_CODE_REPRODUCED,
               "code object is reproduced but multiple source definitions share its callable location" if ambiguous else None)
        for definition in candidates:
            for instance in instances:
                evidence = EvidenceClaim(EvidenceKind.INFERRED,
                    references=tuple(filter(None, (instance.metadata.get("raw_reference"),
                        source.fingerprint, parsed.version))), scope=str(instance.process_id),
                    assumptions=("exact reproduced code object; globals/closure/effects not certified",
                                 "source definition ambiguity retained" if ambiguous else "unique callable source scope"))
                identifier = CorrespondenceID("source-code:" + hashlib.sha256(
                    f"{definition.id.wire}\0{instance.id.wire}\0{source.fingerprint}".encode()).hexdigest())
                graph.add(CorrespondenceRecord(identifier, CorrespondenceKind.DEFINITION_INSTANCE,
                    definition=definition.id, instance=instance.id, evidence=evidence, ambiguous=ambiguous))
    statuses = Counter(row["status"] for row in rows)
    instance_statuses = Counter()
    for row in rows:
        instance_statuses[row["status"]] += len(row["instances"])
    report = {"schema": "scar.correspondence.v2.report", "schema_version": 1,
              "target_executed": False, "runtime_mutated": False,
              "definitions": len(rows), "instances": len(runtime_bundle.evidence.instances),
              "correspondences": len(graph.records),
              "status_counts": {status.value: statuses[status.value] for status in JoinStatus},
              "instance_status_counts": {status.value: instance_statuses[status.value] for status in JoinStatus},
              "unmatched_definitions": statuses[JoinStatus.MISMATCH.value] + statuses[JoinStatus.MISSING.value],
              "rows": rows, "requests": requests,
              "scope": "definition-instance source correspondence only; no slot-version/effect/value equality inferred",
              "limitations": ["legacy marshal code hashes can vary with live nested-code references; unmatched hashes are not normalized",
                              "default compile trials cannot recover arbitrary custom loaders or unavailable historical source"],
              "default_context_policy": "local interpreter, flags=0, optimize=0/1/2, dont_inherit=True; exact unmodified marshal hash required"}
    return CorrespondenceResult(graph, report)


__all__ = ["CompileContext", "CodeSourceWitness", "JoinStatus", "JoinReason",
           "SourceJoinRequest", "CorrespondenceResult", "build_correspondence"]
