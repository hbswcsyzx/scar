"""Real inherited compiler contexts through capture, seeds and inventory CLI."""
from collections import defaultdict
from dataclasses import dataclass
import json
import os
from pathlib import Path

import pytest

from scar.analysis.call_demand import inventory_from_calls
from scar.analysis.call_seeds import CallSourceSeedReport, read_call_source_seeds
from scar.analysis.program_inventory import ProgramInventory
from scar.ir.program.call_edges import CallEdgeBudget
from scar.ir.program.compilation import CallCompilationProfile
from scar.ir.program.expansion import ContextStoreBudget
from scar.ir.program.inventory import InventoryBudget
from tests.integration.test_call_source_seeds_cli import cli, read


LEGACY = CallCompilationProfile.LEGACY_ZERO_FLAGS
RECORDED = CallCompilationProfile.RECORDED_FUTURE_FLAGS


@dataclass(frozen=True)
class Capture:
    project: Path
    entry: Path
    trace: Path
    marker: Path
    sources: dict


def _capture(directory, *, mixed=False, nested=False, nonpy_schema=None):
    project = directory / 'project'
    project.mkdir(parents=True)
    helper = project / 'helper.py'
    helper.write_text('def identity(value):\n    return value\n'
                      'def relay(value):\n    return identity(value)\n' +
                      ('def make():\n    def nested(value):\n        return value\n    return nested\n' if nested else ''))
    marker = project / 'executed'
    entry = project / 'entry.py'
    entry.write_text('from helper import relay' + (', make' if nested else '') + '\n'
                     'def run(value):\n    return relay(value)\n'
                     'value = object()\nassert run(value) is value\n' +
                     ('assert make()(value) is value\n' if nested else '') +
                     f'open({str(marker)!r}, "w").write("ran")\n')
    extra = project / 'captured.json'
    if nonpy_schema:
        extra.write_text(json.dumps({'schema': nonpy_schema}))
    driver = directory / 'driver.py'
    # No flags are patched into captured descriptors. compile() is actually
    # called inside an executing parent carrying future annotations, then the
    # resulting module/function code is automatically recorded by public CLI.
    driver.write_text('from __future__ import annotations\n'
                      'import sys\nfrom pathlib import Path\nfrom types import ModuleType\n'
                      f'project = Path({str(project)!r})\n'
                      f'for inherited in {([False, True] if mixed else [True])!r}:\n'
                      '    module = ModuleType("helper")\n'
                      '    source = project / "helper.py"\n'
                      '    code = (compile(source.read_text(), str(source), "exec") if inherited else\n'
                      '            compile(source.read_text(), str(source), "exec", flags=0, dont_inherit=True))\n'
                      '    exec(code, module.__dict__)\n'
                      '    sys.modules["helper"] = module\n'
                      '    source = project / "entry.py"\n'
                      '    code = (compile(source.read_text(), str(source), "exec") if inherited else\n'
                      '            compile(source.read_text(), str(source), "exec", flags=0, dont_inherit=True))\n'
                      '    exec(code, {})\n' +
                      ('source = project / "captured.json"\n'
                       'exec(compile(source.read_text(), str(source), "exec"), {})\n' if nonpy_schema else ''))
    trace = directory / 'trace'
    import sys
    process = cli('trace', '--calls-only', '--project-root', project, '--out', trace,
                  '--', sys.executable, driver, cwd=project)
    assert process.returncode == 0, process.stdout + process.stderr
    assert marker.read_text() == 'ran'
    marker.unlink()
    sources = {path: path.read_bytes() for path in project.iterdir() if path.is_file()}
    return Capture(project, entry, trace, marker, sources)


@pytest.fixture(scope='module')
def inherited(tmp_path_factory):
    return _capture(tmp_path_factory.mktemp('inherited-compilation'))


@pytest.fixture(scope='module')
def mixed(tmp_path_factory):
    return _capture(tmp_path_factory.mktemp('mixed-compilation'), mixed=True, nested=True)


def _assert_not_executed(capture):
    assert not capture.marker.exists()
    assert all(path.read_bytes() == content for path, content in capture.sources.items())


def _seed(capture, output):
    process = cli('seed-calls', capture.trace, '--project-root', capture.project, '--out', output)
    assert process.returncode == 0, process.stdout + process.stderr
    return read(output)


def _inventory(capture, output):
    process = cli('inventory-program', capture.entry, '--project-root', capture.project,
                  '--calls', capture.trace, '--out', output)
    assert process.returncode == 0, process.stdout + process.stderr
    return read(output)


def _legacy_inventory(capture):
    return inventory_from_calls(
        capture.entry, project_root=capture.project, source_roots=(), budget=InventoryBudget(),
        call_trace=capture.trace, call_budget=CallEdgeBudget(), context_budget=ContextStoreBudget(),
        compilation_profile=LEGACY)


def _entered(capture, document):
    groups = {group['code'] for group in document['model']['groups']}
    return {row['code']['key']: row['code'] for row in document['model']['codes']
            if row['code']['key'] in groups
            and Path(row['code']['filename']).is_relative_to(capture.project)}


def _assert_source_links(document, codes):
    links = {link['code']: link for link in document['model']['code_links']}
    assert codes and all(links[key]['status'] == 'VERIFIED' for key in codes)
    for key, code in codes.items():
        assert links[key]['snapshot']['path'] == code['filename']
        assert links[key]['optimize_levels']


def _assert_core_admissions(document, expected_names):
    names = {definition['id']['wire']: definition['name']
             for file in document['files'] for definition in file['definitions']}
    roots = {body['definition']['wire']: body['graph']['root']
             for file in document['files'] for body in file['bodies'] if body['graph'] is not None}
    admissions = [admission for admission in document['call_source_scope']['admissions']
                  if admission['definition'] is not None
                  and names[admission['definition']['wire']] in expected_names]
    assert {names[item['definition']['wire']] for item in admissions} == set(expected_names)
    assert all(item['status'] == 'CORE_LINKED'
               and item['core_region'] == roots[item['definition']['wire']] for item in admissions)
    assert document['transformation_authorized'] is False
    assert document['summary']['whole_program_graph_established'] is False


@pytest.mark.parametrize('suffix', ['.json', '.json.gz'])
def test_actual_parent_future_capture_to_seed_v2_inventory_v6_and_public_replay(inherited, tmp_path, suffix):
    seed_path = tmp_path / ('seed' + suffix)
    seed = _seed(inherited, seed_path)
    assert seed['schema_version'] == 2 and seed['compilation_profile'] == RECORDED.value
    codes = _entered(inherited, seed)
    assert {'<module>', 'run', 'relay', 'identity'} <= {code['qualname'] for code in codes.values()}
    assert all(code['flags'] & 0x1000000 for code in codes.values())
    _assert_source_links(seed, codes)
    assert CallSourceSeedReport.from_dict(seed).to_dict() == seed
    replay = cli('check-call-seeds', seed_path)
    assert replay.returncode == 0, replay.stdout + replay.stderr
    assert json.loads(replay.stdout)['status'] == 'REPLAYED'
    inventory_path = tmp_path / ('inventory' + suffix)
    inventory = _inventory(inherited, inventory_path)
    assert inventory['schema_version'] == 6 and inventory['call_sources'] == seed
    _assert_core_admissions(inventory, {'run', 'relay', 'identity'})
    replay = cli('check-inventory', inventory_path)
    assert replay.returncode == 0, replay.stdout + replay.stderr
    assert json.loads(replay.stdout)['status'] == 'REPLAYED'
    _assert_not_executed(inherited)


def test_explicit_legacy_seed_v1_keeps_actual_future_code_mismatches_and_replays(inherited, tmp_path):
    report = read_call_source_seeds(inherited.trace, inherited.project, compilation_profile=LEGACY)
    document = report.to_dict()
    assert document['schema_version'] == 1 and 'compilation_profile' not in document
    codes = _entered(inherited, document)
    statuses = {link['code']: link['status'] for link in document['model']['code_links']}
    assert codes and all(statuses[key] == 'MISMATCH' for key in codes)
    assert report.eligible_groups() == ()
    assert CallSourceSeedReport(report.model).to_dict() == document
    assert CallSourceSeedReport.from_dict(document).to_dict() == document
    path = tmp_path / 'legacy-seed.json'
    path.write_text(json.dumps(document))
    replay = cli('check-call-seeds', path)
    assert replay.returncode == 0, replay.stdout + replay.stderr
    _assert_not_executed(inherited)


def test_legacy_v6_nested_seed_v1_replays_without_upgrading_source_claims(inherited, tmp_path):
    result = _legacy_inventory(inherited)
    document = result.to_dict()
    assert document['schema_version'] == 6
    assert document['call_sources']['schema_version'] == 1
    assert 'compilation_profile' not in document['call_sources']
    assert result.call_sources.eligible_groups() == () and result.call_source_scope.admissions == ()
    project_codes = _entered(inherited, document['call_sources'])
    links = {link.code: link for link in result.call_sources.model.code_links}
    assert project_codes and all(links[key].status.value == 'MISMATCH' for key in project_codes)
    # Writing the execution marker can also enter a frozen codecs frame. Its
    # source boundary must remain visible rather than be called a mismatch.
    assert any(issue.kind.value == 'SOURCE_BOUNDARY'
               for key, link in links.items() if key not in project_codes for issue in link.issues)
    assert ProgramInventory.from_dict(document).to_dict() == document
    output = tmp_path / 'legacy-v6.json'
    output.write_text(json.dumps(document))
    replay = cli('check-inventory', output)
    assert replay.returncode == 0, replay.stdout + replay.stderr
    _assert_not_executed(inherited)


def test_same_source_multiple_real_compilation_contexts_and_nested_code_do_not_share_wrong_trials(mixed, tmp_path):
    output = tmp_path / 'mixed-seeds.json.gz'
    document = _seed(mixed, output)
    codes = _entered(mixed, document)
    by_source = defaultdict(set)
    for code in codes.values():
        by_source[(code['filename'], code['qualname'])].add(bool(code['flags'] & 0x1000000))
    assert all(contexts == {False, True} for contexts in by_source.values())
    assert any(name == 'make.<locals>.nested' for _, name in by_source)
    _assert_source_links(document, codes)
    assert CallSourceSeedReport.from_dict(document).to_dict() == document
    inventory_path = tmp_path / 'mixed-inventory.json.gz'
    inventory = _inventory(mixed, inventory_path)
    assert inventory['call_sources'] == document
    _assert_core_admissions(inventory, {'run', 'relay', 'identity'})
    definitions = [task['definition']['wire'] for task in inventory['expansion']['entries']]
    assert len(definitions) == len(set(definitions))
    replay = cli('check-inventory', inventory_path)
    assert replay.returncode == 0, replay.stdout + replay.stderr
    _assert_not_executed(mixed)


@pytest.mark.parametrize('nested', [False, True])
@pytest.mark.parametrize('mutation', ['missing', 'unknown', 'wrong_profile', 'bool_version', 'extra_v1_profile'])
def test_profile_structure_rejected_before_raw_io(inherited, tmp_path, nested, mutation):
    document = (_inventory(inherited, tmp_path / 'original-inventory.json') if nested else
                _seed(inherited, tmp_path / 'original-seed.json'))
    target = document['call_sources'] if nested else document
    if mutation == 'missing':
        del target['compilation_profile']
    elif mutation == 'unknown':
        target['compilation_profile'] = 'INVENTED_COMPILER_CONTEXT'
    elif mutation == 'wrong_profile':
        target['compilation_profile'] = LEGACY.value
    elif mutation == 'bool_version':
        target['schema_version'] = True
    else:
        target['schema_version'] = 1
    output = tmp_path / 'tampered.json'
    output.write_text(json.dumps(document))
    moved = inherited.trace.with_name('trace-temporarily-unavailable')
    inherited.trace.rename(moved)
    try:
        process = cli('check-inventory' if nested else 'check-call-seeds', output)
    finally:
        moved.rename(inherited.trace)
    assert process.returncode == 2 and json.loads(process.stdout)['status'] == 'INVALID'
    assert 'call trace must be a directory' not in process.stdout
    assert any(term in process.stdout for term in ('profile', 'fields', 'schema', 'version'))
    _assert_not_executed(inherited)


@pytest.mark.parametrize('nested', [False, True])
@pytest.mark.parametrize('option', ['--max-call-trace-events', '--max-call-references'])
@pytest.mark.parametrize('profile', [LEGACY, RECORDED])
def test_independent_call_budget_precedes_raw_io_for_both_report_versions(inherited, tmp_path, nested, option, profile):
    if profile is LEGACY:
        document = (_legacy_inventory(inherited).to_dict() if nested else
                    read_call_source_seeds(inherited.trace, inherited.project,
                                           compilation_profile=LEGACY).to_dict())
    else:
        document = (_inventory(inherited, tmp_path / 'original-inventory.json') if nested else
                    _seed(inherited, tmp_path / 'original-seed.json'))
    output = tmp_path / 'report.json'
    output.write_text(json.dumps(document))
    moved = inherited.trace.with_name('trace-temporarily-unavailable')
    inherited.trace.rename(moved)
    try:
        process = cli('check-inventory' if nested else 'check-call-seeds', output, option, 1)
    finally:
        moved.rename(inherited.trace)
    assert process.returncode == 2 and 'independent verifier budget' in process.stdout
    assert 'call trace must be a directory' not in process.stdout
    _assert_not_executed(inherited)


def test_flags_tampering_cannot_match_by_source_name_or_line(inherited, tmp_path):
    trace = tmp_path / 'changed-calls'
    trace.mkdir()
    for path in inherited.trace.iterdir():
        (trace / path.name).write_bytes(path.read_bytes())
    codes_path, = trace.glob('call-codes.*.jsonl')
    rows = [json.loads(line) for line in codes_path.read_text().splitlines()]
    changed = next(row for row in rows if row['qualname'] == 'identity'
                   and row['filename'] == str(inherited.project / 'helper.py'))
    original_key = changed['key']
    changed['flags'] &= ~0x1000000
    codes_path.write_text(''.join(json.dumps(row) + '\n' for row in rows))
    metadata_path, = trace.glob('call-meta.*.json')
    metadata = json.loads(metadata_path.read_text())
    metadata['bytes'] = sum(path.stat().st_size for family in ('codes', 'events')
                            for path in trace.glob(f'call-{family}.*.jsonl'))
    metadata_path.write_text(json.dumps(metadata))
    output = tmp_path / 'changed-seed.json'
    process = cli('seed-calls', trace, '--project-root', inherited.project, '--out', output)
    assert process.returncode == 0, process.stdout + process.stderr
    document = read(output)
    link, = (link for link in document['model']['code_links'] if link['code'] == original_key)
    assert link['status'] == 'MISMATCH' and link['definition'] is None and link['source'] is None
    assert any(issue['kind'] == 'CODE_MISMATCH' for issue in link['issues'])
    replay = cli('check-call-seeds', output)
    assert replay.returncode == 0, replay.stdout + replay.stderr
    _assert_not_executed(inherited)


def test_recorded_source_snapshot_drift_rejects_old_v2_report(tmp_path):
    capture = _capture(tmp_path)
    output = tmp_path / 'seed.json'
    _seed(capture, output)
    helper = capture.project / 'helper.py'
    helper.write_text(helper.read_text() + '\n# current source differs\n')
    replay = cli('check-call-seeds', output)
    assert replay.returncode == 2 and 'replay' in replay.stdout
    assert not capture.marker.exists()


@pytest.mark.parametrize('command,schema', [('seed-calls', 'scar.call-source-seeds'),
                                           ('inventory-program', 'scar.program-inventory')])
@pytest.mark.parametrize('hardlink', [False, True])
def test_recorded_profile_protects_captured_nonpy_source_outputs(tmp_path, command, schema, hardlink):
    capture = _capture(tmp_path, nonpy_schema=schema)
    source = capture.project / 'captured.json'
    destination = tmp_path / 'captured-alias.json' if hardlink else source
    if hardlink:
        os.link(source, destination)
    before = source.read_bytes()
    first = capture.entry if command == 'inventory-program' else capture.trace
    arguments = [command, first, '--project-root', capture.project, '--out', destination,
                 '--max-call-source-bytes', 1]
    if command == 'inventory-program':
        arguments.extend(['--calls', capture.trace])
    process = cli(*arguments)
    assert process.returncode == 2 and 'differ from' in process.stdout
    assert source.read_bytes() == destination.read_bytes() == before
    _assert_not_executed(capture)
