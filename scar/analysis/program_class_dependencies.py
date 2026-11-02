"""Project checked class interfaces into the shared dependency graph view.

There is no I/O, copied graph, invented callee definition, or private unbounded
graph cache here. The owning ProgramDependencySession resolves and checks the
original binding/provider/body receipts. Every edge retains those locators.
"""
from __future__ import annotations

from dataclasses import replace

from scar.ir.program.class_builder import (
    ClassBuilderProvider, ClassBuilderStageKind, StaticClassBuilderBinding,
)
from scar.ir.program.dependencies import (
    DependencyCondition, DependencyEdge, DependencyEvidence, DependencyFrame,
    DependencyFrontier, DependencyKind as K, DependencyMeaning as M,
    DependencyNeighborhood, DependencyPoint as Point, GraphNamespace,
)
from scar.ir.program.model import ExitKind, StateVersionValue, TerminatorKind
from scar.ir.program.source_references import SourceArtifactLocator
from scar.ir.program.source_subjects import ClassFrameABI


PROVIDER_REPRESENTATION = "scar.static-class-provider/1:ProgramGraph"


def class_provider_namespace(locator, provider):
    """Reference the existing embedded typed graph, without a SourceDefinition."""
    if type(locator) is not SourceArtifactLocator or type(provider) is not ClassBuilderProvider:
        raise TypeError("class provider namespace needs its original locator and typed provider")
    if locator.pointer != "#/provider":
        raise ValueError("class provider locator must select the original provider record")
    return GraphNamespace(replace(locator, pointer=locator.pointer + "/graph"),
                          PROVIDER_REPRESENTATION, provider.graph.root)


def class_dependency_frames(binding, provider, load_index):
    """Return the two original interface selections; these are not activations."""
    if type(binding) is not StaticClassBuilderBinding:
        raise TypeError("expected a checked original static class binding")
    parent = GraphNamespace.from_source(binding.parent)
    implementation = class_provider_namespace(binding.provider, provider)
    suite = GraphNamespace.from_source(binding.suite)
    parent_index = load_index(parent)
    call = binding.construction.builder_call
    callee = parent_index.use_site(call.callee)
    if callee.operation != call.operation:
        raise ValueError("class builder callable Use belongs to another operation")
    outer = DependencyFrame(parent, call.operation, call.callee, callee.use.value, implementation)
    stage = next(s for s in provider.stages if s.kind is ClassBuilderStageKind.EVAL_SUITE)
    provider_index = load_index(implementation)
    body_function = provider_index.use_site(stage.inputs[0])
    if body_function.operation != stage.operation:
        raise ValueError("class suite function Use belongs to another eval operation")
    inner = DependencyFrame(implementation, stage.operation, stage.inputs[0], body_function.use.value,
                            suite, binding.suite.definition)
    return parent, implementation, suite, outer, inner


class ClassDependencyProvider:
    """A lazy provider for parent -> native implementation -> shared suite.

    ``bindings_for(point)`` yields ``(StaticClassBuilderBinding, locator)``.
    The owning session must freshly validate that binding against its original
    graphs/provider before yielding it; ``locator`` selects ``#/bindings/N`` in
    the registered immutable relationship shard. ``load_index`` and
    ``load_provider`` share the session's bounded artifact/typed caches.
    """
    relation_kinds = frozenset((K.ARGUMENT, K.CALL_TARGET, K.COMPLETION, K.ENVIRONMENT,
        K.IMPLEMENTATION, K.STATE_INPUT, K.STATE_OUTPUT))

    def __init__(self, bindings_for, load_index, load_provider, *, coverage=None):
        if not all(callable(f) for f in (bindings_for, load_index, load_provider)):
            raise TypeError("class dependency provider requires session resolver callbacks")
        self.bindings_for, self.load_index, self.load_provider = bindings_for, load_index, load_provider
        if coverage is not None and not callable(coverage):
            raise TypeError("class coverage must be an original-interface resolver")
        self.coverage = coverage

    def incoming(self, point):
        return self._neighborhood(point, incoming=True)

    def outgoing(self, point):
        return self._neighborhood(point, incoming=False)

    def _neighborhood(self, point, *, incoming):
        if type(point) is not Point:
            raise TypeError("class dependency query needs a qualified DependencyPoint")
        edges, frontiers, bindings = [], [], []
        matched_context, unmatched_context = False, False
        for binding, locator in self.bindings_for(point):
            if type(binding) is not StaticClassBuilderBinding or type(locator) is not SourceArtifactLocator:
                raise TypeError("class resolver must yield original typed bindings with record locators")
            bindings.append(binding)
            provider = self.load_provider(binding.provider)
            parent, implementation, suite, outer, inner = class_dependency_frames(binding, provider, self.load_index)
            if point.namespace not in (parent, implementation, suite):
                continue
            context = point.context
            if context is None:
                frontiers.append(DependencyFrontier(point, "CLASS_INTERFACE_CONTEXT_UNKNOWN",
                    "The query has no selected interface stack; unknown is not a root activation."))
                continue
            if point.namespace == parent:
                parent_context = context
            elif point.namespace == implementation and context and context[-1] == outer:
                parent_context = context[:-1]
            elif point.namespace == suite and len(context) >= 2 and context[-2:] == (outer, inner):
                parent_context = context[:-2]
            else:
                # Another class can share the same provider graph and eval
                # operation. It must not inherit this binding's suite edges.
                unmatched_context = True
                continue
            if parent_context and parent_context[-1].target != parent:
                frontiers.append(DependencyFrontier(point, "CLASS_PARENT_CONTEXT_UNMATCHED",
                    "The enclosing interface stack does not enter this original parent graph."))
                continue
            matched_context = True
            generated, missing = self._edges(binding, locator, provider, parent, implementation, suite,
                                               outer, inner, parent_context)
            edges.extend(edge for edge in generated if (edge.target if incoming else edge.source) == point)
            frontiers.extend(f for f in missing if f.point == point)
        if unmatched_context and not matched_context:
            frontiers.append(DependencyFrontier(point, "CLASS_INTERFACE_CONTEXT_UNMATCHED",
                "This shared implementation/suite interface requires its original outer and inner selections."))
        if not matched_context:
            index = self.load_index(point.namespace)
            formals = ()
            is_class = False
            if point.namespace.representation == PROVIDER_REPRESENTATION:
                is_class = True
                region = index.regions[point.namespace.root]
                formals = next(b.arguments for b in region.blocks if b.id == region.entry)
            else:
                roots = [r for r in index.graph.frame_roots if type(r.entry) is ClassFrameABI]
                if roots:
                    is_class = True
                    mapping = roots[0].entry.mapping
                    formals = (mapping.locals_namespace, mapping.globals_namespace, mapping.builtins_namespace,
                               *mapping.closure_cells, mapping.world)
            if point.node in formals or is_class and point.node == point.namespace.root:
                kind = ("CLASS_INTERFACE_CONTEXT_UNKNOWN" if point.context is None else
                    "CLASS_INTERFACE_CONTEXT_UNBOUND" if not point.context else "CLASS_INTERFACE_CONTEXT_UNMATCHED")
                frontiers.append(DependencyFrontier(point, kind,
                    "An original class/provider entry has no matching selected enclosing builder interface."))
        enumerated = True
        if self.coverage is not None:
            scope = self.coverage(point, incoming=incoming, bindings=tuple(bindings))
            if type(scope) is not DependencyNeighborhood or scope.edges:
                raise TypeError("class coverage must return typed original-interface frontiers")
            frontiers.extend(scope.frontiers)
            enumerated = scope.enumerated
        return DependencyNeighborhood(tuple(dict.fromkeys(edges)), tuple(dict.fromkeys(frontiers)), enumerated)

    def _edges(self, binding, locator, provider, parent, implementation, suite, outer, inner, parent_context):
        contexts = {parent: parent_context, implementation: (*parent_context, outer),
                    suite: (*parent_context, outer, inner)}
        indexes = {ns: self.load_index(ns) for ns in (parent, implementation, suite)}
        edges, frontiers = [], []
        conditions = tuple(DependencyCondition.from_enum(guard) for guard in binding.guards)

        def point(ns, node):
            return Point(ns, node, contexts[ns])

        def evidence(path, *anchors):
            original = replace(locator, pointer=locator.pointer + path)
            return (DependencyEvidence("CLASS_ORIGINAL_INTERFACE_PORTS_V1",
                (original, parent.graph, implementation.graph, suite.graph), tuple(anchors)),)

        def add(source, target, kind, meaning, path, *anchors, extra_conditions=()):
            edges.append(DependencyEdge(source, target, kind, meaning, evidence(path, *anchors),
                                        (*conditions, *extra_conditions)))

        call = binding.construction.builder_call
        parent_call = point(parent, call.operation)
        parent_callee = point(parent, call.callee)
        add(parent_call, point(implementation, implementation.root), K.IMPLEMENTATION, M.STRUCTURE,
            "/construction/builder_call", parent_call, parent_callee)
        stage = next(s for s in provider.stages if s.kind is ClassBuilderStageKind.EVAL_SUITE)
        suite_call = point(implementation, stage.operation)
        suite_callee = point(implementation, stage.inputs[0])
        add(suite_call, point(suite, suite.root), K.CALL_TARGET, M.STRUCTURE,
            "/suite_inputs", suite_call, suite_callee)

        def input_edge(actual_namespace, target_namespace, mapping, path, *, environment=False):
            site = indexes[actual_namespace].use_site(mapping.actual_use)
            formal = indexes[target_namespace].values[mapping.formal]
            if site.use.value != mapping.actual_value:
                raise ValueError("class input mapping changed its original consumed value")
            state = isinstance(formal, StateVersionValue)
            kind = K.STATE_INPUT if state else K.ENVIRONMENT if environment else K.ARGUMENT
            meaning = M.STATE_INTERFACE if state else M.REFERENCE
            add(point(actual_namespace, mapping.actual_use), point(target_namespace, mapping.formal),
                kind, meaning, path, point(actual_namespace, site.operation))

        for i, mapping in enumerate(binding.inputs):
            input_edge(parent, implementation, mapping, "/inputs/" + str(i))
        for i, mapping in enumerate(binding.suite_inputs):
            input_edge(implementation, suite, mapping, "/suite_inputs/" + str(i), environment=True)

        def complete(source_namespace, target_namespace, route, exit_name, target_block, target_values, path):
            source_index, target_index = indexes[source_namespace], indexes[target_namespace]
            root = source_index.regions[source_namespace.root]
            declared = next((exit for exit in root.exits if exit.name == exit_name and exit.kind is route.kind), None)
            block = next((b for region in target_index.graph.regions for b in region.blocks if b.id == target_block), None)
            if declared is None or block is None or block.arguments != target_values or len(declared.types) != len(target_values):
                raise ValueError("class completion changed its original exit or landing ports")
            found = set()
            for source_block in root.blocks:
                for operation_id in source_block.operations:
                    op = source_index.operations[operation_id]
                    term = op.terminator
                    kind = (ExitKind.NORMAL if term is not None and term.kind is TerminatorKind.RETURN else
                            ExitKind.RAISE if term is not None and term.kind is TerminatorKind.RAISE else None)
                    if kind is not route.kind or term.exit != exit_name:
                        continue
                    if len(term.values) != len(target_values):
                        raise ValueError("class completion producer has another payload arity")
                    for ordinal, (use_id, value_id) in enumerate(zip(term.values, target_values)):
                        site = source_index.use_site(use_id)
                        if site.operation != operation_id:
                            raise ValueError("class completion payload Use belongs to another operation")
                        target = point(target_namespace, value_id)
                        is_state = isinstance(target_index.values[value_id], StateVersionValue)
                        add(point(source_namespace, use_id), target,
                            K.STATE_OUTPUT if is_state else K.COMPLETION,
                            M.STATE_INTERFACE if is_state else M.REFERENCE, path,
                            point(source_namespace, operation_id), point(target_namespace, target_block),
                            extra_conditions=(DependencyCondition("class.completion", route.kind.value,
                                point(source_namespace, operation_id), ordinal),))
                        found.add(ordinal)
            for ordinal, value in enumerate(target_values):
                if ordinal not in found:
                    frontiers.append(DependencyFrontier(point(target_namespace, value),
                        "CLASS_COMPLETION_SOURCE_OPEN", "No original terminating Use supplies this declared completion payload."))

        for i, route in enumerate(binding.suite_completions):
            complete(suite, implementation, route, route.suite_exit, route.provider_block, route.provider_values,
                     "/suite_completions/" + str(i))
        for i, route in enumerate(binding.completions):
            complete(implementation, parent, route, route.provider_exit, route.parent_block, route.parent_values,
                     "/completions/" + str(i))
        return edges, frontiers
