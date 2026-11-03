"""Compare projected static input bases without weakening existing endpoints.

Inputs are the plain JSON unit projections from ``input_basis_unit``. Extra
canonical bodies may fill existing empty ledger entries; neither an original
body artifact nor a source, declaration, identity or position may be replaced.
This comparison does not establish relationship coverage of the added bodies.
"""
from __future__ import annotations

import math


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
                    return False
            elif (not _same({key: value for key, value in old.items() if key not in mutable},
                    {key: value for key, value in new.items() if key not in mutable})
                    or not _same(new, new)):
                return False
    return True


__all__ = ['units_basis_compatible']
