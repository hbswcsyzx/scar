# Same-run program ports and source archive

Implemented `trace --capture-profile program-ports` (`SCAR_PROGRAM_PORTS_V1`).
It records project modules/functions and actual Python descendants, bounded
entry parameters/return references and CALL metadata, with no INSTRUCTION
monitoring. Native interiors stay interfaces. Original CodeIDs and occurrences
remain separate. Each filesystem source is read once into the original capture
archive, retaining raw bytes, encoding, normalized UTF8 hash and provenance.
Reading those bytes does not prove loader input or compiler equivalence.

One CPU capture actually exited 0 (GNU 33.73s). Ordinary operands readback exited
0 in 0.2364s: 177 entries/177 exits, 400 CALL attempts, zero instructions/drops,
no reader issues, two explicit `PROJECT_FUNCTION_CALL_DID_NOT_ENTER` scoped gaps.
Project `main` → external `transform` → stdlib `dedent`, and normal return
references, are present. Torch was preloaded by the recorded test launcher;
this is not coverage of Torch startup or a LeWM episode.

The genuine coordinate binder ran in the CLI and verified the original source
members. Ten files: raw 137,000B, normalized 137,000B, encoded JSONL 189,422B,
gzip 67,369B. Raw budget and JSON/base64 transport bytes are distinct; a 2MB raw
file permits a source row of `4*ceil(raw_limit/3)+32768` bytes. Source rows are
checked against their original raw/normalized receipts. No Tensor contents were
stored. `compiler_match=NOT_CHECKED`, `loader_bytes_observed=False` remain.

Five non-filesystem paths retain original descriptors: frozen `runpy` (launcher
ancestry), `<string>` (the recorded `-c` launcher), frozen `importlib._bootstrap`,
`importlib._bootstrap_external` (import/runtime boundaries), and frozen
`posixpath` (`join`, `_get_sep`). None is silently paired with a similarly named
disk file. This does not mean those runtime bodies have source proof.

The same capture's stream reader passed separately: seven calls, six observed
backings (four regular-file/two FIFO), one closed-stream `FILENO_FAILED`, six
C_RETURN/one C_RAISE. IO dependency commit is `14cbaf51324ce95c8ad15afa8439d2c4bf9c034b`;
its receipt is in `stream-backing-observations/artifacts/analysis/stream_backing_observations_20261027/READBACK.json`.
These are receiver-point FD/stat observations, not an FD-table model, persistent
resource/object identity, contents, completed save or durability.

The original capture also exposed SCAR weakref-cleanup activations entering the
recursive scope. After that run, the producer gained a same-thread scope barrier
at the actual `scar/trace` package/bootstrap: it suppresses the entire collector
subtree, including stdlib/project callbacks. This fix and the explicit new-rule
consumer guard in `source_call_bindings` are implemented/syntax-checked, not
recaptured. The original 177-entry artifact and its producer receipts remain.
Old profiles/wires and instruction/load route guards are unchanged.

Next: consume this original archive in ordinary source planning. The new module
provides `validate_source_metadata`/`validate_source_row`; the canonical source
fact is `captured-sources.PID.jsonl#/lines/N` plus the closed metadata receipt.
`SourceSnapshot(path, sha256:normalized_sha256, utf-8, 3.14)` can be derived only
after normal member validation. There is not yet an owned archived-source reader
for the automatic model pipeline: `_Sources.context` and `admit_dependency_sources`
still read live files; `CodeWitnessStore.admit_archived_source` currently accepts
only normal `SourceAttachments`. That is the next integration point, not a reason
to recapture. Compiler matching, body publication, actual-formal/state/content
and complete-program coverage remain open.
