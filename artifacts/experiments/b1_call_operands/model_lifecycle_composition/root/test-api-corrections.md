# Root body-composition test corrections

The first focused run recorded 4 PASS / 3 FAIL: two assertions used the non-existent `cleanup_replaces` table instead of `cleanup_replacements`; another assumed ProgramIndex exposed `blocks`. These were test API errors after ProgramIndex had already validated each graph, not model defects.

The second run recorded 5 PASS / 2 FAIL: a further source-chain assertion still used the non-existent `BodyOutcomeSite.source` member. The actual chain is `release.sources[0].source.operation == commit.outcome.source`. The final assertion was corrected before the component gate, with no third focused rerun. Independent read-only review confirmed the actual source/current-state and isolated owner/stale-state negative cases.

Both raw stdout files and per-run file hashes are retained under ../body. No product validator was relaxed to make these tests pass. Component and frozen-full evidence separately determine final acceptance.
