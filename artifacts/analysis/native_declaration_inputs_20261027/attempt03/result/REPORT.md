# Native declaration input metadata join: ETO ordinal 17

The normal declaration reader returned one original native operation. The bridge joins its original `EvidenceInstanceRef`, input `NativeInputRef.position=0`, `ValueOccurrence`, and original `UseOccurrence` to the retained metadata leaf at the exact ETO artifact SHA, `#/nodes/17`, and native path `[0]`.

The previous metadata index status remains `CANONICAL_NATIVE_BOUNDARY_UNAVAILABLE`. The new relation does not rewrite it. The other five input paths have no metadata leaf at their exact paths; their type or absence reason remains unresolved.

The matched static use is `program_use:torch-interface:c15636102ea1087dfb7d387755b18323fa28ea9259b123e61f1e87d7d2bfcc25:invoke:use:0`. The retained metadata leaf is `native-tensor-input-observation.v1#/lines/17/inputs/slots/0/metadata`; its observed provider-epoch reference is `tensor-physical-observation.v1#/lines/7`.

The one-time old metadata-row pass verified 310,410 rows and 420,444 leaves. It read 47,577,389 stored bytes and 1,149,320,637 decoded bytes in 61.880 seconds; the disposable SQLite lookup used 330,141,696 bytes. The normal declaration fragment read took 4.167 seconds, with 8,039,410 stored and 44,221,866 decoded bytes. The end-to-end query took 66.501 seconds.

This is one operation out of 230,818. The bridge reuses original IDs and references. It establishes no Tensor content identity, alias, normal completion, or resource readiness. It did not read or rescan the raw ETO.
