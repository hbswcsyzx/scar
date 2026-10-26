# Versioned call-port query

Only `scar/analysis/call_port_query.py` and the existing capability CLI notes changed. The isolated branch lacked this previously main-only module: its exact main baseline was copied, SHA `e36a4c23170fcea9b737fdcae18d9ad240ff4f55a86596f7e9f56f7fbce3c89f`; final SHA `c5cadfe6bbe3f7645b5a8ef88291fb1131dbd6c6bfc7cbe7e48163647a1df1bb`. Root should apply this one-file update to that baseline, not replace other query/CLI/trace/core code.

The reader dispatches by exact `(schema, schema_version)`: v1 `scar.source-call-port-bindings/1` uses the original strict SourceCallPortModel reader; v2 `scar.python-source-port-bindings/2` uses the strict PythonSourcePortModel reader. Unknown pairs/types reject. Stored SHA, regular-file checks, physical/decompressed ceilings and final file stamps remain. No raw/capture/body producer input is replayed.

V1 output remains query schema1, with `ports` and its original qualification/selector/flags. Its original real 100550-attempt model queried successfully (2516 matched bindings, 6805 total argument ports). Final output exactly matches the first actual query except elapsed time after releasing the temporary dispatch JSON; no v1 fields changed.

V2 emits query schema2 and keeps `arguments` separate from `receiver`. `--actual-index` means the original explicit AST argument index; receiver has no synthetic index. Its original observed target supplies caller issue selection; callee queries invent no unresolved destination. Caller/arg0 selected 4 bindings, including 2 independent receiver ports and 3 caller-only issues. Original plain and lossless gzip models returned identical selected records/summary/selector.

Actual rejections: wrong stored SHA; a valid-SHA illegal schema/version pair; gzip decoded-byte ceiling. No extra test matrix or target execution was used. Return routes, reference/content identity, state/ready and whole-program completeness remain false.

Sources: existing v1 model SHA `8b9e8abc8731880bb08ee92ce789f3abe359389c52eb402ba8cf069f15f123d2`; existing v2 model SHA `d71743e6e58a4b90975a725cfa0ac53486e1abc7178754085fd404288037288b`. Exact query outputs, selectors, input URIs and machine receipts are retained here.
