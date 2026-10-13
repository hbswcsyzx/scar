# N1 验收：程序类型与依赖核心

日期：2026-10-13。结论：**N1 范围通过**。
实现版本：`8179cca0b880f8e8e24607d7181587fbd85baad2`。

## 实际完成

- `scar.ir.program` 实现值、状态位置、操作、区域及内部控制块；值细分为
  DataValue、ReferenceValue、StateVersionValue，ID 与旧图保持独立。
- 精确 UseID 保留重复操作数和不同调用位置；参数、分支边、调用和退出接口
  不再只用名称或 slot 代替值与状态连接。
- 校验路径可用性、分支支配关系、循环携带状态、当前状态版本、读写范围、
  引用目标、同步顺序和完整的正常/异常状态出口。
- 严格 JSON 解码后重验全图。可用 `scar check-program graph.json` 读取和
  检查图，返回 WELL_FORMED 或 INVALID；不执行输入，不批准变换。

## 真实验收结果

| 检查 | 结果 | 范围 |
| --- | --- | --- |
| `gates/n1.json` | **93 passed**，2.439 秒 | 逐条件绑定测试，运行时源码未变 |
| 整仓回归 | **1,157 passed**，101.32 秒 | 两条既有警告，无失败或跳过 |
| CLI 示例 | WELL_FORMED | 1 区域、3 块、7 操作、14 值、2 状态位置、20 uses |
| LeWM 工作区 | 干净 | 本轮没有执行或改写 LeWM |

Python 为 conda lewm 环境中的 3.14.7。上述时间为测试耗时，不是工作负载
性能或优化加速比。完整机器记录：

- `artifacts/reports/gates/n1-verified.json`：实现 revision、全部被测文件哈希、
  逐条件测试案例及源文件在运行期间不变的检查。
- `artifacts/reports/gates/n1-acceptance.json`：总体验收范围、环境和 fixture 计数。
- `artifacts/reports/gates/n1-full-regression.xml`：完整回归结果。
- `artifacts/reports/gates/n1-example-check.json`：实际 CLI 输出。

## 失败与修复

独立反例首次得到 **22 passed / 2 failed**，发现：

1. callee 实际读取状态，caller 却可用 STATE_ORDER 冒充仅顺序依赖。
2. call 可以包含未绑定任何形参的额外 use，导致实际输入与接口不一致。

修复要求每个 call use 恰绑定一个参数，N1 call/control 状态端口保留
STATE_CONTENT；只有明确全覆盖写能使用 STATE_ORDER。补充了分支、正常返回
和异常返回的同类反例，最终独立反例 **27 passed**，也包含在正式 93 项中。

失败前实现与反例文件的 SHA256 保存在 `n1-development-findings.json`；
原始失败与修复后的 XML 都存入 artifacts/reports/gates，未把失败当成通过。

## 边界和下一步

四个完整程序例子由手工 IR fixture 构造：分支状态读写/日志/异常、循环状态、
共享函数体的独立调用、载荷名称无关的编码写入。它们验证连接与声明一致性，
不证明自动恢复了 Python，也不证明实际库实现满足 effects_complete 声明。

N1 暂不覆盖一般异常 invoke、动态位置生命周期、GPU ready 和 autograd。
没有新 backend、LeWM 变换或加速比。

下一步按 [N2_IMPLEMENTATION_PLAN.md](N2_IMPLEMENTATION_PLAN.md) 将既有源码、
算子和 CFG 记录转换为新图。先补真实的参数、逐路径合流与调用绑定，不增加
detector，不以 Operation.label 或函数名称猜测计算规则。
