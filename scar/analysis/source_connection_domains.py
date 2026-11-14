"""Mechanical connection-layer input domains, independent of graph rules.

Walk declaration types, never instruction instances or application values.
This inventory makes no claim about implemented connections or complete edges.
"""
from dataclasses import fields, is_dataclass
from enum import Enum
from hashlib import sha256
import json
from pathlib import Path
import sys
from typing import get_args, get_origin, get_type_hints

from scar.ir.program import source_productions as P
from scar.ir.program.source_observed_codes import ObservedSourceScopeKind, ObservedSourceRequestKind
from scar.ir.program.python_call_targets import PythonTargetKind, PythonCodeScope
from scar.ir.program.normal_targets import FunctionActivation, ArgumentBinding
from scar.ir.program.call_edges import FrameCompletion
from scar.ir.program.native_callables import NativeCarrier, NativeFieldState
from scar.ir.program.source_contexts import OwnerRef, SourceScope, EvaluationRegion
from scar.ir.program.compiler_topology import TopologyCatalog
from scar.analysis.compiler_topology import compiler_topology_catalog


SCHEMA = 'scar.source-connection-domains'
SCHEMA_VERSION = 1


def _name(kind):
    return kind.__module__ + '.' + kind.__qualname__


def _canonical(value):
    return json.dumps(value,sort_keys=True,ensure_ascii=True,
        separators=(',',':'),allow_nan=False).encode('ascii')


def connection_domains():
    """Regenerate domains from the live finite type declarations/catalog."""
    instructions = get_args(P.ProductionInstruction)
    if not instructions or any(not isinstance(kind,type) or not is_dataclass(kind) for kind in instructions):
        raise ValueError('ProductionInstruction must retain its explicit dataclass union')
    explicit = (P.ProductionRegionKind,ObservedSourceScopeKind,ObservedSourceRequestKind,
        PythonTargetKind,PythonCodeScope,FunctionActivation,ArgumentBinding,
        FrameCompletion,NativeCarrier,NativeFieldState)
    classifications = tuple((kind,get_type_hints(kind)['kind'])
        for kind in (OwnerRef,SourceScope,EvaluationRegion))
    pending = [*instructions,*explicit,*(annotation for _,annotation in classifications)]
    seen = set(); enums = {}; modules = set()
    while pending:
        annotation = pending.pop()
        if annotation in seen:continue
        seen.add(annotation)
        origin = get_origin(annotation)
        if origin is not None:
            pending.extend(get_args(annotation))
            continue
        if not isinstance(annotation,type):continue
        modules.add(annotation.__module__)
        if issubclass(annotation,Enum):
            enums[_name(annotation)] = dict(type=_name(annotation),values=[member.value for member in annotation])
        elif is_dataclass(annotation):
            hints = get_type_hints(annotation)
            pending.extend(hints[field.name] for field in fields(annotation))

    open_fields = []; classification_fields = []
    for kind,annotation in classifications:
        modules.add(kind.__module__)
        closed = isinstance(annotation,type) and issubclass(annotation,Enum)
        field = dict(type=_name(kind),field='kind',
            annotation=_name(annotation) if isinstance(annotation,type) else str(annotation),
            status='CLOSED_ENUM_DOMAIN' if closed else 'OPEN_TYPE_DOMAIN',type_layer_gap=not closed)
        classification_fields.append(field)
        if not closed:open_fields.append(field)
    topology = compiler_topology_catalog()
    catalog_domains = [dict(type=_name(TopologyCatalog),field=field,
        authority=compiler_topology_catalog.__module__+'.'+compiler_topology_catalog.__qualname__,
        values=list(topology[field])) for field in ('origin_roles','projections')]
    modules.update((P.__name__,TopologyCatalog.__module__,compiler_topology_catalog.__module__,__name__))
    receipts = {}
    for module_name in sorted(modules):
        module = sys.modules[module_name]
        filename = getattr(module,'__file__',None)
        if filename is None:continue  # Builtin declarations have no source file.
        path = Path(filename).resolve(); before = path.stat(); raw = path.read_bytes(); after = path.stat()
        stamp = lambda value:(value.st_dev,value.st_ino,value.st_size,value.st_mtime_ns,value.st_ctime_ns)
        if stamp(before) != stamp(after) or len(raw) != before.st_size:
            raise ValueError('connection-domain declaration changed during inventory: '+module_name)
        receipts[module_name] = dict(path=str(path),sha256=sha256(raw).hexdigest())
    result = dict(schema=SCHEMA,schema_version=SCHEMA_VERSION,
        instruction_domain=dict(type=P.__name__+'.ProductionInstruction',
            values=[_name(kind) for kind in instructions]),
        enum_domains=[enums[name] for name in sorted(enums)],catalog_domains=catalog_domains,
        classification_fields=classification_fields,open_fields=open_fields,declaration_modules=receipts,
        type_domains_closed=not open_fields,graph_rules_implemented_claimed=False,graph_edges_complete_claimed=False)
    result['content_sha256'] = sha256(_canonical(result)).hexdigest()
    return result


def read_connection_domains(document):
    """Independently regenerate and compare, rather than trust saved counts."""
    if isinstance(document,(str,Path)):
        document = json.loads(Path(document).read_bytes())
    if type(document) is not dict or 'content_sha256' not in document:
        raise ValueError('connection domains require their canonical content receipt')
    content = {name:value for name,value in document.items() if name != 'content_sha256'}
    if sha256(_canonical(content)).hexdigest() != document['content_sha256']:
        raise ValueError('connection-domain content SHA differs')
    expected = connection_domains()
    if _canonical(document) != _canonical(expected):
        raise ValueError('connection-domain declarations, catalog or module receipts differ')
    return expected
