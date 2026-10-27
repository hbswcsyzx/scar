# 两次真实静态close调用／两BodyDrive的retry组合

## 限定任务与接口

新增owned `tests/fixtures/program_generator_close_retry_graphs.py` 与
`tests/unit/test_program_generator_close_retry.py`；未改产品、原有fixtures、旧测试、docs或gates。
`two_close_requests_program(release_first=False)->(graph,details)` 为单个supplied ProgramGraph：

1. 一个canonical generator body，含原首cut、真实动态Data predicate→BRANCH、Return(v)/ignored-YIELD两分支；
2. 第一driver真实frontier分别Return/YIELD，保正常close directcopy及错误构造helper own NORMAL/RAISE→host RAISE；
3. caller真实INVOKE第一driver，NORMAL有真实Return路径，只有RAISE landing继续构造第二个RAW CLOSE；
4. instance由第一call独立owned Use转发到该RAISE formal，再作为第二call actual；
   第二call states只取第一call实际CompletionResult→formal，不能回退caller原entry states；
5. 第二driver/第二BodyDrive明确选择第二cut的THROWN_PACKET case，自己的normalizer产生新packet；
   本次body真RAISE→首commit F，close helper自己的NORMAL Reference None→host Return，且能支持真实release；
6. 第一YIELD commit无F；不能借第二driver的终结历史给第一错误路径release。

第二driver只对该静态region自己的Region/Block/Operation/Value/Use/ControlScope/ProtocolScope IDs做显式映射，
重命名其原记录引用；body definitions/state locations/frame records只保一份，未另造producer/Uses/world。
第二driver自己的原PacketDefinition也准确映射。两个RAW CLOSE是caller的真实纯descriptor op，
不是native创建见证或新permit。没有ExecutionModel/CallActivation/BodyDriveExecution记录。

## 不可隐去的首轮接口限制

初稿第一driver只含illegalYIELD→host RAISE，callee只有RAISE ExitPort。
`TerminatorKind.INVOKE` 构造器却要求恰好NORMAL+RAISE两distinct successors；
knowncallee还要求completion signatures精确等于callee全部exits。
因此不能用仅RAISE INVOKE接它，也不能补一个无实际site的NORMAL逃过校验。
首attempt真实暴露这个限制，**本任务没有修改或证明已解决该模型限制**。

root授权最小真实分支方案：body由原dynamic bool结果BRANCH选择真实Return(v)或ignoredYIELD，
两first outcomes及各自adapter都保留，firstcallee因此真正有NORMAL与RAISE，caller两边亦真实。
不是用常量假branch/无site ExitPort凑NORMAL，也不把“仅RAISE INVOKE是否放宽”夹带到本门产品。
这个普通body判词只是declared control/data operation，不是可写native phase或异常类证明。

## 串行attempt与原始证据

每次script均显式source conda.sh、activate lewm、PYTHONDONTWRITEBYTECODE=1、PYTHONPATH=.；
Python3.14.7，selector只本新文件。stdout/stderr/JUnit/exit/时间/准确命令和17源before/after保存于对应attempt，
每次17源前后均一致；未运行global fingerprint，不对并行owner新root测试的全仓变化作假冻结声明。

| attempt | 命令selector | 实际结果 | 归因 |
| --- | --- | --- | --- |
| 001 | 全5 | 5F，0.71s，wall1.32s，exit1 | 上述仅RAISE callee的INVOKE构造限制，原失败保留 |
| 002 | 全5 | 5F，0.73s，wall1.33s，exit1 | 真实分支已成立，但新fixture遗漏second driver自己的原PacketDefinition；原C0正确protocol_definition_missing |
| 003 | -k two_actual | 1P/4 deselected，0.68s，wall1.29s，exit0 | 仅补新fixture中的driver-owned PacketDefinition映射后，正例先独立确认 |
| 004 | 全5 | **5P，0.85s，wall1.49s，exit0** | 正例与四个实质负例共同通过 |

精确运行命令以各 `attemptNNN/command.sh` 为准，终态命令：

```bash
bash artifacts/experiments/b1_call_operands/model_generator_matrix/close-retry-focused/attempt004/command.sh
```

002只归新fixture外键遗漏，不冒产品错误；未加xfail或放松预期，未覆盖首败。

## 实际五项验收，不按总数替代完整矩阵

1. 两实际caller INVOKE／两不同driver Region／两实际BodyDrive共享单body；
   first RAISE exact forward instance和新state进入第二call；第二Resume target精确为新cut THROWN_PACKET；
   first YIELD不F、second trueRaise F、second release成功。
2. 第二target偷换首cut但继续声称retry终端，`driver_outcomes`拒绝。
3. 第二call回退第一call之前state，原SSA `stale_state`拒绝。
4. 第二gate实际delivery与独立forward一起换成上次host error，保core/D1相符但协议`protocol_copy`拒绝。
5. 第一YIELD错误路径release不能借共享body的第二driver F，`terminal_release_unfinished`拒绝。

这是**存在于supplied静态CFG中的准确可能路线**：第一call的RAISE接口也可能由其他真实失败终端绑定；
不把所有first RAISE都说成特定RuntimeError construction，不声称观测到该具体路径或同一动态activation。
第二request/Drive确实已在图中，区别于上批仅存在两个retry landing。

## 最终source receipt与边界

```text
37c2a9979986c338046767633017d20c21dcd2b191a8597f18ca4490aab335c4  tests/fixtures/program_generator_close_retry_graphs.py
58692e4415484920196cd3d535d69cc620af8d9ec4c2c62756b6de92247b89d1  tests/unit/test_program_generator_close_retry.py
de64bd2c6a6552344a59e089d3b893bb40d09c77676c2f960aef2db297fff412  tests/fixtures/program_generator_close_graphs.py
f4d2044c83996b9fdd211276f7c27396d36c6e7900fc8c7f699aba90cbbfc544  scar/ir/program/protocol_validation.py
9fc23f943b8389764876856579db2e82797b2fb375a8c9ecc701b785b094d7f7  scar/ir/program/lifecycle_flow.py
```

**PASS_WITH_SCOPE：五节点supplied static组合通过，四owned源冻结。**
不授native phase/exception class/Reference identity/同runtime activation、source inventory完整性、自动建图或变换权。
未跑组件/full/native/GPU/LeWM；完整P2、同步16格全部子路径、其他C2/D3家族、M0–M2不由本批关闭。
