"""Build a source-only index of import candidates across static source units.

This module reads lexical catalogs supplied by its caller. It does not import
modules, create definitions, assert that a candidate was loaded, or decide
whether module initialization is pure.
"""
from __future__ import annotations

from collections import Counter, defaultdict
from pathlib import Path


_INIT_FILES = frozenset(("__init__.py", "__init__.pyi"))


def _valid_module_name(value):
    return (type(value) is str and bool(value)
            and all(part.isidentifier() for part in value.split(".")))


def _unit_mappings(unit, issues):
    path = unit.get("path")
    root = unit.get("namespace_root")
    if type(path) is not str or not Path(path).is_absolute():
        issues.append({"kind": "INVALID_UNIT_PATH", "unit_key": unit.get("key"),
                       "path": path, "detail": "Unit path must be absolute."})
        return ()
    if type(root) is not str or not Path(root).is_absolute():
        issues.append({"kind": "INVALID_NAMESPACE_ROOT", "unit_key": unit.get("key"),
                       "path": path, "detail": "Unit namespace_root must be absolute."})
        return ()
    rows = unit.get("module_mappings")
    mappings = []
    if type(rows) is list:
        for index, row in enumerate(rows):
            if type(row) is not dict or type(row.get("name")) is not str or type(row.get("source_root")) is not str:
                issues.append({"kind": "INVALID_MODULE_MAPPING", "unit_key": unit.get("key"),
                               "mapping_index": index, "detail": "Expected {name, source_root}."})
                continue
            name, source_root = row["name"], row["source_root"]
            if not Path(source_root).is_absolute():
                issues.append({"kind": "INVALID_MODULE_MAPPING", "unit_key": unit.get("key"),
                               "mapping_index": index, "detail": "Mapping root is not absolute."})
                continue
            if not _valid_module_name(name):
                issues.append({"kind": "SOURCE_NAME_NOT_IMPORTABLE_BY_SYNTAX", "unit_key": unit.get("key"),
                               "mapping_index": index, "module_name": name,
                               "detail": "Source remains cataloged; this physical layout is not a dotted import statement name."})
                continue
            mappings.append((name, source_root))
    if not mappings:
        names = unit.get("module_names", [])
        if type(names) is list and type(root) is str:
            for index, name in enumerate(names):
                if _valid_module_name(name):
                    mappings.append((name, root))
                else:
                    issues.append({"kind": "SOURCE_NAME_NOT_IMPORTABLE_BY_SYNTAX", "unit_key": unit.get("key"),
                                   "module_index": index,
                                   "detail": "Unit module_names entry is not a dotted identifier."})
    return tuple(sorted(set(mappings)))


def _candidate_kind(unit):
    name = Path(unit["path"]).name
    if name == "__init__.py":
        return "PACKAGE_INITIALIZER"
    if name == "__init__.pyi":
        return "STUB_PACKAGE_SOURCE"
    if name.endswith(".pyi"):
        return "STUB_MODULE_SOURCE"
    return "MODULE_SOURCE"


def _importer_contexts(unit, mappings):
    rows = []
    path = unit.get("path")
    is_package_initializer = type(path) is str and Path(path).name in _INIT_FILES
    for module_name, source_root in mappings:
        rows.append({"module_name": module_name, "source_root": source_root,
                     "package_context": module_name if is_package_initializer
                     else module_name.rpartition(".")[0]})
    return tuple(rows)


def _resolve_from(module, level, importer_module):
    if type(level) is not int or level < 0:
        return None, "INVALID_RELATIVE_LEVEL"
    if level == 0:
        if not _valid_module_name(module):
            return None, "INVALID_ABSOLUTE_MODULE"
        return module, "OK"
    if importer_module is None:
        return None, "IMPORTER_MODULE_NAME_UNAVAILABLE"
    package = importer_module
    parts = package.split(".") if package else []
    if level > len(parts):
        return None, "RELATIVE_IMPORT_OVERFLOW"
    base = parts[:len(parts) - (level - 1)]
    if module:
        if not _valid_module_name(module):
            return None, "INVALID_RELATIVE_MODULE"
        base.extend(module.split("."))
    result = ".".join(base)
    if not result:
        return None, "RELATIVE_IMPORT_OVERFLOW"
    return result, "OK"


def _candidate_reference(unit, module_name, source_root, kind):
    row = {"unit_key": unit.get("key"), "path": unit.get("path"),
           "module_name": module_name, "source_root": source_root,
           "candidate_kind": kind}
    # Preserve original SG initializer references when the producer has them.
    # Never synthesize an initializer from a filename or module name.
    if "module_initializer_ids" in unit:
        row["module_initializer_ids"] = unit["module_initializer_ids"]
    return row


def _status_for_candidates(candidates):
    identities = {(item.get("unit_key"), item.get("path"), item.get("source_root"))
                  for item in candidates}
    return "SOURCE_CANDIDATE" if len(identities) == 1 else "AMBIGUOUS_SOURCE_CANDIDATE"


def build_import_index(units, load_lexical) -> dict:
    """Return JSON-compatible import-to-source-candidate relationships.

    ``units`` are static-program manifest rows. ``load_lexical(unit)`` returns
    that unit's decoded lexical catalog. Each alias remains a distinct
    occurrence, even when several aliases share one original ``source_ref``.
    Missing local source is reported as ``EXTERNAL_SOURCE_NOT_SUPPLIED``; this
    is a source-scope frontier, not a request for runtime probing.
    """
    if isinstance(units, (str, bytes, dict)):
        raise TypeError("units must be an iterable of static-program unit records")
    if not callable(load_lexical):
        raise TypeError("load_lexical must be callable")

    source_issues = []
    unit_rows = []
    module_index = defaultdict(list)
    directory_index = defaultdict(list)
    root_package_names = set()
    seen_keys = set()

    for ordinal, unit in enumerate(units):
        if type(unit) is not dict:
            source_issues.append({"kind": "INVALID_UNIT", "unit_index": ordinal,
                                  "detail": "Static-program unit must be a dict."})
            continue
        key, path = unit.get("key"), unit.get("path")
        if type(key) is not str or not key or key in seen_keys:
            source_issues.append({"kind": "INVALID_UNIT_KEY", "unit_index": ordinal,
                                  "unit_key": key, "detail": "Unit key must be unique nonempty text."})
            continue
        seen_keys.add(key)
        mappings = _unit_mappings(unit, source_issues)
        row = {"unit": unit, "mappings": mappings}
        unit_rows.append(row)
        if type(path) is not str or not Path(path).is_absolute():
            continue
        for module_name, source_root in mappings:
            kind = _candidate_kind(unit)
            candidate = _candidate_reference(unit, module_name, source_root, kind)
            module_index[module_name].append(candidate)
            if (kind == "PACKAGE_INITIALIZER" and Path(path).parent == Path(source_root)
                    and module_name == Path(source_root).name):
                root_package_names.add((source_root, module_name))

    # Derive only directory candidates implied by the supplied file mappings.
    # A directory can support a namespace-package candidate; it is not an
    # operation or an asserted Python import resolution.
    for row in unit_rows:
        unit, mappings = row["unit"], row["mappings"]
        path_value = unit.get("path")
        if type(path_value) is not str or not Path(path_value).is_absolute():
            continue
        path = Path(path_value)
        for module_name, source_root in mappings:
            root = Path(source_root)
            parts = module_name.split(".")
            prefix_start = 0
            if parts and (source_root, parts[0]) in root_package_names:
                directory_index[parts[0]].append({"path": str(root), "source_root": source_root,
                                                  "module_name": parts[0]})
                prefix_start = 1
            if path.name in _INIT_FILES:
                directory_index[module_name].append({"path": str(path.parent),
                    "source_root": source_root, "module_name": module_name})
            else:
                for depth in range(prefix_start + 1, len(parts)):
                    prefix = ".".join(parts[:depth])
                    suffix_parts = parts[prefix_start:depth]
                    directory = root.joinpath(*suffix_parts)
                    directory_index[prefix].append({"path": str(directory),
                        "source_root": source_root, "module_name": prefix})

    for candidates in module_index.values():
        candidates.sort(key=lambda item: (item["module_name"], item["source_root"],
                                          item.get("path") or "", item.get("unit_key") or ""))
    for candidates in directory_index.values():
        unique = {(item["path"], item["source_root"], item["module_name"]): item for item in candidates}
        candidates[:] = [unique[key] for key in sorted(unique)]

    relations = []
    # A non-importable physical source name does not invalidate unrelated
    # absolute imports or the source catalog. Preserve it as a namespace fact.
    namespace_notes = [issue for issue in source_issues
                       if issue["kind"] == "SOURCE_NAME_NOT_IMPORTABLE_BY_SYNTAX"]
    issues = [issue for issue in source_issues
              if issue["kind"] != "SOURCE_NAME_NOT_IMPORTABLE_BY_SYNTAX"]
    lexical_scope_frontiers = []
    import_occurrences = alias_occurrences = lexical_units = 0
    for row in unit_rows:
        unit, mappings = row["unit"], row["mappings"]
        try:
            catalog = load_lexical(unit)
        except Exception as error:
            issues.append({"kind": "LEXICAL_CATALOG_UNAVAILABLE", "unit_key": unit.get("key"),
                           "path": unit.get("path"),
                           "detail": f"{type(error).__name__}: {error}"})
            continue
        if type(catalog) is not dict or type(catalog.get("imports")) is not list:
            issues.append({"kind": "INVALID_LEXICAL_IMPORTS", "unit_key": unit.get("key"),
                           "path": unit.get("path"),
                           "detail": "Lexical catalog must contain an imports list."})
            continue
        lexical_units += 1
        lexical_issues = catalog.get("issues", [])
        if type(lexical_issues) is list and lexical_issues:
            # Annotation/closure rule gaps are independent of an import's
            # syntactic source and candidates, and must not poison its status.
            lexical_scope_frontiers.append({"unit_key": unit.get("key"),
                "catalog_artifact": unit.get("artifacts", {}).get("lexical"),
                "issue_kinds": dict(Counter(item["kind"] for item in lexical_issues))})
        contexts = _importer_contexts(unit, mappings)
        for import_index, occurrence in enumerate(catalog["imports"]):
            if type(occurrence) is not dict or type(occurrence.get("names")) is not list:
                issues.append({"kind": "INVALID_IMPORT_OCCURRENCE", "unit_key": unit.get("key"),
                               "import_index": import_index,
                               "detail": "Lexical import must be a dict with an ordered names list."})
                continue
            import_occurrences += 1
            names = occurrence["names"]
            import_kind = occurrence.get("kind")
            base_record = {
                "importer_unit": unit.get("key"), "importer_path": unit.get("path"),
                "importer_namespace_root": unit.get("namespace_root"),
                "source_ref": occurrence.get("source_ref"),
                "ast_path": occurrence.get("ast_path"),
                "owner": occurrence.get("owner"), "phase": occurrence.get("phase"),
                "syntax_control_context": occurrence.get("syntax_control_context", []),
                "import_index": import_index, "import_kind": import_kind,
                "module": occurrence.get("module"), "level": occurrence.get("level", 0),
                "lexical_status": occurrence.get("status"),
            }
            if base_record["source_ref"] is None:
                issues.append({"kind": "IMPORT_SOURCE_REFERENCE_MISSING", "unit_key": unit.get("key"),
                               "import_index": import_index, "ast_path": base_record["ast_path"],
                               "detail": "Original lexical import has no source_ref."})
            context_rows = contexts or ({"module_name": None, "source_root": unit.get("namespace_root"),
                                         "package_context": None},)
            if import_kind == "Import":
                if not names:
                    issues.append({"kind": "EMPTY_IMPORT_ALIASES", "unit_key": unit.get("key"),
                                   "import_index": import_index, "detail": "Import occurrence has no aliases."})
                for alias_index, alias in enumerate(names):
                    if type(alias) is not dict or type(alias.get("name")) is not str:
                        issues.append({"kind": "INVALID_IMPORT_ALIAS", "unit_key": unit.get("key"),
                                       "import_index": import_index, "alias_index": alias_index,
                                       "detail": "Import alias must include its original name."})
                        continue
                    alias_occurrences += 1
                    requested = alias["name"]
                    bound = alias.get("asname") or requested.split(".")[0]
                    for context in context_rows:
                        bound_module = requested if alias.get("asname") else requested.split(".")[0]
                        common = {**base_record, "alias_index": alias_index,
                                  "name": requested, "asname": alias.get("asname"),
                                  "bound_name": bound,
                                  "importer_module": context.get("module_name"),
                                  "search_root": context.get("source_root")}
                        _emit_module(relations, module_index, directory_index, common,
                                     "IMPORT_TARGET_MODULE", requested)
                        if bound_module != requested:
                            _emit_module(relations, module_index, directory_index, common,
                                         "IMPORT_BOUND_TOPLEVEL", bound_module)
                        _emit_parent_candidates(relations, module_index, directory_index,
                                                common, requested)
            elif import_kind == "ImportFrom":
                if not names:
                    issues.append({"kind": "EMPTY_IMPORT_ALIASES", "unit_key": unit.get("key"),
                                   "import_index": import_index, "detail": "ImportFrom occurrence has no aliases."})
                for context_index, context in enumerate(context_rows):
                    base_module, base_status = _resolve_from(occurrence.get("module"),
                        occurrence.get("level", 0), context.get("package_context"))
                    common_base = {**base_record, "importer_module": context.get("module_name"),
                                   "search_root": context.get("source_root"),
                                   "resolved_base_module": base_module}
                    if base_status == "OK":
                        _emit_module(relations, module_index, directory_index, common_base,
                                     "FROM_BASE_MODULE", base_module)
                        _emit_parent_candidates(relations, module_index, directory_index,
                                                common_base, base_module)
                    else:
                        relations.append({**common_base, "relation_kind": "FROM_BASE_MODULE",
                            "candidate_module": None, "candidate": None, "status": base_status})
                    for alias_index, alias in enumerate(names):
                        if type(alias) is not dict or type(alias.get("name")) is not str:
                            issues.append({"kind": "INVALID_IMPORT_ALIAS", "unit_key": unit.get("key"),
                                           "import_index": import_index, "alias_index": alias_index,
                                           "detail": "ImportFrom alias must include its original name."})
                            continue
                        if context_index == 0:
                            alias_occurrences += 1
                        name, asname = alias["name"], alias.get("asname")
                        common = {**common_base, "alias_index": alias_index,
                                  "name": name, "asname": asname,
                                  "bound_name": asname or name if name != "*" else None}
                        if name == "*":
                            _emit_export_candidate(relations, module_index, directory_index, common, base_module,
                                                   "*", status="STAR_EXPORT_UNCLOSED",
                                                   base_status=base_status)
                        elif base_status == "OK":
                            _emit_export_candidate(relations, module_index, directory_index, common, base_module,
                                                   name, status="EXPORT_CANDIDATE_UNRESOLVED")
                            submodule = base_module + "." + name
                            _emit_module(relations, module_index, directory_index, common,
                                         "FROM_POSSIBLE_SUBMODULE", submodule)
                        else:
                            relations.append({**common, "relation_kind": "FROM_EXPORT_ATTRIBUTE",
                                "candidate_module": None, "candidate": None,
                                "status": base_status})
            else:
                issues.append({"kind": "UNSUPPORTED_IMPORT_KIND", "unit_key": unit.get("key"),
                               "import_index": import_index, "ast_path": base_record["ast_path"],
                               "detail": f"Unsupported lexical import kind: {import_kind!r}"})

    relations.sort(key=lambda item: (
        item.get("importer_path") or "", item.get("ast_path") or "",
        item.get("import_index", -1), item.get("importer_module") or "",
        item.get("alias_index", -1), item.get("relation_kind", ""),
        (item.get("candidate") or {}).get("source_root", ""),
        (item.get("candidate") or {}).get("path", ""),
    ))
    issues.sort(key=lambda item: (item.get("path") or "", item.get("unit_key") or "",
                                  item.get("kind", ""), item.get("import_index", -1),
                                  item.get("detail", "")))
    status_counts = Counter(item["status"] for item in relations)
    relation_counts = Counter(item["relation_kind"] for item in relations)
    status = "COMPLETE" if not issues else "PARTIAL"
    return {
        "schema": "scar.static-import-index", "schema_version": 1,
        "status": status, "units": len(unit_rows), "lexical_units": lexical_units,
        "relations": relations, "issues": issues, "namespace_notes": namespace_notes,
        "independent_scope_frontiers": lexical_scope_frontiers,
        "summary": {
            "units": len(unit_rows), "lexical_units": lexical_units,
            "import_occurrences": import_occurrences, "alias_occurrences": alias_occurrences,
            "relations": len(relations), "relation_kinds": dict(sorted(relation_counts.items())),
            "candidate_statuses": dict(sorted(status_counts.items())),
            "source_candidate_relations": (status_counts.get("SOURCE_CANDIDATE", 0)
                                           + status_counts.get("AMBIGUOUS_SOURCE_CANDIDATE", 0)
                                           + status_counts.get("NAMESPACE_PACKAGE_CANDIDATE", 0)
                                           + status_counts.get("STUB_SOURCE_ONLY", 0)),
            "ambiguous_relations": status_counts.get("AMBIGUOUS_SOURCE_CANDIDATE", 0),
            "external_source_not_supplied": status_counts.get("EXTERNAL_SOURCE_NOT_SUPPLIED", 0),
            "issues": len(issues),
            "target_executed": False, "runtime_import_result_established": False,
            "module_initialization_pure_established": False,
        },
    }


def _emit_module(relations, module_index, directory_index, common, relation_kind, module_name):
    if not _valid_module_name(module_name):
        relations.append({**common, "relation_kind": relation_kind,
                          "candidate_module": module_name, "candidate": None,
                          "status": "INVALID_MODULE_NAME"})
        return
    candidates = list(module_index.get(module_name, ()))
    runtime_package_roots = {item["source_root"] for item in candidates
                             if item["candidate_kind"] == "PACKAGE_INITIALIZER"}
    directories = [item for item in directory_index.get(module_name, ())
                   if item["source_root"] not in runtime_package_roots]
    if not candidates and not directories:
        relations.append({**common, "relation_kind": relation_kind,
                          "candidate_module": module_name, "candidate": None,
                          "status": "EXTERNAL_SOURCE_NOT_SUPPLIED"})
        return
    total = len(candidates) + len(directories)
    ambiguous = total > 1
    for candidate in candidates:
        if ambiguous:
            status = "AMBIGUOUS_SOURCE_CANDIDATE"
        elif candidate["candidate_kind"] in ("STUB_MODULE_SOURCE", "STUB_PACKAGE_SOURCE"):
            status = "STUB_SOURCE_ONLY"
        else:
            status = "SOURCE_CANDIDATE"
        relations.append({**common, "relation_kind": relation_kind,
                          "candidate_module": module_name, "candidate": candidate,
                          "status": status})
    for directory in directories:
        relations.append({**common, "relation_kind": relation_kind,
                          "candidate_module": module_name,
                          "candidate": {"unit_key": None, "path": directory["path"],
                              "module_name": module_name, "source_root": directory["source_root"],
                              "candidate_kind": "NAMESPACE_PACKAGE_DIRECTORY"},
                          "status": "AMBIGUOUS_SOURCE_CANDIDATE" if ambiguous
                          else "NAMESPACE_PACKAGE_CANDIDATE"})


def _emit_export_candidate(relations, module_index, directory_index, common, base_module, export_name,
                           *, status, base_status="OK"):
    if base_status != "OK":
        relations.append({**common, "relation_kind": "FROM_EXPORT_ATTRIBUTE",
                          "candidate_module": base_module, "candidate": None,
                          "export_name": export_name,
                          "status": status if status == "STAR_EXPORT_UNCLOSED" else base_status,
                          "candidate_selection_status": base_status})
        return
    candidates = list(module_index.get(base_module, ()))
    runtime_package_roots = {item["source_root"] for item in candidates
                             if item["candidate_kind"] == "PACKAGE_INITIALIZER"}
    candidates.extend({**item, "unit_key": None, "candidate_kind": "NAMESPACE_PACKAGE_DIRECTORY"}
                      for item in directory_index.get(base_module, ())
                      if item["source_root"] not in runtime_package_roots)
    if not candidates:
        relations.append({**common, "relation_kind": "FROM_EXPORT_ATTRIBUTE",
                          "candidate_module": base_module, "candidate": None,
                          "export_name": export_name,
                          "status": status if status == "STAR_EXPORT_UNCLOSED" else "EXTERNAL_SOURCE_NOT_SUPPLIED",
                          "candidate_selection_status": "EXTERNAL_SOURCE_NOT_SUPPLIED"})
        return
    candidate_status = _status_for_candidates(candidates)
    for candidate in candidates:
        relations.append({**common, "relation_kind": "FROM_EXPORT_ATTRIBUTE",
                          "candidate_module": base_module, "candidate": candidate,
                          "export_name": export_name,
                          "status": status,
                          "candidate_selection_status": candidate_status})


def _emit_parent_candidates(relations, module_index, directory_index, common, module_name):
    if not _valid_module_name(module_name):
        return
    parts = module_name.split(".")
    for depth in range(1, len(parts)):
        parent = ".".join(parts[:depth])
        candidates = [item for item in module_index.get(parent, ())
                      if item["candidate_kind"] in ("PACKAGE_INITIALIZER", "STUB_PACKAGE_SOURCE")]
        runtime_roots = {item["source_root"] for item in candidates
                         if item["candidate_kind"] == "PACKAGE_INITIALIZER"}
        directories = [item for item in directory_index.get(parent, ())
                       if item["source_root"] not in runtime_roots]
        selection_status = _status_for_candidates([*candidates, *directories]) if candidates or directories else None
        if candidates:
            for candidate in candidates:
                kind = candidate["candidate_kind"]
                relations.append({**common, "relation_kind": "PARENT_PACKAGE_INITIALIZER",
                    "candidate_module": parent, "candidate": candidate,
                    "status": "STUB_PACKAGE_SOURCE_ONLY" if kind == "STUB_PACKAGE_SOURCE" else selection_status,
                    "candidate_selection_status": selection_status})
        # An initializer-less directory is only a namespace-package candidate.
        for directory in directories:
            relations.append({**common, "relation_kind": "PARENT_NAMESPACE_PACKAGE",
                "candidate_module": parent,
                "candidate": {"unit_key": None, "path": directory["path"],
                    "module_name": parent, "source_root": directory["source_root"],
                    "candidate_kind": "NAMESPACE_PACKAGE_DIRECTORY"},
                "status": "AMBIGUOUS_SOURCE_CANDIDATE" if selection_status == "AMBIGUOUS_SOURCE_CANDIDATE"
                else "NAMESPACE_PACKAGE_CANDIDATE",
                "candidate_selection_status": selection_status})
        if not directories and not candidates:
            nonpackages = module_index.get(parent, ())
            if nonpackages:
                for candidate in nonpackages:
                    relations.append({**common, "relation_kind": "PARENT_NOT_PACKAGE",
                        "candidate_module": parent, "candidate": candidate,
                        "status": "SOURCE_MODULE_NOT_PACKAGE"})
            else:
                relations.append({**common, "relation_kind": "PARENT_PACKAGE_INITIALIZER",
                    "candidate_module": parent, "candidate": None,
                    "status": "EXTERNAL_SOURCE_NOT_SUPPLIED"})


__all__ = ["build_import_index"]
