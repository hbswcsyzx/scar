"""Approved interpolation grammar tools, without configuration evaluation."""
from io import StringIO
from pathlib import Path
import sys

import antlr4
from antlr4.error.ErrorListener import ErrorListener
from antlr4.error.Errors import ParseCancellationException
from antlr4.error.ErrorStrategy import BailErrorStrategy

from scar.analysis.source_data_materials import _artifact
from scar.analysis.source_override_syntax import _check_imports, _tool


_APPROVED = {
    'grammar/gen/OmegaConfGrammarLexer.py': 'f568dd6f735790223ea54db71486f89128320dd2045a8d2115f48b305a552b44',
    'grammar/gen/OmegaConfGrammarParser.py': '2c215392e4da4585bf9f1221dc9cf79fe25bc21f7d19dad994e6a6464c2a7c00',
}


class _Fail(ErrorListener):
    def syntaxError(self, recognizer, offendingSymbol, line, column, msg, error):
        raise ValueError('interpolation syntax '+str(line)+':'+str(column)+': '+str(msg))


class InterpolationSyntax:
    """Parse configValue through EOF; no visitor, resolver or application API."""
    def __init__(self, omegaconf_source):
        root = Path(omegaconf_source).absolute()
        profiles, sources = [], {}
        for relative, expected in _APPROVED.items():
            artifact, raw = _artifact(root/relative, 'scar.approved-interpolation-grammar-tool')
            if artifact.sha256 != expected:
                raise ValueError('interpolation grammar version is not approved: '+relative)
            _check_imports(raw)
            profiles.append(artifact)
            sources[relative] = raw
        # Some distributions retain generated grammar metadata; this one need
        # not provide .g4, .tokens or .interp files. Never fetch replacements.
        stems = {'OmegaConfGrammarLexer', 'OmegaConfGrammarParser'}
        for path in sorted((root/'grammar').rglob('*')):
            if path.is_file() and path.suffix in ('.tokens', '.interp') and path.stem in stems:
                profiles.append(_artifact(path, 'scar.interpolation-grammar-metadata')[0])
        runtime = Path(antlr4.__file__).resolve().parent
        for path in sorted(runtime.rglob('*.py')):
            profiles.append(_artifact(path, 'scar.antlr4-parser-runtime-source')[0])
        profiles.append(_artifact(Path(sys.executable).resolve(), 'scar.analyzer-python-executable')[0])
        self.profiles = tuple(profiles)
        self.lexer = _tool(root/'grammar/gen/OmegaConfGrammarLexer.py',
            sources['grammar/gen/OmegaConfGrammarLexer.py'], 'OmegaConfGrammarLexer')
        self.parser = _tool(root/'grammar/gen/OmegaConfGrammarParser.py',
            sources['grammar/gen/OmegaConfGrammarParser.py'], 'OmegaConfGrammarParser')

    def parse(self, text):
        if type(text) is not str:
            raise TypeError('interpolation input must be a string')
        lexer = self.lexer(antlr4.InputStream(text), output=StringIO())
        lexer.removeErrorListeners()
        lexer.addErrorListener(_Fail())
        lexer.mode(self.lexer.DEFAULT_MODE)
        stream = antlr4.CommonTokenStream(lexer)
        try:
            stream.fill()
            stream.seek(0)
            parser = self.parser(stream, output=StringIO())
            parser.removeErrorListeners()
            parser.addErrorListener(_Fail())
            parser._errHandler = BailErrorStrategy()
            tree = parser.configValue()
        except ParseCancellationException as error:
            raise ValueError('interpolation does not match the complete grammar') from error
        except Exception as error:
            # The approved generated lexer can raise this exact mode-stack
            # error; it must not escape as a successfully recovered tree.
            if type(error) is Exception and str(error) == 'Empty Stack':
                raise ValueError('invalid interpolation lexer mode stack') from error
            raise
        if parser.getNumberOfSyntaxErrors() or tree.EOF() is None or stream.LA(1) != antlr4.Token.EOF:
            raise ValueError('interpolation did not consume the complete input')
        return tree
