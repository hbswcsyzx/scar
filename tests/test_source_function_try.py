"""Small source-only checks; none of these functions is executed."""
from dataclasses import replace
from pathlib import Path
from tempfile import TemporaryDirectory
import unittest

from scar.analysis.program_lowering import lower_source, SourceProgram, BodyLoweringProfile
from scar.analysis.source_language import SourceLanguageOptions
from scar.ir.program.source_language import SourceLanguageCapability
from scar.ir.program.control import LanguageCompletionKind


class FunctionTryChecks(unittest.TestCase):
    def lower(self, directory, text, *, enabled=True):
        path = Path(directory) / 'ordinary.py'
        path.write_text(text)
        result = lower_source(path, 'f', profile=BodyLoweringProfile.STRUCTURED_ENV,
            language_options=SourceLanguageOptions((SourceLanguageCapability.FUNCTION_TRY_314_V1,))
                if enabled else None)
        return result, {str(path): text}

    def test_finally_resumes_original_or_replaces_after_cleanup(self):
        text = ('def f(obj, action):\n    try:\n        action(obj)\n'
                '    finally:\n        obj.closed = False\n    return obj\n')
        with TemporaryDirectory() as directory:
            result, sources = self.lower(directory, text)
            self.assertIsNotNone(result.graph)
            checked = SourceProgram.read_structure(result.to_dict(), source_texts=sources)
            self.assertTrue(checked.graph.cleanup_resumes)
            self.assertTrue(checked.graph.cleanup_replacements)
            self.assertEqual({p.kind for p in checked.graph.control_ports},
                             {LanguageCompletionKind.RAISE, LanguageCompletionKind.FALLTHROUGH})
            packet = checked.graph.exception_packets[0]
            operation = next(op for op in checked.graph.operations
                             if any(u.id == packet.traceback for u in op.uses))
            exception = next(u.value for u in operation.uses if u.id == packet.exception)
            corrupted = replace(operation, uses=tuple(replace(u, value=exception)
                if u.id == packet.traceback else u for u in operation.uses))
            graph = replace(checked.graph, operations=tuple(corrupted if op.id == operation.id else op
                                                           for op in checked.graph.operations))
            with self.assertRaisesRegex(ValueError, 'actual completion/forwarded'):
                SourceProgram.read_structure(replace(checked, graph=graph).to_dict(), source_texts=sources)
            historical, _ = self.lower(directory, text, enabled=False)
            self.assertIsNone(historical.graph)

    def test_single_local_type_handler_has_real_match_and_restoration(self):
        text = ('def f(x, action, error):\n    try:\n        action(x)\n'
                '    except error:\n        raise\n    else:\n        action(x)\n    return x\n')
        with TemporaryDirectory() as directory:
            result, sources = self.lower(directory, text)
            self.assertIsNotNone(result.graph)
            checked = SourceProgram.read_structure(result.to_dict(), source_texts=sources)
            self.assertEqual(len(checked.graph.exception_matches), 1)
            self.assertTrue(checked.graph.cleanup_enters)
            self.assertTrue(checked.graph.cleanup_resumes)
            self.assertTrue(checked.graph.cleanup_replacements)

    def test_unimplemented_boundaries_are_explicit_not_graphs(self):
        with TemporaryDirectory() as directory:
            crossing, _ = self.lower(directory,
                'def f(x):\n    try:\n        return x\n    finally:\n        x.closed = False\n')
            self.assertIsNone(crossing.graph)
            self.assertIn('FUNCTION_TRY_NONLOCAL_TRANSFER_OR_NESTED_UNIMPLEMENTED',
                          '\n'.join(g.detail for g in crossing.metadata.gaps))
            missing_expression, _ = self.lower(directory,
                'def f(x, action):\n    try:\n        action(x)\n    except Exception:\n        action(x)\n    return x\n')
            self.assertIsNone(missing_expression.graph)
            self.assertIn('FUNCTION_TRY_HANDLER_EXPRESSION_SOURCE_PROTOCOL_UNIMPLEMENTED',
                          '\n'.join(g.detail for g in missing_expression.metadata.gaps))


if __name__ == '__main__':
    unittest.main()
