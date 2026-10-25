"""Fixed experiment selection; no production imports or target execution."""
from pathlib import Path

HERE = Path(__file__).resolve().parent
ROOT = HERE.parents[2]
EXPS = HERE.parent
OLD = EXPS / 'first_stage_current_source_gate_20261023'
BASELINE = EXPS / 'first_stage_source_publication_current_attempt04_20261023'
REVISION = EXPS / 'first_stage_source_body_revision_20261023'
ANCESTOR = EXPS / 'first_stage_source_membership_ancestor_20261023'
PUBLISHED = REVISION / 'result'
COMPOSITION = PUBLISHED / 'composition/index.json.gz'
CAPTURE = EXPS / 'first_stage_lewm_physical_20261023'
ATTACHMENT = EXPS / 'first_stage_dependency_continuation_20261023/result/continuation.json'
BRIDGE = EXPS / 'first_stage_joined_physical_20261023/result/native/dispatch-bridge.json.gz'
PROFILE = OLD / 'result/capture-coordinates.json'
CACHE = EXPS / 'first_stage_partitioned_operand_routes_20261023/result/code-witnesses'
STALE_SOURCE = EXPS / 'first_stage_source_publication_current_attempt02_20261023/result/connections/source'
EXPECTED_RUN = 'capture:1ddea1de4990462b59cf5dd24beb3f120156eb47bca68cfb3f1a63f9f73f2cf0'
EXPECTED_PUBLISHED_SHA256 = {
    str(COMPOSITION): '3424d0715a86a5a7db28c7a4617440c4307558c8d3cc7e2f8b9f5ddf2d3dd36c',
    str(PUBLISHED / 'publication/manifest.json'): '97342c29aaab8460f45b67a038e3a3cee22d1781393e1f57a4d7b22e58d26505',
    str(REVISION / 'summary.json'): '19569d4914cf5da2c02245bb9d6458b748bcad3ecd484050dc93caa29cc9ef23',
}
EXPECTED_ANCESTOR_PRODUCERS = {
    'scar/analysis/program_composition.py': 'a0577c7762a53a1c167451bf6b4bd0bd029cd82bbd115721b36315f283dda070',
    'scar/analysis/current_source_evidence.py': '1886477d1845dd5ddf669aec8b2b5830c375cbb328647e345b6329615d09cdf2',
}
BUDGETS = {
    'wall_seconds': 5400, 'cpu_seconds': 5400, 'address_space_bytes': 12 * 1024**3,
    'max_output_file_bytes': 2_200_000_000, 'input_files': 4096,
    'input_file_bytes': 2_200_000_000, 'input_total_bytes': 8_000_000_000,
    'metadata_decoded_bytes': 128_000_000, 'producer_source_bytes': 32_000_000,
    'coordinate_bytes': 2_000_000_000, 'coordinate_lines': 2_000_000,
    'ancestry_depth': 16, 'ancestry_decoded_bytes': 1_000_000_000,
    'heartbeat_seconds': 20, 'audit_stream_decoded_bytes': 2_000_000_000,
    'audit_stream_rows': 2_000_000, 'audit_line_bytes': 16_000_000,
}
FRAME_BUDGET = dict(max_raw_bytes=256_000_000, max_lines=300_000, max_events=250_000,
    max_references=2_000_000, max_source_files=256, max_source_bytes=16_000_000)
OPERAND_BUDGET = dict(max_raw_bytes=128_000_000, max_lines=1_000_000,
    max_line_bytes=2_000_000, max_processes=128, max_events=1_000_000,
    max_loads=1_000_000, max_references=2_000_000, max_metadata_bytes=2_000_000)
ROUTE_BUDGET = dict(max_routes=100_000, max_template_values=100_000)
