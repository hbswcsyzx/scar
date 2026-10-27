# P4：通用异常匹配的建模与连接计划

2026-10-18。基线 `8f08bda1d192f7f9b778c06bb51d6509e17fc8ca`。
上一轮为实际进展：返回后下传、缺来源分母修复、811 affected focused、WIP 推送。
本计划继续 M0–M2；原 F12–F24/X25–X27 共 16 组分母不变，仍全部 OPEN。

## 1. 源码审查与建模决定

Observed：当前只有 structured lowering 的 MATCH_STOP_ITERATION 专用 primitive。
AdmissionPredicate 约束普通 callback-free READ/bool，不能承担一般 matcher 的
INVOKE/RAISE；ExceptionPacketDefinition 只配对原 exception/traceback，不声明类别。
lookup RAISE 因而保 method_lookup_exception_category_unproved 是正确的未知。

Operation / Value / StateLocation / Region / Resource 类型不变。新增的是原操作
的解释附件 ProgramGraph.exception_matches，不建立新 producer、实际参数、状态
链或协议 scope。普通 except 不需要伪造 delegation scope。

```text
独立 exception/packet source → 原 matcher input Use
独立 handler source → 原 handler Use（若真实存在）
     + 原 state inputs
     → matcher 原 NORMAL bool → 原 BRANCH → true / false 原路径
     → matcher 原 RAISE packet + 原完成状态 → 原消费者
```

不能把 handler 表达式求值、类型匹配、handled-context 安装、handler body、清理
绑定当成一个无效应节点。[Python 3.14 语言参考](https://docs.python.org/3.14/reference/compound_stmts.html#except-clause)
规定 handler 表达式求值可抛新异常，匹配使用异常类及其非虚基类；except* 的
拆分行为不同。此附件表示普通 except 匹配，不用它冒充 except*。

## 2. 最小记录

- BuiltinExceptionCategory：闭合 builtin 类别解释，不是运行时类身份。
- FixedBuiltinHandler(category, applicability)：真实固定 intrinsic 不虚增 handler Use。
- ExceptionHandlerOperand(use, source, interpretation)：真实动态类/tuple 必须保原
  Reference Use 和独立 expected source；interpretation 是固定 builtin 的条件解释
  或 StaticProtocolGap，不能按变量名猜 builtin。
- ExceptionMatcher(operation, input_use, source, handler, normal_result, raise_result,
  branch, state_sites)：natural key 为原 operation；input 可为整体 packet 或
  exception Reference；来源角色必须相容。result 是原准确 slot，state_sites
  是原 ExistingAccess / InvokeStateOperand，不另存 SSA。

ordinary matcher 只能有自身普通 bool result，无 RAISE；保明确 callback-free、
完整 effects 和实际 READ。INVOKE 按原完成的非空 N/R subset：NORMAL 若存在
必须自身 bool + 真实 branch；only-RAISE 不造 bool/N 边，branch=None。已存在
的任何完成不得通过把字段置 None 从分母删除。输入、handler 不得是虚构 edge
forward Use；normal_result/raise_result 必须选自身准确 kind/slot。

## 3. 检查与报告

图结构验证检查 owned Uses、角色、端口归属/类型、N/R 分母、原 state sites 和
真实 branch。bounded query 复用已验证 ProgramIndex、ConnectionContext 和单一
预算：逐完整 input tuple 核独立来源、caller/CFG correlation、bool current copy，
并报告 matcher 的历史读 snapshot 与原分支、N/R 状态端口和所有原消费者。
历史 bool 跨 callback 仍可有效；不能把旧 snapshot 当永久当前准入许可。

true/false 原边始终保留；matcher RAISE 使用自身新包，不能冒作源包。未知
occurrence、handler/native/source applicability、missing route 或预算截断保
具体 gap/cursor，不把未知变成 false 或删除义务。

method lookup RAISE 的集成先从既有独立 consumer ledger 找真正的 matcher Use，
再核 matcher 独立 source 是否为该 lookup 原 RAISE。Reference 输入若没有原
packet-component projection 依据则保具体缺口，不造 packet 实参。结构连接和
handler 类别/后续 fallback 分开；接通普通 matcher 不能自动吞 lookup 异常。

## 4. 后续 fallback 的固定义务（本轮不删除）

E0=独立原注入包；EL=lookup 自身 RAISE；EM=matcher 自身 RAISE。
依据 [PEP 380](https://peps.python.org/pep-0380/#formal-semantics)：需要核本次
EL 对 AttributeError 的匹配，正分支才允许对应 THROW/CLOSE 缺方法路径；负
分支继续 EL，matcher RAISE 继续 EM。E0 来源和当前 C1/context/state 必须独立。
NEXT/SEND 不借用 THROW/CLOSE fallback；方法调用自身 RAISE 也不同于 lookup。
generic matcher 不携带这些 delegation 业务字段，缺后续合同仍保明确未决义务。

## 5. 自主验收与版本

| 门 | 必需证据 |
| --- | --- |
| D | 三路只读审查，固定/动态 handler、N/R subset、真实 Reference/packet 输入决定 |
| R0 | 原合法 matcher 链的查询缺口首红，不以未定义新 API 的错误冒充 |
| M | ordinary / N+R / only-R；packet/Reference；动态 handler；准确 bool/branch/state；错接、缺失、预算 |
| L | lookup RAISE→真实 matcher consumer；普通匹配不授缺方法 fallback；删除附件不删除原 lookup 义务 |
| W | Program21 新字段/record，独立旧20 encoder golden；旧1–20字节、降级/假升级拒绝；Execution8不变 |
| V | 三路只读复审、作者冻结、统一受影响 focused；旧811与原夹具/证据守恒 |
| A | 报告、保护 checkout、archive-only 核对与独立 WIP commit/push |

只做必要定向，串行测试；留首败及修后证据。原 16 组全部就绪前不运行组件/full。
新证据目录 model_exception_matches/。不新增 detector/backend，不运行重型 LeWM
或报告新加速。完整模型及自动 LeWM 恢复、类别/fallback 闭环仍需后续原义务，
不能把本轮的结构连接当作这些工作已完成。
