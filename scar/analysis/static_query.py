"""Read-only navigation of saved static source and canonical fragment IDs.

Queries do not execute/import target code or rebuild any graph. The default
reads the manifest only; selected fragments are checked against both stored
and decoded receipts before projecting their original records.
"""
from __future__ import annotations

import argparse
import gzip
import hashlib
import io
import json
from pathlib import Path


def _wire(value):
    if value is None:
        return None
    if type(value) is str:
        return value
    if type(value) is dict:
        return value.get("wire")
    raise ValueError("expected an original wire identity")


def _page(rows, limit):
    return {"total": len(rows), "returned": min(limit, len(rows)),
            "truncated": len(rows) > limit, "items": rows[:limit]}


class _Fragments:
    def __init__(self, root):
        self.root = root
        self.receipts = []
        self.core_graphs = {}

    def read(self, descriptor):
        relative = Path(descriptor["path"])
        if relative.is_absolute() or ".." in relative.parts:
            raise ValueError("fragment path escapes static model")
        path = self.root / relative
        if path.resolve() != path or path.is_symlink() or not path.is_file():
            raise ValueError("fragment is absent or traverses a symlink")
        stored_size, decoded_size = descriptor["bytes"], descriptor["decoded_bytes"]
        if any(type(n) is not int or n < 0 for n in (stored_size, decoded_size)):
            raise ValueError("fragment byte receipts must be nonnegative integers")
        with path.open("rb") as source:
            payload = source.read(stored_size + 1)
        if len(payload) != stored_size or hashlib.sha256(payload).hexdigest() != descriptor["sha256"]:
            raise ValueError("stored fragment receipt differs: " + str(relative))
        with gzip.GzipFile(fileobj=io.BytesIO(payload)) as source:
            decoded = source.read(decoded_size + 1)
        if (len(decoded) != decoded_size or
                hashlib.sha256(decoded).hexdigest() != descriptor["decoded_sha256"]):
            raise ValueError("decoded fragment receipt differs: " + str(relative))
        document = json.loads(decoded)
        if type(document) is not dict:
            raise ValueError("fragment root must be a JSON object")
        self.receipts.append(dict(descriptor))
        return document


def _file_matches(path, selector):
    if selector is None:
        return True
    selected = Path(selector)
    if selected.is_absolute():
        return path == str(selected)
    suffix = selected.as_posix()
    return path == suffix or path.endswith("/" + suffix)


def _entry_matches(entry, name, kind):
    if kind is not None and entry["kind"].casefold() != kind.casefold():
        return False
    if name is None:
        return True
    identities = [entry["entry_key"], *(_wire(item) for item in entry.get("semantic_definition_ids") or ())]
    return name in identities or any(name in entry.get(field, "") for field in ("name", "qualname"))


def _entry_view(entry, unit, symbols, limit):
    keys = entry.get("symbol_table_candidates", [])
    candidates = []
    for key in keys:
        if key not in symbols:
            raise ValueError("lexical symbol candidate is not in its original catalog")
        table = symbols[key]
        candidates.append({**{name: table.get(name) for name in (
            "table_path", "parent", "kind", "name", "lineno", "free_names")},
            "symbols": _page(table.get("symbols", []), limit)})
    bodies = [body for body in unit.get("bodies", ()) if body.get("entry_key") == entry["entry_key"]]
    if len(bodies) > 1:
        raise ValueError("duplicate body status for one original entry")
    fields = ("entry_key", "kind", "name", "qualname", "phase", "definition_phase", "span",
              "lexical_parent", "source_ref", "semantic_definition_ids", "semantic_source_candidates",
              "catalog_status", "support_status", "language_version_dependent", "closure_names", "closure_status",
              "subject_entry_key", "lowering_route")
    body = bodies[0] if bodies else None
    return {**{name: entry.get(name) for name in fields}, "file": unit["path"],
            "namespace_root": unit["namespace_root"], "symbol_table_candidates": candidates,
            "body": None if body is None else {name: body[name] for name in (
                "status", "reason", "artifact", "gaps", "construction_operations", "issue", "last_attempt_issue") if name in body}}


def _catalog(unit, fragments):
    descriptor = unit.get("artifacts", {}).get("lexical")
    if descriptor is None:
        return None
    catalog = fragments.read(descriptor)
    if (catalog.get("schema") != "scar.static-lexical-catalog" or catalog.get("schema_version") != 1
            or catalog.get("path") != unit["path"] or catalog.get("namespace_root") != unit["namespace_root"]
            or catalog.get("fingerprint") != "sha256:" + unit["decoded_sha256"]):
        raise ValueError("lexical catalog belongs to another source unit")
    if len({row["entry_key"] for row in catalog["entries"]}) != len(catalog["entries"]):
        raise ValueError("duplicate lexical entry identity")
    return catalog


def _canonical_dependencies(unit, entries, fragments, limit):
    """Project selected canonical bodies, retaining original typed IDs/ports."""
    from scar.ir.program.codec import loads
    selected = {entry["entry_key"]: entry for entry in entries}
    rows = []
    for body in unit.get("bodies", ()):
        if body["entry_key"] not in selected:
            continue
        row = {key: body.get(key) for key in
               ("entry_key", "status", "reason", "plan", "cache_key", "construction_operations")}
        if "artifact" not in body:
            rows.append(row)
            continue
        document = fragments.read(body["artifact"])
        if document.get("schema") != "scar.static-body" or document.get("schema_version") != 1:
            raise ValueError("unsupported canonical body container")
        if document.get("entry_key") != body["entry_key"] or document.get("cache_key") != body.get("cache_key"):
            raise ValueError("body belongs to a different lexical entry")
        if document.get("status") != body["status"]:
            raise ValueError("canonical body status differs from its ledger")
        if document.get("inputs") != {name: unit["artifacts"].get(name) for name in
                                       ("source", "semantic", "semantics", "control")}:
            raise ValueError("body shared source fragments differ from the selected unit")
        compilation = document.get("static_compilation")
        row["static_compilation"] = compilation
        if compilation is None or "layout" not in compilation:
            row["compiler_layout"] = {"status": "NOT_RECORDED", "runtime_facts": False}
        else:
            from scar.analysis.static_compilation import StaticCompilerLayout
            layout = StaticCompilerLayout.from_dict(compilation["layout"])
            if (compilation.get("evidence_kind") != "SOURCE_COMPILATION"
                    or compilation.get("runtime_code_instance_established") is not False
                    or compilation.get("snapshot", {}).get("path") != unit["path"]
                    or compilation.get("snapshot", {}).get("fingerprint") != "sha256:"+unit["decoded_sha256"]
                    or compilation.get("namespace_root") != unit["namespace_root"]):
                raise ValueError("compiler facts differ from the original static source provenance")
            row["compiler_layout"] = {"status": "SOURCE_COMPILATION_FACTS", "layout": layout.to_dict(),
                "code_layout_key": compilation["code_layout_key"], "runtime_facts": False,
                "independent_compiler_replayed": False}
        graph_document = document.get("graph")
        if graph_document is None:
            row["canonical_graph"] = None
            row["issue"] = document.get("issue")
            rows.append(row)
            continue
        if document["status"] != "LOWERED_WITH_GAPS":
            raise ValueError("a non-lowered body cannot publish a canonical graph")
        metadata = document["metadata"]
        if (metadata["source"]["path"] != unit["path"] or
                metadata["source"]["fingerprint"] != "sha256:" + unit["decoded_sha256"]):
            raise ValueError("canonical body source differs from selected source unit")
        # Ordinary canonical structure, rather than a purity or execution test.
        graph = loads(json.dumps(graph_document, allow_nan=False))
        fragments.core_graphs[body["artifact"]["path"]] = graph
        interface = document.get("interface")
        module_document = document.get("module")
        class_document = document.get("class")
        module_view = None
        class_view = None
        if module_document is not None:
            from scar.ir.program.module_entries import decode_frame_body, StaticModuleEntryDeclaration
            from scar.ir.program.source_subjects import SourceCompilationFrameRoot
            overlay = decode_frame_body(module_document)
            subject = overlay.declaration.unit
            if (selected[body["entry_key"]]["kind"] != "MODULE" or interface is not None
                    or type(overlay.declaration) is not StaticModuleEntryDeclaration
                    or subject.snapshot.path != unit["path"] or subject.namespace_root != unit["namespace_root"]
                    or subject.snapshot.fingerprint != "sha256:" + unit["decoded_sha256"]
                    or module_document["declaration"]["unit"]["initializer"] not in
                       (selected[body["entry_key"]].get("semantic_definition_ids") or ())
                    or len(graph.frame_roots) != 1 or type(graph.frame_roots[0]) is not SourceCompilationFrameRoot
                    or graph.frame_roots[0].code != overlay.declaration.compilation):
                raise ValueError("static module body differs from the original initializer/compiler root")
            metadata = {**metadata, "operation_links": module_document["operation_links"],
                        "value_links": module_document["value_links"], "use_links": module_document["use_links"]}
            module_view = {"declaration": module_document["declaration"], "status": overlay.status.value,
                           "prefix": module_document["prefix"], "remaining": module_document["remaining"],
                           "frontiers": _page(module_document["frontiers"], limit)}
            if "compiler_prologue" in module_document:
                from scar.analysis.source_module_compiler_lowering import validate_compiler_prologue_core
                validate_compiler_prologue_core(overlay, graph)
                module_view["compiler_prologue"] = module_document["compiler_prologue"]
                module_view["compiler_prologue_core_checked"] = True
                module_view["compiler_prologue_source_replayed"] = False
        elif class_document is not None:
            from scar.ir.program.class_entries import (
                decode_class_entry_overlay, validate_class_entry_core, ClassSuiteOverlay, ClassSuiteMethodOverlay,
            )
            from scar.ir.program.source_subjects import SourceCompilationFrameRoot,FrameKind
            from scar.ir.record_codec import decode, encode
            from scar.ir.program.source import LoweringMetadata
            overlay=decode_class_entry_overlay(class_document)
            typed_metadata=decode(LoweringMetadata,metadata)
            validate_class_entry_core(overlay,graph,typed_metadata)
            if (selected[body["entry_key"]]["kind"]!="CLASS" or interface is not None
                    or encode(overlay.source)!=selected[body["entry_key"]]["source_ref"]
                    or encode(overlay.definition) not in (selected[body["entry_key"]].get("semantic_definition_ids") or ())
                    or len(graph.frame_roots)!=1 or type(graph.frame_roots[0]) is not SourceCompilationFrameRoot
                    or graph.frame_roots[0].kind is not FrameKind.CLASS or graph.frame_roots[0].code!=overlay.compilation
                    or graph.frame_roots[0].entry!=overlay.interface or graph.frame_roots[0].scope!=overlay.root_scope
                    or type(overlay) not in (ClassSuiteOverlay, ClassSuiteMethodOverlay) and overlay.required_expansion.region!=graph.root):
                raise ValueError("class body differs from the original source/compiler/frame namespace")
            class_view={key:class_document[key] for key in ("definition","parent_definition","source","compilation","interface","status")}
            class_view.update(inputs=_page(class_document["inputs"],limit),frontiers=_page(class_document["frontiers"],limit))
            if type(overlay) in (ClassSuiteOverlay, ClassSuiteMethodOverlay):
                class_view.update(profile=overlay.profile,normal_payload=overlay.normal_payload.value,
                    body_statements=_page(class_document["statements"],limit),
                    compiler_instructions=_page(class_document["instructions"],limit),
                    protocols=_page(class_document["protocols"],limit),
                    cells=_page(class_document["cells"],limit),factories=_page(class_document["factories"],limit),
                    constants=_page(class_document["constants"],limit),remaining=class_document["remaining"],
                    core_checked=True,source_replayed=False)
                if type(overlay) is ClassSuiteMethodOverlay:
                    class_view.update(method_lookups=_page(class_document["method_lookups"],limit),
                                      method_calls=_page(class_document["method_calls"],limit))
            else:
                required=class_document["required_expansion"]
                class_view.update(body_statements=_page(required["body_statements"],limit),
                    compiler_stages=_page(required["compiler_stages"],limit),normal_payload=required["normal_payload"],
                    required_expansion={key:required[key] for key in ("region","operation","status")})
        elif (interface is None or interface.get("definition") not in
                  (selected[body["entry_key"]].get("semantic_definition_ids") or ())
                  or interface.get("region") != graph_document["root"]):
            raise ValueError("canonical body interface differs from the selected definition/root")
        row.update(canonical_root=graph_document["root"],
                   canonical_schema=graph_document["schema_version"],
                   regions=_page(graph_document["regions"], limit),
                   operations=_page(graph_document["operations"], limit),
                   operation_order="storage tuple; execution order follows each Region's CFG blocks",
                   values=_page(graph_document["values"], limit),
                   state_locations=_page(graph_document["locations"], limit),
                   interface=document.get("interface"),
                   module=module_view,
                   class_entry=class_view,
                   frame_roots=graph_document.get("frame_roots", []),
                   producer=document.get("producer"),
                   targets=_page(metadata.get("call_targets", []), limit),
                   operation_sources=_page(metadata.get("operation_links", []), limit),
                   value_sources=_page(metadata.get("value_links", []), limit),
                   use_sources=_page(metadata.get("use_links", []), limit),
                   source_gaps=_page(metadata.get("gaps", []), limit),
                   language_capabilities=(document.get("language") or {}).get("capabilities", []),
                   core_structure_checked=True, source_snapshot_match=True,
                   source_mapping_revalidated=False, source_language_revalidated=False,
                   independent_compiler_replayed=False,
                   counts={"regions": len(graph.regions), "operations": len(graph.operations),
                           "values": len(graph.values), "state_locations": len(graph.locations)},
                   projection_closed=False)
        rows.append(row)
    return {"bodies": rows, "qualification": "Ordinary canonical structure checked; original ports, source links and state versions projected, without purity or execution claims."}


def _rule_plans(unit, entries, fragments, limit):
    descriptor = unit.get("artifacts", {}).get("rules")
    if descriptor is None:
        return {"status": "RULE_LEDGER_NOT_BUILT"}
    document = fragments.read(descriptor)
    source = document.get("source", {})
    if (document.get("schema") != "scar.static-rule-ledger" or document.get("schema_version") != 1
            or source.get("path") != unit["path"] or source.get("namespace_root") != unit["namespace_root"]
            or source.get("fingerprint") != "sha256:" + unit["decoded_sha256"]
            or source.get("artifact") != unit["artifacts"]["source"]):
        raise ValueError("rule ledger belongs to another source unit")
    selected = {entry["entry_key"] for entry in entries}
    plans = []
    for plan in document["plans"]:
        if plan["entry_key"] in selected:
            plans.append({**{key: plan.get(key) for key in
                              ("entry_key", "kind", "status", "selected_profile", "capabilities")},
                          "rules": _page(plan.get("rules", []), limit),
                          "prerequisites": _page(plan.get("prerequisites", []), limit),
                          "unsupported_shapes": _page(plan.get("unsupported_shapes", []), limit)})
    if {plan["entry_key"] for plan in plans} != selected:
        raise ValueError("rule ledger omits a selected source entry")
    return {"status": "ORIGINAL_STATIC_RULE_PLANS", "plans": plans,
            "language_semantics_complete": document["language_semantics_complete"]}


def _call_relations(manifest, unit, entries, fragments, limit):
    """Read qualified v1-v4 relations and replay their original endpoint joins."""
    from collections import OrderedDict
    from types import SimpleNamespace
    from scar.analysis.static_calls import input_basis_unit
    from scar.analysis.static_function_environment import (
        derive_function_environment_routes, validate_static_body_namespace, _source_reference,
    )
    from scar.analysis.static_namespace import NamespaceDependencies, normal_reference
    from scar.ir.program.codec import loads as load_core
    from scar.ir.program.model import OperationResult
    from scar.ir.program.queries import ProgramIndex
    from scar.ir.program.static_calls import loads as load_relations
    from scar.ir.record_codec import encode

    publication = manifest.get("static_calls")
    if publication is None:
        return {"status": "STATIC_CALL_LINKS_NOT_BUILT"}
    selected = {entry["entry_key"]: entry for entry in entries}
    descriptors = {row["path"]: row for row in publication["artifacts"]}
    if len(descriptors) != len(publication["artifacts"]):
        raise ValueError("duplicate static call artifact declaration")
    bases = [row for row in descriptors.values() if row.get("kind") == "BASIS"]
    if len(bases) != 1:
        raise ValueError("static call publication needs one immutable input-basis receipt")
    basis = bases[0]
    basis_document = fragments.read(basis)
    if (basis_document.get("schema") != "scar.static-call-source-basis"
            or basis_document.get("schema_version") != 1
            or basis_document.get("logical_root") != str(fragments.root)
            or basis_document.get("input_manifest_sha256") != publication.get("input_manifest_sha256")
            or basis_document.get("units") != [input_basis_unit(row) for row in manifest["units"]]):
        raise ValueError("static call input namespace/source/body basis differs from the current model")
    basis_uri = str(fragments.root / basis["path"])
    registry = {}
    for number, owner in enumerate(manifest["units"]):
        for position, row in enumerate(owner["bodies"]):
            if "artifact" not in row:
                continue
            uri = str(fragments.root / row["artifact"]["path"])
            if uri in registry:
                raise ValueError("qualified body artifact has multiple manifest owners")
            registry[uri] = number, position, owner, row

    # Foreign graph/index lifetimes are bounded. Selected canonical graphs
    # already owned by the enclosing query can be reused without recopying.
    cache, catalogs, source_facts = OrderedDict(), OrderedDict(), OrderedDict()
    cached_bytes = 0
    cache_limit = 128 * 1024 * 1024
    def catalog_for(owner):
        key = owner["key"]
        if key not in catalogs:
            catalogs[key] = _catalog(owner, fragments)
            if len(catalogs) > 8:
                catalogs.popitem(last=False)
        else:
            catalogs.move_to_end(key)
        return catalogs[key]

    def basis_artifact(artifact):
        return (artifact.uri == basis_uri and artifact.sha256 == basis["sha256"]
                and artifact.size_bytes == basis["bytes"]
                and artifact.schema == "scar.static-call-source-basis/1")

    def load_body(namespace):
        nonlocal cached_bytes
        namespace.__post_init__()
        location = registry.get(namespace.graph.artifact.uri)
        if location is None:
            raise ValueError("qualified body is absent from the current model")
        number, position, owner, row = location
        descriptor = row["artifact"]
        locator = namespace.graph
        if (locator.artifact.sha256 != descriptor["sha256"]
                or locator.artifact.size_bytes != descriptor["bytes"]
                or locator.artifact.schema != "scar.static-body/1"
                or locator.decoded_sha256 != descriptor["decoded_sha256"]
                or locator.decoded_bytes != descriptor["decoded_bytes"]
                or locator.representation != "gzip-canonical-json" or locator.pointer != "#/graph"
                or locator.declaration is None
                or not basis_artifact(locator.declaration.artifact)
                or locator.declaration.locator != f"#/units/{number}/bodies/{position}/artifact"):
            raise ValueError("qualified body stored/decoded receipt or original declaration differs")
        uri = locator.artifact.uri
        if uri in cache:
            loaded, _ = cache[uri]
            cache.move_to_end(uri)
            validate_static_body_namespace(loaded.graph, loaded.document, namespace)
            if loaded.namespace != namespace:
                raise ValueError("qualified namespace relabels an already read original body")
            return loaded
        document = fragments.read(descriptor)
        if (document.get("schema") != "scar.static-body" or document.get("schema_version") != 1
                or document.get("entry_key") != row["entry_key"]
                or document.get("cache_key") != row.get("cache_key")
                or document.get("status") != row["status"] or row["status"] != "LOWERED_WITH_GAPS"
                or document.get("graph") is None
                or document.get("inputs") != {name: owner["artifacts"].get(name)
                                             for name in ("source", "semantic", "semantics", "control")}):
            raise ValueError("qualified endpoint differs from its original body ledger/shared inputs")
        graph = fragments.core_graphs.get(descriptor["path"])
        if graph is None:
            graph = load_core(json.dumps(document["graph"], allow_nan=False))
        metadata = validate_static_body_namespace(graph, document, namespace)
        if (metadata.source.path != owner["path"]
                or metadata.source.fingerprint != "sha256:" + owner["decoded_sha256"]):
            raise ValueError("qualified endpoint snapshot differs from its original source unit")
        catalog = catalog_for(owner)
        original = [e for e in (catalog or {}).get("entries", ()) if e["entry_key"] == row["entry_key"]]
        if (len(original) != 1
                or encode(namespace.definition) not in (original[0].get("semantic_definition_ids") or ())
                or original[0]["kind"] != "MODULE" and encode(namespace.source) != original[0].get("source_ref")):
            raise ValueError("qualified endpoint differs from its original lexical definition/source")
        index = ProgramIndex(graph)
        loaded = SimpleNamespace(graph=graph, index=index, document=document, namespace=namespace,
            unit=owner, row=row, unit_number=number, body_position=position, catalog=catalog,
            dependencies=NamespaceDependencies(graph, document, index=index))
        cache[uri] = loaded, descriptor["decoded_bytes"]
        cached_bytes += descriptor["decoded_bytes"]
        while cache and (len(cache) > 16 or cached_bytes > cache_limit):
            _, (_, size) = cache.popitem(last=False)
            cached_bytes -= size
        return loaded

    def check_definition(definition, owner):
        if (not basis_artifact(definition.root.artifact)
                or definition.root.decoded_sha256 != basis["decoded_sha256"]
                or definition.root.decoded_bytes != basis["decoded_bytes"]
                or definition.root.representation != "gzip-canonical-json"
                or definition.context.namespace_root != owner["namespace_root"]
                or definition.snapshot.path != owner["path"]
                or definition.snapshot.fingerprint != "sha256:" + owner["decoded_sha256"]):
            raise ValueError("qualified definition belongs to another source namespace/basis")
        number = next(n for n, candidate in enumerate(manifest["units"]) if candidate is owner)
        if definition.root.pointer != f"#/units/{number}":
            raise ValueError("qualified definition root points to another source unit")
        descriptor = owner["artifacts"]["semantic"]
        locator = definition.graph
        if (locator.artifact.uri != str(fragments.root / descriptor["path"])
                or locator.artifact.sha256 != descriptor["sha256"]
                or locator.artifact.size_bytes != descriptor["bytes"]
                or locator.artifact.schema != "scar.ir.v2.semantic"
                or locator.decoded_sha256 != descriptor["decoded_sha256"]
                or locator.decoded_bytes != descriptor["decoded_bytes"]
                or locator.representation != "gzip-canonical-json"
                or locator.declaration is None or not basis_artifact(locator.declaration.artifact)
                or locator.declaration.locator != f"#/units/{number}/artifacts/semantic"):
            raise ValueError("qualified definition semantic artifact/declaration differs from its source unit")
        if owner["key"] not in source_facts:
            from scar.analysis.source_layers import _digest
            contexts, definitions = [], None
            for name in ("semantic", "semantics", "control"):
                original = fragments.read(owner["artifacts"][name])
                contexts.append(_digest(original))
                if name == "semantic":
                    definitions = {_wire(row["id"]): (position, row["code_id"], row["source_atoms"],
                        row.get("metadata", {}).get("phase"))
                        for position, row in enumerate(original["definitions"])}
            source_facts[owner["key"]] = tuple(contexts), definitions
            if len(source_facts) > 8:
                source_facts.popitem(last=False)
        else:
            source_facts.move_to_end(owner["key"])
        contexts, definitions = source_facts[owner["key"]]
        if contexts != tuple(getattr(definition.context, name) for name in
                             ("semantic_sha256", "semantics_sha256", "control_sha256")):
            raise ValueError("qualified definition source context differs from the original fragments")
        original = definitions.get(definition.definition.wire)
        if (original is None or locator.pointer != f"#/definitions/{original[0]}"
                or original[1] != definition.source.atom_id.wire
                or encode(definition.source.atom_id) not in original[2] or original[3] != "call_time"):
            raise ValueError("qualified definition does not point to its original semantic source record")
        declarations = [e for e in (catalog_for(owner) or {}).get("entries", ())
            if e["kind"] in ("FUNCTION", "ASYNC_FUNCTION", "LAMBDA")
            and e.get("source_ref") == encode(definition.source)
            and encode(definition.definition) in (e.get("semantic_definition_ids") or ())]
        if len(declarations) != 1:
            raise ValueError("qualified definition has no unique original lexical source declaration")

    checked_creations = set()
    def check_creation(namespace, creation):
        key = namespace, creation
        if key in checked_creations:
            return
        body = load_body(namespace)
        dependencies, document = body.dependencies, body.document
        check_definition(creation.definition, body.unit)
        if dependencies.protocols.get(creation.factory) not in ("MAKE_FUNCTION_314", "MAKE_NESTED_FUNCTION"):
            raise ValueError("creation relation is not its original factory protocol")
        normal = normal_reference(body.index, creation.factory, blocks=dependencies.blocks)
        if normal != (creation.normal_edge, creation.normal_value):
            raise ValueError("creation relation changed its original NORMAL reference port")
        code = body.index.use_site(creation.code_use)
        factory = body.index.operations[creation.factory]
        if code.operation != creation.factory or code.use.id not in factory.invoke_arguments:
            raise ValueError("creation code Use is not an original factory input")
        source_rows = (document.get("module") or document["metadata"]).get("use_links", ())
        source_code = [r for r in source_rows if r["operation"] == encode(creation.factory)
                       and r["use"] == encode(creation.code_use)]
        if len(source_code) != 1 or (source_code[0]["role"], source_code[0]["index"]) != ("function-code", 0):
            raise ValueError("creation code Use lost its original source role")
        links = (document.get("module") or document["metadata"]).get("operation_links", ())
        factory_links = [link for link in links if link["operation"] == encode(creation.factory)]
        if (len(factory_links) != 1
                or _source_reference(factory_links[0].get("source")) != creation.definition.source
                or encode(creation.definition.snapshot) != document["metadata"]["source"]):
            raise ValueError("factory creation does not retain its original source function definition")
        declaration = source_facts[body.unit["key"]][1].get(_wire(factory_links[0].get("semantic_operation")))
        if (declaration is None or declaration[3] != "definition_time"
                or declaration[1] != creation.definition.source.atom_id.wire
                or encode(creation.definition.source.atom_id) not in declaration[2]):
            raise ValueError("factory source lost its original definition-time declaration")
        origin = body.index.values[code.use.value].origin
        if type(origin) is not OperationResult or origin.operation != creation.code_constant_operation:
            raise ValueError("factory code is not its original constant operation result")
        module_constants = (document.get("module") or {}).get("constants", ())
        original_constant = any(record["operation"] == encode(creation.code_constant_operation)
            and record["code_key"] == creation.code_layout_key
            and tuple(record["constant_path"]) == creation.constant_path for record in module_constants)
        class_overlay = document.get("class") or {}
        if class_overlay.get("class_record") in ("STATIC_CLASS_SUITE_OVERLAY", "STATIC_CLASS_SUITE_METHOD_OVERLAY"):
            original_constant = (class_overlay["compilation"]["code_layout_key"] == creation.code_layout_key
                and any(record["operation"] == encode(creation.code_constant_operation)
                        and record["reference"] == encode(code.use.value)
                        and tuple(record["constant_path"]) == creation.constant_path
                        for record in class_overlay["constants"])
                and any(record["operation"] == encode(creation.factory)
                        and record["reference"] == encode(creation.normal_value)
                        and record["definition"] == encode(creation.definition.definition)
                        and record["code_reference"] == encode(code.use.value)
                        and tuple(record["constant_path"]) == creation.constant_path
                        for record in class_overlay["factories"]))
        if dependencies.protocols[creation.factory] == "MAKE_NESTED_FUNCTION":
            from scar.analysis.static_nested_creation import validate_nested_function_creation
            source = fragments.read(body.unit["artifacts"]["source"])
            if (source.get("path") != body.unit["path"]
                    or source.get("namespace_root") != body.unit["namespace_root"]
                    or type(source.get("text")) is not str
                    or hashlib.sha256(source["text"].encode()).hexdigest() != body.unit["decoded_sha256"]):
                raise ValueError("nested factory source text differs from its original source unit")
            validate_nested_function_creation(creation, graph=body.graph, index=body.index,
                document=document, namespace=body.namespace, source_text=source["text"])
            original_constant = True  # Shared source/compiler rule proved the exact parent/child code slot.
        constant = body.index.operations.get(creation.code_constant_operation)
        if not original_constant or constant is None or code.use.value not in constant.results:
            raise ValueError("creation code slot/qualified definition differs from its original creator")
        checked_creations.add(key)

    def check_environment_creation(route):
        check_creation(route.creation_body, route.creation)
        # The common environment validator replays caller/callee and creator
        # ports. In particular foreign factory IDs never index the caller.
        return load_body(route.creation_body)

    rows = []
    for item in publication.get("shards", ()):
        key = item.get("caller_entry_key")
        if key not in selected:
            continue
        relative = item.get("artifact_path") or item["artifact"]["path"]
        path = "indexes/calls/" + relative
        if path not in descriptors:
            raise ValueError("call shard is not registered in the current model")
        document = fragments.read(descriptors[path])
        shard = load_relations(json.dumps(document, allow_nan=False))
        caller = load_body(shard.caller)
        if (caller.unit is not unit or caller.row["entry_key"] != key
                or encode(shard.caller.definition) not in (selected[key].get("semantic_definition_ids") or ())
                or not basis_artifact(shard.source_model)):
            raise ValueError("static call shard differs from its selected original caller/input basis")
        owners = {op: region.id for region in caller.graph.regions for block in region.blocks for op in block.operations}
        for call in shard.calls:
            if call.operation not in owners:
                raise ValueError("static call operation is absent from its original graph namespace")
            if call.callee_use is not None:
                site = caller.index.use_site(call.callee_use)
                if (site.operation != call.operation or site.use.value != call.callee_value
                        or call.callee_use not in caller.index.operations[call.operation].invoke_arguments):
                    raise ValueError("static call callee Use/value differs from its original invoke")
            for flow in call.namespace_flows:
                caller.dependencies.validate(flow)
            for creation in call.function_creations:
                check_creation(caller.namespace, creation)
            for qualified in call.qualified_namespace_flows:
                load_body(qualified.body).dependencies.validate(qualified.flow)
            for qualified in call.qualified_function_creations:
                check_creation(qualified.body, qualified.creation)
            for flow in call.cross_body_namespace_flows:
                from scar.analysis.static_crossbody_namespace import (
                    StaticNamespaceBody, validate_cross_body_namespace_flow,
                )
                namespaces = {flow.write.body, flow.read.body, *(segment.body for segment in flow.segments)}
                for bridge in flow.bridges:
                    route = bridge.environment
                    check_environment_creation(route)
                    namespaces.update((route.caller, route.callee, route.creation_body))
                    for incoming in bridge.caller_owner_routes:
                        check_environment_creation(incoming)
                        namespaces.update((incoming.caller, incoming.callee, incoming.creation_body))
                endpoints = {}
                for namespace in namespaces:
                    body = load_body(namespace)
                    endpoints[namespace] = StaticNamespaceBody(
                        body.graph, body.document, namespace, body.index, body.dependencies)
                validate_cross_body_namespace_flow(flow, bodies=endpoints)
            for target in call.targets:
                if target.body is None:
                    # The source definition remains qualified even when no
                    # canonical body exists; do not invent a body to check it.
                    candidates = [owner for owner in manifest["units"]
                        if owner["path"] == target.definition.snapshot.path
                        and owner["namespace_root"] == target.definition.context.namespace_root]
                    if len(candidates) != 1:
                        raise ValueError("unlowered target definition has no original source unit")
                    check_definition(target.definition, candidates[0])
                    continue
                callee = load_body(target.body)
                check_definition(target.definition, callee.unit)
                if target.environment_routes:
                    for route in target.environment_routes:
                        check_environment_creation(route)
                    original_routes, _ = derive_function_environment_routes(
                        caller_graph=caller.graph, caller_document=caller.document, caller_namespace=caller.namespace,
                        callee_graph=callee.graph, callee_document=callee.document, callee_namespace=callee.namespace,
                        definition=target.definition, call_operation=call.operation, callee_use=call.callee_use,
                        creations=call.function_creations, qualified_creations=call.qualified_function_creations,
                        load_creation_body=load_body, caller_index=caller.index, callee_index=callee.index)
                    if any(route not in original_routes for route in target.environment_routes):
                        raise ValueError("function environment route differs from original qualified factory/call/member ports")
        relations = document["relations"]
        calls = [{**record, "owning_region": encode(owners[call.operation]),
                  "namespace_flows": _page(encode(call.namespace_flows), limit),
                  "function_creations": _page(encode(call.function_creations), limit),
                  "qualified_namespace_flows": _page(encode(call.qualified_namespace_flows), limit),
                  "qualified_function_creations": _page(encode(call.qualified_function_creations), limit),
                  "cross_body_namespace_flows": _page(encode(call.cross_body_namespace_flows), limit),
                  "targets": [{**target_record, "environment_routes": _page(encode(target.environment_routes), limit)}
                              for target_record, target in zip(record["targets"], call.targets)]}
                 for record, call in zip(relations["calls"], shard.calls)]
        rows.append({"entry_key": key, "caller": relations["caller"],
                     "storage_schema_version": document["schema_version"],
                     "v4_dependencies_checked": document["schema_version"] == 4,
                     "caller_meaning": "original stored graph namespace; owning_region identifies the lexical subgraph, not an observed calling frame",
                     "calls": _page(calls, limit)})
    return {"status": "QUALIFIED_CONDITIONAL_STATIC_CALL_RELATIONS", "shards": rows,
            "enumeration_status": publication.get("status"), "enumeration_complete": publication.get("complete"),
            "scope": publication.get("scope"), "counts": publication.get("counts"),
            "frontiers": _page(publication.get("frontiers", []), limit),
            "qualified_dependencies_revalidated": True,
            "source_mapping_revalidated": False, "target_resolution_complete": False,
            "qualification": "Original qualified body receipts, factory/source/code-slot and conditional namespace/entry routes checked; no execution, purity, content equality or target-set closure claim."}


def _dependencies(unit, entries, fragments, limit):
    artifacts = unit.get("artifacts", {})
    if "semantic" not in artifacts:
        return {"status": "SEMANTIC_FRAGMENT_UNAVAILABLE", "source_unit_status": unit["status"],
                "language_rules": _rule_plans(unit, entries, fragments, limit)}
    semantic = fragments.read(artifacts["semantic"])
    if semantic.get("schema") != "scar.ir.v2.semantic":
        raise ValueError("unsupported semantic fragment")
    modules = [row for row in semantic["modules"] if row.get("path") == unit["path"]]
    if not modules or any(row.get("fingerprint") != "sha256:" + unit["decoded_sha256"] for row in modules):
        raise ValueError("semantic fragment belongs to another source snapshot")
    roots = {_wire(identity) for entry in entries for identity in entry.get("semantic_definition_ids") or ()}
    atoms = {_wire(entry["source_ref"]["atom_id"]) for entry in entries if entry.get("source_ref")}
    definitions = {_wire(row["id"]): row for row in semantic["definitions"]}
    if not roots:
        roots = {identity for identity, row in definitions.items()
                 if atoms.intersection(_wire(item) for item in row.get("source_atoms", ()))}
    if not roots <= definitions.keys():
        raise ValueError("selected lexical definition is absent from semantic fragment")
    source_ids = {_wire(row["id"]) for row in semantic["source_atoms"]}
    if not atoms <= source_ids:
        raise ValueError("selected source atom is absent from semantic fragment")
    operations = set(roots)
    computational, values, bindings, uses, semantic_gaps = [], [], [], [], []
    if "semantics" in artifacts:
        document = fragments.read(artifacts["semantics"])
        from scar.ir.semantics_v2 import SourceSemanticsGraph
        if document.get("schema") != SourceSemanticsGraph.SCHEMA:
            raise ValueError("unsupported source-semantics fragment")
        snapshots = [row for row in document["sources"] if row["path"] == unit["path"]]
        if not snapshots or any(row["fingerprint"] != "sha256:" + unit["decoded_sha256"] for row in snapshots):
            raise ValueError("source semantics belongs to another source snapshot")
        for row in document["operations"]:
            if _wire(row["scope"]) in roots or _wire(row["operation"]) in roots:
                # Preserve the original operand array order; it is not a set.
                computational.append({key: row.get(key) for key in (
                    "operation", "scope", "block", "position", "opcode", "operands", "result",
                    "source", "binding_use", "attribute", "dispatch", "callee", "import_spec")})
                operations.add(_wire(row["operation"]))
        value_ids = {_wire(value) for row in computational for value in [row["result"]] if value is not None}
        value_ids.update(_wire(use["value"]) for row in computational for use in row["operands"])
        values = [row for row in document["values"] if _wire(row["id"]) in value_ids]
        bindings = [row for row in document["bindings"] if _wire(row["scope"]) in roots
                    or _wire(row["definition"]) in operations]
        uses = [row for row in document["uses"] if _wire(row["scope"]) in roots
                or _wire(row["operation"]) in operations]
        semantic_gaps = document.get("gaps", [])
    slot_ids = {_wire(slot) for identity in operations if identity in definitions
                for role in ("input_slots", "output_slots", "state_slots") for slot in definitions[identity][role]}
    slots = [row for row in semantic["slots"] if _wire(row.get("owner")) in operations
             or _wire(row["slot_id"]) in slot_ids]
    slot_ids.update(_wire(row["slot_id"]) for row in slots)
    endpoints = operations | slot_ids | atoms
    edges = [row for row in semantic["edges"]
             if _wire(row["source"].get("id")) in endpoints or _wire(row["target"].get("id")) in endpoints]
    suites, nodes, control_edges = [], [], []
    control_status = "CONTROL_FRAGMENT_UNAVAILABLE"
    if "control" in artifacts:
        document = fragments.read(artifacts["control"])
        from scar.ir.control_flow_v2 import SourceControlFlowGraph
        if document.get("schema") != SourceControlFlowGraph.SCHEMA:
            raise ValueError("unsupported control-flow fragment")
        graph = document["graph"]
        snapshot = graph["sources"].get(unit["path"])
        if snapshot is None or snapshot["fingerprint"] != "sha256:" + unit["decoded_sha256"]:
            raise ValueError("control flow belongs to another source snapshot")
        suites = [row for row in graph["suites"] if _wire(row["scope"]) in roots
                  or _wire(row.get("owner")) in operations]
        suite_ids = {_wire(row["id"]) for row in suites}
        nodes = [row for row in graph["nodes"] if _wire(row["suite"]) in suite_ids
                 or any(_wire(identity) in operations for identity in row["operations"])]
        node_ids = {_wire(row["id"]) for row in nodes}
        control_edges = [row for row in graph["edges"] if _wire(row["source"]) in node_ids
                         or _wire(row["target"]) in node_ids]
        control_status = "ORIGINAL_CFG_RELATIONS"
    return {"status": "ORIGINAL_STATIC_RELATIONS", "entry_keys": [row["entry_key"] for row in entries],
            "selection": "returned entries only; source-atom fallback may include multiple definition phases",
            "definition_ids": sorted(roots), "source_atom_ids": sorted(atoms),
            "definitions": _page([row for key, row in definitions.items() if key in operations], limit),
            "slots": _page(slots, limit), "semantic_edges": _page(edges, limit),
            "ordered_operations": _page(computational, limit), "values": _page(values, limit),
            "bindings": _page(bindings, limit), "binding_uses": _page(uses, limit),
            "file_semantic_gaps": _page(semantic_gaps, limit), "control_status": control_status,
            "suites": _page(suites, limit), "cfg_nodes": _page(nodes, limit), "cfg_edges": _page(control_edges, limit),
            "canonical": _canonical_dependencies(unit, entries, fragments, limit),
            "language_rules": _rule_plans(unit, entries, fragments, limit),
            "closed_graph_projection": False,
            "qualification": "Original fragment records/IDs only; limits can omit endpoint descriptions. No producer/state reconstruction or execution claim."}


def query_static_program(directory, *, file=None, name=None, kind=None, limit=20, include_dependencies=False):
    """Query saved entries; name matches name/qualname text or an exact original ID.

    File selection accepts an absolute original filename or a component suffix.
    No filters means a manifest summary, without loading lexical fragments.
    Dependencies require exactly one selected file and describe returned entries.
    """
    if type(limit) is not int or limit < 1:
        raise ValueError("limit must be a positive integer")
    if type(include_dependencies) is not bool:
        raise TypeError("include_dependencies must be an explicit bool")
    for label, value in (("file", file), ("name", name), ("kind", kind)):
        if value is not None and (type(value) is not str or not value):
            raise ValueError(label + " must be nonempty text")
    from scar.analysis.static_program import read_static_program
    root = Path(directory).absolute()
    manifest = read_static_program(root, verify=False)
    manifest_bytes = (root / "manifest.json").read_bytes()
    if json.loads(manifest_bytes) != manifest:
        raise ValueError("static manifest changed during query")
    manifest_hash = hashlib.sha256(manifest_bytes).hexdigest()
    units = [unit for unit in manifest["units"] if _file_matches(unit["path"], file)]
    if include_dependencies and len(units) != 1:
        raise ValueError("--dependencies requires exactly one selected source file")
    fragments = _Fragments(root)
    result = {"schema": "scar.static-program-query", "schema_version": 1,
              "model": {"directory": str(root), "manifest_sha256": manifest_hash, "phase": manifest["phase"]},
              "summary": manifest["summary"], "completion": manifest["completion"],
              "selection": {"file": file, "name": name, "kind": kind, "limit": limit},
              "files_matched": len(units), "files": _page([
                  {key: unit.get(key) for key in ("key", "path", "namespace_root", "module_names", "status", "counts", "issues")}
                  for unit in units], limit),
              "entries": [], "target_executed": False, "runtime_evidence_required": False}
    summary_only = all(value is None for value in (file, name, kind)) and not include_dependencies
    selected = []
    count = 0
    unavailable = []
    if not summary_only:
        for unit in units:
            catalog = _catalog(unit, fragments)
            if catalog is None:
                unavailable.append({"file": unit["path"], "status": unit["status"], "reason": "LEXICAL_FRAGMENT_UNAVAILABLE"})
                continue
            symbols = {row["table_path"]: row for row in catalog.get("symbol_tables", [])}
            for entry in catalog["entries"]:
                if _entry_matches(entry, name, kind):
                    count += 1
                    if len(result["entries"]) < limit:
                        result["entries"].append(_entry_view(entry, unit, symbols, limit))
                        selected.append(entry)
        result.update(candidate_count=count, returned_entries=len(result["entries"]), entries_truncated=count>limit,
                      unavailable_lexical=_page(unavailable, limit), mode="ENTRIES")
    else:
        result.update(candidate_count=manifest["summary"].get("lexical_entries"), returned_entries=0,
                      entries_truncated=False, mode="MANIFEST_SUMMARY")
    if include_dependencies:
        result["dependencies"] = _dependencies(units[0], selected, fragments, limit)
        result["dependencies"]["static_calls"] = _call_relations(manifest, units[0], selected, fragments, limit)
    if (root / "manifest.json").read_bytes() != manifest_bytes:
        raise ValueError("static manifest changed during query")
    result["verified_fragments"] = fragments.receipts
    result["qualification"] = "Manifest namespace and selected stored/decoded SHA receipts checked; original static facts projected, not a new graph or semantic replay."
    return result


def main(argv=None):
    parser = argparse.ArgumentParser(description=__doc__, prog="scar static-query")
    parser.add_argument("--model", default="artifacts/current/static")
    parser.add_argument("--file", help="absolute original source path or component suffix")
    parser.add_argument("--name", help="name/qualname substring or exact entry key/semantic definition ID")
    parser.add_argument("--kind", help="case-insensitive exact lexical entry kind")
    parser.add_argument("--limit", type=int, default=20)
    parser.add_argument("--dependencies", action="store_true")
    args = parser.parse_args(argv)
    result = query_static_program(args.model, file=args.file, name=args.name, kind=args.kind,
                                  limit=args.limit, include_dependencies=args.dependencies)
    print(json.dumps(result, ensure_ascii=False, indent=2, allow_nan=False))
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
