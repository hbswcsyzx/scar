# M2 原 G1—G5 关闭复审；另列新 G6

2026-10-16。仅审查本轮文档修改；原 `field_coverage.json` 的 113/196、184 COVERED /
12 GAP 与原报告保持不动。该历史快照不能被本文件改写成原来全部通过。
未修改 tracked 规范/产品/测试，未重跑已有 runtime/目标/长测试。

## 原五项：文字规则均已关闭

| 原项 | 修订后精确位置 | 关闭依据 |
| --- | --- | --- |
| G1 AnnAssign | 数据 §8.2 | simple 0/1、括号Name不收集；无RHS Name不赋None，Attribute/Subscript仍求owner/key但不最终get/set；scope与setup分开。 |
| G2 Not 上下文 | 数据 §10.1、控制 §0.2 | 明确V(Not e)与T(Not e)；T对调真假continuations；保留值上下文两次/条件一次的真实区别，不给truth cache权限。 |
| G3 target ctx | 数据 §11 | List/Tuple Load构造、Store解包、Del递归删除分开；Starred合法Load/Store与Del编译禁止；失败/部分更新有依赖。 |
| G4 Expr/Pass/TypeIgnore | 数据 §2.1、§2.1.1 | Expr普通discard与interactive display分开，临时引用释放/异常/挂起明确；Pass Fallthrough与source保留；TypeIgnore.lineno/tag逐字段metadata归属。还明确docstring不是每次body求值。 |
| G5 class header | 数据 §5 → §9 | bases位置/星号准备与keywords分组、header跨字段顺序和失败端口明确；复用已有参数准备接口，不靠AST顺序。 |

新增 class/free Name 规则也修正了原过强简化：class prepared namespace 可先于
enclosing cell；method 不捕获 class namespace。现有独立 JSON 给出 observed=9 与
LOAD_FROM_DICT_OR_DEREF，规则要求 symtable/dis witness，不将所有 free 直接视为cell。
本次没有重跑该探针，也不将单例升级为所有 lookup 已自动恢复。

## 新 G6：Call 单星号 iterable 的实际展开阶段（未关闭）

**位置：数据 §9 开头与 Call.args 行的“立即迭代”主张；关联 Starred.value、
Call.keywords 的跨字段执行/失败顺序。** 这是本次新增 finding，不撤回旧 G1—G5
对应补充已存在的事实，也不要求推倒现有五类模型。

旧 definition probe 的 `star_expr()` 返回 list，`star-item` 事件来自 list 创建时的
元素表达式，没有自定义 `__iter__`；它证明 star 表达式先求，不证明迭代立即发生。

经 root 明确授权，新增独立 CPython 3.14.7 小 probe，覆盖 4 种 call 形态 × 正常/
iter失败/next失败/keyword失败，共16个记录；没有 import SCAR/Torch 或执行目标。
脚本和完整失败路径为 `call_star_probe.py/.json`，exit 0。

| 形态 | 正常时真实事件（简写） |
| --- | --- |
| `fn(*star(), named=kw())` | star_expr → kw → iter → next → body |
| `fn(0, *star(), named=kw())` | star_expr → iter → next → kw → body |
| `fn(*star(), 0, named=kw())` | star_expr → iter → next → kw → body |
| `fn(*star('a'), *star('b'), named=kw())` | star_a → iter_a → next_a → star_b → iter_b → next_b → kw → body |

single-star 的 iter/next 失败时 keyword 已执行；keyword 失败时 iterable 还没有进入。
其余形态在本 probe 的第一个 iter/next 失败时 keyword 未执行。若按“每个*立即
迭代”删除/前移操作或接异常后态，会改变真实副作用与失败先后。

此前只读 compile/dis 记录也保存为 `call-star-compile-inspection.json`：single-star
没有预先 LIST_EXTEND，在 keyword BUILD_MAP 后才 CALL_FUNCTION_EX；有prefix时
先 LIST_EXTEND/转换tuple，再求keyword。样本函数体未执行。官方对应3.14.7
[`Python/bytecodes.c`](https://github.com/python/cpython/blob/v3.14.7/Python/bytecodes.c)
中的 `_MAKE_CALLARGS_A_TUPLE` 在 CALL_FUNCTION_EX 内按需转换 tuple，与该区别一致。
最初源码查询使用过窄字符串，`cpython-call-ex-source.json` 的 matches为空；这不是
“源码没有转换”的证据，不作为支持结论。

**关闭要求**：将 star expression 求值与 iterable materialization 分为不同步骤，
按实际3.14 compiler/bytecode witness选择展开位置；别将一个优化形态推为所有calls。
保持每一步有序 Uses、状态/失败出口；keyword发生后才迭代失败时，保留keyword的
后态。确认 class header 的复用指向适用参数准备规则，不由此统一所有call形态。

本复审结论：**原五项可以关闭；新 G6 仍 GAP；不宣布 M2 全门通过、M1 实现完成
或 M3 自动覆盖。** 修订后文档 SHA 独立保存在 `document-hashes.json`，不得用本次
关闭覆盖旧失败快照。

## G6 修订后限定关闭

root 随后修订数据 §9，将 star expression 与 iterator materialization 拆开，明确
四种 compiler 路线及16例的正常/失败影响；§11 Starred Load 改为引用所属协议，
不再宣称立即迭代。只读复核当前文字与现有 `call_star_probe.json`、compile/dis
见证一致，没有重跑样本或其他实验。

class header §5 仍明确其 bases/starred 准备在 keywords 前，这与含隐式
build_class body/name prefix 的构造路线一致；不应反向推广为普通 single-star Call
也必须这样。该节已明确header自己的顺序，复用§9不会覆盖其适用条件。

**G6 在这项已确认问题的范围内可关闭。原 G1—G5 关闭结论保持。** 仍不宣称对
所有调用适配器、Python API 或整个 M2 的穷尽验证，不宣称 M1/M3 实现通过。新
hash 保存为 `document-hashes.G6-closed.json`；前面的发现、失败及原184/12审计
保持原样，供版本化审查。
