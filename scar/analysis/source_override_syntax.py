"""Approved generated override grammar as an analysis tool, without Hydra imports."""
import ast
from hashlib import sha256
from importlib.util import module_from_spec, spec_from_file_location
from io import StringIO
from pathlib import Path
import sys

import antlr4
from antlr4.error.ErrorListener import ErrorListener
from antlr4.error.Errors import ParseCancellationException
from antlr4.error.ErrorStrategy import BailErrorStrategy

from scar.analysis.source_data_materials import _artifact


_APPROVED = {
    'grammar/OverrideLexer.g4': '48b7f812b950a8b86ea987319b5f9cb0875cbbeeb46ef5714a9899e445679446',
    'grammar/OverrideParser.g4': 'dffa79412959f0a9682c629079c0b4feb6651467bab7771f2d0cfe10c1f0881f',
    'grammar/gen/OverrideLexer.py': '427a56ab2e48c2f544c23ea550cb4240d397ed34c0c72b8889588842971bde7e',
    'grammar/gen/OverrideParser.py': '114a65e033914a46ffb8e938d32212a2d360ce6f4f0667380f7eca70ebab98f5',
}
_IMPORTS = {('antlr4', ('*',)), ('io', ('StringIO',)), ('typing', ('TextIO',)),
    ('typing.io', ('TextIO',)), ('', ('sys',))}


def _check_imports(raw):
    found = []
    for node in ast.walk(ast.parse(raw)):
        if not isinstance(node, (ast.Import, ast.ImportFrom)):
            continue
        if isinstance(node, ast.ImportFrom) and node.level:
            raise ValueError('generated grammar has a relative import')
        key = (node.module if isinstance(node, ast.ImportFrom) else '', tuple(a.name for a in node.names))
        if key not in _IMPORTS or any(a.asname is not None for a in node.names):
            raise ValueError('generated grammar has an unapproved dependency')
        found.append(key)
    if len(found) != len(_IMPORTS) or set(found) != _IMPORTS:
        raise ValueError('generated grammar import profile differs')


def _tool(path, raw, name):
    module_name = 'scar.analysis._override_tool_'+name+'_'+sha256(raw).hexdigest()[:12]
    spec = spec_from_file_location(module_name, path)
    if spec is None or spec.loader is None:
        raise ValueError('generated grammar has no file module specification')
    module = module_from_spec(spec)
    # Compile the approved tool bytes, avoiding an unchecked cached .pyc.
    exec(compile(raw, str(path), 'exec', dont_inherit=True), module.__dict__)
    sys.modules[module_name] = module
    return getattr(module, name)


class _Fail(ErrorListener):
    def syntaxError(self, recognizer, offendingSymbol, line, column, msg, error):
        raise ValueError('override syntax '+str(line)+':'+str(column)+': '+msg)


class OverrideSyntax:
    """Parse complete override strings; no visitor, resolver or target API."""
    def __init__(self, hydra_source):
        root = Path(hydra_source).absolute()
        profiles, sources = [], {}
        for relative, expected in _APPROVED.items():
            artifact, raw = _artifact(root/relative, 'scar.approved-override-grammar-tool')
            if artifact.sha256 != expected:
                raise ValueError('override grammar version is not approved: '+relative)
            if relative.endswith('.py'):
                _check_imports(raw)
            profiles.append(artifact)
            sources[relative] = raw
        runtime = Path(antlr4.__file__).resolve().parent
        for path in sorted(runtime.rglob('*.py')):
            profiles.append(_artifact(path, 'scar.antlr4-parser-runtime-source')[0])
        profiles.append(_artifact(Path(sys.executable).resolve(), 'scar.analyzer-python-executable')[0])
        self.profiles = tuple(profiles)
        self._lexer = _tool(root/'grammar/gen/OverrideLexer.py',
            sources['grammar/gen/OverrideLexer.py'], 'OverrideLexer')
        self._parser = _tool(root/'grammar/gen/OverrideParser.py',
            sources['grammar/gen/OverrideParser.py'], 'OverrideParser')
        self.lexer = self._lexer
        self.parser = self._parser

    def parse(self, token):
        if type(token) is not str:
            raise TypeError('override token must be a string')
        lexer = self._lexer(antlr4.InputStream(token), output=StringIO())
        lexer.removeErrorListeners()
        lexer.addErrorListener(_Fail())
        stream = antlr4.CommonTokenStream(lexer)
        # Force every lexical error through our listener before building a tree.
        stream.fill()
        stream.seek(0)
        parser = self._parser(stream, output=StringIO())
        parser.removeErrorListeners()
        parser.addErrorListener(_Fail())
        parser._errHandler = BailErrorStrategy()
        try:
            tree = parser.override()
        except ParseCancellationException as error:
            raise ValueError('override does not match the complete grammar') from error
        if parser.getNumberOfSyntaxErrors() or tree.EOF() is None or stream.LA(1) != antlr4.Token.EOF:
            raise ValueError('override did not consume the complete input')
        return tree
