# Pinned Python dispatch / native Tensor boxing contract

2026-10-25. Provider revision: `cf30153c4c131c8164ee7798e5022d810682e2cb`.
This is primary-source research, not a new execution or proof that a particular
conversion occurred. Complete retrieved-file hashes, bytes, URLs and reviewed
line ranges are in `source-receipts.json`. No production changes, raw/SQLite/
archive-chunk reads, target execution, compilation or new gate occurred here.

The fixed provider permits a native Tensor port without a Python-held Tensor:

| Pinned source, file lines (1-based) | Conditional provider mechanism |
| --- | --- |
| [PyInterpreter.cpp:273–324](https://github.com/pytorch/pytorch/blob/cf30153c4c131c8164ee7798e5022d810682e2cb/torch/csrc/PyInterpreter.cpp#L273) | Python dispatch converts the boxed native arguments through `parseIValuesToPyArgsKwargs`. |
| [python_variable.cpp:190–283](https://github.com/pytorch/pytorch/blob/cf30153c4c131c8164ee7798e5022d810682e2cb/torch/csrc/autograd/python_variable.cpp#L190) | Schema-aware conversion generally delegates to `toPyObject`; trailing/default arguments can be omitted from the Python argument view. |
| [pybind_utils.cpp:586–632](https://github.com/pytorch/pytorch/blob/cf30153c4c131c8164ee7798e5022d810682e2cb/torch/csrc/jit/python/pybind_utils.cpp#L586) | If a Tensor is marked wrapped-number, conversion can return a Python numeric value, or its saved symbolic `_wrapped_number`. Other Tensor conversion returns a Tensor wrapper. |
| [python_arg_parser.cpp:83–118 and 1830–1888](https://github.com/pytorch/pytorch/blob/cf30153c4c131c8164ee7798e5022d810682e2cb/torch/csrc/utils/python_arg_parser.cpp#L1830) | Eligible Python Tensor parameters accept numbers; `tensor_slow` constructs a scalar Tensor and sets its wrapped-number flag. This is an alternative generated-binding route. |
| [init.cpp:151–155 and 1733–1758](https://github.com/pytorch/pytorch/blob/cf30153c4c131c8164ee7798e5022d810682e2cb/torch/csrc/jit/python/init.cpp#L1733) | The returned operator-overload callable installs the allow-numbers TLS guard, using the pinned provider's operator eligibility predicate. The packet callable does likewise at 1826–1837. |
| [pybind_utils.h:759–784 and 942–1011](https://github.com/pytorch/pytorch/blob/cf30153c4c131c8164ee7798e5022d810682e2cb/torch/csrc/jit/python/pybind_utils.h#L759) | Re-entry uses the actual formal `real_type()` to construct boxed arguments. |
| [pybind_utils.cpp:22–30 and 70–118](https://github.com/pytorch/pytorch/blob/cf30153c4c131c8164ee7798e5022d810682e2cb/torch/csrc/jit/python/pybind_utils.cpp#L70) | With the guard enabled, a numeric Python object for a Tensor formal can become a new scalar Tensor, marked wrapped-number. The guard restores the previous TLS state. |
| [_ops.py:798–805 and 1124–1142](https://github.com/pytorch/pytorch/blob/cf30153c4c131c8164ee7798e5022d810682e2cb/torch/_ops.py#L798) | OpOverload delegates to the callable obtained from `_get_operation_overload`. A separate direct boxed/redispatch entry need not install that guard itself. |

These are versioned, conditional contracts. They invalidate the universal rule
that every native Tensor leaf must be a Python Tensor leaf held by the observer.
They do **not** authorize silently matching an unheld native leaf to a Python
object. In particular, zero rank, one element, CPU device or Double dtype does
not prove the wrapped-number bit, the selected conversion branch, original
primitive kind/value, or content equality across native Tensor IDs.

The owner supplied a small read-only diagnostic for dispatch sequence 3182;
this agent did not reread its database. It reports one held self input/output,
but two native Tensor inputs: self and an additional zero-dimensional one-element
Double Tensor. It also reports distinct additional-Tensor IDs outside and inside
the PythonDispatchMode interval. Exact supplied fields are retained in
`owner-observation.json`, labelled as owner-reported observations. This pattern
is consistent with wrapped-number unboxing and reboxing. That explanation is
**Inferred**, not observed: neither the wrapped bit, the primitive value nor its
Python source was recorded in the supplied sidecar summary. The same qualification
applies to the actual guard state of this call; locating its provider entry point
does not turn source code into a per-call observation.

The ETO Tensor tuple records provider Tensor/storage tokens, geometry and device,
not the numeric element payload or wrapped-number flag. The observer stores
held Tensor/Parameter paths; its accepted primitive leaves are skipped without
being counted as slot gaps. Thus `slot_gaps=[]` cannot establish equality of the
Python-held Tensor set and the native Tensor set. It also cannot recover the
missing scalar or justify invoking the exact scalar decoder on a guessed value.

For a subsequent reviewed implementation, preserve the native Tensor slot,
ReferenceValue, ValueOccurrence, ordered Use and NativeBoundary ordinal. A
native-only Tensor can retain explicit **Unresolved identity**, anchored to its
actual ETO artifact/node/slot, while already matched held Tensor slots keep their
original qualified ObjectIdentity. No WeakRef/ObjectID, storage lifetime, alias,
scalar DataIdentity, content Version or equality follows for the unheld slot.
Unknown why the sets differ is a concrete frontier, rather than permission to
drop the native port, fabricate a Python object, or relabel every mismatch as
wrapped-number. Do not implement a package/operator-name exception from this
one occurrence; retain ordinary duplicate/contradictory-identity rejection.
