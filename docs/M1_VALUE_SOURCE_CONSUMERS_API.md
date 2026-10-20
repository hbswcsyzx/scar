# 条件值来源：接口与证据边界

依据[冻结计划](M1_VALUE_SOURCE_CONSUMERS_PLAN.md)。五类实体没有增加；Program27 /
Execution8没有迁移。新查询建立局部证明图，不写canonical图、不合并identity。

## 三个不同问题

| 查询 | 问题 | 不代表什么 |
| --- | --- | --- |
| 原 `pair` / `copy_recipe` | 两端是否有原copy共同祖先 | 不穿越可变槽的历史 |
| `stored_value_sources(site, occurrence)` | 这一次own load的槽值来自哪个原store payload | 不接通任意上层消费者 |
| `value_source_pair(source, target)` | 两个准确实际值能否经原copy和条件stored边追到共同来源 | 不证明对象内容恒定、纯度、native identity或可重写 |

公开入口在 `ExecutionIndex`；source/target必须是现有准确ValueOccurrenceID，
budget为正整数。每次外部调用使用fresh content context，最终一次deepcopy。
source_value/target_value始终是所询两端，common_source是共同来源ID；不能将
其中的source_value误解成“系统从全部store中选择的一个payload”。

## 多边证明图

每个实际值可以同时有原copy边和 `DECLARED_STORED_VALUE` 边。先尝试独立原copy
证明；必要时在所有已达值上保留条件边。不是只在copy链末端找load，也不是
`copy_recipe or projection`。visited与predecessor保每侧独立路径；循环本身
不是证明。实际存储来源查询不接受expected source，不能按期望结果反选写入。

`support`保被选中路径的recipes；`projections`保探索到的独立读取收据。
`conditional_stored_source`只在成功路径实际使用stored边时为True。
`binding_kind=CONDITIONAL_STORED_VALUE_SOURCE`不能改称ordinary copy。
只有先找到真实共同来源才比较两端及所选边兼容性。无关owner不是全局冲突，
已存在的原copy硬冲突也不能靠stored或identity分支救回。

## Own load定位

普通结果核本次producer和原OperationResult slot；INVOKE核本visit的incoming
transfer、原BlockArgument位置、edge上对应的CompletionResult index和选中NORMAL。
forwarded Use / SavedInput /旧carrier不等于本次own result。已识别但缺采保
Unknown收据，不借兄弟调用、另一个loop visit或另一个successor。

当前规范要求每个INVOKE完成进入private落点，多个调用不能直接共享own
CompletionResult落点。跨调用汇合使用各自private landing→普通CFG转发→共同
consumer；普通join自身不是READ，查询沿原copy回到实际被选中的own result。

## 有界与递归

读取投影缓存属于同一shared query，键含fresh context与准确target occurrence。
查找、索引、路径和兼容检查计同一预算；库存先保留。ACTIVE阻止递归依赖自证，
cycle依赖产生的临时失败不固化缓存。显式深度界触发共享分析截断；不以
RecursionError作为控制流。截断后缓存不能恢复True，也不能授权成功前缀。

## 既有消费者

原stored地址匹配使用通用来源，因此owner/key经过已证明load时无需伪造Ref
precision或identity。body history保原ordinary True/False；只在None时试独立
条件来源，并保ordinary_binding与stored_source_binding。其余scoped identity /
native projection仍有独立作用与条件，不因局部来源成立而跳过整历史的检查。

当前constructor own新R不是其pre-owned输入。可展开的真实Region能表达allocate
→own R→R-owned store→return及全状态；不可展开native保持边界。缺失的Drive
owner→Create handle、opaque/RW与自动source/native恢复不会由本查询凭空补齐。

验收状态以[限定验收](M1_VALUE_SOURCE_CONSUMERS_ACCEPTANCE.md)为准；本文件描述
接口和模型边界，不是whole-program完成、优化或性能证明。
