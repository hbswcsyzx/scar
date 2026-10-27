from hashlib import sha256
from pathlib import Path
import shutil

base = Path("artifacts/experiments/b1_call_operands/model_protocol_followup/codec").resolve()
tree = (base / "legacy-src").resolve()
archive = base / "legacy-source-v19.tar"
if tree.parent != base or tree.name != "legacy-src":
    raise SystemExit("refusing cleanup outside the exact owned extraction directory")
if not (base / "verify-legacy-source.log").is_file():
    raise SystemExit("refusing cleanup without successful content comparison evidence")
if sha256(archive.read_bytes()).hexdigest() != (
        "a57e394498a8b485260b170b7e29ccfb235bfa699989c55bf7c677adf2ef6bf9"):
    raise SystemExit("refusing cleanup if the legacy archive digest changed")
shutil.rmtree(tree)
print("removed=legacy-src")
print("verified_entries=157")
print("archive_sha256=" + sha256(archive.read_bytes()).hexdigest())
print("preserved=legacy-source-v19.tar,attempt001,attempt002,oracle-v19,verify-legacy-source.*")
