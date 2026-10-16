# M2 language probe evidence

This directory contains a short, standard-library-only probe for language behavior referenced by
`docs/model/PYTHON_DATA_DEFINITION_PROTOCOLS.md`. It imports neither SCAR nor LeWM and does not
execute target project code. The probe records interpreter version, selected AST fields/modes, and
observable event order from small local definitions.

Runtime: `CPython 3.14.7 | packaged by conda-forge | (main, Sep 2 2026, 21:08:32) [GCC 15.3.0]`.

Command used from this worktree:

```sh
source /home/zyf/miniconda3/etc/profile.d/conda.sh
conda activate lewm
python artifacts/experiments/b1_call_operands/model_definition_protocols/probe.py \
  > artifacts/experiments/b1_call_operands/model_definition_protocols/probe-output.json
```

Observed examples include decorator/default timing; lazy 3.14 function, module, class and type
annotations; TypeAlias value and TypeVar bound/default access; metaclass construction hooks; call
argument expansion; assignment target timing; async/generator entry; and f-string/t-string
construction. The probe is illustrative evidence for these cases, not a proof for arbitrary
metaclasses, descriptors, loaders, native code, Python implementations, or all language paths.
Language rules are checked against the Python 3.14 reference linked from the specification.
