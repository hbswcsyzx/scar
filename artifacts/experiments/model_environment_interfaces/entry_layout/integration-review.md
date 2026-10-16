# Function environment integration review

日期：2026-10-16。**PASS（本次声明/结构范围内无阻断发现）。**
只读审查，不修改产品、测试或共享文档；下列源码是工作树未提交实现，不能只用
HEAD 声称全部被固定。全 M1、来源自动恢复及运行绑定均未因此完成。

## 1. 关键顺序问题

`ProgramIndex.environment_call` 先用 callee 的实际 entry.arguments 与现有
call_arguments/invoke_arguments 逐位置对齐，建立 `formal ValueID -> UseSite`。
随后按 EnvironmentMember.reference 和 FunctionEntryLayout.parameters 的
ValueID 查表。因此逻辑形参顺序不必等于物理 entry 顺序，环境/状态不必连续
成组；不会把第一个 logical formal 强行绑定第一个 physical argument。

对应 validator 用完整集合分区，而不是用前缀个数切割参数。环境成员和显式
形参都必须是本 Region entry 的 ReferenceValue；StateVersion 参数不成为
Python formal。原始 BlockArgument 的 block/index/ValueID 一致性仍由 core
和环境 validator 检查。每个 environment 必须且仅有一份 layout。

对这个具体风险复验了已存在的两种调用正例：direct call 和 INVOKE。fixture
同时逆置 logical formal 顺序，并把 physical entry 混排为环境/形参/状态/
captured cell。查询精确返回对应 UseID，且状态版本未被重排丢失。

```bash
PYTHONPATH=. PYTHONDONTWRITEBYTECODE=1 \
 /home/zyf/miniconda3/envs/lewm/bin/python -m pytest -q \
 tests/unit/test_program_environments.py::test_entry_physical_order_and_logical_parameter_order_are_independent
```

实测：**2 passed，exit 0**；原输出在 `review-order-probe.log`。这是复验已有
结构 fixture，不是自动来源正例，也不是运行真实 Python 函数绑定的验证。
未跑整仓、LeWM、GPU 或新语言实验。

## 2. 其余连接检查

- **Use 身份保留：** query 返回实际 operation-owned UseSite；各环境端口
  即使指向同一 actual Value，仍保留不同 use。没有按对象相同或字符串名字散连。
- **状态推进：** query 由当前 call 的 actual state arguments 按 LocationID
  取值；不从第一次调用/捕获快照复用状态。共同 validator 校验 current state、
  STATE_CONTENT、callee arity/types、reference targets/selector 及两条完成边。
- **共享状态域：** member.locations 是声明的必要域，不是完整效果集合；
  各成员共享 coarse world 合法。已知 reference targets 与域矛盾会拒绝，
  targets=None 不产生 disjoint 或无依赖结论。未声明域不代表 NONE。
- **builtins/闭包：** BUILTINS_NAMESPACE 是独立入口 reference，不从当前
  globals['__builtins__'] 合成；捕获的是 cell identity，对内容的读仍依赖
  规范 state。cell 空内容不是 None，也未由本批伪造内容冻结规则。
- **codec：** v5 同时承载 environments/function_entries；旧 v1–v4 严格拒绝
  新字段并按旧字段集合输出。新表只加在顶层，没有向旧 Operation/Region wire
  注入新字段。孤立 layout、缺 layout、伪装无环境的 v5 都不能绕过 graph validation。
- **query 权限：** DECLARED / NO_DECLARED_CALLEE / NO_DECLARED_ENVIRONMENT
  明确分开。declared callee 是现 core 的已声明边，不是此次新增的 runtime
  target 证据；缺声明不被解释为“没有环境”。
- **CLI 权限：** WELL_FORMED 的 scope 仍是 declared graph structure and
  dependencies；environment_realization_verified、environment_extraction_verified、
  python_signature_binding_verified、runtime_callable_verified 均为 False，
  source_recovery/transformation_authorized 也未升级。

## 3. 必须继续保留的验收边界

本次没有证明实际 callable 的 __code__/globals/builtins/defaults/cells 符合
这些声明，没有验证 cell_slot/position 与真实 co_freevars 对齐，也没有用
source signature 证明 layout.parameters 完整顺序。这些是尚未实现的来源/
环境提取和运行对应义务；当前源码与 query/CLI 已明确声明，不构成隐藏 falseproof。

入口端口分区校验不代表全部函数行为已表达。异常/恢复协议、frame 规则以及
完整 typed state/resource 模型仍按各自阶段验收。没有必要为本批声明 record
补写全语言解释器或把模板 graph 称为自动构图。

## 4. 当前审查快照

工作树：`/tmp/scar-structured-model-280qf4mi`。
HEAD：`f80af0fedb20c20121707ee1aaf494844b7dcea5`（存在未提交实现，以文件 SHA 为准）。

| 文件 | SHA256 |
| --- | --- |
| `scar/ir/program/environment_validation.py` | `a63089081e0c152f3519b8118310cdca62dd502cd000cb212aba71e04ed38d3f` |
| `scar/ir/program/queries.py` | `749b9ce7b6234f13cf804737f8151901869bb3faa95f4fadf431f66bbb7c0d55` |
| `scar/ir/program/codec.py` | `c0cb4c5b7f359b46db3b898b35b19d79f6bdcbfb7a36313ac8ef931a41d9ce9c` |
| `scar/cli.py` | `a41a45411338b7d15f23630578af3329514ee63b835df8d2f99e215130488790` |
| `scar/ir/program/validation.py` | `3868b74b773593a1cf39a43d5819efc588fd55151d0af0e11683dfff56ddf03f` |
| `scar/ir/program/model.py` | `5a989b8f07cb42003bee26b1c7757b5f61b6b0e3973807b49347ccd5785bc851` |
| `scar/ir/program/environments.py` | `bc46be047812a9ca992ed920014b7d66dcbafef7b36397f5267ad7559f6bbf4f` |
| `scar/ir/program/functions.py` | `8410a92b3e9645fd765a6234aa8bf70816e265ad7b8c670b7adc94f0661cb026` |
| `tests/unit/test_program_environments.py` | `eb20b9fd74733a816656096347decb897e33b45779e16c6f28b055f829ab4d01` |

结论仅适用于上述快照和范围；未发现本次必须修正的错误绑定或权限提升。
