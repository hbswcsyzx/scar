# Actual owned OS observations

Three focused integration cases pass in `witness_os/attempt001`: **3 passed / 0.33s**.
Separately, `witness_capture/attempt001` contains three raw CLI receipts, exact
commands and the observed script hash. These are additional OS executions, not
three more pytest cases or a frozen gate.

| Case | Observed | Does not establish |
| --- | --- | --- |
| file | write accepted 8; same-fd unbuffered pread saw 0 before explicit flush, 8 after; fsync and close returned. | A different process/open descriptor sees the same state; power-loss durability; IR/native correspondence. |
| file_raise | outer save wrapper raised after accepting 8; no explicit flush/fsync; successful finally close left 8 readable. | close itself raised; a syscall accepted 8 but wrote only 4; no implicit close effects. |
| pending_raise | at host raise: worker not done and destination still zero; later 4 of 8 bytes changed, worker FAILED, this memoryview was released. | GPU completion; all aliases gone; allocation retirement; automatic source/port binding. |

Normal file output SHA-256:
`e30e916712e1c3cadfa6929d4ece20a189a5ab5ccce238f528b72055e8169fbc`.
Partial worker-buffer SHA-256:
`39c962d347ed1503afcf75afae38d53c8e2bf2496a163a82f22a259540e935a9`.

Each script supervises one fixed worker with a ten-second hard timeout and
waits for its exit before removing only its own temporary directory. Positive
cases observed cleanup; the timeout-kill branch was source-reviewed against
local stdlib, not forcibly triggered by these cases. Raw results never set
source_runtime_verified or transformation_authorized.

The first declared unbuffered pipeline fixture cannot represent this buffering
case merely by moving its Q root later. Root review required a distinct CPU
buffer materialization, explicit buffer-state extraction, a flush contribution
to the file endpoint and a read-before-flush negative. Host failure after
submit must branch before wait/consume. These findings guide the model change;
OS observations do not automatically create those canonical ports or effects.
