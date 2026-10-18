"""Shared original-port queries for the Program19 connection obligations.

The context is prepared only after canonical validation. Expected ports are
independent declarations; resolving the actual producer never selects one.
No result here grants runtime identity, source applicability or a rewrite.
"""
from scar.ir.execution.validity_budget import ValidityBudget

from .model import (BlockArgument, InvokeLiteralResult, OperationResult,
                    StateVersionValue, TerminatorKind)
from .protocol_flow import ProtocolFlow, ProtocolPort, ProtocolReferenceError
from .protocols import ContractResult, OwnedUse, StaticProtocolGap
from .state_addresses import ExistingAccess, InvokeStateOperand


def _answer(match=None, *, routes=(), gaps=(), cursor=None, conditions=()):
    return {"match": match, "routes": tuple(routes), "gaps": tuple(gaps),
            "cursor": cursor, "conditions": (
                "supplied-model ports only; source/native applicability unproved",
                "dynamic visit and value identity unproved", *conditions),
            "source_runtime_verified": False, "runtime_identity_verified": False,
            "transformation_authorized": False}


class ConnectionContext(ProtocolFlow):
    """One validated-core index, original flow and shared query budget."""

    def __init__(self, graph, *, index, budget=None):
        from .queries import ProgramIndex
        if type(index) is not ProgramIndex or index.graph is not graph:
            raise TypeError("connections require the exact prepared ProgramIndex")
        accounting = ValidityBudget(1000000) if budget is None else budget
        if type(accounting) is not ValidityBudget:
            raise TypeError("connections require one exact shared ValidityBudget")
        super().__init__(graph, budget=accounting)
        self.index = index
        self.call_inputs = {row.site: row for row in graph.protocol_call_inputs}
        self.result_consumers = {row.site: row for row in graph.protocol_result_consumers}
        self._connection_origins = {}
        self._connection_bindings = {}
        self._connection_reports = {}
        self.preparation["prepared_program_index_reused"] = True

    def row(self, site):
        from .protocol_connections import ProtocolOperationRef
        if type(site) is not ProtocolOperationRef:
            raise TypeError("connection site requires exact ProtocolOperationRef")
        site.__post_init__()
        row = self.rows.get((site.scope, site.clause, site.operation, site.slot))
        if row is None:
            raise ProtocolReferenceError("connection site must select an exact existing protocol row")
        return row

    def port(self, source, *, referring=None):
        if type(source) is not BlockArgument:
            return super().port(source, referring=referring)
        source.__post_init__()
        if not self.spend("ports"):
            return None
        if source not in self._ports:
            block = self.blocks.get(source.block)
            if block is None or source.index >= len(block.arguments):
                raise ProtocolReferenceError("expected formal is outside its original block")
            value = block.arguments[source.index]
            if self.values[value].origin != source:
                raise ProtocolReferenceError("expected formal must retain its original producer")
            self._ports[source] = ProtocolPort(source, block.operations[0], (value,), "before")
        return self._ports[source]

    def origins(self, actual, *, guard=None):
        """Original input recipes; caches are scoped to this shared budget."""
        from .input_origins import _input_origins_with_flow
        self.owned_use(actual.operation, actual.use)
        key = actual, guard
        if key not in self._connection_origins:
            self._connection_origins[key] = _input_origins_with_flow(
                self.index, actual.operation, actual.use,
                accounting=self.budget, _copy_flow=self, _guard=guard)
        return self._connection_origins[key]

    def request_binding(self, raw, input, ordinal=0, *, guard=None):
        from .request_inputs import request_input_binding
        return request_input_binding(self.index, raw, input, ordinal,
                                     accounting=self.budget, _flow=self, _guard=guard)

    def recipe_context(self, recipe):
        """Project original caller/CFG context without adding a copy relation."""
        from .request_inputs import _context
        calls, choices, rooted = _context(self.index, recipe, self.budget)
        return {"match": True if rooted and not self.budget.truncated else None,
                "context": calls, "choices": choices, "recipe": recipe,
                "rooted": rooted, "runtime_identity_verified": False,
                "gaps": () if rooted else ("static_caller_or_cfg_visit_context_unresolved",)}

    def correlate(self, *reports):
        """Join declared semantic projections on the same static context.

        Family resolvers provide independently established port/projection
        reports. This method checks context coherence, never invents a value
        equality or turns a semantic projection into an ordinary copy edge.
        """
        from .protocol_connection_validation import _joint_routes
        joined, gaps = _joint_routes(self, reports)
        complete = bool(reports) and all(report["match"] is True for report in reports)
        covered = {id(route) for row in joined for route in row["support"]}
        all_routes = tuple(route for report in reports for route in report["routes"]
                           if route.get("match") is True)
        full_coverage = all(id(route) in covered for route in all_routes)
        match = (False if any(report["match"] is False for report in reports) else
                 True if joined and complete and full_coverage else
                 False if not joined and complete and not self.budget.truncated else None)
        if not full_coverage:
            gaps += ("whole_input_tuple_context_coverage_unresolved",)
        return _answer(match, routes=joined, gaps=gaps,
                       cursor={"phase": "context_correlation"} if self.budget.truncated else None,
                       conditions=("context coherence does not establish projection semantics",))

    def extend_context(self, recipe, anchor, consumer_recipe):
        """Extend a source recipe along an independently selected caller path.

        Used for a declared request's latent/body projections. The anchor is
        an actual original Use; no RAW formal or semantic-copy fact is added.
        """
        from .request_inputs import _context, _helper_context_extension
        if type(anchor) is not OwnedUse:
            raise TypeError("context extension requires an exact original Use anchor")
        self.owned_use(anchor.operation, anchor.use)
        source_calls, source_choices, source_rooted = _context(self.index, recipe, self.budget)
        target_calls, target_choices, target_rooted = _context(self.index, consumer_recipe, self.budget)
        choices = {**source_choices, **target_choices}
        match, extension, gaps = None, None, ()
        if any(key in source_choices and source_choices[key] != value for key, value in target_choices.items()):
            match = False
        elif source_calls == target_calls and source_rooted and target_rooted:
            match = True
        elif source_rooted and target_rooted:
            extension = _helper_context_extension(self.index, self, anchor,
                source_calls, target_calls, self.budget)
            match = True if type(extension) is dict else extension
        if match is None:
            gaps = ("projection_caller_prefix_unresolved",)
        return {"match": match, "context": target_calls, "choices": choices,
                "recipe": recipe, "consumer_recipe": consumer_recipe,
                "anchor": anchor, "extension": extension, "gaps": gaps,
                "runtime_identity_verified": False, "transformation_authorized": False}

    def bind(self, expected, actual, *, guard=None, choices=(), path=""):
        """Tri-state exact copy/source check, preserving every known route.

        ``True`` is an original-port relation, not equality of dynamic objects.
        Mixed known routes stay partial, never an independent ANY success.
        """
        from .protocol_connections import RawOperandSource
        if type(choices) is not tuple:
            raise TypeError("additional original choices require an exact tuple")
        guard = self.selected_edges((*self.selected_edges(guard), *choices)) or None
        ambiguity = self.selection_ambiguity(guard)
        if ambiguity is not None:
            return _answer(gaps=(ambiguity["code"],))
        if type(actual) is not OwnedUse:
            raise TypeError("actual connection must be exact OwnedUse")
        destination = self.owned_use(actual.operation, actual.use)
        key = expected, actual, guard
        if key in self._connection_bindings:
            return self._connection_bindings[key]
        if not self.spend("connection_bindings"):
            return _answer(gaps=("protocol_connection_budget_exhausted",),
                           cursor={"path": path, "expected": expected, "actual": actual})
        if type(expected) is RawOperandSource:
            expected.__post_init__()
            from .protocol_validation import raw_definition
            definition = raw_definition(self, expected.raw)
            origin = None if definition is None else self.values[definition.value].origin
            if type(origin) is OperationResult and self.region_of[origin.operation] == self.region_of[actual.operation]:
                if expected.ordinal >= len(definition.operands):
                    answer = _answer(False, gaps=("request_ordinal_absent",))
                else:
                    operand = OwnedUse(origin.operation, definition.operands[expected.ordinal])
                    copied = self.bind(operand, actual, guard=guard, path=path)
                    current = self.available(expected.raw, actual.operation, guard=guard, path=path)
                    checks = (copied["match"], current["match"])
                    match = False if False in checks else None if None in checks else True
                    answer = _answer(match, routes=copied["routes"],
                        gaps=(*copied["gaps"], *current["gaps"]),
                        cursor=copied["cursor"] or current["cursor"])
            else:
                report = self.request_binding(expected.raw, actual, expected.ordinal, guard=guard)
                routes = tuple({"request_binding": row, "match": True,
                                "context": row["caller_context"],
                                "choices": dict(row["cfg_choices"])}
                               for row in report["bindings"])
                covered = {id(row["input_recipe"]) for row in report["bindings"]}
                complete = (report["cursor"] is None and report["input"]["recipes"]
                            and all(id(recipe) in covered for recipe in report["input"]["recipes"])
                            and all(recipe["freshness"] is True or recipe["freshness_target"] is None
                                for row in report["bindings"] for recipe in
                                (row["raw_recipe"], row["operand_recipe"], row["input_recipe"])))
                answer = _answer(True if routes and complete else None, routes=routes,
                                 gaps=report["gaps"], cursor=report["cursor"])
        else:
            port = self.port(expected)
            if port is None or port.gap is not None or port.operation is None:
                answer = _answer(gaps=(("expected_source_unresolved" if port is None
                                        else port.gap),))
            elif self.region_of[port.operation] == self.region_of[actual.operation]:
                future = (self.block_of[port.operation] == self.block_of[actual.operation]
                    and (self.positions[port.operation] > self.positions[actual.operation]
                         or (port.operation == actual.operation and port.phase != "before")))
                relevant = self.selected_edges(guard, region=self.region_of[port.operation]) or None
                before = {} if future else self._fresh_copies(port, guard=relevant)
                match = None if before is None else destination.value in before.get(actual.operation, ())
                answer = _answer(match, routes=({"source": expected, "actual": actual,
                    "guard": guard, "context": None, "choices": {}, "match": match},),
                    gaps=("protocol_connection_budget_exhausted",) if before is None else ())
            else:
                answer = self._bind_cross_region(expected, port, actual, guard=guard)
        self._connection_bindings[key] = answer
        return answer

    def available(self, expected, consumer, *, guard=None, path=""):
        """Source evaluation is available before an operation, without a fake operand.

        This is used for zero-argument request triggers. Cross-region support
        comes from real caller/actual/formal recipes of this consumer's inputs.
        Availability alone does not prove that a native call uses the request.
        """
        from .request_inputs import _context
        operation = self.operations.get(consumer)
        if operation is None:
            raise ProtocolReferenceError("availability consumer must be an original operation")
        ambiguity = self.selection_ambiguity(guard)
        if ambiguity is not None:
            return _answer(gaps=(ambiguity["code"],))
        port = self.port(expected)
        if port is None or port.operation is None or port.gap is not None:
            return _answer(gaps=("source_availability_unresolved",))
        source_region, target_region = self.region_of[port.operation], self.region_of[consumer]
        if source_region == target_region:
            future = (self.block_of[port.operation] == self.block_of[consumer]
                and (self.positions[port.operation] > self.positions[consumer]
                     or port.operation == consumer and port.phase != "before"))
            relevant = self.selected_edges(guard, region=source_region) or None
            flow = {} if future else self._fresh_copies(port, guard=relevant)
            match = None if flow is None else bool(flow.get(consumer, ()))
            return _answer(match, routes=({"source": expected, "consumer": consumer,
                "guard": guard, "context": None, "choices": {}, "match": match},),
                gaps=("source_availability_unresolved",) if match is None else (),
                conditions=("availability does not prove native request selection",))
        routes, gaps, cursor = [], [], None
        arguments = (operation.invoke_arguments if operation.terminator is not None
                     and operation.terminator.kind is TerminatorKind.INVOKE else
                     operation.call_arguments if operation.callee is not None else
                     tuple(use.id for use in operation.uses))
        for identity in arguments:
            value = self.values[self.owned_use(consumer, identity).value]
            if isinstance(value, StateVersionValue):
                continue
            report = self.origins(OwnedUse(consumer, identity), guard=guard)
            for recipe in report["recipes"]:
                if not self.spend("connection_available_routes"):
                    cursor = {"phase": "source_availability", "consumer": consumer, "path": path}
                    break
                calls, choices, _ = _context(self.index, recipe, self.budget)
                first = next((caller for caller, region, _ in calls if region == source_region), None)
                if first is None:
                    continue
                relevant = self.selected_edges(guard, region=source_region) or None
                flow = self._fresh_copies(port, guard=relevant)
                match = None if flow is None else bool(flow.get(first, ()))
                route = {"source": expected, "consumer": consumer, "context": calls,
                         "choices": choices, "match": match, "entry_call": first,
                         "recipe": recipe, "source_current_before_call": match}
                if not any(old["context"] == calls and old["choices"] == choices for old in routes):
                    routes.append(route)
            if report["cursor"] is not None:
                cursor = report["cursor"]
            if self.budget.truncated:
                break
        matches = tuple(route["match"] for route in routes)
        if matches and all(match is True for match in matches) and cursor is None:
            match = True
        elif matches and all(match is False for match in matches) and cursor is None:
            match = False
        else:
            match = None
            gaps.append("cross_region_source_availability_unresolved")
        return _answer(match, routes=routes, gaps=gaps, cursor=cursor,
                       conditions=("availability does not prove native request selection",))

    def _bind_cross_region(self, expected, port, actual, *, guard):
        """Follow original call/formal paths; never equate local reachability with global reachability."""
        from .request_inputs import _context
        report = self.origins(actual, guard=guard)
        routes, gaps = [], list(report["gaps"])
        for recipe in report["recipes"]:
            if not self.spend("connection_source_routes"):
                return _answer(routes=routes, gaps=(*gaps, "protocol_connection_budget_exhausted"),
                               cursor={"phase": "connection_source_routes", "actual": actual})
            calls, choices, _ = _context(self.index, recipe, self.budget)
            for selected in self.selected_edges(guard):
                applicable = [number for (_, operation), number in choices.items()
                              if operation == selected.operation]
                if applicable and selected.successor_index not in applicable:
                    break
            else:
                applicable = None
            if applicable is not None:
                continue
            leaf_match = recipe["leaf"].id in port.values
            formal_steps = tuple(step for step in recipe["path"]
                if step.get("kind") in ("CALL_ACTUAL_TO_FORMAL", "CFG_COPY")
                and getattr(step.get("formal"), "id", step.get("formal")) in port.values)
            anchored = leaf_match or bool(formal_steps)
            current = None
            if anchored and calls:
                first = next((caller for caller, region, _ in calls
                              if region == self.region_of[port.operation]), None)
                if first is not None:
                    future = (self.block_of[port.operation] == self.block_of[first]
                        and (self.positions[port.operation] > self.positions[first]
                             or port.operation == first and port.phase != "before"))
                    relevant = self.selected_edges(guard, region=self.region_of[port.operation]) or None
                    flow = {} if future else self._fresh_copies(port, guard=relevant)
                    current = (None if flow is None else
                               bool(set(port.values).intersection(flow.get(first, ()))))
            # A known foreign leaf is a mismatching route; an unsupported
            # return/opaque bridge cannot establish a positive copy relation.
            match = current if anchored else False
            routes.append({"source": expected, "actual": actual, "recipe": recipe,
                           "context": calls, "choices": choices, "match": match,
                           "formal_support": formal_steps})
        matches = tuple(route["match"] for route in routes)
        if matches and all(item is True for item in matches) and report["cursor"] is None:
            match = True
        elif matches and all(item is False for item in matches) and report["cursor"] is None:
            match = False
        else:
            match = None
            gaps.append("cross_region_source_routes_unresolved")
        return _answer(match, routes=routes, gaps=gaps, cursor=report["cursor"])

    def current(self, site, consumer, *, after=False, path=""):
        """Check the original state version at this consumer operation.

        The consumer may be a reference Use; its operation must still expose
        the corresponding canonical state input. No empty-support success.
        """
        self.owned_use(consumer.operation, consumer.use)
        operation = self.operations.get(site.operation)
        if operation is None:
            raise ProtocolReferenceError("state site operation does not exist")
        if type(site) is ExistingAccess:
            if site.index >= len(operation.accesses):
                raise ProtocolReferenceError("state site access does not exist")
            access = operation.accesses[site.index]
            before = self.owned_use(operation.id, access.before)
            location = access.location
            if after:
                if access.after is None:
                    return _answer(gaps=("state_site_has_no_after",))
                source = self.values[access.after].origin
            else:
                source = OwnedUse(operation.id, before.id)
        elif type(site) is InvokeStateOperand:
            before = self.owned_use(operation.id, site.state_use)
            if site.state_use not in operation.invoke_arguments:
                raise ProtocolReferenceError("state site must select actual invoke input")
            value = self.values[before.value]
            if not isinstance(value, StateVersionValue):
                raise ProtocolReferenceError("state site must carry canonical state")
            location, source = value.location, OwnedUse(operation.id, before.id)
            if after:
                return _answer(gaps=("invoke_after_requires_exact_completion_state_port",))
        else:
            raise TypeError("current state requires an exact state address site")
        target = self.operations[consumer.operation]
        uses = target.invoke_arguments if (target.terminator is not None and
            target.terminator.kind is TerminatorKind.INVOKE) else tuple(a.before for a in target.accesses)
        targets = tuple(OwnedUse(target.id, identity) for identity in uses
                       if isinstance(self.values[self.owned_use(target.id, identity).value], StateVersionValue)
                       and self.values[self.owned_use(target.id, identity).value].location == location)
        if not targets:
            return _answer(gaps=("consumer_current_state_input_unresolved",))
        reports = tuple(self.bind(source, actual, path=path) for actual in targets)
        matches = tuple(row["match"] for row in reports)
        match = False if False in matches else None if None in matches else True
        return _answer(match, routes=tuple(route for row in reports for route in row["routes"]),
                       gaps=tuple(gap for row in reports for gap in row["gaps"]))


__all__ = ["ConnectionContext"]
