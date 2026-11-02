"""Locate materials named by an existing import index, without importing targets.

The only searches are fixed module-derived paths under caller-supplied roots.
There is no environment walk, importlib resolution, import hook, package/plugin
initialization, setup.py execution, or second definition/value graph.
"""
from __future__ import annotations

from collections import Counter, defaultdict
from dataclasses import replace
import gzip
import hashlib
from importlib.machinery import EXTENSION_SUFFIXES
import json
import os
from pathlib import Path
import stat

from scar.ir.program.discovery import ModuleMapping
from scar.ir.program.providers import ProviderArtifact
from scar.ir.program.source_references import SourceArtifactLocator
from scar.ir.program.static_dependencies import (
    DependencyFrontier, DependencyImportRelation, DependencyLimits, DependencyMaterial,
    DependencyMaterialKind as Kind, DependencyModuleQuery, DependencyRelationCount,
    DependencySearchStatus as Search, DependencyVersionStatus as Version, StaticDependencyInventory,
)
from scar.ir.v2.common import SourceVersion


def _stamp(info):
    return (info.st_dev, info.st_ino, info.st_mode, info.st_size, info.st_mtime_ns, info.st_ctime_ns)


def _symlink(path):
    current = Path(path.anchor)
    for part in path.parts[1:]:
        current /= part
        if current.is_symlink():
            return str(current)
    return None


def _descriptor_locator(root, descriptor, schema):
    relative = Path(descriptor["path"])
    if relative.is_absolute() or ".." in relative.parts:
        raise ValueError("dependency source artifact escapes its model")
    path = root / relative
    return SourceArtifactLocator(
        ProviderArtifact(str(path), descriptor["sha256"], descriptor["bytes"], schema),
        descriptor["decoded_sha256"], descriptor["decoded_bytes"], "gzip-canonical-json")


def _load_inputs(directory):
    root = Path(os.path.abspath(directory))
    if _symlink(root) is not None:
        raise ValueError("static dependency model must not traverse symlinks")
    path = root / "manifest.json"
    if _symlink(path) is not None:
        raise ValueError("static dependency manifest must not traverse symlinks")
    payload = path.read_bytes()
    manifest = json.loads(payload)
    if manifest.get("schema") != "scar.static-program" or manifest.get("schema_version") != 1:
        raise ValueError("unsupported static program manifest")
    descriptor = manifest.get("artifacts", {}).get("imports")
    if descriptor is None:
        raise ValueError("static program has no original import index; refine its lexical/import index first")
    # These immutable fragment receipts survive adding this inventory to the
    # same manifest. An optional declaration receipt to the mutable manifest
    # would become stale (or require a circular self-hash) on publication.
    locator = _descriptor_locator(root, descriptor, "scar.static-import-index")
    import_path = Path(locator.artifact.uri)
    if _symlink(import_path) is not None:
        raise ValueError("import index must not traverse symlinks")
    stored = import_path.read_bytes()
    if len(stored) != locator.artifact.size_bytes or hashlib.sha256(stored).hexdigest() != locator.artifact.sha256:
        raise ValueError("original import index stored receipt differs")
    decoded = gzip.decompress(stored)
    if len(decoded) != locator.decoded_bytes or hashlib.sha256(decoded).hexdigest() != locator.decoded_sha256:
        raise ValueError("original import index decoded receipt differs")
    imports = json.loads(decoded)
    if imports.get("schema") != "scar.static-import-index" or imports.get("schema_version") != 1:
        raise ValueError("unsupported original import index")
    return root, manifest, imports, locator


def _read_receipt(path, before, limit, spent):
    """Hash complete stable bytes; stat alone is never a content identity."""
    if before.st_size > limit:
        raise ValueError("file exceeds available content-read budget")
    spent[0] += 1
    descriptor = os.open(path, os.O_RDONLY | getattr(os, "O_CLOEXEC", 0) | getattr(os, "O_NOFOLLOW", 0))
    try:
        if _stamp(os.fstat(descriptor)) != _stamp(before):
            raise OSError("material changed between path check and open")
        digest, read = hashlib.sha256(), 0
        while read < before.st_size:
            chunk = os.read(descriptor, min(1024 * 1024, before.st_size - read))
            if not chunk:
                break
            read += len(chunk)
            spent[1] += len(chunk)
            digest.update(chunk)
        if (read != before.st_size or _stamp(os.fstat(descriptor)) != _stamp(before)
                or _stamp(path.lstat()) != _stamp(before) or _symlink(path) is not None):
            raise OSError("material changed while its version was read")
        return digest.hexdigest(), read
    finally:
        os.close(descriptor)


def read_static_dependencies(directory):
    """Read the published view against its original current import endpoints.

    External receipts describe bytes inventoried earlier; this reader does not
    import those files or assert that they are still their recorded version.
    Source ingestion must check that version again before using new bytes.
    """
    from dataclasses import fields
    from scar.analysis.static_program import _read_fragment
    from scar.ir.record_codec import decode

    root, manifest, imports, locator = _load_inputs(directory)
    descriptor = manifest.get("artifacts", {}).get("dependencies")
    if descriptor is None:
        raise ValueError("static program has no published dependency inventory")
    relative = Path(descriptor["path"])
    if relative.is_absolute() or ".." in relative.parts or _symlink(root / relative) is not None:
        raise ValueError("dependency inventory escapes its model or traverses symlinks")
    document = _read_fragment(root, descriptor)
    if (document.get("schema") != StaticDependencyInventory.SCHEMA
            or document.get("schema_version") != StaticDependencyInventory.SCHEMA_VERSION):
        raise ValueError("unsupported dependency inventory")
    names = {field.name for field in fields(StaticDependencyInventory)}
    if set(document) != names | {"schema", "schema_version", "summary", "qualification"}:
        raise ValueError("dependency inventory has unexpected or missing fields")
    result = decode(StaticDependencyInventory, {key: document[key] for key in names})
    if result.import_index != locator:
        raise ValueError("dependency inventory refers to a different original import index")
    if document["summary"] != result.summary() or document["qualification"] != result.to_dict()["qualification"]:
        raise ValueError("dependency inventory summary or qualification differs")
    if len(result.relations) != len(imports["relations"]):
        raise ValueError("dependency inventory does not cover the original import relations")
    for origin, relation in zip(imports["relations"], result.relations):
        module = origin.get("candidate_module")
        if relation.module_query is None:
            if module:
                raise ValueError("dependency inventory omitted an original module query")
        elif result.module_queries[relation.module_query].module != module:
            raise ValueError("dependency module query differs from the original relation")
    units = {unit["key"]: unit for unit in manifest["units"]}
    for material in result.materials:
        if material.supplied_unit is None:
            continue
        unit = units.get(material.supplied_unit)
        if (unit is None or unit["path"] != material.path
                or material.supplied_source != _descriptor_locator(root, unit["artifacts"]["source"], "scar.static-source-text")
                or material.supplied_version != SourceVersion(unit["path"], "sha256:" + unit["decoded_sha256"])):
            raise ValueError("dependency supplied snapshot differs from its current original unit")
    return result


def inventory_static_dependencies(directory, *, search_roots, max_modules=4096, max_files=4096,
                                  max_bytes=64 * 1024 * 1024, max_file_bytes=8 * 1024 * 1024,
                                  native_suffixes=None):
    """Return a typed, read-only material view of the original import relations.

    ``search_roots`` are explicit import-root *candidates*, not a claim about a
    target process's sys.path. ``native_suffixes`` defaults to this analyzer's
    public interpreter suffix metadata; cross-environment clients must supply
    their target profile. Dotted names probe only their component-derived file
    names; ``pkg-stubs`` is a declaration candidate, never a runtime package.

    The module budget bounds filesystem queries. File/byte budgets bound only
    attempted external file reads (including failed reads), with source/stub
    files prioritized over native binaries. Supplied snapshots retain original receipts and are not
    reread from the application's source tree. Missing paths are scoped to
    these roots and patterns; from-export/submodule ambiguity remains in the
    original relation records and is never resolved by file presence alone.
    """
    limits = DependencyLimits(max_modules, max_files, max_bytes, max_file_bytes)
    if isinstance(search_roots, (str, bytes, Path)):
        raise TypeError("search_roots must be an iterable of explicit root paths")
    roots = tuple(dict.fromkeys(str(Path(os.path.abspath(x))) for x in search_roots))
    suffixes = tuple(dict.fromkeys(EXTENSION_SUFFIXES if native_suffixes is None else native_suffixes))
    if not suffixes or any(type(x) is not str or not x.startswith(".") or "/" in x for x in suffixes):
        raise ValueError("native suffixes must be nonempty explicit filename suffixes")
    root, manifest, imports, locator = _load_inputs(directory)
    roots_frontiers, valid_roots = [], []
    for supplied_root in roots:
        path = Path(supplied_root)
        try:
            link = _symlink(path)
            if link is not None:
                roots_frontiers.append(DependencyFrontier("SEARCH_ROOT_SYMLINK", supplied_root, "Not followed: " + link))
            elif not stat.S_ISDIR(path.lstat().st_mode):
                roots_frontiers.append(DependencyFrontier("SEARCH_ROOT_NOT_DIRECTORY", supplied_root, "No directory available."))
            else:
                valid_roots.append(path)
        except OSError as error:
            roots_frontiers.append(DependencyFrontier("SEARCH_ROOT_UNAVAILABLE", supplied_root, str(error)))

    material_rows, material_keys, mappings, supplied = [], {}, defaultdict(set), defaultdict(set)

    def add_material(material):
        key = (material.path, material.kind, material.supplied_unit)
        if key not in material_keys:
            material_keys[key] = len(material_rows)
            material_rows.append(material)
        number = material_keys[key]
        mappings[number].update(material.mappings)
        return number

    for unit in manifest["units"]:
        pairs = tuple(ModuleMapping(x["name"], x["source_root"]) for x in unit.get("module_mappings", ()))
        if not pairs:
            pairs = tuple(ModuleMapping(x, unit["namespace_root"]) for x in unit.get("module_names", ()))
        descriptor = unit.get("artifacts", {}).get("source")
        if not pairs or descriptor is None:
            continue
        material = DependencyMaterial(unit["path"], Kind.STUB if unit["path"].endswith(".pyi") else Kind.SOURCE,
            tuple(sorted(set(pairs), key=lambda x: (x.source_root, x.name))), Version.SUPPLIED_SNAPSHOT,
            supplied_unit=unit["key"],
            supplied_source=_descriptor_locator(root, descriptor, "scar.static-source-text"),
            supplied_version=SourceVersion(unit["path"], "sha256:" + unit["decoded_sha256"]),
            version_detail="Original supplied snapshot; current application source file was not reread or imported.")
        index = add_material(material)
        for mapping in pairs:
            supplied[mapping.name].add(index)

    # Retain only referenced supplied materials in the published view; do not
    # confuse every file in an analysis scope with an actually used import.
    names = sorted({x["candidate_module"] for x in imports["relations"] if type(x.get("candidate_module")) is str
                    and x["candidate_module"]})
    queries, query_by_name, searched = [], {}, 0
    for name in names:
        indices, frontiers = set(supplied.get(name, ())), []
        if not all(x.isidentifier() for x in name.split(".")):
            status = Search.INVALID_MODULE_NAME
        elif searched >= limits.max_modules:
            status = Search.MODULE_BUDGET
            frontiers.append(DependencyFrontier("MODULE_SEARCH_BUDGET", None, "No filesystem query for this module was performed."))
        else:
            status = Search.SEARCHED_EXPLICIT_ROOTS
            searched += 1
            parts = name.split(".")
            for search_root in valid_roots:
                stem = search_root.joinpath(*parts)
                candidates = [(Path(str(stem) + ".py"), Kind.SOURCE),
                              (stem / "__init__.py", Kind.SOURCE),
                              (Path(str(stem) + ".pyi"), Kind.STUB), (stem / "__init__.pyi", Kind.STUB)]
                for suffix in suffixes:
                    candidates.extend(((Path(str(stem) + suffix), Kind.NATIVE), (stem / ("__init__" + suffix), Kind.NATIVE)))
                stub_stem = search_root.joinpath(parts[0] + "-stubs", *parts[1:])
                if len(parts) == 1:
                    candidates.append((stub_stem / "__init__.pyi", Kind.STUB))
                else:
                    candidates.extend(((Path(str(stub_stem) + ".pyi"), Kind.STUB), (stub_stem / "__init__.pyi", Kind.STUB)))
                # A .pyi initializer is a declaration and does not turn a
                # directory into an executable regular Python package.
                runtime_initializer_found = False
                for path, kind in candidates:
                    try:
                        link = _symlink(path)
                        if link is not None:
                            frontiers.append(DependencyFrontier("MATERIAL_SYMLINK_NOT_FOLLOWED", str(path), "Not followed: " + link))
                            continue
                        info = path.lstat()
                    except FileNotFoundError:
                        continue
                    except OSError as error:
                        frontiers.append(DependencyFrontier("MATERIAL_PATH_UNAVAILABLE", str(path), str(error)))
                        continue
                    if not stat.S_ISREG(info.st_mode):
                        frontiers.append(DependencyFrontier("MATERIAL_NOT_REGULAR_FILE", str(path), "Candidate is not a regular file."))
                        continue
                    if path.parent == stem and kind in (Kind.SOURCE, Kind.NATIVE):
                        runtime_initializer_found = True
                    # A supplied snapshot already covers this exact mapping;
                    # avoid inventing a second file identity for its disk path.
                    matched = [i for i in indices if material_rows[i].path == str(path)
                               and material_rows[i].supplied_unit is not None
                               and ModuleMapping(name, str(search_root)) in material_rows[i].mappings]
                    if matched:
                        continue
                    index = add_material(DependencyMaterial(str(path), kind, (ModuleMapping(name, str(search_root)),),
                        Version.CONTENT_NOT_READ, stat_stamp=_stamp(info), version_detail="Content version not read yet."))
                    indices.add(index)
                try:
                    if _symlink(stem) is None and stat.S_ISDIR(stem.lstat().st_mode) and not runtime_initializer_found:
                        indices.add(add_material(DependencyMaterial(str(stem), Kind.NAMESPACE_DIRECTORY,
                            (ModuleMapping(name, str(search_root)),), Version.DIRECTORY_ONLY,
                            stat_stamp=_stamp(stem.lstat()), version_detail="Namespace directory candidate, not a file/content identity.")))
                except FileNotFoundError:
                    pass
                except OSError as error:
                    frontiers.append(DependencyFrontier("NAMESPACE_PATH_UNAVAILABLE", str(stem), str(error)))
        query_by_name[name] = len(queries)
        queries.append(DependencyModuleQuery(name, status, tuple(sorted(indices)), tuple(frontiers)))

    used = sorted({i for query in queries for i in query.materials})
    old_to_new = {old: new for new, old in enumerate(used)}
    material_rows = [replace(material_rows[i], mappings=tuple(sorted(mappings[i], key=lambda x: (x.source_root, x.name)))) for i in used]
    queries = [replace(x, materials=tuple(sorted(old_to_new[i] for i in x.materials))) for x in queries]

    read_files, spent = 0, [0, 0]
    order = sorted(range(len(material_rows)), key=lambda i: (material_rows[i].kind is Kind.NATIVE, material_rows[i].path))
    for index in order:
        material = material_rows[index]
        if material.version_status is not Version.CONTENT_NOT_READ:
            continue
        required = material.stat_stamp[3]
        available = min(limits.max_file_bytes, limits.max_bytes - spent[1])
        if spent[0] >= limits.max_files or required > available:
            material_rows[index] = replace(material, version_detail="Content version not read: file/count/byte budget. Stat is not a content identity.")
            continue
        try:
            path = Path(material.path)
            if _symlink(path) is not None:
                raise OSError("material path now traverses a symbolic link")
            before = path.lstat()
            if not stat.S_ISREG(before.st_mode) or _stamp(before) != material.stat_stamp:
                raise OSError("material changed since candidate discovery")
            digest, count = _read_receipt(path, before, available, spent)
            material_rows[index] = replace(material, version_status=Version.CONTENT_HASHED,
                artifact=ProviderArtifact(material.path, digest, count, "scar.dependency-material-bytes"),
                version_detail="Complete stable file bytes hashed; file was not imported, parsed or executed.")
            read_files += 1
        except (OSError, ValueError) as error:
            material_rows[index] = replace(material, version_status=Version.READ_FAILED,
                                           version_detail=type(error).__name__ + ": " + str(error))

    relation_rows, counts = [], Counter()
    for number, relation in enumerate(imports["relations"]):
        query_index = query_by_name.get(relation.get("candidate_module"))
        relation_rows.append(DependencyImportRelation("#/relations/" + str(number), query_index,
            relation.get("status", "ORIGINAL_MODULE_UNRESOLVED") if query_index is None else None))
        if query_index is None:
            availability = "ORIGINAL_MODULE_UNRESOLVED"
        else:
            query = queries[query_index]
            if query.materials:
                availability = "MATERIAL_CANDIDATES"
            elif query.status is not Search.SEARCHED_EXPLICIT_ROOTS:
                availability = query.status.value
            elif query.frontiers or roots_frontiers:
                availability = "SEARCH_FRONTIER"
            else:
                availability = "NOT_LOCATED_IN_EXPLICIT_ROOTS"
        counts[(relation["relation_kind"], availability)] += 1
    return StaticDependencyInventory(locator, roots, suffixes, limits, tuple(material_rows), tuple(queries),
        tuple(relation_rows), tuple(DependencyRelationCount(kind, availability, count)
            for (kind, availability), count in sorted(counts.items())), tuple(roots_frontiers), read_files, spent[1], spent[0])
