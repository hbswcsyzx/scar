"""Distinguish an unbuilt body diagnostic from an existing canonical graph.

An old diagnostic is retained as an owned input when its lexical entry gains
a body. Relationship readers check its original bytes; a status or manifest
claim alone never authorizes replacing existing core ports.
"""
from __future__ import annotations


def null_body_diagnostic(unit, row, document):
    if (type(document) is not dict or document.get('schema') != 'scar.static-body'
            or type(document.get('schema_version')) is not int or document['schema_version'] != 1
            or document.get('entry_key') != row['entry_key']
            or document.get('status') != row['status']
            or document.get('cache_key') != row.get('cache_key')
            or document.get('inputs') != {name: unit['artifacts'].get(name)
                for name in ('source', 'semantic', 'semantics', 'control')}):
        raise ValueError('body diagnostic differs from its original entry/source receipts')
    return (row['status'] != 'LOWERED_WITH_GAPS' and 'graph' in document
        and all(document.get(name) is None for name in
            ('graph', 'metadata', 'interface', 'structured', 'language', 'frame', 'module', 'class')))


def diagnostic_materializations(manifest, read):
    """Build a fresh reader callback, not a serialized compatibility token.

    The usual source/entry projection comparison is still required. This
    callback admits only a current canonical row with the exact archived old
    receipt and an independently read old payload containing no graph/ports.
    """
    units = {unit['key']: unit for unit in manifest['units']}
    checked, projected = {}, {}

    def admits(old_unit, old, new_unit, new):
        from scar.analysis.static_basis_compatibility import _same
        from scar.analysis.static_calls import input_basis_unit
        unit = units.get(new_unit['key'])
        if unit is None or old_unit['key'] != new_unit['key']:
            return False
        if unit['key'] not in projected:
            projected[unit['key']] = input_basis_unit(unit)
        if not _same(projected[unit['key']], new_unit):
            return False
        matches = [row for row in unit['bodies'] if row['entry_key'] == new['entry_key']]
        if len(matches) != 1:
            return False
        row, = matches
        if (new.get('status') != 'LOWERED_WITH_GAPS'
                or not _same(row.get('diagnostic_input'), old.get('artifact'))
                or any(not _same(row.get(name), new.get(name)) for name in
                    ('status', 'artifact', 'cache_key', 'definitions', 'source', 'kind'))):
            return False
        key = (unit['key'], old['entry_key'], old['artifact']['path'], old['artifact']['sha256'],
               old['status'], old.get('cache_key'))
        if key not in checked:
            checked[key] = null_body_diagnostic(unit, old, read(old['artifact']))
        return checked[key]

    return admits


__all__ = ['null_body_diagnostic', 'diagnostic_materializations']
