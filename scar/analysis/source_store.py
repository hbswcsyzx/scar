"""Shared source receipts and material-store ownership, without stage policy."""
from pathlib import Path
import json

from scar.analysis.source_materials import _matches, _source_envelope, _stamps


REQUIRED_SOURCE_ARTIFACTS = ('source', 'source_bytes', 'source_tokens', 'source_syntax')


def source_input_basis(units):
    return [{**{name: unit[name] for name in ('key', 'path', 'namespace_root', 'raw_sha256',
        'decoded_sha256', 'encoding', 'size_bytes', 'source_bytes') if name in unit},
        'artifacts': {name: unit['artifacts'][name] for name in REQUIRED_SOURCE_ARTIFACTS}}
        for unit in units]


def check_replay_limit(document, name, limit, stage):
    value = document[name]
    if type(value) is not int or not 0 <= value <= limit:
        raise ValueError(stage + ' replay budget exceeds the requested ' + name + ' limit')


def read_source_prerequisites(reader, unit, max_nodes, max_tokens):
    source = reader.read(unit['artifacts']['source'])
    size = _source_envelope(unit, source)
    f0 = reader.read(unit['artifacts']['source_bytes'])
    if not _matches(unit, source, f0, size):
        raise ValueError('source stage requires matching original F0 bytes/text')
    f1 = reader.read(unit['artifacts']['source_tokens'])
    f2 = reader.read(unit['artifacts']['source_syntax'])
    check_replay_limit(f1, 'max_tokens', max_tokens, 'F1')
    check_replay_limit(f2, 'max_nodes', max_nodes, 'F2')
    return f0, f1, f2


def material_store_members(root, descriptors, *, result=True):
    expected = {d['path'] for d in descriptors} | ({'result.json'} if result else set())
    actual = set()
    for path in root.rglob('*'):
        if path.is_symlink():
            raise ValueError('source material store cannot traverse symlinks')
        if path.is_file():
            actual.add(path.relative_to(root).as_posix())
    if actual != expected:
        raise ValueError('source material store has unowned or missing files')


def read_material_manifest(store, out):
    root = Path(store).absolute()
    if root.resolve() != root or not root.is_dir() or out.is_relative_to(root):
        raise ValueError('source materials require a canonical store and independent report directory')
    path = root / 'result.json'
    if path.is_symlink() or path.resolve() != path:
        raise ValueError('source material manifest cannot traverse a symlink')
    before = _stamps(root, ({'path': 'result.json'},))
    raw = path.read_bytes()
    if _stamps(root, ({'path': 'result.json'},)) != before:
        raise ValueError('source material manifest changed during read')
    document = json.loads(raw)
    if type(document) is not dict:
        raise ValueError('source material manifest must be an object')
    return root, document, raw


def pin_material_store(root, descriptors, raw):
    descriptors = tuple(descriptors)
    material_store_members(root, descriptors)
    pins = _stamps(root, (*descriptors, {'path': 'result.json'}))
    if (root / 'result.json').read_bytes() != raw:
        raise ValueError('source material manifest changed before receipt pinning')
    return pins


def check_material_store(root, descriptors, raw, pins):
    descriptors = tuple(descriptors)
    material_store_members(root, descriptors)
    if (_stamps(root, (*descriptors, {'path': 'result.json'})) != pins
            or (root / 'result.json').read_bytes() != raw):
        raise ValueError('source material store changed during verification')


__all__ = ['REQUIRED_SOURCE_ARTIFACTS', 'source_input_basis', 'check_replay_limit',
    'read_source_prerequisites', 'material_store_members', 'read_material_manifest',
    'pin_material_store', 'check_material_store']
