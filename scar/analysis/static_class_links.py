"""Publish/read class construction relations over saved static source graphs.

The caller owns atomic model publication. This module only writes its fresh
staging directory; all original source and canonical body artifacts stay intact.
"""
from __future__ import annotations

from collections import Counter
from dataclasses import fields
import gzip
import hashlib
import io
import json
from pathlib import Path
import re
from time import monotonic

from scar.analysis.static_class_builder import connect_class_suite, validate_class_builder_expansion
from scar.ir.program.class_builder import (
    ClassBuilderExpansion, ClassBuilderProvider, StaticClassBuilderBinding,
)
from scar.ir.program.class_entries import ClassSuiteOverlay, ClassSuiteMethodOverlay, decode_class_entry_overlay
from scar.ir.program.codec import loads as load_core
from scar.ir.program.module_entries import decode_frame_body
from scar.ir.program.providers import ProviderArtifact
from scar.ir.program.source_language import decode_language_overlay
from scar.ir.program.source_references import SourceArtifactLocator
from scar.ir.record_codec import decode, encode, loads as strict_loads


def _canonical(value):
    return json.dumps(value, sort_keys=True, separators=(",", ":"), ensure_ascii=False,
                      allow_nan=False).encode() + b"\n"


def _constructions(body):
    if body.module is not None:
        return tuple(getattr(body.module, "class_constructions", ()))
    language = body.document.get("language")
    return tuple(decode_language_overlay(language).class_constructions) if language else ()


def build_static_class_links(directory, out, *, logical_root=None, expected_manifest_sha256=None,
                             budget=None, progress=None):
    """Write provider and parent-owned relation shards, never copy a suite.

    Descriptor paths are relative to ``out``. ``logical_root`` follows the
    existing atomic-publisher convention: original namespaces name the final
    model directory, even while their bytes are read from staging. The budget
    is the existing StaticCallBudget reader/cache/time/byte policy; no CALL
    detection or target-program execution is performed here.
    """
    from scar.analysis.static_calls import StaticCallSession
    started = monotonic()
    counts, frontiers, shards, providers = Counter(), [], [], {}
    session = StaticCallSession(directory, out=out, logical_root=logical_root,
        expected_manifest_sha256=expected_manifest_sha256, budget=budget)
    counts["declared_class_bodies"] = sum(row["kind"] == "CLASS" for u in session.units for row in u["bodies"])
    visited, issue, enumeration_complete = set(), None, False

    def body(context, number, row):
        key = context.number, number
        if key not in visited:
            if len(visited) >= session.budget.max_bodies:
                raise OverflowError("static class body-read budget exhausted")
            visited.add(key)
        return session._body(context, number, row)

    def gap(kind, detail, unit, entry, definition=None):
        counts["frontier_" + kind] += 1
        frontiers.append({"kind": kind, "detail": detail, "unit_key": unit["key"],
                          "entry_key": entry, "definition": encode(definition) if definition is not None else None})

    try:
        with session:
            for number, unit in enumerate(session.units):
                session._check()
                if not any(row["kind"] == "CLASS" for row in unit["bodies"]):
                    counts["source_units_processed"] += 1
                    continue
                catalog = session._read(unit["artifacts"]["lexical"])
                entries = {row["entry_key"]: row for row in catalog["entries"]}
                children = [row for row in entries.values() if row["kind"] == "CLASS"]
                child_by_definition = {json.dumps(identity, sort_keys=True): child for child in children
                    for identity in child.get("semantic_definition_ids", ())}
                parents = dict.fromkeys(child["lexical_parent"] for child in children)
                rows = {row["entry_key"]: (i, row) for i, row in enumerate(unit["bodies"])}
                context = session._unit(number)
                seen_definitions = set()
                for key in parents:
                    if key not in rows:
                        gap("PARENT_ENTRY_UNAVAILABLE", "Original lexical parent has no canonical body row.", unit, key)
                        continue
                    parent = body(context, *rows[key])
                    if parent is None:
                        gap("PARENT_GRAPH_UNAVAILABLE", "Original parent body has no saved canonical graph.", unit, key)
                        continue
                    counts["parent_graphs_processed"] += 1
                    bindings = []
                    for construction in _constructions(parent):
                        counts["parent_constructions"] += 1
                        identity = json.dumps(encode(construction.definition), sort_keys=True)
                        seen_definitions.add(identity)
                        child = child_by_definition.get(identity)
                        if child is None or child["lexical_parent"] != key:
                            gap("SUITE_SOURCE_UNPAIRED", "Construction has no matching original lexical class child.",
                                unit, key, construction.definition)
                            continue
                        selected = rows.get(child["entry_key"])
                        suite = body(context, *selected) if selected is not None else None
                        if suite is None or type(suite.class_entry) not in (ClassSuiteOverlay, ClassSuiteMethodOverlay):
                            gap("SUITE_BODY_UNEXPANDED", "Original class has no expanded shared suite graph.",
                                unit, child["entry_key"], construction.definition)
                            continue
                        expansion = connect_class_suite(parent_namespace=parent.namespace, parent_graph=parent.graph,
                            construction=construction, suite_namespace=suite.namespace,
                            suite_graph=suite.graph, suite_overlay=suite.class_entry)
                        provider_wire = {"schema": "scar.static-class-provider", "schema_version": 1,
                                         "provider": encode(expansion.provider)}
                        payload = _canonical(provider_wire)
                        digest = hashlib.sha256(payload).hexdigest()
                        if digest not in providers:
                            descriptor = session._write("providers/" + digest + ".json.gz", payload)
                            artifact = ProviderArtifact(str(session.logical_out / descriptor["path"]),
                                descriptor["sha256"], descriptor["bytes"], "scar.static-class-provider/1")
                            providers[digest] = SourceArtifactLocator(artifact, descriptor["decoded_sha256"],
                                descriptor["decoded_bytes"], "gzip-canonical-json", "#/provider")
                        values = {f.name: getattr(expansion, f.name) for f in fields(expansion) if f.name != "provider"}
                        binding = StaticClassBuilderBinding(**values, provider=providers[digest])
                        bindings.append(binding)
                        counts["connected_class_constructions"] += 1
                        counts["parent_input_mappings"] += len(binding.inputs)
                        counts["suite_input_mappings"] += len(binding.suite_inputs)
                        counts["suite_completion_mappings"] += len(binding.suite_completions)
                        counts["parent_completion_mappings"] += len(binding.completions)
                        counts["connected_suites_with_residual"] += suite.class_entry.remaining is not None
                    if bindings:
                        shard = {"schema": "scar.static-class-bindings", "schema_version": 1,
                            "source_model": encode(session.basis), "parent": encode(parent.namespace),
                            "bindings": [encode(b) for b in bindings]}
                        descriptor = session._write("bindings/" + str(len(shards)).zfill(6) + ".json.gz", _canonical(shard))
                        shards.append({"artifact": descriptor, "artifact_path": descriptor["path"],
                            "parent": encode(parent.namespace), "parent_entry_key": key, "bindings": len(bindings)})
                for identity, child in child_by_definition.items():
                    if identity not in seen_definitions:
                        gap("PARENT_CONSTRUCTION_UNEXPANDED", "No original construction record for this lexical class.",
                            unit, child["entry_key"])
                counts["source_units_processed"] += 1
                if progress is not None:
                    progress({"stage": "STATIC_CLASS_RELATIONS", "source_units_processed": number + 1,
                        "source_units_total": len(session.units), "last_source_path": unit["path"],
                        "connected_class_constructions": counts["connected_class_constructions"]})
            enumeration_complete = True
    except (TimeoutError, OverflowError) as error:
        issue = {"kind": type(error).__name__, "detail": str(error)}
    counts["body_records_read"] = len(visited)
    counts["shared_provider_graphs"] = len(providers)
    counts["published_parent_shards"] = len(shards)
    counts["published_bindings"] = sum(row["bindings"] for row in shards)
    return {"schema": "scar.static-class-publication", "schema_version": 1,
        "source_model": encode(session.basis), "input_manifest_sha256": session.manifest_sha256,
        "artifacts": session.artifacts, "shards": shards, "counts": dict(counts), "frontiers": frontiers,
        "scope": {"enumeration_complete": enumeration_complete, "conditional_builder_selection": True,
            "whole_program_model_complete": False, "effects_closed": False, "target_executed": False},
        "issue": issue, "analyzer_seconds": monotonic() - started}


def _read_artifact(artifact, *, max_bytes):
    path = Path(artifact.uri)
    if not path.is_absolute() or path.resolve() != path or path.is_symlink() or not path.is_file():
        raise ValueError("class index artifact is absent or traverses a symlink")
    with path.open("rb") as stream:
        stored = stream.read(min(artifact.size_bytes, max_bytes) + 1)
    if (len(stored) != artifact.size_bytes or len(stored) > max_bytes
            or hashlib.sha256(stored).hexdigest() != artifact.sha256):
        raise ValueError("class index stored receipt differs or exceeds budget")
    return stored


def _read_json_artifact(artifact, *, max_bytes):
    stored = _read_artifact(artifact, max_bytes=max_bytes)
    if stored[:2] == b"\x1f\x8b":
        with gzip.GzipFile(fileobj=io.BytesIO(stored)) as stream:
            raw = stream.read(max_bytes + 1)
        if len(raw) > max_bytes:
            raise OverflowError("class index decoded artifact exceeds budget")
    else:
        raw = stored
    return strict_loads(raw.decode()), raw


def read_static_class_links(directory, publication, *, index_directory=None, logical_root=None,
                            max_bytes=256_000_000):
    """Freshly read stored bindings and re-derive them from original inputs.

    ``directory`` is the original program model. An unpublished staging index
    may supply ``index_directory``; otherwise it is the source-basis parent.
    This reader executes no target or saved validation result.
    """
    from scar.analysis.static_calls import input_basis_unit
    from scar.analysis.static_program import read_static_program
    root = Path(directory).absolute()
    manifest = read_static_program(root, verify=False)
    if publication.get("schema") != "scar.static-class-publication" or publication.get("schema_version") != 1:
        raise ValueError("unsupported static class publication")
    basis_artifact = decode(ProviderArtifact, publication["source_model"])
    logical_index = Path(basis_artifact.uri).parent
    index_root = Path(index_directory).absolute() if index_directory is not None else logical_index
    logical_model = Path(logical_root).absolute() if logical_root is not None else root

    def index_artifact(artifact):
        from dataclasses import replace
        try:
            relative = Path(artifact.uri).relative_to(logical_index)
        except ValueError:
            raise ValueError("provider artifact escapes its owned class index") from None
        return replace(artifact, uri=str(index_root / relative))

    basis, _ = _read_json_artifact(index_artifact(basis_artifact), max_bytes=max_bytes)
    if (basis.get("schema") != "scar.static-call-source-basis" or basis.get("schema_version") != 1
            or basis["logical_root"] != str(logical_model)
            or basis["units"] != [input_basis_unit(u) for u in manifest["units"]]):
        raise ValueError("class source basis differs from current original inputs")
    cache, providers, catalogs = {}, {}, {}

    def original(namespace):
        if namespace in cache:
            return cache[namespace]
        locator = namespace.graph
        declaration = locator.declaration
        match = re.fullmatch(r"#/units/(\d+)/bodies/(\d+)/artifact", declaration.locator) if declaration else None
        if declaration is None or declaration.artifact != basis_artifact or match is None:
            raise ValueError("class namespace has no original basis declaration")
        i, j = map(int, match.groups())
        unit = basis["units"][i]
        row = unit["bodies"][j]
        descriptor = row["artifact"]
        if (locator.artifact.uri != str(logical_model / descriptor["path"])
                or locator.artifact.sha256 != descriptor["sha256"] or locator.artifact.size_bytes != descriptor["bytes"]
                or locator.decoded_sha256 != descriptor["decoded_sha256"]
                or locator.decoded_bytes != descriptor["decoded_bytes"] or locator.pointer != "#/graph"):
            raise ValueError("class namespace receipt differs from original body declaration")
        from dataclasses import replace
        physical = replace(locator.artifact, uri=str(root / descriptor["path"]))
        document, raw = _read_json_artifact(physical, max_bytes=max_bytes)
        if len(raw) != locator.decoded_bytes or hashlib.sha256(raw).hexdigest() != locator.decoded_sha256:
            raise ValueError("class original decoded body receipt differs")
        graph = load_core(json.dumps(document["graph"], allow_nan=False))
        if i not in catalogs:
            lexical = unit["artifacts"]["lexical"]
            lexical_artifact = ProviderArtifact(str(root / lexical["path"]), lexical["sha256"],
                lexical["bytes"], "scar.static-lexical")
            lexical_document, lexical_raw = _read_json_artifact(lexical_artifact, max_bytes=max_bytes)
            if (len(lexical_raw) != lexical["decoded_bytes"]
                    or hashlib.sha256(lexical_raw).hexdigest() != lexical["decoded_sha256"]):
                raise ValueError("class original lexical receipt differs")
            catalogs[i] = {entry["entry_key"]: entry for entry in lexical_document["entries"]}
        lexical_entry = catalogs[i][row["entry_key"]]
        if (namespace.region != graph.root or namespace.entry != document["metadata"]["entry"]
                or encode(namespace.definition) not in (lexical_entry.get("semantic_definition_ids") or ())
                or encode(namespace.source) != lexical_entry.get("source_ref")):
            raise ValueError("class body namespace differs from original interface")
        if namespace.graph_representation != "scar.program-graph/" + str(document["graph"]["schema_version"]):
            raise ValueError("class original core representation differs")
        if document.get("class") is not None:
            overlay = decode_class_entry_overlay(document["class"])
            constructions = ()
        elif document.get("module") is not None:
            overlay = None
            constructions = tuple(getattr(decode_frame_body(document["module"]), "class_constructions", ()))
        else:
            overlay = None
            constructions = tuple(decode_language_overlay(document["language"]).class_constructions) if document.get("language") else ()
        cache[namespace] = graph, overlay, constructions
        return cache[namespace]

    result = []
    for shard in publication["shards"]:
        descriptor = shard["artifact"]
        path = Path(descriptor["path"])
        if path.is_absolute() or ".." in path.parts:
            raise ValueError("class shard escapes its index")
        artifact = ProviderArtifact(str(index_root / path), descriptor["sha256"], descriptor["bytes"],
                                    "scar.static-class-bindings/1")
        document, raw = _read_json_artifact(artifact, max_bytes=max_bytes)
        if (len(raw) != descriptor["decoded_bytes"] or hashlib.sha256(raw).hexdigest() != descriptor["decoded_sha256"]
                or document.get("schema") != "scar.static-class-bindings" or document.get("schema_version") != 1
                or document["source_model"] != publication["source_model"]):
            raise ValueError("class binding shard receipt/schema/basis differs")
        for record in document["bindings"]:
            binding = decode(StaticClassBuilderBinding, record)
            if encode(binding.parent) != document["parent"] or encode(binding.parent) != shard["parent"]:
                raise ValueError("class binding is owned by a different parent shard")
            locator = binding.provider
            if locator not in providers:
                provider_document, raw = _read_json_artifact(index_artifact(locator.artifact), max_bytes=max_bytes)
                if (len(raw) != locator.decoded_bytes or hashlib.sha256(raw).hexdigest() != locator.decoded_sha256
                        or locator.pointer != "#/provider" or provider_document.get("schema") != "scar.static-class-provider"
                        or provider_document.get("schema_version") != 1):
                    raise ValueError("class provider decoded receipt/schema differs")
                providers[locator] = decode(ClassBuilderProvider, provider_document["provider"])
            parent_graph, _, constructions = original(binding.parent)
            suite_graph, suite_overlay, _ = original(binding.suite)
            if binding.construction not in constructions:
                raise ValueError("class binding is not an original parent construction")
            values = {f.name: getattr(binding, f.name) for f in fields(binding) if f.name != "provider"}
            expansion = ClassBuilderExpansion(**values, provider=providers[locator])
            validate_class_builder_expansion(expansion, parent_graph=parent_graph,
                suite_graph=suite_graph, suite_overlay=suite_overlay)
            result.append(expansion)
    if len(result) != publication["counts"]["published_bindings"]:
        raise ValueError("class binding publication count differs")
    return tuple(result)
