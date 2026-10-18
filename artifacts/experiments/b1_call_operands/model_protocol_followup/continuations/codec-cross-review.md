# Program20 codec: bounded independent source closure

**PASS_WITH_SCOPE for the reviewed capability/wire connection. Full P4 remains
OPEN.** This review read files and existing evidence only. It ran no tests,
legacy generator, archive checker, fingerprint script or external/native probe,
and changed no product/test/fixture owned by A.

## Exact reviewed source

| File | SHA-256 |
| --- | --- |
| `scar/ir/program/codec.py` | `3753c0ac02667e5bc6e816f23e6c624393a04e4e86278aab01861a0f89d09d47` |
| `scar/ir/program/protocol_connections.py` | `df7f63e6c8f7048b75c03c3942185d6603c295aed11953bae2679052aaef3759` |
| `tests/unit/test_program_method_lookup_codec.py` | `d2a874eceb138d1936801302d33b473947d52a2ede209990857a52e945242776` |
| `tests/fixtures/program_graph_v19_frozen.json` | `57fe9feb47f5b186cb1b5c708c1eff56e54a61b43c597a6951a82719cfd0a5f6` |
| `tests/fixtures/program_graph_v19_frozen.proof.json` | `2591eaff58893bdec58e28db4e13125aa156236a424744794c870101a1260cbc` |

The reviewed continuation source remains
`ef26888f07aa6934fe50009a5afc50606dced4f231e52eea8da5d942fa494635`.
`docs/M1_PROTOCOL_FOLLOWUP_PLAN.md` is
`44437087abfe3fa1a7b074ca973c06a0f863eb0c4fc9073ef26f8881de412f78`.

## Closed connections observed in source

1. `has_delegated_method_lookup_capability` checks exactly the four new rule
   values on original ProtocolCall rows. `has_protocol_connection_capability`
   calls that same predicate. Deleting the input/consumer/binding tables cannot
   remove the expensive validator/query stage or downgrade the rule's wire
   capability. Capability is not inferred from incidental state-address fields,
   labels or actual producer discovery.
2. Program20 and Program19 have the same canonical graph fields and record tags.
   The version boundary is nevertheless explicit: dumps selects 20 when that
   closed new rule capability is present; loads rejects a new-rule graph under
   every earlier supported envelope, and rejects a 20 envelope without the new
   capability. It does not rely on new record tags to detect an otherwise
   same-shape enum. Future and Boolean schema values are rejected separately.
3. Older no-new-rule graphs follow the existing selection order, fields and
   encoding path. No connection table/field is added to Program18 or earlier,
   no empty Program20 capability is synthesized, and Execution codec is not
   upgraded by this change. The original Program19 byte oracle round-trip is
   explicitly tested rather than regenerated with the current encoder.
4. The new graph with all three connection tables empty still carries the new
   rule, serializes as Program20 and obtains MISSING input/consumer obligations
   from the public query. The test does not treat table deletion as successful
   protocol completion. Whole source/site-inventory coverage remains unproved;
   deleting every original family claim is not advertised as detectable by a
   source parser that does not exist.
5. Own NORMAL bound method, RAISE packet, actual callable Use and current state
   survive the actual expanded fixture's round-trip. This establishes encoded
   declarations and canonical-port preservation, not Python descriptor identity,
   native exception category, dynamic occurrence correspondence or permission
   to transform the program.

No remaining concrete blocker was found in this bounded source path.

## Independent Program19 oracle provenance

The adjacent proof records full revision
`7dd8c54b8d8cfdb3454b9f3b671f3412d1a914f0`. The retained command exports its
immutable git archive into `codec/legacy-source-v19.tar`, SHA
`a57e394498a8b485260b170b7e29ccfb235bfa699989c55bf7c677adf2ef6bf9`.
The recorded generator uses both cwd and PYTHONPATH inside the extracted old
tree, activates conda lewm, disables bytecode and imports the old encoder.
`source-check.log` reports Python 3.14.7, schema 19 and the old-tree import paths.

Before the extraction was cleaned, the reviewer read its old codec SHA
`125d0d3e56a6f07abf00633e3c178dcc1ba3ef497a68025b950341ba59bc41fe`, old
connection helper SHA
`86ea3d6d5822d14a72680c569baa90c4a91569007c280a33ce25f45975e6fde9`,
and old continuation fixture SHA
`0137c37ebc5d4c101c36f77a1bdd624ce88d987b3b258b25943541f356b43733`.
They match the proof. The archive verification receipt records 157 file-content
matches. A subsequently removed only the verified extracted directory and
retained the tar/logs. This reviewer did not independently rerun that checker.

The successful old-source generator is `codec/attempt002/generate.py`, SHA
`7530265a61f773fbb502049c01ffb8799471c5905d384311b7e8a6e37e82e932`.
Its command/exit/stdout record 44,484 bytes and
`57fe9feb47f5b186cb1b5c708c1eff56e54a61b43c597a6951a82719cfd0a5f6`.
The present fixture's byte count and SHA match. The first failed generator
incorrectly required nonempty protocol_bindings in a fixture that populates
only call_inputs/result_consumers; its exit 1 is preserved, not hidden or called
an old-codec failure.

## Actual A focused evidence and test-only repair

`codec-attempt001` is a collection error (exit 2): pytest reserves parameter name
`request`. This reviewer noticed that same source issue and notified A, without
editing its file. Final source uses `request_kind`; the original collection log
is preserved.

`codec-attempt002/stdout.log` records **387 passed / 11.37 s**. Its result receipt
records exit 0, wall 12.052487 s, and identical before/after registered-source
fingerprints:
`fc5a4b495932dbc40cf798af908cb683d6dd7588e3e23d184526e16097bdd6b0`.
This is A's focused run, not an independent execution by this reviewer. It
includes the new wire tests and affected historical codec/record selectors;
this report does not substitute that count for the complete sixteen groups.

## Limits

The original missing-method branch/category and raw/current-original-packet
fallback relationships stay OPEN. Neither a same-shaped record nor a
Program20 enum validates an AttributeError handler or makes an atomic helper's
internal lookup understood. Source/runtime authority and transformation remain
false. No component/full, backend/detector, native capture or LeWM/GPU work is
claimed. This closure freezes only the actual reviewed source and provenance
above; root owns the later unified affected focus.
