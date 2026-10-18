# P4 通用调用返回连接：实施与自主验收

2026-10-18，起点 `b73d8c5d2150decf4787e6c3f4225d47471ff5f5`。
这是原 P4 的连接修复，不新增 detector/backend，不改变固定 16 组分母。
完整 M0–M2 建模尚未完成；本轮不运行重型 LeWM 或报告加速。

## 1. 审查发现与模型边界

现有 input_origins 能沿实参进入 entry formal，却在已知 callee 的返回结果处停止。
ConnectionContext 同 region 的 fresh-copy 也未将 callee 原 RETURN/RAISE 接回结果。
这影响普通 Python 多层函数、packet/helper 以及状态输出，不能靠更多协议标签弥补。

仍以原 Operation / Value / StateLocation / Region / Resource 建模：

```text
caller current Value → exact call actual ordinal → callee entry formal
  → original CFG / ordered Use → actual RETURN or RAISE slot
  → that call's result / selected completion → caller consumer
```

不新增 producer、状态 SSA、wire family 或执行历史。查询派生的复制关系仅说明
供应静态图中的原端口连接，不证明运行时对象/内容相同、native 实现、纯性或可变换。
Reference 复制不延续旧 StateVersion 的有效性。同 Location 不等于同版本。

## 2. 固定实现决定

1. 在原 fresh-copy 引擎提供默认空的调用 transfer hook；只有 ConnectionContext
   开启返回分析。历史 ProtocolFlow、input_origins 配方和 request_inputs 上下文
   格式不变，避免把并列调用误写成嵌套调用。
2. 每个调用分别将当前复制集合对应的全部 actual ordinal 同时映射 entry formals。
   summary 只缓存 callee-local seeds/mode/guard，不缓存另一 caller 的 frame。
3. 逐原 exit kind + slot 收集真实 terminal Uses。CALL 只接 NORMAL；INVOKE 按
   实际 successor.kind 和 CompletionResult.index 接入 landing，而不是按边或 formal 顺序。
4. 必须覆盖所有相关 terminal。全 True 才 must True；混合、缺 terminal、未决递归、
   预算截断均不能给出 must True。未知不能转换成空集合再被解释成已证 False。
   False 只表示不满足原 must-copy 关系，不表示运行时数值必不同。
5. callee summary 用迭代依赖工作表；active recursion 保具体 gap，不能从一个 base
   分支提前发布成功。不靠提高 Python recursion limit。
6. 原 source 求值重执行的 reset 优先于调用 hook；旧返回结果和 loop carrier 不能
   因同 ValueID 复活。保持原同时 CFG rename、不可达前驱和逐 Use 规则。
7. callee 内 source 导出时保留准确 caller / callee / kind / slot / edge frame，随后
   以该实际 caller port 重新检查 freshness。静态信息不足以选择调用 occurrence 时
   保未知，不能把不同调用的输入与输出拼接。
8. guard 只约束所属原 region。多 caller 的 callee 内未加调用限定的 guard 不可
   冒充某次访问；报告歧义。flow/summary cache 包含适用的 guard 上下文。
9. 新薄入口 ProgramIndex.source_binding(expected, actual: OwnedUse, guard, budget)
   复用准备过的 index 和单一共享预算，expected 限单槽。报告 routes/gaps/cursor、
   准备量和费用；runtime/native/transformation 权限均为 False。

## 3. 自主验收节点

| 节点 | 证据 / 验收条件 |
| --- | --- |
| D | 本计划、三路只读审查；原接口/旧证据/保护仓库基线归档 |
| R0 | 原合法 identity CALL 的真实红例，失败日志不覆盖 |
| R1 | identity、多层、同 callee 并列/连续调用、错结果和多出口 |
| R2 | N/R 反排、CompletionResult 与 landing 序号、分域状态、内部新版本导出 |
| R3 | source 重执行、未知/递归/无 terminal/预算、guard、frame 隔离反例 |
| V | 独立源码复审；冻结所有作者后统一受影响 focused；源码/历史 fixture 指纹 |
| A | 如实报告已实现范围与未实现项，独立 WIP commit/push，原 16 组继续 OPEN |

先必要小定向，再一次统一受影响 focused；不得称为组件/full，也不重新运行历史
5822 full。所有新证据写入 model_call_returns/，首败及失败尝试分别保留。
代码或验收发现模型不充分时先补本轮进展说明，不能静默缩减计划或改历史 oracle。

## 4. 后续

此连接成立后再定义异常类别 matcher 的独立 packet/handler/自身 N/R/branch 合同，
然后回到原 P4 全部 16 组、P5 和 M2 的既定建模验收。本轮不把方法 lookup RAISE
当 AttributeError，不把 returned Reference 当纯函数或缓存许可。
