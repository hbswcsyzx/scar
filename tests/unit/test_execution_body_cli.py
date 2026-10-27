"""CLI body queries keep original wire IDs, missing evidence and input bytes."""
from dataclasses import replace
import json

import pytest

from scar.cli import main
from scar.ir.execution.codec import dumps as dump_execution
from scar.ir.program.codec import dumps as dump_program
from tests.fixtures.execution_resumable_graphs import resumable_execution


def _files(tmp_path, *, missing=None):
    program, model, details = resumable_execution()
    if missing is not None:
        first, second = model.body_drive_executions
        model = replace(model, body_drive_executions=(replace(first, **{missing: details['gap']}), second))
    paths = (tmp_path / 'program.json', tmp_path / 'execution.json')
    payloads = (dump_program(program).encode('utf-8'), dump_execution(model).encode('utf-8'))
    for path, payload in zip(paths, payloads, strict=True):
        path.write_bytes(payload)
    return program, model, details, paths, payloads


def _argv(paths, flag, wire, *extra):
    return ['query-body-execution', *(str(path) for path in paths), flag, wire, *extra]


def _unchanged(paths, payloads):
    assert tuple(path.read_bytes() for path in paths) == payloads


@pytest.mark.parametrize('number', (0, 1))
def test_cli_drive_uses_original_codec_occurrence_ids_and_keeps_missing_external_evidence(number, tmp_path, capsys):
    _, model, details, paths, payloads = _files(tmp_path)
    drive = details['instances'][0]['drives'][number]
    assert main(_argv(paths, '--drive', drive.wire)) == 0
    report = json.loads(capsys.readouterr().out)
    view = report['query']
    assert report['status'] == 'PARTIAL' and view['status'] == 'DECLARED'
    assert view['drive']['id'] == drive.as_dict()
    assert view['association']['drive'] == drive.as_dict()
    assert view['association']['activation'] == model.body_drive_executions[number].activation.as_dict()
    assert view['input_count'] in (8, 5) and view['output_count'] == 3
    assert any(gap['code'] == 'external_graph_unavailable' for gap in report['validation_gaps'])
    assert report['validation_gaps'] == view['validation_gaps']
    assert report['source_runtime_verified'] is report['transformation_authorized'] is False
    assert view['runtime_identity_verified'] is view['value_identity_verified'] is False
    _unchanged(paths, payloads)


def test_cli_activation_projects_capture_keys_to_full_namespace_without_faking_identity(tmp_path, capsys):
    _, model, details, paths, payloads = _files(tmp_path)
    activation = details['instances'][0]['activation']
    assert main(_argv(paths, '--activation', activation.wire)) == 0
    report = json.loads(capsys.readouterr().out)
    view = report['query']
    assert view['association']['activation'] == activation.as_dict()
    assert view['creation']['id'] == model.body_activation_origins[0].creation.as_dict()
    assert len(view['captures']) == 6
    for key, capture in view['captures'].items():
        assert key == capture['definition']['formal']['wire'] and key.startswith('program_value:')
    assert view['drives'] == [drive.as_dict() for drive in details['instances'][0]['drives']]
    assert report['status'] == 'PARTIAL' and view['status'] == 'DECLARED'
    assert any(gap['code'] == 'external_graph_unavailable' for gap in report['validation_gaps'])
    assert report['validation_gaps'] == view['validation_gaps']
    _unchanged(paths, payloads)


@pytest.mark.parametrize('subject', ('drive', 'activation'))
def test_cli_budget_one_keeps_full_port_denominators_and_cursor(subject, tmp_path, capsys):
    _, _, details, paths, payloads = _files(tmp_path)
    instance = details['instances'][0]
    identity = instance['drives'][0] if subject == 'drive' else instance['activation']
    assert main(_argv(paths, '--' + subject, identity.wire, '--budget', '1')) == 0
    report = json.loads(capsys.readouterr().out)
    view = report['query']
    assert view['budget']['limit'] == view['budget']['used'] == 1
    assert view['budget']['truncated'] and view['cursor'] is not None
    if subject == 'drive':
        assert view['input_count'] == len(view['inputs']) == 8
        assert view['output_count'] == len(view['outputs']) == 3
        assert any(binding['check_status'] == 'NOT_CHECKED' for binding in view['inputs'])
    else:
        assert len(view['captures']) == 6 and len(view['drives']) == 2
    _unchanged(paths, payloads)


@pytest.mark.parametrize('endpoint', ('entry', 'outcome'))
def test_cli_missing_endpoint_remains_explicit_and_does_not_erase_other_endpoint(endpoint, tmp_path, capsys):
    _, model, _, paths, payloads = _files(tmp_path, missing=endpoint)
    first = model.body_drive_executions[0]
    assert main(_argv(paths, '--drive', first.drive.wire)) == 0
    view = json.loads(capsys.readouterr().out)['query']
    assert view[endpoint] is None
    assert view['association'][endpoint]['reason'] == getattr(first, endpoint).reason
    assert view['outcome' if endpoint == 'entry' else 'entry'] is not None
    assert view['status'] == 'PARTIAL'
    _unchanged(paths, payloads)


@pytest.mark.parametrize('flag,wire', (
    ('--drive', 'not-a-wire'), ('--drive', 'exec_operation_occurrence:'),
    ('--drive', 'exec_region_activation:wrong-family'),
    ('--activation', 'exec_operation_occurrence:wrong-family'),
    ('--drive', 'exec_operation_occurrence:absent'),
    ('--activation', 'exec_region_activation:absent'),
))
def test_cli_strict_wire_identity_errors_return_two_and_preserve_inputs(flag, wire, tmp_path, capsys):
    _, _, _, paths, payloads = _files(tmp_path)
    assert main(_argv(paths, flag, wire)) == 2
    report = json.loads(capsys.readouterr().out)
    assert report['status'] == 'ERROR' and report['errors']
    assert report['source_runtime_verified'] is report['transformation_authorized'] is False
    _unchanged(paths, payloads)


@pytest.mark.parametrize('subject', ('drive', 'activation'))
def test_cli_known_id_of_wrong_canonical_kind_is_not_selected_by_region_or_name(subject, tmp_path, capsys):
    _, model, _, paths, payloads = _files(tmp_path)
    identity = model.body_activation_origins[0].creation if subject == 'drive' else model.activations[0].id
    assert main(_argv(paths, '--' + subject, identity.wire)) == 2
    assert json.loads(capsys.readouterr().out)['status'] == 'ERROR'
    _unchanged(paths, payloads)


@pytest.mark.parametrize('family,corruption', ((0, 'syntax'), (0, 'duplicate'), (1, 'syntax'), (1, 'unknown-field')))
def test_cli_strict_codecs_reject_malformed_wire_without_repairing_inputs(family, corruption, tmp_path, capsys):
    _, _, details, paths, _ = _files(tmp_path)
    if corruption == 'syntax':
        paths[family].write_text('{', encoding='utf-8')
    elif corruption == 'duplicate':
        original = paths[family].read_text(encoding='utf-8')
        paths[family].write_text('{"schema":"scar.program-graph",' + original[1:], encoding='utf-8')
    else:
        document = json.loads(paths[family].read_text(encoding='utf-8'))
        document['forged_authority'] = True
        paths[family].write_text(json.dumps(document), encoding='utf-8')
    payloads = tuple(path.read_bytes() for path in paths)
    assert main(_argv(paths, '--drive', details['instances'][0]['drives'][0].wire)) == 2
    assert json.loads(capsys.readouterr().out)['status'] == 'ERROR'
    _unchanged(paths, payloads)


@pytest.mark.parametrize('which', (0, 1, 'symlink'))
def test_cli_output_cannot_overwrite_either_input_even_via_resolved_symlink(which, tmp_path, capsys):
    _, _, details, paths, payloads = _files(tmp_path)
    output = paths[which] if which != 'symlink' else tmp_path / 'alias.json'
    if which == 'symlink':
        output.symlink_to(paths[1])
    assert main(_argv(paths, '--drive', details['instances'][0]['drives'][0].wire,
                      '--out', str(output))) == 2
    report = json.loads(capsys.readouterr().out)
    assert report['status'] == 'ERROR' and 'differ from both' in report['errors'][0]
    _unchanged(paths, payloads)


def test_cli_output_document_matches_machine_stdout_and_keeps_original_inputs(tmp_path, capsys):
    _, _, details, paths, payloads = _files(tmp_path)
    output = tmp_path / 'query' / 'report.json'
    assert main(_argv(paths, '--drive', details['instances'][0]['drives'][0].wire,
                      '--out', str(output))) == 0
    assert output.read_text(encoding='utf-8') == capsys.readouterr().out
    assert json.loads(output.read_text(encoding='utf-8'))['transformation_authorized'] is False
    _unchanged(paths, payloads)


def test_cli_invalid_budget_is_error_without_creating_output(tmp_path, capsys):
    _, _, details, paths, payloads = _files(tmp_path)
    output = tmp_path / 'not-written.json'
    assert main(_argv(paths, '--drive', details['instances'][0]['drives'][0].wire,
                      '--budget', '0', '--out', str(output))) == 2
    assert json.loads(capsys.readouterr().out)['status'] == 'ERROR'
    assert not output.exists()
    _unchanged(paths, payloads)
