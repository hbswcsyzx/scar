import hashlib, importlib.util, json
from pathlib import Path
import scar.ir.execution.codec as codec
spec = importlib.util.spec_from_file_location("old_fixture", "tests/unit/test_execution_production_codec.py")
fixture = importlib.util.module_from_spec(spec)
spec.loader.exec_module(fixture)
model = fixture.production_model.__wrapped__()
payload = codec.dumps(model).encode("utf-8")
Path("v5.json").write_bytes(payload)
assert codec.SCHEMA_VERSION == 5
assert codec.loads(payload.decode()) == model
print(json.dumps({"codec_file":str(Path(codec.__file__).resolve()),
 "codec_sha256":hashlib.sha256(Path(codec.__file__).read_bytes()).hexdigest(),
 "fixture_file":str(Path(fixture.__file__).resolve()),
 "fixture_sha256":hashlib.sha256(Path(fixture.__file__).read_bytes()).hexdigest(),
 "schema_version":5,"payload_sha256":hashlib.sha256(payload).hexdigest(),
 "payload_bytes":len(payload),"p_table_counts":{k:len(getattr(model,k)) for k in
 ("source_inventories","source_bridges","writes","produced")}},sort_keys=True))
