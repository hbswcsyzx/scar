"""Pure syntax/field/layout check; no capture, target or body source read."""
import ast
from dataclasses import fields
from hashlib import sha256
import inspect
import json
from pathlib import Path
import sys

BASE = Path(__file__).resolve().parents[3]
names = ('scar/analysis/source_invocations.py', 'scar/analysis/source_entry_routing.py',
         'scar/analysis/source_entry_routing_validation.py')
receipts = []
for name in names:
    raw = (BASE/name).read_bytes()
    ast.parse(raw, filename=name)
    receipts.append({'path': name, 'bytes': len(raw), 'sha256': sha256(raw).hexdigest()})
from scar.analysis.source_invocations import bind_source_invocations
from scar.analysis.source_entry_routing import ENTRY_ROUTING_PROFILE, EntryRoutingSession
from scar.analysis.source_entry_routing_validation import require_code_layout, EntryRoutingError, _same
from scar.ir.program.call_edges import CapturedCode, ReferenceOccurrence
from scar.ir.program.functions import FormalParameter, FunctionSignature, ParameterKind
from scar.ir.v2.common import SourceReference
from scar.ir.v2.ids import SourceAtomID, ValueSlotID, OperationDefinitionID
assert inspect.signature(bind_source_invocations).parameters['entry_routing_profile'].default is None
assert {'core_value','source_reference','ref','anchor'} <= {x.name for x in fields(ReferenceOccurrence)}
assert not _same({'ordinal': True}, {'ordinal': 1})
source = SourceReference(SourceAtomID('pure-field-check'), '/pure/api.py', 'sha256:'+'0'*64, 1, 1)
ordered = [('a',ParameterKind.POSITIONAL), ('args',ParameterKind.VAR_POSITIONAL),
           ('k',ParameterKind.KEYWORD_ONLY), ('kw',ParameterKind.VAR_KEYWORD)]
signature = FunctionSignature(OperationDefinitionID('pure-field-check'), source,
    tuple(FormalParameter(name,kind,ValueSlotID('pure:'+name),source) for name,kind in ordered))
descriptor = CapturedCode('pycode-v2:'+'0'*64,'/pure/api.py','f',1,15,('a','k','args','kw'))
require_code_layout(descriptor, signature)
bad = CapturedCode(descriptor.key,descriptor.filename,descriptor.qualname,1,15,('a','args','k','kw'))
try:
    require_code_layout(bad, signature)
except EntryRoutingError:
    pass
else:
    raise AssertionError('blind signature zip was accepted as code layout')
try:
    EntryRoutingSession(None,None,None,None,None,None)
except TypeError:
    pass
else:
    raise AssertionError('caller constructed an owned routing session')
assert 'torch' not in sys.modules
print(json.dumps({'status':'PASS_PURE_SYNTAX_FIELDS_LAYOUT','sources':receipts,
    'profile':ENTRY_ROUTING_PROFILE,'default_off':True,'name_slot_mapping_required':True,
    'raw_reads':0,'body_reads':0,'target_runs':0,'owned_producer_runs':0,'torch_imports':0},indent=2))
