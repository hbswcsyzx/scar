# Retention plan — no terminal qualification

Keep original entry/config/audit/prepare/report_archive and shell bytes, both
PREPARED_NOT_RUN and actual frozen producer receipts, input manifest, order-change
receipt, preparation stdout/stderr, actual root stdout/stderr/time, progress and
summary or failure. Keep small snapshot/ancestor/checkpoint-negative/proof/
namespace receipts and actual participating-source hashes. No source/std-library
payload copies were made; Root may archive exact entry/source changes from Git.

Original source858/846/843 compositions, publication parents,15 SP5 artifacts,
CodeWitness provider files, capture raw, source-context and native/OS data remain
at their original local URIs, with exact receipts in inputs.json. Do not duplicate
those payloads into this consumer worktree. A clone without the original local
artifacts will not be a self-contained replay package.

After the actual terminal, enumerate every generated output and its stored size.
Choose the finite small report roots, terminal evidence and <=1MB artifacts for
Root's explicit stage list; any larger body/source/invocation stream remains
local with an accurate receipt. SBA uses original16MB-decoded/1000-row report
chunks. Whether to retain their entire compressed set depends on actual sizes;
this plan preauthorizes neither a size exception nor a PASS. Do not re-decode
SP5/raw or rerun consumers to produce the retention list.
