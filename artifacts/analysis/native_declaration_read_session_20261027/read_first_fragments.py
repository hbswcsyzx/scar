#!/home/zyf/miniconda3/envs/lewm/bin/python
"""Read a bounded prefix of one existing native declaration publication."""
import argparse
from collections import Counter
from hashlib import sha256
import json
from pathlib import Path
import sys
import time

sys.path.insert(0, str(Path(__file__).resolve().parents[3]))
from scar.analysis.native_declaration_interfaces import NativeDeclarationBudget, NativeDeclarationReadSession
from scar.ir.program.providers import ProviderArtifact
from scar.ir.record_codec import decode, loads as strict_json

DEFAULT_PUBLICATION = "/home/zyf/AAA/scar-worktrees/structured-program-model/artifacts/experiments/native_declaration_full_20261027/attempt01/manifest.json"
DEFAULT_SHA256 = "8dba167f8c14df8431b3964b999efa4a11b6f82edd586d5287ecb012f57aae4e"


def read_receipted_json(ref, maximum):
    artifact = decode(ProviderArtifact, ref)
    path = Path(artifact.uri)
    if not path.is_absolute() or path.resolve(strict=True) != path or path.is_symlink():
        raise ValueError("publication member URI is not a stable absolute path")
    raw = path.read_bytes()
    if len(raw) != artifact.size_bytes or len(raw) > maximum or sha256(raw).hexdigest() != artifact.sha256:
        raise ValueError("publication member receipt differs")
    return artifact, strict_json(raw.decode())


def main():
    parser = argparse.ArgumentParser()
    parser.add_argument("--publication", default=DEFAULT_PUBLICATION)
    parser.add_argument("--expected-publication-sha256", default=DEFAULT_SHA256)
    parser.add_argument("--fragment-count", type=int, default=2)
    parser.add_argument("--max-input-bytes", type=int, default=4_000_000_000)
    parser.add_argument("--max-seconds", type=int, default=1800)
    parser.add_argument("--result", default=str(Path(__file__).with_name("ACTUAL_RESULT.json")))
    args = parser.parse_args()
    if not 1 <= args.fragment_count <= 16:
        raise ValueError("bounded fragment count must be in [1,16]")

    publication_path = Path(args.publication).resolve(strict=True)
    publication_raw = publication_path.read_bytes()
    publication_sha = sha256(publication_raw).hexdigest()
    if publication_sha != args.expected_publication_sha256:
        raise ValueError("native declaration publication SHA differs")
    publication = strict_json(publication_raw.decode())
    if publication.get("schema") != "scar.native-declaration-pipeline" or publication.get("schema_version") != 1:
        raise ValueError("unsupported native declaration publication")
    if not publication.get("all_source_shards_processed") or not publication.get("whole_source_range_indexed"):
        raise ValueError("publication is not the completed indexed source range")

    _, shard = read_receipted_json(publication["shards"][0]["artifact"], 16_000_000)
    fragments = tuple(decode(ProviderArtifact, item) for item in shard["fragments"])
    if len(fragments) < args.fragment_count:
        raise ValueError("first source shard lacks requested fragments")
    catalog_ref = publication["catalog"]
    catalog, catalog_doc = read_receipted_json(catalog_ref, 16_000_000)
    if shard.get("catalog") != catalog_ref or catalog_doc.get("schema") != "scar.native-declaration-catalog":
        raise ValueError("source shard and publication catalog differ")

    started = time.perf_counter()
    results = []
    budget = NativeDeclarationBudget(max_input_bytes=args.max_input_bytes, max_seconds=args.max_seconds)
    with NativeDeclarationReadSession(catalog, budget=budget) as reader:
        for fragment in fragments[:args.fragment_count]:
            view = reader.read_fragment(fragment)
            results.append({
                "fragment": {"uri": fragment.uri, "sha256": fragment.sha256, "size_bytes": fragment.size_bytes},
                "operation_rows": len(view.occurrences),
                "input_ports": sum(len(row.inputs) for row in view.occurrences),
                "conditional_output_ports": sum(len(row.output_sources) for row in view.occurrences),
                "validation_valid": view.validation.valid,
                "validation_issue_count": len(view.validation.issues),
                "measurement_scope": view.measurements["measurement_scope"],
                "cumulative_measurements": view.measurements,
            })
        reads = Counter(str(path) for path, _ in reader.meter.inputs)
        coordinate_uri = reader.coordinates_artifact.uri
        catalog_uri = catalog.uri
        program_uri = reader.program_artifact.uri
        interface_uri = reader.interface_artifact.uri
        result = {
            "status": "PASS" if all(r["validation_valid"] and r["validation_issue_count"] == 0 for r in results) else "FAIL",
            "publication": {"uri": str(publication_path), "sha256": publication_sha, "size_bytes": len(publication_raw)},
            "catalog": {"uri": catalog.uri, "sha256": catalog.sha256, "size_bytes": catalog.size_bytes},
            "source_shard": shard["source_shard_index"],
            "fragments": results,
            "read_session": {
                "elapsed_seconds": time.perf_counter() - started,
                "measurements": reader.measurements,
                "tracked_path_reads": dict(sorted(reads.items())),
                "catalog_path_count": reads[catalog_uri],
                "coordinates_path_count": reads[coordinate_uri],
                "program_path_count": reads[program_uri],
                "interfaces_path_count": reads[interface_uri],
            },
            "scope": "Only the first bounded fragments were normally decoded and source-validated; no new native build or raw ETO rescan.",
        }
    output = Path(args.result)
    output.parent.mkdir(parents=True, exist_ok=True)
    output.write_text(json.dumps(result, sort_keys=True, indent=2) + "\n")
    print(json.dumps(result, sort_keys=True))
    if result["status"] != "PASS":
        raise SystemExit(1)


if __name__ == "__main__":
    main()
