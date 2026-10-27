# Async close chains：模型与查询接口

本门仍使用 Operation / Value / StateLocation / Region / Resource。没有增加
执行图实体、schema、detector 或 backend；LeWM不出现在任何判定规则中。

## 数据与控制是两种连接

一个异常包经过 matcher、bool、分支后，handler可以构造另一个异常包。
它们之间有控制依赖；只有各段真实传值边才有copy关系：

```
原packet → matcher input
matcher own bool → BRANCH condition
选中True臂 → constructor
constructor own NORMAL exception → packet.exception → 新packet → host
constructor own RAISE packet → host
```

新旧packet不合并身份。False臂仍需传播其当前原packet。constructor的N/R槽、
packet定义和host的连接分别核对；同类型、可达或命名相近均不足以证明copy。
固定matcher类别/constructor的native解释仍然是独立的适用条件，没有获得运行时
验证。一个结构有效的未解释call可以存在于图中，但不能据此授予转换权限。

## 静态公开查询

`ProgramIndex.handled_completion(source, HostTerminal(...), budget=4096)`
返回原记录上的派生收据。不是另一张producer图，不执行目标程序。

- `applicable`：原source的精确所选完成能否到达这个terminal；ownN/R互斥。
- `match`：完整所供路径上的复制段和handler替换结构是否得到支持。
- `receipts`：准确choices、packet来源与定义、matcher输入、own bool、实际选边、
  constructor、own结果槽、当前packet来源、host绑定和每段独立binding。
- `gaps`：native解释、缺的端口/关系及未支持的嵌套边界；不等于已知反证。
- `budget` / `cursor`：同一次派生的共享预算与截断位置。

明确矛盾保持False。缺独立期望的构造结果不等于已知错包：如改变实际
PacketDefinition输入但没有声明其独立期望，构造来源证明应为None。预算截断
不能产生True，也不能抹掉同terminal已经建立的False。

## 动态公开查询

`ExecutionIndex.drive_execution(actual_drive, budget=...)`既有接口中的
`session.hosts[].handled_completion`投影上述收据到本次实际suffix，保留准确的
matcher/branch/constructor occurrence、selected edge、current value和分段copy。

派生发生在公开查询期间，复用同一个shared budget，不在准备阶段另开默认百万
预算。原记录和actual suffix索引可准备；原choices、receipt、slots、adapter和
绑定扫描均在派生预算内。query context与证明cache不跨查询复用。

独立使用BlockArgument的实际BlockVisit，不用同site的另一次调用补缺；当前薄
投影遇同static site重复visit保守保留未证明，不摊平循环。缺actual body outcome
不解引用候选、不借完整兄弟补证。预算不足保原hosts/source/target库存，但撤掉
支持结论；返回对象与准备缓存分离。

## 请求完成、F与释放

ASYNC_YIELD使本请求COMPLETE；AWAIT保HOLD；真正BodyReturn/BodyRaise才可种F。
非法close-yield的请求完成发生在错误构造前，因此错误构造自身RAISE也不能
撤销已发生的该点COMPLETE，更不能把仍挂起的body变成F。

TerminalFrameRelease只表示真实F后的窄引用释放边界。UNKNOWN副作用、可能不
终止、释放不保证都保持；它不是GPU/CPU allocation已物理free的证明。

## 明确边界

本门供给的图与capture是模型压力测试，不是自动从LeWM恢复的程序。既有
CPython3.14.7固定源码和22调用旧探针作为参考，不把fixture执行算native实测。
初始S=None是主链前提；任意非None S拒绝、native ITER/active标记的全部路径及
未选opaque ITER边界未宣称展开。source/runtime identity/native interpretation/
transformation权限均保持False。整个M0–M2与自动建图完成度由原阶段门另行验收。
