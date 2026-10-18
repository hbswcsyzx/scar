# 同步 close 新组合：原结果/消费者/F 连接

## 范围与owned文件

只新增 `tests/fixtures/program_generator_close_graphs.py` 与
`tests/unit/test_program_generator_close_contracts.py`，以及本ignored证据。
没有改产品/旧fixture/旧测试/主docs；未运行组件/full/native/Python工作负载。
设计母报告为 `../design/suspended-closed.md`，完整Suspended/Closed与16格分母未因本批缩窄。

`generator_close_program(outcome='return'|'yield',adapter='direct'|'helper',release=False)` 返回 `(graph,details)`。
它复用真正packet resume、FirstOutcome、FinalGate私有landing、原ContextAttach/Detach、State SSA，
在构造adapter后用原 `with_publications` 插首commit并更新其实际current state inputs。

- Return：声明body处理注入packet后真RETURN(saved Reference)，不把普通bodyReturn→hostReturn当所有请求通用。
  close可directcopy，或真实opaque helper own NORMAL Reference与RAISE packet分别消费。
- ignored-YIELD：body packet landing真Detach→第二Suspend；frame/value私有保存，
  NEXT/SEND和THROW/CLOSE各有独占retry landing与新Attach。错误构造INVOKE有真实NORMAL/RAISE两后态；
  NORMAL Reference组原PacketDefinition后host RAISE，RAISE直接传播own packet。
- 每个Drive source先BodyOutcomeCommit；source是Suspend则不种F，host错误不能改写其为终结。
- `state_as_close_payload_program()` 只给原core-valid publication贴错误close metadata，
  DriveResult state slot和State OperationResult不能冒yield payload或RuntimeError。

这些是声明图，handler/GeneratorExit类别/当前Suspended/native helper applicability仍是source条件。
retry landings证明接口能够保存并恢复；**本批尚未创建第二次driver request/BodyDrive，不能称完整retry已验收**。
“另一旧终端不能给当前Suspend种F”反例指同body不同ingress的静态source，不授跨动态activation身份结论。

## 首轮实际命令与结果（保留失败）

root明确暂停产品修改后，只执行：

```bash
bash artifacts/experiments/b1_call_operands/model_generator_matrix/close-focused/attempt001/command.sh
```

script完整保存，包含：

```bash
source /home/zyf/miniconda3/etc/profile.d/conda.sh
conda activate lewm
export PYTHONDONTWRITEBYTECODE=1
export PYTHONPATH=.
python -m pytest -q tests/unit/test_program_generator_close_contracts.py --junitxml=artifacts/experiments/b1_call_operands/model_generator_matrix/close-focused/attempt001/junit.xml
```

实际 **Python3.14.7；5 PASS / 5 FAIL；pytest0.87s；wall1.47s；exit1**。
15源before/after经cmp相同；stdout/stderr/JUnit/exit/环境/时间与精确命令均在attempt001。
没有改预期迎合产品，没有xfail，没有重跑或覆盖首败。

| 实际失败 | 实际结果 | 分类 |
| --- | --- | --- |
| STATE冒close payload/result | `_codes(graph)==set()` | 产品漏拒；metadata-only，原core先通过 |
| bodyReturn→helper own NORMAL Ref→hostRETURN / RAISE packet→hostRAISE | `protocol_host_adapter` | 产品误拒合法条件结构；原core先通过 |
| ignoredYIELD的constructor NORMAL packet换旧入站packet | `_codes(wrong)==set()` | 产品消费者漏核；原core先通过 |
| 同constructor RAISE packet换旧入站packet | `_codes(wrong)==set()` | 产品消费者漏核；原core先通过 |
| return-helper own NORMAL结果换可用旧owner Ref | 只有泛`protocol_host_adapter` | 该图被拒，但与合法图同误拒，不能当own-result copy校验通过 |

5项通过：close directReturn、ignoredYIELD真实own N/R且Ffalse、该host错误后release拒绝、
把其他ingress Return冒本Drive source拒绝、release旧preDrive state拒绝。
所有构造/负例都先对剥protocol表的原图require_valid（release本身故意不合法的F/state反例除外）。
没有fixture错误导致的测试失败；没有把本批观察误称native/runtime证明。

首轮冻结文件与命令SHA：

```text
7fcbca237df537adf9ed05a2d4f1a378aa1e8737e7f3f51cf3a2e104d66770e3  tests/fixtures/program_generator_close_graphs.py
6434bc2e175a658a407c0e2919468c65900cb5a8c6b8bcafcccf166280e56bd3  tests/unit/test_program_generator_close_contracts.py
72bb405b76a48e49c17cd783a7e3d6adc821ef9436c433177893204621eb48b6  close-focused/attempt001/command.sh
```

## 当前结论

**IMPLEMENTATION_OPEN**。root接手close规则与精确consumer修正；owned新fixture/断言暂冻结，
等待产品稳定窗口才另attempt复跑。GE消解None、其他异常传播、真正第二driver retry、NEXT/SEND/THROW完整子分母、
Closed阶段/请求来源继续按母报告保留，不能以这10个节点代替完整P2。

## attempt002：原断言与fixture不变的限定关闭

root完成close消费者修正并明确稳定窗口后，仅原样复跑该10节点文件：

```bash
bash artifacts/experiments/b1_call_operands/model_generator_matrix/close-focused/attempt002/command.sh
```

该命令除证据目录改为attempt002外，conda activation、禁pyc、PYTHONPATH、
pytest selector均与首轮一致。实际 **Python3.14.7；10 PASS；pytest0.83s；wall1.43s；exit0**。
本轮15源before/after经cmp完全相同，原始stdout/stderr/JUnit/exit/command均保存。
首轮5P/5F及所有其时源hash原样保留，没有覆盖或将其追认通过。

两轮15源清单对照中，仅 `protocol_validation.py` 改动：

```text
attempt001 0dd22732e03bf6824c8c3551060814013e96ce693fedaad95cdbba1b7a3825c7
attempt002 59dfeacdae45b4f9c434298b62e204be0a20af0a512e2646ca2a9ec86ca49363
```

owned fixture保持 `7fcbca237df537adf9ed05a2d4f1a378aa1e8737e7f3f51cf3a2e104d66770e3`，
owned unit保持 `6434bc2e175a658a407c0e2919468c65900cb5a8c6b8bcafcccf166280e56bd3`。
attempt002 script SHA `42b75776e50e5e9fab70d38b701d82d605ba0a5bcd3f2ae831990bbd47e6246f`。
未运行global fingerprint脚本；并行owner的input_origins等文件不在本15源范围，
这里不声称全工作树无其他变化，也不将其他owner新增源归因为close产品变更。

窄读当前修复与实际测试一致：close固定DriveResult index0/真Return、Raise或相应YIELD来源；
禁止STATE结果角色；close own selected N/R继续核host kind及结果/显式packet的exactcopy；
bodyReturn helper NORMAL自身结果路线被允许，不能只要求输入v直接copy而误拒新边界结果。
原session/F算法SHA不变，真正Suspend仍不F，旧状态与旧source借用仍由原守卫拒绝。
以上源审/测试仅关闭首轮列出的五项连接问题，不将native applicability/引用identity变成已证明。

**本批10节点结论：PASS_WITH_SCOPE。** GE suppression的准确None来源、其他异常propagate、
真正第二个request/BodyDrive retry和完整16格继续OPEN，待root后续精确分工。
现在停止owned fixture/unit写入与测试；未运行full/组件/其他测试文件。

## 获新授权后的Task1：GE消解及其他异常传播

root后续授权补原两个owned文件。`outcome='raise',adapter='helper'` 使用真实body RAISE packet，
修正adapter原input Use为PROTOCOL；helper NORMAL原Reference结果通过
`LiteralEvaluation(InvokeLiteralResult(adapter, NORMAL/CompletionResult(0)), exact None)` 声明None内容，
没有给Reference改成ExactLiteralOrigin/ExactData、没有更换producer。
该own结果进host RETURN；helper RAISE自己的packet进host RAISE。
异常类别/GeneratorExit适用仍Native条件，None payload声明不授权对象身份。

`outcome='propagate'` 在body内新增真实opaque INVOKE，NORMAL/RAISE均产生自己的新packet及两domain后态，
各自Detach后真body RAISE，再沿准确DriveResult到host RAISE。不拿已注入的同一GE packet假称其他异常。
所有ordinary非GE类别仍需source协议/原判词证明，当前结构允许表达且保条件。

| 顺序attempt | 实际结果 | 失败归因/处理 |
| --- | --- | --- |
| 003，全15 | 12P/3F，1.01s，wall1.63s，exit1 | 新propagate fixture移除旧Detach却保留两旧结果，原core result_origin拒；仅修fixture过滤旧结果 |
| 004，全15 | 12P/3F，1.00s，wall1.64s，exit1 | 新propagate fixture仍保无site的NORMAL ExitPort，原core unbound_exit拒；仅删该无实际site端口，没有补假normal |
| 005，仅other_三项 | 1P/2F，0.66s，wall1.33s，exit1 | 正例core/full合法；两个host输出换旧入站packet的core-valid错误图均被完整validate接受，是真实产品漏检 |
| 006，全15 | **15P，1.01s，wall1.61s，exit0** | root修bodyRAISE默认exact packet或准确adapter消费后，原断言通过 |

003/004首败原样保留且**不当作产品bug**；005是已执行的不同产品consumer漏洞，
root负责产品修正。本owner没有改任何产品或削弱反例；每attempt均有stdout/stderr/JUnit/命令/exit/15源前后SHA，
各自前后完全一致。新None两项已在003/004通过，最终仍由006全文件覆盖。

006受测 `protocol_validation.py` SHA
`f4d2044c83996b9fdd211276f7c27396d36c6e7900fc8c7f699aba90cbbfc544`。
新最终owned fixture SHA `de64bd2c6a6552344a59e089d3b893bb40d09c77676c2f960aef2db297fff412`；
unit SHA `37d3414639642a33eaa61ed260c858708a90592542095e1d0781e0d95a6330c6`。
本轮不测global fingerprint；其他owner新admission/source文件不在15源中，不能据此声称全源冻结。

**Task1限定终态：15节点PASS_WITH_SCOPE，包含原10节点，不能把10+15重复相加。**
新增None/propagate的声明连接关闭；native异常类别、真实Python对象identity及其自动来源仍未证。
真实第二request/Drive由独立 `close-retry-focused/report.md` 记录，不拿两个retry landing冒替。
