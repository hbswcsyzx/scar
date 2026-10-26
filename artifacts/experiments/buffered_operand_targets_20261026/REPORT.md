# Bounded metadata writes

Implemented 64 KiB byte buffers for operand and v2 Python target sidecars. Records,
IDs, bounds and normal wire formats are unchanged. Buffers contain bytes only;
parent PID guards prevent child flushes. An operand flush failure marks its
metadata invalid; a target write/flush failure prevents its final manifest.

Actual generic run03 returned 40000. The normal automatic source inventory and
operand linker completed: 1412 operand records / 8 writes, 603 target records /
5 writes (403 TARGET, 200 ENTRY, 0 GAP). Retained byte count and SHA checks passed.
The first two capture runs completed, but their verification runners used an
incorrect budget keyword and omitted the required automatic inventory; their
artifacts and failure notes remain separate. They are not successful linker runs.

The final negative02 checks reject child writes, mark operand flush failure and
prevent target manifest publication after flush failure. This reduces observer
system calls, not a measured workload speedup. No LeWM episode was run here.
