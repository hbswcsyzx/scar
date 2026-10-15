"""Independent source-to-inventory checks for conditional function interfaces."""
import ast
from copy import deepcopy
from dataclasses import replace
from textwrap import dedent

import pytest

from scar.analysis.program_inventory import (
    ProgramInventory, _inventory_from_inputs, inventory_program,
)
from scar.analysis.program_lowering import PreparedSource, lower_source, prepare_source
from scar.ir.program.functions import (
    BindingCondition, BindingIssueKind, BindingOrigin, BodyLoweringProfile,
    CallBindingStatus, FunctionInterfaces, ParameterKind,
)
from scar.ir.program.inventory import InventoryBudget
from scar.ir.program.model import BlockArgument, ReferenceValue, StateVersionValue
from scar.ir.program.source import SourceRole
from scar.ir.record_codec import decode, encode


def _inventory(tmp_path, source, **options):
    path = tmp_path / "entry.py"
    path.write_text(dedent(source).lstrip(), encoding="utf-8")
    result = inventory_program(path, project_root=tmp_path, **options)
    file = next(file for file in result.files if file.snapshot.path == str(path))
    return result, file, path


def _definition(file, name):
    return next(definition for definition in file.definitions if definition.name == name)


def _body(file, definition):
    return next(body for body in file.bodies if body.definition == definition.id)


def _same_span(source, node):
    return (source.start_line, source.end_line, source.start_column, source.end_column) == (
        node.lineno, node.end_lineno, node.col_offset, node.end_col_offset)


@pytest.fixture(scope="module")
def all_formals_inventory(tmp_path_factory):
    return _inventory(tmp_path_factory.mktemp("function-interface-review"), """
        def target(a, /, b=7, *rest, c=8, **extra):
            return a
        def caller():
            first = target(1, 2, 3, c=4, z=5)
            second = target(6)
            return first
    """)


def test_all_five_formals_map_exact_source_slots_to_bound_entry(all_formals_inventory):
    result, file, path = all_formals_inventory
    definition = _definition(file, "target")
    signature = next(item for item in result.interfaces.signatures if item.definition == definition.id)
    interface = next(item for item in result.interfaces.bodies if item.definition == definition.id)
    body = _body(file, definition)
    assert body.graph is not None
    assert [(p.name, p.kind) for p in signature.parameters] == [
        ("a", ParameterKind.POSITIONAL_ONLY), ("b", ParameterKind.POSITIONAL),
        ("rest", ParameterKind.VAR_POSITIONAL), ("c", ParameterKind.KEYWORD_ONLY),
        ("extra", ParameterKind.VAR_KEYWORD),
    ]
    # The legacy source layer orders slots differently; names must decide the mapping.
    prepared = prepare_source(path, project_root=path.parent)
    source_slots = {slot.name: slot.slot_id for slot in prepared.semantic.slots.values()
                    if slot.owner == definition.id}
    region = next(region for region in body.graph.regions if region.id == body.graph.root)
    entry = next(block for block in region.blocks if block.id == region.entry)
    values = {value.id: value for value in body.graph.values}
    assert interface.region == body.graph.root
    assert interface.profile is BodyLoweringProfile.BOUND_FORMALS
    assert entry.arguments == (*tuple(port.value for port in interface.parameters), interface.world)
    for index, (parameter, port) in enumerate(zip(signature.parameters, interface.parameters)):
        assert parameter.slot == port.slot == source_slots[parameter.name]
        assert isinstance(values[port.value], ReferenceValue)
        assert values[port.value].origin == BlockArgument(entry.id, index)
        links = [link for link in body.metadata.value_links if link.value == port.value
                 and link.role is SourceRole.PARAMETER]
        assert len(links) == 1
        assert (links[0].slot, links[0].source) == (parameter.slot, parameter.source)
    assert isinstance(values[interface.world], StateVersionValue)
    assert values[interface.world].origin == BlockArgument(entry.id, 5)


def test_conditional_routes_connect_actual_uses_and_pack_plans(all_formals_inventory):
    result, file, _ = all_formals_inventory
    target, caller = _definition(file, "target"), _definition(file, "caller")
    signature = next(item for item in result.interfaces.signatures if item.definition == target.id)
    slots = {parameter.slot: parameter.name for parameter in signature.parameters}
    bindings = sorted((binding for binding in result.interfaces.bindings if binding.target == target.id),
                      key=lambda binding: binding.source.start_line)
    assert len(bindings) == 2
    explicit, defaulted = bindings
    assert explicit.status is defaulted.status is CallBindingStatus.CONDITIONAL
    assert [(slots[route.slot], route.origin, route.argument_indices) for route in explicit.routes] == [
        ("a", BindingOrigin.ARGUMENT, (0,)), ("b", BindingOrigin.ARGUMENT, (1,)),
        ("rest", BindingOrigin.VAR_POSITIONAL_PACK, (2,)),
        ("c", BindingOrigin.ARGUMENT, (3,)),
        ("extra", BindingOrigin.VAR_KEYWORD_PACK, (4,)),
    ]
    body = _body(file, caller)
    for binding in bindings:
        source_call = next(call for call in file.calls if call.operation == binding.call)
        assert source_call.execution_owner == caller.id
        operation_links = [link for link in body.metadata.operation_links
                           if link.semantic_operation == binding.call]
        assert len(operation_links) == 1
        operation = next(op for op in body.graph.operations if op.id == operation_links[0].operation)
        assert tuple(argument.use for argument in binding.arguments) == operation.invoke_arguments[1:-1]
        for argument in binding.arguments:
            assert any(link.operation == operation.id and link.use == argument.use
                       and link.source == argument.source for link in body.metadata.use_links)
        assert operation.callee is None
        assert binding.conditions == tuple(BindingCondition)
    default_routes = {slots[route.slot]: route for route in defaulted.routes}
    assert default_routes["rest"].origin is BindingOrigin.VAR_POSITIONAL_PACK
    assert default_routes["extra"].origin is BindingOrigin.VAR_KEYWORD_PACK
    assert default_routes["rest"].argument_indices == default_routes["extra"].argument_indices == ()
    for name in ("b", "c"):
        parameter = next(parameter for parameter in signature.parameters if parameter.name == name)
        assert default_routes[name].origin is BindingOrigin.DEFAULT_STATE
        assert default_routes[name].default_source == parameter.default_source
        assert default_routes[name].argument_indices == ()


def test_v4_without_trace_has_no_fabricated_runtime_scope(all_formals_inventory):
    result, _, _ = all_formals_inventory
    document = result.to_dict()
    assert document["schema_version"] == 4
    assert document["runtime_scope"] is None and result.runtime_scope is None
    assert result.expansion is not None
    assert result.summary()["interfaces"]["live_call_binding_established"] is False
    assert ProgramInventory.from_dict(document).to_dict() == document


def test_positional_actual_cannot_carry_even_an_empty_keyword(all_formals_inventory):
    result, _, _ = all_formals_inventory
    argument = next(argument for binding in result.interfaces.bindings for argument in binding.arguments
                    if argument.kind.name == "POSITIONAL")
    assert argument.use is not None and argument.keyword is None
    with pytest.raises(ValueError):
        replace(argument, keyword="")


def test_defaults_and_decorators_remain_definition_stage_without_execution(tmp_path):
    marker = tmp_path / "must-not-exist"
    result, file, path = _inventory(tmp_path, f"""
        @decorate(open({str(marker)!r}, "w"))
        def target(a=make_default(), *, option=make_option()):
            return a
        def caller():
            return target()
    """)
    target = _definition(file, "target")
    assert _body(file, target).graph is not None
    signature = next(item for item in result.interfaces.signatures if item.definition == target.id)
    assert signature.decorators
    assert {item.role.name for item in target.definition_inputs} >= {"DECORATOR", "DEFAULT", "KEYWORD_DEFAULT"}
    declaration = ast.parse(path.read_text()).body[0]
    nodes = [*declaration.decorator_list, *declaration.args.defaults, *declaration.args.kw_defaults]
    definition_calls = [node for expression in nodes for node in ast.walk(expression)
                        if isinstance(node, ast.Call)]
    for node in definition_calls:
        call, = [call for call in file.calls if _same_span(call.source, node)]
        assert call.phase.name == "MODULE_INITIALIZATION"
        assert call.execution_owner != target.id
        assert not any(_same_span(link.source, node)
                       for link in _body(file, target).metadata.operation_links)
    applications = [item for item in file.implicit_invocations if item.definition == target.id]
    assert len(applications) == 1 and applications[0].role == "DECORATOR_APPLICATION"
    assert applications[0].phase.name == "MODULE_INITIALIZATION"
    binding, = [binding for binding in result.interfaces.bindings if binding.target == target.id]
    assert binding.status is CallBindingStatus.INCOMPLETE and binding.routes == ()
    assert BindingIssueKind.DECORATED_TARGET in {issue.kind for issue in binding.issues}
    assert not marker.exists()


def test_mutable_defaults_and_later_defaults_replacement_remain_conditional(tmp_path):
    result, file, _ = _inventory(tmp_path, """
        def target(items=[]):
            return items
        target.__defaults__ = None
        def caller():
            first = target()
            second = target()
            return first
    """)
    target = _definition(file, "target")
    signature = next(item for item in result.interfaces.signatures if item.definition == target.id)
    bindings = [binding for binding in result.interfaces.bindings if binding.target == target.id]
    assert len(bindings) == 2
    assert len({binding.call for binding in bindings}) == 2
    for binding in bindings:
        assert binding.status is CallBindingStatus.CONDITIONAL
        assert binding.arguments == ()
        route, = binding.routes
        assert route.origin is BindingOrigin.DEFAULT_STATE
        assert route.default_source == signature.parameters[0].default_source
        assert BindingCondition.FUNCTION_DEFAULT_STATE_MATCHES_SOURCE_DECLARATION in binding.conditions
        assert BindingCondition.RAW_FUNCTION_TARGET_MATCHES_SIGNATURE in binding.conditions
        assert BindingCondition.CALL_STATE_AND_FRAME_MAPPING_PRESERVED in binding.conditions
    assert any(entry.ast_kind == "Attribute" and entry.source.start_line == 3 for entry in file.coverage)
    assert result.summary()["transformation_authorized"] is False


def test_positional_only_name_in_kwargs_does_not_replace_its_default(tmp_path):
    result, file, _ = _inventory(tmp_path, """
        def target(a=0, /, **kwargs):
            return a
        def caller():
            return target(a=2)
    """)
    target = _definition(file, "target")
    binding, = [binding for binding in result.interfaces.bindings if binding.target == target.id]
    assert binding.status is CallBindingStatus.CONDITIONAL
    default, packed = binding.routes
    assert default.origin is BindingOrigin.DEFAULT_STATE and default.argument_indices == ()
    assert packed.origin is BindingOrigin.VAR_KEYWORD_PACK and packed.argument_indices == (0,)


def test_self_recursive_bound_body_does_not_retain_legacy_call_mapping(tmp_path):
    result, file, _ = _inventory(tmp_path, """
        def recursive(value):
            return recursive(value)
    """)
    body = _body(file, _definition(file, "recursive"))
    assert body.graph is not None
    target, = body.metadata.call_targets
    # This candidate already has a region, so legacy mapping would be tempting.
    assert target.candidate == body.graph.root
    assert target.arguments == target.results == ()
    assert all(op.callee is None for op in body.graph.operations)
    binding, = result.interfaces.bindings
    assert binding.status is CallBindingStatus.CONDITIONAL
    assert binding.routes[0].origin is BindingOrigin.ARGUMENT


@pytest.mark.parametrize("tamper", [
    "formal_name", "formal_kind", "formal_slot", "port_swap", "world_port",
    "route_actual_swap", "default_source", "argument_use", "overlay_profile", "body_profile",
])
def test_public_replay_rejects_wrong_interface_correspondence(all_formals_inventory, tamper):
    result, file, _ = all_formals_inventory
    document = deepcopy(result.to_dict())
    target = encode(_definition(file, "target").id)
    overlay = document["interfaces"]
    signature = next(item for item in overlay["signatures"] if item["definition"] == target)
    interface = next(item for item in overlay["bodies"] if item["definition"] == target)
    bindings = sorted((item for item in overlay["bindings"] if item["target"] == target),
                      key=lambda item: item["source"]["start_line"])
    explicit, defaulted = bindings
    if tamper == "formal_name":
        signature["parameters"][0]["name"] = "fabricated"
    elif tamper == "formal_kind":
        signature["parameters"][0]["kind"] = ParameterKind.POSITIONAL.value
    elif tamper == "formal_slot":
        left, right = signature["parameters"][:2]
        left["slot"], right["slot"] = right["slot"], left["slot"]
        left, right = interface["parameters"][:2]
        left["slot"], right["slot"] = right["slot"], left["slot"]
        for binding in bindings:
            left, right = binding["routes"][:2]
            left["slot"], right["slot"] = right["slot"], left["slot"]
    elif tamper == "port_swap":
        left, right = interface["parameters"][:2]
        left["value"], right["value"] = right["value"], left["value"]
    elif tamper == "world_port":
        other = next(item for item in overlay["bodies"] if item["definition"] != target)
        interface["world"] = other["world"]
    elif tamper == "route_actual_swap":
        left, right = explicit["routes"][:2]
        left["argument_indices"], right["argument_indices"] = right["argument_indices"], left["argument_indices"]
    elif tamper == "default_source":
        defaulted["routes"][1]["default_source"] = signature["parameters"][3]["default_source"]
    elif tamper == "argument_use":
        left, right = explicit["arguments"][:2]
        left["use"], right["use"] = right["use"], left["use"]
    elif tamper == "overlay_profile":
        overlay["profile"] = BodyLoweringProfile.LEGACY.value
    elif tamper == "body_profile":
        interface["profile"] = BodyLoweringProfile.LEGACY.value
    else:
        raise AssertionError(tamper)
    if tamper not in {"overlay_profile", "body_profile"}:
        # These edits are valid typed records: source replay must catch the lie.
        decode(FunctionInterfaces, overlay)
    with pytest.raises(ValueError):
        ProgramInventory.from_dict(document)


def test_legacy_profile_and_v1_replay_still_reject_default_body(tmp_path):
    result, file, path = _inventory(tmp_path, """
        def target(value=7):
            return value
    """)
    assert _body(file, _definition(file, "target")).graph is not None
    legacy_source = lower_source(path, "target")
    assert legacy_source.graph is None
    assert any(gap.kind.name == "UNSUPPORTED_SIGNATURE" for gap in legacy_source.metadata.gaps)
    legacy = _inventory_from_inputs(path, project_root=tmp_path, source_roots=(),
                                    budget=InventoryBudget(), interface_model=False)
    document = legacy.to_dict()
    assert document["schema_version"] == 1
    assert legacy.interfaces is legacy.runtime_scope is legacy.expansion is None
    assert all(body.graph is None for file in legacy.files for body in file.bodies)
    assert ProgramInventory.from_dict(document).to_dict() == document
    from scar.ir.program.inventory import ParameterKind as InventoryParameterKind
    assert InventoryParameterKind is ParameterKind


def test_failed_body_keeps_signature_but_no_ports_or_dangling_actual_uses(tmp_path):
    result, file, _ = _inventory(tmp_path, """
        def target(value=7):
            return value
        def broken(value):
            target(value)
            assert value
    """)
    broken = _definition(file, "broken")
    body = _body(file, broken)
    assert body.graph is None and body.construction_operations > 0
    assert body.metadata.operation_links == body.metadata.value_links == body.metadata.use_links == ()
    assert any(signature.definition == broken.id for signature in result.interfaces.signatures)
    assert all(interface.definition != broken.id for interface in result.interfaces.bodies)
    calls = {call.operation for call in file.calls if call.execution_owner == broken.id}
    for binding in result.interfaces.bindings:
        if binding.call in calls:
            assert all(argument.use is None for argument in binding.arguments)
    assert ProgramInventory.from_dict(result.to_dict()).to_dict() == result.to_dict()


def test_cross_file_routes_keep_caller_uses_and_callee_default_provenance(tmp_path):
    helper_path = tmp_path / "helper.py"
    helper_path.write_text("def target(value, *, option=[]):\n    return value\n", encoding="utf-8")
    result, caller_file, path = _inventory(tmp_path, """
        from helper import target
        def caller(value):
            return target(value)
    """)
    helper_file = next(file for file in result.files if file.snapshot.path == str(helper_path))
    target = _definition(helper_file, "target")
    signature = next(signature for signature in result.interfaces.signatures if signature.definition == target.id)
    binding, = [binding for binding in result.interfaces.bindings if binding.target == target.id]
    caller_body = _body(caller_file, _definition(caller_file, "caller"))
    target_body = _body(helper_file, target)
    assert caller_body.graph is not None and target_body.graph is not None
    assert binding.status is CallBindingStatus.CONDITIONAL
    assert binding.source.path == binding.arguments[0].source.path == str(path)
    assert binding.routes[1].origin is BindingOrigin.DEFAULT_STATE
    assert binding.routes[1].default_source == signature.parameters[1].default_source
    assert binding.routes[1].default_source.path == str(helper_path)
    caller_uses = {use.id for operation in caller_body.graph.operations for use in operation.uses}
    target_uses = {use.id for operation in target_body.graph.operations for use in operation.uses}
    assert binding.arguments[0].use in caller_uses
    assert binding.arguments[0].use not in target_uses
    call, = [call for call in caller_file.calls if call.operation == binding.call]
    assert call.candidate_witnesses[0].through_imports
    assert all(operation.callee is None for operation in caller_body.graph.operations)
    assert ProgramInventory.from_dict(result.to_dict()).to_dict() == result.to_dict()


def test_rejected_entry_interface_discards_links_but_charges_construction(tmp_path, monkeypatch):
    original = PreparedSource.lower
    constructed = {}

    def wrong_interface(self, entry, **kwargs):
        result = original(self, entry, **kwargs)
        if entry == "caller":
            assert result.graph is not None and result.interface is not None
            constructed[entry] = result.operations_emitted
            left, right = result.interface.parameters
            ports = (replace(left, value=right.value), replace(right, value=left.value))
            return replace(result, interface=replace(result.interface, parameters=ports))
        return result

    monkeypatch.setattr(PreparedSource, "lower", wrong_interface)
    result, file, _ = _inventory(tmp_path, """
        def target(left, right=7):
            return left
        def caller(left, right):
            return target(left, right)
    """)
    definition = _definition(file, "caller")
    body = _body(file, definition)
    assert body.status.name == "UNSUPPORTED" and body.graph is body.metadata is None
    assert "body interface correspondence failed" in body.reason
    assert body.construction_operations == constructed["caller"] > 0
    attempt = next(entry for entry in result.expansion.entries if entry.definition == definition.id)
    assert attempt.operation_budget_charged == attempt.construction_operations == constructed["caller"]
    assert attempt.construction_cost_known
    assert all(interface.definition != definition.id for interface in result.interfaces.bodies)
    calls = {call.operation for call in file.calls if call.execution_owner == definition.id}
    for binding in result.interfaces.bindings:
        if binding.call in calls:
            assert all(argument.use is None for argument in binding.arguments)
