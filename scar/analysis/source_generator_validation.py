"""Closed source/entry/temporal-region partition for opt-in GeneratorExp.

Core validation still owns every SSA/state/driver edge. This verifier adds
source roles, readonly childCode identity and creation-versus-drive boundaries.
It grants no runtime, effect completeness, CLOSE or optimizer authority.
"""
from __future__ import annotations

import ast
import dis
from dataclasses import replace

from scar.analysis.program_lowering import _REF, _BOOL
from scar.ir.program.bindings import BindingState
from scar.ir.program.drivers import BodyStart, BodyResume, RawRequestKind
from scar.ir.program.environments import EnvironmentRole
from scar.ir.program.model import (
    Behavior, BlockArgument, CompletionResult, ExitKind, LiteralOrigin, LocalBindingValue,
    ReferenceValue, StateVersionValue, TerminatorKind, ProtocolValue, value_type,
)
from scar.ir.program.resumption import SavedInput, SavedRole, ResumeSlotKind, SuspendTerminator, SuspensionFlavor
from scar.ir.program.source import SourceRole
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
        lazy_code = None
        if not structural_only:
            _need(options is not None and options.code_evidence is not None,
                  'lazy string/compiler validation requires independent parent code evidence')
            lazy_code = options.code_evidence.code.co_consts[constant.constant_path[0]]
        string_operations, string_results = _validate_lazy_strings(
            body, local_operations, model, graph, metadata, semantic, source_tree, lazy_code,
            operations, values, blocks, protocols, links, positions)
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
                _need(key in string_operations or protocol is not None and protocol.kind in (
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
            if isinstance(node.elt,ast.Constant):
                # A literal has a source-backed value, not an executable elt
                # operation. Its actual YIELD export must name that exact
                # original value and source occurrence inside the lazy Region.
                exported=[use for use in suspend.uses if use.id==suspend.terminator.exported]
                _need(suspend.terminator.flavor is SuspensionFlavor.YIELD and len(exported)==1,
                      'literal element has no unique actual YIELD payload Use')
                payload=values[exported[0].value]
                source_uses=[row for row in metadata.use_links
                             if row.operation==suspend.id and row.use==exported[0].id]
                _need(len(source_uses)==1 and (source_uses[0].role,source_uses[0].index)==('yield',0),
                      'literal element lost its original ordered YIELD Use source')
                source_use=source_uses[0];atom=semantic.source_atoms.get(source_use.source.atom_id)
                expected=(node.elt.lineno,node.elt.end_lineno,node.elt.col_offset,node.elt.end_col_offset)
                _need(atom is not None and atom.kind=='Constant' and atom.reference==source_use.source
                      and (source_use.source.path,source_use.source.fingerprint)==(source.path,source.fingerprint)
                      and (source_use.source.start_line,source_use.source.end_line,
                           source_use.source.start_column,source_use.source.end_column)==expected,
                      'literal element YIELD source differs from the original Constant AST')
                value_sources=[row for row in metadata.value_links if row.value==payload.id
                               and row.source==source_use.source and row.role is SourceRole.EXPRESSION]
                _need(type(payload)is ReferenceValue and payload.region==body.id
                      and type(payload.origin)is LiteralOrigin
                      and type(payload.origin.value)is type(node.elt.value) and payload.origin.value==node.elt.value
                      and len(value_sources)==1,
                      'literal element is not its exact source-backed lazy reference/value')
            elif isinstance(node.elt, ast.JoinedStr) and _node_span(node.elt) in string_results:
                exported = [use.value for use in suspend.uses if use.id == suspend.terminator.exported]
                _need(exported == [string_results[_node_span(node.elt)]],
                      'lazy string result does not reach its original YIELD payload')
            else:
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


def _node_span(node):
    return node.lineno, node.end_lineno, node.col_offset, node.end_col_offset


def _validate_lazy_strings(body, local_operations, model, graph, metadata, semantic, tree, code,
                           operations, values, blocks, protocols, links, positions):
    """Consume existing string contracts under the real lazy caller/PEP479 ABI.

    This is a validator view over original IDs, never a second program graph.
    Only the argument-inspection view omits the separately checked caller-edge
    Uses; all CFG, state, releases and escape adapters remain the real records.
    """
    from scar.analysis.source_language import require_source_tree
    from scar.analysis.source_string_validation import _ordered_next, _pending_group
    from scar.ir.program.control import ProtocolValueKind as P
    from types import SimpleNamespace
    kinds = (Kind.FSTRING_CONVERT, Kind.FSTRING_FORMAT, Kind.BUILD_STRING)
    selected = {identity for identity in local_operations if protocols.get(identity) is not None
                and protocols[identity].kind in kinds}
    if not selected:
        return set(), {}
    _need(isinstance(tree, ast.Module), 'lazy strings require their retained original AST')
    uses = {(row.operation, row.use): row for row in metadata.use_links}
    value_sources = {(row.value, row.source.atom_id) for row in metadata.value_links}
    parents = {child: parent for parent in ast.walk(tree) for child in ast.iter_child_nodes(parent)}
    by_source, normalized, failures = {}, dict(operations), {}

    def args(operation):
        indexed = {use.id: use for use in operation.uses}
        return tuple(indexed[key] for key in operation.invoke_arguments)

    def invocation(operation):
        operands = args(operation)
        _need(operation.terminator is not None and operation.terminator.kind is TerminatorKind.INVOKE
              and operation.callee is None and not operation.effects_complete and len(operands) >= 2
              and all(type(values[use.value]) is ReferenceValue for use in operands[:-1])
              and type(values[operands[-1].value]) is StateVersionValue
              and values[operands[-1].value].region == body.id
              and tuple(operation.uses[:len(operands)]) == operands and len(operation.uses) == len(operands) + 2,
              'lazy string/escape must retain its original reference/world invoke and two caller edges')
        world_type = value_type(values[operands[-1].value])
        _need(tuple((row.kind, row.types) for row in operation.completions)
              == ((ExitKind.NORMAL, (_REF, world_type)), (ExitKind.RAISE, (_REF, world_type)))
              and tuple(edge.kind for edge in operation.terminator.successors) == (ExitKind.NORMAL, ExitKind.RAISE),
              'lazy string/escape changed its raw exception completion contract')
        extra = operation.uses[len(operands):]
        _need(extra[0].value == extra[1].value and all(type(values[use.value]) is ProtocolValue
              and values[use.value].protocol is P.DRIVE_CALLER_CONTEXT for use in extra),
              'lazy string/escape lost its original forwarded caller context')
        for edge, forward in zip(operation.terminator.successors, extra):
            landing = blocks[edge.block]
            _need(len(landing.arguments) == 3 and values[landing.arguments[0]].region == body.id
                  and value_type(values[landing.arguments[0]]) == _REF
                  and type(values[landing.arguments[1]]) is ProtocolValue
                  and values[landing.arguments[1]].protocol is P.DRIVE_CALLER_CONTEXT
                  and value_type(values[landing.arguments[2]]) == world_type
                  and edge.arguments == (CompletionResult(0), forward.id, CompletionResult(1)),
                  'lazy completion must forward its own result/caller/post-world ports')
        return operands[:-1]

    def frame_pending(block, exception, world):
        _need(bool(block.operations), 'lazy string escape has no frame cleanup')
        cleanup = operations[block.operations[0]]
        _need(protocols.get(cleanup.id) is not None and protocols[cleanup.id].kind is Kind.FRAME_EXIT
              and cleanup.terminator is None and cleanup.uses[-1].value == world
              and [use.value for use in cleanup.uses if uses[cleanup.id, use.id].role == 'held-payload'] == [exception],
              'PEP479 outcome must clean the same lazy frame with its own exception/post-world')
        _need(len(block.operations) == 3 and len(cleanup.results) == 1, 'lazy frame cleanup has an unclassified continuation')
        detach, terminal = (operations[key] for key in block.operations[1:])
        records = [row for row in graph.frame_context_detaches if row.operation == detach.id]
        _need(len(records) == 1 and detach.terminator is None and len(detach.uses) == 2
              and detach.uses[-1].value == cleanup.results[0] and len(detach.results) == 2
              and terminal.terminator is not None and terminal.terminator.kind is TerminatorKind.RAISE
              and tuple(use.value for use in terminal.uses) == (exception, detach.results[-1])
              and terminal.terminator.values == tuple(use.id for use in terminal.uses),
              'lazy exception lost its original frame-detach/terminal world corridor')
        return tuple(use.value for use in cleanup.uses if uses[cleanup.id, use.id].role == 'held-temporary')

    for identity in selected:
        operation, protocol = operations[identity], protocols[identity]
        operands = invocation(operation)
        atom = semantic.source_atoms.get(protocol.source.atom_id)
        expected = ast.JoinedStr if protocol.kind is Kind.BUILD_STRING else ast.FormattedValue
        candidates = [node for node in require_source_tree(tree, metadata.source, protocol.source) if isinstance(node, expected)]
        definitions = [row for row in semantic.definitions.values() if row.code_id == protocol.source.atom_id.wire
                       and protocol.source.atom_id in row.source_atoms and row.kind is OperationKind.OPERATOR
                       and row.metadata.get('ast_type') == expected.__name__ and len(row.output_slots) == 1]
        _need(atom is not None and atom.reference == protocol.source == links[identity].source
              and atom.kind == expected.__name__ and len(candidates) == len(definitions) == 1
              and links[identity].semantic_operation is None and Behavior.MEMORY in operation.behaviors
              and (2 <= len(operands) <= 30 if protocol.kind is Kind.BUILD_STRING else len(operands) == 2),
              'lazy string lost its original AST/SG operator or exact reference arity')
        key = protocol.kind, protocol.source.atom_id
        _need(key not in by_source, 'lazy string duplicated an original stage')
        by_source[key] = identity
        # This is only the pure pending-query's argument view. Constructing an
        # Operation with its caller Uses removed would be invalid canonical IR;
        # the original operation/edges remain unchanged and independently checked.
        normalized[identity] = SimpleNamespace(id=identity, uses=args(operation), terminator=operation.terminator)
        refs = tuple(use.value for use in operands)
        consumed = (refs if protocol.kind is Kind.BUILD_STRING else refs[:1]
                    if protocol.kind is Kind.FSTRING_CONVERT or type(values[refs[1]].origin) is LiteralOrigin
                    and values[refs[1]].origin.value is None else refs)
        retained = None
        for edge in operation.terminator.successors:
            landing = blocks[edge.block]
            _need(len(landing.operations) > len(consumed), 'lazy string lost its input release corridor')
            world = landing.arguments[-1]
            for key, reference in zip(landing.operations, reversed(consumed)):
                release = operations[key]
                _need(protocols.get(key) is not None and protocols[key].kind is Kind.FRAME_RELEASE_TEMPORARY
                      and len(release.uses) == 2 and release.uses[0].value == reference
                      and uses[key, release.uses[0].id].role == 'fstring-consumed-reference'
                      and release.uses[-1].value == world and len(release.results) == 1,
                      'lazy string completion lost/reordered its original input releases')
                world = release.results[0]
            following = operations[landing.operations[len(consumed)]]
            _need(not following.uses or uses[following.id, following.uses[0].id].role != 'fstring-consumed-reference',
                  'lazy string releases an additional input')
            if edge.kind is ExitKind.RAISE:
                _need(protocols.get(following.id) is not None
                      and protocols[following.id].kind is Kind.GENERATOR_ESCAPE_STOPITER_TO_RUNTIME_ERROR
                      and tuple(use.value for use in invocation(following)) == (landing.arguments[0],)
                      and args(following)[-1].value == world,
                      'lazy string exception bypassed its original PEP479 adapter')
                for escaped in following.terminator.successors:
                    terminal = blocks[escaped.block]
                    actual = frame_pending(terminal, terminal.arguments[0], terminal.arguments[-1])
                    _need(retained is None or retained == actual, 'PEP479 outcomes changed the retained pending prefix')
                    retained = actual
        failures[identity] = retained

    def reference(node):
        matches = [row.reference for row in semantic.source_atoms.values() if row.kind == type(node).__name__
                   and (row.reference.start_line, row.reference.end_line, row.reference.start_column,
                        row.reference.end_column) == _node_span(node)]
        _need(len(matches) == 1, 'lazy string child lacks its exact original source atom')
        return matches[0]

    def literal(value, expected):
        origin = values[value].origin
        return type(origin) is LiteralOrigin and type(origin.value) is type(expected) and origin.value == expected

    def match_value(value, node):
        source = reference(node)
        matched = (value, source.atom_id) in value_sources
        if not matched and type(values[value].origin) is BlockArgument and values[value].origin.index == 0:
            # Nested invoke ports retain the GeneratorExp entry source. Recover
            # the exact child result from its real NORMAL edge and original SG
            # producer instead of inventing a missing ValueSource annotation.
            origin = values[value].origin
            producers = [identity for identity in local_operations
                if operations[identity].terminator is not None
                and operations[identity].terminator.kind is TerminatorKind.INVOKE
                and links[identity].source == source
                and any(edge.kind is ExitKind.NORMAL and edge.block == origin.block
                        and edge.arguments[0] == CompletionResult(0)
                        for edge in operations[identity].terminator.successors)
                and (definition := semantic.definitions.get(links[identity].semantic_operation)) is not None
                and definition.code_id == source.atom_id.wire and source.atom_id in definition.source_atoms
                and len(definition.output_slots) == 1]
            matched = len(producers) == 1 and blocks[origin.block].arguments[0] == value
        _need(matched and (not isinstance(node, ast.Constant) or literal(value, node.value)),
              'lazy string input lost its original source/literal value')

    def result(identity):
        return blocks[operations[identity].terminator.successors[0].block].arguments[0]

    roots = set()
    for identity in selected:
        source = protocols[identity].source
        node, = [node for node in require_source_tree(tree, metadata.source, source)
                 if isinstance(node, ast.JoinedStr if protocols[identity].kind is Kind.BUILD_STRING else ast.FormattedValue)]
        if isinstance(node, ast.FormattedValue): node = parents.get(node)
        _need(isinstance(node, ast.JoinedStr), 'lazy string stage has no JoinedStr owner')
        while isinstance(parents.get(node), ast.FormattedValue) and parents[node].format_spec is node:
            node = parents.get(parents[node])
        roots.add(node)
    covered, root_results = set(), {}
    for root in sorted(roots, key=_node_span):
        stages = []
        def stage(node, kind):
            identity = by_source.get((kind, reference(node).atom_id))
            _need(identity is not None, 'lazy string AST is missing a required stage')
            stages.append(identity)
            return identity
        def formatted(node, expected=None):
            identity = by_source.get((Kind.FSTRING_FORMAT, reference(node).atom_id))
            _need(identity is not None, 'lazy FormattedValue has no format stage')
            refs = tuple(use.value for use in args(operations[identity])[:-1])
            if node.conversion == -1:
                match_value(refs[0], node.value)
                _need((Kind.FSTRING_CONVERT, reference(node).atom_id) not in by_source,
                      'lazy string inserted a conversion absent from source')
            else:
                conversion = stage(node, Kind.FSTRING_CONVERT)
                operands = args(operations[conversion])
                match_value(operands[0].value, node.value)
                _need(literal(operands[1].value, node.conversion) and refs[0] == result(conversion),
                      'lazy conversion selector/result differs from exact source')
            if node.format_spec is None:
                _need(literal(refs[1], None), 'lazy simple format gained an explicit specification')
            else:
                joined(node.format_spec, refs[1])
            stage(node, Kind.FSTRING_FORMAT)
            _need(expected is None or result(identity) == expected, 'lazy consumer changed the formatted result')
            return result(identity)
        def joined(node, expected=None):
            _need(isinstance(node, ast.JoinedStr) and len(node.values) <= 30, 'unsupported original lazy string shape')
            if len(node.values) > 1:
                identity = by_source.get((Kind.BUILD_STRING, reference(node).atom_id))
                _need(identity is not None, 'lazy JoinedStr lost its join')
                refs = tuple(use.value for use in args(operations[identity])[:-1])
                _need(len(refs) == len(node.values), 'lazy join piece count differs')
            else:
                identity, refs = None, (expected,)
                _need((Kind.BUILD_STRING, reference(node).atom_id) not in by_source, 'lazy one-piece string gained a join')
            value = expected
            for offset, child in enumerate(node.values):
                value = refs[offset]
                if isinstance(child, ast.FormattedValue):
                    value = formatted(child, value)
                else:
                    _need(isinstance(child, ast.Constant) and type(child.value) is str, 'lazy string piece changed source type')
                    if value is None:
                        choices = {value for value, atom in value_sources if atom == reference(child).atom_id and literal(value, child.value)}
                        _need(len(choices) == 1, 'lazy string literal lacks its unique reference')
                        value, = choices
                    match_value(value, child)
            if identity is not None:
                stage(node, Kind.BUILD_STRING); value = result(identity)
            _need((bool(node.values) or expected is not None and literal(expected, ''))
                  and (expected is None or value == expected), 'lazy JoinedStr result differs from its actual consumer')
            return value
        value = joined(root)
        _need(stages and not covered.intersection(stages), 'lazy string stages have duplicate owners')
        covered.update(stages); root_results[_node_span(root)] = value
        for current, following in zip(stages, stages[1:]):
            _ordered_next(current, following, set(stages), operations, blocks, positions)
        if code is not None:
            rows = tuple(dis.get_instructions(code)); offsets = []
            for identity in stages:
                kind, source = protocols[identity].kind, protocols[identity].source
                node, = [node for node in require_source_tree(tree, metadata.source, source)
                         if isinstance(node, ast.JoinedStr if kind is Kind.BUILD_STRING else ast.FormattedValue)]
                name = ('BUILD_STRING' if kind is Kind.BUILD_STRING else 'CONVERT_VALUE' if kind is Kind.FSTRING_CONVERT
                        else 'FORMAT_SIMPLE' if node.format_spec is None else 'FORMAT_WITH_SPEC')
                matches = [row for row in rows if row.opname == name and tuple(row.positions) == _node_span(node)]
                _need(len(matches) == 1, 'lazy string lost its exact child compiler opcode/position')
                row, = matches
                _need(name != 'BUILD_STRING' or row.arg == len(node.values), 'lazy compiler join arity differs')
                _need(name != 'CONVERT_VALUE' or row.arg == {115: 1, 114: 2, 97: 3}.get(node.conversion),
                      'lazy compiler conversion differs')
                offsets.append(row.offset)
            _need(offsets == sorted(set(offsets)), 'lazy compiler stage order differs from source')
        held = set()
        for node in ast.walk(root):
            if isinstance(node, ast.JoinedStr) and len(node.values) > 1: held.update(node.values)
            elif isinstance(node, ast.FormattedValue):
                held.add(node.value)
                if node.conversion != -1: held.add(node)
                if node.format_spec is not None: held.add(node.format_spec)
        _pending_group(stages, {reference(node).atom_id for node in held}, normalized, protocols,
                       blocks, positions, uses, values, failures)
    _need(covered == selected, 'lazy string protocol has no original AST construction owner')
    return selected, root_results


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
