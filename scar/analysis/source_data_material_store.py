"""Receipt-bound representation graphs; no configuration composition or execution."""
from collections import Counter
import ast
from hashlib import sha256
import json
from pathlib import Path
import re

from scar.analysis import normal_output, source_symbol_variants
from scar.analysis.source_stage import _durable_bytes, _durable_mkdir
from scar.analysis.source_template_links import _json
from scar.ir import record_codec as codec
from scar.ir.literals import LiteralKind
from scar.ir.program import data_materials as D


_SCHEMA = 'scar.source-data-material'
_STATUS = 'DATA_MATERIAL_ONLY'
_SEMANTICS = 'PARSED_REPRESENTATION_NOT_COMPOSED_CONFIGURATION_OR_RUNTIME_VALUE'
_TABLES = dict(nodes=D.DataNode, references=D.DataReference, obligations=D.DataObligation)
_HEADER = ('source', 'profile', 'normalized_text_sha256', 'root', 'semantics')


def _require(condition, message):
    if not condition:
        raise ValueError(message)


def _sha(value):
    return type(value) is str and re.fullmatch('[0-9a-f]{64}', value) is not None


def _receipt(receipt, name, *, table=False):
    fields = {'path', 'bytes', 'sha256'} | ({'decoded_bytes', 'decoded_sha256', 'records'} if table else set())
    _require(type(receipt) is dict and set(receipt) == fields and receipt['path'] == name,
        'unexpected data material receipt')
    _require(all(type(receipt[key]) is int and receipt[key] >= 0
        for key in (('bytes', 'decoded_bytes', 'records') if table else ('bytes',)))
        and all(_sha(receipt[key]) for key in (('sha256', 'decoded_sha256') if table else ('sha256',))),
        'invalid data material receipt fields')


def pins():
    directory = Path(__file__).parent
    paths = dict(store=Path(__file__), parser=directory/'source_data_materials.py',
        types=Path(D.__file__), codec=Path(codec.__file__),
        table_writer=Path(normal_output.__file__), table_reader=Path(source_symbol_variants.__file__))
    return {name: sha256(path.read_bytes()).hexdigest() for name, path in paths.items()}


def _profile_receipts(profile):
    artifacts = (*profile.tools, *((profile.loader_source,) if profile.loader_source else ()))
    seen = {}
    for artifact in artifacts:
        artifact.__post_init__()
        path = Path(artifact.uri)
        _require(path.is_absolute(), 'parser tool receipt requires an absolute filesystem path')
        if artifact.uri in seen:
            _require(seen[artifact.uri] == artifact, 'conflicting parser tool receipts')
            continue
        seen[artifact.uri] = artifact
        payload = path.read_bytes()
        _require(len(payload) == artifact.size_bytes and sha256(payload).hexdigest() == artifact.sha256,
            'parser tool or loader receipt differs: '+artifact.uri)
    _require(bool(profile.tools) and bool(profile.rule), 'data parser profile needs its tool receipts and rule')
    _require((profile.loader_source is None) == (profile.loader_function_ast_sha256 is None),
        'loader source and function AST receipt must be paired')
    _require(profile.loader_function_ast_sha256 is None or _sha(profile.loader_function_ast_sha256),
        'invalid loader function AST digest')
    if profile.loader_source is not None:
        source = Path(profile.loader_source.uri).read_bytes()
        _require(sha256(source).hexdigest() == profile.loader_source.sha256, 'loader changed during admission')
        functions = (node for node in ast.parse(source).body if isinstance(node, (ast.FunctionDef, ast.AsyncFunctionDef)))
        _require(sum(sha256(ast.dump(node, include_attributes=False).encode()).hexdigest()
            == profile.loader_function_ast_sha256 for node in functions) == 1,
            'loader function AST does not occur in its recorded source')
    _require(profile.float_flags >= 0 and (profile.float_pattern is not None or (
        profile.float_flags == 0 and profile.float_initial_characters == '')), 'invalid float resolver profile')
    _require(profile.text_view == 'UTF8_UNIVERSAL_NEWLINES' and profile.construction_scope ==
        'SCALARS_ONLY_NO_CONTAINER_OR_CUSTOM_CONSTRUCTORS', 'unsupported data interpretation scope')
    _require(len(set(profile.scalar_tags)) == len(profile.scalar_tags)
        and all(profile.scalar_tags) and len(set(profile.removed_implicit_tags)) == len(profile.removed_implicit_tags),
        'invalid parser tag declarations')


def _validate(material, raw):
    # Round-trip admission checks every declared field before following ordinals.
    _require(type(material) is D.DataMaterial and type(raw) is bytes, 'typed material and raw bytes required')
    material = codec.decode(D.DataMaterial, codec.encode(material))
    material.source.__post_init__()
    _require(Path(material.source.uri).is_absolute(), 'data source requires an absolute filesystem locator')
    _require(material.semantics == _SEMANTICS, 'data representation has no configuration or execution authority')
    _require(len(raw) == material.source.size_bytes and sha256(raw).hexdigest() == material.source.sha256,
        'source bytes differ from material version')
    _profile_receipts(material.profile)
    text = raw.decode('utf-8').replace('\r\n', '\n').replace('\r', '\n')
    _require(sha256(text.encode('utf-8')).hexdigest() == material.normalized_text_sha256,
        'normalized data text digest differs')
    lines = re.split('[\n\x85\u2028\u2029]', text)

    def span(value):
        _require(0 <= value.byte_start <= value.byte_end <= len(raw), 'data span exceeds source bytes')
        _require(all(p == len(raw) or raw[p] & 0xC0 != 0x80
            for p in (value.byte_start, value.byte_end)), 'data span splits a UTF-8 character')
        _require(0 <= value.line <= value.end_line < len(lines)
            and 0 <= value.column <= len(lines[value.line])
            and 0 <= value.end_column <= len(lines[value.end_line])
            and (value.line, value.column) <= (value.end_line, value.end_column), 'invalid parser span coordinates')

    nodes, references = material.nodes, material.references
    _require(all(n.ordinal == i for i, n in enumerate(nodes)), 'data node ordinals differ')
    _require(all(r.ordinal == i for i, r in enumerate(references)), 'data reference ordinals differ')
    if material.root is None:
        _require(not nodes and not references, 'empty data document has graph records')
    else:
        _require(0 <= material.root < len(references), 'data root reference is outside its catalog')
    uses = Counter(() if material.root is None else (material.root,))
    scalar_kinds = dict(zip(('null', 'bool', 'int', 'float', 'str'),
        (LiteralKind.NONE, LiteralKind.BOOL, LiteralKind.INT, LiteralKind.FLOAT64, LiteralKind.STR)))
    anchors = {}
    for node in nodes:
        span(node.span)
        _require(bool(node.tag) and (node.anchor is None or bool(node.anchor)), 'empty node tag or anchor')
        if node.anchor is not None:
            _require(node.anchor not in anchors, 'duplicate data anchor')
            anchors[node.anchor] = node.ordinal
        if node.kind is D.DataNodeKind.SCALAR:
            _require(node.scalar_text is not None and node.scalar_style in (None, "'", '"', '|', '>')
                and node.flow_style is None and not node.items and not node.entries,
                'scalar node contains incompatible fields')
            if node.representation_literal is not None:
                name = node.tag.removeprefix('tag:yaml.org,2002:')
                expected = (LiteralKind.STR, LiteralKind.STR_CODEPOINTS) if name == 'str' else (scalar_kinds.get(name),)
                _require(node.tag in material.profile.scalar_tags and name in scalar_kinds
                    and node.representation_literal.kind in expected,
                    'scalar representation literal does not match its admitted tag')
        else:
            _require(node.scalar_text is None and node.scalar_style is None
                and node.representation_literal is None, 'container node contains scalar fields')
            if node.kind is D.DataNodeKind.SEQUENCE:
                _require(not node.entries, 'sequence contains mapping entries')
                uses.update(node.items)
            else:
                _require(not node.items, 'mapping contains sequence items')
                for entry in node.entries:
                    uses.update((entry.key, entry.value))
    _require(set(uses) == set(range(len(references))) and all(n == 1 for n in uses.values()),
        'each syntax reference requires exactly one root or child occurrence')
    definitions = Counter()
    for reference in references:
        span(reference.span)
        _require(0 <= reference.target < len(nodes), 'data reference target is outside node catalog')
        target = nodes[reference.target]
        _require(reference.anchor == target.anchor, 'reference anchor differs from its target definition')
        if reference.alias:
            _require(reference.anchor is not None, 'alias has no target anchor')
        else:
            definitions[reference.target] += 1
    _require(set(definitions) == set(range(len(nodes))) and all(n == 1 for n in definitions.values()),
        'each data node requires exactly one non-alias definition reference')
    seen_nodes, seen_refs, pending = set(), set(), ([] if material.root is None else [material.root])
    while pending:
        ordinal = pending.pop()
        if ordinal in seen_refs:
            continue
        seen_refs.add(ordinal)
        node = nodes[references[ordinal].target]
        if node.ordinal in seen_nodes:
            continue
        seen_nodes.add(node.ordinal)
        pending.extend(node.items)
        for entry in node.entries:
            pending.extend((entry.key, entry.value))
    _require(len(seen_nodes) == len(nodes) and len(seen_refs) == len(references), 'unreachable data graph records')
    for obligation in material.obligations:
        _require(bool(obligation.code), 'data obligation needs a code')
        _require(obligation.node is None or 0 <= obligation.node < len(nodes), 'obligation node is outside catalog')
        _require(obligation.reference is None or 0 <= obligation.reference < len(references),
            'obligation reference is outside catalog')
    return material


def write_data_material(material, raw, out):
    """Publish one fresh material snapshot without changing its source file."""
    out = Path(out).absolute()
    _require(not out.exists(), 'fresh data material output required')
    material = _validate(material, raw)
    for artifact in (material.source, *material.profile.tools,
            *((material.profile.loader_source,) if material.profile.loader_source else ())):
        path = Path(artifact.uri).resolve()
        _require(not path.is_relative_to(out.resolve()), 'data output must be independent of input artifacts')
    initial = pins()
    _durable_mkdir(out)
    _durable_bytes(out/'source.bin', raw, replace=False)
    tables = {name: normal_output.write_table(out/(name+'.jsonl.gz'), getattr(material, name)) for name in _TABLES}
    report = dict(schema=_SCHEMA, schema_version=1, status=_STATUS,
        **{name: codec.encode(getattr(material, name)) for name in _HEADER},
        raw_source=dict(path='source.bin', bytes=len(raw), sha256=sha256(raw).hexdigest()),
        tables=tables, implementation_sha256=initial['store'], pins=initial,
        target_executed=False, configuration_composed=False, first_stage_complete=False)
    _profile_receipts(material.profile)
    _require(pins() == initial, 'data material producer changed during publication')
    _durable_bytes(out/'result.json', _json(report), replace=False)
    return report


class DataMaterialStore:
    def __init__(self, path):
        self.path = Path(path).absolute()
        self.manifest_raw = (self.path/'result.json').read_bytes()
        self.report = json.loads(self.manifest_raw)

    def _load(self):
        r = json.loads(self.manifest_raw)
        expected = {'schema', 'schema_version', 'status', *_HEADER, 'raw_source', 'tables',
            'implementation_sha256', 'pins', 'target_executed', 'configuration_composed', 'first_stage_complete'}
        _require(set(r) == expected and r['schema'] == _SCHEMA and type(r['schema_version']) is int
            and r['schema_version'] == 1 and r['status'] == _STATUS, 'expected data-material-only store')
        _require(r['pins'] == pins() and r['implementation_sha256'] == r['pins']['store'],
            'data material producer pins differ')
        _require(all(r[name] is False for name in ('target_executed', 'configuration_composed', 'first_stage_complete')),
            'data material store has no execution or composition authority')
        _require(set(r['tables']) == set(_TABLES), 'data material table coverage differs')
        source = r['raw_source']
        _receipt(source, 'source.bin')
        raw = (self.path/'source.bin').read_bytes()
        _require(len(raw) == source['bytes'] and sha256(raw).hexdigest() == source['sha256'],
            'stored raw data material differs')
        rows = {}
        for name, kind in _TABLES.items():
            receipt = r['tables'][name]
            _receipt(receipt, name+'.jsonl.gz', table=True)
            document = source_symbol_variants._table(self.path, receipt)
            _require(len(document) == receipt['records'], 'data table record count differs')
            rows[name] = tuple(codec.decode(kind, item) for item in document)
        document = {name: r[name] for name in _HEADER}
        document.update({name: [codec.encode(item) for item in rows[name]] for name in _TABLES})
        material = _validate(codec.decode(D.DataMaterial, document), raw)
        _require((self.path/'result.json').read_bytes() == self.manifest_raw and r['pins'] == pins(),
            'data material manifest or producer changed during reading')
        return material, raw

    def read(self):
        return self._load()[0]

    def raw(self):
        return self._load()[1]
