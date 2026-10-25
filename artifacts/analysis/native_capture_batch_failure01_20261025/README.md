# First full native-batch gate: sequence 3182 diagnosis

2026-10-25. Read-only diagnosis of terminal session 88951. No producer or first
gate artifact was changed, no owner was recreated, and no retry was started.
`extract.py` uses saved failure/inventory metadata and 29 selected SQLite rows.
The database is opened `mode=ro&immutable=1`; its size/mtime/inode are unchanged.
Its ephemeral MAC key is unavailable, so these are diagnostic records, not
restored runtime authority. No original raw trace or archive chunk was reopened.

The precise failed sequence is **3182**, operator `aten.mul_.Tensor`. The failure
file records 3181 classified actual groups; the next actual observed inventory
row is 3182. The last progress checkpoint at 3071 is not the failure sequence.
BEGIN/OUTPUT/END are original dispatch lines **9544 / 9545 / 9546**, with normal
RETURNED completion and no slot gaps. The failed equality is the V1 requirement
that every native Tensor input have a held Python Tensor reference.

| Actual port | Native ETO observation | Python-held observation |
|---|---|---|
| input 0, self | Tensor(float), shape [3,224,224], stride [1,672,3], tuple [24607,24608,0,150528,4,"cpu"] | BEGIN path [0,0], maps to formal [0], weak:369749:354301 |
| input 1, other | Tensor(double), shape [], stride [], tuple [24617,24618,0,1,8,"cpu"] | No held path [0,1] or keyword equivalent |
| output 0 | Same native self tuple | OUTPUT path [], maps to formal [0], same WeakRef |

The extra input is a real recorded zero-dimensional, one-element native Tensor,
not an empty container. Its raw schema is
`aten::mul_.Tensor(Tensor(a!) self, Tensor other) -> Tensor(a!)`: the second
formal is not optional and has no default. None/default/empty-container handling
is therefore not the observed cause of this particular set difference.

Native source locators, using artifact SHA
`625558680ced281fc2b4789d9d742bc97dd4fed57106701e98adea3ebe0428b6`:

| Node | Original nodes-array ordinal | Role and source pointer |
|---|---:|---|
| 24611 | 20481 | outer native mul_; `#/nodes/20481` |
| 24614 | 20480 | PythonDispatchMode, parent 24611; `#/nodes/20480` |
| 24615 | 20479 | sequence 3182 span, parent 24614; `#/nodes/20479` |
| 24616 | 20477 | unique direct native child, parent 24615; `#/nodes/20477` |
| 24625 | 20478 | output marker, parent 24615; `#/nodes/20478` |

The native-only input pointer is `#/nodes/20477/inputs/values/1`. The outer native
operation already has a different zero-dimensional Double Tensor,
`[24612,24613,0,1,8,"cpu"]`; PythonDispatchMode also records those two outer
inputs. Inside the held-marker interval, the extra Tensor has new provider IDs.
Nested native nodes show a Double-to-Float conversion and copy. None of this
records the scalar element value or establishes equality of the two Tensor IDs.

The selected existing self witnesses agree: span/output marker RF IDs are
20475/20481, native thread token is 1, physical marker lines are 9688/9693 and
point back to dispatch 9544/9545. Each marker declares one expected argument and
contains one original argument at ordinal 0. Native child RF 20476 belongs to
the exact span. The extracted original archive instance, object, region and
allocation rows retain their original manifest/chunk/row locators. No known
self identity, nonce, parent, RF or thread contradiction was found here.

## Why the inventories differ

The dispatch collector traverses Tensor/Parameter leaves, holds them through the
call, and supplies that held list to its markers. Supported primitive leaves
are skipped without a slot gap. Its emitted observation retains tensor paths
and WeakRefs plus call context; it does **not** preserve non-Tensor argument
kind/value, full args/kwargs structure, or the wrapped-number bit. Thus an empty
slot-gap list is not a promise that the native Tensor inventory equals the
Python-held Tensor inventory. This is a reference-observability/profile gap,
not evidence by itself that a Tensor reference was dropped or corrupted.

The pinned provider offers a consistent explanation. Native dispatch arguments
are converted to Python objects; wrapped-number Tensors can become Python
numbers, and numeric inputs can be boxed as new native Tensors on a permitted
operator entry. Default arguments may also disappear from the Python view.
See the independently checked [boxing contract](../../../analysis/native_boxing_contract_20261025/CONTRACT.md)
and [complete official-source receipts](../../../analysis/native_boxing_contract_20261025/source-receipts.json).
Relevant primary sources include
[Python argument conversion](https://github.com/pytorch/pytorch/blob/cf30153c4c131c8164ee7798e5022d810682e2cb/torch/csrc/autograd/python_variable.cpp#L190),
[wrapped-number conversion](https://github.com/pytorch/pytorch/blob/cf30153c4c131c8164ee7798e5022d810682e2cb/torch/csrc/jit/python/pybind_utils.cpp#L586),
and the [operator-overload guard](https://github.com/pytorch/pytorch/blob/cf30153c4c131c8164ee7798e5022d810682e2cb/torch/csrc/jit/python/init.cpp#L1733).

For this occurrence, wrapped-number unboxing/reboxing is **Inferred**, strongly
consistent with the observed boundary and changed provider IDs. The actual
wrapped bit, primitive kind/value and guard state were not captured. Do not
infer them from dtype/rank/numel, a function name, or nearby allocation sizes.
Do not manufacture a WeakRef/ObjectID, assign the outer Tensor's identity to the
inner Tensor, or create a scalar/content identity from this missing observation.

## Terminal scope and cost

The first real gate is **FAILED / actual exit 1**. GNU-time whole wall is
196.92 seconds, gate in-process wall 195.470389 seconds, native-batch wall
184.089763 seconds, maximum RSS 910,204 KiB. It completed all three original
native SHA/byte/full-parse passes: 546,619,922 raw bytes. It also verified all
95 chunks of the four original tables, totaling 1,490,910,199 decoded /
91,044,471 stored bytes.

The recorded path-API decoded/stored counts are 1,261,870,214 / 118,910,986 for
coordinates and 547,054,104 / 111,790,669 for the batch phase. Adding separately
verified BytesIO chunk decoding gives 3,299,834,517 decoded representation bytes.
This excludes actual SQLite disk I/O, libraries and output writes. The retained
SQLite file is 3,973,341,184 bytes, only 26,658,816 below its 4,000,000,000-byte cap.

All 39,796 actual BEGIN/group inventory entries matched the metadata count at
the cardinality checkpoint. Per-group semantic discovery stopped at 3182 after
3181 classifications; the last reported signature count was 29 at checkpoint
3071. No shared ProgramGraph or execution shard was published. Full source
acquisition/counting does not constitute full native-port or program modeling.
The first freeze, code, database, progress, failures and time remain untouched.

`V2_CONTRACT.md` records the proposed general capability split for root review.
It is a contract proposal, not a change to V1 or authority for a second gate.
