"""Safe, standalone CPython operand-evidence experiment; no SCAR imports.

Run in the lewm environment: python probe.py --out result.json
Only the embedded tiny fixtures execute. There is no ctypes/native stack access.
Before-LOAD namespace observations are explicitly not evaluated stack operands.
"""
from __future__ import annotations

import argparse
import ast
import dis
import functools
import hashlib
import json
import os
from pathlib import Path
import sys
import sysconfig
import threading
from types import CodeType, FunctionType, MethodType, ModuleType


HELPER = """\
def identity(value):
    return value
def relay(value):
    return identity(value)
def raw_target(self, value=None):
    return self
def replacement(self, value=None):
    return value
class Holder:
    pass
Holder.method = raw_target
"""
ENTRY = """\
from c1_helper_fixture import relay
def name_call(fn, value):
    return fn(value)
def attr_call(receiver, value):
    return receiver.method(value)
def run(left, right):
    first = relay(left)
    second = relay(right)
    return first
selected = replacement = None
def mutate_selected(value):
    global selected
    selected = replacement
    return value
def global_rebind(value):
    return selected(mutate_selected(value))
def local_rebind(fn, other, value):
    return fn((fn := other), value)
"""
CONDITIONS = [
    {"condition": "NO_FRAME_INTERPOSITION", "status": "UNKNOWN"},
    {"condition": "NO_UNMODELED_NAMESPACE_MUTATION_BETWEEN_OBSERVATION_AND_LOAD", "status": "UNKNOWN"},
    {"condition": "OBSERVER_CALLBACKS_DO_NOT_REPLACE_VALUES_OR_CONTROL", "status": "UNKNOWN"},
]


def span(node):
    return [node.lineno, node.end_lineno, node.col_offset, node.end_col_offset]


def position(instruction):
    p = instruction.positions
    return [p.lineno, p.end_lineno, p.col_offset, p.end_col_offset]


class Identities:
    """Bounded fixture-only strong identities; never serialized memory addresses."""
    def __init__(self):
        self.objects = []

    def ref(self, value):
        for index, previous in enumerate(self.objects):
            if previous is value:
                return "ref:" + str(index + 1)
        self.objects.append(value)
        if len(self.objects) > 4096:
            raise ValueError("fixture reference ceiling exceeded")
        return "ref:" + str(len(self.objects))


class Probe:
    def __init__(self, modules, sources):
        self.ids = Identities()
        self.sources, self.codes, self.instructions, self.calls = sources, {}, {}, {}
        for module in modules:
            for value in module.__dict__.values():
                if type(value) is FunctionType and value.__code__.co_filename in sources:
                    code = value.__code__
                    self.codes[code] = self.code(code)
                    self.instructions[code] = {i.offset: i for i in dis.get_instructions(code)}
        for filename, text in sources.items():
            self.calls[filename] = {tuple(span(node)): node for node in ast.walk(ast.parse(text))
                                    if isinstance(node, ast.Call)}
        self.case = None
        self.invocations, self.active, self.loads, self.writes, self.pending = {}, {}, {}, {}, {}
        self.events, self.attempts, self.routes, self.counter = [], [], [], 0
        self.observer_mode = "monitoring_py_start_return"

    def code(self, code):
        return {"ref": self.ids.ref(code), "filename": code.co_filename,
                "qualname": code.co_qualname, "first_line": code.co_firstlineno,
                "bytecode_sha256": hashlib.sha256(code.co_code).hexdigest(),
                "positions_sha256": hashlib.sha256(code.co_linetable).hexdigest()}

    def shape(self, value):
        result = {"ref": self.ids.ref(value), "exact_type": type(value).__name__}
        if type(value) is FunctionType:
            code = value.__code__
            result.update(code=self.code(code), positional_formals=list(code.co_varnames[:code.co_argcount]),
                          keyword_only=code.co_kwonlyargcount, variadic=bool(code.co_flags & 12),
                          defaults=[self.ids.ref(v) for v in (value.__defaults__ or ())],
                          closure_names=list(code.co_freevars))
        elif type(value) is MethodType:
            result.update(function=self.shape(value.__func__), receiver=self.ids.ref(value.__self__))
        elif type(value) is functools.partial:
            result.update(function=self.shape(value.func), args=[self.ids.ref(v) for v in value.args],
                          keyword_names=[key for key in value.keywords if type(key) is str])
        return result

    def event(self, kind, **fields):
        row = {"index": len(self.events) + 1, "case": self.case, "kind": kind,
               "process_id": os.getpid(), "thread_id": threading.get_ident(), **fields}
        self.events.append(row)
        if len(self.events) > 4096:
            raise ValueError("fixture event ceiling exceeded")
        return row

    def local_instruction(self, code, offset):
        if code not in self.codes:
            return
        frame = sys._getframe(1)
        assert frame.f_code is code
        owner = self.active[id(frame)]
        instruction = self.instructions[code][offset]
        row = self.event("INSTRUCTION", owner=owner, code=self.codes[code]["ref"], offset=offset,
                         opcode=instruction.opname, argument=instruction.argval,
                         position=position(instruction))
        name = instruction.argval
        if any(part in instruction.opname for part in ("STORE_FAST", "STORE_DEREF", "DELETE_FAST", "DELETE_DEREF")):
            names = (name,) if type(name) is str else name if type(name) is tuple else ()
            # Fused store/load variants have no validated suboperand rule here;
            # conservatively stop treating every named slot as an unchanged
            # entry formal rather than inventing a formal origin.
            self.writes[owner].update(item for item in names if type(item) is str)
        namespace = None
        if instruction.opname in ("LOAD_FAST", "LOAD_FAST_BORROW", "LOAD_FAST_CHECK") and type(name) is str:
            namespace, mapping = "FAST_LOCAL", frame.f_locals
        elif instruction.opname == "LOAD_GLOBAL" and type(name) is str:
            if name in frame.f_globals:
                namespace, mapping = "GLOBAL", frame.f_globals
            elif name in frame.f_builtins:
                namespace, mapping = "BUILTIN", frame.f_builtins
        if namespace is not None and name in mapping:
            observation = {"event": row["index"], "owner": owner, "name": name,
                           "namespace": namespace, "position": row["position"], "offset": offset,
                           "observed_before_load": self.shape(mapping[name]),
                           "evaluated_operand_observed": False,
                           "unchanged_formal_slot": namespace == "FAST_LOCAL" and name not in self.writes[owner]
                               and name in self.invocations[owner]["parameters"]}
            self.loads[owner].append(observation)
            row["namespace_observation"] = observation

    def call_event(self, code, offset, callable_object, arg0):
        if code not in self.codes:
            return
        frame = sys._getframe(1)
        assert frame.f_code is code
        owner = self.active[id(frame)]
        instruction = self.instructions[code][offset]
        node = self.calls[code.co_filename].get(tuple(position(instruction)))
        row = self.event("CALL", owner=owner, code=self.codes[code]["ref"], offset=offset,
                         normalized_callable=self.shape(callable_object),
                         arg0={"missing": arg0 is sys.monitoring.MISSING,
                               "ref": None if arg0 is sys.monitoring.MISSING else self.ids.ref(arg0)})
        attempt = {"event": row["index"], "owner": owner, "code": row["code"], "offset": offset,
                   "callee_source": span(node.func) if node is not None else None,
                   "normalized_callable": row["normalized_callable"], "arg0": row["arg0"],
                   "callee_load": None, "actual_loads": [], "boundary": None,
                   "routing_status": "UNSUPPORTED_SCOPE", "conditions": CONDITIONS}
        def loaded(expression):
            if not isinstance(expression, ast.Name):
                return None
            candidates = [item for item in self.loads[owner] if item["position"] == span(expression)
                          and item["name"] == expression.id]
            return candidates[-1] if candidates else None
        if node is None:
            attempt["boundary"] = "NO_UNIQUE_SOURCE_CALL"
        elif not isinstance(node.func, ast.Name):
            attempt["boundary"] = "CALLEE_RESULT_NOT_EXPOSED_BY_PUBLIC_INSTRUCTION_EVENT"
        else:
            attempt["callee_load"] = loaded(node.func)
            if attempt["callee_load"] is None:
                attempt["boundary"] = "CALLEE_LOAD_NOT_CAPTURED"
            elif any(not isinstance(arg, ast.Name) for arg in node.args) or node.keywords:
                attempt["boundary"] = "ACTUALS_OUTSIDE_EXPLICIT_NAME_LOAD_SCOPE"
            else:
                attempt["actual_loads"] = [loaded(arg) for arg in node.args]
                raw = attempt["callee_load"]["observed_before_load"]
                if raw["exact_type"] != "function":
                    attempt["boundary"] = "RAW_CALLEE_IS_ADAPTER_OR_OTHER_CALLABLE"
                elif raw["ref"] != row["normalized_callable"]["ref"]:
                    attempt["boundary"] = "LOAD_OBSERVATION_AND_NORMALIZED_CALLABLE_DISAGREE"
                elif any(item is None or item["namespace"] != "FAST_LOCAL" for item in attempt["actual_loads"]):
                    attempt["boundary"] = "ACTUAL_LOAD_NOT_CAPTURED_OR_NOT_FAST_LOCAL"
                elif raw["variadic"] or raw["keyword_only"] or len(raw["positional_formals"]) != len(node.args):
                    attempt["boundary"] = "ADAPTER_DEFAULT_PACK_OR_KEYWORD_STATE_WOULD_BE_REQUIRED"
                else:
                    attempt["routing_status"] = "CONDITIONAL_LOAD_AND_BIND_RULE"
        # Deliberately diagnostic only: this demonstrates why rereading a Name
        # at CALL cannot substitute for its earlier evaluated operand.
        if node is not None and isinstance(node.func, ast.Name):
            mapping = frame.f_locals if node.func.id in frame.f_locals else frame.f_globals
            if node.func.id in mapping:
                attempt["diagnostic_current_name_at_call"] = self.shape(mapping[node.func.id])
        self.attempts.append(attempt)
        self.pending[owner] = attempt

    def profile(self, frame, event, arg):
        if frame.f_code not in self.codes:
            return
        if event == "call":
            self.counter += 1
            owner = self.counter
            self.active[id(frame)] = owner
            self.loads[owner], self.writes[owner] = [], set()
            code = frame.f_code
            names = code.co_varnames[:code.co_argcount + code.co_kwonlyargcount]
            parameters = {name: self.ids.ref(frame.f_locals[name]) for name in names if name in frame.f_locals}
            parent = self.active.get(id(frame.f_back))
            row = self.event("FRAME_ENTER", observer=self.observer_mode,
                             owner=owner, parent=parent, code=self.codes[code]["ref"],
                             qualname=code.co_qualname, parameters=parameters)
            self.invocations[owner] = row
            attempt = self.pending.pop(parent, None)
            if attempt is None:
                return
            normalized = attempt["normalized_callable"]
            function = normalized.get("function", normalized)
            if function.get("code", {}).get("ref") != self.codes[code]["ref"]:
                attempt["entry_handshake"] = "CODE_MISMATCH"
                return
            attempt["entry_handshake"] = {"owner": owner, "event": row["index"], "code": row["code"]}
            if attempt["routing_status"] != "CONDITIONAL_LOAD_AND_BIND_RULE":
                return
            raw = attempt["callee_load"]["observed_before_load"]
            for index, (name, occurrence) in enumerate(zip(raw["positional_formals"], attempt["actual_loads"])):
                # Position supplies provenance; equality checks the proposed
                # route and never chooses among equal-reference candidates.
                agrees = parameters.get(name) == occurrence["observed_before_load"]["ref"]
                self.routes.append({"attempt": attempt["event"], "actual_index": index,
                    "source": {"owner": parent, "load_event": occurrence["event"],
                               "name": occurrence["name"], "position": occurrence["position"],
                               "formal_origin": occurrence["name"] if occurrence["unchanged_formal_slot"] else None},
                    "destination": {"owner": owner, "formal": name},
                    "reference_consistency": agrees,
                    "status": "CONDITIONAL" if agrees else "CONTRADICTED",
                    "unconditional_verified": False, "conditions": CONDITIONS,
                    "contents_or_effects_established": False})
        elif event == "return":
            owner = self.active.pop(id(frame))
            self.event("FRAME_RETURN", observer=self.observer_mode,
                       owner=owner, code=self.codes[frame.f_code]["ref"],
                       return_ref=self.ids.ref(arg),
                       completion_established=self.observer_mode == "monitoring_py_start_return")
            self.pending.pop(owner, None)

    def paths(self, case):
        routes = [route for route in self.routes if route["status"] == "CONDITIONAL"
                  and self.invocations[route["destination"]["owner"]]["case"] == case]
        by_destination = {(route["destination"]["owner"], route["destination"]["formal"]): route for route in routes}
        used_as_origin = {(route["source"]["owner"], route["source"]["formal_origin"])
                          for route in routes if route["source"]["formal_origin"] is not None}
        paths = []
        for route in routes:
            start = route["destination"]
            if (start["owner"], start["formal"]) in used_as_origin:
                continue
            current, path = (start["owner"], start["formal"]), []
            while current in by_destination:
                edge = by_destination[current]
                path.append({"destination": edge["destination"], "source": edge["source"]})
                origin = edge["source"]["formal_origin"]
                if origin is None:
                    break
                current = edge["source"]["owner"], origin
            paths.append({"from": start, "path": path, "endpoint": {"owner": current[0], "name": current[1]},
                          "status": "CONDITIONAL", "unconditional_verified": False})
        return paths


def header_evidence():
    root = Path(sysconfig.get_path("include"))
    requested = {
        "cpython/monitoring.h": ("_PyMonitoring_FireCallEvent", "PyObject* callable, PyObject *arg0"),
        "internal/pycore_instruments.h": ("_Py_call_instrumentation_instruction",),
        "internal/pycore_interpframe_structs.h": ("Py_BUILD_CORE", "f_funcobj", "stackpointer", "localsplus"),
        "internal/pycore_opcode_metadata.h": ("[CALL_BOUND_METHOD_EXACT_ARGS] = {", "[CALL_PY_EXACT_ARGS] = {"),
        "cpython/pyframe.h": ("PyFrame_GetVar", "PyFrame_GetLasti"),
    }
    evidence = []
    for name, terms in requested.items():
        path = root / name
        raw = path.read_bytes()
        lines = raw.decode().splitlines()
        evidence.append({"path": str(path), "sha256": hashlib.sha256(raw).hexdigest(),
                         "matches": [{"line": i + 1, "text": line} for i, line in enumerate(lines)
                                     if any(term in line for term in terms)]})
    return evidence


def profile_compatibility(function, argument_function, value):
    """A separate exact comparison; no production assumptions from headers."""
    matrix = []
    old_profile = sys.getprofile()
    assert old_profile is None, "run this experiment without another profile observer"
    for order in ("monitor_only", "monitor_then_profile", "profile_then_monitor"):
        # Fresh ordinary code objects prevent one trial's instrumentation state
        # from leaking into the next trial or the real fixture protocol below.
        caller = FunctionType(function.__code__.replace(), function.__globals__)
        callee = FunctionType(argument_function.__code__.replace(), argument_function.__globals__)
        observed = []
        def instruction(code, offset):
            observed.append({"kind": "INSTRUCTION", "offset": offset})
        def call(code, offset, callable_object, arg0):
            observed.append({"kind": "CALL", "offset": offset})
        def profile(frame, event, arg):
            if frame.f_code in (caller.__code__, callee.__code__):
                observed.append({"kind": "PROFILE", "function": frame.f_code.co_qualname, "event": event})
        tool = next(i for i in range(6) if sys.monitoring.get_tool(i) is None)
        sys.monitoring.use_tool_id(tool, "c1-profile-compatibility")
        try:
            if order == "profile_then_monitor":
                sys.setprofile(profile)
            sys.monitoring.register_callback(tool, sys.monitoring.events.CALL, call)
            sys.monitoring.register_callback(tool, sys.monitoring.events.INSTRUCTION, instruction)
            sys.monitoring.set_local_events(tool, caller.__code__,
                sys.monitoring.events.CALL | sys.monitoring.events.INSTRUCTION)
            if order == "monitor_then_profile":
                sys.setprofile(profile)
            caller(callee, value)
        finally:
            sys.setprofile(old_profile)
            sys.monitoring.free_tool_id(tool)
        matrix.append({"order": order, "events": observed,
                       "instruction_count": sum(row["kind"] == "INSTRUCTION" for row in observed),
                       "call_count": sum(row["kind"] == "CALL" for row in observed)})
    assert matrix[0]["instruction_count"] > 0
    assert matrix[1]["instruction_count"] == 0 and matrix[1]["call_count"] == 1
    assert matrix[2]["instruction_count"] > 0 and matrix[2]["call_count"] == 1
    return matrix


def main():
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--out", type=Path, default=Path(__file__).with_name("result.json"))
    args = parser.parse_args()
    directory = Path(__file__).resolve().parent
    helper_path, entry_path = directory / "helper_fixture.py", directory / "entry_fixture.py"
    helper_path.write_text(HELPER); entry_path.write_text(ENTRY)
    modules, previous = [], sys.modules.get("c1_helper_fixture")
    for name, path, text in (("c1_helper_fixture", helper_path, HELPER), ("c1_entry_fixture", entry_path, ENTRY)):
        module = ModuleType(name); module.__file__ = str(path)
        exec(compile(text, str(path), "exec", dont_inherit=True), module.__dict__)
        modules.append(module)
        if name == "c1_helper_fixture":
            sys.modules[name] = module
    helper, entry = modules
    shared, left, right = helper.Holder(), helper.Holder(), helper.Holder()
    helper.raw_target.__defaults__ = (shared,)
    bound = MethodType(helper.raw_target, shared)
    partial = functools.partial(helper.raw_target, shared)
    # Warm only safe fixture calls; specialization is recorded but never used
    # as evidence of the next execution's original callable shape.
    for _ in range(128):
        entry.name_call(bound, shared); entry.attr_call(shared, shared)
    before_disassembly = {fn.__name__: [{"offset": i.offset, "opcode": i.opname, "argument": i.argrepr}
                                       for i in dis.get_instructions(fn, adaptive=True)]
                          for fn in (entry.name_call, entry.attr_call)}
    compatibility = profile_compatibility(entry.name_call, helper.identity, shared)
    probe = Probe(modules, {str(helper_path): HELPER, str(entry_path): ENTRY})
    probe.observer_mode = "sys_setprofile_installed_before_monitoring"
    tool = next(i for i in range(6) if sys.monitoring.get_tool(i) is None)
    old_profile = sys.getprofile()
    cases = [
        ("raw_default_alias", lambda: entry.name_call(helper.raw_target, shared)),
        ("name_bound_alias", lambda: entry.name_call(bound, shared)),
        ("optimized_attr_bound_alias", lambda: entry.attr_call(shared, shared)),
        ("partial_alias", lambda: entry.name_call(partial, shared)),
        ("two_file_distinct", lambda: entry.run(left, right)),
        ("two_file_shared", lambda: entry.run(shared, shared)),
        ("global_rebind_during_argument", lambda: entry.global_rebind(shared)),
        ("local_rebind_during_argument", lambda: entry.local_rebind(helper.raw_target, helper.replacement, shared)),
    ]
    sys.monitoring.use_tool_id(tool, "scar-c1-safe-operand-audit")
    # On this runtime order is material: install profile before configuring
    # INSTRUCTION instrumentation. The compatibility matrix tests both orders
    # using fresh code objects, avoiding stale instrumentation contamination.
    sys.setprofile(probe.profile)
    sys.monitoring.register_callback(tool, sys.monitoring.events.INSTRUCTION, probe.local_instruction)
    sys.monitoring.register_callback(tool, sys.monitoring.events.CALL, probe.call_event)
    for code in probe.codes:
        sys.monitoring.set_local_events(tool, code, sys.monitoring.events.INSTRUCTION | sys.monitoring.events.CALL)
    try:
        for name, action in cases:
            probe.case = name
            entry.selected, entry.replacement = helper.raw_target, helper.replacement
            action()
    finally:
        sys.setprofile(old_profile)
        sys.monitoring.free_tool_id(tool)
        if previous is None:
            sys.modules.pop("c1_helper_fixture", None)
        else:
            sys.modules["c1_helper_fixture"] = previous
    after_disassembly = {fn.__name__: [{"offset": i.offset, "opcode": i.opname, "argument": i.argrepr}
                                      for i in dis.get_instructions(fn, adaptive=True)]
                         for fn in (entry.name_call, entry.attr_call)}
    paths = {case: probe.paths(case) for case in ("two_file_distinct", "two_file_shared")}
    aliases = {}
    for case in ("raw_default_alias", "name_bound_alias", "optimized_attr_bound_alias", "partial_alias"):
        attempt = next(a for a in probe.attempts if probe.invocations[a["owner"]]["case"] == case
                       and probe.invocations[a["owner"]]["qualname"] in ("name_call", "attr_call"))
        entered = probe.invocations[attempt["entry_handshake"]["owner"]]
        aliases[case] = {"attempt": attempt["event"], "normalized": attempt["normalized_callable"],
                         "arg0": attempt["arg0"], "callee_load": attempt["callee_load"],
                         "parameters": entered["parameters"], "boundary": attempt["boundary"]}
    raw, method = aliases["raw_default_alias"], aliases["name_bound_alias"]
    assert raw["normalized"] == method["normalized"] and raw["arg0"] == method["arg0"]
    assert raw["parameters"] == method["parameters"]
    assert raw["callee_load"]["observed_before_load"]["exact_type"] == "function"
    assert method["callee_load"]["observed_before_load"]["exact_type"] == "method"
    for case, pair in paths.items():
        assert len(pair) == 2
        assert {item["endpoint"]["name"] for item in pair} == {"left", "right"}
        assert all(len(item["path"]) == 2 for item in pair)
    rebound = [a for a in probe.attempts if probe.invocations[a["owner"]]["qualname"] in ("global_rebind", "local_rebind")]
    rebound = [a for a in rebound if a["callee_load"] and a["callee_load"]["name"] in ("selected", "fn")]
    assert len(rebound) == 2
    assert all(a["callee_load"]["observed_before_load"]["ref"] == a["normalized_callable"]["ref"]
               != a["diagnostic_current_name_at_call"]["ref"] for a in rebound)
    result = {
        "schema": "scar.experiment.c1-operand-audit", "schema_version": 1,
        "python": sys.version, "process_id": os.getpid(), "thread_id": threading.get_ident(),
        "probe_sha256": hashlib.sha256(Path(__file__).read_bytes()).hexdigest(),
        "sources": [{"path": str(path), "sha256": hashlib.sha256(text.encode()).hexdigest()}
                    for path, text in ((helper_path, HELPER), (entry_path, ENTRY))],
        "headers": header_evidence(), "disassembly_before": before_disassembly,
        "profile_instruction_compatibility": compatibility,
        "disassembly_after": after_disassembly, "aliases": aliases, "conditional_paths": paths,
        "observed": [
            "raw FunctionType and Name-bound MethodType have identical normalized CALL callable/arg0 and entry parameter references",
            "pre-LOAD namespace observations distinguish raw function from Name-bound method",
            "optimized LOAD_ATTR reports normalized function plus receiver but does not expose its result operand",
            "exact partial remains visible as partial at CALL in this fixture",
            "global and local rebinding during argument evaluation leaves the previously loaded callable selected",
            "INSTRUCTION supplies code/offset, without an evaluated operand or full argument vector",
            "on fresh code objects monitor-then-profile loses INSTRUCTION callbacks, whereas profile-then-monitor preserves INSTRUCTION/CALL/profile delivery",
        ],
        "inferred": [
            "a versioned LOAD rule plus pre-load observation can construct conditional operand occurrences under explicit noninterposition conditions",
            "a raw FunctionType with all fixed formals supplied by explicit captured Name loads admits positional routes without consuming defaults",
            "route origin is instruction/source occurrence and actual index; equal object references only check consistency",
        ],
        "unsupported_scope": ["unconditional binding provenance", "arbitrary LOAD_ATTR/descriptor result",
                              "adapter/partial/receiver insertion", "default-state consumption", "stars/keywords/packing",
                              "fused loads without a validated suboperand rule", "native calls and child processes",
                              "incorrect observer installation order or missing per-instruction records",
                              "contents/effects/purity or permission to transform"],
        "observer_scope": "single process/thread; bounded tiny fixtures; strong fixture references affect lifetimes; no application or LeWM execution",
        "conditions": CONDITIONS, "events": probe.events, "attempts": probe.attempts,
        "minimum_protocol": {
            "scope": "raw FunctionType; callee LOAD_FAST/LOAD_GLOBAL; fixed positional formals all supplied by explicit FAST_LOCAL Name loads",
            "registration": "install sys.setprofile before local INSTRUCTION/CALL monitoring; check every required load event exists",
            "load_record": ["pid", "tid", "invocation", "code_fingerprint", "offset", "opcode",
                            "full_source_span", "namespace_kind", "slot", "occurrence_index",
                            "pre_load_shape", "pre_load_reference", "observation_is_not_stack_result"],
            "attempt_record": ["pid", "tid", "caller_invocation", "code_fingerprint", "CALL_offset",
                               "attempt_sequence", "callee_load_occurrence", "actual_load_occurrences_in_position_order",
                               "normalized_callable_reference", "normalized_callable_code", "arg0_or_missing"],
            "entry_record": ["pid", "tid", "invocation", "direct_parent_invocation", "entry_code",
                             "parameters", "matched_attempt", "capture_gaps"],
            "derivation": "versioned LOAD rule turns a pre-load namespace observation into a conditional operand occurrence; raw-function positional binding maps actual index to formal; observed CALL/entry checks consistency",
            "identity_policy": "reference equality rejects a contradicted proposed route; it never selects its origin",
            "state_policy": "default/receiver/partial consumption is a boundary; explicit formal routes do not establish closure/globals/content/effects",
            "gap_policy": "missing load/CALL/entry, duplicate or ambiguous attempts, truncation, code/source mismatch or a failed reference check stops that route",
            "production_code_identity": "use existing structural pycode-v2 plus verified current-source snapshot; this independent probe uses within-run code identity and bytecode/position hashes for diagnostics",
            "result_status": "CONDITIONAL; no unconditionally VERIFIED actual-to-formal provenance",
        },
        "conditional_routes": probe.routes, "unconditional_verified": False,
        "contents_or_effects_established": False, "transformation_authorized": False,
        "assertions": {"same_code_same_ref_ambiguity": True, "raw_name_shape_distinguished": True,
                       "two_file_distinct_paths": True, "two_file_shared_paths_not_selected_by_ref": True,
                       "global_and_local_rebinding_counterexamples": True},
    }
    args.out.parent.mkdir(parents=True, exist_ok=True)
    args.out.write_text(json.dumps(result, ensure_ascii=True, indent=2, allow_nan=False) + "\n")
    summary_path = args.out.with_name(args.out.stem + ".summary.json")
    summary = {key: result[key] for key in (
        "schema", "schema_version", "python", "probe_sha256", "sources", "observed", "inferred",
        "minimum_protocol", "conditions", "unsupported_scope", "observer_scope", "assertions",
        "unconditional_verified", "contents_or_effects_established", "transformation_authorized")}
    summary["counts"] = {"events": len(probe.events), "attempts": len(probe.attempts), "conditional_routes": len(probe.routes)}
    summary["installation_matrix"] = [{key: row[key] for key in ("order", "instruction_count", "call_count")}
                                      for row in compatibility]
    summary["conditional_paths"] = paths
    summary["full_result"] = {"path": str(args.out.resolve()),
                              "sha256": hashlib.sha256(args.out.read_bytes()).hexdigest()}
    summary_path.write_text(json.dumps(summary, ensure_ascii=True, indent=2, allow_nan=False) + "\n")
    print(json.dumps({"status": "OBSERVED_WITH_CONDITIONAL_PROTOCOL", "out": str(args.out.resolve()),
                      "summary": str(summary_path.resolve()),
                      "events": len(probe.events), "attempts": len(probe.attempts),
                      "conditional_routes": len(probe.routes), "assertions": result["assertions"],
                      "unconditional_verified": False, "transformation_authorized": False}))


if __name__ == "__main__":
    main()
