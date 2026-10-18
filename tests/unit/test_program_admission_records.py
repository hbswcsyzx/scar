"""Strict sixth contract records over original producers, not native behavior."""
from dataclasses import FrozenInstanceError, fields, replace
from typing import get_type_hints

import pytest

from scar.ir.program.ids import OperationID, UseID
from scar.ir.program.model import CompletionResult, InvokeLiteralResult, OperationResult
from scar.ir.program.protocol_rules import contract_allowed
from scar.ir.program.protocols import (
    ADMISSION_RECORD_TAGS, AdmissionPredicate, BodyStateCondition, BodyStatePredicateRule,
    ProtocolClause, ProtocolProfile, ReferenceIsNoneCondition,
)
from scar.ir.program.state_addresses import ExistingAccess, InvokeStateOperand
from scar.ir.program.structured import ControlEdgeReference
from scar.ir.record_codec import decode, encode


def _predicate(subject=None):
    return AdmissionPredicate(subject if subject is not None else BodyStateCondition(
        UseID("owner"), (ExistingAccess(OperationID("read"), 0),),
        BodyStatePredicateRule.IS_RUNNING), OperationResult(OperationID("read"), 0),
        OperationID("branch"))


@pytest.mark.parametrize("rule", tuple(BodyStatePredicateRule))
def test_readonly_body_condition_keeps_actual_sites_and_has_no_raw_or_phase_field(rule):
    row = _predicate(replace(_predicate().subject, rule=rule))
    assert tuple(field.name for field in fields(row.subject)) == (
        "instance_use", "state_sites", "rule")
    assert row.state_sites is row.subject.state_sites
    assert decode(AdmissionPredicate, encode(row, record_tags=ADMISSION_RECORD_TAGS),
                  record_tags=ADMISSION_RECORD_TAGS) == row
    assert get_type_hints(AdmissionPredicate)["result"] is OperationResult
    assert not hasattr(row, "__dict__") and not hasattr(row.subject, "__dict__")
    with pytest.raises(FrozenInstanceError):
        row.branch = OperationID("other")


def test_reference_condition_does_not_add_body_raw_state_or_permission_fields():
    row = _predicate(ReferenceIsNoneCondition(UseID("arg")))
    assert tuple(field.name for field in fields(row.subject)) == ("input_use",)
    assert tuple(field.name for field in fields(row)) == ("subject", "result", "branch")
    assert row.state_sites == ()
    wire = encode(row, record_tags=ADMISSION_RECORD_TAGS)
    assert set(wire) == {"subject", "result", "branch", "kind"}
    assert decode(AdmissionPredicate, wire, record_tags=ADMISSION_RECORD_TAGS) == row
    with pytest.raises(TypeError):
        AdmissionPredicate(row.subject, row.result, row.branch, verified=True)


@pytest.mark.parametrize("sites", [(), [], (InvokeStateOperand(OperationID("read"), UseID("s")),),
    (ExistingAccess(OperationID("read"), 0), ExistingAccess(OperationID("read"), 0))])
def test_body_sites_are_nonempty_exact_existing_accesses_without_duplicates(sites):
    with pytest.raises((TypeError, ValueError)):
        BodyStateCondition(UseID("owner"), sites, BodyStatePredicateRule.IS_CREATED)


def test_result_is_only_an_exact_ordinary_port_and_nested_ids_are_rechecked():
    class DerivedUse(UseID):
        pass

    class DerivedResult(OperationResult):
        pass

    row = _predicate()
    invoke = InvokeLiteralResult(ControlEdgeReference(OperationID("read"), 0), CompletionResult(0))
    for result in (invoke, DerivedResult(OperationID("read"), 0), True, {}):
        with pytest.raises((TypeError, ValueError)):
            replace(row, result=result)
    for subject in (True, {}, ReferenceIsNoneCondition(UseID("arg"))):
        if type(subject) is ReferenceIsNoneCondition:
            object.__setattr__(subject, "input_use", DerivedUse("arg"))
        with pytest.raises((TypeError, ValueError)):
            replace(row, subject=subject)
    for field, value in (("index", True), ("operation", "read")):
        result = OperationResult(OperationID("read"), 0)
        object.__setattr__(result, field, value)
        with pytest.raises((TypeError, ValueError)):
            replace(row, result=result)
    site = ExistingAccess(OperationID("read"), 0)
    object.__setattr__(site, "index", True)
    with pytest.raises((TypeError, ValueError)):
        replace(row.subject, state_sites=(site,))


def test_mutated_identifier_inner_text_and_noncanonical_rule_cannot_enter_condition():
    class Text(str):
        pass

    identity = OperationID("read")
    object.__setattr__(identity, "value", Text("read"))
    with pytest.raises(TypeError):
        BodyStateCondition(UseID("owner"), (ExistingAccess(identity, 0),),
                           BodyStatePredicateRule.IS_RUNNING)
    with pytest.raises(TypeError):
        replace(_predicate().subject, rule="IS_RUNNING")
    with pytest.raises(TypeError):
        replace(_predicate(), branch=True)


def test_sixth_contract_is_allowed_only_for_generator_raw_admission():
    row = _predicate()
    for profile in ProtocolProfile:
        for clause in ProtocolClause:
            assert contract_allowed(profile, clause, row) is (
                profile is ProtocolProfile.GENERATOR_BODY_V1
                and clause is ProtocolClause.RAW_ADMISSION)
