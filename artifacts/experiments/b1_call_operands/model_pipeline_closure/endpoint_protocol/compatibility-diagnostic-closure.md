# Unsupported endpoint diagnostic compatibility

This note records only the narrow diagnostic repair requested after the joint component run. It does not claim a component or full-repository pass.

## Change

In `scar/ir/execution/validity_validation.py::_supports`, when endpoint profile resolution fails and emits `endpoint_profile_unsupported`, the support also retains `validity_endpoint_interpreter_unsupported`. The existing `validity_endpoint_protocol_unresolved` remains. A successfully parsed supported profile does not receive the unsupported gap; missing profile bytes and malformed profile issues keep their own diagnostics.

The added logic is:

```python
profile_gap_count = len(ctx.gaps)
# resolve the read, visibility, and interval profiles
if read_profile is None or visibility_profile is None or interval_profile is None:
    if any(gap.code == 'endpoint_profile_unsupported'
           for gap in ctx.gaps[profile_gap_count:]):
        ctx.gap('validity_endpoint_interpreter_unsupported', path,
                'same Q protocol reference is not a parsed observation/facet/selector visibility interpretation')
    ctx.gap('validity_endpoint_protocol_unresolved', path,
            'endpoint read selector, interval and visibility need the same parsed byte-prefix profile')
```

The fixture and tests were not changed. The existing endpoint implementation continues to distinguish unsupported profile references from a valid byte-prefix profile.

## Focused evidence

Both attempts used the same focused command in the `lewm` environment, with `PYTHONPATH=.` and `PYTHONDONTWRITEBYTECODE=1`:

```sh
python artifacts/experiments/b1_call_operands/model_pipeline_closure/focus.py endpoint_diagnostic tests/unit/test_execution_validity_domains.py::test_endpoint_observation_matches_only_its_exact_protocol_not_any_flush
```

- `endpoint_diagnostic/attempt001`: **2 failed**. Both parameter cases retained `content_selector_protocol_unverified` and `MISSING`, but lacked `validity_endpoint_interpreter_unsupported`.
- `endpoint_diagnostic/attempt002`: **2 passed** in 0.52 seconds. Both cases still report `MISSING`; the original and changed unsupported protocol references retain the specific unsupported-interpreter gap.

Attempt logs and JUnit files remain in their respective directories. Attempt001 was not overwritten.

## Source identity

Final `scar/ir/execution/validity_validation.py` SHA-256: `45e5e6cf5daf1a29b91778c03f7334a580e5bca311e76fb7895c5ab8a048a84f`.

The endpoint implementation in this file already contained other uncommitted changes from the endpoint task; this note attributes only the compatibility hunk above to the current repair. No full gate or workload was run for this repair.
