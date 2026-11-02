"""Publish import-driven source expansion into the one canonical static model."""
from __future__ import annotations

from collections import Counter
from dataclasses import replace
import hashlib
import os
from pathlib import Path
import shutil
import tempfile
import time


def expand_static_dependency_program(directory, *, material_indices=None, max_files=4096,
                                     max_bytes=64 * 1024 * 1024, jobs=4, progress=None):
    """Analyze available source candidates, retaining their conditional origins.

    A round consumes the current material inventory and refreshes import and
    material indices. Newly discovered materials remain explicit next-round
    inputs. No runtime import choice or complete dependency closure is claimed.
    """
    from scar.analysis.static_program import (_discard_static_calls,
        _discard_static_dependencies, _json, _lowering_route, _read_fragment, _write,
        read_static_program)
    from scar.analysis.static_dependencies import inventory_static_dependencies, read_static_dependencies
    from scar.analysis.static_dependency_expansion import expand_static_dependency_materials
    from scar.analysis.static_imports import build_import_index
    from scar.analysis.static_body import _stamp
    from scar.ir.record_codec import encode
    from scar.ir.program.providers import ProviderArtifact
    from scar.ir.program.source_references import SourceArtifactLocator

    output = Path(directory).absolute()
    manifest = read_static_program(output, verify=False)
    original = (output / "manifest.json").read_bytes()
    inventory = read_static_dependencies(output)
    if (output / "manifest.json").read_bytes() != original:
        raise ValueError("current model changed while reading dependency inputs")
    started = time.monotonic()
    temporary = Path(tempfile.mkdtemp(prefix=".static-dependency-expansion-", dir=output.parent))
    try:
        shutil.copytree(output, temporary, dirs_exist_ok=True, copy_function=os.link)
        _discard_static_calls(temporary, manifest)
        # Preserve only the actual proof inputs. They are content addressed,
        # owned current-model fragments, not old checkouts or old manifests.
        prior_import = manifest["artifacts"]["imports"]
        import_basis_path = "indexes/dependency-inputs/imports-" + prior_import["sha256"] + ".json.gz"
        import_basis = {**prior_import, "path": import_basis_path}
        destination = temporary / import_basis_path
        destination.parent.mkdir(parents=True, exist_ok=True)
        if not destination.exists():
            os.link(temporary / prior_import["path"], destination)
        _read_fragment(temporary, import_basis)
        manifest["artifacts"]["dependency-input-imports-" + prior_import["sha256"]] = import_basis
        input_inventory = replace(inventory, import_index=replace(inventory.import_index,
            artifact=replace(inventory.import_index.artifact, uri=str(output / import_basis_path))))
        basis_document = input_inventory.to_dict()
        basis_key = hashlib.sha256(_json(basis_document)).hexdigest()
        inventory_basis_path = "indexes/dependency-inputs/materials-" + basis_key + ".json.gz"
        inventory_basis = _write(temporary, inventory_basis_path, basis_document)
        manifest["artifacts"]["dependency-input-materials-" + basis_key] = inventory_basis
        shared = {descriptor["path"]: _stamp(temporary / descriptor["path"])
            for unit in manifest["units"]
            for descriptor in (*unit["artifacts"].values(),
                *(body["artifact"] for body in unit["bodies"] if "artifact" in body))}
        expansion = expand_static_dependency_materials(input_inventory, out=temporary,
            material_indices=material_indices, max_files=max_files, max_bytes=max_bytes,
            jobs=jobs, existing_units=manifest["units"], progress=progress)
        old_keys = {unit["key"] for unit in manifest["units"]}
        new_units = [unit for unit in expansion.units if unit["key"] not in old_keys]
        # Existing units and their canonical bodies retain all original IDs.
        # A new namespace interpretation enters the same normal unit schema.
        for unit in new_units:
            if "lexical" not in unit["artifacts"]:
                continue
            catalog = _read_fragment(temporary, unit["artifacts"]["lexical"])
            for entry in catalog["entries"]:
                entry["lowering_route"] = _lowering_route(entry)
            unit["module_initializer_ids"] = [identity for entry in catalog["entries"]
                if entry["kind"] == "MODULE" for identity in entry["semantic_definition_ids"] or ()]
            unit["lexical_completion"] = catalog.get("completion", {})
            unit["lexical_summary"] = catalog["summary"]
            unit["artifacts"]["lexical"] = _write(temporary, unit["artifacts"]["lexical"]["path"], catalog)
        manifest["units"].extend(new_units)
        manifest["dependency_source_roots"] = list(dict.fromkeys((
            *manifest.get("dependency_source_roots", ()), *(unit["namespace_root"] for unit in new_units))))
        summary = manifest["summary"]
        for unit in new_units:
            for key, number in unit["counts"].items():
                summary[key] = summary.get(key, 0) + number
        summary.update(files=len(manifest["units"]), processed_files=len(manifest["units"]),
            source_bytes=sum(unit["source_bytes"] for unit in manifest["units"]),
            physical_source_files=len({(unit["path"], unit["raw_sha256"]) for unit in manifest["units"]}),
            statuses=dict(Counter(unit["status"] for unit in manifest["units"])),
            body_statuses=dict(Counter(body["status"] for unit in manifest["units"] for body in unit["bodies"])),
            issues_by_stage=dict(Counter(issue["stage"] for unit in manifest["units"] for issue in unit["issues"])))
        syntax, kinds, scopes, routes = Counter(), Counter(), Counter(), Counter()
        def lexical(unit):
            if "lexical" not in unit["artifacts"]:
                return {"imports": []}
            catalog = _read_fragment(temporary, unit["artifacts"]["lexical"])
            syntax.update(catalog["syntax"])
            kinds.update(entry["kind"] for entry in catalog["entries"])
            scopes.update(table["kind"] for table in catalog["symbol_tables"])
            routes.update(entry.get("lowering_route", _lowering_route(entry))["status"] for entry in catalog["entries"])
            return catalog
        imports = build_import_index(manifest["units"], lexical)
        _discard_static_dependencies(temporary, manifest)
        manifest["artifacts"]["imports"] = _write(temporary, "indexes/imports.json.gz", imports)
        ledger = {"schema": "scar.static-language-inventory", "schema_version": 1,
            "syntax_occurrences": dict(sorted(syntax.items())), "entry_kinds": dict(kinds),
            "compiler_scope_kinds": dict(scopes), "entry_routes": dict(routes), "language_rules_complete": False,
            "qualification": "Source inventory and entry routes, including conditional dependency candidates; canonical rules remain open."}
        manifest["artifacts"]["language"] = _write(temporary, "indexes/language.json.gz", ledger)
        input_locator = SourceArtifactLocator(ProviderArtifact(str(output / inventory_basis_path),
            inventory_basis["sha256"], inventory_basis["bytes"], input_inventory.SCHEMA),
            inventory_basis["decoded_sha256"], inventory_basis["decoded_bytes"], "gzip-canonical-json")
        report = {"schema": "scar.static-dependency-expansion-index", "schema_version": 1,
            "input_inventory": encode(input_locator), "import_index": encode(input_inventory.import_index),
            "selected_materials": list(expansion.selected_materials), "unit_keys": [unit["key"] for unit in expansion.units],
            "origins": encode(expansion.origins), "frontiers": encode(expansion.frontiers),
            "summary": {**expansion.summary(), "new_units": len(new_units)},
            "qualification": "Original material/import pointers refer to the immutable input basis; units are conditional source interpretations, not selected runtime implementations."}
        report_key = hashlib.sha256(_json(report)).hexdigest()
        manifest["artifacts"]["dependency-expansion-" + report_key] = _write(temporary,
            "indexes/dependency-expansions/" + report_key + ".json.gz", report)
        manifest["dependency_expansion"] = {"analyzer_seconds": time.monotonic() - started,
            "summary": report["summary"], "report": "dependency-expansion-" + report_key}
        for property in ("explicit_ast_catalog_complete", "compiler_symbol_tables_cataloged"):
            manifest["completion"][property] = all(unit.get("lexical_completion", {}).get(property, False)
                                                   for unit in manifest["units"])
        manifest["completion"].update(body_expansion_complete=False, dependency_closure_complete=False,
            whole_program_model_complete=False, language_ledger_complete=False, implicit_scope_semantics_complete=False)
        manifest["catalog_refinement"] = {"updated_stage": "dependency-source-expansion+imports",
            "source_graphs_rebuilt": 0, "new_source_units": len(new_units), "entry_routes": dict(routes),
            "compiler_scope_kinds": dict(scopes), "import_summary": imports["summary"]}
        # Refresh candidate materials against the enlarged source scope. Only
        # URI roots change on publication; exact stored/decoded receipts do not.
        (temporary / "manifest.json").unlink()
        (temporary / "manifest.json").write_bytes(_json(manifest))
        next_inventory = inventory_static_dependencies(temporary, search_roots=inventory.search_roots,
            max_modules=inventory.limits.max_modules, max_files=inventory.limits.max_files,
            max_bytes=inventory.limits.max_bytes, max_file_bytes=inventory.limits.max_file_bytes,
            native_suffixes=inventory.native_suffixes)
        def relocate(locator):
            return replace(locator, artifact=replace(locator.artifact,
                uri=str(output / Path(locator.artifact.uri).relative_to(temporary))))
        next_inventory = replace(next_inventory, import_index=relocate(next_inventory.import_index),
            materials=tuple(replace(material, supplied_source=relocate(material.supplied_source))
                if material.supplied_source is not None else material for material in next_inventory.materials))
        manifest["artifacts"]["dependencies"] = _write(temporary, "indexes/dependencies.json.gz", next_inventory.to_dict())
        manifest["dependency_inventory"] = {"summary": next_inventory.summary(),
            "search_roots": list(next_inventory.search_roots)}
        manifest["completion"]["dependency_inventory_present"] = True
        manifest["storage"] = {"files": len(list(temporary.rglob("*.gz"))),
            "compressed_bytes": sum(path.stat().st_size for path in temporary.rglob("*.gz"))}
        if any(_stamp(temporary / path) != stamp for path, stamp in shared.items()):
            raise ValueError("an original source/body fragment changed during dependency expansion")
        (temporary / "manifest.json").write_bytes(_json(manifest))
        read_static_program(temporary, verify=False)
        read_static_program(output, verify=False)
        if (output / "manifest.json").read_bytes() != original:
            raise ValueError("current model changed before dependency source publication")
        previous = Path(tempfile.mkdtemp(prefix=".static-replacing-", dir=output.parent))
        previous.rmdir()
        output.rename(previous)
        try:
            temporary.rename(output)
        except BaseException:
            previous.rename(output)
            raise
        shutil.rmtree(previous)
        return manifest
    except BaseException:
        shutil.rmtree(temporary, ignore_errors=True)
        raise
