"""Closed source/entry/temporal-region partition for opt-in GeneratorExp.

Core validation still owns every SSA/state/driver edge. This verifier adds
source roles, readonly childCode identity and creation-versus-drive boundaries.
It grants no runtime, effect completeness, CLOSE or optimizer authority.
"""
from __future__ import annotations

import ast
from dataclasses import replace

from scar.analysis.program_lowering import _REF, _BOOL
from scar.ir.program.bindings import BindingState
from scar.ir.program.drivers import BodyStart, BodyResume, RawRequestKind
from scar.ir.program.environments import EnvironmentRole
from scar.ir.program.model import (
    Behavior, BlockArgument, CompletionResult, ExitKind, LiteralOrigin, LocalBindingValue,
    ReferenceValue, StateVersionValue, TerminatorKind, value_type,
)
from scar.ir.program.resumption import SavedInput, SavedRole, ResumeSlotKind, SuspendTerminator
from scar.ir.semantics_v2 import Opcode
from scar.ir.v2.semantic import SemanticRelation
from scar.ir.program.source_language import SourceLanguageCapability as Capability
from scar.ir.program.structured import PythonProtocolKind as Kind
from scar.ir.v2.semantic import OperationKind


def _need(condition, detail):
    if not condition:
        raise ValueError("source generator: " + detail)


def validate_generator_regions(model, graph, interface, metadata, semantic, language,
                               *, source_tree=None, options=None, structural_only=False):
    from scar.analysis.source_generator_lowering import compiler_entry_slot, child_code, VERSION, driver_rule
    from scar.analysis.source_language import require_source_tree
    creation_only = language is not None and Capability.GENEXPR_CREATION_314_V1 in language.capabilities
    enabled = language is not None and (Capability.GENEXPR_314_V1 in language.capabilities or creation_only)
    _need(not creation_only or Capability.GENEXPR_314_V1 not in language.capabilities,
          'creation-only and fixed-unpack policies are distinct versions')
    if not enabled:
        _need(not graph.resumable_creates and not graph.resumable_bodies and not graph.driver_interfaces,
              "nested generator records require the explicit nondefault capability")
        return set()
    if creation_only:
        _need(not any((graph.driver_interfaces,graph.body_drives,graph.raw_driver_requests,
                       graph.final_body_gates,graph.driver_lifecycles,graph.body_outcome_commits)),
              'creation-only source cannot introduce a driver, request, gate or published outcome')
    operations = {row.id: row for row in graph.operations}
    values = {row.id: row for row in graph.values}
    regions = {row.id: row for row in graph.regions}
    blocks = {row.id: row for region in graph.regions for row in region.blocks}
    owners = {operation: region.id for region in graph.regions for block in region.blocks for operation in block.operations}
    protocols = {row.operation: row for row in model.protocols}
    links = {row.operation: row for row in metadata.operation_links}
    constants = {row.operation: row for row in language.constants}
    positions = {key: (block.id, position) for region in graph.regions for block in region.blocks
                 for position, key in enumerate(block.operations)}
    envs = {row.region: row for row in graph.environments}
    layouts = {row.environment: row for row in graph.function_entries}
    creates = {row.operation: row for row in graph.resumable_creates}
    bodies = {row.region: row for row in graph.resumable_bodies}
    drivers = {row.region: row for row in graph.driver_interfaces}
    _need(set(links) == set(operations), "every nested operation needs its exact original source")
    for link in links.values():
        atom = semantic.source_atoms.get(link.source.atom_id)
        _need(atom is not None and atom.reference == link.source, "unowned source atom in generator graph")
    creation_protocols = {key for key, row in protocols.items() if row.kind is Kind.CREATE_GENEXPR}
    _need(creation_protocols == set(creates), "Create protocol/declaration coverage differs")
    root_primitives, claimed, used_constants, used_makes = set(), set(), set(), set()
    for identity, create in creates.items():
        protocol = protocols[identity]
        source = protocol.source
        atom = semantic.source_atoms[source.atom_id]
        definitions = [row for row in semantic.definitions.values() if row.code_id == source.atom_id.wire
                       and row.output_slots and row.metadata.get("role") != "binding"]
        _need(len(definitions) == 1 and definitions[0].kind is OperationKind.OPAQUE
              and definitions[0].metadata.get("ast_type") == atom.kind == "GeneratorExp"
              and len(definitions[0].output_slots) == 1, "Create lost the exact original OPAQUE GeneratorExp scope")
        definition, = definitions
        _need(owners[identity] == graph.root and create.body in bodies, "Create must remain outside its lazy body")
        body = regions[create.body]
        _need(body.parent == graph.root and envs.get(body.id) is not None
              and envs[body.id].code_definition == definition.id, "lazy body source/environment owner differs")
        environment = envs[body.id]
        layout = layouts[environment.id]
        _need(len(layout.parameters) == 1 and layout.parameters[0].slot not in semantic.slots,
              ".0 must be one compiler entry port, never a fabricated SG slot")
        matches = [key for key, row in constants.items() if row.source == source]
        makes = [key for key, row in protocols.items() if row.kind is Kind.MAKE_GENEXPR_FUNCTION and row.source == source]
        _need(len(matches) == len(makes) == 1, "each creation needs unique original childCode/function construction")
        code_read, = matches
        make, = makes
        constant = constants[code_read]
        _need(len(constant.constant_path) == 1 and constant.source == source
              and protocols[code_read].kind is Kind.READ_CODE_CONSTANT,
              "childCode must retain one exact parent constant slot")
        _need(layout.parameters[0].slot == compiler_entry_slot(definition.id, constant.code_key, constant.constant_path[0]),
              "compiler entry identity lost source/parent-code/constant-slot provenance")
        read = operations[code_read]
        _need(owners[code_read] == owners[make] == graph.root and read.behaviors == (Behavior.READ,)
              and read.terminator is None and read.callee is None and not read.effects_complete
              and len(read.results) == 1 and type(values[read.results[0]]) is ReferenceValue
              and len(read.uses) == len(read.accesses) == 1, "childCode read has invented evaluation/effects")
        factory = operations[make]
        _need(factory.callee is None and not factory.effects_complete and factory.terminator is not None
              and factory.terminator.kind is TerminatorKind.INVOKE
              and tuple(row.kind for row in factory.completions) == (ExitKind.NORMAL, ExitKind.RAISE)
              and factory.completions[0].types == (_REF,) * 5 + (value_type(values[interface.world]),),
              "MAKE_FUNCTION environment must remain a five-reference stateful interface")
        factory_uses = {row.id: row for row in factory.uses}
        inputs = tuple(factory_uses[key].value for key in factory.invoke_arguments)
        root_env = envs[graph.root]
        _need(inputs[0] == read.results[0] and inputs[1] == root_env.members[1].reference,
              "child function must use its exact code and parent globals; saved-builtins are separately produced")
        own = {row.id: row for row in operations[identity].uses}
        captures = {row.formal: own[row.source].value for row in create.captures}
        edge = next(row for row in factory.terminator.successors if row.kind is ExitKind.NORMAL)
        produced = blocks[edge.block].arguments[:-1]
        _need(tuple(captures[row.reference] for row in environment.members[:5]) == produced,
              "creation must capture the actual newly constructed function/environment ports")
        cell_members = environment.members[5:]
        _need(inputs[2:-1] == tuple(captures[row.reference] for row in cell_members),
              "capture must preserve cells, not eager reads of their contents/attributes")
        parent_cells = {blocks[e.block].arguments[0] for row in model.protocols if row.kind is Kind.MAKE_CELL
                        and owners[row.operation] == graph.root
                        for e in operations[row.operation].terminator.successors if e.kind is ExitKind.NORMAL}
        parent_cells |= {member.reference for member in root_env.members[5:]}
        _need(set(inputs[2:-1]) <= parent_cells, "captured source is not an actual parent cell reference")
        iterator = captures[layout.parameters[0].value]
        iterator_origin = values[iterator].origin
        _need(type(iterator_origin) is BlockArgument, "creation iterator must be GET_ITER normal output")
        gets = [key for key, row in protocols.items() if row.kind is Kind.GET_ITERATOR
                and owners[key] == graph.root and any(e.kind is ExitKind.NORMAL and e.block == iterator_origin.block
                                                     for e in operations[key].terminator.successors)]
        _need(len(gets) == 1, "outermost iterable must be acquired eagerly exactly once")
        from scar.analysis.source_string_validation import _ordered_next
        stages = {make, gets[0], identity}
        _ordered_next(make, gets[0], stages, operations, blocks, positions)
        _ordered_next(gets[0], identity, stages, operations, blocks, positions)
        _need(operations[identity].callee is None and not operations[identity].effects_complete,
              "generator creation cannot synchronously call B or claim purity")
        local_drivers = [row for row in drivers.values() if row.body == body.id]
        if creation_only:
            sites = [op for op in operations.values() if owners[op.id]==body.id and type(op.terminator) is SuspendTerminator]
            _need(len(sites)==1,'creation-only lazy body must retain its unique original yield boundary')
            suspend, = sites
        else:
            _need(len(local_drivers) == 2, "NEXT start/resume need separate driver interfaces sharing one B")
            local_drives = [row for row in graph.body_drives if owners[row.operation] in {row.region for row in local_drivers}]
            starts = [row for row in local_drives if type(row.target) is BodyStart]
            resumes = [row for row in local_drives if type(row.target) is BodyResume]
            _need(len(starts) == len(resumes) == 1 and starts[0].target.body == body.id,
                  "driver start/resume target coverage differs")
            suspend = operations[resumes[0].target.suspend]
        _need(owners[suspend.id] == body.id and type(suspend.terminator) is SuspendTerminator
              and len(suspend.terminator.successors) == 1
              and tuple(slot.kind for slot in suspend.terminator.successors[0].inputs)
                  == (ResumeSlotKind.SENT_VALUE, ResumeSlotKind.STATE), "NEXT resume must use the same real yield boundary")
        saved = suspend.terminator.saved
        _need(tuple(row.role for row in saved[:2]) == (SavedRole.FRAME_CONTEXT, SavedRole.LOCAL_BINDING)
              and all(row.role is SavedRole.VALUE for row in saved[2:])
              and len(saved) == len(environment.members) + 3,
              "suspend must retain frame, target binding, environment and iterator")
        local_operations = {key for key, owner in owners.items() if owner == body.id}
        _need([key for key in local_operations if type(operations[key].terminator) is SuspendTerminator] == [suspend.id],
              "one-clause generator must have its unique actual yield boundary")
        semantic_operations = [links[key].semantic_operation for key in local_operations if links[key].semantic_operation is not None]
        _need(len(semantic_operations) == len(set(semantic_operations)), "a lazy source operation was duplicated")
        advances = [key for key in local_operations if key in protocols and protocols[key].kind is Kind.ADVANCE_ITERATOR]
        _need(len(advances) == 1 and not any(key in protocols and protocols[key].kind is Kind.GET_ITERATOR for key in local_operations),
              "lazy B must advance .0 and must not repeat GET_ITER")
        # Must-copy sets include the real SavedInput temporal edge, so a name
        # read cannot quietly substitute a newly read object for a saved cell.
        from scar.ir.program.cleanup_forward import _must_forward
        from scar.ir.program.resumption import saved_actual_use
        incoming = {formal: [] for block in body.blocks for formal in block.arguments}
        for block in body.blocks:
            final = operations[block.operations[-1]]
            owned = {use.id: use.value for use in final.uses}
            for edge in final.terminator.successors:
                for actual, formal in zip(edge.arguments, blocks[edge.block].arguments):
                    incoming[formal].append(owned.get(saved_actual_use(final, actual)))
        copied = {member.reference: _must_forward({member.reference}, incoming) for member in environment.members}
        iterator_copies = _must_forward({layout.parameters[0].value}, incoming)
        advance = operations[advances[0]]
        _need(advance.uses[0].value in iterator_copies, "lazy iteration lost the captured .0 iterator")
        bindings = {values[row.value].origin.operation for row in graph.binding_definitions if values[row.value].region == body.id}
        binding_reads = {row.operation for row in graph.binding_reads if owners[row.operation] == body.id}
        context_actions = {row.operation for rows in (graph.frame_context_initials, graph.frame_context_attaches,
                                                      graph.frame_context_detaches) for row in rows}
        source_slots = {}
        for edge in semantic.edges.values():
            if edge.relation is SemanticRelation.READS_SLOT:
                source_slots.setdefault(edge.source.id, []).append(semantic.slots[edge.target.id])
        for key in local_operations:
            operation, link = operations[key], links[key]
            protocol = protocols.get(key)
            if protocol is not None and protocol.kind is Kind.GENEXPR_CONTAINS:
                _need(creation_only and isinstance(source_tree,ast.Module),'membership requires new creation policy and original AST')
                from scar.analysis.source_language import require_source_tree
                nodes=[n for n in require_source_tree(source_tree,language.source,link.source)if isinstance(n,ast.Compare)]
                _need(len(nodes)==1 and len(nodes[0].ops)==len(nodes[0].comparators)==1
                      and isinstance(nodes[0].ops[0],(ast.In,ast.NotIn)),'membership lost original one-operator AST')
                member=nodes[0];own={u.id:u for u in operation.uses};args=tuple(own[u]for u in operation.invoke_arguments)
                _need(len(args)==4 and all(type(values[u.value])is ReferenceValue for u in args[:3])
                      and type(values[args[-1].value])is StateVersionValue and not operation.effects_complete
                      and operation.callee is None and operation.terminator.kind is TerminatorKind.INVOKE
                      and operation.completions[0].types==(_REF,value_type(values[interface.world]))
                      and operation.completions[1].types==(_REF,value_type(values[interface.world]))
                      and link.opcode is None,'membership must keep incomplete reference/world NORMAL and RAISE')
                negative=values[args[2].value].origin
                _need(type(negative)is LiteralOrigin and type(negative.value)is bool
                      and negative.value==isinstance(member.ops[0],ast.NotIn),'membership negation differs')
                source_uses={(r.operation,r.use):r for r in metadata.use_links}
                for i,(child,role)in enumerate(((member.left,'left'),(member.comparators[0],'right'))):
                    src=source_uses[(key,args[i].id)]
                    _need(src.role==role and src.index==i and (src.source.start_line,src.source.end_line,src.source.start_column,src.source.end_column)
                          ==(child.lineno,child.end_lineno,child.col_offset,child.end_col_offset),'membership ordered original operands differ')
            if protocol is not None and protocol.kind in (Kind.READ_FREE_CELL, Kind.LOOKUP_GLOBAL):
                original = semantic.definitions.get(link.semantic_operation)
                slots = source_slots.get(link.semantic_operation, ())
                _need(original is not None and len(slots) == 1 and link.opcode is Opcode.READ
                      and semantic.source_atoms[link.source.atom_id].kind == "Name",
                      "lazy Name read lost its actual SG binding")
                refs = [use.value for use in operation.uses if type(values[use.value]) is ReferenceValue]
                if protocol.kind is Kind.READ_FREE_CELL:
                    from scar.analysis.environment_lowering import captured_cell_slot
                    members = [member for member in cell_members
                               if member.cell_slot == captured_cell_slot(definition.id, slots[0].name)]
                    _need(len(members) == len(refs) == 1 and refs[0] in copied[members[0].reference],
                          "free read must use the saved captured cell, not its eager contents")
                else:
                    _need(len(refs) == 3 and refs[0] in copied[environment.members[1].reference]
                          and refs[1] in copied[environment.members[2].reference]
                          and type(values[refs[2]].origin) is LiteralOrigin
                          and values[refs[2]].origin.value == slots[0].name,
                          "lazy global read lost the child function's own globals/saved-builtins")
            if link.semantic_operation is not None:
                original = semantic.definitions.get(link.semantic_operation)
                _need(original is not None and original.code_id == link.source.atom_id.wire
                      and link.source.atom_id in original.source_atoms,
                      "lazy semantic operation does not own its exact source atom")
            elif operation.terminator is None:
                _need(key in bindings | binding_reads | context_actions
                      or protocol is not None and protocol.kind in (
                          Kind.FRAME_ENTER, Kind.FRAME_BIND, Kind.FRAME_EXIT, Kind.FRAME_DISCARD,
                          Kind.FRAME_HOLD_TEMPORARY, Kind.FRAME_RELEASE_TEMPORARY, Kind.MATCH_STOP_ITERATION),
                      "unclassified ordinary primitive in lazy B")
            elif operation.terminator.kind is TerminatorKind.INVOKE:
                _need(protocol is not None and protocol.kind in (
                    Kind.ADVANCE_ITERATOR, Kind.GENERATOR_ESCAPE_STOPITER_TO_RUNTIME_ERROR),
                      "unclassified effectful primitive in lazy B")
            if operation.terminator is not None and operation.terminator.kind is TerminatorKind.RAISE:
                result_use = next(use for use in operation.uses if use.id == operation.terminator.values[0])
                origin = values[result_use.value].origin
                _need(type(origin) is BlockArgument, "escaping exception lost its adapter result origin")
                adapters = [row.operation for row in model.protocols
                    if row.kind is Kind.GENERATOR_ESCAPE_STOPITER_TO_RUNTIME_ERROR
                    and any(edge.block == origin.block for edge in operations[row.operation].terminator.successors)]
                _need(len(adapters) == 1,
                      "escaping elt exception must pass the generator PEP479 adapter, not become exhaustion")
        _need({row.region for row in graph.driver_lifecycles} >= {row.region for row in local_drivers},
              "every NEXT driver must publish its actual outcomes")
        for driver in local_drivers:
            allowed = {row.operation for row in graph.body_drives if owners[row.operation] == driver.region}
            allowed |= {row.operation for row in graph.final_body_gates if owners[row.operation] == driver.region}
            allowed |= {row.operation for row in graph.body_outcome_commits if owners[row.operation] == driver.region}
            for key, owner in owners.items():
                if owner != driver.region or key in allowed:
                    continue
                operation = operations[key]
                protocol = protocols.get(key)
                _need(operation.terminator is not None and operation.terminator.kind in (TerminatorKind.RETURN, TerminatorKind.RAISE)
                      or protocol is not None and protocol.kind is Kind.FRAME_EXIT,
                      "unclassified primitive in NEXT driver")
        consumer_ids = set()
        if not creation_only:
            unpack_calls = [row for row in language.unpackings if operations[row.operation].callee is not None
                            and owners[row.operation] == graph.root
                            and any(e.kind is ExitKind.NORMAL and captures_handle == blocks[e.block].arguments[0]
                                    for captures_handle in [next(iter(operations[row.operation].uses)).value]
                                    for e in operations[identity].terminator.successors)]
            _need(len(unpack_calls) == 1, "fresh handle must have its exact fixed-unpack composite consumer")
            unpack, = unpack_calls
            consumer_id = operations[unpack.operation].callee
            consumer = regions[consumer_id]
            _need(consumer.parent == graph.root, "consumer must remain a separate synchronous Region")
            local_calls = [operations[key] for block in consumer.blocks for key in block.operations
                           if operations[key].callee in {row.region for row in local_drivers}]
            start_region, resume_region = owners[starts[0].operation], owners[resumes[0].operation]
            _need(len(local_calls) == len(unpack.child_targets) + 1
                  and [row.callee for row in local_calls] == [start_region, *([resume_region] * len(unpack.child_targets))],
                  "fixed unpack requires N results plus one excess probe, without restarting B")
            requests = [row for row in graph.raw_driver_requests if values[row.value].region == consumer_id]
            _need(len(requests) == 1 and requests[0].kind is RawRequestKind.NEXT and not requests[0].operands,
                  "fixed unpack drives only NEXT; close/throw cannot be invented")
            consumer_calls = {row.id for row in local_calls}
            raw_producer = values[requests[0].value].origin.operation
            for block in consumer.blocks:
                for key in block.operations:
                    if key in consumer_calls or key == raw_producer:
                        continue
                    operation, protocol = operations[key], protocols.get(key)
                    _need(protocol is not None and protocol.kind in (
                              Kind.FRAME_HOLD_TEMPORARY, Kind.FRAME_DISCARD, Kind.FRAME_EXIT, Kind.MAKE_UNPACK_ARITY_ERROR)
                          or operation.terminator is not None and operation.terminator.kind in (
                              TerminatorKind.BRANCH, TerminatorKind.RETURN, TerminatorKind.RAISE),
                          "unclassified primitive in fixed-unpack consumer")
            for ordinal, call in enumerate(local_calls):
                landing = blocks[call.terminator.successors[0].block]
                branch = operations[landing.operations[-1]]
                _need(branch.terminator.kind is TerminatorKind.BRANCH
                      and next(use.value for use in branch.uses if use.id == branch.terminator.condition) == landing.arguments[1],
                      "unpack must branch on that drive's yielded/exhausted outcome")
                bad = blocks[branch.terminator.successors[int(ordinal < len(unpack.child_targets))].block]
                first = protocols.get(bad.operations[0])
                _need(first is not None and first.kind is Kind.FRAME_DISCARD,
                      "excess/exhausted drive payload must be consumed before constructing arity error")
                error = operations[bad.operations[-1]]
                _need(error.id in protocols and protocols[error.id].kind is Kind.MAKE_UNPACK_ARITY_ERROR
                      and not error.effects_complete and error.callee is None,
                      "arity failure requires its explicit incomplete error-construction primitive")
                error_uses = {use.id: use for use in error.uses}
                arity = [values[error_uses[key].value].origin for key in error.invoke_arguments[:-1]]
                _need(all(type(origin) is LiteralOrigin and type(origin.value) is int for origin in arity)
                      and [origin.value for origin in arity] == [len(unpack.child_targets), ordinal + int(ordinal == len(unpack.child_targets))],
                      "unpack shortage/excess arity differs from its actual probe ordinal")
            consumer_ids.add(consumer_id)
        _need(not any(row.operation in local_operations for row in graph.resumable_creates), "lazy body cannot execute at creation")
        if not structural_only:
            _need(options is not None and options.code_evidence is not None,
                  "compiler validation requires the independent readonly parent CodeWitness")
            nodes = [row for row in require_source_tree(source_tree, language.source, source) if isinstance(row, ast.GeneratorExp)]
            _need(len(nodes) == 1, "generator needs its exact source AST")
            node, = nodes
            if creation_only:
                from scar.analysis.source_generator_creation_lowering import creation_code_sources
                index, code, _sites = creation_code_sources(options.code_evidence.code, node)
            else: index, code = child_code(options.code_evidence.code, node)
            _need(constant.code_key == options.code_evidence.code_layout_key and constant.constant_path == (index,),
                  "childCode does not match the exact original readonly parent witness")
            _need(len(node.generators) == 1 and not node.generators[0].ifs and not node.generators[0].is_async
                  and isinstance(node.generators[0].target, ast.Name), "unsupported generator clause")
            from scar.analysis.environment_lowering import captured_cell_slot
            _need(tuple(member.cell_slot for member in cell_members)
                  == tuple(captured_cell_slot(definition.id, name) for name in code.co_freevars),
                  "closure order/names differ from childCode")
            if creation_only:
                from scar.analysis.source_generator_creation_lowering import creation_rule
                expected_rule = creation_rule()
            else: expected_rule = driver_rule()
            _need(create.rule == expected_rule and all(row.rule == create.rule for row in local_drivers),
                  "independently running source policy differs from the declared driver contract")
            target_slots = {row.slot_id for row in semantic.slots.values()
                            if row.owner == definition.id and row.name == node.generators[0].target.id}
            bindings = [row for row in graph.binding_definitions if values[row.value].region == body.id]
            _need(target_slots and all(values[row.value].slot in target_slots for row in bindings),
                  "generator target binding must use the original comprehension SG slot")
            elt_ops = [key for key in local_operations if links[key].source.start_line == node.elt.lineno
                       and links[key].source.start_column == node.elt.col_offset]
            _need(elt_ops, "lazy element source must be connected inside B")
            for p in model.protocols:
                if p.kind is not Kind.GENEXPR_CONTAINS or owners[p.operation]!=body.id:continue
                source=p.source
                rows=[r for r in __import__('dis').get_instructions(code)if r.opname=='CONTAINS_OP'
                      and tuple(r.positions)==(source.start_line,source.end_line,source.start_column,source.end_column)]
                _need(len(rows)==1 and rows[0].arg==int(values[operations[p.operation].uses[2].value].origin.value),
                      'membership lost its original childCode opcode/source occurrence')
            lazy_sources = {semantic.source_atoms[ref.atom_id].reference for ref in
                            (link.source for link in links.values())
                            if any((ref.start_line, ref.end_line, ref.start_column, ref.end_column)
                                   == (child.lineno, child.end_lineno, child.col_offset, child.end_col_offset)
                                   for child in ast.walk(node.elt) if hasattr(child, "end_lineno"))}
            _need(all(owners[key] == body.id for key, link in links.items()
                      if link.source in lazy_sources and link.semantic_operation is not None),
                  "element or attribute lookup executed eagerly outside B")
        else:
            from scar.analysis.source_generator_creation_lowering import VERSION as CREATION_VERSION
            _need(create.rule.implementation.artifact.schema == (CREATION_VERSION if creation_only else VERSION),
                  "unsupported generator construction policy")
        claimed |= {body.id, *consumer_ids, *(row.region for row in local_drivers)}
        root_primitives |= {identity, make, code_read}
        used_constants.add(code_read); used_makes.add(make)
    _need(set(regions) == {graph.root, *claimed}, "unclaimed nested Region")
    _need(set(envs) == {graph.root, *bodies}, "unclaimed nested environment")
    _need(set(bodies) == {row.body for row in creates.values()}, "body has no original creation interface")
    _need(used_makes == {key for key, row in protocols.items() if row.kind is Kind.MAKE_GENEXPR_FUNCTION},
          "orphan function construction")
    return root_primitives


def root_projection(model, graph, metadata, language, delegated):
    """Source root checks retain their old contract after whole-core validation.

    This is a temporary verifier view, never serialized or published as facts.
    Nested canonical records have already passed the closed partition check.
    """
    root = next(row for row in graph.regions if row.id == graph.root)
    root_ops = {key for block in root.blocks for key in block.operations}
    root_values = {row.id for row in graph.values if row.region == graph.root}
    environment = next(row for row in graph.environments if row.region == graph.root)
    from scar.analysis.source_generator_lowering import TABLES
    cleared = {name: () for name in TABLES if name not in ("environments", "function_entries")}
    projected = replace(graph, **cleared, regions=(root,), operations=tuple(row for row in graph.operations if row.id in root_ops),
        values=tuple(row for row in graph.values if row.id in root_values), environments=(environment,),
        function_entries=tuple(row for row in graph.function_entries if row.environment == environment.id),
        binding_definitions=tuple(row for row in graph.binding_definitions if row.value in root_values),
        binding_reads=tuple(row for row in graph.binding_reads if row.operation in root_ops),
        state_address_refinements=tuple(row for row in graph.state_address_refinements if row.site.operation in root_ops))
    source_model = replace(model, protocols=tuple(row for row in model.protocols if row.operation in root_ops and row.operation not in delegated))
    source_metadata = replace(metadata,
        operation_links=tuple(row for row in metadata.operation_links if row.operation in root_ops),
        value_links=tuple(row for row in metadata.value_links if row.value in root_values),
        use_links=tuple(row for row in metadata.use_links if row.operation in root_ops),
        call_targets=tuple(row for row in metadata.call_targets if row.operation in root_ops))
    source_language = replace(language, constants=tuple(row for row in language.constants if row.operation not in delegated))
    return source_model, projected, source_metadata, source_language


__all__ = ["validate_generator_regions", "root_projection"]
