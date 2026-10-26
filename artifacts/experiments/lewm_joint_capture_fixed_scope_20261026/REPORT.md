# Fixed-scope LeWM joint capture — actual result

One authorized capture, no retry. Main HEAD `914a3536f57423152b8e282ef563d79b43edce5b`; the 13 source receipts stayed unchanged. Wrapper1705081 / CLI1705099 / target1705107. Actual PTY93714 exited0; outer1323.199968679s, OS provider1199.923549625s/exit0, no timeout or provider budget stop. Original argv/cwd/eval25 and all limits were retained; utilization sampling was OFF, RLIMIT_AS unlimited. Original capture remains unchanged.

The ordinary CLI archive/coordinate path completed, but call/operand coverage is PARTIAL. The observed-code predicate passed the earlier CPU reproduction and this capture advanced well beyond original event104. It did not establish complete recording:

| Collection | Actual observation |
|---|---|
| Frame/call | 1,073,707 events;536,883 retained invocations;4,075 codes;1,199,999,834 charged bytes against1.2GB |
| Frame debt | 176,654 dropped events;161,799 dropped codes;59 open invocations;64,771 path gaps;16 retained `ValueError` types |
| Operand | 694,960 events;171,690 attempts;53 legacy handshakes;523,215 instructions;0 dropped events;2 GAPs |
| First operand GAP | event531809 `PROJECT_FUNCTION_CALL_DID_NOT_ENTER`, invocation1, frame27457, hook epoch1 |
| Terminal operand GAP | event694960 `INSTRUCTION_FRAME_UNAVAILABLE`, invocation null, frame58826, epoch2; no recorded CodeID/offset |
| Python v2 | 171,690 TARGET /21,560 ENTRY /283 GAP; own stopped=false; parent operand incomplete |
| v2 GAP reasons | 236 `PYTHON_TARGET_DID_NOT_ENTER_BEFORE_NEXT_CALL`;47 `PYTHON_TARGET_NO_IMMEDIATE_ENTRY_RETAINED` |

The terminal unavailable-frame GAP activates the existing global window stop (`call_operands.py:670–675`). Its exact missing callee cannot be reconstructed from that GAP. The first GAP advanced the hook epoch but did not immediately stop the stream. The frame byte ceiling was later reached; it is a separate observed limit, not an explanation silently assigned to the earlier operand failure. `_code` can raise ValueError on code/byte budget exhaustion, but the metadata retains types only, so individual errors are not retrospectively classified.

Archive602 members:3,050,919,760 raw bytes read and3,050,919,760 decoded roundtrip bytes read;232,544,761 stored bytes written. Coordinates610 members/252 OS artifacts/3,850,570 OS lines/5 processes/252 threads,3,050,991,506 verified raw bytes. Payload apparent245,684,973B /allocated247,349,248B; free disk after review112,466,624,512B. These are observed capture/validation costs, not a benchmark or speed comparison.

Normal collector-witness reader passed: CLOSED/errors[], process-image REGISTRATION/NATIVE_START/NATIVE_CLOSE/COLLECTOR_CLOSE, topology CLOSED_WITH_EXPLICIT_FRONTIERS. Native collection CLOSED/failures[] and311 native-input chunks were declared. v2 membership and the full C5 stat rendering are present; bounded actual stat sample is OS line11. Target stdout reports success_rate100%, which is separate from recorder coverage.

`STOP_DIAGNOSTIC.json` is one retained diagnostic pass over operand/v2 files:348,115,095 decoded bytes,16,714,884 unique stored bytes (33,429,768 stored bytes read for SHA+decode), original stored/raw EOF/SHA verified. It projects GAPs/tail only, not a full typed model read. No source body lowering, full native import, or new call-port model was run; coordinate call_ports_established remains false. State/content/ready, unknown entries and complete modeling remain OPEN. No further capture is started.
