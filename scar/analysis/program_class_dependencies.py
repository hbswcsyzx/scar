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
    DependencyNeighborhood, DependencyPoint as Point, DependencyStrength, GraphNamespace,
    context_frames, context_is_closed, context_push, context_pop,
)
from scar.ir.program.model import (CompletionResult, ExitKind, OperationResult,
    ReferenceValue, StateVersionValue, TerminatorKind)
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
            if point.namespace == parent:
                # An original parent port can project its explicitly supplied
                # guarded interfaces even with an unknown enclosing prefix.
                parent_context = context
            elif context is None:
                frontiers.append(DependencyFrontier(point, "CLASS_INTERFACE_CONTEXT_UNKNOWN",
                    "The query has no selected interface stack; unknown is not a root activation."))
                continue
            else:
                suffix=(outer,) if point.namespace==implementation else (outer,inner)
                popped=context_pop(context,suffix)
                if not popped.matched:
                    # Never consume an unknown prefix to complete a guessed
                    # selection of this shared provider/suite's creator.
                    unmatched_context=True;continue
                parent_context=popped.remaining
            parent_frames=context_frames(parent_context)
            if parent_frames and parent_frames[-1].target != parent:
                frontiers.append(DependencyFrontier(point, "CLASS_PARENT_CONTEXT_UNMATCHED",
                    "The enclosing interface stack does not enter this original parent graph."))
                continue
            matched_context = True
            generated, missing = self._edges(binding, locator, provider, parent, implementation, suite,
                                               outer, inner, parent_context)
            selected=[edge for edge in generated if (edge.target if incoming else edge.source) == point]
            edges.extend(selected)
            frontiers.extend(f for f in missing if f.point == point)
            if selected and not context_is_closed(context):
                frontiers.append(DependencyFrontier(point,"CLASS_INTERFACE_CONTEXT_PREFIX_OPEN",
                    "Original class interface selections are retained; their enclosing prefix is not selected."))
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
                    "CLASS_INTERFACE_CONTEXT_UNBOUND" if not context_frames(point.context) else "CLASS_INTERFACE_CONTEXT_UNMATCHED")
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
        contexts = {parent: parent_context, implementation: context_push(parent_context,outer),
                    suite: context_push(parent_context,outer,inner)}
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

        edges.append(self._globals_capture_edge(binding,locator,provider,parent,implementation,suite,
            contexts,indexes,conditions))

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

    @staticmethod
    def _globals_capture_edge(binding,locator,provider,parent,implementation,suite,contexts,indexes,conditions):
        """A guarded function-field reference projection, not operand equality.

        The provider reads current fields after arbitrary preparation callbacks.
        Original code provenance does not prove that current field state.  The
        explicit read-world predicate below is therefore never discharged here.
        No namespace contents, saved builtins, code or closure identity follows.
        """
        from scar.analysis.static_namespace import normal_reference
        def need(ok,detail):
            if not ok:raise ValueError('class function globals capture: '+detail)
        def point(namespace,node):return Point(namespace,node,contexts[namespace])
        construction=binding.construction
        pindex=indexes[parent];vindex=indexes[implementation];sindex=indexes[suite]
        factory=pindex.operations.get(construction.factory)
        need(factory is not None and factory.terminator is not None
             and factory.terminator.kind is TerminatorKind.INVOKE
             and factory.invoke_arguments==tuple(use.id for use in factory.uses)
             and tuple(use.id for use in factory.uses[:-1])==(
                 construction.factory_code,construction.factory_globals,*construction.factory_closure),
             'original factory code/globals/closure operand ports changed')
        code=pindex.use_site(construction.factory_code)
        capture=pindex.use_site(construction.factory_globals)
        need(code.operation==capture.operation==factory.id
             and type(pindex.values[code.use.value]) is ReferenceValue
             and type(pindex.values[capture.use.value]) is ReferenceValue,
             'code or captured globals is not the original factory reference Use')
        code_origin=pindex.values[code.use.value].origin
        need(type(code_origin) is OperationResult and code_origin.index==0
             and code_origin.operation in pindex.operations
             and pindex.operations[code_origin.operation].results==(code.use.value,),
             'factory code lost its original code-reference producer')
        suite_roots=sindex.graph.frame_roots
        need(len(suite_roots)==1 and suite_roots[0].code==construction.suite
             and type(suite_roots[0].entry) is ClassFrameABI,
             'shared suite no longer has the original code provenance and class frame ABI')
        normal=normal_reference(pindex,factory.id,blocks=pindex._block_records)
        need(normal is not None and normal[1]==construction.body_function,
             'body function is not the original factory NORMAL reference')
        call=construction.builder_call
        need(bool(call.arguments),'builder has no original body-function actual')
        body_actual=pindex.use_site(call.arguments[0].use)
        function_inputs=[mapping for mapping in binding.inputs if mapping.formal==provider.body_function]
        need(body_actual.operation==call.operation and body_actual.use.value==construction.body_function
             and len(function_inputs)==1 and function_inputs[0].actual_use==body_actual.use.id
             and function_inputs[0].actual_value==construction.body_function,
             'provider body function is not the original builder argument from this factory')
        reads=[(ordinal,stage) for ordinal,stage in enumerate(provider.stages)
               if stage.kind is ClassBuilderStageKind.READ_FUNCTION_FRAME]
        evals=[stage for stage in provider.stages if stage.kind is ClassBuilderStageKind.EVAL_SUITE]
        need(len(reads)==len(evals)==1,'provider needs its unique original field-read and suite-eval stages')
        read_ordinal,read=reads[0];evaluate=evals[0]
        operation=vindex.operations.get(read.operation)
        need(operation is not None and operation.terminator is not None
             and operation.terminator.kind is TerminatorKind.INVOKE
             and len(read.inputs)==1 and len(read.results)==3+len(provider.freevars)
             and tuple(use.id for use in operation.uses)==(*read.inputs,read.world)
             and operation.invoke_arguments==tuple(use.id for use in operation.uses),
             'field-read stage changed its original function/world/result ports')
        actual=vindex.use_site(read.inputs[0]);world=vindex.use_site(read.world)
        need(actual.operation==world.operation==read.operation
             and actual.use.value==provider.body_function
             and type(vindex.values[actual.use.value]) is ReferenceValue
             and type(vindex.values[world.use.value]) is StateVersionValue,
             'field-read is not on this provider body function and current world')
        for kind,block_id,expected in (
                (ExitKind.NORMAL,read.normal,(*read.results,read.normal_world)),
                (ExitKind.RAISE,read.raised,(read.exception,read.traceback,read.raised_world))):
            selected=[edge for edge in operation.terminator.successors if edge.kind is kind]
            need(len(selected)==1 and selected[0].block==block_id
                 and vindex._block_records[block_id].arguments==expected
                 and selected[0].arguments==tuple(CompletionResult(i) for i in range(len(expected))),
                 'field-read NORMAL/RAISE landing ports changed')
        need(type(vindex.values[read.results[1]]) is ReferenceValue,
             'field-read globals slot is not its original reference result')
        need(len(evaluate.inputs)>=5,'suite evaluation lost its function/code/namespace/G/B inputs')
        eval_sites=[vindex.use_site(use) for use in evaluate.inputs]
        eval_world=vindex.use_site(evaluate.world)
        eval_operation=vindex.operations.get(evaluate.operation)
        need(all(site.operation==evaluate.operation for site in eval_sites)
             and eval_world.operation==evaluate.operation and eval_operation is not None
             and tuple(use.id for use in eval_operation.uses)==(*evaluate.inputs,evaluate.world)
             and eval_sites[0].use.value==provider.body_function
             and eval_sites[1].use.value==read.results[0]
             and eval_sites[3].use.value==read.results[1]
             and eval_sites[4].use.value==read.results[2]
             and eval_world.use.value==read.normal_world,
             'suite evaluation does not use the current field-read code/G/savedB and post-world')
        globals_inputs=[mapping for mapping in binding.suite_inputs if mapping.role=='globals']
        need(len(globals_inputs)==1 and globals_inputs[0].actual_use==evaluate.inputs[3]
             and globals_inputs[0].actual_value==read.results[1]
             and globals_inputs[0].formal==suite_roots[0].entry.mapping.globals_namespace,
             'suite globals mapping does not select this exact field-read output')
        source=point(parent,construction.factory_globals)
        target=point(implementation,read.results[1])
        body_function=point(parent,construction.body_function)
        read_world=point(implementation,read.world)
        predicate=DependencyCondition('scar.class-function-frame',
            'CURRENT_FUNCTION_GLOBALS_EQUALS_FACTORY_CAPTURE',body_function,
            operands=(source,read_world,target))
        evidence=DependencyEvidence('CLASS_BODY_FUNCTION_GLOBALS_CAPTURE_V1',
            (replace(locator,pointer=locator.pointer+'/construction/factory_globals'),
             replace(locator,pointer=locator.pointer+'/construction/factory_code'),
             replace(binding.provider,pointer=binding.provider.pointer+'/stages/'+str(read_ordinal)),
             parent.graph,implementation.graph,suite.graph),
            (point(parent,factory.id),body_function,point(parent,construction.factory_code),
             point(parent,body_actual.use.id),point(implementation,read.inputs[0]),read_world,target))
        return DependencyEdge(source,target,K.ENVIRONMENT,M.REFERENCE,(evidence,),
            (*conditions,predicate),DependencyStrength.MAY)
