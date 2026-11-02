"""Selected external sources become ordinary source frontend/lowerer inputs."""
import copy
import gzip
import hashlib
import json
from pathlib import Path

from scar.analysis.static_dependency_expansion import expand_static_dependency_materials
from scar.analysis.static_program import _read_fragment
from scar.ir.program.discovery import ModuleMapping
from scar.ir.program.providers import ProviderArtifact
from scar.ir.program.source_references import SourceArtifactLocator
from scar.ir.program.static_dependencies import (
    DependencyImportRelation, DependencyLimits, DependencyMaterial, DependencyMaterialKind as Kind,
    DependencyModuleQuery, DependencyRelationCount, DependencySearchStatus as Search,
    DependencyVersionStatus as Version, StaticDependencyInventory,
)


def test_selected_materials_make_normal_units_without_selection_or_execution(tmp_path):
    root = tmp_path / "external"
    (root / "pkg").mkdir(parents=True)
    marker = tmp_path / "executed"
    program = ("from other_dependency import VALUE\nCONST = 7\ndef identity(value):\n    return value\n"
               "from pathlib import Path\nPath(" + repr(str(marker)) + ").touch()\nraise RuntimeError('must not execute')\n")
    contents = (("pkg/provider.py", program, Kind.SOURCE), ("declaration.pyi", "def f(x: int) -> int: ...\n", Kind.STUB),
                ("changed.py", "VALUE = 1\n", Kind.SOURCE), ("native.so", "not an executable", Kind.NATIVE),
                ("later.py", "VALUE = 8\n", Kind.SOURCE))
    materials = []
    for index, (relative, text, kind) in enumerate(contents):
        path = root / relative
        path.write_text(text)
        mappings = ((ModuleMapping("pkg.provider", str(root)), ModuleMapping("provider", str(root / "pkg")))
                    if index == 0 else (ModuleMapping(Path(relative).stem, str(root)),))
        materials.append(DependencyMaterial(str(path), kind, mappings, Version.CONTENT_HASHED,
            artifact=ProviderArtifact(str(path), hashlib.sha256(text.encode()).hexdigest(), len(text.encode()),
                                      "scar.dependency-material-bytes")))
    original = {"schema": "scar.static-import-index", "schema_version": 1,
                "relations": [{"candidate_module": mapping.name, "relation_kind": "IMPORT_TARGET_MODULE"}
                              for material in materials for mapping in material.mappings]}
    raw = json.dumps(original, sort_keys=True, separators=(",", ":")).encode()
    stored = gzip.compress(raw, mtime=0)
    imports = tmp_path / "imports.json.gz"
    imports.write_bytes(stored)
    locator = SourceArtifactLocator(ProviderArtifact(str(imports), hashlib.sha256(stored).hexdigest(), len(stored),
        "scar.static-import-index"), hashlib.sha256(raw).hexdigest(), len(raw), "gzip-canonical-json")
    queries, relations = [], []
    for index, material in enumerate(materials):
        for mapping in material.mappings:
            relations.append(DependencyImportRelation("#/relations/" + str(len(relations)), len(queries)))
            queries.append(DependencyModuleQuery(mapping.name, Search.SEARCHED_EXPLICIT_ROOTS, (index,)))
    inventory = StaticDependencyInventory(locator, (str(root), str(root / "pkg")), (".so",), DependencyLimits(),
        tuple(materials), tuple(queries), tuple(relations),
        (DependencyRelationCount("IMPORT_TARGET_MODULE", "MATERIAL_CANDIDATES", len(relations)),))
    (root / "changed.py").write_text("VALUE = 2\n")
    output = tmp_path / "units-staging"
    result = expand_static_dependency_materials(inventory, out=output, material_indices=(0, 1, 2, 3))
    assert len(result.units) == 3 and result.unselected_materials == (4,)
    assert result.import_index == locator and not (output / "manifest.json").exists()
    providers = [unit for unit in result.units if unit["path"] == materials[0].path]
    assert len(providers) == 2 and len({unit["key"] for unit in providers}) == 2
    assert {unit["namespace_root"] for unit in providers} == {str(root), str(root / "pkg")}
    for unit in providers:
        assert set(("source", "lexical", "semantic", "semantics", "control", "constants")) <= unit["artifacts"].keys()
        assert all(mapping["source_root"] == unit["namespace_root"] for mapping in unit["module_mappings"])
        assert unit["counts"]["ast_nodes"] > 0 and unit["counts"]["control_nodes"] > 0
        assert _read_fragment(output, unit["artifacts"]["source"])["text"] == program
        lexical = _read_fragment(output, unit["artifacts"]["lexical"])
        assert lexical["imports"] and any(entry["kind"] == "FUNCTION" for entry in lexical["entries"])
    stub = next(unit for unit in result.units if unit["path"].endswith(".pyi"))
    assert set(stub["artifacts"]) == {"source", "lexical"}
    assert {item.kind for item in result.frontiers} == {"MATERIAL_VERSION_CHANGED", "NON_SOURCE_MATERIAL"}
    assert all(origin.analyzed_file == materials[origin.material].artifact for origin in result.origins)
    assert all(origin.import_relations for origin in result.origins)
    assert not marker.exists() and result.summary()["dependency_closure_complete"] is False
    receipts = {str(path): hashlib.sha256(path.read_bytes()).hexdigest() for path in output.rglob("*.gz")}
    reused = expand_static_dependency_materials(inventory, out=output, material_indices=(0, 1), existing_units=result.units)
    assert len(reused.units) == 3 and all(origin.reused for origin in reused.origins)
    assert receipts == {str(path): hashlib.sha256(path.read_bytes()).hexdigest() for path in output.rglob("*.gz")}
    source_fragment = output / providers[0]["artifacts"]["source"]["path"]
    source_fragment.write_bytes(b"caller-owned-corrupt-fragment")
    refused = expand_static_dependency_materials(inventory, out=output, material_indices=(0,), existing_units=result.units)
    assert any(item.kind == "EXISTING_UNIT_NOT_EXACT" for item in refused.frontiers)
    assert source_fragment.read_bytes() == b"caller-owned-corrupt-fragment"
    bounded = expand_static_dependency_materials(inventory, out=tmp_path / "bounded", material_indices=(0, 1), max_files=1)
    assert len(bounded.units) == 2 and bounded.read_files == 1
    assert any(item.material == 1 and item.kind == "FILE_BUDGET" for item in bounded.frontiers)
    tiny = expand_static_dependency_materials(inventory, out=tmp_path / "tiny", material_indices=(0,), max_bytes=1)
    assert not tiny.units and any(item.kind == "BYTE_BUDGET" for item in tiny.frontiers)

    # A fresh normal unit reaches the existing canonical lowerer directly;
    # this is more than a new metadata/schema record and executes no target.
    from scar.analysis.static_body import _producer, _run_unit
    unit = copy.deepcopy(bounded.units[0])
    catalog = _read_fragment(Path(bounded.output), unit["artifacts"]["lexical"])
    function = next(entry for entry in catalog["entries"] if entry["qualname"].endswith(".identity"))
    lowered = _run_unit(unit, catalog, (function["entry_key"],), bounded.output, 10000, _producer())
    body = next(row for row in lowered["bodies"] if row["entry_key"] == function["entry_key"])
    assert body["status"] == "LOWERED_WITH_GAPS" and body["artifact"]
    assert not marker.exists()

    # Publish those same normal units into a real source-root model. Rebuilt
    # import indices must not destroy the basis of their original provenance.
    from scar.analysis.static_program import (build_static_program, refine_static_program,
        inventory_static_program, read_static_program)
    from scar.analysis.static_dependencies import read_static_dependencies
    from scar.analysis.static_dependency_publication import expand_static_dependency_program
    seed = tmp_path / "seed"
    seed.mkdir()
    (seed / "app.py").write_text("import pkg.provider\nimport declaration\n")
    model = tmp_path / "published"
    build_static_program(seed, out=model, jobs=1)
    refine_static_program(model)
    inventory_static_program(model, search_roots=(root,), native_suffixes=(".so",))
    before = read_static_program(model)
    old_source = before["units"][0]["artifacts"]["source"]
    after = expand_static_dependency_program(model, jobs=1)
    assert len(after["units"]) == 3 and after["summary"]["files"] == 3
    assert after["units"][0]["artifacts"]["source"] == old_source
    assert after["completion"]["whole_program_model_complete"] is False
    assert after["completion"]["dependency_closure_complete"] is False
    view = read_static_dependencies(model)
    assert view.import_index.artifact.uri == str(model / after["artifacts"]["imports"]["path"])
    report = _read_fragment(model, after["artifacts"][after["dependency_expansion"]["report"]])
    assert len(report["origins"]) == 2 and all(origin["import_relations"] for origin in report["origins"])
    old_import = next(descriptor for key, descriptor in after["artifacts"].items()
                      if key.startswith("dependency-input-imports-"))
    assert _read_fragment(model, old_import)["relations"]
    assert read_static_program(model)["dependency_expansion"]["summary"]["new_units"] == 2
    assert not marker.exists()
