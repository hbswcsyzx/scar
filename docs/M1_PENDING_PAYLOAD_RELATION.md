# PendingPayload：投影关系与实际发生证据

2026-10-19；[来源到终点计划](M1_AWAIT_SOURCE_TO_TERMINAL_PLAN.md)的关系细化。
这是本轮待实现/验证的查询合同，不新增 Program/Execution 规范记录。

## 原实体与关系

```text
constructor OperationOccurrence c
  payload UseOccurrence u → ValueOccurrence x
  result ValueOccurrence p : PENDING_COMPLETION
       ↓ 原 CFG / SavedInput / 准确调用绑定（如该类型允许）
dispatch OperationOccurrence d
  selector UseOccurrence s → token p'
  selected original port k
       ↓ 原 edge.arguments[i] = PendingPayload()
landing ValueOccurrence y
```

原 `PendingCompletionDefinition` 声明 constructor 的已求值 payload Use 与 port。
token p/p'、payload x 和投影 y 是不同端点；不能加入 `p == x` 的普通 copy 边。
可派生的关系是 `x → y`，其证据包含 c/u、s 的本次 token ancestry、选中 transfer
与 port k。它引用原 producer，不生成新值或挑选另一个 occurrence。

在 Reference 情形，投影保对象引用，不冻结该对象内容或异常的可变属性；在
RAISE 情形保准确 whole packet，不把其中 exception 与 whole packet 作 alias。
这不证明 LogicalVersion、数值相同、native 执行对应、无副作用或可移除 cleanup。
world/context/保存的 handled context 分别由原状态/恢复端口连接，不能从 payload
相等推导它们相等。

## 必需证据与判断

1. y 必须是实际 BlockVisit 的原 formal。该 visit 有准确 incoming transfer，
   transfer 的实际原 argument 是 PendingPayload，当前 operation 是原 dispatch。
2. 原 dispatch selector 的本次 Use 被捕获，值为 token。仅沿已验证原 copy recipes
   反向走到这个 token 的实际 constructor result；循环、缺口或未捕获 token 保未知。
3. root 的规范 ValueID 对应唯一原 PendingCompletionDefinition，实际 origin 是
   同一个原 constructor 的准确 OperationOccurrence。不得按 expected x、同 code、
   同类型、同 ObjectID、唯一可见 site 或另一实例选择 constructor。
4. 实际选中 successor.port 必须等于该 definition.port。已知不相符是端口冲突；
   缺 selector/ancestry 不足以得出不相符。definition.payload 的原 Use 必须属于该
   constructor，且该 occurrence 的原 UseOccurrence 和 payload value 均被捕获。
5. 派生 recipe `source=x.id,target=y.id,rule=ORIGINAL_PENDING_PAYLOAD` 只表示上述
   原端口投影。support 保原 definition、constructor、transfer、selector、token
   recipes 和实际 payload Use。沿证据链逐项计费；截断不能保 True。

查询在同一 shared budget 内缓存原目标 y 的 receipt，查询之间不共享外部身份
判断或未计费的成功路径。不免费为所有 dispatch/constructor 做跨图 join。
一次准备只能建原 definitions、原边与 formal 位置索引，需报告其准备开销。

## 查询字段

原 composition argument 仍保 `source=None`（PendingPayload 没有直接原 Use）、
`projection.pending` 与 `projection.port`。新增 `projection.payload`：

```text
definition                  原 PendingCompletionDefinition 或 None
constructor                 本次 OperationOccurrence 或 None
selector                    本次 UseOccurrence 或 None
token_path                  实际 token 的原 copy recipe tuple
payload_use / payload_value 本次 constructor 的原 payload 端点或 None
target_value                本次投影 formal 或 None
binding                     match / gaps / support
status / gaps               DECLARED / PARTIAL / CONTRADICTED
source_runtime_verified = runtime_identity_verified = False
value_identity_verified = transformation_authorized = False
```

普通 ancestor 比较可使用该 recipe 继续追本次原 payload；投影 receipt 保留其结构
原因，不能偷偷把 canonical copy graph 改成 token/payload equivalence graph。
缺 capture 的 receipt 不能借 sibling 的好 receipt。相同 port 多次 constructor
也必须由实际 selector ancestry 区分，不以“只有一个类型”代替。

## 与原验收的关系

独立 C1 完整链测试先暴露缺口，root 再接公共查询。Return/Replace 的真实 terminal
各接其正确 await 后继，缺 payload Use / dispatch / Resume 的反例保原分母。
现有 PendingPayload/cleanup/composition 测试原字节保留。最终证据以新的 source
fingerprint、原1572 case身份守恒和实际 JUnit 为准；本合同不自行授通过。
