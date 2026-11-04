"""F4-A input-shape signatures over the original official AST and B rules.

This catalog partitions syntax forms. It does not infer context, phases,
execution order, operations or effects, and never parses or executes a target.
"""
from hashlib import sha256
import json
from pathlib import Path

from scar.analysis.source_roles import source_role_catalog
from scar.analysis.source_syntax import _schema_and_digests
from scar.ir.record_codec import encode


_VERSION = 'F4A_SOURCE_INPUT_SHAPE_V1'
_SCHEMA = '8f5cd1f9759dfeb2b1ccaf1a10c4483bad994b674241557e1cdd464be1c4831a'
# Original official ASDL bases; AST contains the seven auxiliary constructors.
_SORTS = (('mod', 4), ('stmt', 28), ('expr', 29), ('expr_context', 3),
    ('boolop', 2), ('operator', 13), ('unaryop', 4), ('cmpop', 10),
    ('excepthandler', 1), ('pattern', 8), ('type_param', 3), ('type_ignore', 1), ('AST', 7))
_FLAGS = dict(authority='SOURCE_INPUT_SHAPE_CLOSURE', context_inference='NOT_COMPUTED',
    phase_inference='NOT_COMPUTED', execution_semantics='NOT_CLAIMED', graph_realization='NOT_PERFORMED')


def _canonical(value):
    return json.dumps(value, sort_keys=True, separators=(',', ':'), ensure_ascii=True,
        allow_nan=False).encode('ascii')


def _digest(value):
    return sha256(_canonical(value)).hexdigest()


def source_type_catalog() -> dict:
    """Return a fresh catalog; type payloads are unchanged F2 AstTypeSchemas.

    FIELD rows retain their original type. ATTRIBUTE rows have type=None:
    the captured official schema declares their names, not _field_types.
    role_rule references the original B rule, including its selector and role.
    """
    schema = _schema_and_digests()[0]
    schema_sha = _digest(encode(schema))
    roles = source_role_catalog()
    if (schema_sha != _SCHEMA or roles['f2_schema_sha256'] != schema_sha
            or _digest({key: value for key, value in roles.items() if key != 'content_sha256'}) != roles['content_sha256']):
        raise ValueError('input type catalog requires its reviewed original F2/B schema')
    constructors, slots = [], []
    sorts = [dict(name=name, constructors=[]) for name, _ in _SORTS]
    sort_by_name = {name: index for index, (name, _) in enumerate(_SORTS)}
    role_constructors = {row['name']: row for row in roles['constructors']}
    if len(role_constructors) != len(roles['constructors']):
        raise ValueError('B constructor references are not unique')
    consumed_rules = set()
    for schema_index, cls in enumerate(schema):
        if cls.abstract:
            continue
        if len(cls.bases) != 1 or cls.bases[0] not in sort_by_name or cls.name not in role_constructors:
            raise ValueError('official constructor has no closed input-sort partition')
        if tuple(field.name for field in cls.field_types) != cls.fields:
            raise ValueError('F2 ordered field types differ from original field declarations')
        index, sort = len(constructors), sort_by_name[cls.bases[0]]
        original, groups = role_constructors[cls.name], []
        for group, names, role_group in (('FIELD', cls.fields, 'fields'), ('ATTRIBUTE', cls.attributes, 'attributes')):
            references = original[role_group]
            if len(references) != len(names):
                raise ValueError('F2/B original field denominator differs')
            ids = []
            for ordinal, name in enumerate(names):
                rule_id = references[ordinal]
                if type(rule_id) is not int or not 0 <= rule_id < len(roles['rules']) or rule_id in consumed_rules:
                    raise ValueError('B original rule reference is invalid or duplicated')
                rule = roles['rules'][rule_id]
                if (rule['rule'], rule['constructor'], rule['group'], rule['ordinal'], rule['name']) != (rule_id, cls.name, group, ordinal, name):
                    raise ValueError('B rule does not identify the original F2 field')
                consumed_rules.add(rule_id);ids.append(len(slots))
                slots.append(dict(constructor=index, group=group, ordinal=ordinal, role_rule=rule_id,
                    type=encode(cls.field_types[ordinal].type) if group == 'FIELD' else None))
            groups.append(ids)
        constructors.append(dict(name=cls.name, source_schema_index=schema_index, sort=sort,
            fields=groups[0], attributes=groups[1]))
        sorts[sort]['constructors'].append(index)
    if (len(constructors) != 113 or len(slots) != 484
            or len(role_constructors) != 113 or consumed_rules != set(range(len(roles['rules'])))
            or len(roles['rules']) != 484
            or any(len(row['constructors']) != size for row, (_, size) in zip(sorts, _SORTS))
            or sum(row['group'] == 'FIELD' for row in slots) != 196):
        raise ValueError('input-sort or original-field partition is not closed')
    payload = dict(schema='scar.source-type-catalog', schema_version=1, rule_version=_VERSION,
        f2_schema_sha256=schema_sha, role_catalog_sha256=roles['content_sha256'],
        implementation_sha256=sha256(Path(__file__).read_bytes()).hexdigest(),
        sorts=sorts, constructors=constructors, slots=slots, **_FLAGS)
    return {**payload, 'content_sha256': _digest(payload)}


def read_source_type_catalog(document) -> dict:
    """Fresh exact wire comparison, without granting execution semantics."""
    expected = source_type_catalog()
    if type(document) is not dict or _canonical(document) != _canonical(expected):
        raise ValueError('input type catalog differs from its reviewed original schema/rules')
    return expected


__all__ = ['source_type_catalog', 'read_source_type_catalog']
