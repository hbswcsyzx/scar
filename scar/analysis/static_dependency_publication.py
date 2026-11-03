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


def append_static_source_units(directory, sources, *, provenance, jobs=4,
                               max_bytes=64 * 1024 * 1024, progress=None,
                               expected_manifest_sha256=None):
    """Append explicit source interpretations without replacing old inputs.

    Retained relationship/import/material publications describe their original
    source basis only. No loader, source import or target execution occurs.
    """
    from concurrent.futures import ProcessPoolExecutor
    import json
    import multiprocessing
    import re
    from scar.analysis.static_program import (_artifacts, _json, _lowering_route,
        _read_fragment, _run_file, _write, read_static_program)
    from scar.analysis.static_sources import _read_source
    from scar.analysis.static_body import _stamp
    from scar.analysis.static_calls import input_basis_unit
    from scar.analysis.static_basis_compatibility import (_same, _source_expansion_valid,
        source_units_identity)
    from scar.ir.program.static_sources import StaticSourceFile

    if type(sources) is not tuple or any(type(source) is not StaticSourceFile for source in sources):
        raise TypeError('source append requires an immutable tuple of exact StaticSourceFile records')
    if type(jobs) is not int or not 1 <= jobs <= 32:
        raise ValueError('source append jobs must be in [1,32]')
    if type(max_bytes) is not int or max_bytes < 1:
        raise ValueError('source append byte budget must be positive')
    if type(provenance) is not dict or not provenance or not _same(provenance, provenance):
        raise ValueError('source append requires explicit JSON provenance')
    if expected_manifest_sha256 is not None and (type(expected_manifest_sha256) is not str
            or re.fullmatch(r'[0-9a-f]{64}', expected_manifest_sha256) is None):
        raise ValueError('expected manifest receipt must be a lowercase SHA256')
    if progress is not None and not callable(progress):
        raise TypeError('source append progress must be callable')
    output = Path(directory).absolute()
    manifest = read_static_program(output, verify=False)
    original = (output / 'manifest.json').read_bytes()
    if json.loads(original) != manifest or (expected_manifest_sha256 is not None
            and hashlib.sha256(original).hexdigest() != expected_manifest_sha256):
        raise ValueError('current static manifest changed before source append')
    if not sources:
        return manifest
    old_basis = [input_basis_unit(unit) for unit in manifest['units']]
    ledger = manifest.get('source_expansion')
    if ledger is not None and not _source_expansion_valid(ledger, old_basis):
        raise ValueError('current source expansion ledger is not an exact append-only chain')
    old_keys = {unit['key'] for unit in manifest['units']}
    old_coordinates = {(unit['namespace_root'], unit['path']) for unit in manifest['units']}
    if len(old_keys) != len(manifest['units']) or len(old_coordinates) != len(manifest['units']):
        raise ValueError('source append cannot inherit duplicate original unit identities')
    coordinates = [(source.namespace_root, source.path) for source in sources]
    if len(set(coordinates)) != len(sources) or any(key in old_coordinates for key in coordinates):
        raise ValueError('source append cannot replace or duplicate an original source interpretation')
    if sum(source.size_bytes for source in sources) > max_bytes:
        raise OverflowError('source append byte budget exhausted')
    requested_keys = [hashlib.sha256(_json([source.namespace_root, source.path,
        source.decoded_sha256])).hexdigest()[:24] for source in sources]
    if len(set(requested_keys)) != len(sources) or any(key in old_keys for key in requested_keys):
        raise ValueError('source append would overwrite an original canonical unit key')

    def verify_sources():
        for source in sources:
            source.__post_init__()
            if source.module_names or source.module_mappings:
                raise ValueError('observed source append cannot assert candidate import identities')
            path = Path(source.path)
            if path.resolve() != path or path.is_symlink():
                raise ValueError('source append requires original canonical file paths')
            raw, text, encoding = _read_source(path, min(max_bytes, source.size_bytes))
            if (len(raw) != source.size_bytes or hashlib.sha256(raw).hexdigest() != source.raw_sha256
                    or text != source.text or encoding != source.encoding
                    or hashlib.sha256(text.encode('utf8')).hexdigest() != source.decoded_sha256):
                raise ValueError('source append differs from its exact retained bytes/text/encoding')

    verify_sources()
    temporary = Path(tempfile.mkdtemp(prefix='.static-source-append-', dir=output.parent))
    try:
        shutil.copytree(output, temporary, dirs_exist_ok=True, copy_function=os.link)
        shared = {descriptor['path']: _stamp(temporary / descriptor['path'])
                  for descriptor in _artifacts(manifest)}
        if jobs == 1:
            new_units = []
            for source in sources:
                new_units.append(_run_file(source, str(temporary), 'graph', 10000))
                if progress is not None:
                    progress(len(new_units), len(sources), new_units[-1])
        else:
            with ProcessPoolExecutor(max_workers=jobs,
                    mp_context=multiprocessing.get_context('spawn')) as pool:
                # Preserve the requested unit order regardless of worker completion.
                futures = [pool.submit(_run_file, source, str(temporary), 'graph', 10000)
                           for source in sources]
                new_units = []
                for future in futures:
                    new_units.append(future.result())
                    if progress is not None:
                        progress(len(new_units), len(sources), new_units[-1])
        if len({unit['key'] for unit in new_units}) != len(new_units) or any(
                unit['key'] in old_keys for unit in new_units):
            raise ValueError('source append would overwrite an existing canonical unit key')
        for unit in new_units:
            if 'lexical' not in unit['artifacts']:
                continue
            catalog = _read_fragment(temporary, unit['artifacts']['lexical'])
            for entry in catalog['entries']:
                entry['lowering_route'] = _lowering_route(entry)
            unit['module_initializer_ids'] = [identity for entry in catalog['entries']
                if entry['kind'] == 'MODULE' for identity in entry['semantic_definition_ids'] or ()]
            unit['lexical_completion'] = catalog.get('completion', {})
            unit['lexical_summary'] = catalog['summary']
            unit['artifacts']['lexical'] = _write(temporary, unit['artifacts']['lexical']['path'], catalog)
        step = {'before_count': len(old_basis), 'after_count': len(old_basis) + len(new_units),
            'prior_manifest_sha256': hashlib.sha256(original).hexdigest(),
            'before_identity_sha256': source_units_identity(old_basis),
            'appended_identity_sha256': source_units_identity([input_basis_unit(unit) for unit in new_units]),
            'unit_keys': [unit['key'] for unit in new_units], 'provenance': json.loads(_json(provenance))}
        manifest['units'].extend(new_units)
        manifest['source_expansion'] = {'schema': 'scar.static-source-expansion-ledger',
            'schema_version': 1, 'coverage': 'PRIOR_SOURCE_BASIS_ONLY',
            'steps': [*(ledger['steps'] if ledger is not None else ()), step]}
        manifest['dependency_source_roots'] = list(dict.fromkeys((
            *manifest.get('dependency_source_roots', ()), *(source.namespace_root for source in sources))))
        summary = manifest['summary']
        for unit in new_units:
            for name, number in unit['counts'].items():
                summary[name] = summary.get(name, 0) + number
        summary.update(files=len(manifest['units']), processed_files=len(manifest['units']),
            source_bytes=sum(unit['source_bytes'] for unit in manifest['units']),
            physical_source_files=len({(unit['path'], unit['raw_sha256']) for unit in manifest['units']}),
            statuses=dict(Counter(unit['status'] for unit in manifest['units'])),
            body_statuses=dict(Counter(body['status'] for unit in manifest['units'] for body in unit['bodies'])),
            issues_by_stage=dict(Counter(issue['stage'] for unit in manifest['units'] for issue in unit['issues'])))
        manifest['completion'].update(body_expansion_complete=False, dependency_closure_complete=False,
            whole_program_model_complete=False, language_ledger_complete=False,
            static_rule_ledgers_present=all('rules' in unit['artifacts'] for unit in manifest['units']))
        for name in ('explicit_ast_catalog_complete', 'compiler_symbol_tables_cataloged'):
            if name in manifest['completion']:
                manifest['completion'][name] = all(unit.get('lexical_completion', {}).get(name, False)
                                                   for unit in manifest['units'])
        manifest['storage'] = {'files': len(list(temporary.rglob('*.gz'))),
            'compressed_bytes': sum(path.stat().st_size for path in temporary.rglob('*.gz'))}
        if not _source_expansion_valid(manifest['source_expansion'],
                [input_basis_unit(unit) for unit in manifest['units']]):
            raise ValueError('source append failed its strict prefix/ledger identity check')
        if any(_stamp(temporary / path) != stamp for path, stamp in shared.items()):
            raise ValueError('an original source/body/publication artifact changed during source append')
        (temporary / 'manifest.json').unlink()
        (temporary / 'manifest.json').write_bytes(_json(manifest))
        read_static_program(temporary, verify=False)
        verify_sources()
        read_static_program(output, verify=False)
        if (output / 'manifest.json').read_bytes() != original:
            raise ValueError('current model changed before source append publication')
        previous = Path(tempfile.mkdtemp(prefix='.static-replacing-', dir=output.parent))
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
