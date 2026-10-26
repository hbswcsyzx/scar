# Shared context / independent body result

The new opt-in store splits two retained real SP5s (85/217 operations) from the same source snapshot and namespace into one context plus two body archives. Original inputs are pinned in `attempt03/result.json`; no source lowering, target run, or whole-publication check was performed. The 239-op context-heavy sample is the motivation, not an additional claimed readback.

| Bytes | Old two complete SP5 archives | One context + two body fragments |
|---|---:|---:|
| Stored | 3,303,841 | 1,764,916 |
| Decoded | 30,744,053 | 16,639,005 |

The shared context is 1,540,382 stored /14,109,704 decoded bytes. The85 body is62,325 /662,175; the217 body162,209 /1,867,126. This pair removes about46.58% stored /45.88% decoded duplication; it is not a general speed or compression claim.

Actual attempt03 exit0:76.288943582s, SELF peak306,116KiB (entire process including the necessary positive/negative/legacy checks). Writer3.5446s read4,844,223 stored bytes including1,540,382 existing-output guard bytes, and30,744,053 decoded bytes. The shared normal-reader session read/validated exactly1 context for2 bodies:1,764,916 stored /16,639,005 decoded,22.0309s; it additionally made4 private canonical-hash guards. An independent new session read only the217 body and its referenced context:1,702,591 stored /15,976,830 decoded,17.4669s. These are phase-instrumented counts, not a claim that negatives, the legacy reader and output-measurement reads cost zero or are included in those three phase counters.

The ordinary old85 SP5 reader returned the same graph/metadata and identical wire tree. Wrong context SHA, wrong namespace, reading after close, and private context mutation were rejected. Private context objects never appear on returned LoweredSourceBody. Core IDs, original source namespaces/locators and ports remain unchanged; an index is not needed to read either fragment.

Two original failed checks remain: attempt01 failed before body reading because the new typed check omitted the required record_errors path argument (1.293s); attempt02 had already passed shared/cold reading but its mutation-negative expected a later message than the existing structured validator produced (57.497s). The private hash guard was moved before body validation, the missing path was fixed, and exact duplicate-output read costs were added. Old sources and failed artifacts were preserved.

A final read-only postflight closes the original decoded-byte receipt in addition to the canonical-tree hash. It uses the already-written217 fragment, supports only the public canonical UTF8 /same+LF forms by exact length/SHA, and rejects an altered original decoded SHA. It does not re-create either body or read the old full SP5 payloads. Postflight actually exited0 in23.7101s, SELF peak203,052KiB; one context validation and one accepted217-op body, with changed-origin rejection. Its session read1,864,767 stored /17,843,956 decoded bytes including that negative. It read0 old full-SP5 payloads. Separate result/source hashes are in `postflight01/result.json`; attempt03 timing belongs to its recorded source version.

Qualification is the ordinary structural/core/structured/language path plus normal source-context semantics/CFG validation. It grants no new compiler/runtime/effect/content/ready proof. The complete model remains OPEN. This standalone adapter is not yet wired into source publication/catalog readers. Main was not modified and the pre-existing three trace buffering changes were not staged.

The final current-writer idempotence check also actually passed: 3.582053s /SELF162100KiB, 6609139 stored /30744053 decoded bytes read. It checked both old SP5 originals and existing outputs, returned the same locators, wrote0 bytes, and left every old output inode/size/mtime/ctime unchanged. This additional read is separate from the earlier writer timing and the read-only postflight.
