"""Retain exact primary provider source revisions; never execute them."""
from concurrent.futures import ThreadPoolExecutor
import hashlib
import json
from pathlib import Path
from urllib.request import Request, urlopen

torch_revision = "cf30153c4c131c8164ee7798e5022d810682e2cb"
kineto_revision = "094d3c1d072362d0a919a77299459eee94f97931"
root = Path(__file__).resolve().parent / "sources"
root.mkdir(exist_ok=False)
sources = [("torch-collection.cpp", "pytorch", torch_revision, "torch/csrc/profiler/collection.cpp"),
           ("kineto-shim.cpp", "pytorch", torch_revision, "torch/csrc/profiler/kineto_shim.cpp"),
           *[(name, "kineto", kineto_revision, "libkineto/src/" + name)
             for name in ["CuptiActivityApi.cpp", "CuptiActivityProfiler.cpp",
                          "GenericActivityProfiler.cpp", "output_json.cpp"]]]


def fetch(row):
    name, repo, revision, path = row
    url = f"https://raw.githubusercontent.com/pytorch/{repo}/{revision}/{path}"
    with urlopen(Request(url, headers={"User-Agent": "SCAR-model-audit"}), timeout=45) as response:
        payload = response.read(2_000_001)
    if len(payload) > 2_000_000:
        raise ValueError("source unexpectedly large")
    (root / name).write_bytes(payload)
    return {"file": name, "url": url, "revision": revision,
            "bytes": len(payload), "sha256": hashlib.sha256(payload).hexdigest()}


with ThreadPoolExecutor(max_workers=3) as pool:
    manifest = list(pool.map(fetch, sources))
url = ("https://api.github.com/repos/pytorch/pytorch/contents/third_party/kineto?ref="
       + torch_revision)
with urlopen(Request(url, headers={"User-Agent": "SCAR-model-audit"}), timeout=45) as response:
    payload = response.read(2_000_001)
assert json.loads(payload)["sha"] == kineto_revision
(root / "kineto-gitlink.json").write_bytes(payload)
manifest.append({"file": "kineto-gitlink.json", "url": url,
                 "bytes": len(payload), "sha256": hashlib.sha256(payload).hexdigest()})
(root / "manifest.json").write_text(json.dumps(manifest, indent=2) + "\n")
print(json.dumps({"files": len(manifest), "bytes": sum(row["bytes"] for row in manifest)}))
