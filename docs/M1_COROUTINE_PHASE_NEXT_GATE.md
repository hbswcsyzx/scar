# 原F14/F16：本门之后仍需连接什么

2026-10-19，只读审查所得；不是测试结果或关账。原16组/P5/M2分母不变。

## F14：native coroutine的同一个B

已有native零/两cut及self无wrapper路径保留。下一有限组约五个例子：

1. 真实Running重入：B从准确Create到AWAIT，下一SEND的operand0传同一B
   handle，经caller→normalizer→BodyResume SENT_VALUE到B内部inner driver。
   用原copy证明同B，不用同body Region或有条件的holder heap-read代替。
2. 同B完成后reuse：零cut完成→原completion/extractor，独立forward保留B；
   之后IS_CLOSED READ→自身bool→BRANCH→拒绝helper。状态取前次真实full slots，
   不能重新Create B。
3. THROW与CLOSE分别连接当前normalizer ownN packet→THROWN_PACKET，以及
   ownR packet→自己的host RAISE与完整状态。不能借generator测试自动验native。
4. callback后的历史predicate仍能控制历史边，但其旧read不支持当前gate资格。

可复用 `_guard`、generator reentry的原inner call/handler/context RW结构及
native两cut/full-final fixture；必须保COROUTINE_BODY_V1与AWAIT。现no_entry
seeds只处理真实INITIAL_THROW条款，不可用它冒充Running/Closed拒绝。潜在CFG
中存在snapshot不相容gate应保条件gap，不能把过近似路径全局判成非法程序。

## F16：状态内容的跨调用关系

“首Drive的SessionUpdate COMPLETE post已成立”“当前SSA被传到下次read”与
“下次read的bool应为True”是三件不同的事。现session查询明确不授权post跨
任意后续调用持续生效，局部request_state_view也不搜索前次SessionUpdate。
完整供采链可以检查实际原端口，但不能凭其手工选择边推导native phase。

下一步沿原SessionUpdate、CallActivation、state传递和当前READ建立派生收据：
准确R/B关联、post真正落在NORMAL、post到read之间每个影响该状态的操作、
跨callee及callback失效、当前read对应的状态版本。完整性未证时保gap；查询
关系不需再存一套影子状态。接通后再审F16原完整验收条款。

建模方式应复用StateLocation/address、footprint、alias与原Contract的前/后
状态端口：一个post事实必须携带subject的独立来源和适用状态快照；中间操作
的读写效果决定它能否保持。不能因为SSA端口可达，就断言某个字段内容未变。
未描述的helper效果会阻断内容传播，需明确指出缺少的frame/preservation
条件，而不是靠“同producer”或时间上最近一次选择事实。

仍有两项独立原义务：R1/R2竞争同一B时各自Create/L与拒绝来源，以及首次
ASEND的R.initial、B.Created、nonNone SEND联合分支/参数。不能把IS_INITIAL_STEP
当作B.Created，也不能只有CHECK_INITIAL_ASEND enum。

F18/F19/F20/F22/F24/X25/X26/X27继续按各自原义务；之后做P4组件/冻结全仓、
P5和M2原113构造/196字段总核，完成建模阶段再解释模型。M3自动lowering、M4
实际采集对应及LeWM优化/新加速比未在本门建立。
