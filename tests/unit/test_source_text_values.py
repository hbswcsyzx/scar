"""Captured text-open candidates retain provider, path and decoding conditions."""
import gzip
from hashlib import sha256
import json
import pathlib
from pathlib import Path

from scar.analysis.normal_facts import SourceFactStore
from scar.analysis.normal_links import _pins
from scar.analysis.source_bytes import source_bytes_document
from scar.analysis.source_launch import declare_script_entry
from scar.analysis.source_text_values import source_text_candidates
from scar.ir.program import source_text as X, source_productions as P
from scar.ir.record_codec import encode, decode
from tests.unit.test_source_construction_connections import source_facts
from tests.unit.test_source_expression_rules import _documents


def test_pathlib_source_text_uses_raw_open_rules_and_excludes_local_shadow(tmp_path):
    source = '''
from pathlib import Path as Location, PurePath
base = Location(__file__).resolve().parent
path = base / 'payload.py'
content = path.read_text()
exact = path.read_text(encoding='utf-8', newline='')
pure = PurePath(__file__).parent / 'payload.py'
pure.read_text()
def shadow(Location):
    return Location(__file__).read_text()
'''
    unit = source_facts(source)
    f0, _, f2, *_ = _documents(source)
    raw_payload = b"# coding: latin-1\r\nvalue = 'caf\xc3\xa9'\r\n"
    model = tmp_path/'model'
    model.mkdir()

    def artifact(name, document):
        decoded = json.dumps(document,sort_keys=True,separators=(',',':')).encode()
        stored = gzip.compress(decoded,mtime=0)
        (model/name).write_bytes(stored)
        return dict(path=name,bytes=len(stored),sha256=sha256(stored).hexdigest(),
            decoded_bytes=len(decoded),decoded_sha256=sha256(decoded).hexdigest())

    stdlib = str(Path(pathlib.__file__).absolute())
    payload_f0 = source_bytes_document(raw_payload,path='/source/payload.py',namespace_root='/source')
    rows = [dict(key=unit.unit,path=f0['path'],namespace_root='/source',artifacts={
                'source_bytes':artifact('script-f0.json.gz',f0),'source_syntax':artifact('script-f2.json.gz',f2)}),
            dict(key='text-payload',path='/source/payload.py',namespace_root='/source',artifacts={
                'source_bytes':artifact('payload-f0.json.gz',payload_f0)}),
            dict(key='stdlib-pathlib',path=stdlib,namespace_root=str(Path(stdlib).parent.parent),artifacts={
                'source_bytes':artifact('pathlib-f0.json.gz',source_bytes_document(Path(stdlib).read_bytes(),
                    path=stdlib,namespace_root=str(Path(stdlib).parent.parent)))})]
    (model/'manifest.json').write_text(json.dumps(dict(schema='CONTROLLED_SOURCE_MATERIAL_DIRECTORY',units=rows)))
    # Actual F5 records/ports come from the source frontend. The minimal
    # receipt-bound directory supplies controlled parents; no F4 body is read.
    facts, templates = tmp_path/'facts', tmp_path/'templates'
    facts.mkdir(); templates.mkdir()
    (templates/'result.json').write_text('{"schema":"CONTROLLED_UNREAD_F4_PARENT"}')
    decoded = json.dumps(encode(unit,record_tags=P.PRODUCTION_RECORD_TAGS)).encode()
    stored = gzip.compress(decoded,mtime=0)
    (facts/'unit.json.gz').write_bytes(stored)
    row = dict(unit=unit.unit,module=unit.module,path=f0['path'],facts='unit.json.gz',
        bytes=len(stored),sha256=sha256(stored).hexdigest(),decoded_bytes=len(decoded),
        decoded_sha256=sha256(decoded).hexdigest(),counts={'ports':len(unit.ports)})
    report = dict(schema='scar.normal-source-link-facts',schema_version=6,
        implementation_sha256=_pins(),model=str(model),templates=str(templates),
        model_manifest_sha256=sha256((model/'manifest.json').read_bytes()).hexdigest(),
        source_result_sha256=sha256((templates/'result.json').read_bytes()).hexdigest(),units=[row])
    (facts/'result.json').write_text(json.dumps(report))
    store = SourceFactStore(facts)
    entry = declare_script_entry(store,f0['path'],cwd='/source',argv=(f0['path'],))
    overlay = source_text_candidates(store,store.load(unit.unit),entry)
    assert len(overlay.reads) == 2
    assert len(overlay.candidates) == 2
    assert any(p.lexical_path=='/source/payload.py' for p in overlay.path_values)
    assert any(o.reason.startswith('PURE_PATH_HAS_NO_FILESYSTEM_METHOD') for o in overlay.obligations)
    default, = [c for c in overlay.candidates if c.interpretation.default_encoding]
    explicit, = [c for c in overlay.candidates if not c.interpretation.default_encoding]
    assert default.raw_sha256 == explicit.raw_sha256 == sha256(raw_payload).hexdigest()
    assert default.text_utf8_sha256 == sha256(raw_payload.decode('utf-8').replace('\r\n','\n').encode()).hexdigest()
    assert explicit.text_utf8_sha256 == sha256(raw_payload.decode('utf-8').encode()).hexdigest()
    assert default.text_utf8_sha256 != payload_f0['decoding']['decoded_utf8_sha256']
    assert 'TEXT_OPEN_DEFAULT_ENCODING_SELECTS_UTF8' in default.conditions
    assert default.obligations and not explicit.obligations
    assert default.interpretation.newline is None and explicit.interpretation.newline == ''
    assert all(c.source_path=='/source/payload.py' and c.source.declaration is not None for c in overlay.candidates)
    assert all('PATH_RESOLUTION_HAS_NO_SYMLINK_REDIRECTION' in c.conditions for c in overlay.candidates)
    assert all(r.site.world != r.site.result_world and r.owner==unit.root_scope.owner for r in overlay.reads)
    assert decode(X.SourceTextOverlay,encode(overlay,record_tags=P.PRODUCTION_RECORD_TAGS),
                  record_tags=P.PRODUCTION_RECORD_TAGS)==overlay
