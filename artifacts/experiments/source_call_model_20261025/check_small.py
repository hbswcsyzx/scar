"""Three necessary checks; only reuse two small immutable compiler modules.
No source preparation, body lowering, compilation, target call or raw replay.
"""
import argparse
import ast
from dataclasses import dataclass
import dis
import hashlib
import json
from pathlib import Path
from types import SimpleNamespace
import unittest

from scar.analysis.code_witness import CodeWitnessStore
from scar.analysis.program_lowering import _Unsupported
from scar.analysis.source_call_lowering import _witness_plan, _invoke
from scar.analysis.source_call_validation import _pop_suffix, _check_failure_pending
from scar.analysis.source_language import SourceLanguageOptions
from scar.ir.program.source_language import SourceLanguageCapability as Capability
from scar.ir.program.structured import PythonProtocolKind as Kind

MAIN = Path('/home/zyf/AAA/scar-worktrees/structured-program-model')
STORE = MAIN / 'artifacts/experiments/first_stage_partitioned_operand_routes_20261023/result/code-witnesses'
INPUT = MAIN / 'artifacts/analysis/kwargs_expansion_design_20261025/SOURCE_RECEIPTS.json'
RECEIPT = {}

class CoreChecks(unittest.TestCase):
    @classmethod
    def setUpClass(cls):
        source = json.loads(INPUT.read_bytes())
        cls.store = CodeWitnessStore(STORE, create=False, compile_missing=False)
        before = cls.store.receipt()
        cls.cases, cached = [], {}
        module_receipts = []
        for case in source['selected_by_ast']:
            archive = case['archived_source_receipt']; fingerprint = 'sha256:' + archive['sha256']
            if fingerprint not in cached:
                candidates = [(key, row) for key, row in cls.store.document['modules'].items()
                              if row['snapshot']['fingerprint'] == fingerprint]
                if len(candidates) != 1: raise ValueError('small fixture module identity is not unique')
                key, row = candidates[0]
                cached[fingerprint] = cls.store._load(key, row)
                module_receipts.append(dict(row['artifact'], path=str(STORE / row['artifact']['path'])))
            raw = Path(archive['path']).read_bytes()
            if len(raw) != archive['bytes'] or hashlib.sha256(raw).hexdigest() != archive['sha256']:
                raise ValueError('original fixture UTF8 source changed')
            tree = ast.parse(raw.decode(), filename=case['definition_source']['path'])
            ref = case['frontier']['source']
            span = (ref['start_line'], ref['end_line'], ref['start_column'], ref['end_column'])
            nodes = [n for n in ast.walk(tree) if isinstance(n, ast.Call)
                     and (n.lineno, n.end_lineno, n.col_offset, n.end_col_offset) == span]
            definition = case['definition_source']
            definitions = [n for n in ast.walk(tree) if isinstance(n, (ast.FunctionDef, ast.AsyncFunctionDef))
                           and (n.lineno, n.end_lineno, n.col_offset, n.end_col_offset) ==
                           (definition['start_line'], definition['end_line'], definition['start_column'], definition['end_column'])]
            if len(definitions) != 1: raise ValueError('exact original AST definition is not unique')
            function = definitions[0]
            start = min([function.lineno] + [n.lineno for n in function.decorator_list])
            codes = [code for code, _path in cached[fingerprint]
                     if code.co_filename == ref['path'] and code.co_name == function.name
                     and start <= code.co_firstlineno <= function.lineno]
            if len(nodes) != 1 or len(codes) != 1: raise ValueError('original source/compiler position not unique')
            cls.cases.append((case['sequence'], nodes[0], tuple(dis.get_instructions(codes[0]))))
        if cls.store.receipt() != before or cls.store.counts['compile_attempts']:
            raise ValueError('readonly witness changed or compiled')
        RECEIPT.update(witness_manifest=before, module_inputs=module_receipts,
            witness_activity=cls.store.counts, source_receipt_sha256=hashlib.sha256(INPUT.read_bytes()).hexdigest(),
            body_lowerings=0, source_prepares=0, target_executions=0, raw_reads=0)

    def test_original_compiler_order_and_explicit_opt_in(self):
        self.assertNotIn(Capability.CALL_KWARGS_314_V1, SourceLanguageOptions().capabilities)
        records = []
        for sequence, node, instructions in self.cases:
            pack, names = _witness_plan(node, instructions)
            records.append({'sequence': sequence, 'packing': pack.opname, 'named_keys': len(names)})
        RECEIPT['compiler_cases'] = records
        _sequence, node, instructions = self.cases[1]
        own = [i for i, row in enumerate(instructions) if tuple(row.positions) ==
               (node.lineno, node.end_lineno, node.col_offset, node.end_col_offset) and row.opname == 'DICT_MERGE']
        changed = list(instructions)
        first = own[0]
        changed[first], changed[first + 1] = changed[first + 1], changed[first]
        with self.assertRaises(_Unsupported): _witness_plan(node, changed)

    def test_dict_update_is_rejected(self):
        _sequence, node, instructions = self.cases[0]
        changed = [SimpleNamespace(opname='DICT_UPDATE' if row.opname == 'DICT_MERGE' else row.opname,
                                  arg=row.arg, argval=row.argval, positions=row.positions) for row in instructions]
        with self.assertRaises(_Unsupported): _witness_plan(node, changed)

    def test_completion_specific_pending_preserves_instances(self):
        prefix = ('outside',)
        callee, a, b = ('h-callee', 'callee'), ('h-a', 'same'), ('h-b', 'same')
        parts = (callee, a, b)
        self.assertEqual(_pop_suffix(parts, ('same', 'same')), (callee,))
        self.assertEqual(_check_failure_pending(prefix + ('callee', 'same', 'same'), parts), prefix)
        with self.assertRaises(ValueError): _check_failure_pending(prefix + ('callee', 'same'), parts)
        prepared = (callee, ('h-args', 'args'), ('h-kw', 'kwargs'))
        update = prepared + (('h-update', 'mapping'),)
        self.assertEqual(_pop_suffix(update, ('mapping',)), prepared)
        self.assertEqual(_check_failure_pending(prefix + ('callee', 'args', 'kwargs'), prepared, prefix), prefix)
        with self.assertRaises(ValueError):
            _check_failure_pending(prefix + ('callee', 'args', 'kwargs', 'mapping'), prepared, prefix)
        @dataclass
        class ProtocolFixture:
            id: str
            behaviors: tuple = ()
        class OwnerFixture:
            def __init__(self, pending):
                self.active_temporaries = list(pending)
                operation = ProtocolFixture('op')
                self.operations = [operation]; self.operation_records = {'op': operation}
            def invoke(self, cursor, node, inputs, **kwargs):
                kwargs['failure_handler']('raise-world', 'exception')
                return 'normal-world', 'result', 'op'
            def finish_exit(self, cursor, node, exception, kind):
                self.failure_pending = tuple(self.active_temporaries)
            def protocol(self, *args): pass
        owner = OwnerFixture(('outside', 'callee', 'same', 'same'))
        _invoke(owner, 'pre-world', None, (), Kind.BUILD_CALL_POSITIONALS,
                ((None, 'same'), (None, 'same')), raise_consumed=(), result=True)
        self.assertEqual(owner.failure_pending, ('outside', 'callee', 'same', 'same'))
        self.assertEqual(owner.active_temporaries, ['outside', 'callee'])
        owner = OwnerFixture(('outside', 'callee', 'args', 'kwargs', 'mapping'))
        _invoke(owner, 'pre-world', None, (), Kind.DICT_MERGE, ((None, 'mapping'),))
        self.assertEqual(owner.failure_pending, ('outside', 'callee', 'args', 'kwargs'))
        self.assertEqual(owner.active_temporaries, ['outside', 'callee', 'args', 'kwargs'])

if __name__ == '__main__':
    parser = argparse.ArgumentParser(); parser.add_argument('--receipt', default='small-check-receipt.json')
    args = parser.parse_args()
    suite = unittest.defaultTestLoader.loadTestsFromTestCase(CoreChecks)
    result = unittest.TextTestRunner(verbosity=2).run(suite)
    RECEIPT.update(tests=result.testsRun, failures=len(result.failures), errors=len(result.errors), passed=result.wasSuccessful())
    with (Path(__file__).parent / args.receipt).open('x') as output:
        json.dump(RECEIPT, output, indent=2, sort_keys=True); output.write('\n')
    raise SystemExit(0 if result.wasSuccessful() else 1)
