# Native scalar union V2 — actual offline gate exit0

The explicit capability `SCAR_NATIVE_SCALAR_OBSERVED_ROOT_V2` preserves V1 and
adds only original NumberType/NumberType formals paired with actual ETO Int or
Bool and exact compatible payloads. The normalized PythonLiteral/builtin_type
does not establish the original Python class or earlier enum/symbolic origin.
Enum real formals, Device/Enum tags and incompatible None/String remain gaps;
Double/Sym/container/Tensor meanings are unchanged. No static program signature,
IR schema, upstream producer, state or readiness qualification is added.

Call the existing `bind_native_capture_model_batches` with
`scalar_input_profile=SCALAR_INPUT_CAPABILITY_V2`, exported by
`scar.ir.execution.native_port_protocol`. The default is still None. The pure
decoder's new keyword `profile` defaults to the original V1 contract. Its V2
path preserves both actual formal kinds instead of replacing NumberType with a
primitive formal. Owned `scalar_values` performs one exact scope/projection
check followed by indexed ordered queries; its authority/checks are unchanged.

Preparation includes only the four-source implementation, a pure syntax/API
check (16 decoder calls; no Torch import), the reviewed pinned-source contract,
and a fresh root-run entry. At preparation runtime kind distribution was
NOT_MEASURED. The actual gate measured it from its already checked immutable
owned replay data, without reading a saved qualification report or adding a raw
pass. Root session68758 confirmed exit0/21.848741629s; REPORT.md gives the actual
260 observed roots +4 frontiers and remaining scope limits.

Root's single actual command, after reviewing attempt01/freeze.json:

```sh
bash /home/zyf/AAA/scar-worktrees/native-scalar-model/artifacts/experiments/native_scalar_union_20261025/attempt01/run.sh
```

The gate uses the same saved CPU capture/G1 products and exact original static
ProgramSnapshot. It checks preservation of the four V1 observation footprints
and Tensor qualification counts, all original 261 dispatch/2332 metadata-row/
3095 metadata-path denominators and RAISED frontier, and performs one batch
typed query per verified shard. The sole negative exchanges source and Version
between two genuine equal-content NumberType/Int observations, constructing
fresh evidence from the same live owner; missing a pair is BLOCKED, never
synthetically filled. The equal contents are not merged and no different
underlying values/upstreams are asserted.

Limits remain 68,000,000 accounted stored+decoded payload bytes, 1,000,000
separate control bytes, 120s whole / 150s outer, RSS2GiB, index128,000,000B and
published outputs64,000,000B. The unchanged complete-pass bound is67,598,442B
and control bound864,842B; these are planned accounting bounds, not measured
new I/O. No extra retained input pass is added. Each source+runner SHA pass
reads6,639,632B separately. Production, runner and dependencies remain frozen
at their actual gate bytes. Historical scalar V1 and previous
failed native gates remain unchanged; old scope dirt is excluded.
