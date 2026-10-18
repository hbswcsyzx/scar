# Protocol terminal and no-entry path review

## Scope and source snapshot

This is a bounded source review of host-result routing and no-entry terminal paths against `docs/M1_PROTOCOL_CONTRACT.md`. It does not close the full P2 protocol-family matrix, prove native Python behavior, or establish runtime/source equivalence.

Reviewed SHA-256:

| File | SHA-256 |
|---|---|
| `docs/M1_PROTOCOL_CONTRACT.md` | `2a5d982907ed8d9d9e93586f8cf9979002cbac6e27c73de8aac8ce4d0c45c4ac` |
| `scar/ir/program/protocol_validation.py` | `0dd22732e03bf6824c8c3551060814013e96ce693fedaad95cdbba1b7a3825c7` |
| `scar/ir/program/protocol_flow.py` | `3410733f931ba9f15340ea4af30f7f5b92860258a00d94ad78d60250b455c4bd` |
| `scar/ir/program/protocol_query.py` | `d0a7976bc920c95c2286368cbc5d41341cefae6dfd70619bd85abed7b9488eab` |
| `tests/fixtures/program_protocol_graphs.py` | `7e15b2955336a0f82e406189ae7ec55c6dc12dbfbb25f7c20660c2f8a50110e9` |
| `tests/unit/test_program_protocol_path_safety.py` | `3d728045ce36e5459e03507d7d4adc284647bcb6eee5ccb0a1fee2f1efa087f7` |

## Findings

### Adapter output must come from that adapter

The current validator checks an `OutcomeAdapter`'s selected output against the exact host terminal. `adapter_host_output` resolves the adapter's own ordinary `OperationResult` or indexed `InvokeLiteralResult`, then `host_output_copy` requires either a direct copy or an explicit same-region packet whose exception component comes from that result. Equal value types, a reachable `RAISE`, or a packet from an unrelated result do not satisfy the connection. Ordinary adapters are constrained to result slot 0; invoke adapters must match their exact successor slot. See [`protocol_validation.py`](/tmp/scar-structured-model-280qf4mi/scar/ir/program/protocol_validation.py:47), especially `host_output_copy` and `adapter_host_output`, and the adapter checks around lines 388–443.

Before these guards were added, a small in-memory mutation of the generator fixture retargeted an adapter to five unrelated host terminals and validation returned no issues for each. That development observation has no preserved script or contemporaneous source hash, so it is historical, unbound evidence rather than a source-bound regression result. On the current snapshot, the five corresponding wrong-terminal cases are rejected with `protocol_copy`; valid adapter-owned NORMAL and RAISE output paths pass. A same-region RETURN terminal on a Python exception-adapter route is rejected. The helper's same-region packet filter also prevents an unrelated cross-region `PacketDefinition` with unknown forwarding from downgrading a known mismatch.

### No-entry completion remains conditional on its selected route and state

The no-entry check follows the original CFG from the selected edge to the declared host terminal. It marks the route partial when there is a reachable nonterminal exit or a cycle, and it does not seed lifecycle facts for a partial route. The selected transition also needs the declared lifecycle coverage; for INVOKE, at least one lifecycle location must have a real `CompletionResult` post on the selected edge, while an ordinary transition needs a real WRITE/RW post in a lifecycle location. The existing core state SSA checks still govern freshness along the route. See [`protocol_validation.py`](/tmp/scar-structured-model-280qf4mi/scar/ir/program/protocol_validation.py:158) for route traversal and cycle handling, lines 244–268 for lifecycle/post checks, and lines 577–595 for conditional seeding.

One earlier probe that removed a single site used a fixture whose lifecycle contained only `resume.world`; removing an unrelated context site therefore did not demonstrate a missing lifecycle site. That attribution is withdrawn. The meaningful negative is omitting a required lifecycle location. Likewise, a lifecycle domain that is read/forwarded unchanged may coexist with a real update in another lifecycle location; requiring every lifecycle domain to be newly written was not part of the accepted contract and is not a defect. The current safety test covers a reachable terminal plus a sibling self-loop: the original graph remains core-valid, the no-entry route is reported partial, and no completion seed is produced.

The public obligation view keeps fixed clause obligations and exposes missing edge bindings and partial rows rather than treating an absent row set as success. See [`protocol_query.py`](/tmp/scar-structured-model-280qf4mi/scar/ir/program/protocol_query.py:72).

## Verification recorded

Focused command, run once against the source snapshot above:

```sh
source /home/zyf/miniconda3/etc/profile.d/conda.sh && conda activate lewm && PYTHONDONTWRITEBYTECODE=1 PYTHONPATH=. pytest -q tests/unit/test_program_protocol_path_safety.py --junitxml=artifacts/experiments/b1_call_operands/model_protocol_implementation/port-safety/attempt001/junit.xml
```

Result: **9 passed**, exit 0, 0.55 seconds. Raw output and JUnit are preserved in `port-safety/attempt001/` (`output.log` SHA-256 `5f0bd7749642c76e9222f6ff14f70210be37da5be78a44ff5f4dcb9b5726c0f0`; JUnit SHA-256 `dea5d8a5e954674acc80e7e152c75adb07668821db8cdd2f3dd44d43b0218671`). The nine cases comprise five wrong-terminal connections, two adapter-owned output routes, a wrong same-region terminal kind, and a reachable-cycle no-entry route.

The root's later unified focused run reported 153 passed and one failed. The single failure was a test mutation that removed a context site even though that fixture's declared lifecycle contained only `resume.world`; it did not demonstrate a product defect. This report does not count that mutation as a validator failure or as evidence that all lifecycle locations must be written.

## Limits

These checks establish structural connections in the supplied IR. They do not prove that a declared protocol profile matches a particular Python implementation, that a callback's native behavior matches its row, or that source/runtime identities were captured. Broader family coverage and source applicability remain open. No full suite, native workload, GPU workload, or runtime probe was run for this review.
