"""Durability boundaries, with syscall failures rather than power-loss claims."""
import json
import os
from pathlib import Path

import pytest

from scar.analysis.source_stage import SourceStage, _durable_bytes
from scar.analysis.static_program import _json, _write, read_static_program


def _model(tmp_path):
    root = tmp_path / 'model'
    root.mkdir()
    descriptor = _write(root, 'units/0/source.json.gz', {'source': 'unchanged'})
    manifest = {'schema': 'scar.static-program', 'schema_version': 1,
        'units': [{'key': '0', 'artifacts': {'source': descriptor}, 'bodies': []}],
        'remaining': [], 'source_issues': []}
    original = _json(manifest)
    (root / 'manifest.json').write_bytes(original)
    return root, original


def _rows(stage):
    descriptor = _write(stage.staging, 'units/0/source_syntax.json.gz', {'syntax': 'complete'})
    return [{'unit': '0', 'artifact': descriptor}]


def test_source_stage_syncs_contents_and_names_before_old_cleanup(tmp_path, monkeypatch):
    import scar.analysis.source_stage as storage
    root, original = _model(tmp_path)
    out, events = tmp_path / 'new' / 'report', []
    fsync, rename, cleanup, link = os.fsync, Path.rename, storage._remove_owned_previous, os.link

    def synced(fd):
        events.append(('sync', os.readlink('/proc/self/fd/' + str(fd))))
        return fsync(fd)
    def renamed(path, target):
        result = rename(path, target)
        events.append(('rename', str(path), str(target)))
        return result
    def cleaned(*args):
        events.append(('cleanup', str(args[0])))
        return cleanup(*args)
    def linked(source, target, *args, **kwargs):
        if Path(target) == out / 'result.json':
            assert json.loads(Path(source).read_bytes())['complete'] is True
            events.append(('report', str(source), str(target)))
        return link(source, target, *args, **kwargs)
    monkeypatch.setattr(os, 'fsync', synced)
    monkeypatch.setattr(Path, 'rename', renamed)
    monkeypatch.setattr(storage, '_remove_owned_previous', cleaned)
    monkeypatch.setattr(os, 'link', linked)
    with SourceStage(root, out, artifact='source_syntax', verify=False,
            consumes=('source', 'source_syntax')) as stage:
        staging = stage.staging
        stage.publish(_rows(stage), {'stage': 'F2'})
        stage.finish({'complete': True})
    renames = [i for i, event in enumerate(events) if event[0] == 'rename']
    assert len(renames) == 2
    first, second = renames
    assert ('sync', str(staging / 'units/0/source_syntax.json.gz')) in events[:first]
    assert ('sync', str(staging / 'units/0')) in events[:first]
    assert ('sync', str(staging / 'manifest.json')) in events[:first]
    assert ('sync', str(root.parent)) in events[first + 1:second]
    cleanup_index = next(i for i, event in enumerate(events) if event[0] == 'cleanup')
    assert ('sync', str(root.parent)) in events[second + 1:cleanup_index]
    report_index = next(i for i, event in enumerate(events) if event[0] == 'report')
    temporary = events[report_index][1]
    assert ('sync', temporary) in events[:report_index]
    assert ('sync', str(out)) in events[report_index + 1:]
    assert (root / 'manifest.json').read_bytes() != original
    read_static_program(root, verify=True)
    assert list(out.iterdir()) == [out / 'result.json']


@pytest.mark.parametrize('failure', ('sidecar_sync', 'sidecar_receipt', 'first_rename_sync', 'second_rename_sync'))
def test_source_stage_failures_never_delete_the_last_durable_model(tmp_path, monkeypatch, failure):
    import scar.analysis.source_stage as storage
    root, original = _model(tmp_path)
    out = tmp_path / 'report'
    sync_file, sync_directory = storage._sync_file, storage._sync_directory
    with SourceStage(root, out, artifact='source_syntax', verify=False,
            consumes=('source', 'source_syntax')) as stage:
        rows = _rows(stage)
        staging = stage.staging
        if failure == 'sidecar_receipt':
            (staging / rows[0]['artifact']['path']).write_bytes(b'')
        def file_boundary(path, descriptor=None):
            if failure == 'sidecar_sync' and descriptor is not None:
                raise OSError('injected file fsync failure')
            return sync_file(path, descriptor)
        def directory_boundary(path):
            if path == root.parent:
                if failure == 'first_rename_sync' and not root.exists():
                    raise OSError('injected first rename fsync failure')
                if failure == 'second_rename_sync' and root.exists() and not staging.exists():
                    raise OSError('injected second rename fsync failure')
            return sync_directory(path)
        monkeypatch.setattr(storage, '_sync_file', file_boundary)
        monkeypatch.setattr(storage, '_sync_directory', directory_boundary)
        with pytest.raises((OSError, ValueError), match='injected|receipt'):
            stage.publish(rows, {'stage': 'F2'})
        if failure == 'second_rename_sync':
            previous = Path(stage.retained_previous)
            assert previous.exists() and (previous / 'manifest.json').read_bytes() == original
            read_static_program(root, verify=True)
        else:
            assert (root / 'manifest.json').read_bytes() == original
    assert not staging.exists() and not out.exists()


def test_durable_report_publication_does_not_overwrite_existing_report(tmp_path):
    target = tmp_path / 'result.json'
    target.write_bytes(b'preserve this report')
    with pytest.raises(FileExistsError):
        _durable_bytes(target, b'{"new":"complete"}', replace=False)
    assert target.read_bytes() == b'preserve this report'
    assert list(tmp_path.iterdir()) == [target]
