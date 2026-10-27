# Reuse normal native views in resource batches

Adds `NativeDeclarationResourceSession.query_view(view: NativeDeclarationView,
*, source_instances=None) -> dict`. `query(fragment, ...)` remains the normal
reader wrapper and charges its reader I/O once before delegating. The live view
must remain unchanged under its caller's ownership. No serialized validation or
PASS field is inspected. Original Run/process/namespace, host, edge, work and
resource checks remain in the common path.

The result retains `connections: tuple[NativeDeclarationWorkConnection,...]`.
`measurements` is **session-cumulative artifact I/O**, including construction
and all previous joins; `query_measurements` is **this resource join's delta**,
excluding session construction and the input view's normal reader. When the
caller owns a normal reader session, account its I/O separately once. SQLite
page I/O remains outside the artifact meter, as in the original report.

The private original-record cache now keeps at most three immutable tuples of
byte lines per table, under LRU. Each exact chunk still passes full original
stored/decoded SHA, byte, EOF and line-count checks on load. `row()` directly
indexes these lines rather than splitting a 16MB payload for every row. No
mutable parsed IR or validity result is cached.

One original same-ca66 case, no new work/raw/index production: actual exit 0.
The ordinary native reader took 12.484s / 111,004,742B stored+decoded. Reused-view
resource join took 0.525s / 86,124,395B delta; the resource session including its
construction took 1.542s / 221,855,162B. Overall worker 14.109s. Both original
paths to the same one WorkTicket and every source/namespace/ref field equal the
previous normal Query04 connections exactly. The cache ended with 2 instance,
3 edge and 1 resource chunks. These are one-case costs, not a full-batch timing
or speedup claim. Completion/content/state/ready remain OPEN.

`RESULT.json` binds exact source SHA, original receipts and measurements. Only
the resource module and this small example/receipts changed; old receipts and
factory were not altered.
