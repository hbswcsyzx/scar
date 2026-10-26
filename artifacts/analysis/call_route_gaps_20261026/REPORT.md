# 当前 LeWM 调用连接：完整问题分母审计

2026-10-26。**Observed / Verified：保存产物审计；没有重跑 LeWM 或改变路由资格。**

Root session83477 actual exit0。逐一核对普通 partition manifest 声明的全部
`routing.issues` chunk：stored SHA、decoded SHA、字节和行数均一致。100,523 条
原问题全部分类；实际累计输入50,411,252B，限额96MB，未读取 raw frame/operand。
精确来源、各组原 anchor 样本和输入清单在 `RESULT.json`，执行源码为 `run.py`。

| 真实问题 | 原条数 | 已知含义 |
|---|---:|---|
| 没有唯一真实 entry handshake | 96,481 | 无法使用当前 exact-Python-function 入口绑定规则；不能一概认定为漏掉了 Python 调用。 |
| 仅支持 Name callee + 显式局部 Name 实参 | 2,656 | 已越过 handshake/source 检查，但被现有引用观测路由的狭窄 AST 条件拒绝。 |
| 没有唯一 direct source/core call 和双方 body | 1,329 | 当前恢复/接线不足；不能用祖先上下文代替直接调用。 |
| CALL instruction window 缺少编译见证 | 57 | source 已匹配，但缺少该规则所需的完整 CodeWitness。 |

原 pinned operand metadata 为100,550 attempts、4,069 handshakes。它与原报告
27 条已接受 argument/completion call routes 精确构成漏斗：

```text
100550 attempts
  - 96481 无唯一 handshake
= 4069
  - 2656 Name 限制
  - 1329 source/core body 缺口
  - 57 CodeWitness 缺口
= 27 已接受调用
```

metadata 的精确原件及 Git 恢复来源另存；这次额外1963B读取独立于上述 issue
扫描计量。旧运行使用 `CPYTHON_CALL_WINDOWS_V1`；不能用当前 collector 字节替代
当时执行字节的证明。无 dropped events 的声明也不证明所有程序操作均已采集。

## 对模型连接的结论

**Inferred：** 当前把“调用传递的数据依赖”过度依赖于“观测到每个实参的局部名称
引用”。程序图中的源实参 Use→formal port，和捕获引用之间的身份对应，是两种
不同关系。前者可以依赖已验证的 Python 调用规则、真实 dispatch/entry、源码/编译
见证和规范端口；不必先保存中间 Tensor 数值，也不必把表达式改写成局部名称。

这不是允许删去原引用规则的 guard。即使语言绑定成立，值内容、ObjectID、状态、
默认参数、receiver、装饰器、packing、effects、cleanup 和 ready 仍需各自依据。
引用规则原27条及其边界保持原义；新的语言绑定不能冒充旧 ReferenceIdentityRoute。

## 下一项（Proposed，尚未实现）

1. 复用已有 `CandidateBinding`、有序 CallArgument/Use、FunctionSignature/FormalPort
   和真实 direct handshake，表达有条件的源端口绑定，保留原 graph namespace。
2. 首个有限规则处理 exact function 的显式位置实参，允许一般表达式；检查 CALL
   指令/arity/source position、双方规范 body 与参数布局，不能猜 receiver/default。
3. 通过普通 fresh linker 的同一输入会话生成；不从本审计 JSON 恢复验证权威。
4. 用同一真实 LeWM 原采集验收新增事实及反例，再接通用建模入口。未执行之前
   不声称2656条全部可接，不改变 source858/6882 正式指针。

完整第一阶段 **OPEN**。这份报告没有新增 detector/backend、变换或加速结论。
