"""Compile retained text under explicit flags; never execute the program."""
from hashlib import sha256
from pathlib import Path
from types import SimpleNamespace
import __future__

from scar.analysis import source_execution
from scar.analysis.source_compiled_values import compile_source_candidates
from scar.analysis.source_compilation_contexts import code_digest
from scar.ir.program import source_text as S, source_compiled_values as X, source_productions as P
from scar.ir.program.source_bytes import SourceBytesProfile
from scar.ir.program.source_references import SourceArtifactLocator
from scar.ir.program.providers import ProviderArtifact
from scar.ir.record_codec import encode, decode
from tests.unit.test_source_construction_connections import source_facts
from tests.unit.test_source_expression_rules import _documents


def test_path_filename_context_inheritance_and_shadow(monkeypatch):
    source = '''
from pathlib import Path
path = Path(__file__).parent / 'payload.py'
text = reader()
code = compile(text, str(path), 'exec')
isolated = compile(text, 'literal.py', 'exec', dont_inherit=True)
def shadow(str):
    return compile(text, str(path), 'exec')
'''
    unit = source_facts(source)
    f0, _, syntax, *_ = _documents(source)
    annotations = __future__.annotations.compiler_flag
    runtime = decode(SourceBytesProfile,f0['profile'])
    entry = SimpleNamespace(source=SimpleNamespace(unit=unit.unit,
        raw_sha256=syntax['input']['raw_sha256'],runtime=runtime),root=unit.root_scope,
        compilation=SimpleNamespace(optimize=0,effective_flags=annotations))
    monkeypatch.setattr(source_execution,'_Fragments',lambda path:SimpleNamespace(read=lambda ref:syntax))
    store = SimpleNamespace(model_for=lambda identity:Path('/controlled-source'),
        model_units={unit.unit:{'artifacts':{'source_syntax':{}}}})
    boundaries, contexts, _ = source_execution.source_builtin_boundaries(store,unit,entry=entry)
    gp = lambda ordinal:source_execution.T.GlobalPort(unit.unit,unit.ports[ordinal])
    join = unit.operations[0]
    path = S.SourcePathCandidate('controlled-path',gp(join.result),'/controlled/payload.py',
        ('CONTROLLED_STANDARD_PATH_CANDIDATE',))
    name_reads = {a.value for a in unit.names if not a.write and a.namespace.name=='reader'}
    # Original callee-to-call aliases select the controlled material port.
    adjacency = {}
    for a,b in unit.aliases:
        adjacency.setdefault(a,set()).add(b)
    reached = source_execution._reach(adjacency,name_reads)
    read = next(c for c in unit.calls if c.callee in reached)
    raw = b'value: int = 1\n'
    digest = sha256(raw).hexdigest()
    locator = SourceArtifactLocator(ProviderArtifact('/controlled/payload-f0.json.gz',
        '0'*64,1,'CONTROLLED_FIXTURE'),'0'*64,1,'gzip-canonical-json')
    text = S.SourceTextCandidate(gp(read.result),'controlled-path','controlled-payload',
        '/controlled/payload.py',locator,'0'*64,digest,len(raw),
        S.TextOpenInterpretation('utf-8','strict',None,True,False),digest,len(raw),
        ('CONTROLLED_CAPTURED_TEXT_CANDIDATE',))
    result = compile_source_candidates(unit,boundaries,contexts,(text,),(path,),entry,
        lambda candidate:(raw,None))
    assert len(result.candidates)==2
    derived = next(c for c in result.candidates if c.context.filename=='/controlled/payload.py')
    isolated = next(c for c in result.candidates if c.context.filename=='literal.py')
    assert derived.context.inherited_future_flags==annotations
    assert derived.context.compiled_future_flags & annotations
    assert isolated.context.inherited_future_flags==0 and not isolated.context.compiled_future_flags & annotations
    expected = compile(raw.decode('utf-8'),'/controlled/payload.py','exec',flags=annotations,
                       dont_inherit=True,optimize=0)
    assert derived.code_digest==code_digest(expected)
    assert any(o.reason=='COMPILE_FILENAME_VALUE_NOT_RESOLVED' for o in result.obligations)
    assert all(c.matched_body is None and 'CONTEXT_QUALIFIED_F3_F4_VARIANT_NOT_BUILT' in c.obligations
               for c in result.candidates)
    assert decode(X.CompiledSourceOverlay,encode(result,record_tags=P.PRODUCTION_RECORD_TAGS),
                  record_tags=P.PRODUCTION_RECORD_TAGS)==result
