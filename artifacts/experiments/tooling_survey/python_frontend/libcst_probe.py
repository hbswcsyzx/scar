"""Evaluate one pinned optional frontend in a disposable directory, not conda."""
import hashlib
import importlib.metadata
import json
import pathlib
import sys
import tempfile
import time
import urllib.request
import zipfile

ROOT = pathlib.Path(__file__).resolve().parent


def main():
    start = time.monotonic()
    with urllib.request.urlopen("https://pypi.org/pypi/libcst/1.9.0/json", timeout=30) as response:
        metadata = json.load(response)
    candidates = [f for f in metadata["urls"]
                  if "cp314-cp314-manylinux" in f["filename"]
                  and f["filename"].endswith("x86_64.whl")]
    # Both manylinux_2_28 and older-compatible wheels may be offered; pin the
    # actual selected filename/hash below instead of guessing from a package name.
    wheel = sorted(candidates, key=lambda f: f["filename"])[0]
    with urllib.request.urlopen(wheel["url"], timeout=30) as response:
        payload = response.read()
    digest = hashlib.sha256(payload).hexdigest()
    assert digest == wheel["digests"]["sha256"]
    results = []
    with tempfile.TemporaryDirectory(prefix="scar-libcst-tooling-") as directory:
        wheel_path = pathlib.Path(directory) / wheel["filename"]
        wheel_path.write_bytes(payload)
        target = pathlib.Path(directory) / "package"
        with zipfile.ZipFile(wheel_path) as archive:
            archive.extractall(target)
        sys.path.insert(0, str(target))
        import libcst as cst
        from libcst.metadata import MetadataWrapper, PositionProvider, ScopeProvider
        sources = {
            "comments_and_formatting": "# keep me\nresult  = (1 + 2)  # trailing\n",
            "imports_and_access": "import math as m\nunused = 4\ndef f(x):\n    return m.sqrt(x)\n",
            "type_parameters": "type Pair[T] = tuple[T, T]\n",
            "template_string": 'template = t"value={item}"\n',
            "try_finally": "def f(x):\n    try:\n        return x\n    finally:\n        cleanup()\n",
        }
        for name, source in sources.items():
            row = {"name": name, "source": source}
            try:
                module = cst.parse_module(source)
                row["parse"] = "PASS"
                row["roundtrip_exact"] = module.code == source
                wrapper = MetadataWrapper(module)
                positions = wrapper.resolve(PositionProvider)
                row["position_nodes"] = len(positions)
                try:
                    scopes = wrapper.resolve(ScopeProvider)
                    unique = {id(scope): scope for scope in scopes.values()}
                    row["scopes"] = [{"type": type(scope).__name__,
                                      "assignments": [{"name": a.name, "references": len(a.references)}
                                                      for a in scope.assignments]}
                                     for scope in unique.values()]
                    row["scope_provider"] = "PASS"
                except Exception as error:
                    row["scope_provider"] = "ERROR"
                    row["scope_error"] = {"type": type(error).__name__, "message": str(error)}
            except Exception as error:
                row["parse"] = "ERROR"
                row["parse_error"] = {"type": type(error).__name__, "message": str(error)}
            results.append(row)
        package_version = importlib.metadata.version("libcst")
        sys.path.remove(str(target))
    report = {
        "python": sys.version, "executable": sys.executable,
        "package": "libcst", "version": package_version,
        "wheel": {"filename": wheel["filename"], "url": wheel["url"],
                  "bytes": len(payload), "sha256": digest},
        "command": "PYTHONDONTWRITEBYTECODE=1 /home/zyf/miniconda3/envs/lewm/bin/python "
                   "artifacts/experiments/tooling_survey/python_frontend/libcst_probe.py",
        "probe_sha256": hashlib.sha256(pathlib.Path(__file__).read_bytes()).hexdigest(),
        "installation": "one isolated temporary wheel extraction; conda unchanged; directory removed",
        "cases": results, "elapsed_seconds": time.monotonic() - start,
        "scope": "parser/metadata compatibility witnesses, no SCAR adapter or complete dataflow proof",
    }
    (ROOT / "libcst-result.json").write_text(json.dumps(report, indent=2) + "\n")
    print(json.dumps({"version": package_version, "wheel_bytes": len(payload),
                      "cases": [{k: row[k] for k in ("name", "parse", "roundtrip_exact", "scope_provider") if k in row}
                                for row in results]}))


if __name__ == "__main__":
    main()
