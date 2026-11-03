"""The strict indexed loader validates once, without admitting bad wire/core."""
import json
from pathlib import Path

import pytest


def test_indexed_codec_shares_strict_decode_and_one_full_validation(monkeypatch):
    from scar.ir.program import codec, validation
    from scar.ir.program.queries import ProgramIndex

    validate, prepare = validation.validate, ProgramIndex._prepare
    checked, prepared = [], []

    def check(graph, **kwargs):
        checked.append(graph)
        return validate(graph, **kwargs)

    def build(index, graph, *facts):
        prepared.append(graph)
        return prepare(index, graph, *facts)

    monkeypatch.setattr(validation, 'validate', check)
    monkeypatch.setattr(ProgramIndex, '_prepare', build)
    fixtures = Path(__file__).parents[1] / 'fixtures'
    for version in (2, 19):
        # v2 prepares after validation; v19 reuses the index prepared inside
        # the validator for protocol-connection checks. Both must run once.
        payload = (fixtures / f'program_graph_v{version}_frozen.json').read_text()
        ordinary = codec.loads(payload)
        checked.clear(); prepared.clear()
        graph, index = codec._loads_with_index(payload)
        assert graph == ordinary and type(index) is ProgramIndex and index.graph is graph
        assert checked == [graph] and prepared == [graph]
        assert index.operations == {operation.id: operation for operation in graph.operations}
        assert index.values == {value.id: value for value in graph.values}

    document = json.loads((fixtures / 'program_graph_v2_frozen.json').read_text())
    invalid_core = json.loads(json.dumps(document))
    invalid_core['root'].update(value='missing-root', wire='program_region:missing-root')
    extra = dict(document, unexpected=True)
    wrong_id = json.loads(json.dumps(document))
    wrong_id['root']['kind'] = 'program_value'
    duplicate = json.dumps(document)[:-1] + ',"schema_version":2}'
    for payload, full_checks in ((json.dumps(invalid_core), 1), (json.dumps(extra), 0),
                                 (json.dumps(wrong_id), 0), (duplicate, 0)):
        errors = []
        for loader in (codec.loads, codec._loads_with_index):
            checked.clear(); prepared.clear()
            with pytest.raises((TypeError, ValueError)) as raised:
                loader(payload)
            assert len(checked) == full_checks
            errors.append((type(raised.value), str(raised.value)))
        assert errors[0] == errors[1]
