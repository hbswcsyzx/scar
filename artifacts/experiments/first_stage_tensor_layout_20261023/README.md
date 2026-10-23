# Tensor layout admission: bounded actual gate

PASS, exit0. One production file changed: tensor_physical_import.py.

`gate.py` regenerates4 StorageRegion records from the first28 actual physical
rows,70 ETO nodes and16 existing region rows. It uses the existing allocation
IDs and checks actual byte extents/overlap against raw epoch2's640-byte birth
receipt. Original layout yields unknown bounds; canonical layout yields the
expected full/row/scalar/second-row intervals. Unknown layout stays unknown;
wrong profile/revision and unqualified source spelling reject.

Wall1.08s, RSS76292KiB; gate analysis0.343s. No new allocation, content/version,
provenance/materialization, ready qualification, torch import, target or compile.
No full raw/shard SHA replay, whole-bundle validation or complete importer run.
Old artifacts are read-only;4 normalized records are stored in this report only.

See docs/TENSOR_LAYOUT_ADMISSION.md. `producer.json`, script/time/stdout/stderr,
`report.json`, exact changed product bytes and patch are retained for review.
