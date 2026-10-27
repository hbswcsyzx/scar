"""Source-only lexical catalog; navigation records never define another IR.

The caller owns source discovery/byte budgets.  This module does not open files,
import a target, resolve CodeWitness, lower a body, or execute source.  Optional
``source_text`` is the original decoded text, used only by the stdlib symbol
table builder.  Symbol-table matches are candidates, not loaded-code evidence.
"""
from __future__ import annotations

import ast
from collections import Counter, defaultdict
import hashlib
import json
from pathlib import Path
import re
import symtable
import sys

from scar.ir.frontend_v2 import source_reference
from scar.ir.record_codec import encode


_ATOM_TYPES = (ast.stmt, ast.expr, ast.arg, ast.alias, ast.keyword, ast.ExceptHandler)
_FUNCTIONS = (ast.FunctionDef, ast.AsyncFunctionDef, ast.Lambda)
_COMPREHENSIONS = (ast.ListComp, ast.SetComp, ast.DictComp, ast.GeneratorExp)
_CONTROL = (ast.If, ast.IfExp, ast.While, ast.For, ast.AsyncFor, ast.Try,
            ast.BoolOp, ast.Match, ast.With, ast.AsyncWith)
if hasattr(ast, "TryStar"):
    _CONTROL += (ast.TryStar,)


def _span(node):
    return {name: getattr(node, name, None) for name in
            ("lineno", "col_offset", "end_lineno", "end_col_offset")}


def _children(node, path):
    for field, value in ast.iter_fields(node):
        if isinstance(value, ast.AST):
            yield field, value, path + "." + field
        elif isinstance(value, list):
            for index, child in enumerate(value):
                if isinstance(child, ast.AST):
                    yield field, child, f"{path}.{field}[{index}]"


def _yielding(body):
    pending = list(body)
    while pending:
        node = pending.pop()
        if isinstance(node, (ast.Yield, ast.YieldFrom)):
            return True
        if not isinstance(node, (*_FUNCTIONS, ast.ClassDef, *_COMPREHENSIONS)):
            pending.extend(ast.iter_child_nodes(node))
    return False


def _table_kind(table):
    value = table.get_type()
    return str(getattr(value, "value", value)).lower()


def _symbol_tables(text, filename, issues):
    if text is None:
        issues.append({"kind": "SYMBOL_SOURCE_UNAVAILABLE", "ast_path": "$",
                       "detail": "Original source_text was not supplied; no symtable or closure claim."})
        return []
    try:
        root = symtable.symtable(text, filename, "exec")
    except (SyntaxError, ValueError, RecursionError) as error:
        issues.append({"kind": "SYMBOL_TABLE_UNAVAILABLE", "ast_path": "$",
                       "detail": str(error), "line": getattr(error, "lineno", None)})
        return []
    result, pending = [], [(root, "$symbols", None)]
    flags = ("referenced", "parameter", "global", "nonlocal", "local", "free",
             "imported", "assigned", "annotated", "namespace", "declared_global",
             "type_parameter", "free_class", "comp_iter", "comp_cell")
    while pending:
        table, path, parent = pending.pop()
        symbols = []
        for symbol in sorted(table.get_symbols(), key=lambda item: item.get_name()):
            row = {"name": symbol.get_name()}
            for flag in flags:
                method = getattr(symbol, "is_" + flag, None)
                row[flag] = bool(method()) if method is not None else None
            symbols.append(row)
        result.append({"table_path": path, "parent": parent, "kind": _table_kind(table),
                       "name": table.get_name(), "lineno": table.get_lineno(),
                       "symbols": symbols,
                       "free_names": [item["name"] for item in symbols if item["free"]],
                       "source": "ORIGINAL_SOURCE_STDLIB_SYMTABLE"})
        children = list(table.get_children())
        pending.extend((child, f"{path}.children[{index}]", path)
                       for index, child in reversed(list(enumerate(children))))
    return result


class _Catalog:
    def __init__(self, tree, path, root, fingerprint, semantic, source_text):
        self.tree, self.path, self.root, self.fingerprint = tree, path, root, fingerprint
        self.refs = {id(node): source_reference(Path(path), Path(root), fingerprint, index, node)
                     for index, node in enumerate(ast.walk(tree))
                     if isinstance(node, _ATOM_TYPES) and hasattr(node, "lineno")}
        self.semantic = semantic
        self.by_atom = defaultdict(list)
        if semantic is not None:
            for definition in semantic.definitions.values():
                if definition.source_file == path:
                    self.by_atom[definition.code_id].append(definition)
        self.entries, self.scopes, self.syntax_nodes = [], [], []
        self.calls, self.imports, self.dynamic_sites, self.issues = [], [], [], []
        self.syntax = Counter()
        self.entry_by_key = {}
        self.scope_by_key = {}
        self.tables = _symbol_tables(source_text, path, self.issues)

    def anchor(self, node, path):
        reference = self.refs.get(id(node))
        return {"path": self.path, "namespace_root": self.root,
                "fingerprint": self.fingerprint, "ast_path": path,
                "source_ref": encode(reference) if reference is not None else None,
                "span": _span(node)}

    def _association(self, node, phase, module=False):
        if self.semantic is None:
            return None, []
        if module:
            modules = [item for item in self.semantic.modules.values()
                       if item.path == self.path and item.fingerprint == self.fingerprint
                       and item.initializer is not None]
            ids = sorted({item.initializer for item in modules}, key=lambda item: item.wire)
            if not ids:
                self.issues.append({"kind": "SEMANTIC_MODULE_UNMATCHED", "ast_path": "$",
                                    "detail": "No original module initializer matches path and fingerprint."})
            return [encode(item) for item in ids] or None, []
        reference = self.refs.get(id(node))
        if reference is None:
            return None, []
        atom = self.semantic.source_atoms.get(reference.atom_id)
        if atom is None or atom.reference != reference:
            self.issues.append({"kind": "SEMANTIC_SOURCE_UNMATCHED",
                                "source_ref": encode(reference),
                                "detail": "The original semantic source atom is absent or differs."})
            return None, []
        candidates = sorted(self.by_atom.get(reference.atom_id.wire, ()), key=lambda item: item.id.wire)
        # An absent phase must not associate an annotation/type context with
        # an unrelated opaque operation which also has no phase declaration.
        exact = [item for item in candidates if phase is not None
                 and item.metadata.get("phase") == phase]
        return ([encode(item.id) for item in exact] or None,
                [{"id": encode(item.id), "phase": item.metadata.get("phase"),
                  "kind": item.kind.value} for item in candidates])

    def entry(self, node, path, kind, owner, phase, *, name=None,
              definition_phase=None, semantic_phase=None, version_dependent=False):
        anchor = self.anchor(node, path)
        # A derived catalog key: no OperationDefinitionID or body ID is minted.
        key_input = {**anchor, "phase": phase}
        key = "lexical:" + hashlib.sha256(json.dumps(
            key_input, sort_keys=True, separators=(",", ":")).encode()).hexdigest()
        if key in self.entry_by_key:
            raise ValueError("one source/phase catalog entry was visited twice")
        parent = self.entry_by_key.get(owner)
        display = name or type(node).__name__
        qualname = display if parent is None else parent["qualname"] + "." + display
        ids, candidates = self._association(node, semantic_phase, kind == "MODULE")
        row = {"entry_key": key, **anchor, "kind": kind, "name": display,
               "qualname": qualname, "phase": phase, "definition_phase": definition_phase,
               "lexical_parent": owner, "definition_owner": owner,
               "subject_entry_key": None,
               "semantic_definition_ids": ids, "semantic_source_candidates": candidates,
               "catalog_status": "SEMANTIC_ASSOCIATED" if ids else "CATALOGED",
               "support_status": "UNEXPANDED", "language_version_dependent": version_dependent,
               "symbol_table_candidates": [], "closure_names": None,
               "closure_status": "UNAVAILABLE", "formal_parameters": [],
               "definition_inputs": []}
        if version_dependent:
            row["implicit_scope_status"] = "REQUIRES_VERSIONED_LANGUAGE_RULE"
            self.issues.append({"kind": "IMPLICIT_SCOPE_LANGUAGE_RULE_REQUIRED",
                                "entry_key": key, "ast_path": path,
                                "detail": "Syntax context is cataloged; compiler thunk/frame existence and timing are not asserted."})
        self.entries.append(row)
        self.entry_by_key[key] = row
        scope = {"entry_key": key, "kind": kind, "lexical_parent": owner,
                 "phase": phase, "runtime_frame_established": False,
                 "language_version_dependent": version_dependent}
        self.scopes.append(scope)
        self.scope_by_key[key] = scope
        return row

    def record(self, node, path, owner, phase, controls):
        kind = type(node).__name__
        self.syntax[kind] += 1
        anchor = self.anchor(node, path)
        self.syntax_nodes.append({**anchor, "ast_type": kind, "owner": owner,
                                  "phase": phase, "syntax_control_context": controls})
        site = {**anchor, "owner": owner, "phase": phase,
                "syntax_control_context": controls}
        if isinstance(node, ast.Call):
            self.calls.append({**site, "callee_ast_path": path + ".func",
                               "positional_count": len(node.args),
                               "has_starred": any(isinstance(item, ast.Starred) for item in node.args),
                               "keywords": [item.arg for item in node.keywords]})
            func = node.func
            spelling = func.id if isinstance(func, ast.Name) else func.attr if isinstance(func, ast.Attribute) else None
            if spelling in {"eval", "exec", "compile", "__import__", "import_module", "find_spec"}:
                self.dynamic_sites.append({**site, "spelling": spelling,
                                           "status": "SYNTAX_CANDIDATE_NOT_RESOLVED_BUILTIN",
                                           "kind": "DYNAMIC_SOURCE_OR_IMPORT"})
        if isinstance(node, (ast.Import, ast.ImportFrom)):
            self.imports.append({**site, "kind": kind, "module": getattr(node, "module", None),
                                 "level": getattr(node, "level", 0),
                                 "names": [{"name": item.name, "asname": item.asname} for item in node.names],
                                 "status": "SYNTAX_ONLY_NOT_IMPORT_RESULT"})

    def _input(self, entry, role, node, path, index=None):
        entry["definition_inputs"].append({"role": role, "index": index,
                                            **self.anchor(node, path)})

    def _annotation_scope(self, node, path, owner, *, subject_entry_key=None):
        entry = self.entry(node, path, "ANNOTATION_CONTEXT", owner, "ANNOTATION",
                           name="<annotations>", semantic_phase="annotation_time",
                           version_dependent=True)
        entry["subject_entry_key"] = subject_entry_key
        return entry

    def _arguments(self, node, path, outer, phase, body, annotation, controls):
        self.record(node, path, body["entry_key"], "FORMAL_INTERFACE", controls)
        positional = [*node.posonlyargs, *node.args]
        defaults = {id(arg): default for arg, default in
                    zip(positional[len(positional) - len(node.defaults):], node.defaults)}
        defaults.update({id(arg): default for arg, default in zip(node.kwonlyargs, node.kw_defaults)
                         if default is not None})
        for field, child, child_path in _children(node, path):
            if isinstance(child, ast.arg):
                self.record(child, child_path, body["entry_key"], "FORMAL_INTERFACE", controls)
                self.entry_by_key[body["entry_key"]]["formal_parameters"].append({
                    "name": child.arg, "kind": field, **self.anchor(child, child_path),
                    "has_default": id(child) in defaults,
                    "annotation": self.anchor(child.annotation, child_path + ".annotation")
                    if child.annotation is not None else None})
                for _, descendant, descendant_path in _children(child, child_path):
                    self.walk(descendant, descendant_path,
                              annotation["entry_key"] if annotation else outer,
                              "ANNOTATION", controls)
            else:
                self._input(body, "KEYWORD_DEFAULT" if field == "kw_defaults" else "DEFAULT",
                            child, child_path)
                self.walk(child, child_path, outer, phase, controls)

    def _definition(self, node, path, owner, phase, controls):
        is_class, is_lambda = isinstance(node, ast.ClassDef), isinstance(node, ast.Lambda)
        kind = ("CLASS" if is_class else "LAMBDA" if is_lambda else
                "ASYNC_FUNCTION" if isinstance(node, ast.AsyncFunctionDef) else "FUNCTION")
        name = getattr(node, "name", f"<lambda@{node.lineno}:{node.col_offset}>")
        body_phase = "CLASS_BODY" if is_class else "FUNCTION_BODY"
        entry = self.entry(node, path, kind, owner, body_phase, name=name,
                           definition_phase=phase, semantic_phase=None if is_class else "call_time")
        body = [node.body] if is_lambda else node.body
        entry["generator"] = False if is_class else _yielding(body)
        entry["async"] = isinstance(node, ast.AsyncFunctionDef)
        parameters = getattr(node, "type_params", ())
        type_scope = None
        if parameters:
            type_scope = self.entry(node, path, "TYPE_PARAMETERS", owner, "TYPE_PARAMETERS",
                                    name="<type-parameters>", version_dependent=True)
            type_scope["subject_entry_key"] = entry["entry_key"]
            entry["lexical_parent"] = type_scope["entry_key"]
            self.scope_by_key[entry["entry_key"]]["lexical_parent"] = type_scope["entry_key"]
        annotations = [] if is_class else [arg.annotation for arg in
            (*node.args.posonlyargs, *node.args.args, *node.args.kwonlyargs,
             *((node.args.vararg,) if node.args.vararg else ()),
             *((node.args.kwarg,) if node.args.kwarg else ())) if arg.annotation is not None]
        if getattr(node, "returns", None) is not None:
            annotations.append(node.returns)
        annotation = self._annotation_scope(node, path,
            type_scope["entry_key"] if type_scope else owner,
            subject_entry_key=entry["entry_key"]) if annotations else None
        for field, child, child_path in _children(node, path):
            if field == "body":
                self.walk(child, child_path, entry["entry_key"], body_phase, ())
            elif field == "args":
                self._arguments(child, child_path, owner, phase, entry, annotation, controls)
            elif field == "returns":
                self._input(entry, "RETURN_ANNOTATION", child, child_path)
                self.walk(child, child_path, annotation["entry_key"], "ANNOTATION", controls)
            elif field == "type_params":
                self._input(entry, "TYPE_PARAMETER", child, child_path)
                self.walk(child, child_path, type_scope["entry_key"], "TYPE_PARAMETERS", controls)
            else:
                role = {"decorator_list": "DECORATOR", "bases": "BASE", "keywords": "CLASS_KEYWORD"}.get(field, field)
                self._input(entry, role, child, child_path)
                execution_owner = type_scope["entry_key"] if type_scope and field in {"bases", "keywords"} else owner
                self.walk(child, child_path, execution_owner, phase, controls)

    def walk(self, node, path, owner, phase, controls):
        self.record(node, path, owner, phase, controls)
        if isinstance(node, (*_FUNCTIONS, ast.ClassDef)):
            self._definition(node, path, owner, phase, controls)
            return
        if isinstance(node, _COMPREHENSIONS):
            entry = self.entry(node, path, type(node).__name__.upper(), owner,
                               "COMPREHENSION_BODY", name=f"<{type(node).__name__}@{node.lineno}:{node.col_offset}>",
                               definition_phase=phase, semantic_phase="comprehension_body")
            entry["async"] = any(item.is_async for item in node.generators)
            entry["lazy"] = isinstance(node, ast.GeneratorExp)
            entry["separate_runtime_frame_established"] = False
            for field, child, child_path in _children(node, path):
                if field == "generators":
                    index = node.generators.index(child)
                    self.record(child, child_path, entry["entry_key"], "COMPREHENSION_BODY", controls)
                    for inner_field, inner, inner_path in _children(child, child_path):
                        eager = index == 0 and inner_field == "iter"
                        self.walk(inner, inner_path, owner if eager else entry["entry_key"],
                                  phase if eager else "COMPREHENSION_BODY", controls)
                else:
                    self.walk(child, child_path, entry["entry_key"], "COMPREHENSION_BODY", controls)
            return
        if isinstance(node, ast.AnnAssign):
            annotation = self._annotation_scope(node, path, owner)
            for field, child, child_path in _children(node, path):
                self.walk(child, child_path, annotation["entry_key"] if field == "annotation" else owner,
                          "ANNOTATION" if field == "annotation" else phase, controls)
            return
        if isinstance(node, getattr(ast, "TypeAlias", ())):
            entry = self.entry(node, path, "TYPE_ALIAS", owner, "TYPE_ALIAS_EVALUATION",
                               name=getattr(node.name, "id", "<type-alias>"),
                               definition_phase=phase, semantic_phase="type_alias_evaluation",
                               version_dependent=True)
            for field, child, child_path in _children(node, path):
                self.walk(child, child_path, owner if field == "name" else entry["entry_key"],
                          phase if field == "name" else "TYPE_ALIAS_EVALUATION", controls)
            return
        type_parameter = getattr(ast, "type_param", None)
        if type_parameter is not None and isinstance(node, type_parameter):
            for field, child, child_path in _children(node, path):
                entry = self.entry(node, path, "TYPE_PARAMETER_" + field.upper(), owner,
                                   "TYPE_PARAMETER_" + field.upper(), name=f"<{field}>",
                                   version_dependent=True)
                self.walk(child, child_path, entry["entry_key"], entry["phase"], controls)
            return
        for field, child, child_path in _children(node, path):
            nested = controls
            if isinstance(node, _CONTROL):
                nested = (*controls, {"ast_path": path, "ast_type": type(node).__name__, "field": field})
            self.walk(child, child_path, owner, phase, nested)

    def attach_symbols(self):
        names = {"FUNCTION": "function", "ASYNC_FUNCTION": "function", "CLASS": "class",
                 "LAMBDA": "function", "LISTCOMP": "function", "SETCOMP": "function",
                 "DICTCOMP": "function", "GENERATOREXP": "function", "MODULE": "module"}
        special_names = {"LAMBDA": "lambda", "LISTCOMP": "listcomp", "SETCOMP": "setcomp",
                         "DICTCOMP": "dictcomp", "GENERATOREXP": "genexpr", "MODULE": "top"}
        by_name_line = defaultdict(list)
        by_kind_line = defaultdict(list)
        for table in self.tables:
            by_name_line[(table["kind"], table["name"], table["lineno"])].append(table)
            by_kind_line[(table["kind"], table["lineno"])].append(table)
        implicit_kinds = {"ANNOTATION_CONTEXT": "annotation", "TYPE_PARAMETERS": "type parameters",
                          "TYPE_ALIAS": "type alias"}
        for entry in self.entries:
            kind = entry["kind"]
            candidates = by_name_line.get((names.get(kind), special_names.get(kind, entry["name"]),
                                           0 if kind == "MODULE" else entry["span"]["lineno"]), ())
            implicit = implicit_kinds.get(kind)
            if kind.startswith("TYPE_PARAMETER_"):
                implicit = "type variable"
            if implicit is not None:
                candidates = by_kind_line.get((implicit, entry["span"]["lineno"]), ())
            entry["symbol_table_candidates"] = [item["table_path"] for item in candidates]
            if candidates:
                entry["closure_names"] = sorted({name for table in candidates for name in table["free_names"]})
                entry["closure_status"] = ("SYMTABLE_KIND_LINE_CANDIDATES_NOT_EXACT_SCOPE_PROOF" if implicit
                                          else "SYMTABLE_NAME_LINE_CANDIDATES_NOT_EXACT_SCOPE_PROOF")
            if len(candidates) > 1:
                self.issues.append({"kind": "AMBIGUOUS_SYMBOL_SCOPE", "entry_key": entry["entry_key"],
                                    "detail": "Same-line/name tables remain separate; no unique closure association asserted."})

    def compiler_scope_links(self):
        """Project every original symbol table, including unmatched implicit scopes.

        Table paths/parents are compiler facts.  AST/subject associations remain
        explicit candidates; this projection does not mint code, IR or frames.
        """
        by_table, definitions_by_line = defaultdict(list), defaultdict(list)
        for entry in self.entries:
            for table_path in entry["symbol_table_candidates"]:
                by_table[table_path].append(entry)
            if entry["kind"] in {"FUNCTION", "ASYNC_FUNCTION", "CLASS", "LAMBDA", "TYPE_ALIAS"}:
                definitions_by_line[entry["span"]["lineno"]].append(entry)
        links = []
        implicit_kinds = {"annotation", "type alias", "type parameters", "type variable"}
        table_paths = {table["table_path"] for table in self.tables}
        for table in self.tables:
            parent = table["parent"]
            if parent is not None and parent not in table_paths:
                raise ValueError("compiler symbol table has an absent parent")
            entries = by_table.get(table["table_path"], ())
            subjects = {entry["subject_entry_key"] for entry in entries if entry["subject_entry_key"] is not None}
            basis = ["ENTRY_SYMBOL_TABLE_CANDIDATES"] if entries else []
            if table["kind"] in implicit_kinds:
                declarations = [entry for entry in definitions_by_line.get(table["lineno"], ())
                                if table["kind"] == "annotation" or entry["name"] == table["name"]]
                if declarations:
                    subjects.update(entry["entry_key"] for entry in declarations)
                    basis.append("DECLARATION_LINE_AND_APPLICABLE_NAME_CANDIDATES")
                if not subjects:
                    for entry in by_table.get(parent, ()):
                        if entry["kind"] in {"MODULE", "CLASS", "TYPE_PARAMETERS"}:
                            subjects.add(entry["subject_entry_key"] or entry["entry_key"])
                    if subjects:
                        basis.append("PARENT_TABLE_ENTRY_CANDIDATES")
            else:
                subjects.update(entry["entry_key"] for entry in entries)
            links.append({"table_path": table["table_path"], "parent_table_path": parent,
                          "kind": table["kind"], "name": table["name"], "lineno": table["lineno"],
                          "ast_entry_candidates": sorted(entry["entry_key"] for entry in entries) or None,
                          "subject_entry_candidates": sorted(subjects) or None,
                          "candidate_basis": basis,
                          "association_status": "CANDIDATE_ONLY" if entries or subjects else "UNMATCHED",
                          "source": table["source"], "runtime_thunk_established": False,
                          "runtime_frame_established": False})
        return links

    def build(self):
        module = self.entry(self.tree, "$", "MODULE", None, "MODULE_INITIALIZATION",
                            name="<module>", semantic_phase="module_initialization")
        self.record(self.tree, "$", module["entry_key"], "MODULE_INITIALIZATION", ())
        for _, child, path in _children(self.tree, "$"):
            self.walk(child, path, module["entry_key"], "MODULE_INITIALIZATION", ())
        self.attach_symbols()
        compiler_links = self.compiler_scope_links()
        actual = sum(self.syntax.values())
        expected = sum(1 for _ in ast.walk(self.tree))
        if actual != expected:
            raise ValueError("lexical catalog omitted or duplicated an AST occurrence")
        futures = sorted({alias.name for node in self.tree.body
                          if isinstance(node, ast.ImportFrom) and node.module == "__future__" and node.level == 0
                          for alias in node.names})
        return {"schema": "scar.static-lexical-catalog", "schema_version": 1,
                "path": self.path, "namespace_root": self.root, "fingerprint": self.fingerprint,
                "reference_policy": "frontend_v2.source_reference/ast.walk",
                "entry_identity": "CATALOG_NAVIGATION_ONLY_SOURCE_AND_PHASE",
                "parser_python_version": ".".join(map(str, sys.version_info[:3])),
                "future_imports": futures, "entries": self.entries,
                "syntax": dict(sorted(self.syntax.items())), "syntax_nodes": self.syntax_nodes,
                "scopes": self.scopes, "symbol_tables": self.tables,
                "compiler_scope_links": compiler_links,
                "calls": self.calls, "imports": self.imports, "dynamic_sites": self.dynamic_sites,
                "issues": self.issues,
                "completion": {"explicit_ast_catalog_complete": actual == expected,
                               "compiler_symbol_tables_cataloged": bool(self.tables)
                               and len(compiler_links) == len(self.tables),
                               "implicit_scope_semantics_complete": False,
                               "language_ledger_complete": False,
                               "body_expansion_complete": False,
                               "whole_program_model_complete": False},
                "summary": {"ast_occurrences": actual, "entries": len(self.entries),
                            "entry_kinds": dict(sorted(Counter(row["kind"] for row in self.entries).items())),
                            "source_references": len(self.refs), "calls": len(self.calls),
                            "imports": len(self.imports), "implicit_scope_language_rules_complete": False,
                            "compiler_symbol_tables": len(self.tables),
                            "compiler_scopes_without_ast_entry": sum(
                                link["ast_entry_candidates"] is None for link in compiler_links),
                            "bodies_lowered": 0, "target_executed": False}}


def inspect_lexical(tree: ast.Module, *, path: str, namespace_root: str,
                    fingerprint: str, semantic=None, source_text: str | None = None) -> dict:
    """Catalog every AST occurrence and lexical context without target execution.

    Existing SG IDs are associated only by exact original source/phase.  Missing
    IDs remain None.  Annotation/type contexts are explicitly version-dependent;
    this catalog does not certify an implicit code object, frame or lowerability.
    """
    if type(tree) is not ast.Module:
        raise TypeError("inspect_lexical requires an original ast.Module")
    if (type(path) is not str or type(namespace_root) is not str
            or not Path(path).is_absolute() or not Path(namespace_root).is_absolute()
            or ".." in Path(path).parts or ".." in Path(namespace_root).parts
            or not Path(path).is_relative_to(Path(namespace_root))):
        raise ValueError("lexical paths must preserve an absolute source namespace")
    if type(fingerprint) is not str or re.fullmatch(r"sha256:[0-9a-f]{64}", fingerprint) is None:
        raise ValueError("fingerprint must be the canonical decoded-source SHA256")
    if source_text is not None:
        if type(source_text) is not str:
            raise TypeError("source_text must be original decoded text or None")
        if "sha256:" + hashlib.sha256(source_text.encode()).hexdigest() != fingerprint:
            raise ValueError("source_text differs from its original fingerprint")
    return _Catalog(tree, path, namespace_root, fingerprint, semantic, source_text).build()


__all__ = ["inspect_lexical"]
