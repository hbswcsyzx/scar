# C1/B1：跨层参数来源的实现与验收计划

日期：2026-10-15，2026-10-16续。状态：**Implementing；R1已验收，B1采集、
有界读取和路线/公开查询已实现，联合冻结验收尚未完成**。
本文件细化 [调用与环境总计划](N2_CALL_BINDING_PLAN.md)，不替代 E0/E1、C2、循环
和状态来源门。不新增 detector/backend，不手工补 workload 图。
当前实现与失败复查见 [B1执行记录](N2_B1_IMPLEMENTATION.md)，原始协议见
[operand证据协议](N2_OPERAND_PROTOCOL.md)。

## 1. 交付必须是能查询的连接

输入原始 Python 命令、项目范围和预算，自动采集、源码核验、inventory、绑定和查询。
最终查询须穿过 caller 的具体 Use、实际 callee 形参和返回，再回到同一次调用结果。
只添加记录、再加一层 UNKNOWN、按引用相同连线，均不算 B1 通过。

第一条规则支持原生 FunctionType、同步调用、显式提供的全部固定位置参数。
Name callee 可来自 local/global/builtin；actual 首批为局部 Name。
未消费 defaults 时不因函数存在默认值而拒绝；消费 default、bound method、partial、
keyword/packing 和 suspended code 后续逐条实现，当前必须有具体边界。

## 2. 与四类结构实体的对应

| 对象 | 模型中的位置 | 连接含义 |
| --- | --- | --- |
| load | Operation 的一次 occurrence | 从具体 slot/状态读取引用；pre-load 观察不是解释器值栈 |
| actual | caller call 的有序 Use | 同对象的两个位置仍是两个 occurrence/Use |
| formal | callee Region 的引用 Value 端口 | 经绑定规则对应 actual，不等于内容/LogicalVersion 已恒定 |
| 环境 | StateLocation selector 与状态版本 | 不从相同 code 推出 globals/defaults/closure 相同 |
| attempt/entry/completion | 执行证据与模板 Region 的实例对应 | 与源码词法包含分开；不用时间相近补父调用 |
| return/result | completion payload 到 caller normal-result Value | 必须属于同一 attempt；异常不能接普通结果 |

采集记录、proof 条件和对应关系不增加第五种顶层结构节点。相同源码 Region 可作为
模板；不同 invocation 的端口对应独立，不能把它们合成同一次执行或相同逻辑数据。

## 3. 最小生产证据协议

| 记录 | 必需字段 |
| --- | --- |
| LoadOccurrence | PID/TID、caller invocation、raw anchor、pycode-v2、offset、fused suboperand、namespace/slot、观察引用、原始 callable shape |
| CallAttempt | caller 与独立 attempt 序号、CALL site、callee occurrence、有序 actual occurrences、dispatch 时 callable/current code |
| EntryHandshake | 唯一 callee invocation、真实直接父 frame、事件区间、当前 code/layout 对应 |
| ArgumentRoute | attempt、actual index、caller call/UseID、load occurrence、callee definition/Region/formal slot/ValueID、规则版本、条件 |
| CompletionRoute | 同一 entry 的正常完成、return payload、唯一 caller CALL normal-result ValueID |

规则输入是 occurrence 与位置。weak token 相等只能检查矛盾，不能选择实际来源。
非 weakref 对象的 snapshot token 不升级成跨事件身份；条件路由连接两个独立观察，
不把它们合成已观测的同对象组。禁止保存 Tensor 数值或长期持有应用对象。

## 4. 动态指令路径与 dispatch

1. 从当前源码/完整 code 产生每个 call 的有限字节码计划，源 actual index 接回 UseID。
2. 对每个 attempt 独立重放实际指令与栈来源；不按 span/name 取最近一次 load。
3. 纯 LOAD/LOAD fused 指令保留 offset+suboperand 顺序；必须支持同次 `leaf(x, x)`。
   未支持的 STORE/LOAD 等组合停边，不能猜栈效果。
4. pre-load shape 只说明当时观察到的 callee。绑定用 CALL 当前状态与真实 entry
   code/layout；callee 在实参求值期间重绑或换 code，不能沿用旧 layout。
5. 握手消费唯一 pending attempt；递归、wrapper、finalizer 或后续同 code 调用不能
   补配。没有入口仅说明未观察到 body，不能擅自判定绑定失败或伪造 body raise。

全局/builtin 采样使用有界 exact-dict items 遍历，仅比较 exact-str key；拒绝自定义
key、dict 子类、扫描超限或变化。不得用 `name in mapping`、`mapping[name]` 或
`mapping.get` 探测任意 namespace，这些查找可能额外调用用户 key 的 `__eq__`。
局部采样按已核验的 LOAD_FAST slot，不重新猜测 Python 名称解析规则。

禁止重新求值目标表达式、descriptor、repr 或用户容器/签名协议。frame/function 的
公共读取本身可触发 audit hook，故不承诺绝对无观察干预。相关条件必须显式保留。

## 5. hook 与完整性

独立进程探针已确认本机 CPython 3.14.7：

| 初始化次序 | INSTRUCTION | CALL |
| --- | --- | --- |
| monitor only | 5 | 1 |
| monitor 后 profile | 0 | 1 |
| profile 后 monitor | 5 | 1 |

替换 INSTRUCTION callback 时，tool/mask/profile 的表面快照可以不变，原 observer
仍丢事件。关闭再恢复 local mask 也不能仅靠最终快照发现。生产需 hook epoch、
可见 audit 变化、配置见证及逐 required occurrence 完整性；不能只查询开关。

追加 lazy 前置已经实测：两个独立进程在 hooks 后动态 import 两文件，分别在
PY_START 内和 profile call 内首次启用 local events；两方案各收到38 INSTRUCTION/
4 CALL，5个code的完整post-RESUME offset与反汇编一致，首LOAD全部收到。
实际次序为PROFILE_CALL→PY_START→first LOAD，真实recorder均0drop/error/open。
这允许设计与现有profile collector组合的原型，但生产安装/恢复和缺口仍需独立门验收。

官方 [monitoring 回调协议](https://docs.python.org/3.14/library/sys.monitoring.html#callback-function-arguments)
给 CALL 的是 callable/arg0；INSTRUCTION 在指令执行前触发，未提供完整值栈。
在线文档当前为 3.14.8，本机实验版本为 3.14.7，二者不混作已测兼容性保证。

## 6. 公开查询的必过正例

两文件程序自动采集与构图：

```python
# helper.py
def choose(left, right):
    return left

def relay(a, b):
    selected = choose(a, b)
    return selected

# entry.py
from helper import relay

def run(x, y):
    first = relay(x, y)
    second = relay(y, x)
    return first
```

distinct 和 `run(shared, shared)` 都必须查询到：

```text
first 的 call result → relay return → choose return/formal
→ 此次 actual occurrence → relay formal → 此次 caller actual → run.x
```

不能散连到 run.y 或第二次调用；choose 的两个 formal 要显示不同 actual occurrence。
这仍是带条件的引用来源链，不证明内容/状态/效果等价或变换合法。

## 7. 验收门与阻断反例

| 顺序 | 交付 | 必须阻断 |
| --- | --- | --- |
| 前置 R1 | 自动恢复已记录的编译上下文，保留历史匹配 profile | future 继承导致假 mismatch；按文件名/行号补匹配；旧报告静默改变 |
| B0 | fresh-process startup/lazy hook 证据、预算与干预边界 | 首次 LOAD 丢失；callback 被换但 mask 未变；无事件被当作无操作 |
| B1.capture | 有界真实 occurrences/attempt/entry，metadata 与 raw 锚点 | 缺事件、截断、错父 invocation、过期 attempt、跨 PID 补配 |
| B1.routes | 两文件正例完整穿过实际调用和返回的公开查询 | 同 ref 多 actual 选错；递归、两个调用点串线；旧 layout/源码补目标 |
| B1.replay | 新协议版本、独立预算、当前 source/raw 全重放 | 改 offset/suboperand/index/attempt/源/code/hash/预算仍通过 |

额外反例：Name-bound method；receiver/default/actual 同对象；callee load 后重绑和换
code；global 恶意 key；slot/hook 干预；pre-body 与 body 失败；异常接 normal result。

新 capture/report 明确版本分派，旧 v1 原算法重放。消费当前 inventory v6，保持
BOUND_FRAME/source-program v2 含义；本门不暗加环境端口或跨调用 world 等价。

## 8. 后续结构支持与真实压力测试

C1/C2 后必须补源码到核心 CFG 的循环/集合/写入支持。当前 Source CFG 分类了 loop，
core lowerer 仍拒绝 for/while、复合赋值、切片写和多种集合表达式。不能用源码分类
数量代表核心可分析覆盖。

循环放在函数 Region 内：preheader→header 的 block arguments 携带引用/状态，
body/latch 回 header；break 绕过 loop-else，continue 回 latch，零次与异常有明确出口。
for 的迭代步骤区分 item、正常耗尽和其他异常。需要 typed loop interface，不能只用
字符串 label 猜 backedge；它是 Region 的控制结构，不是新增顶层实体。

LeWM 仅作未修改的压力测试：它的 CEM、rollout、policy 组合需要动态方法/实例调用、
循环、字典 alias、RNG、callback、写入与异常依赖。源码已有 goal embedding 缓存
分支，必须根据实际分支和状态判断，不能见重复 module 名就认定重复编码。

先接通具体参数和返回，再补这些结构，最后从观察根反查完整依赖与合法提升位置。
没有新 backend、LeWM 特判或加速比结论。

前置实验：`artifacts/experiments/c1_operand_preflight/independent/`，复制前后逐文件
SHA 已核对；8 独立进程 hook trial、154 event/15 attempt/9 条条件路线的旧探针复跑，
以及 audit 回调实测均保留。它们不是生产 B1 验收。
