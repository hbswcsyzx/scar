"""Replay legacy atom identity from accepted F2 fields, without parsing them.

The pure builder checks identity correspondence conditional on F2 acceptance.
The public document factory/reader additionally replay that upstream gate.
Neither path proves the legacy graph's execution semantics or rewrites its IDs.
"""
from collections import deque
from hashlib import sha256
import json
from pathlib import Path, PurePosixPath

from scar.analysis.source_bytes import decoded_source_bytes
from scar.analysis.source_roles import SyntaxRoleView
from scar.analysis.source_syntax import _profile, read_source_syntax_material
from scar.ir.program.source_anchors import SourceAnchorInput, SourceAtomAnchor, SourceAtomAnchors
from scar.ir.program.source_roles import SlotRef
from scar.ir.program.source_syntax import SourceSyntaxMaterial
from scar.ir.record_codec import decode, encode
from scar.ir.v2.codec import semantic_from_dict
from scar.ir.v2.common import SourceReference
from scar.ir.v2.ids import SourceAtomID
from scar.ir.v2.semantic import SourceAtom
from scar.ir.v2._validation import record_errors


_FRONTEND_SHA256 = 'd2ab18c5d396c913c297a56d94782ae1149b8a57ef858310b29f9ce32d04471c'
_ELIGIBLE = {'stmt', 'expr', 'arg', 'alias', 'keyword', 'excepthandler'}


class SourceAnchorError(ValueError):
    def __init__(self, code, path, detail):
        self.code, self.path, self.detail = code, path, detail
        super().__init__(code + ' at ' + path + ': ' + detail)


def _require(condition, code, path, detail):
    if not condition:
        raise SourceAnchorError(code, path, detail)


def _digest(document):
    return sha256(json.dumps(document, sort_keys=True, separators=(',', ':'),
        ensure_ascii=True, allow_nan=False).encode('ascii')).hexdigest()


def _record(value, expected, path):
    _require(type(value) is expected, 'RECORD_TYPE', path, 'expected exact ' + expected.__name__)
    errors = record_errors(value, expected, path)
    _require(not errors, 'INVALID_RECORD', path, errors[0] if errors else '')


def build_source_atom_anchors(f0_document, syntax: SourceSyntaxMaterial, semantic_document, *, namespace_root):
    """Build identity links from independently accepted original F2 material.

    This function does not establish the F2-to-text equality again: its caller
    must have accepted that input. It does check the F0/F2 lineage, current
    reviewed profiles, full occurrence topology and complete legacy atom set.
    BFS replays an identifier recipe; it is never an execution-order claim.
    """
    try:
        return _build(f0_document, syntax, semantic_document, namespace_root)
    except SourceAnchorError:
        raise
    except (TypeError, ValueError, KeyError, AttributeError, IndexError) as error:
        raise SourceAnchorError('INVALID_INPUT', 'inputs', str(error)) from error


def _build(f0, syntax, semantic_document, namespace_root):
    _record(syntax, SourceSyntaxMaterial, 'syntax')
    # F0's byte/encoding reader is independent of AST parsing.
    original = decoded_source_bytes(f0)
    _require(syntax.status == 'PARSED' and syntax.mode == 'exec', 'UNSUPPORTED_SYNTAX_INPUT',
             'syntax', 'identity recipe requires a complete exec-mode occurrence table')
    _require(syntax.profile == _profile(f0), 'PROFILE_MISMATCH', 'syntax.profile',
             'F2 profile differs from the reviewed official parser profile')
    _require(syntax.input.f0_document_sha256 == _digest(f0)
             and syntax.input.path == f0['path'] and syntax.input.raw_sha256 == f0['raw']['sha256'],
             'INPUT_LINEAGE', 'syntax.input', 'F2 does not refer to these original F0 bytes')
    _require(f0['namespace_root'] == namespace_root, 'NAMESPACE_MISMATCH', 'namespace_root',
             'namespace must be the original source namespace')
    fingerprint = 'sha256:' + sha256(original.encode('utf-8')).hexdigest()
    basis = SourceAnchorInput(_digest(f0), _digest(encode(syntax)), _digest(semantic_document),
                              f0['path'], namespace_root, fingerprint)
    frontend = Path(__file__).resolve().parents[1] / 'ir' / 'frontend_v2.py'
    _require(sha256(frontend.read_bytes()).hexdigest() == _FRONTEND_SHA256,
             'FRONTEND_PROFILE_MISMATCH', 'frontend', 'legacy atom recipe implementation changed')
    # Reuse the existing finite layout/parent validator. It does not parse or
    # reconstruct an AST, and does not provide the BFS ordering used below.
    roles = SyntaxRoleView(syntax)
    schema = {row.name: row for row in syntax.profile.ast_schema if not row.abstract}
    _require(len(syntax.nodes) <= syntax.max_nodes, 'F2_BUDGET', 'syntax.nodes', 'occurrence count exceeds original budget')
    _require(type(semantic_document) is dict and type(semantic_document.get('source_atoms')) is list,
             'SEMANTIC_DOCUMENT', 'semantic', 'expected the original semantic graph document')
    semantic = semantic_from_dict(semantic_document)
    raw_atoms = semantic_document['source_atoms']
    _require(len(raw_atoms) == len(semantic.source_atoms), 'DUPLICATE_ATOM', 'semantic.source_atoms',
             'raw atom records must not collapse to the same ID')
    own_modules = [row for row in semantic.modules.values() if row.path == basis.path]
    _require(len(own_modules) == 1 and own_modules[0].fingerprint == fingerprint,
             'SOURCE_VERSION', 'semantic.modules', 'original source module fingerprint differs')
    actual = semantic.source_atoms
    for identity, atom in actual.items():
        _record(atom, SourceAtom, 'semantic.source_atoms')
        _require(type(identity) is SourceAtomID and identity == atom.id
                 and atom.reference.path == basis.path and atom.reference.fingerprint == fingerprint
                 and atom.text_fingerprint is None,
                 'SOURCE_VERSION', 'semantic.source_atoms', 'atom is not from this complete legacy source profile')

    def attribute(row, name):
        layout = schema[row.constructor].attributes
        _require(name in layout, 'SOURCE_COORDINATE', row.constructor, 'missing declared ' + name)
        value = row.attributes[layout.index(name)]
        _require(value.kind == 'SCALAR', 'SOURCE_COORDINATE', row.constructor + '.' + name,
                 'legacy atom requires a present scalar source coordinate')
        return value.scalar.to_python()

    queue, seen, anchors, predicted = deque([syntax.root]), set(), [], set()
    relative = str(PurePosixPath(basis.path).relative_to(PurePosixPath(namespace_root)))
    while queue:
        occurrence = queue.popleft()
        _require(occurrence not in seen, 'F2_TOPOLOGY', 'syntax.nodes', 'repeated occurrence reference or cycle')
        seen.add(occurrence)
        ordinal, row = len(seen) - 1, syntax.nodes[occurrence]
        declaration = schema[row.constructor]
        for field in row.fields:
            if field.kind == 'NODE':
                queue.append(field.reference)
            elif field.kind == 'LIST':
                # ast.iter_child_nodes visits direct AST items in list order,
                # ignores scalar/None holes, and never visits attributes.
                queue.extend(item.reference for item in field.items if item.kind == 'NODE')
        eligible = any(base in _ELIGIBLE for base in declaration.bases) or row.constructor in _ELIGIBLE
        if not eligible or 'lineno' not in declaration.attributes:
            continue
        if row.attributes[declaration.attributes.index('lineno')].kind == 'ABSENT':
            continue
        line, column = attribute(row, 'lineno'), attribute(row, 'col_offset')
        end_line, end_column = attribute(row, 'end_lineno'), attribute(row, 'end_col_offset')
        _require(type(line) is int and line >= 1 and type(column) is int and column >= 0
                 and (end_line is None or type(end_line) is int and end_line >= 0)
                 and (end_column is None or type(end_column) is int and end_column >= 0),
                 'SOURCE_COORDINATE', str(occurrence), 'invalid original UTF-8 source coordinates')
        payload = f'{relative}:{fingerprint}:{ordinal}:{row.constructor}'
        identity = SourceAtomID('atom:' + sha256(payload.encode()).hexdigest()[:24])
        reference = SourceReference(identity, basis.path, fingerprint, line, end_line or line, column, end_column)
        _require(identity not in predicted, 'DUPLICATE_ATOM', str(occurrence), 'predicted ID collision')
        predicted.add(identity)
        atom = actual.get(identity)
        _require(atom is not None, 'MISSING_ATOM', str(occurrence), 'original graph omits the predicted atom ID')
        _require(atom.kind == row.constructor and atom.reference == reference,
                 'ATOM_MISMATCH', identity.wire, 'kind or complete source reference differs')
        anchors.append(SourceAtomAnchor(identity, occurrence, ordinal))
    _require(len(seen) == len(syntax.nodes), 'F2_TOPOLOGY', 'syntax.nodes', 'not all occurrences are reachable through original fields')
    _require(predicted == set(actual), 'EXTRA_ATOM', 'semantic.source_atoms', 'original graph contains unaccounted atom IDs')
    # Keep layout validation alive above, but store only original relationships.
    del roles
    return SourceAtomAnchors(basis, _FRONTEND_SHA256, len(syntax.nodes), tuple(anchors))


class SourceAtomAnchorView:
    """Unit-local reference indexes; direct construction is not fresh proof."""

    def __init__(self, syntax: SourceSyntaxMaterial, material: SourceAtomAnchors):
        _record(syntax, SourceSyntaxMaterial, 'syntax')
        _record(material, SourceAtomAnchors, 'anchors')
        _require(material.input.f2_sha256 == _digest(encode(syntax))
                 and material.occurrences == len(syntax.nodes) and material.input.path == syntax.input.path,
                 'INPUT_LINEAGE', 'anchors.input', 'anchor table belongs to another original F2 document')
        _require(material.frontend_sha256 == _FRONTEND_SHA256, 'PROFILE_MISMATCH',
                 'anchors.frontend_sha256', 'unknown legacy identifier profile')
        self.syntax, self.material, self.input = syntax, material, material.input
        self._atoms = {row.atom: row for row in material.anchors}
        self._occurrences = {row.occurrence: row for row in material.anchors}
        self._roles = SyntaxRoleView(syntax)
        schema = {row.name: row for row in syntax.profile.ast_schema if not row.abstract}
        eligible = set()
        for ordinal, row in enumerate(syntax.nodes):
            cls = schema[row.constructor]
            if ((any(base in _ELIGIBLE for base in cls.bases) or row.constructor in _ELIGIBLE)
                    and 'lineno' in cls.attributes
                    and row.attributes[cls.attributes.index('lineno')].kind != 'ABSENT'):
                eligible.add(ordinal)
        _require(set(self._occurrences) == eligible, 'INCOMPLETE_ANCHORS', 'anchors',
                 'every and only eligible original occurrence must have an identity link')

    def atom(self, identity: SourceAtomID):
        _require(type(identity) is SourceAtomID, 'QUERY_ARGUMENT', 'atom', 'expected exact SourceAtomID in this unit')
        _require(identity in self._atoms, 'MISSING_ATOM', identity.wire, 'atom is outside this unit identity table')
        return self._atoms[identity]

    def occurrence(self, ordinal: int):
        """Return None only for a form outside the legacy atom eligibility."""
        _require(type(ordinal) is int and 0 <= ordinal < len(self.syntax.nodes),
                 'QUERY_ARGUMENT', 'occurrence', 'expected original local F2 ordinal')
        return self._occurrences.get(ordinal)

    def field(self, identity: SourceAtomID, name: str):
        anchor = self.atom(identity)
        row = self.syntax.nodes[anchor.occurrence]
        _require(type(name) is str and name in self._roles.fields[row.constructor],
                 'QUERY_ARGUMENT', 'field', 'expected a declared original field name')
        ordinal = self._roles.fields[row.constructor][name]
        return SlotRef(anchor.occurrence, 'FIELD', ordinal), row.fields[ordinal]


def source_atom_anchors_document(f0, f1, f2, semantic, *, namespace_root):
    """Freshly accept F2 upstream, then build links from its stored occurrences.

    The upstream reader intentionally replays the parser/AST restoration. The
    identity transformation above neither uses nor traverses that restored AST.
    """
    syntax = _accepted_syntax(f0, f1, f2)
    return encode(build_source_atom_anchors(f0, syntax, semantic, namespace_root=namespace_root))


def read_source_atom_anchors(document, f0, f1, f2, semantic, *, namespace_root):
    try:
        material = decode(SourceAtomAnchors, document)
    except (TypeError, ValueError, KeyError, AttributeError, IndexError) as error:
        raise SourceAnchorError('INVALID_ANCHOR_DOCUMENT', 'anchors', str(error)) from error
    syntax = _accepted_syntax(f0, f1, f2)
    expected = build_source_atom_anchors(f0, syntax, semantic, namespace_root=namespace_root)
    _require(material == expected, 'ANCHOR_DOCUMENT_MISMATCH', 'anchors', 'original inputs or identity links differ')
    return SourceAtomAnchorView(syntax, material)


def _accepted_syntax(f0, f1, f2):
    try:
        return read_source_syntax_material(f2, f0, f1)
    except (TypeError, ValueError, KeyError, AttributeError, IndexError) as error:
        raise SourceAnchorError('UPSTREAM_REJECTION', 'source_syntax', str(error)) from error


__all__ = ['SourceAnchorError', 'build_source_atom_anchors', 'source_atom_anchors_document',
           'read_source_atom_anchors', 'SourceAtomAnchorView']
