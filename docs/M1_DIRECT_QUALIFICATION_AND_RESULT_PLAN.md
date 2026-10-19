# F15：direct/self资格与另一Drive结果的有限验收

2026-10-19。基线 `7aee713c1b700f504ba3ebb8606fa2a4456c4e1c`，开始时干净，
前轮为verified progress：1845同源定向、全部1807旧identities保留，原E/G/H
及F17/F21/F23条件结构关闭，commit前后归档核验和远端精确SHA确认。本轮
开头实际重核前轮checkpoint。整个目标继续active。

## 1. 模型与原范围

仍用Operation / Value / StateLocation / Region / Resource及原有序Use、CFG、
own完成端口和状态SSA。资格、值来源、动态发生及变换权限分别核；相同类型
不意味着可以交换两个结果。M1供应图结构不代替M3/M4自动恢复/实际采集。

依据原[M1_REMAINING_PROTOCOL_PLAN](M1_REMAINING_PROTOCOL_PLAN.md)F15行与
[上一门原范围验收第4节](M1_AWAIT_ORIGINAL_SCOPE_ACCEPTANCE.md)。主链、当前
状态、wrapper原B错接已有精确证据，不能重写成nativeB全路线矩阵。本轮只
补该族两个准确negative；确认是否已正确拒绝，再决定是否修改通用产品。

## 2. 两个必须实际运行的变体

### A：ordinary GENERATOR不能误获direct/self await资格

仅新tests/unit/test_program_await_direct_qualification.py。以现有完整
zero-cut、单Create的await_resume_program为基础；原GENCORO完整图是正对照。

负图把唯一body.kind改为GENERATOR，并准确迁移对应scope到已有
GENERATOR_BODY_V1、原完成adapter clause到已有HOST_ADAPTER。原rule、Get
expected/ownN、调用receiver、真实NEXT/Drive、最终提取ownN/R、全部Uses、
state、CFG和协议行库存保留。不删旧factory的kind限制，不改旧fixtures。

先清空五protocol表核core合法；full应准确报protocol_await_acquisition_kind。
泛化层拒错才是证据，不能拿早期record/core错误冒充。另保ordinary GENERATOR
普通NEXT的合法正对照，防止把非法await资格扩成“普通generator不可驱动”。
不以general __await__返回GENCORO的相反拒例填此格。

### C：另一Drive的adapter结果不能替代当前准确结果

仅新tests/unit/test_program_await_foreign_drive_result.py，构造器同文件。
必须在合法原图中保留两个真正不同Drive的独立结果/adapter own端口和正确
对照，明确本次expected结果与另一结果的producer/ordered Use/completion。
替换后引用支配及状态SSA仍合法；不把另一Drive的O关联填错、helper结果、
wrapper terminal包或不同类型值当这个反例。独立callee/caller需用原调用
端口衔接，不制造已关闭B第二次Start的非法生命周期。

由作者先给具体原端口与控制映射，再写最小helper。core-only必须合法；
source_binding须能精确说明不来自本次expected，full公共校验应拒绝。若
当前原端口不能自然表达，先记录真实字段阻断，不造第二producer图/隐式
copy/新的业务规则。预计不需要wire/codec变化。

两个反例都保完整好图与具体错误证据；只在真正抵达公共产品的失败后修复。
准确拒绝时只补缺证，不能为了出现产品diff而改已经正确的逻辑。

## 3. 并行、冻结、验收与版本

A/C独占上述两个新文件；B只读核F12/F13与原A/B/C/D/F精确条款。root独占
产品/docs/所有Python、pytest、probe、compile、归档及Git。作者不运行解释器，
每次root执行前两作者全冻结；不得同时写源/运行或覆盖旧attempt。

1. 冻结本计划，记录设计基线/保护仓库/原1845选择及原义务ledger。
2. 先完整最小例并保存实际命令、日志、JUnit、source before/after；新测试
   构造错误与真正公共关系缺陷分账。失败不删、不覆盖、不提高预算求绿。
3. 两个准确negative和必要好图通过后，一次最终受影响定向保原1845全部准确
   identities及所有旧test/fixture字节。不是P4组件或冻结全仓的替代品。
4. 独立读原F15完整条款，对照既有wrapper/主链和新两负例，证据齐全才关该
   原M1结构族。E/G/H及F17/F21/F23保关闭；其余十二族仍须各自原义务。
5. F12/F13审查只可根据原条款和实际selectors合账；已有证据不反复造图，真
   欠项留具体selector/关系，不强行宣布整行通过。不扩大scope乘积。
6. checkpoint核原归档/字节/合同/codecs、保护仓库、最终同源测试，归档报告、
   commit/push及远端SHA；原始全阶段P5/M2的113构造/196字段完整范围保留。

证据目录artifacts/experiments/b1_call_operands/model_direct_qualification_and_foreign_result/。
不新增detector/backend，不跑native/GPU/LeWM实验，不给新加速比；M0–M2真
齐后按用户要求先停下来解释模型。既有工具复用和后续自动建图职责保持。
