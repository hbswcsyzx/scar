# P2 协议连接独立实施与源审

基线由root指定`85aee70`；当前**OPEN，未验收P2整门**。
仅拥有新fixture、connection unit和本ignored报告；没有修改产品、codec/model、旧fixtures或主docs。
截至本起始记录没有执行Python/pytest/probe；等待root validator/query READY后首跑自有单文件。

## 1. 已落实的原图连接夹具

`tests/fixtures/program_protocol_graphs.py`各factory返回`(graph, details)`：

- `request_processing_program(loop=False, previous_iteration=False)`：真实3operand THROW descriptor，
  不同operation拥有独立Use；处理器产生两个Reference结果，指定结果进入原ExceptionPacketDefinition。
  旁边另一同型Q packet可作错误替代。loop版同一静态producer每轮重执行，header保留上轮carrier，
  正例消费本轮结果，反例消费prior，拒绝把静态来源相同当当前结果。
- `generator_protocol_program(target='start'|'value'|'packet')`：复用原D1 driver/C2 body。
  start为普通YIELD export→Drive→host item；value添加真实异常构造INVOKE NORMAL/RAISE，
  NORMAL结果组packet后host RAISE、异常分支原packet传播；不保旧generic bodyReturn→hostReturn为Python正例。
  value/packet处理器在final gate之前，NORMAL私有landing仍仅有原BodyDrive，处理后的payload沿准确gate/drive slot。
- `no_entry_throw_program(selected=ExitKind.NORMAL|RAISE,reject=False)`：原helper INVOKE两真实后态，
  NORMAL helper也可最终host RAISE；只一准确selected edge具有NoEntry合同，另一边无新终结事实。
  reject改PREENTRY_REJECT；保body声明而没有伪Drive。Lifecycle启用以观察F/T，不从Raise类型种F。
- `closed_request_program(kind=NEXT|SEND|THROW|CLOSE)`：当前helper输出到host terminal，
  没有Drive/NoEntry INITIAL合同或新F；保一个旧packet/return carrier用于core-valid错误重放。
  Closed前提属于source applicability，不靠fixture名、phase字段或枚举自证。

这些都是手工声明IR，不是Python程序恢复或native执行证据。source为准确typed gap；
规范化/StopIteration构造/Closed/current状态语义保条件，不把Method名称或同型Value升级为身份事实。

## 2. 首批有意义正反例

新unit针对：own result与同op其他同型result；packet Q错组件和目的地Use自证；raw原ordinal与跨op独立Uses；
Reference Use冒external RAW；loop旧visit值；NoEntry N/R只选边F/T及PREENTRY不F；
选边/slot/terminal反选；YIELD item换owner；processed payload回退entry旧值；Closed旧packet/return重放；
固定ledger、缺scope和budget=1 cursor。没有写implementation镜像的字段逐项复制测试。

## 3. 完整同步generator分母台账（不能按测试总数关闭）

| 当前阶段 | NEXT | SEND | THROW | CLOSE |
| --- | --- | --- | --- | --- |
| Created | 新Start/YIELD原端口；外部raw/source前提未证 | **OPEN**：None启动/非None拒绝未有本批完整新组合 | 新NoEntry helper N/R及PREENTRY三类路线；native/phase source仍条件 | **OPEN**：已有旧CreatedClose接口可复用，本批尚未贴新scope组合 |
| Running | **OPEN**：源guard/拒绝路线未新实例化 | **OPEN** | **OPEN** | **OPEN** |
| Suspended | **OPEN**：准确None来源未新实例化 | 新处理结果→SENT→body Return→真实adapter N/R；异常/源码适用条件未证 | 新处理packet→THROWN_PACKET→body/host异常；缺更完整捕获继续组合 | **OPEN**：GeneratorExit、非法yield/后续重试未新实例化 |
| Closed | 新helper结果→host异常，反旧packet | 新helper结果→host异常 | 新helper结果→host异常 | 新helper结果→host返回，反旧return |

表中“新”仅表示本批夹具已写，**尚未运行**，不是clause全部MATCHED、native phase证明或P2已通过。
Created SEND有None/非None子分母，CLOSE有合法返回/GeneratorExit/忽略yield/重试子分母，不能由一个格代替。
Running拒绝也不能伪造成NoEntry finished source。全16格及其必要子路径继续保留，root已确认不以首批case数宣布整门完成。

## 4. 初步产品源审发现（未运行复现）

1. RequestProcessing原实现只owned_use→raw_definition，contract.raw_use可改指本op已有Reference Use，
   而core保持合法；raw_definition返回None会误当external raw缺口。已发root，root接受先核RAW协议类型/role，
   本unit新增metadata-only反例。不是已执行失败。
2. NoEntry原route只看state_sites非空可complete；ordinary全READ可能误种F。
   root接受：须准确原WRITE/RW等真实post或INVOKE实际edge的State completion，READ-only保持
   `no_entry_transition_effect_unproved`且不种F；当前未构造旧实现运行反例，后续核实际改动。

等待root READY，首focus所有命令/原始失败/源hash存独占`connections/attempt001`，不覆盖其他owner的attempts。

## 5. 首次自有focused实际结果（不是整门验收）

root READY后只执行一次：

```text
bash artifacts/experiments/b1_call_operands/model_protocol_implementation/connections/attempt001/command.sh
source /home/zyf/miniconda3/etc/profile.d/conda.sh
conda activate lewm
PYTHONDONTWRITEBYTECODE=1 PYTHONPATH=. python -m pytest -q tests/unit/test_program_protocol_connections.py --junitxml=.../connections/attempt001/junit.xml
```

实际Python3.14.7；**27 PASS / 1 FAIL，pytest0.91s，wall1.53s，exit1**。
唯一失败为raw wrongtype诊断预期：实际已准确拒绝，code为`protocol_raw_operand`，
测试期待`protocol_raw_kind`/`protocol_result_owner`。root预先提示并接手统一发码，
本审查没有弱化反例或改产品，没有立即重跑。本次没有fixture构造/原core拒绝失败。

stdout/stderr/JUnit/returncode/环境/精确command及14文件source-before/after均原样保存；
两份source清单`cmp`无输出、exit0。首测产品validation SHA
`27f6e95b3619892d7692b90b8eebadab693b3e67451cf5e88b61a5e7456e9510`，
flow `ab694ca6d073c2c3d7470352a26aefe39e8b907498233b469ffc15c962d825cb`，
query `59dd1fa1cfef0c875753f9dd9b9036c6f22e8e898125c1a0aabb2e67b6e67139`。

```text
7e15b2955336a0f82e406189ae7ec55c6dc12dbfbb25f7c20660c2f8a50110e9 tests/fixtures/program_protocol_graphs.py
359c74a0265c2e7b3167b3a087c77eaebe76aed9cbaffb27b6f6d15101f778c0 tests/unit/test_program_protocol_connections.py
2e7dd22633c1af673a55a6e69e909d5b43fff796a671712828a4b3f27154d3de connections/attempt001/command.sh
```

首测27项通过包含旧visit循环反例、NoEntry两个selected edge分别仅本边F/T、PREENTRY不F、
三种generator路径、Closed四raw/两重放负例；这只计实际测试，不改§3缺口台账，不授native phase或P2全表PASS。

## 6. 首测后有限独立源码审查（SOURCE_OPEN，未新运行）

按root授权转入只读protocol_flow/validation/query和lifecycle patch，未改他人产品。
阅读期间root正在修诊断/接口，本节源审快照不是最终冻结hash或独立实测。

### R1：body Return adapter可换成处理器结果（必须拒绝的角色错接）

源审`protocol_validation.py`的OutcomeAdapter分支只在input为DriveResult时核RETURN/RAISE；
ContractResult未按固定rule限制来源角色。最小增量从已通过的`generator_protocol_program(target='value')`出发：

1. 将两条`GENERATOR_RETURN_TO_STOP_ITERATION`的input改为本图processing NORMAL的准确ContractResult；
2. 将该adapter原input Use的value改为`details['payload']`，它是已存在且支配adapter的Reference；
3. body Return、所有当前state、own result、INVOKE边与最终host RAISE保持真实，故core结构/def-use不因这两改动失效。

现copy会匹配该错误处理器结果；connection_errors只在缺DriveResult adapter且最终host RETURN时拒绝，
本图两个终端都是host RAISE，不能兜住。必须按rule要求准确body RETURN/对应payload source，
不能用CHECK_SEND或任意helper同型result代替。本项为明确源推断机制，**本审查未运行该增量**，已一次合并发root。

### R2：NoEntry transition为真实BodyDrive，及坏state index继续执行后的崩溃风险

从已通过的generator Start图，只新增CREATED_THROW OperationSite scope和NoEntry row：
outer.operation为现Drive；instance/raw均该Drive已有owned Uses；selected_input为StaticGap；
selected_edge为该Drive edge0；terminal为其已存在landing host终端。

`no_entry_route`从selected edge目标开始走，未检查transition本身是BodyDrive；state_sites空时会只保gap，
却未拒绝“无用户入口transition就是已知Drive”的类型矛盾。若再给`ExistingAccess(drive,0)`，
`_state_sites`先记访问索引错误却未跳过该row；后route的ordinary write检查直接索引空accesses[0]，
会发生未捕获IndexError，而不是稳定诊断。必须拒真实Drive作NoEntry source，并在已知state-site错误后安全停止该row。
这同样是**未运行的源推断**，不是声称已复现崩溃；已发root决定最小回归与修复。

### 已核的有限正面事实和保守边界

- flow按程序点本次producer重执行reset旧copy；真实edge的actual→formal同时重命名，CompletionResult/ResumeInput非copy；
  首测loop反例已实际拒绝，未按静态root集合相等放过。
- lifecycle的新增edge_seeds在E/F边改名之前应用，T第二阶段同边种源；非selected边没有新来源，首测N/R正反已验证。
- session_flow的body_only白名单仍仅旧BodyOutcomeCommit/NoBodyFinish；未将NoEntry整op白名单，
  unknown/callback/INVOKE保原P kills；不会因终结历史F成立而声称当前session未变。
- query保固定profile clauses及28组原编号，budget耗尽仍留NOT_CHECKED分母/cursor，缺scope保global inventory gap；
  preparation另列，authority false。完整site inventory/native applicability仍未证。

source快照（只读事实，非所有这些版本已测试）：

```text
757467d8efa6b7308ec1554969265871db1bbaec10e8d6a0225ccb40e59b9dd4 protocol_flow.py
ea8fb1602aedb23ab3b2f7d6fd746cc1694845805a0e3a7a96e3466bc3543c87 protocol_validation.py（本节机制阅读）
4f8b7231b5970c661b595a7f4aa66e0a9cbc096b95e90f4ca33889d86356a5f5 protocol_query.py（初读）
9fc23f943b8389764876856579db2e82797b2fb375a8c9ecc701b785b094d7f7 lifecycle_flow.py
13e90d83f74bd46281a678c778c559ad1d6d52d3d5722137be38848f853a7387 session_flow.py
153c309f0cd32a6b6b719f0266dbc68209a107c9746bb88c2463194d7d650dd7 lifecycle_analysis.py
```

等待root对R1/R2具体修复及最终source hash，当前不授产品PASS，不新增运行或扩大协议范围。

## 7. R1/R2修后独立回归与有限closure

root确认修复后，授权将具体mutation落实为自有unit；没有回退旧源码来制造失败：

- R1四项：当前helper ContractResult代body Return；input选尾随state槽；output选自身state槽；
  给旧generic host RETURN贴GENERATOR_RETURN_TO_STOP_ITERATION标签。第一项明确清新metadata再require_valid，
  证明其余core/def-use/当前状态仍合法；后三项是metadata-only mutation或旧已验证D1图。
- R2两项：真实BodyDrive被声明为NoEntry transition，state_sites空或坏ExistingAccess0；
  两者均须稳定protocol_no_entry_edge，而非漏拒或崩溃。

root READY并暂停编辑后，唯一后续自有whole-file执行：

```text
bash artifacts/experiments/b1_call_operands/model_protocol_implementation/connections/attempt002/command.sh
```

实际lewm Python3.14.7，**34 PASS / 0.95s，wall1.60s，exit0**。
首attempt001的27P1F完整保留；rawtype只统一产品发码protocol_raw_kind，没有降低反例断言。
attempt002保存独立命令、stdout/stderr、JUnit、returncode/环境/时间和14文件前后hash；`cmp`前后清单一致、exit0。
不得将R1/R2说成旧实现已实测失败：本批证据是**源发现→root修复→新真实IR负例修后通过**。

### 源码关闭依据

最终所核`protocol_validation.py`：

- no_entry_route:95–97先拒真实Drive/其block的Drive，再安全核state sites；坏索引不继续越界。
- :208–215核RAW类型且known raw kind相符；Reference输入不被当external RAW。
- :283–336固定body adapter source为准确DriveResult/本scope、payload槽0与正确非state角色，
  正常/异常结果不能借state，RAISE原结果须packet，hostterminal必须RAISE。
  因而不是贴一个adapter标签就允许旧bodyReturn→hostReturn。
- NoEntry普通READ-only不具备关闭写，保no_entry_transition_effect_unproved，不能种F；
  此条在本轮做源码核对，未新增ordinary READ-only专门执行case。
- lifecycle_flow的E/F边seed和T边source使用相同edge key，先种该边再同时重命名，未污染另一边。
  session_flow未新增NoEntry白名单，宽helper/INVOKE仍kill P；本批NoEntry unit没有新SessionUpdate组合，
  所以P kills只记为源码核对，不冒本批动态组合实测。

query固定clauses与bindings：缺一个已知INVOKE edge row保MISSING；共享预算不足不删profile分母，
源scope inventory未知始终独立gap，source_inventory_complete/protocol_implementation_complete均false。
本审查没有把该ledger当完备源码枚举，没有将old/generic条件夹具当native映射证明。

```text
9dd2832716269f86ce9f98b73dea6a634caa084a18d0f974ccaec401322dcacb scar/ir/program/protocols.py
e72627e8d6b2ab215e057c29f8f2774e8484da16b26960af6d6d3d99a3f35064 scar/ir/program/protocol_rules.py
3410733f931ba9f15340ea4af30f7f5b92860258a00d94ad78d60250b455c4bd scar/ir/program/protocol_flow.py
72f7ec09256c0c46496ee6751da33a71e8055354703542d6946ffdb2e402ca3e scar/ir/program/protocol_validation.py
15c3e4dbfb80a6732fc391b9760efb505969d5b79073db3dcd6ab23a244005b0 scar/ir/program/protocol_query.py
2546e57c7303e6ff97c65a51d9cc472401acaf4d8917eb36af27e0706ec1363c scar/ir/program/model.py
c65ff8590068bed8c8c0bd8fbbbe44a33e4bfc2afce1ae218b936a90207a465e scar/ir/program/validation.py
94139fe8dda97b52d98aaa62f927871af2c98618786a822b673550a549ca7e97 scar/ir/program/queries.py
9fc23f943b8389764876856579db2e82797b2fb375a8c9ecc701b785b094d7f7 scar/ir/program/lifecycle_flow.py
13e90d83f74bd46281a678c778c559ad1d6d52d3d5722137be38848f853a7387 scar/ir/program/session_flow.py
153c309f0cd32a6b6b719f0266dbc68209a107c9746bb88c2463194d7d650dd7 scar/ir/program/lifecycle_analysis.py
b96e989a611a518630e2c33bbf61b5f69d4cc015b54166d27f78a6486482e0fc scar/ir/program/session_release_validation.py
7e15b2955336a0f82e406189ae7ec55c6dc12dbfbb25f7c20660c2f8a50110e9 tests/fixtures/program_protocol_graphs.py
2c831066f5c7072a1c4ab373ec526e7b38d37d0f0a4ee422c093f5f6d9b6d4ad tests/unit/test_program_protocol_connections.py
```

**有界结论：R1/R2及本批准确来源/consumer/selected-edge接线在上述冻结快照上关闭，PASS_WITH_SCOPE。**
只覆盖本批声明接口基础与列明正反例；§3完整16格及子分母继续OPEN，不能据34P宣称P2整门。
P3 O发生关联、P4其他家族/delegate/await/cancel、P5完整公共面与M0–M2原分母没有被该结论替代。
没有新native见证/来源适用证明/运行身份/自动建图/变换授权，没有full/组件/LeWM/GPU或git操作。
自有fixture/unit到此冻结，不再扩展可选测试；等待root统一组件与后续明确授权。
