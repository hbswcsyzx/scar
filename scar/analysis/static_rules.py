"""Pure-source lowering selection and prerequisites, not a body-support proof.

Rules name existing dispatchers/producers.  No target is imported, compiled or
executed, and no CodeWitness is created.  Catalog keys remain navigation keys.
The compiler requirements describe missing static inputs/adapters, never an
observed implementation or runtime identity.
"""
from __future__ import annotations

import ast
from functools import lru_cache
import hashlib
import math
from pathlib import Path
import re

from scar.ir.program.functions import BodyLoweringProfile
from scar.ir.program.module_entries import FrameBodyProfile
from scar.ir.program.source_language import SourceLanguageCapability as C


_AUTO_PROFILE = "SCAR_STATIC_SOURCE_CAPS_V2"
_DEFAULT_CAPS = (C.FIXED_UNPACK, C.SLICE_KEYS, C.LEXICAL_LOCALS)
_FUNCS = (ast.FunctionDef, ast.AsyncFunctionDef)
_COMPS = (ast.ListComp, ast.SetComp, ast.DictComp)
_METADATA = (ast.arg, ast.alias, ast.keyword, ast.ExceptHandler, ast.comprehension)


def _children(node, path):
    for field, value in ast.iter_fields(node):
        if isinstance(value, ast.AST):
            yield value, path + "." + field
        elif isinstance(value, list):
            for index, child in enumerate(value):
                if isinstance(child, ast.AST):
                    yield child, f"{path}.{field}[{index}]"


def _at_path(tree, path):
    if type(path) is not str or not path.startswith("$"):
        raise ValueError("entry needs its original AST path")
    current, offset = tree, 1
    for match in re.finditer(r"\.([A-Za-z_][A-Za-z_0-9]*)(?:\[([0-9]+)\])?", path[1:]):
        if match.start() != offset - 1 or match.group(1) not in current._fields:
            raise ValueError("entry AST path differs from the original tree")
        current = getattr(current, match.group(1))
        if match.group(2) is not None:
            current = current[int(match.group(2))]
        if not isinstance(current, ast.AST):
            raise ValueError("entry AST path must select an AST node")
        offset = match.end() + 1
    if offset != len(path):
        raise ValueError("entry AST path has an unsupported suffix")
    return current


def _owned(node, path):
    """Select source-owned syntax without crossing deferred bodies.

    Nested creation/defaults are the enclosing body's work. Generator lazy body
    is a separate lexical entry; its constants must never use parent co_consts.
    """
    yield node, path
    if isinstance(node, (*_FUNCS, ast.Lambda, ast.ClassDef)):
        for child, child_path in _children(node, path):
            field = child_path[len(path) + 1:].split("[")[0].split(".")[0]
            if field in {"decorator_list", "bases", "keywords"}:
                yield from _owned(child, child_path)
            elif field == "args":
                for value, value_path in _children(child, child_path):
                    if value_path.startswith(child_path + ".defaults[") or value_path.startswith(child_path + ".kw_defaults["):
                        yield from _owned(value, value_path)
        return
    if isinstance(node, ast.GeneratorExp):
        if node.generators:
            yield from _owned(node.generators[0].iter, path + ".generators[0].iter")
        return
    # AnnAssign annotation has its own catalog context and versioned timing.
    for child, child_path in _children(node, path):
        if isinstance(node, ast.AnnAssign) and child is node.annotation:
            continue
        yield from _owned(child, child_path)


@lru_cache(maxsize=64)
def _source(module, signature):
    package = Path(__file__).parent.parent
    file = package.joinpath(*module.split(".")[1:]).with_suffix(".py")
    raw = file.read_bytes()
    if _stat(file) != signature:
        raise ValueError("lowering rule source changed while being read")
    tree = ast.parse(raw, filename=str(file))
    names = set()
    def visit(node, prefix):
        for child in ast.iter_child_nodes(node):
            if isinstance(child, (ast.FunctionDef, ast.AsyncFunctionDef, ast.ClassDef)):
                name = prefix + child.name
                names.add(name)
                if isinstance(child, ast.ClassDef):
                    visit(child, name + ".")
    visit(tree, "")
    return hashlib.sha256(raw).hexdigest(), names


def _stat(path):
    info = path.stat()
    return info.st_dev, info.st_ino, info.st_size, info.st_mtime_ns, info.st_ctime_ns


def _reference(module, function, kind, phase):
    module = "scar.analysis." + module
    file = Path(__file__).parent / (module.rsplit(".", 1)[1] + ".py")
    digest, names = _source(module, _stat(file))
    if function not in names:
        raise ValueError("lowering rule function no longer exists: " + module + "." + function)
    return {"module": module, "function": function, "syntaxKinds": [kind],
            "phase": phase, "source_sha": digest}


def _needs(kind, detail):
    return {"kind": kind, "status": "REQUIRED", "detail": detail}


_CODE = "Static compiler output must preserve filename/options, positions, constants and code layout; no execution or loaded-code claim."
_ADAPTER = "Existing producer/validator requires code_evidence; a normal static compiler adapter is required, not a fabricated captured witness."


def _rule(node):
    """Return real producer, selected caps and source-checkable shape boundary."""
    caps, needs, unsupported = [], [], None
    module, function = "structured_lowering", "StructuredBuilder.expr"
    compiler = False
    if isinstance(node, _FUNCS):
        module, function = "source_function_definition_lowering", "lower_function_definition"
        caps, compiler = [C.NESTED_FUNCTION_314_V1], True
        if isinstance(node, ast.AsyncFunctionDef) or node.decorator_list or getattr(node, "type_params", ()) or any(x is not None for x in node.args.kw_defaults):
            unsupported = "Nested creation currently rejects async/decorators/type parameters/keyword defaults (compiler_plan)."
    elif isinstance(node, ast.ClassDef):
        return "environment_lowering", "StructuredEnvironmentBuilder.statements", caps, needs, "Nested class construction has no structured-environment statement adapter."
    elif isinstance(node, ast.Lambda):
        module, function = "source_lambda_lowering", "lower_lambda"
        caps, compiler = [C.LAMBDA_EXPRESSION_314_V1], True
        needs.append(_needs("STATIC_CHILD_CODE_AND_CELLS", "Use this lambda's exact child code/constants and closure layout; do not substitute parent co_consts."))
    elif isinstance(node, _COMPS):
        module, function = "source_comprehension_lowering", "lower_comprehension"
        caps, compiler = [C.COMPREHENSION_314_V1], True
        from scar.analysis.source_comprehension_lowering import shape
        if node.generators and not isinstance(node.generators[0].target,ast.Name):
            caps.extend((C.COMPREHENSION_TARGETS_314_V1,C.FUNCTION_TRY_314_V1))
        if not shape(node,recursive_targets=True):
            unsupported = "Current comprehension shape requires one synchronous clause, recursive Tuple/List-to-Name target, no filters/nesting/walrus/suspension."
        needs.append(_needs("COMPREHENSION_LOCAL_SCOPE_AND_UNWIND", "Recursive target bindings use original comprehension slots; failed partial unpack preserves earlier writes, releases local references and forwards original propagation/world to enclosing cleanup."))
    elif isinstance(node, ast.GeneratorExp):
        module, function = "source_generator_creation_lowering", "lower_creation"
        caps, compiler = [C.GENEXPR_CREATION_314_V1], True
        if len(node.generators) != 1 or node.generators[0].is_async or node.generators[0].ifs or not isinstance(node.generators[0].target, ast.Name):
            unsupported = "Generator creation requires one synchronous clause, Name target and no filters."
        needs.append(_needs("STATIC_CHILD_CODE_AND_CELLS", "Creation and lazy body remain distinct; child .0/freevars/constant slot must match. Drive/close are not selected by creation."))
    elif isinstance(node, ast.Set):
        module, function = "source_set_lowering", "lower_set_display"
        caps, compiler = [C.SET_DISPLAY_314_V1], True
        if not 0 < len(node.elts) <= 30 or any(isinstance(x, ast.Starred) for x in node.elts):
            unsupported = "Set display requires 1..30 non-starred elements."
    elif isinstance(node, (ast.Tuple, ast.List)) and isinstance(node.ctx, ast.Store):
        module, function = "source_unpack_lowering", "lower_unpack_target"
        caps, compiler = [C.UNPACK_TARGETS_314_V1], True
        if any(isinstance(x, ast.Starred) for x in ast.walk(node)):
            unsupported = "Unpack target star binding has no current target adapter."
        needs.append(_needs("STATIC_BINDING_CLASSIFICATION", "Name leaves must resolve to original local/cell/global slots; heap leaves obey _check and exact ordered compiler consumption."))
    elif isinstance(node, (ast.Tuple, ast.List)) and any(isinstance(x, ast.Starred) for x in node.elts):
        module, function = "source_display_lowering", "lower_starred_display"
        caps, compiler = [C.STARRED_DISPLAY_314_V1], True
        if len(node.elts) > 30:
            unsupported = "Current starred display supports at most 30 elements."
    elif isinstance(node, ast.Call):
        if any(isinstance(x, ast.Starred) for x in node.args) or any(x.arg is None for x in node.keywords):
            module, function = "source_call_lowering", "lower_kwargs_call"
            caps, compiler = [C.CALL_KWARGS_314_V1, C.CALL_EXPANSION_314_V1], True
            needs.append(_needs("STATIC_CALL_FUNCTION_EX_SEQUENCE", "Validate exact call position, ordered positional/keyword runs, merge and release protocol; dict display update is a different rule."))
    elif isinstance(node, ast.Constant):
        value = node.value
        if not (value is None or type(value) in (bool, int, str) or type(value) is float and math.isfinite(value)):
            module, function = "source_constant_lowering", "lower_code_constant"
            caps, compiler = [C.CODE_CONSTANTS_314_V1], True
            needs.append(_needs("STATIC_CODE_CONSTANT_SLOT", "Exact original LOAD_CONST position/index/content is required; no active object identity is inferred."))
        else:
            module, function = "program_lowering", "_Builder.expr"
    elif isinstance(node, ast.Name):
        module, function = "environment_lowering", "StructuredEnvironmentBuilder.read_source_name" if isinstance(node.ctx, ast.Load) else "StructuredEnvironmentBuilder.store"
        if isinstance(node.ctx, ast.Del):
            unsupported = "General Delete has no structured statement rule."
    elif isinstance(node, (ast.Attribute, ast.Subscript)) and isinstance(node.ctx, ast.Store):
        module, function = "source_heap_lowering", "store_heap_target"
        if isinstance(node, ast.Attribute) and node.attr.startswith("__") and not node.attr.endswith("__"):
            unsupported = "Private heap assignment requires an unavailable exact compiler-class mangling rule."
        if isinstance(node, ast.Subscript) and isinstance(node.slice, ast.Slice):
            caps.append(C.SLICE_ACCESS_314_V1)
            compiler = True
        elif isinstance(node, ast.Subscript) and any(isinstance(child, ast.Slice) for child in ast.walk(node.slice)):
            caps.append(C.SLICE_ACCESS_314_V1)
            compiler = True
    elif isinstance(node, ast.Slice) or isinstance(node, ast.Subscript):
        module = "source_slice_lowering"
        function = "lower_slice" if isinstance(node, ast.Slice) else "lower_subscript"
        # Ordinary non-tuple keys never call _instructions. Slice and extended
        # tuple keys do; capability presence alone is not a compiler dependency.
        compiler = isinstance(node, ast.Slice) or isinstance(node.slice, (ast.Slice, ast.Tuple))
        if isinstance(node, ast.Subscript) and isinstance(node.slice, ast.Slice):
            caps.append(C.SLICE_ACCESS_314_V1)
        if isinstance(node, ast.Subscript) and isinstance(node.slice, ast.Slice) and node.slice.step is None and not all(x is None or isinstance(x, ast.Constant) for x in (node.slice.lower, node.slice.upper)):
            needs.append(_needs("STATIC_SLICE_SEQUENCE", "Compiler must select a supported BINARY_SLICE/BUILD_SLICE protocol; source shape alone cannot decide."))
    elif isinstance(node, ast.Dict):
        module, function = "source_mapping_lowering", "lower_dictionary"
    elif isinstance(node, ast.JoinedStr):
        module, function = "source_string_lowering", "lower_joined_string"
        if len(node.values) > 30:
            unsupported = "Incremental f-string list/append/join for more than 30 pieces is not implemented."
    elif isinstance(node, ast.FormattedValue):
        module, function = "source_string_lowering", "_formatted_value"
        if node.conversion not in (-1, 115, 114, 97):
            unsupported = "Unknown f-string conversion protocol."
    elif isinstance(node, (ast.BoolOp, ast.IfExp)):
        module = "source_conditional_lowering"
        function = "lower_bool_expression" if isinstance(node, ast.BoolOp) else "lower_if_expression"
    elif isinstance(node, (ast.BinOp, ast.UnaryOp, ast.Attribute, ast.Tuple, ast.List)):
        pass
    elif isinstance(node, ast.Compare):
        if len(node.ops) != 1:
            unsupported = "Current StructuredBuilder.expr has no chained comparison lowering."
    elif isinstance(node, ast.Try):
        module = "source_function_try_lowering"
        function = "FunctionTryBuilder.try_except" if node.handlers else "FunctionTryBuilder.try_finally"
        caps = [C.FUNCTION_TRY_314_V1]
        if (node.handlers and node.finalbody or not (node.handlers or node.finalbody)
                or any(x is not node and isinstance(x, (ast.Try, ast.TryStar, ast.Yield, ast.YieldFrom, ast.Await)) for x in ast.walk(node))):
            unsupported = "_try_shape rejects nested/combined try and nested yield/await transfers."
        needs.append(_needs("PAIRED_EXCEPTION_AND_CLEANUP_PROTOCOL", "Reuse existing C0/C1 pending, current propagation packet and namespace cleanup; no runtime traceback observation is asserted."))
    elif isinstance(node, ast.With):
        module, function = "source_with_lowering", "FunctionWithBuilder.with_statement"
        caps, compiler = [C.FUNCTION_TRY_314_V1, C.FUNCTION_WITH_314_V1], True
        if len(node.items) != 1:
            unsupported = "Current with_shape accepts exactly one synchronous item."
        needs.append(_needs("CLEANUP_CONTEXT_CHECK", "Current with_statement rejects nesting inside an active cleanup/try corridor; enclosing syntax must be checked."))
    elif isinstance(node, ast.AugAssign):
        module, function = "source_function_try_lowering", "FunctionTryBuilder.augmented_assignment"
        caps = [C.FUNCTION_TRY_314_V1]
        if isinstance(node.target, (ast.Attribute, ast.Subscript)):
            caps.append(C.HEAP_AUGASSIGN_314_V1)
            if isinstance(node.target, ast.Subscript) and isinstance(node.target.slice, ast.Slice):
                unsupported = "SLICE_AUGASSIGN_LIFETIME_UNRECOVERED"
            if isinstance(node.target, ast.Attribute) and node.target.attr.startswith("__") and not node.target.attr.endswith("__"):
                unsupported = "Private augmented attribute requires exact compiler-class mangling."
        else:
            needs.append(_needs("ORDINARY_LOCAL_AUGASSIGN_TARGET", "Name target must be an ordinary local, not cell/global; heap target retains its receiver/key once."))
    elif isinstance(node, (ast.Import, ast.ImportFrom)):
        module, function = "source_import_lowering", "lower_import"
        caps, compiler = [C.FUNCTION_IMPORT_314_V1], True
        if any(x.name == "*" for x in node.names) or isinstance(node, ast.Import) and any("." in x.name and x.asname for x in node.names):
            unsupported = "Current import rule rejects star binding and dotted Import with alias traversal."
        needs.append(_needs("STATIC_IMPORT_BINDING_LAYOUT", "Current producer requires exact fast-local, non-cell stores; source/import candidates do not prove loaded ModuleObject."))
    elif isinstance(node, (ast.AnnAssign, ast.Assert, ast.Raise)):
        module = "source_statement_lowering"
        function = {ast.AnnAssign: "annotated_assignment", ast.Assert: "assert_statement", ast.Raise: "raise_statement"}[type(node)]
        if isinstance(node, ast.Assert):
            needs.append(_needs("COMPILER_OPTIMIZE_ZERO", "Assertion lowering is conditional on compile optimize=0."))
        if isinstance(node, ast.AnnAssign):
            needs.append(_needs("ANNOTATION_SCOPE_POLICY", "Local annotation declaration and target side effects are separate from version-dependent thunk execution."))
    elif isinstance(node, (ast.If, ast.While, ast.For, ast.Assign, ast.Expr, ast.Return, ast.Pass, ast.Break, ast.Continue)):
        function = "StructuredBuilder.statements"
        if isinstance(node, ast.Assign) and len(node.targets) != 1:
            unsupported = "Current structured assignment accepts a single target."
    elif isinstance(node, (ast.Global, ast.Nonlocal)):
        module, function = "environment_lowering", "StructuredEnvironmentBuilder.statements"
    elif isinstance(node, _METADATA):
        module, function = "environment_lowering", "dispatch_source_expression"
        needs.append(_needs("OWNING_CONSTRUCT_PROTOCOL", "Auxiliary syntax belongs to its enclosing call/import/handler/entry; it is not an independent operation."))
    elif isinstance(node, ast.Starred):
        module, function = "environment_lowering", "dispatch_source_expression"
        needs.append(_needs("OWNING_EXPANSION_PROTOCOL", "Starred marker is consumed by the selected call/display/target producer; its value expression is planned separately."))
    else:
        module, function = "environment_lowering", "dispatch_source_expression"
        unsupported = "No current structured-environment producer for " + type(node).__name__
    if compiler:
        needs.extend((_needs("STATIC_COMPILER_CODE", _CODE), _needs("STATIC_COMPILER_EVIDENCE_ADAPTER", _ADAPTER)))
    return module, function, caps, needs, unsupported


def plan_static_entry(tree, entry, *, path, fingerprint):
    """Select actual rules for one original lexical entry; never lower it."""
    if type(tree) is not ast.Module or type(entry) is not dict:
        raise TypeError("static rules require original AST and catalog entry")
    if entry.get("path") != path or entry.get("fingerprint") != fingerprint:
        raise ValueError("entry source identity differs")
    node = _at_path(tree, entry["ast_path"])
    kind, phase = entry["kind"], entry["phase"]
    mapping_entry = kind == "MODULE" and isinstance(node, ast.Module)
    class_entry = kind == "CLASS" and isinstance(node, ast.ClassDef)
    selected = (FrameBodyProfile.STRUCTURED_MAPPING_COMPILER_OPS_314_V1.value if mapping_entry else
                "STATIC_CLASS_SUITE_METHOD_314_V1" if class_entry else
                BodyLoweringProfile.STRUCTURED_ENV.value if kind == "FUNCTION" else None)
    caps, rules = list(_DEFAULT_CAPS), []

    def add(n, ast_path, module, function, chosen=(), needs=(), unsupported=None, status=None):
        for cap in chosen:
            if cap not in caps:
                caps.append(cap)
        prerequisites = list(needs)
        state = status or ("UNSUPPORTED_SHAPE" if unsupported else "NEEDS_STATIC_COMPILER" if any(
            item["kind"].startswith("STATIC_COMPILER") or item["kind"] == "STATIC_CODE_CONSTANT_SLOT"
            for item in prerequisites) else "READY")
        rules.append({"rule_key": ast_path + "::" + phase + "::" + function,
                      "ast_path": ast_path, "syntax_kind": type(n).__name__, "phase": phase,
                      "status": state, "capabilities": [cap.value for cap in chosen],
                      "rule_references": [_reference(module, function, type(n).__name__, phase)],
                      "prerequisites": prerequisites, "unsupported_shape": unsupported,
                      "open_relations": ["CALLEE_TARGETS", "FINE_STATE_EFFECTS", "REFERENCE_ALIAS"]
                      if isinstance(n, (ast.Call, ast.Attribute, ast.Subscript, ast.BinOp, ast.UnaryOp)) else []})

    base_needs = [_needs("ORIGINAL_SOURCE_CONTEXT", "Original source/namespace and SG/semantics/CFG mapping must be normally constructed; no dynamic evidence is implied.")]
    if mapping_entry:
        caps = []  # Module mapping protocols do not use function fast-local capabilities.
        base_needs.append(_needs("STATIC_COMPILER_MODULE_ROOT", "Compile retained text without exec; use the original MODULE initializer, empty compiler path and a source-compilation frame root, never CapturedCode."))
        base_needs.append(_needs("MAPPING_PREFIX_AND_RESIDUAL", "Mechanically select the supported ordered mapping prefix; keep the exact remaining source slice as REQUIRED_EXPANSION with its original namespace and CFG."))
        add(node, entry["ast_path"], "source_module_lowering", "lower_module_entry",
            needs=base_needs, status="NEEDS_STATIC_COMPILER")
        roots = [(child, f"{entry['ast_path']}.body[{index}]") for index, child in enumerate(node.body)]
    elif class_entry:
        caps=[]
        base_needs.append(_needs("STATIC_COMPILER_CLASS_LAYOUT", "Original ClassDef child code determines outer freevar inputs, local compiler cell roles and Python-reference normal payload; no runtime class or prepared namespace is established."))
        base_needs.append(_needs("CLASS_BODY_REQUIRED_EXPANSION", "Preserve every original class-scope statement and compiler-owned cell stage; parent class construction and body internals remain distinct open relations."))
        add(node,entry["ast_path"],"source_class_body_lowering","lower_class_suite",needs=base_needs,
            status="ENTRY_ADAPTER_MISSING" if node.type_params else "NEEDS_STATIC_COMPILER")
        if node.type_params:
            rules[0]["prerequisites"].append(_needs("TYPE_PARAMETER_CLASS_ENTRY_ADAPTER", "Generic parameter scope needs its exact parent compiler-code adapter; do not guess a same-name child."))
        roots=[]  # Class body is explicitly retained by its required-expansion record, not function-frame dispatch.
    elif kind == "FUNCTION" and isinstance(node, ast.FunctionDef):
        base_needs.append(_needs("STATIC_COMPILER_ENVIRONMENT_LAYOUT", "build_function checks symtable against exact compiled freevars/cellvars and qualified body layout; existing fallback is compiler_environment_layout."))
        add(node, entry["ast_path"], "environment_lowering", "StructuredEnvironmentBuilder.build_function", needs=base_needs)
        roots = [(child, f"{entry['ast_path']}.body[{index}]") for index, child in enumerate(node.body)]
    else:
        module, function = ("source_module_lowering", "lower_module_entry") if kind == "MODULE" else ("environment_lowering", "StructuredEnvironmentBuilder.build_function")
        base_needs.append(_needs("PURE_STATIC_ENTRY_ADAPTER", "Existing function adapter rejects async/yield bodies; module has partial mapping profiles, class/annotation/type and standalone expression scopes need their exact entry adapter. Enclosing-body expression producers remain reusable."))
        add(node, entry["ast_path"], module, function, needs=base_needs, status="ENTRY_ADAPTER_MISSING")
        # Rules below remain requirements for a missing entry adapter, not
        # permission to give a mapping/class frame the function environment ABI.
        roots = ([(child, f"{entry['ast_path']}.body[{index}]") for index, child in enumerate(node.body)]
                 if kind in {"MODULE", "CLASS", "ASYNC_FUNCTION"} and isinstance(node, (ast.Module, ast.ClassDef, ast.AsyncFunctionDef)) else [])
    if isinstance(node, ast.FunctionDef) and getattr(node, "type_params", ()):
        rules[0]["prerequisites"].append(_needs("TYPE_PARAMETER_ENTRY_ADAPTER", "Generic function type-parameter scope must be mapped explicitly before using this function ABI."))
        rules[0]["status"] = "ENTRY_ADAPTER_MISSING"
    comp_targets=set()
    for root,root_path in roots:
        for child,_ in _owned(root,root_path):
            if isinstance(child,_COMPS) and child.generators:
                comp_targets.update(id(n) for n in ast.walk(child.generators[0].target))
    for root, root_path in roots:
        for child, child_path in _owned(root, root_path):
            if isinstance(child, (ast.stmt, ast.expr, ast.Slice, *_METADATA)):
                if mapping_entry:
                    add(child, child_path, "source_module_lowering", "mapping_prefix_selection",
                        needs=[_needs("MAPPING_PREFIX_ADMISSION", "This predicate checks exact source/compiler mapping in source order; unsupported suffix members remain typed residual source, not function-frame operations.")],
                        status="REQUIRES_MAPPING_SELECTION")
                    continue
                if id(child) in comp_targets:
                    chosen=[C.COMPREHENSION_314_V1]
                    # Target-tree syntax is consumed by its owning comp. It
                    # must not accidentally select the outer-frame unpack ABI.
                    add(child,child_path,"source_comprehension_lowering","lower_comprehension",chosen,
                        [_needs("COMPREHENSION_OWNED_TARGET", "Original target occurrence belongs to its comprehension scope; the owning producer binds its original slots once.")])
                    continue
                module, function, chosen, needs, unsupported = _rule(child)
                if selected is None:
                    # A function-frame predicate cannot reject or admit a
                    # module/class mapping-frame construct. Preserve the real
                    # reusable producer and declare the missing relation.
                    needs.append(_needs("FRAME_DISPATCH_ADAPTER", "Referenced rule is a function-body implementation candidate; mapping/async frame ports and dispatch must be supplied independently."))
                    add(child, child_path, module, function, chosen, needs,
                        status="ENTRY_ADAPTER_MISSING")
                else:
                    add(child, child_path, module, function, chosen, needs, unsupported)
    if C.FUNCTION_TRY_314_V1 in caps and C.COMPREHENSION_314_V1 in caps:
        if C.COMPREHENSION_TARGETS_314_V1 not in caps:caps.append(C.COMPREHENSION_TARGETS_314_V1)
        for rule in rules:
            if rule["syntax_kind"] in {"ListComp","SetComp","DictComp"}:
                for cap in (C.COMPREHENSION_TARGETS_314_V1,C.FUNCTION_TRY_314_V1):
                    if cap.value not in rule["capabilities"]:rule["capabilities"].append(cap.value)
    statuses = {rule["status"] for rule in rules}
    status = next((value for value in ("ENTRY_ADAPTER_MISSING", "UNSUPPORTED_SHAPE", "NEEDS_STATIC_COMPILER") if value in statuses), "READY")
    if any(rule["syntax_kind"] in {"Yield", "YieldFrom", "Await"} for rule in rules):
        status = "ENTRY_ADAPTER_MISSING"
        rules[0]["prerequisites"].append(_needs("RESUMABLE_ENTRY_ADAPTER", "Ordinary function build_function explicitly rejects generator/async body activation; creation capability is not a body driver."))
    requirements = [{**need, "rule_key": rule["rule_key"], "ast_path": rule["ast_path"]}
                    for rule in rules for need in rule["prerequisites"]]
    refs = {}
    for rule in rules:
        for ref in rule["rule_references"]:
            refs[(ref["module"], ref["function"], tuple(ref["syntaxKinds"]), ref["phase"])] = ref
    return {"schema": "scar.static-entry-rules", "schema_version": 1,
            "entry_key": entry["entry_key"], "kind": kind, "path": path, "fingerprint": fingerprint,
            "selected_profile": selected, "automatic_source_profile": _AUTO_PROFILE,
            "capabilities": [cap.value for cap in caps], "status": status,
            "rules": rules, "rule_references": list(refs.values()), "prerequisites": requirements,
            "unsupported_shapes": [{"rule_key": rule["rule_key"], "ast_path": rule["ast_path"],
                                     "detail": rule["unsupported_shape"]} for rule in rules if rule["unsupported_shape"]],
            "body_lowered": False, "whole_body_support_established": False,
            "policy_reference": _reference("static_rules", "plan_static_entry", type(node).__name__, phase),
            "selection_scope": "ORIGINAL_LEXICAL_OWNER_WITH_DEFERRED_CHILD_BODIES_SEPARATE"}


__all__ = ["plan_static_entry"]
