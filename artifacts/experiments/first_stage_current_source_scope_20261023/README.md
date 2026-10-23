# Current369749 source demand: small retained evidence audit

Observed, exit0. This is a design-input audit, not source/runtime binding.
`analyze.py` uses Python stdlib only and reads small codes/meta/archive/coordinate
and historical code/source reports. It reads zero current event/OS/source bytes,
does not import SCAR/IR, prepare/compile source, execute a target or use GPU.

Real inputs are SHA-recorded in `producer.json`. Current capture codes were
selected by original archive logical→actual mapping, gzip/raw SHA and byte
receipts; code/meta were checked against saved same-Run coordinate membership.
The old capture uses plain raw files. Existing artifacts are not modified.

Both captures have855 descriptors;854 complete dictionaries match, one is new
and one old descriptor is absent. All same-key descriptors are fully equal.
667 current descriptors have historical source definitions (425project +242
external),128 have historical VERIFIED source without a definition,21 historical
unresolved,38 captured-only without an old entered binding, one unmatched.
These code categories sum855 and are not current entered-group weights.

Old14-call importing code is the one absent code. The new importing descriptor
has a different full code identity; filename/qualname/nearby line never select a
replacement. Current per-code group/counts and current source guards were not
read or inferred. They remain null. Current collector metadata declares100438
invocations/200876events,855codes and zero drop/error; a future complete strict
current scan must verify its own groups and weights.

Detailed boundaries and minimal five-file API proposal:
`docs/CURRENT_CAPTURE_SOURCE_CONNECTION.md`. No shared source or Git was changed.
