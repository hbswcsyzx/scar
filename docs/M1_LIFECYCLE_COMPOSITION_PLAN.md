# D2.4：生命周期与清理组合、公开事实范围

实施基线：`fdf9d0d37ab043db297f095bfafa685b32b0b058`（D2.3 已验收）。
本门仅完成已有 C0/C1/C2B/D1/D2 类型的组合验收及查询范围；不新增
detector、backend、source lowerer、Tensor tracer 或 LeWM 性能实验。

## 1. 为什么需要本门

Operation、Value、StateLocation、Region、Resource 的含义保持不变。
本门检查的是它们的连接：终结来源须来自实际 body frontier，清理必须读写本点
当前状态，pending completion 和 saved handled context 必须沿各自控制端口转发。
F 是条件性的终结历史，P 是依赖当前状态的会话谓词；未知清理可保留 F 并使 P
失效。二者都不证明 native 适用、对象已释放、资源 ready 或可以变换。

公开查询脱离索引后仍须携带原声明、原 DriverInterface/rule、确切操作与
before/after/实际 successor index，避免条件事实在传播中被误当成运行时证明。
scope 的 applicability 始终为 UNKNOWN，不能由 caller 填写 verified。

## 2. 有限组合与验收节点

| 节点 | 验收内容 | 明确边界 |
| --- | --- | --- |
| A：body 内真实清理 | 复用真实 suspend/cleanup/invoke body；每个实际 Return/Raise 私有首 commit 后接 session 和 release，保留 helper 的 NORMAL/RAISE 与部分后态。 | 手工通用 IR fixture，不是源程序自动恢复。 |
| B：driver 内 active cleanup | 两条真实 body 完成分别构造 pending，进入共享 cleanup；Enter 后 release 或真实 helper，Resume/Replace 各自恢复；pending/context 不进入 helper 调用参数。 | scope 直接归属、状态 SSA、C1 栈均由原 validator 校验，不新增第二状态机。 |
| 反例 | 未完成或错误 owner、旧状态、丢失 RAISE、pending/context escape、清理后的旧 P；source/reference 与真正边精确对应。 | 不把缺失谓词当成原程序非法，不把回调当成无副作用。 |
| 公开面 | frozen scope/point、原对象与 Use、真实 NORMAL index；旧 v11 无 scope，v12/13 只有声明范围，v14 才有实际新表能力。 | derived 与 verified 分开，schema 不升级。 |
| 兼容与复审 | v14 golden 从不可变 D2.3 提交生成；v1–v13 字节保持；交叉复核最终源指纹和有限路径矩阵。 | 不用当前 encoder 自己生成自己的历史期望。 |
| 冻结回归 | 组件通过后 clean 实现提交，只做一次全仓；运行中不改源/文档、不另跑测试，观察超时继续同一进程。 | 时长仅为测试成本，不是 LeWM wall-clock。 |
| 归档 | 原命令/失败/修正、逐文件 SHA、验收报告、保护仓库检查、独立版本和推送。 | D2.4 通过不表示 D3、完整 C2 或 M0–M2 已完成。 |

## 3. 分工及后续停止点

根代理负责 A、历史兼容、组件门和归档；独立代理负责 B；另一代理负责公开面。
先各自小规模运行，再交叉只读审查，最后冻结回归。发现矛盾时先保留具体反例，
只修通用模型或错误 fixture，不为 LeWM 特判。

D2.4 后仍按第一阶段矩阵补资源实例/work/ready、selector、literal、
occurrence/denotation/provenance 接口和构造协议守恒。第一阶段全部模型类型与
组合验收完成后，先向用户解释并停在约定边界；自动源码恢复与运行时匹配各按
后续 M3/M4 验收。
