# Full direct source-call publication after ABI repair

## Run and receipts

The public `build-source-port-shards --all-candidates` command ran once against the original retained PID 272038 capture, with the original source report SHA256 `88e0ad71244ba59a455eb8bcd3a369fbe579e7c2e95bb3498d123bd4a965aa6f` and original bindings SHA256 `096c5a53213bae9f480ba813c240a277220ce6ac636390c0edff3bde9a91f449`. It did not create a capture or replay the full 201 source-entry reader. The original 2,672-call publication remains at its original path and is unchanged.

The run exited 0 in 145.14s GNU wall time (user 143.39s, system 1.39s, peak RSS 1,029,036 KiB). The strict raw reader took 125.32s and publication took 16.91s after raw reading.

- New manifest: [manifest.json](publication/manifest.json), SHA256 `32b84dae11ae3d1e5a0b7b7c9dc4461def8dc59ae8c8e8b2ad31c80cc1667afe`, 749,531 bytes.
- Model: 2,683 direct bindings in 84 gzip typed shards; 2,572,965 stored shard bytes and 63,875,141 decoded bytes.
- Full command output and resource counters: [stdout.txt](stdout.txt), [time-stderr.txt](time-stderr.txt).
- Machine result and receipts: [ACTUAL_RESULT.json](ACTUAL_RESULT.json).

One initial invocation exited during source-report receipt validation because a manually entered SHA was mistyped; it opened no trace. The single full scan used the exact SHA from the retained report and completed normally. Its terminal is retained in [attempt01_stderr_time.txt](attempt01_stderr_time.txt).

## Candidate scope and result

The publication examined all 2,683 of 2,683 direct body-linked candidate pairs, with zero remaining. It selected 2,683 typed bindings across 84 disjoint windows/shards. There are no remaining candidate issues: the former 11 ABI candidates are included. The original 2,672 bindings were preserved exactly; all 11 locally repaired attempts are present in the new publication.

Normal receipt-bound shard readers decoded all 84 old and all 84 new shards. The comparison found 2,672 old bindings, 0 missing and 0 changed. All 11 prior ABI cases were found in the new publication. Readback took 16.09s for the new shards and 16.70s for the old shards. No body replay was performed in this readback. Details: [verification.json](verification.json), with a reproduction reader [verify_full_publication.py](verify_full_publication.py).

## Coverage and costs

The capture has 100,550 calls, 100,438 frame entries, 4,069 handshakes, 312,812 operand events, and 945 operand gaps. The candidate funnel reports 96,481 calls without a unique entry handshake and another 1,386 without a retained body link. These are outside the direct-candidate denominator; this publication is not full attempt or whole-program coverage.

The source/body cache read 24 bodies (93,798,357 decoded bytes; 10,007,152 stored bytes), 23 code witnesses (38,767,006 decoded bytes), and 6 source files (82,137 bytes). The cache held 24 static call templates.

The published bindings remain conditional source-call interfaces. The receipts establish the candidate connections and preserve original IDs; they do not prove runtime callable identity, receiver identity, default values, selected return, content or effect equivalence, or permission to transform.
