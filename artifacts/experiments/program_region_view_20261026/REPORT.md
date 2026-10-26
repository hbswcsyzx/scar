# Compact source Region view

Public CLI read of one original 239-operation source body: compact exit0/3.393s,
expanded exit0/3.352s. Verification exit0/5.702s: every original operation occurs
once; 714 ordered Uses = 628 crossing + 86 inside folded runs; all 76 state
accesses and 121 control edges, exits, resource declarations and effects survive.
Original members are expandable. Wrong source SHA/region rejects.

This folds language-management encoding inside an original Block, without
deleting target work or granting source/runtime/optimization proof. Original
SourceProgram context is not replayed. Outputs stay local; the small input and
verification receipts are versioned. Run with `PYTHONPATH=. .../python -B verify.py`
from the repository root; the initial attempt without PYTHONPATH exited1 before
opening the input. Whole-program modeling remains OPEN.
