# 条件值来源消费者：限定验收

2026-10-20。基线 `fff1895fd3abc312409b9b95d40affa9b2c06f86`；
[冻结计划](M1_VALUE_SOURCE_CONSUMERS_PLAN.md)、[实际进展](M1_VALUE_SOURCE_CONSUMERS_PROGRESS.md)、
[接口](M1_VALUE_SOURCE_CONSUMERS_API.md)、[后续原门](M1_VALUE_SOURCE_CONSUMERS_NEXT_GATE.md)。

## Implemented / Verified

五类实体仍Operation / Value / StateLocation / Region / Resource。新
`ExecutionIndex.value_source_pair`以准确实际两端建立query-local多边证明图，
保原copy与条件stored边并存；不写copy表、roots、identity union或第二份heap。
原stored地址匹配可用已证明load的owner/key；body普通None后有独立条件分支，
原普通True/False与独立identity/native条件保留。

冻结后一次26模块相关选集 **292 PASS / 0 FAIL / 0 ERROR / 0 SKIP**，其中
21新增、271既有。pytest318.32秒、wrapper319.10433820448816秒。917个指纹输入
前后稳定，SHA `51da7700c5d9f29c1619ce8085c1c20102f98789eb768605c8d00802e9dbbbd5`。
此前2304个已知focused case作为原义务保留，不声称全部在本门重跑或全仓通过。
其中271个本门复验，新增21后目录2325；其余2033个本门未重跑，账本保其原义务。
旧tests/fixtures全部逐字节保留，Program27/Execution8无迁移；原pair/copy源码
也不改。细目由归档checkpoint/case-catalog机械核验。

| 验收项 | 实际范围 |
| --- | --- |
| 两层payload | P→store/load X→store/load Y，上层追到P，保两份stored支持，原ordinary仍None |
| loaded owner | 不补produced Ref precision/identity而定位真实槽 |
| 并行来源 | getter own结果可独立沿原copy或stored边，不丢边、不推全局P/Q identity |
| 调用与汇合 | private N/R→普通join、当前call/loop occurrence、所选slot，转发值不冒充own result |
| 保守失败 | 缺本实例Use/state/association/声明、覆盖写、opaque、tiny budget，不借完整兄弟或成功前缀 |
| cache/cycle/depth | query-local、截断不复活、ACTIVE不自证；实际未来owner循环后独立seeded读取仍可证明 |
| 既有consumer | 私有body_pair薄分支接线通过；既有公开历史/状态区间回归另列在相关选集中 |

默认深度界32在真实40层owner依赖上额外实测：最终同源码689计费后截断，None /
cursor / 40Read+40Write库存及公开detached复制均保留，无RecursionError。
这个探针和测试耗时不是性能优化结果。

## Rejected / 修复记录

首轮新fixture非法共用own completion落点，第二轮新arm漏全state参数/读旧state，
均在来源查询前被已有验证拒绝；各45 PASS/1 FAIL。仅修两NEW文件，21case身份
与原验证保持，随后该节点单独PASS，再全选集292 PASS。原失败源码、命令、
JUnit、日志保留。G0另有归档脚本JSON序列化失败，修仅其dataclass报告写出，
不算目标运行或模型失败。独立最终七文件审查无未决阻塞。

## 不能据此宣称的结论

这是供采模型条件下的值来源证明，不是自动源码/native恢复，也不证明对象内容
稳定、tensor数值恒定、纯度、可重写或优化收益。body新测试只证明薄分支；没有
BodyStateCondition/Drive/F整链，不算公开F19整历史成功。constructor own新R
仍需真实Region allocate/init/return或准确native边界，不能造future输入。

F19第1项/整族、原F19/F20/F22/F24/X25/X26/X27七族、P4 component/full、
P5、M2原113构造/196字段和第一阶段继续开放。九族/await A–H的旧限定接受
保持。没有新detector/backend/LeWM规则、自动whole-LeWM图、可信TRANSFORM
或新加速比。接下来返回原F19连接与组合，不扩大同类来源工具箱。
