"""Module dictionary displays retain allocation and following source code."""
import hashlib
from pathlib import Path
import subprocess
import sys


def test_module_dictionary_displays_keep_the_following_subgraph(tmp_path):
    from scar.analysis.program_dependency_session import ProgramDependencySession
    from scar.ir.program.model import Behavior, BlockArgument, ReferenceValue

    project = tmp_path / 'source'
    project.mkdir()
    source = project / 'program.py'
    marker = tmp_path / 'must-not-execute'
    text = ('def value(item):\n    return item\n'
        'first = {}\nsecond = {}\n'
        'entries = {"left": value(1), value("right"): value(2)}\n'
        'merged = {**entries, "left": value(3)}\n'
        'argument = value({"inside": value(4)})\n'
        'value({})\nafter = value(99)\n'
        f'open({str(marker)!r}, "x").close()\n')
    source.write_text(text)
    source_hash = hashlib.sha256(source.read_bytes()).hexdigest()
    repository = Path(__file__).resolve().parents[2]
    model = tmp_path / 'model'
    built = subprocess.run([sys.executable, '-B', '-m', 'scar.cli', 'static', str(project),
        '--out', str(model), '--jobs', '1', '--phase', 'bodies'],
        cwd=repository, capture_output=True, text=True, timeout=40)
    assert built.returncode == 0, built.stdout + built.stderr
    assert not marker.exists()
    with ProgramDependencySession(model) as session:
        namespace, = session.select_bodies(file='program.py', kind='MODULE')
        body = session.load(namespace)
        overlay = body.module
        assert overlay.remaining is None
        blocks = {block.id: block for region in body.graph.regions for block in region.blocks}
        protocols = {row.operation: row for row in overlay.protocols}
        allocations = [row for row in overlay.protocols if row.kind.value == 'BUILD_MAP']
        assert len(allocations) >= 6
        assert any(row.kind.value == 'DICT_UPDATE' for row in overlay.protocols)
        refs = []
        for line in (3, 4):
            row, = (row for row in allocations if row.source.start_line == line)
            operation = body.index.operations[row.operation]
            assert Behavior.MEMORY in operation.behaviors
            normal = next(edge for edge in operation.terminator.successors if edge.kind.value == 'NORMAL')
            value = body.index.values[blocks[normal.block].arguments[0]]
            assert type(value) is ReferenceValue and type(value.origin) is BlockArgument
            refs.append(value.id)
        assert refs[0] != refs[1]
        after_line = text.splitlines().index('after = value(99)') + 1
        assert any(getattr(link.source, 'start_line', None) == after_line and link.opcode is not None
            and link.opcode.value == 'call' for link in overlay.operation_links)
        # Native dictionary updates preserve their exceptional post-world;
        # a possible failure must not be turned into a pure constant display.
        for identity, protocol in protocols.items():
            if protocol.kind.value not in ('BUILD_MAP', 'DICT_UPDATE', 'MAP_ADD'):
                continue
            operation = body.index.operations[identity]
            assert {edge.kind.value for edge in operation.terminator.successors} == {'NORMAL', 'RAISE'}
            assert operation.effects_complete is False
    assert hashlib.sha256(source.read_bytes()).hexdigest() == source_hash
