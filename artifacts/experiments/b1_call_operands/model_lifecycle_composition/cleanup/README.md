# Owned cleanup composition attempts

Each run used this command in `/tmp/scar-structured-model-280qf4mi`:

```bash
source /home/zyf/miniconda3/etc/profile.d/conda.sh
conda activate lewm
PYTHONPATH=. python -m pytest tests/unit/test_lifecycle_cleanup_composition.py -q
```

The actual invocations redirected stdout/stderr to the corresponding `attempt-00N/pytest.log`,
captured `$?`, printed that same log, and exited with that code. Every attempt exited 0.

- attempt-001: initial four positive compositions; 4 passed in 0.53s.
- attempt-002: 13 cases, added E/F/P/current-state/escape/early-release assertions; 13 passed in 1.08s.
- attempt-003: same 13 cases after adding incoming HOLD→Enter kill and original packet/fresh pack chain; 13 passed in 1.08s.

No failed run, full suite, component gate, native probe, LeWM execution or GPU work was performed.
Attempt-001 source hashes were not captured before the additional tests; no reconstructed hash is claimed.
The fixture first run passed unchanged; its final source later adds source-post before Enter.
