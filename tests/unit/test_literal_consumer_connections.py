"""New exact abstract contents retain existing native-count correspondence guards."""
from dataclasses import replace

import pytest

from scar.ir.literals import PythonLiteral, literal_builtin_type
from scar.ir.execution.coordinates import ValueOccurrence
from scar.ir.execution.ids import ValueOccurrenceID
from scar.ir.execution.snapshot import snapshot_for
from scar.ir.execution.validation import validate
from scar.ir.program.ids import ValueID
from scar.ir.program.literal_sources import ExactLiteralOrigin
from scar.ir.program.model import DataValue
from tests.fixtures.execution_produced_graphs import byte_prefix_execution


@pytest.mark.parametrize('value', (4, 5, True, '4', complex(4, 0), float('inf')))
def test_new_exact_content_only_matches_native_byte_count_for_builtin_int(value):
    program, model, values, payloads = byte_prefix_execution()
    literal = PythonLiteral.from_python(value, exact=True)
    builtin = literal_builtin_type(literal)
    constant = DataValue(ValueID('new.native.count'), program.root, ExactLiteralOrigin(literal),
                         builtin.__module__+'.'+builtin.__qualname__)
    program = replace(program, values=(*program.values, constant))
    actual = ValueOccurrence(ValueOccurrenceID('new.native.count'), constant.id, model.activations[0].id)
    model = replace(model, snapshot=snapshot_for(program), values=(*model.values, actual),
        outcomes=(replace(model.outcomes[0], protocol_result=actual.id),))
    report = validate(model, program, value_graphs=values, artifact_bytes=payloads)
    if type(value) is int and value != 4:
        assert any(row.code == 'production_protocol_result' for row in report.issues)
    else:
        assert report.valid, report.issues
    if type(value) is not int:
        assert any(row.code == 'production_result_unresolved' for row in report.gaps)


def test_matching_exact_count_does_not_prove_original_host_return_port():
    from scar.ir.execution.common import Unresolved
    from scar.ir.execution.coordinates import OccurrencePhase, OccurrencePoint
    from scar.ir.execution.ids import EstablishedProductionID
    from scar.ir.execution.validity import EstablishedProduction
    from tests.fixtures.execution_produced_graphs import produced_execution
    program, model, values = produced_execution(host=True)
    constant = DataValue(ValueID('exact.host.count'), program.root,
                         ExactLiteralOrigin(PythonLiteral.from_python(4, exact=True)), 'builtins.int')
    program = replace(program, values=(*program.values, constant))
    actual = ValueOccurrence(ValueOccurrenceID('exact.host.count'), constant.id, model.activations[0].id)
    write = model.writes[0]
    unknown = Unresolved('native actual range and rule have not been decoded', model.activations[0].entry)
    established = EstablishedProduction(EstablishedProductionID('exact.host'), write.id,
        OccurrencePoint(write.writer.operation, OccurrencePhase.AFTER), unknown, actual.id, unknown, write.source)
    model = replace(model, snapshot=snapshot_for(program), values=(*model.values, actual),
                    established_productions=(established,))
    report = validate(model, program, value_graphs=values)
    assert report.valid, report.issues
    assert any(gap.code == 'validity_establishment_result_port_unverified' for gap in report.gaps)
