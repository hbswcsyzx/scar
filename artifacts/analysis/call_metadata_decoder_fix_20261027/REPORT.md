# Byte-only cold CALL decoder

Local CPython3.14 `dis.py:652` constructs `ArgResolver`; lines 771–785 resolve
argument representations, and `_get_const_info:698–707` invokes `repr(argval)`.
The cold cache now uses only pinned CPython3.14.7 `_unpack_opargs(co_code)`:
opcode/oparg, EXTENDED_ARG and skipped CACHE units, without argval or repr.
The original structural-key/unsupported-constant and code-unit guards remain.

One metadata micro passed. The old formatter invoked the probe's repr once;
the new observer path invoked it zero times and retained the unsupported-
constant rejection. Eight same-site requests unpacked bytes once. CALL257 and
inline CACHE boundaries matched. No target/capture was run.

The earlier `20d3228f` micro records its then-current `get_instructions` scan
counter; this fix's receipt supersedes that implementation detail without
changing its historical output. Runtime is explicitly CPython3.14.7; no general
cross-version private-dis ABI compatibility or LeWM speedup is claimed.
