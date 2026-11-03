"""Compare projected static input bases without weakening existing endpoints.

Inputs are the plain JSON unit projections from ``input_basis_unit``. Extra
canonical bodies may fill existing empty ledger entries; neither an original
body artifact nor a source, declaration, identity or position may be replaced.
This comparison does not establish relationship coverage of the added bodies.
"""
from __future__ import annotations

import math
import hashlib
import json
import re


def _same(left, right):
    """Exact JSON equality, including bool/int and container distinctions."""
    if type(left) is not type(right):
        return False
    if type(left) is dict:
        return (all(type(key) is str for key in left)
            and all(type(key) is str for key in right)
            and left.keys() == right.keys()
            and all(_same(value, right[key]) for key, value in left.items()))
    if type(left) is list:
        return len(left) == len(right) and all(_same(a, b) for a, b in zip(left, right))
    if type(left) is float:
        return math.isfinite(left) and math.isfinite(right) and left == right
    return type(left) in (str, int, bool, type(None)) and left == right


def units_basis_compatible(original_units, current_units):
    """Whether the current basis is equal or only fills original body holes.

    Unit/body sequence positions are original locator coordinates. Existing
    artifact-bearing rows remain entirely equal. For an original empty row,
    only status, cache_key and artifact may change; all other fields retain
    their exact original presence, types and values. Invalid inputs return
    False rather than granting compatibility from a partial comparison.
    """
    return _units_basis_compatible(original_units, current_units)


def _units_basis_compatible(original_units, current_units, diagnostic_body=None):
    if (type(original_units) is not list
            or type(current_units) is not list
            or len(original_units) != len(current_units)):
        return False
    mutable = frozenset(('status', 'cache_key', 'artifact'))
    for before, after in zip(original_units, current_units):
        if (type(before) is not dict or type(after) is not dict
                or type(before.get('bodies')) is not list
                or type(after.get('bodies')) is not list
                or not _same({key: value for key, value in before.items() if key != 'bodies'},
                    {key: value for key, value in after.items() if key != 'bodies'})
                or len(before['bodies']) != len(after['bodies'])):
            return False
        for old, new in zip(before['bodies'], after['bodies']):
            if type(old) is not dict or type(new) is not dict:
                return False
            if any(name in row and type(row[name]) is not kind
                    for row in (old, new)
                    for name, kind in (('status', str), ('cache_key', str), ('artifact', dict))):
                return False
            if 'artifact' in old:
                if not _same(old, new):
                    if (diagnostic_body is None
                            or not _same({key: value for key, value in old.items() if key not in mutable},
                                {key: value for key, value in new.items() if key not in mutable})
                            or not diagnostic_body(before, old, after, new)):
                        return False
            elif (not _same({key: value for key, value in old.items() if key not in mutable},
                    {key: value for key, value in new.items() if key not in mutable})
                    or not _same(new, new)):
                return False
    return True


def source_units_identity(units):
    """Digest immutable unit/entry coordinates, excluding body-hole contents.

    This is an append ledger coordinate, not a replacement for the full
    artifact-preserving comparison in ``units_basis_compatible``.
    """
    if not units_basis_compatible(units, units):
        raise ValueError('source expansion identity requires valid projected units')
    mutable = frozenset(('status', 'cache_key', 'artifact'))
    stable = [{**{key: value for key, value in unit.items() if key != 'bodies'},
        'bodies': [{key: value for key, value in row.items() if key not in mutable}
                   for row in unit['bodies']]} for unit in units]
    payload = json.dumps(stable, sort_keys=True, ensure_ascii=False,
                         separators=(',', ':'), allow_nan=False).encode('utf8')
    return hashlib.sha256(payload).hexdigest()


def _source_expansion_valid(ledger, current):
    if (type(ledger) is not dict or set(ledger) != {'schema', 'schema_version', 'coverage', 'steps'}
            or ledger['schema'] != 'scar.static-source-expansion-ledger'
            or type(ledger['schema_version']) is not int or ledger['schema_version'] != 1
            or ledger['coverage'] != 'PRIOR_SOURCE_BASIS_ONLY'
            or type(ledger['steps']) is not list or not ledger['steps']):
        return False
    if not units_basis_compatible(current, current):
        return False
    keys = [unit.get('key') for unit in current]
    coordinates = [(unit.get('namespace_root'), unit.get('path')) for unit in current]
    if (any(type(key) is not str or not key for key in keys)
            or len(set(keys)) != len(keys) or len(set(coordinates)) != len(coordinates)):
        return False
    expected_fields = {'before_count', 'after_count', 'prior_manifest_sha256',
        'before_identity_sha256', 'appended_identity_sha256', 'unit_keys', 'provenance'}
    previous = None
    for step in ledger['steps']:
        if type(step) is not dict or set(step) != expected_fields:
            return False
        before, after = step['before_count'], step['after_count']
        if (type(before) is not int or type(after) is not int
                or not 0 <= before < after <= len(current)
                or previous is not None and before != previous
                or any(type(step[name]) is not str or re.fullmatch(r'[0-9a-f]{64}', step[name]) is None
                       for name in ('prior_manifest_sha256', 'before_identity_sha256', 'appended_identity_sha256'))
                or type(step['unit_keys']) is not list
                or step['unit_keys'] != [unit.get('key') for unit in current[before:after]]
                or type(step['provenance']) is not dict or not step['provenance']
                or not _same(step['provenance'], step['provenance'])):
            return False
        if any(unit.get('module_names') != [] or unit.get('module_mappings') != []
               for unit in current[before:after]):
            return False  # Appended evidence is not an inferred import namespace.
        if (source_units_identity(current[:before]) != step['before_identity_sha256']
                or source_units_identity(current[before:after]) != step['appended_identity_sha256']):
            return False
        previous = after
    return previous == len(current)


def published_units_basis_compatible(original_units, current_units, *, source_expansion=None,
                                     diagnostic_body=None):
    """Retain prior relationship scope across an explicit append-only ledger.

    Every original source/body endpoint is still checked by the strict normal
    comparison. Additional units are accepted only at recorded append borders;
    their relationships are not asserted to have been covered by the old basis.
    """
    if _units_basis_compatible(original_units, current_units, diagnostic_body):
        return True
    if (type(original_units) is not list or type(current_units) is not list
            or len(original_units) >= len(current_units)
            or not _units_basis_compatible(original_units, current_units[:len(original_units)], diagnostic_body)):
        return False
    try:
        if not _source_expansion_valid(source_expansion, current_units):
            return False
        borders = {count for step in source_expansion['steps']
                   for count in (step['before_count'], step['after_count'])}
        return len(original_units) in borders
    except (TypeError, ValueError, KeyError, OverflowError):
        return False


__all__ = ['units_basis_compatible', 'published_units_basis_compatible', 'source_units_identity']
