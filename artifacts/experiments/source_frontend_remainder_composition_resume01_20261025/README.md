# Composer-only consumer of the twelve existing ADD artifacts

Original session20197 exited1 at396.750s after publisher completed. The
validator rebuilt appended interfaces/structured refs in serialized changed-body
order rather than the exact original plan order. Original inputs, publication,
producer bytes, failure and exit remain unchanged; this is a new consumer gate.
Root fixed only the consumer validator in commit3c8a81aa, source SHA
bfd6fdd3879d4b6311e987718d72c8e88e091e8ee482d41a1ef5882c274b464a.

The entry loads exact846 parent and the original already-published inventory.
No publisher, external plan_source call, lowerer or target is invoked. Ordinary
composer receives source_texts from the readonly20-key archive. A delegating
observer records actual ordinary-reader returns, checking their order against
publication.changed_bodies. A unique(fi,bi) map then checks every original plan
expectation's artifact ref and namespace. Graph-internal ordered Uses are not
sorted or weakened. Original plan order remains authoritative for active
component append validation; the serialized change inventory has its own order.

One public CompositionIndex read of the new output preserves its normal lineage
and accounting guards; no extra external typed-body pass is added. This public
constructor may itself read canonical accounting fields. No claim is made that
it avoids all graph I/O. Final checks require12 original refs, exact old compiler
origin,151 files/2217 definitions and858 bodies. Until actual consumer success,
source846/runtime843 remains the current qualified state;179 calls is potential.

Budget stays outer1800s ceiling,128MB record,256MB composition output. No global
input interceptor or complete combined I/O measurement is added; aggregate
stored+decoded accounting remainsOPEN. Freeze records356 current source files,
runtime and fixed inputs bySHA with zero payload copies/graph predecode. Original
publisher freeze/producer receipts and new consumer freeze are reported separately.
Failed/partial consumer output is preserved without automatic retry. Root owns
the actual run in the standard lewm environment.
