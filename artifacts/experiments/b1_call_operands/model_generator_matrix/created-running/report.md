# Created/Running 原图矩阵：限定交付

2026-10-18。依据 `M1_GENERATOR_MATRIX_PLAN.md`、`M1_ADMISSION_PREDICATE_CONTRACT.md` 及本机 `native/report.md`（40项矩阵观察+6项机制观察，非本作者重跑）。

**终态：本分工18项focused PASS，fixture/test已冻结；完整P2消费者与16格语义验收仍OPEN。** 18是本文件参数化测试数，不是16格或40项native观察的通过数。本分工只改两个新fixture/test文件及ignored evidence，没有产品修改、组件/full、workload或commit。

## 1. 原图/API

`tests/fixtures/program_generator_admission_graphs.py`：

```text
generator_admission_program(
    stage='created'|'running', kind=RawRequestKind,
    send_none=True, constructor_failure=False, retry=False, throw_operands=1)
    -> (ProgramGraph, details)

invalid_request_binding_program(operand_count=0|4)
    -> (ProgramGraph, details)
```

只复用原 `_Builder`、resumption/close/driver/no-body/publication构造器，产生一个规范ProgramGraph；没有ExecutionModel、动态activation或第二份state/producer图。每次组合保留一份原body定义，wrapper/caller是原region/operation/Use，所有 state after仍原OperationResult/CompletionResult的formal。

- 同一个body支持首YIELD、SENT后再次YIELD、packet捕获后再次YIELD及后续Return/Raise。这些是实际declared CFG分支，因此普通方法wrapper的NORMAL/RAISE都有真实接口路径，不借无关body或不可达假NORMAL绕过旧INVOKE限制。
- 原caller持有真实raw pack的OperationResult与RawRequestDefinition；driver scheduler仍entry formal。CALL/INVOKE实际ordinal绑定直接断言，None/7是原Reference producer的LiteralEvaluation，不能把ExactData当Ref。THROW class/instance原引用仍未知内容，不把其名称当class证明。
- 新phase谓词拥有body+实际coarse READ，None谓词只拥有原argument；没有添加raw输入、phase flag或新state链。原bool和BRANCH保完整true/false edges。读数的native/source适用仍有条件。

## 2. 八格及必要分支的实际构造范围

| 格 | 本次原图/检查 | 未被本次测试证明 |
| --- | --- | --- |
| Created NEXT | 原Create NORMAL handle→原caller NEXT raw→driver Created READ/bool/branch→真实gate/BodyStart；Start无resume payload | native确为Created、gate正常边实际发生、完整consumer/source闭合 |
| Created SEND | 精确None Reference附件+独立isNone分支；nonNone=7另走本次拒绝。真实caller RAISE landing后，以同owner forwarding和最新RAISE state第二次INVOKE NEXT-driver，不从host终端造假续边 | raw/None多caller recipe与消费者可行性的完整联合核验；动态同一实例 |
| Created THROW | Created真分支的原helper N/R及准确selected no-entry transition→host RAISE；分别核delivered/constructor-failure边的F，选中分支没有BodyDrive；非Created分支为同body真正Suspended packet捕获/YIELD | opaque initial helper内部的constructor/callback具体code与异常class/值身份；自动native匹配 |
| Created CLOSE | 复用原CreatedCloseTest、真实true私有landing首NoBodyFinish；原None Ref producer→host RETURN，false为真实Suspended close处理 | predicate native执行/phase正确性，引用释放与实际资源free |
| Running NEXT | 当前READ/bool→Running真分支→本次拒绝helper/packet→host RAISE；外层caller实际catch后继续RETURN | 当前phase native真实性、外层真实生成器activation采集 |
| Running SEND | 同样真实READ/拒绝路线及原SEND参数；wrapper非Running分支保留实际SENT→YIELD路径 | 不是“None就允许重入”；本次尚未完成逐consumer feasibility核验 |
| Running THROW | **先**真实normalizer INVOKE，NORMAL和RAISE的各自poststate分别进入当前Running READ/branch，再由新的重入拒绝helper产生最终packet；normalizer失败packet不直接冒最终ValueError；外层catch继续 | 源code覆盖/异常类真正ValueError、norm callback真实执行，不能由标签授证 |
| Running CLOSE | 当前READ/branch→本次拒绝，无finish/F；false分支保真实close的Return/ignored-YIELD语义 | 不按单host RuntimeError推bodyClosed，也不声称完整close组合已由本文件复验 |

CreatedTHROW还保留本次selected N/R的actual state/F对应；每条初始边均单独测试，未把不同异常名当终结判断。RunningTHROW同时检查normalizer的RAISE→新reentry错误覆盖，严格区别于早早Running判断而跳过callback。

## 3. 有界反例和接口边界

- **同型错误bool**：添加本分支可用的literal bool替代predicate结果；原core先单独验证仍合法，然后必须命中 `admission_bool_source`。初稿使用互斥分支的bool只触发core `unavailable_value`，其失败保留，未把假阳性当产品漏洞。
- **retry旧state**：把第二次调用的currentRAISE states换第一次调用前states，必须 `stale_state`。
- **Running真→Start overapproximation**：在原Created图仅改变phase rule，仍允许opaque final gate自身拒绝，因此图合法；公开predicate路径必须标 `target_compatible_at_snapshot=False`、`admission_phase_target_incompatible_at_snapshot`、PARTIAL和 `native_gate_verified=False`。没有误称hard reject或把该路径当可成功执行。
- **非法arity在RAW之前**：新core允许真实单RAISE INVOKE后，0/4个THROW operands作为原call-binding helper输入，通过onlyRAISE callee→caller的准确异常landing→handler RETURN；始终没有RawRequestDefinition/BodyDrive/F。只验失败端口与partial after-state，不用错误arity破坏合法RawRequestDefinition合同。其和builtin throw绑定算法的source对应仍是fixture解释，非自动识别。

## 4. 所有实际尝试

每次均显式激活lewm、禁止pyc，精确命令为：

```text
source /home/zyf/miniconda3/etc/profile.d/conda.sh
conda activate lewm
PYTHONDONTWRITEBYTECODE=1 PYTHONPATH=. python artifacts/experiments/b1_call_operands/model_generator_matrix/created-running/focus.py attemptNNN
```

runner只运行 `tests/unit/test_program_generator_admission.py`，各目录保command/Python、完整stdout/stderr、JUnit、registered源码before/after哈希和returncode。

| attempt | 真实结果 | 归因/处理 |
| --- | --- | --- |
| 001 | 15 failed / 1.50s | 三类fixture错误：启用DriverLifecycle未补原Drive publication；外层抓住所有错误仍多声明无终端RAISE；旧no-body factory假定entry=gate，直接套normalizer图导致重复owner。只修新fixture：调用既有with_publications、caller仅声明真实NORMAL、按原template在normalizer前接predicate/truefinish，不改旧factory/core。 |
| 002 | 14 passed, 1 failed / 1.69s | 错bool来自互斥block导致core先拒；保旧负例源码，改为本分支可用同型bool以隔离真正协议guard。 |
| 003 | 16 passed / 1.75s | 上述图及精确snapshot-incompatible query负例。16是当时case数。 |
| 004 | **18 passed / 1.93s** | 在根代理实现general onlyRAISE INVOKE后，加入2个原arity binding失败/真实caller-handler用例。 |

四次实际进程期间注册源码前后均相等。最后指纹 `b4872422e3a47833debba8f4ae5a80e41f5f7d74c82d2dc09452f27101c95d34`，harness wall2.612686s。后续其他作者编辑不属于此指纹，不称最终component/full已冻结。各次重复用例不相加。

## 5. 明确仍OPEN的分母

1. Created/Running八格现在都有原read/branch/caller/result/state的**正结构图**；并未全部具备逐格原类型保持的raw/None/source/host反例和完整consumer feasibility闭合。
2. rawkind、raw ordinal、None及不同static caller的原recipe如何与特定predicate edge/target联合，是根代理/A后续消费者接口；本文件没有firstmatch，也没有假装未知source已经配上。
3. opaque gate面对Running快照不相容仍可能通过自身RAISE拒绝；公开gap已验，不把静态NORMAL边存在等同真实成功重入。callback后旧read失效与gate重新检查分别保条件。
4. supplied phase/read primitive、no-entry/helper异常类别、class构造与callback实现均未取得native/source/runtime证明。实际异常身份/cause/traceback相等不从相同文字或payload类型推导。
5. 本机native40+6只提供对本版本行为的观察；这些手工IR不是其自动恢复结果。P3持续body activation、动态调用/实例/线程与运行采集均未在此新增。
6. Suspended/Closed另归C矩阵；完整16格、F01–X28、P2总验收和后续P3–P5不因这18项关闭。没有detector/backend/优化或LeWM加速结论。

## 6. 冻结SHA

```text
f75029b80becdd7f1a477d4757176171ea70ebd2a080236c81f4b5b65d3aea9a  tests/fixtures/program_generator_admission_graphs.py
c3efce01352102351fbf6240b991ec0977675495ca2e7c31e4eb233d951fae6e  tests/unit/test_program_generator_admission.py
```

末次阅读的协作产品SHA（不是本人修改，不宣后续不变）：

```text
3f3d49ed938273588f0350ee2a813ee23d2dcf2ff669e332a9441e0364f93838  scar/ir/program/admission.py
830a5b7571a35ffbe56d3f910bcd17f7ca06b9b503792194edccb84e6a3bd790  scar/ir/program/protocol_validation.py
c99cf731b763367f58f569f272003e4b979857a7d4452aa61705ffd504289306  scar/ir/program/input_origins.py
```

本报告后停止本分工所有source/test写入及测试；完整消费者剩余分母交根代理继续处理，不擅自缩小验收范围。
