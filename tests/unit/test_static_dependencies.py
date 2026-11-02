"""An import-derived material inventory preserves uncertainty without execution."""
import ast
import gzip
import hashlib
import json
from pathlib import Path
import sys

from scar.analysis.static_dependencies import inventory_static_dependencies
from scar.analysis.static_imports import build_import_index
from scar.analysis.static_lexical import inspect_lexical
from scar.ir.program.static_dependencies import (
    DependencyMaterialKind as Kind, DependencySearchStatus as Search,
    DependencyVersionStatus as Version, StaticDependencyInventory,
)
from scar.ir.record_codec import decode, encode


def test_original_import_materials_are_conditional_versioned_and_never_imported(tmp_path):
    first, second, model = (tmp_path / name for name in ("first", "second", "model"))
    for path in (first, second, model):
        path.mkdir()

    def write(root, relative, text):
        path = root / relative
        path.parent.mkdir(parents=True, exist_ok=True)
        path.write_text(text)
        return path

    def fragment(relative, value):
        raw = json.dumps(value, sort_keys=True, separators=(",", ":")).encode()
        stored = gzip.compress(raw, mtime=0)
        path = model / relative
        path.parent.mkdir(parents=True, exist_ok=True)
        path.write_bytes(stored)
        return {"path": relative, "sha256": hashlib.sha256(stored).hexdigest(), "bytes": len(stored),
                "decoded_sha256": hashlib.sha256(raw).hexdigest(), "decoded_bytes": len(raw)}

    text = ("import scar_test_unexecuted_trap as alias\nfrom . import relative\n"
            "from provider import symbol\nimport ns.child\nimport declared\nimport native\nimport absent\nimport boom\n")
    app = write(first, "pkg/main.py", text)
    relative = write(first, "pkg/relative.py", "VALUE = 1\n")
    marker = tmp_path / "TARGET_EXECUTED"
    trap = "from pathlib import Path\nPath(" + repr(str(marker)) + ").touch()\nraise RuntimeError('never import')\n"
    write(first, "scar_test_unexecuted_trap.py", trap)
    write(second, "scar_test_unexecuted_trap.py", trap)
    write(first, "provider/__init__.py", "symbol = 3\n")
    write(first, "provider/symbol.pyi", "x: int\n")
    write(first, "ns/child.py", "VALUE = 2\n")
    write(first, "declared-stubs/__init__.pyi", "x: int\n")
    write(first, "native.so", "not-an-executable-extension")
    outside = write(tmp_path, "outside.py", trap)
    (first / "boom.py").symlink_to(outside)

    units, catalogs = [], {}
    for number, (path, module) in enumerate(((app, "pkg.main"), (relative, "pkg.relative"))):
        content = path.read_text()
        digest = hashlib.sha256(content.encode()).hexdigest()
        unit = {"key": "unit-" + str(number), "path": str(path), "namespace_root": str(first),
                "module_names": [module], "module_mappings": [{"name": module, "source_root": str(first)}],
                "decoded_sha256": digest, "artifacts": {}, "bodies": []}
        catalogs[unit["key"]] = inspect_lexical(ast.parse(content, filename=str(path)), path=str(path),
            namespace_root=str(first), fingerprint="sha256:" + digest, source_text=content)
        unit["artifacts"]["source"] = fragment("units/" + unit["key"] + "/source.json.gz",
            {"schema": "scar.static-source-text", "text": content, "decoded_sha256": digest})
        units.append(unit)
    original = build_import_index(units, lambda unit: catalogs[unit["key"]])
    descriptor = fragment("indexes/imports.json.gz", original)
    (model / "manifest.json").write_text(json.dumps({"schema": "scar.static-program", "schema_version": 1,
        "units": units, "artifacts": {"imports": descriptor}}))
    inventory = inventory_static_dependencies(model, search_roots=(first, second), native_suffixes=(".so",))
    assert inventory.import_index.artifact.sha256 == descriptor["sha256"]
    assert inventory.import_index.decoded_sha256 == descriptor["decoded_sha256"]
    assert inventory.import_index.declaration is None  # No receipt cycle through its publishing manifest.
    assert len(inventory.relations) == len(original["relations"])
    queries = {row.module: row for row in inventory.module_queries}
    materials = inventory.materials
    assert sum(materials[i].kind is Kind.SOURCE for i in queries["scar_test_unexecuted_trap"].materials) == 2
    assert any(materials[i].supplied_unit == "unit-1" and materials[i].version_status is Version.SUPPLIED_SNAPSHOT
               for i in queries["pkg.relative"].materials)
    assert any(materials[i].kind is Kind.SOURCE for i in queries["provider"].materials)
    assert any(materials[i].kind is Kind.STUB for i in queries["provider.symbol"].materials)
    assert any(materials[i].kind is Kind.NAMESPACE_DIRECTORY for i in queries["ns"].materials)
    assert all(materials[i].kind is Kind.STUB for i in queries["declared"].materials)
    assert any(materials[i].kind is Kind.NATIVE for i in queries["native"].materials)
    assert not queries["absent"].materials and not queries["absent"].frontiers
    assert any(row.kind == "MATERIAL_SYMLINK_NOT_FOLLOWED" for row in queries["boom"].frontiers)
    assert not queries["boom"].materials
    for index, relation in enumerate(inventory.relations):
        assert relation.origin == "#/relations/" + str(index)
        if original["relations"][index].get("candidate_module"):
            assert inventory.module_queries[relation.module_query].module == original["relations"][index]["candidate_module"]
    assert any(original["relations"][i]["relation_kind"] == "FROM_EXPORT_ATTRIBUTE"
               and original["relations"][i].get("name") == "symbol" for i in range(len(inventory.relations)))
    assert decode(StaticDependencyInventory, encode(inventory)) == inventory
    assert not marker.exists() and "scar_test_unexecuted_trap" not in sys.modules
    assert inventory.summary()["external_source_analyzed"] is False
    limited = inventory_static_dependencies(model, search_roots=(first,), native_suffixes=(".so",),
        max_modules=1, max_file_bytes=1)
    assert any(row.status is Search.MODULE_BUDGET for row in limited.module_queries)
    assert sum(row.status is Search.SEARCHED_EXPLICIT_ROOTS for row in limited.module_queries) == 1
    # Query and content-version budgets are distinct; native files stay
    # locatable when their full binary bytes have deliberately not been read.
    tiny = inventory_static_dependencies(model, search_roots=(first,), native_suffixes=(".so",), max_file_bytes=1)
    native = next(row for row in tiny.materials if row.kind is Kind.NATIVE)
    assert native.artifact is None and native.stat_stamp and native.version_status is Version.CONTENT_NOT_READ
    assert not marker.exists()
    # Publish through the normal owned model and read back from original
    # import/source endpoints, without changing any original fragment.
    from scar.analysis.static_program import inventory_static_program, read_static_program
    from scar.analysis.static_dependencies import read_static_dependencies
    before = {path.relative_to(model): path.read_bytes() for path in model.rglob("*.gz")}
    published = inventory_static_program(model, search_roots=(first, second), native_suffixes=(".so",))
    assert published["completion"]["dependency_inventory_present"] is True
    assert published["completion"]["dependency_closure_complete"] is False
    assert published["completion"]["whole_program_model_complete"] is False
    assert read_static_dependencies(model) == inventory
    assert read_static_program(model)["artifacts"]["imports"] == descriptor
    assert all((model / path).read_bytes() == data for path, data in before.items())
    assert not marker.exists() and not tuple(tmp_path.glob(".static-dependencies-*"))
