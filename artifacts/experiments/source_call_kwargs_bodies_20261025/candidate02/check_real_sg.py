"""One direct check against the first existing archived SG, not body lowering."""
import hashlib
import json
from pathlib import Path
import unittest

from scar.analysis.source_layers import load_source_layers
from scar.analysis.source_call_validation import is_original_call_definition
from scar.ir.record_codec import encode
from scar.ir.semantics_v2 import Opcode
from scar.ir.v2.semantic import OperationKind

BASE=Path(__file__).resolve().parent
OLD=BASE.parent
RECORD={}

class ExistingSGCall(unittest.TestCase):
    def test_original_opaque_call_and_computational_opcode(self):
        selection=json.loads((OLD/'selection.json').read_bytes())
        item=selection['selected'][0]
        view=load_source_layers(selection['source_layers'],item['snapshot']['path'],max_record_bytes=64_000_000)
        ref=item['frontier']['source']
        candidates=[a.reference for a in view.semantic.source_atoms.values() if a.kind=='Call'
                    and encode(a.reference)==ref]
        self.assertEqual(len(candidates),1)
        source=candidates[0]
        definitions=[d for d in view.semantic.definitions.values()
                     if is_original_call_definition(view.semantic,d,source)]
        self.assertEqual(len(definitions),1)
        definition=definitions[0]
        self.assertIs(definition.kind,OperationKind.OPAQUE)
        self.assertEqual(definition.metadata['ast_type'],'Call')
        self.assertEqual(len(definition.output_slots),1)
        calls=[r for r in view.semantics.operations.values()
               if r.operation==definition.id and r.source==source and r.opcode is Opcode.CALL]
        self.assertEqual(len(calls),1)
        RECORD.update(source=encode(source),definition=encode(definition.id),sg_kind=definition.kind.value,
                      ast_type=definition.metadata['ast_type'],opcode=calls[0].opcode.value,
                      existing_archive=encode(view.artifact_locator),source_context=encode(view.context))

if __name__=='__main__':
    result=unittest.TextTestRunner(verbosity=2).run(unittest.defaultTestLoader.loadTestsFromTestCase(ExistingSGCall))
    RECORD.update(tests=result.testsRun,passed=result.wasSuccessful(),body_lowerings=0,target_executions=0,
                  code_witness_payloads_loaded=0,new_source_prepares=0,raw_capture_reads=0,
                  reused_legacy_checks=str((OLD.parent/'source_call_model_20261025/small-check-receipt-03.json').resolve()),
                  legacy_checks_rerun=False)
    with (BASE/'real-sg-check-receipt.json').open('x') as f:json.dump(RECORD,f,sort_keys=True,indent=2);f.write('\n')
    raise SystemExit(0 if result.wasSuccessful() else 1)
