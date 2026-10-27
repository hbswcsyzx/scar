# Final read-only review and bounded acceptance

2026-10-18. Three review streams: cleanup_forward_review (exact frame/call and
all-route coverage), value_resource_review (state/N/R/freshness/guards), and
reuse_capture (independent missing-route false-positive reproduction and
coverage propagation). All approved the final bounded affected run; no stream
claims all16 P4 groups or M0-M2 complete.

The first unified run was 809P/2F: old4096 budget/determinism. An independent
read-only re-review approved moving the already established STATIC_CYCLE /
not-rooted rejection ahead of its useless path scan. Original routes and gaps
remain in the denominator. Narrow repair was26P. Limits and old assertions
were unchanged. Root froze source for the final affected run.

Final final-focused-repair:811P,0failures/errors/skips; previous788 retained,
new23. pytest32.19s; runner32.97729947883636s. All702 source digests stable:
fd97098b4e65b5923b7ac07f328eaee3603e7258a12155b3a2a9504e3822db1c.
Raw failure logs are retained. No complete component/full, new LeWM evidence,
runtime identity/native applicability or transformation authorization.

## Final changed source digests

- `scar/ir/program/call_composition.py`: `f03ef49aa1d0925b7dd22d43541ce04722c52e2acaf066e42c9e47db06a1b6bf`
- `scar/ir/program/input_origins.py`: `6346b4e88e034b3ca8c44529ba6264152ddbd11bb7d14bef9ed00663a3e98a3a`
- `scar/ir/program/protocol_connection_flow.py`: `0e7d31f1096c732e1af1f0248e839438686b7a71b6123448857da2f5708de1b0`
- `scar/ir/program/protocol_async.py`: `bfda3c3b923dcbc64440000d3169042cd53112384a1e13cf94552a079a57734f`
- `scar/ir/program/request_inputs.py`: `3854ab1af53a8b050cba03285f90ef2a1a99f5de299e1418646c310b3f1507a4`
- `tests/fixtures/program_call_composition_graphs.py`: `176bb489a668fb662c12fdb0c42a3855499d81f46036d92cdfd1e4b233cdc19b`
- `tests/fixtures/program_call_composition_state_graphs.py`: `8f8ac5859c6cd90cb752c586e97aa0abf7f2c4607916c21bd31799cf8a759750`
- `tests/unit/test_program_call_composition.py`: `1c2b800bf874aa9a81d2932be92155520f346a6d626bf26090168c46d90f21e1`
- `tests/unit/test_program_call_composition_state.py`: `1205d11e54a1ed93f0b00626961832f0022916b88ad9646465ddcc962af0d6c3`
- `tests/unit/test_program_call_composition_coverage.py`: `8623e3f58bba05f6616cdec939b6de4084d36dd4e519989c440067fd33003f82`
