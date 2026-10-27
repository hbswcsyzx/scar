"""Conditional source ports from the linker's same fresh input session.

No operand load window is invented. Raw attempts/handshakes select entries;
normal source/code/body readers supply the ordered static Use/formal endpoints.
"""
from __future__ import annotations

import ast
from collections import defaultdict
import dis
import inspect

from scar.analysis.call_edges import _Sources
from scar.analysis.call_operand_reader import CallOperandTrace
from scar.analysis.call_operand_routes import _Core, _Boundary as _CoreBoundary, _has_index, _layout_matches, _span
from scar.analysis.function_binding import bind_call
from scar.ir.program.call_edges import CallEdgeModel, CallLinkStatus, CapturedSite
from scar.ir.program.call_operands import CALL_WINDOWS_RULE, LOAD_OCCURRENCES_RULE, LEAN_PORTS_RULE, PROGRAM_PORTS_RULE, PROCESS_PORTS_RULE, OperandScopedGap, CallableKind
from scar.ir.program.functions import ArgumentKind, BindingOrigin, CallArgument, CallBindingStatus, ParameterKind
from scar.ir.program.model import ReferenceValue, StateVersionValue, TerminatorKind, UseRole
from scar.ir.program.providers import ProviderArtifact, ProviderFactReference
from scar.ir.program.source_call_bindings import (
    SourceArgumentPort, SourceBodyNamespace, SourceCallPortBinding, SourceCallPortBudget,
    SourceCallPortIssue, SourceCallPortModel, SourcePortIssueKind as Issue,
)
from scar.ir.program.source_references import SourceArtifactLocator
from scar.ir.record_codec import decode, encode
from scar.ir.v2.common import SourceReference
from scar.trace.code_snapshot import site as code_site


class _Boundary(Exception):
    def __init__(self, kind, detail):
        self.kind, self.detail = kind, detail


def _need(condition, kind, detail):
    if not condition:
        raise _Boundary(kind, detail)


def _exact_function_dispatch(attempt, callee_code, code_key):
    # monitoring CALL arg0 is the first argument (or MISSING for zero
    # arguments), not an implicit-receiver flag. Arity is checked below
    # against the AST, CALL instruction and actual entry layout together.
    _need(attempt.dispatch.kind is CallableKind.EXACT_FUNCTION and attempt.dispatch.code == code_key
          and _layout_matches(attempt.dispatch.layout, callee_code),
          Issue.DISPATCH_BOUNDARY, "exact current function/code/layout required")


class _Session:
    def __init__(self, call_model, operand_model, inventory, sources):
        if (type(call_model) is not CallEdgeModel or type(operand_model) is not CallOperandTrace
                or type(sources) is not _Sources or sources.inventory is not inventory):
            raise TypeError("source ports require the matching normal call/operand/source session")
        self.model, self.operands, self.sources = call_model, operand_model, sources
        self.core = _Core(sources)
        self.edges = {e.entry.invocation: e for e in call_model.edges}
        self.handshakes = defaultdict(list)
        for h in operand_model.handshakes:
            self.handshakes[h.process_id, h.attempt_index].append(h)
        self.rules, self.bad_processes = {}, set()
        for meta in operand_model.metadata:
            if meta.process_id in self.rules or meta.errors or meta.io_failed or meta.dropped_events or meta.previous_profile:
                self.bad_processes.add(meta.process_id)
            self.rules[meta.process_id] = meta.rule
        self.local_gaps, self.global_gaps, self.read_issues = defaultdict(list), defaultdict(list), defaultdict(list)
        for gap in operand_model.gaps:
            if type(gap) is OperandScopedGap and gap.invocation is None:
                # The code is observed, but no invocation ID was issued. Mark
                # only that code's activations; do not fabricate an owner or
                # turn the missing local region into a process-wide gap.
                for invocation, edge in self.edges.items():
                    if invocation.process_id == gap.process_id and edge.entry.code == gap.code:
                        self.local_gaps[invocation].append(gap.index)
            else:
                target = self.global_gaps[gap.process_id] if gap.invocation is None else self.local_gaps[gap.invocation]
                target.append(gap.index)
        for item in operand_model.issues:
            if item.invocation is None:
                self.bad_processes.add(item.process_id)
            elif item.anchor is not None:
                self.read_issues[item.invocation].append(item.anchor.index)
        for table in (self.local_gaps, self.global_gaps, self.read_issues):
            for values in table.values():
                values.sort()
        self.instructions, self.namespaces, self.formals, self.use_sources = {}, {}, {}, {}

    def namespace(self, definition):
        if definition in self.namespaces:
            return self.namespaces[definition]
        access = self.sources.source_access
        _need(access is not None and access.bound and definition in access.selected,
              Issue.BODY_NAMESPACE_UNAVAILABLE, "body has no original qualified partition/namespace")
        fi, bi = access.selected[definition]
        attachment = access.composition.document["files"][fi]["bodies"][bi]
        bundle = access.bundle(definition)  # The normal accessor caches its checked original body.
        locator, namespace = attachment["graph_locator"], attachment["namespace"]
        _need(type(locator) is dict and set(locator) == {"artifact", "pointer", "namespace"}
              and type(namespace) is dict and set(namespace) == {"artifact", "representation", "record_pointer", "body"}
              and locator["namespace"] == namespace == bundle.namespace,
              Issue.BODY_NAMESPACE_UNAVAILABLE, "original body graph namespace is absent or unsupported")
        a = locator["artifact"]
        _need(type(a) is dict and set(a) == {"uri", "physical_sha256", "physical_bytes", "decoded_sha256", "decoded_bytes", "representation"},
              Issue.BODY_NAMESPACE_UNAVAILABLE, "original body artifact descriptor is unsupported")
        plain = (a["physical_sha256"], a["physical_bytes"]) == (a["decoded_sha256"], a["decoded_bytes"])
        _need(plain or (a["representation"] in ("scar.body-construction-checkpoint/1", "scar.source-program/5")
                        and a["uri"].endswith(".json.gz")),
              Issue.BODY_NAMESPACE_UNAVAILABLE, "original body encoding has no explicit supported contract")
        receipt = access.composition.index_receipt
        declaration = ProviderFactReference(ProviderArtifact(receipt["path"], receipt["raw_sha256"],
            receipt["raw_bytes"], "scar.program-composition"), f"#/files/{fi}/bodies/{bi}/graph_locator")
        graph = SourceArtifactLocator(ProviderArtifact(a["uri"], a["physical_sha256"], a["physical_bytes"], a["representation"]),
            a["decoded_sha256"], a["decoded_bytes"], "canonical-json" if plain else "gzip-canonical-json",
            locator["pointer"], declaration)
        body = namespace["body"]
        _need(type(body) is dict and set(body) == {"definition", "source", "entry"},
              Issue.BODY_NAMESPACE_UNAVAILABLE, "unsupported original body namespace identity")
        value = SourceBodyNamespace(graph, namespace["representation"], definition,
            None if body["source"] is None else decode(SourceReference, body["source"]),
            body["entry"], bundle.body.graph.root)
        _need(value.original_namespace() == namespace and body["definition"] == encode(definition)
              and bundle.body.definition == definition, Issue.BODY_NAMESPACE_UNAVAILABLE,
              "qualified body definition/namespace differs")
        self.namespaces[definition] = value
        return value

    def bind(self, attempt):
        sources = self.sources
        _need(self.rules.get(attempt.process_id) in (LOAD_OCCURRENCES_RULE, CALL_WINDOWS_RULE, LEAN_PORTS_RULE, PROGRAM_PORTS_RULE, PROCESS_PORTS_RULE)
              and attempt.process_id not in self.bad_processes, Issue.CAPTURE_GAP,
              "unsupported/lost/failed/interposed operand capture process")
        matches = self.handshakes[attempt.process_id, attempt.index]
        _need(len(matches) == 1, Issue.HANDSHAKE_BOUNDARY, "attempt has no unique real entry handshake")
        handshake, = matches
        callee, caller = self.edges.get(handshake.invocation), self.edges.get(attempt.invocation)
        _need(callee is not None and caller is not None and callee.caller_identity_verified
              and callee.entry.caller_invocation == attempt.invocation
              and callee.entry.anchor.index == handshake.entry_index
              and caller.entry.anchor.index <= attempt.frame_index < handshake.entry_index
              and handshake.thread_id == attempt.thread_id and handshake.hook_epoch == attempt.hook_epoch,
              Issue.HANDSHAKE_BOUNDARY, "handshake does not identify this direct caller/entry interval")
        _need(len(callee.path) == 1 and callee.path[0].site == attempt.site
              and callee.path[0].status is caller.target.status is callee.target.status is CallLinkStatus.VERIFIED
              and callee.path[0].core_operation is not None
              and caller.target.definition in sources.core and callee.target.definition in sources.core
              and callee.target.definition in sources.ports,
              Issue.SOURCE_CORE_BOUNDARY, "direct source/core call and both original bodies are required")
        call = callee.path[0]
        _need(call.execution_owner == caller.target.definition,
              Issue.SOURCE_CORE_BOUNDARY, "CALL owner is not the actual caller code definition")
        _need(attempt.site.code in sources.objects and callee.entry.code in sources.objects,
              Issue.CODE_WITNESS_UNAVAILABLE, "current complete caller/callee CodeWitness is unavailable")
        caller_code, callee_code = sources.objects[attempt.site.code], sources.objects[callee.entry.code]
        _exact_function_dispatch(attempt, callee_code, callee.entry.code)
        suspended = inspect.CO_GENERATOR | inspect.CO_COROUTINE | inspect.CO_ASYNC_GENERATOR
        layout = attempt.dispatch.layout
        _need(not layout.flags & (suspended | inspect.CO_VARARGS | inspect.CO_VARKEYWORDS)
              and layout.kwonlyargcount == 0 and not caller_code.co_flags & suspended
              and not caller.entry.suspended and not callee.entry.suspended,
              Issue.DISPATCH_BOUNDARY, "variadic/keyword-only/suspended frame is outside this positional rule")
        for table, key in ((self.global_gaps, attempt.process_id), (self.local_gaps, attempt.invocation),
                           (self.local_gaps, handshake.invocation), (self.read_issues, attempt.invocation),
                           (self.read_issues, handshake.invocation)):
            _need(not _has_index(table.get(key, ()), attempt.index, handshake.index), Issue.CAPTURE_GAP,
                  "capture/reader gap occurs during this call-to-entry interval")
        node = sources.node(call.source)
        _need(isinstance(node, ast.Call) and not node.keywords and not any(isinstance(a, ast.Starred) for a in node.args),
              Issue.DISPATCH_BOUNDARY, "only explicit positional arguments are supported")
        _need(layout.argcount == len(node.args) and callee.entry.parameters_complete
              and tuple(p.name for p in callee.entry.parameters) == layout.parameters,
              Issue.DISPATCH_BOUNDARY, "arity or captured entry parameters differ from actual layout")
        if attempt.site.code not in self.instructions:
            self.instructions[attempt.site.code] = {i.offset: i for i in dis.get_instructions(caller_code)}
        instruction = self.instructions[attempt.site.code].get(attempt.site.offset)
        _need(instruction is not None and instruction.opname == "CALL" and instruction.arg == len(node.args)
              and attempt.site.position == _span(node)
              and decode(CapturedSite, code_site(caller_code, attempt.site.offset)) == attempt.site,
              Issue.CALL_INSTRUCTION_BOUNDARY, "complete CALL n/position differs from current CodeWitness/source")
        definition = callee.target.definition
        if definition not in self.formals:
            self.formals[definition] = self.core.formal_ports(definition)
        signature, formals = sources.signatures[definition], self.formals[definition]
        _need(tuple(p.name for p in signature.parameters) == layout.parameters
              and all(p.kind in (ParameterKind.POSITIONAL_ONLY, ParameterKind.POSITIONAL) for p in signature.parameters),
              Issue.SOURCE_CORE_BOUNDARY, "normal formal signature/layout differs")
        body, operations, uses, _ = sources.core[call.execution_owner]
        operation = operations[call.core_operation]
        _need(operation.terminator is not None and operation.terminator.kind is TerminatorKind.INVOKE
              and len(operation.invoke_arguments) == len(node.args) + 2
              and operation.invoke_arguments[0] == call.callee_use
              and uses[call.callee_use].value == call.callee_value,
              Issue.SOURCE_CORE_BOUNDARY, "normal CALL needs exact callee/actual/world Use partition")
        values = self.core.values(call.execution_owner)
        world = uses[operation.invoke_arguments[-1]]
        _need(world.role is UseRole.STATE_CONTENT and type(values.get(world.value)) is StateVersionValue
              and all(type(values.get(uses[u].value)) is ReferenceValue for u in operation.invoke_arguments[:-1]),
              Issue.SOURCE_CORE_BOUNDARY, "normal CALL reference/world roles differ")
        if call.execution_owner not in self.use_sources:
            grouped = defaultdict(list)
            for link in body.metadata.use_links:
                grouped[link.operation, link.use].append(link.source)
            self.use_sources[call.execution_owner] = grouped
        actuals = []
        for index, argument in enumerate(node.args):
            use = operation.invoke_arguments[index + 1]
            source = sources.source(call.source.path, argument)
            _need(self.use_sources[call.execution_owner][operation.id, use] == [source],
                  Issue.SOURCE_CORE_BOUNDARY, "actual Use is not the unique indexed expression occurrence")
            actuals.append(CallArgument(index, source, ArgumentKind.POSITIONAL, use=use))
        candidate = bind_call(signature, call=call.call, target=definition, source=call.source, arguments=tuple(actuals))
        _need(candidate.status is CallBindingStatus.CONDITIONAL
              and all(r.origin is BindingOrigin.ARGUMENT for r in candidate.routes),
              Issue.BINDING_INCOMPLETE, "normal source signature binding " + candidate.status.value
              + ": " + ",".join(i.kind.value for i in candidate.issues))
        caller_namespace, callee_namespace = self.namespace(call.execution_owner), self.namespace(definition)
        routes = {r.slot: r for r in candidate.routes}
        ports = tuple(SourceArgumentPort(index, caller_namespace, operation.id, actual.source, actual.use,
            uses[actual.use].value, callee_namespace, parameter.slot, formal.value, parameter.name, routes[parameter.slot])
            for index, (actual, parameter, formal) in enumerate(zip(actuals, signature.parameters, formals)))
        return SourceCallPortBinding(attempt.anchor, handshake.anchor, callee.entry.anchor,
            attempt.invocation, callee.entry.invocation, caller.target, callee.target, call,
            caller_namespace, callee_namespace, candidate, ports)


def build_source_call_port_bindings(*, call_model, operand_model, inventory, sources,
                                    budget=SourceCallPortBudget(), consumer=None):
    """Same session only; every original attempt retains a binding or an issue."""
    if type(budget) is not SourceCallPortBudget:
        raise TypeError("typed source-port budget required")
    budget.__post_init__()
    if len(operand_model.attempts) > budget.max_attempts:
        raise ValueError("complete attempt denominator exceeds source-port budget")
    session = _Session(call_model, operand_model, inventory, sources)
    bindings, issues, port_count = [], [], 0
    for attempt in operand_model.attempts:
        try:
            binding = session.bind(attempt)
            _need(len(bindings) < budget.max_bindings and port_count + len(binding.ports) <= budget.max_ports,
                  Issue.BUDGET, "source-port output budget exhausted; this attempt remains unbound")
            bindings.append(binding); port_count += len(binding.ports)
        except (_Boundary, _CoreBoundary) as error:
            kind = error.kind if type(error) is _Boundary else Issue.SOURCE_CORE_BOUNDARY
            issues.append(SourceCallPortIssue(kind, attempt.anchor, attempt.invocation, error.detail))
    model = SourceCallPortModel(budget, len(operand_model.attempts), tuple(bindings), tuple(issues))
    if consumer is not None:
        if not callable(consumer):
            raise TypeError("source-port consumer must be callable")
        attempts = {attempt.anchor: attempt for attempt in operand_model.attempts}

        def check(binding):
            # Ephemeral verifier over these same already-read inputs; never a
            # serialized token, user resolver or reconstructed raw/live owner.
            if type(binding) is not SourceCallPortBinding or binding.attempt not in attempts:
                raise ValueError("retained source binding has no original attempt")
            if session.bind(attempts[binding.attempt]) != binding:
                raise ValueError("retained source binding differs from original source/code/entry/ports")
            return binding

        consumer(model, check)
    return model


def validate_source_call_port_binding(binding, *, call_model, operand_model, inventory, sources):
    """Recheck one retained record against the same normal, already-read session."""
    if type(binding) is not SourceCallPortBinding:
        raise TypeError("typed source-call binding required")
    attempts = [a for a in operand_model.attempts if a.anchor == binding.attempt]
    if len(attempts) != 1:
        raise ValueError("retained source binding has no unique original attempt")
    rebuilt = _Session(call_model, operand_model, inventory, sources).bind(attempts[0])
    if rebuilt != binding:
        raise ValueError("retained source binding differs from normal source/code/entry/ports")
    return binding
